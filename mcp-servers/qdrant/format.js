/**
 * Response formatting for memory_search — token-efficiency layer
 * (2026-07-04, eng-blog backlog #2).
 *
 * Two verbosity modes:
 *   concise (default) — content-first: path/lines, ONE effective relevance
 *     score per hit, snippet/context, and only non-empty metadata. Envelope
 *     keeps the decision-relevant signals (count, search_mode, temporal
 *     rewrite transparency, no_strong_match + warning) and drops static
 *     config echo (provider/model/collection/recency weights). Compact JSON.
 *   detailed — the full pipeline view: every per-hit score (dense cosine,
 *     RRF fused, rerank logit, recency, final), config metadata, pretty
 *     -printed. For debugging retrieval, threshold calibration, evals.
 *
 * Pure functions, no I/O — unit-tested in test/format.test.js.
 */

/** Round a number for output; passes through null/undefined untouched. */
export function roundScore(v, dp = 3) {
  return typeof v === 'number' && Number.isFinite(v) ? Number(v.toFixed(dp)) : v;
}

/**
 * The one score concise mode reports per hit, in order of authority:
 * finalScore (rank actually used, incl. recency) > rerankScore (calibrated
 * relevance) > dense cosine > RRF fused. Null only if all are null
 * (shouldn't happen in practice).
 */
export function effectiveScore(r) {
  if (r.finalScore !== null && r.finalScore !== undefined) return r.finalScore;
  if (r.rerankScore !== null && r.rerankScore !== undefined) return r.rerankScore;
  if (r.score !== null && r.score !== undefined) return r.score;
  return r.fusedScore ?? null;
}

// Default per-hit snippet cap in concise mode. Measured 2026-07-04 on the
// live corpus: most chunks are 0.2-3.5K chars, but `sessions` / long-email
// chunks blow up to 15-55K chars EACH (a single 54K snippet ~= 13K tokens),
// so one memory_search could cost ~40K tokens. 2000 keeps the large majority
// of hits whole. This truncates the RESPONSE only, never the archive
// (Behavioral Rule #1 is about storage): the marker tells the agent exactly
// how to pull the full text via memory_get path + lines.
export const DEFAULT_SNIPPET_CHARS = 2000;

/** Cap text at maxChars, appending an actionable how-to-get-the-rest marker. */
export function truncateSnippet(text, maxChars) {
  if (!maxChars || !text || text.length <= maxChars) return text;
  return (
    text.slice(0, maxChars) +
    `\n…[+${text.length - maxChars} chars truncated — memory_get this path with its line range for the full text, or re-search with detail:"detailed"]`
  );
}

/** Concise per-hit shape: content + location + one score; empty fields dropped. */
export function conciseResult(r, maxSnippetChars = DEFAULT_SNIPPET_CHARS) {
  const out = {
    path: r.path,
    lines: `${r.startLine}-${r.endLine}`,
    score: roundScore(effectiveScore(r)),
  };
  if (r.source) out.source = r.source;
  if (r.date) out.date = r.date;
  if (r.title) out.title = r.title;
  if (r.subject) out.subject = r.subject;
  if (r.participants) out.participants = r.participants;
  if (r.context) out.context = r.context;
  if (r.snippet) out.snippet = truncateSnippet(r.snippet, maxSnippetChars);
  return out;
}

/** Detailed per-hit shape: everything, with float noise rounded. */
export function detailedResult(r) {
  return {
    ...r,
    score: roundScore(r.score),
    fusedScore: roundScore(r.fusedScore, 6), // RRF scores are small; keep precision
    rerankScore: roundScore(r.rerankScore),
    recencyScore: roundScore(r.recencyScore),
    finalScore: roundScore(r.finalScore),
  };
}

/**
 * Render the full internal response object as the tool's text payload.
 * `response` is the complete (detailed-shape) object built by memory_search.
 */
export function formatSearchResponse(response, detail = 'concise', maxSnippetChars = DEFAULT_SNIPPET_CHARS) {
  if (detail === 'detailed') {
    const out = { ...response, results: (response.results || []).map(detailedResult) };
    return JSON.stringify(out, null, 2);
  }
  const out = {
    results: (response.results || []).map((r) => conciseResult(r, maxSnippetChars)),
    count: response.count,
    search_mode: response.search_mode,
  };
  if (response.rewritten_query !== undefined) out.rewritten_query = response.rewritten_query;
  if (response.parsed_range !== undefined) out.parsed_range = response.parsed_range;
  out.no_strong_match = response.no_strong_match;
  if (response.warning !== undefined) out.warning = response.warning;
  return JSON.stringify(out);
}
