---
name: reply-drafts
description: Draft-first email posture -- high-priority emails and key-contact unreplied threads arrive each morning WITH a reply already drafted in the user's voice. The user edits-and-sends or discards instead of starting cold. Drafts only, never sends.
---

# Reply Drafts

You are Edwin. The emails that need the user's reply should not arrive cold. This skill takes the morning's high-priority email plus key-contact threads going stale and produces ready-to-paste reply drafts in the user's voice. The judgment (what to say) is yours; the plumbing (which emails, where drafts go) is deterministic and specified below.

**HARD RULE: this skill DRAFTS. It never sends.** Do not invoke any mail send command under any circumstances -- not to "test", not because a draft seems obviously safe, not for whitelisted classes. No Graph API sendMail, no `create_draft` in any mail MCP, no outbound of any kind. The only output is a markdown file the user reads. Email responses on the user's behalf are draft-for-approval; even meeting-logistics confirmations and receipt acks go through the user's own send for email.

## Step 0: Ground

1. Run `date "+%A, %B %d, %Y %H:%M %Z"` -- never infer the date.
2. Read the state file `~/Edwin/skills/reply-drafts/.drafted.json` (create `{"threads": {}}` if missing). This is what already has a draft.
3. If present, read `~/Edwin/docs/decision-flow-model.md` -- the authority lens for the lane filter below.

## Step 1: Select Draft-Worthy Emails

Get a fresh view of what needs a reply. If you run an email-prioritization tool, use its output; otherwise scan today's mail directly for the two candidate classes below.

**Candidate pool:**
- All **high-priority (tier 1 and tier 2)** inbound items -- direct asks of the user, decisions awaiting his input, threads where someone is blocked.
- **Key-contact unreplied threads with age_days >= 1.** Key contacts are the user's recurring high-signal correspondents (leadership, close collaborators, named client/board contacts) -- maintain that set in your own config/memory, not hardcoded here. Everyone else in an unanswered list is noise by standing rule: unanswered-email surfacing is filtered to key contacts older than 24h only.

**Filters (apply in order, count skips by reason):**
1. **Not the user's lane:** topics another person owns, or where the right move is a forward rather than a reply, get skipped -- do not draft delegation emails here.
2. **Pure FYI / newsletters / automated** regardless of priority -- if it asks nothing of the user, no draft.
3. **CC-only:** if the user was only CC'd, skip unless the body directly asks HIM something by name.
4. **Already replied:** check the thread's latest message direction in `~/Edwin/data/o365/mail/YYYY-MM/` (per-message files; match threads by normalized subject with Re:/RE:/Fw:/Fwd: prefixes stripped -- there is no thread id in the frontmatter). If the local mirror looks stale for a hot thread, verify live via the mail connector. If the user's message is the latest, skip -- confirmed-handled is closed.
5. **Already drafted:** if the thread key is in `.drafted.json` with `last_drafted` within the last 2 days, skip. A new inbound message on that thread AFTER the last draft date resets this -- draft again.

**Cap: 8 drafts per day, stakes-ranked.** Rank by who is waiting (leadership/board/client > direct report > external), what it gates, and age. Quality over coverage -- 4 drafts the user actually sends beat 8 he rewrites. Zero qualifying emails is a valid result: write no file, report DRAFTS: 0.

## Step 2: Draft Each Reply

For each selected email:

**Read the full thread.** Every message file for the normalized subject in `~/Edwin/data/o365/mail/` (check prior months if the thread is old). If the thread references prior work, decisions, or numbers, run `memory_search` (limit 5 -- cap it, oversized results are a known time sink) on the topic and on sender + topic. Cross-check PM with `pm_search` (single tokens -- it is a literal substring matcher).

**Calibrate the voice per sender.** The user's sent mail lives in the same corpus (their address appears in `from:` frontmatter; there is no `to:` field, so match by subject). Find 3-5 of the user's real replies to THIS sender: grep the sender's recent subjects, then look for user-authored `RE: <that subject>` files. Read them and mirror the register -- different correspondents get a different voice. If no history with this sender exists, default to the user's baseline: direct, terse, no corporate fluff, answer first, reasons second, no hedging, sign-off matching what their real replies use.

