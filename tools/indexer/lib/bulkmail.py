"""Bulk/marketing email detection for context-generation gating.

Detected bulk mail is still chunked and embedded (it stays searchable) --
it just doesn't get a paid Haiku context prefix. The classifier is
deliberately conservative: a personal sender must never be classified
bulk, so classification requires either an unambiguous automated-sender
local part (noreply@ etc.) or TWO independent weak marketing signals
(promo subdomain, unsubscribe footer, marketing subject). When unsure,
we keep context.
"""

import os
import re

# Sender local parts that are automated/broadcast by definition.
# A human never mails from these. Exact match on the local part
# (dots/hyphens/underscores normalized away).
BULK_LOCAL_PARTS = {
    "noreply", "donotreply", "notreply", "nereply",
    "newsletter", "newsletters",
    "marketing", "promotions", "promo", "promos",
    "offers", "deals", "specials",
    "email", "emails", "mailer", "bounce", "bounces",
    "campaigns", "campaign",
}

# First DNS label of the sender domain that marks a dedicated
# promotional-sending subdomain (email.toolnut.com, mail.notion.so,
# e.linkedin.com, ...). Weak signal on its own.
PROMO_DOMAIN_LABELS = {
    "email", "emails", "e", "em", "eml", "mail", "mailer", "mailers",
    "news", "newsletter", "newsletters", "marketing", "promo",
    "click", "links", "link", "go", "reply", "bounce", "mta",
    "campaign", "campaigns", "info", "engage", "connect",
}

# Marketing subject markers. Weak signal: a personal sender could
# conceivably forward a deal, so this never classifies alone.
SUBJECT_MARKERS = (
    "% off", "sale ends", "flash sale", "limited time", "last chance",
    "free shipping", "coupon", "promo code", "don't miss", "act now",
    "black friday", "cyber monday", "deal of the day", "exclusive offer",
    "shop now", "[trending]", "best sellers", "new arrivals",
    "your rewards", "clearance",
)

# Bulk-mail footer phrases (unsubscribe machinery). Weak signal.
UNSUBSCRIBE_MARKERS = (
    "unsubscribe", "view in browser", "view this email in your browser",
    "view it in your browser", "email preferences", "manage preferences",
    "manage your preferences", "update your preferences",
    "if you no longer wish to receive", "opt out of these emails",
    "why did i get this",
)

# Never classify these sender domains as bulk (work + internal tooling
# whose automated mail is still worth situating). Set via the
# EDWIN_BULKMAIL_ALLOW_DOMAINS env var (comma-separated suffixes).
ALLOW_DOMAIN_SUFFIXES = tuple(
    d.strip().lower()
    for d in os.environ.get("EDWIN_BULKMAIL_ALLOW_DOMAINS", "").split(",")
    if d.strip()
)

_ADDR_RE = re.compile(r"<([^<>@\s]+)@([^<>\s]+)>|(?<![<\w.])([^<>@\s]+)@([\w.-]+\.\w+)")


def _parse_sender(from_field: str) -> tuple[str, str]:
    """Extract (local_part, domain) from a From header value.

    Handles 'Name <addr@dom>' and bare 'addr@dom'. Returns ("", "")
    when no address can be found.
    """
    if not from_field:
        return "", ""
    m = _ADDR_RE.search(str(from_field))
    if not m:
        return "", ""
    local = m.group(1) or m.group(3) or ""
    domain = m.group(2) or m.group(4) or ""
    return local.lower().strip(), domain.lower().strip().rstrip(".")


def is_bulk_mail(frontmatter: dict, body: str) -> bool:
    """Return True if this email is bulk/marketing mail.

    Conservative by design: requires one STRONG signal (automated
    local part) or two WEAK signals (promo subdomain, marketing
    subject, unsubscribe footer). Allow-listed domains are never bulk.
    Missing/empty sender is never bulk (can't be confident).
    """
    local, domain = _parse_sender(str(frontmatter.get("from", "") or ""))

    if domain and any(domain == suf or domain.endswith("." + suf)
                      for suf in ALLOW_DOMAIN_SUFFIXES):
        return False

    # Strong: automated/broadcast local part. Normalize separators so
    # no-reply / do_not_reply / no.reply all match.
    if local:
        # Strip plus-addressing tags (newsletter+211@...) before matching.
        norm = re.sub(r"[._-]", "", local.split("+", 1)[0])
        if norm in BULK_LOCAL_PARTS:
            return True

    weak = 0

    # Weak: dedicated promotional-sending subdomain (needs 3+ labels so
    # bare "mail.com"-style domains don't count).
    if domain:
        labels = domain.split(".")
        if len(labels) >= 3 and labels[0] in PROMO_DOMAIN_LABELS:
            weak += 1

    # Weak: marketing subject line.
    subject = str(frontmatter.get("subject", "") or "").lower()
    if subject and any(mk in subject for mk in SUBJECT_MARKERS):
        weak += 1

    # Weak: unsubscribe footer machinery in the body.
    if body:
        lowered = body.lower()
        if any(mk in lowered for mk in UNSUBSCRIBE_MARKERS):
            weak += 1

    return weak >= 2
