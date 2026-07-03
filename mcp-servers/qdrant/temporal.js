/**
 * Deterministic temporal query rewriting for memory_search (RAG item 5, 2026-07-02).
 *
 * Callers write queries like "what did we discuss about the tunnel last week".
 * The temporal phrase just muddies the embedding; the date intent belongs in
 * the payload date filter instead. parseTemporal() detects an UNAMBIGUOUS
 * temporal phrase at the very START or very END of the query, strips it from
 * the text to embed, and returns the equivalent dateFrom/dateTo.
 *
 * Design rules (conservative by construction — a wrong rewrite is worse than
 * no rewrite):
 *   - Pure deterministic parse. No LLM call. Clock = system time resolved in
 *     America/New_York (the physical host's timezone).
 *   - Leading/trailing phrases ONLY. Mid-sentence temporal words are never
 *     rewritten ("what did we decide last week about the tunnel" -> untouched).
 *     Leading phrases additionally require an explicit comma/colon
 *     ("Yesterday, what did I promise Pete") — a leading temporal word
 *     followed by a bare space is usually adverbial ("recently updated
 *     files list") and stays untouched.
 *   - Possessives never match ("last week's plan file" -> untouched): the
 *     trailing anchor requires end-of-query and the leading anchor requires
 *     a comma/space after the phrase, so the 's blocks both.
 *   - Month names require a preposition (in/during/from/throughout June).
 *     Adjectival months ("the June report") are never rewritten.
 *   - If stripping the phrase leaves fewer than 3 word characters, the whole
 *     query was temporal — don't rewrite (nothing left to embed).
 *   - "recently"/"lately" = the last 14 days.
 *   - Bare month/weekday names resolve to the MOST RECENT PAST occurrence
 *     ("in August" asked in July 2026 -> August 2025).
 *   - dateFrom is a plain YYYY-MM-DD (midnight UTC in Qdrant's datetime
 *     index); dateTo gets T23:59:59Z appended so day-precision payload dates
 *     ("2026-06-30") AND timestamped ones ("2026-06-30T19:00:03+00:00") both
 *     fall inside the closed range. The corpus stamps dates in UTC-or-day
 *     precision, so UTC day boundaries are the consistent choice.
 *
 * Also runnable as a CLI (used by tools/librarian/lib/retrieval_eval.py so
 * the eval mirrors production by executing THIS file, not a port):
 *   node temporal.js "<query>" [nowISO]
 * -> {"match":false} or {"match":true,"query":...,"phrase":...,"dateFrom":...,"dateTo":...}
 */

import { pathToFileURL } from 'url';

const DEFAULT_TZ = 'America/New_York';

const MONTHS = {
  january: 1, february: 2, march: 3, april: 4, may: 5, june: 6, july: 7,
  august: 8, september: 9, sept: 9, october: 10, november: 11, december: 12,
  jan: 1, feb: 2, mar: 3, apr: 4, jun: 6, jul: 7, aug: 8, sep: 9,
  oct: 10, nov: 11, dec: 12,
};
const WEEKDAYS = {
  sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6,
};
const MONTH_RE = Object.keys(MONTHS).sort((a, b) => b.length - a.length).join('|');
const WEEKDAY_RE = Object.keys(WEEKDAYS).join('|');

// --- calendar-date helpers (pure y/m/d arithmetic via UTC — DST-proof) ------

function ymdInTz(now, tz) {
  // en-CA formats as YYYY-MM-DD
  const s = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(now);
  const [y, m, d] = s.split('-').map(Number);
  return { y, m, d };
}
const toMs = (t) => Date.UTC(t.y, t.m - 1, t.d);
function fromMs(ms) {
  const d = new Date(ms);
  return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate() };
}
const addDays = (t, n) => fromMs(toMs(t) + n * 86400000);
const dow = (t) => new Date(toMs(t)).getUTCDay(); // 0 = Sunday
const monthEnd = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
const weekMonday = (t) => addDays(t, -((dow(t) + 6) % 7));
const pad = (n) => String(n).padStart(2, '0');
const iso = (t) => `${t.y}-${pad(t.m)}-${pad(t.d)}`;

/** Most recent past month occurrence: "August" asked in July -> last year. */
function resolveMonth(name, yearStr, today) {
  const m = MONTHS[name.toLowerCase()];
  const y = yearStr ? Number(yearStr) : (m <= today.m ? today.y : today.y - 1);
  return { y, m };
}