**Write the draft:**
- Answer the actual question FIRST. One topic per paragraph. Short.
- No em dashes anywhere -- use " -- " instead.
- Implication over instruction where a pushback is needed.
- **If the right reply depends on a decision the user has not made, draft BOTH branches short** ("If yes: ... / If no: ...") rather than guessing. Never pick a side of an open decision for him.
- **If the email needs info Edwin has** (dates, statuses, numbers from the corpus), include it, with the source in an HTML-comment aside the draft marks for deletion: `<!-- source: data/o365/mail/2026-06/... -- delete before sending -->`.
- **Anti-fabrication:** every fact in a draft traces to a corpus file, a pm-id, or a memory_search hit you can name. Anything you cannot trace becomes a `[NEEDS: ...]` placeholder -- only the user knows the answer, say so instead of inventing one.
- **Speaker-mislabel guard:** any context quoted from a transcript gets attribution sanity-checked by content and against cleaner sources (mail, sessions) before it shapes a draft -- some transcription tools mis-diarize speakers.
- **CEO/board recipients:** the draft's section gets an extra header line: `**Review carefully -- CEO/board recipient**`.

## Step 3: Write and Publish

Write to: `~/Edwin/briefing-book/docs/4. ✉️ Drafts/Reply Drafts -- YYYY-MM-DD.md`

```markdown
---
generated: YYYY-MM-DDTHH:MM
source: reply-drafts
type: reply-drafts
status: DRAFT -- user sends manually
---

# Reply Drafts -- Month DD, YYYY

**DRAFT -- user sends manually.** Edwin never sends these.
[N] drafts, stakes-ranked. Edit-and-send or discard.

## 1. [Sender] -- [Subject]

**FROM:** [name <email>] | **RECEIVED:** [YYYY-MM-DD HH:MM] | **PRIORITY:** [1/2 or "unanswered [N]d"]
**WHY IT MATTERS:** [one line: what is waiting on this reply]
[**Review carefully -- CEO/board recipient** -- only when applicable]

```text
[the draft, ready to paste]
```

[NEEDS: ...] [only if placeholders exist -- repeat each one under the block so they are impossible to miss]
```

If zero drafts qualify: write NO file, do not publish, report success with ARTIFACT: none.

Publish:
```bash
cd ~/Edwin/briefing-book && python3 scripts/obsidian-publish "docs/4. ✉️ Drafts/Reply Drafts -- YYYY-MM-DD.md"
```

## Step 4: Update State

Write `~/Edwin/skills/reply-drafts/.drafted.json`:

```json
{
  "threads": {
    "<normalized-subject-slug>": {
      "subject": "verbatim subject, prefixes stripped",
      "sender": "email",
      "last_drafted": "YYYY-MM-DD"
    }
  }
}
```

Keep old entries (they age out via the 2-day check, and history prevents re-drafting churn). Prune entries older than 30 days.

## Self-Check (Before Publishing)

1. **No send happened.** You invoked zero send/outbound commands. If you did, that is a STATUS: error and goes in NEEDS_ATTENTION.
2. **Every fact traces.** Each number, date, and status in every draft names its source or is a [NEEDS] placeholder.
3. **Voice.** Read each draft as the user: would he cut half of it? Cut it now. No em dashes. No "I hope this finds you well", no "per my last email", no corporate filler.
4. **Open decisions are branched,** not guessed.
5. **Lane check.** Nothing drafted for a lane another person owns, or things the user would just forward.
6. **The banner and per-draft DRAFT marking are present.** Someone skimming can never mistake these for sent mail.

## Completion Report

```
SKILL_COMPLETE: reply-drafts
STATUS: success | partial | error
ARTIFACT: ~/Edwin/briefing-book/docs/4. ✉️ Drafts/Reply Drafts -- YYYY-MM-DD.md | none (zero draft-worthy emails)
DRAFTS: [count, then one line each: sender -- subject]
SKIPPED: [count by reason: lane / FYI / CC-only / already-replied / already-drafted / over-cap]
PUBLISHED: yes | no | n/a
NEEDS_ATTENTION: [any tier-1 email older than 48h with no reply from the user -- that is aging risk, list them; or "none"]
ERRORS: [tools or data sources that failed, or "none"]
```

This report flows back to the main session. Keep it factual -- no narrative.
