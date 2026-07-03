"""Shared near-duplicate detection for PM (prospective memory) items.

Consumed by:
  - mcp-servers/pm/server.py  -> pm_add add-time guard (warn before creating a near-dup)
  - tools/pm-dedup            -> scan/sweep review lists

WHY THIS EXISTS: pm_search is a literal SUBSTRING matcher (SQL LIKE). The
"pm_search before pm_add" dedup step therefore silently misses semantically
identical commitments that are simply reworded across meetings/sessions --
e.g. "Email Jane Doe and John Roe with details on the team restructuring" vs
"Send email to Jane Doe and John Roe with the team restructuring details".
This module compares on normalized fuzzy + token-overlap similarity, which
catches those.

SAFETY: everything here is FLAG-ONLY. Nothing in this module deletes, cancels,
merges, or mutates any item. It only computes similarity and returns candidate
matches for a human (or the calling model) to act on.
"""

import re
from difflib import SequenceMatcher

# Threshold tuned against real-world usage: catches reworded duplicate
# families while leaving genuinely distinct open items alone. See
# tools/pm-dedup/test_dedup.py.
DEFAULT_THRESHOLD = 0.72

# Statuses considered "still live" -- an add-time guard only warns against items
# that are actually open, never against done/cancelled history.
OPEN_STATUSES = ("open", "in_progress", "waiting", "blocked", "scheduled", "overdue")

# Common words that carry no dedup signal. Kept small on purpose -- over-stemming
# hurts precision more than it helps recall here.
_STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "and", "or", "with", "on", "in", "at",
    "by", "is", "are", "be", "this", "that", "it", "as", "from", "into", "about",
    "get", "got", "send", "sent", "email", "reply", "follow", "followup", "up",
    "re", "provide", "providing", "details", "detail", "info", "information",
    "need", "needs", "please", "make", "sure", "him", "her", "them",
}


def normalize(text: str) -> str:
    """Normalize a description for comparison.

    Lowercases, strips ISO/verbose dates, PM ids, and dollar amounts (which are
    noise that varies between restatements), collapses whitespace, and drops
    trailing punctuation. Lifted from the original pm-dedup normalize() and
    extended so both callers share one definition.
    """
    t = (text or "").lower().strip()
    # Dates (ISO + verbose month names)
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", t)
    t = re.sub(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}\b",
        "",
        t,
        flags=re.I,
    )
    # PM ids
    t = re.sub(r"pm-[a-f0-9]+", "", t)
    # Dollar amounts / bare numbers that drift between restatements (80k, $1,000)
    t = re.sub(r"\$?\d[\d,\.]*\s*k?\b", "", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # Remove trailing punctuation / dashes
    t = re.sub(r"[\s\-—.]+$", "", t)
    return t


def _tokens(text: str) -> set:
    """Content-word token set: normalized, punctuation-split, stopwords removed."""
    norm = normalize(text)
    raw = re.split(r"[^a-z0-9]+", norm)
    return {w for w in raw if w and w not in _STOPWORDS and len(w) > 1}


def similarity(a: str, b: str) -> float:
    """Return a 0-1 similarity score between two descriptions.

    Blends three signals and takes the max so different duplicate shapes are all
    caught:
      - sequence ratio  : good for light rewordings / typo drift
      - token Jaccard   : order-independent overlap of content words
      - token containment: one description is a subset of a longer one
                           (down-weighted -- containment alone over-fires on
                           short generic items, so it needs strong overlap).
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0

    seq = SequenceMatcher(None, na, nb).ratio()

    ta, tb = _tokens(a), _tokens(b)
    if ta and tb:
        inter = len(ta & tb)
        jaccard = inter / len(ta | tb)
        containment = inter / min(len(ta), len(tb))
    else:
        jaccard = containment = 0.0

    return max(seq, jaccard, 0.85 * containment)


def find_matches(description, existing, threshold=DEFAULT_THRESHOLD,
                 owner=None, counterparty=None, restrict_open=True):
    """Find open items that look like near-duplicates of `description`.

    Args:
        description: the candidate new item's description.
        existing: iterable of item dicts (id, description, status, owner,
            counterparty, due_date -- missing keys tolerated).
        threshold: minimum similarity to report.
        owner/counterparty: of the candidate item. Not used to filter (we WANT
            cross-counterparty catches), but a matching counterparty nudges the
            reported score up slightly so the strongest candidate sorts first.
        restrict_open: only compare against still-live items.

    Returns:
        list of (item_dict, score) sorted by score descending, score >= threshold.
        FLAG-ONLY: no item is mutated.
    """
    results = []
    for item in existing:
        status = (item.get("status") or "").lower()
        if restrict_open and status and status not in OPEN_STATUSES:
            continue
        other = item.get("description") or ""
        score = similarity(description, other)
        # Small tie-break boost when the counterparty matches -- same person,
        # same restated commitment is the most likely true duplicate.
        cp = (item.get("counterparty") or "").strip().lower()
        if counterparty and cp and counterparty.strip().lower() == cp:
            score = min(1.0, score + 0.03)
        if score >= threshold:
            results.append((item, round(score, 3)))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def find_duplicate_groups(items, threshold=DEFAULT_THRESHOLD, bucket_by_party=True):
    """Cluster a set of items into near-duplicate groups (for the sweep).

    Greedy single-link clustering. Groups are sorted oldest-first (by created_at
    when present) so a reviewer can see the canonical item at the head. Returns
    only groups with >1 member. FLAG-ONLY: nothing is mutated.
    """
    from collections import defaultdict

    if bucket_by_party:
        buckets = defaultdict(list)
        for item in items:
            key = ((item.get("owner") or ""), (item.get("counterparty") or ""))
            buckets[key].append(item)
        bucket_lists = list(buckets.values())
    else:
        bucket_lists = [list(items)]

    groups = []
    for bucket in bucket_lists:
        if len(bucket) < 2:
            continue
        norm = [(it, normalize(it.get("description") or "")) for it in bucket]
        used = set()
        for i, (item_a, _) in enumerate(norm):
            if i in used:
                continue
            group = [item_a]
            used.add(i)
            for j, (item_b, _) in enumerate(norm):
                if j in used:
                    continue
                if similarity(item_a.get("description") or "",
                              item_b.get("description") or "") >= threshold:
                    group.append(item_b)
                    used.add(j)
            if len(group) > 1:
                group.sort(key=lambda x: x.get("created_at") or "")
                groups.append(group)
    return groups