/** Most recent occurrence of a weekday. allowToday: "on Thursday" asked on a
 *  Thursday means today; "last Thursday" means a week back. */
function lastWeekday(name, today, allowToday) {
  const target = WEEKDAYS[name.toLowerCase()];
  let diff = (dow(today) - target + 7) % 7;
  if (diff === 0 && !allowToday) diff = 7;
  return addDays(today, -diff);
}

/** "since X" start dates. Returns {y,m,d} or null when X isn't a clean date. */
function resolveSince(s, today) {
  s = s.trim().toLowerCase();
  if (s === 'yesterday') return addDays(today, -1);
  if (s === 'this week') return weekMonday(today);
  if (s === 'last week') return addDays(weekMonday(today), -7);
  if (s === 'this month') return { y: today.y, m: today.m, d: 1 };
  if (s === 'last month') {
    const pm = today.m === 1 ? { y: today.y - 1, m: 12 } : { y: today.y, m: today.m - 1 };
    return { y: pm.y, m: pm.m, d: 1 };
  }
  if (WEEKDAYS[s] !== undefined) return lastWeekday(s, today, false);
  let m = new RegExp(`^(${MONTH_RE})(?:\\s+(\\d{1,2})(?:st|nd|rd|th)?)?(?:,?\\s+(\\d{4}))?$`, 'i').exec(s);
  if (m) {
    const { y, m: mon } = resolveMonth(m[1], m[3], today);
    return { y, m: mon, d: m[2] ? Number(m[2]) : 1 };
  }
  m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (m) return { y: Number(m[1]), m: Number(m[2]), d: Number(m[3]) };
  return null;
}

// --- rules -------------------------------------------------------------------
// Each rule: frag (regex fragment, case-insensitive, may contain captures)
// + resolve(groups, today) -> {from, to|null} | null (null = rule doesn't
// apply after all; parsing continues as if it never matched).
// Order matters: "since last week" must hit the since-rule before the plain
// last-week rule would strip just "last week" and corrupt the query.

const RULES = [
  { // since <date-ish>
    frag: `since\\s+([a-z]{3,9} ?\\d{0,2}(?:st|nd|rd|th)?(?:,? ?\\d{4})?|[a-z]+ [a-z]+|\\d{4}-\\d{2}-\\d{2})`,
    resolve: (g, today) => {
      const from = resolveSince(g[1], today);
      return from ? { from, to: null } : null;
    },
  },
  { // N days ago (single day)
    frag: `(?:(\\d{1,3})|a|one)\\s+days?\\s+ago`,
    resolve: (g, today) => {
      const d = addDays(today, -(g[1] ? Number(g[1]) : 1));
      return { from: d, to: d };
    },
  },
  { // N weeks ago (that calendar week, Mon-Sun)
    frag: `(?:(\\d{1,2})|a|one)\\s+weeks?\\s+ago`,
    resolve: (g, today) => {
      const mon = weekMonday(addDays(today, -7 * (g[1] ? Number(g[1]) : 1)));
      return { from: mon, to: addDays(mon, 6) };
    },
  },
  { // (in/over/during) the last/past N days|weeks|months (rolling window)
    frag: `(?:(?:in|over|during|from)\\s+)?(?:the\\s+)?(?:last|past)\\s+(\\d{1,3})\\s+(day|week|month)s?`,
    resolve: (g, today) => {
      const mult = { day: 1, week: 7, month: 30 }[g[2].toLowerCase()];
      return { from: addDays(today, -Number(g[1]) * mult), to: today };
    },
  },
  { // in/during/from/throughout <Month> [year] — preposition REQUIRED
    frag: `(?:in|during|from|throughout)\\s+(?:(?:early|mid|late)[- ])?(${MONTH_RE})(?:\\s+(\\d{4}))?`,
    resolve: (g, today) => {
      const { y, m } = resolveMonth(g[1], g[2], today);
      return { from: { y, m, d: 1 }, to: { y, m, d: monthEnd(y, m) } };
    },
  },
  { // on <Weekday> / last <Weekday> (single day, most recent occurrence)
    frag: `(on|last)\\s+(${WEEKDAY_RE})`,
    resolve: (g, today) => {
      const d = lastWeekday(g[2], today, g[1].toLowerCase() === 'on');
      return { from: d, to: d };
    },
  },
  { // this week (Mon-Sun of the current week)
    frag: `(?:from\\s+)?this\\s+week`,
    resolve: (g, today) => {
      const mon = weekMonday(today);
      return { from: mon, to: addDays(mon, 6) };
    },
  },
  { // last week (Mon-Sun of the previous week)
    frag: `(?:from\\s+)?last\\s+week`,
    resolve: (g, today) => {
      const mon = addDays(weekMonday(today), -7);
      return { from: mon, to: addDays(mon, 6) };
    },
  },
  { // this month
    frag: `(?:from\\s+)?this\\s+month`,
    resolve: (g, today) => ({
      from: { y: today.y, m: today.m, d: 1 },
      to: { y: today.y, m: today.m, d: monthEnd(today.y, today.m) },
    }),
  },
  { // last month (previous calendar month)
    frag: `(?:from\\s+)?last\\s+month`,
    resolve: (g, today) => {
      const y = today.m === 1 ? today.y - 1 : today.y;
      const m = today.m === 1 ? 12 : today.m - 1;
      return { from: { y, m, d: 1 }, to: { y, m, d: monthEnd(y, m) } };
    },
  },
  { // yesterday
    frag: `(?:from\\s+)?yesterday`,
    resolve: (g, today) => {
      const d = addDays(today, -1);
      return { from: d, to: d };
    },
  },
  { // today / this morning|afternoon|evening / tonight
    frag: `(?:from\\s+)?today|this\\s+(?:morning|afternoon|evening)|tonight`,
    resolve: (g, today) => ({ from: today, to: today }),
  },
  { // recently / lately = last 14 days
    frag: `recently|lately|in\\s+the\\s+(?:last|past)\\s+few\\s+days`,
    resolve: (g, today) => ({ from: addDays(today, -14), to: today }),
  },
];

// --- parse -------------------------------------------------------------------

/**
 * @param {string} query   natural-language search query
 * @param {Date}   [now]   clock override (tests / eval determinism)
 * @param {string} [tz]    IANA timezone (default America/New_York)
 * @returns {null | {query: string, phrase: string, dateFrom: string, dateTo?: string}}
 */
export function parseTemporal(query, now = new Date(), tz = DEFAULT_TZ) {
  if (!query || typeof query !== 'string') return null;
  const today = ymdInTz(now, tz);

  for (const rule of RULES) {
    // Trailing: phrase at the very end (preceded by a separator, so a
    // query that IS the phrase never matches — nothing would remain).
    const trail = new RegExp(`[\\s,;:(](${rule.frag})[\\s?!.)]*$`, 'i');
    // Leading: phrase at the very start, followed by an EXPLICIT comma/
    // colon/semicolon ("Yesterday, what did I promise Pete"). Space alone is
    // not enough — leading temporal words followed directly by a verb are
    // usually adverbial ("recently updated files list") and must not rewrite.
    const lead = new RegExp(`^(${rule.frag})[,:;]\\s*`, 'i');

    let phrase = null;
    let rest = null;
    let m = trail.exec(query);
    if (m) {
      phrase = m[1];
      rest = query.slice(0, m.index).trim();
    } else {
      m = lead.exec(query);
      if (m) {
        phrase = m[1];
        rest = query.slice(m[0].length).trim();
      }
    }
    if (phrase === null) continue;

    // Enough non-temporal content must remain to embed.
    if (rest.replace(/[^\p{L}\p{N}]/gu, '').length < 3) continue;

    // Re-run the bare fragment on the phrase to get clean capture groups.
    const groups = new RegExp(`^(?:${rule.frag})$`, 'i').exec(phrase);
    if (!groups) continue;
    const range = rule.resolve(groups, today);
    if (!range) continue; // e.g. "since forever" — not a clean date

    const out = { query: rest, phrase, dateFrom: iso(range.from) };
    if (range.to) out.dateTo = `${iso(range.to)}T23:59:59Z`;
    return out;
  }
  return null;
}

// --- CLI (used by the retrieval eval to run the EXACT production parser) -----

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const q = process.argv[2] || '';
  const nowArg = process.argv[3];
  const res = parseTemporal(q, nowArg ? new Date(nowArg) : new Date());
  process.stdout.write(JSON.stringify(res ? { match: true, ...res } : { match: false }) + '\n');
}
