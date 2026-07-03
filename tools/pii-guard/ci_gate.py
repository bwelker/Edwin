#!/usr/bin/env python3
"""ci_gate -- CI wrapper around pii-guard for the PUBLIC Edwin repo.

WHY THIS EXISTS
    `pii-guard` is a recall-over-precision leak scanner: it deliberately flags
    a large "noise floor" of sanctioned patterns (the EDWIN_HOME env
    convention, RFC-2606 reserved example domains, and the credential heuristic
    firing on plain variable assignments that hold no literal secret). Those are
    NOT leaks -- they are the tool working as designed. A raw `pii-guard scan`
    of the tree therefore FAILs on legitimately-clean public code.

    This wrapper runs pii-guard, then subtracts the documented noise floor
    (see docs / the parity scrub report), and gates on what remains. It keeps
    full recall on genuine PII (real emails, phones, /Users paths, typed API
    keys/tokens, private keys, denylisted person names, data-bearing binaries)
    while not red-ing CI on the sanctioned baseline.

MODES
    --files f1 f2 ...   scan an explicit set of files (CI gate = the PR/push
                        diff, so pre-existing baseline noise never blocks a
                        build; only NEWLY introduced PII fails).
    --tree DIR          scan a whole directory (used for the non-blocking
                        full-tree audit step).

DENYLIST
    The authoritative person/entity seed must NEVER live in the public repo.
    Pass --denylist to point at a seed injected at CI time from the
    `PII_DENYLIST` GitHub Actions secret. With no secret, it falls back to the
    committed generic template (structural detection still runs -- it needs no
    seed).

EXIT CODES
    0  PASS -- no gating findings after the noise floor is removed
    1  FAIL -- genuine PII present; do NOT merge
    2  usage / runtime error
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PII_GUARD = HERE / "pii-guard"

# Severity at or above which a *surviving* finding fails the gate.
GATE_SEVERITY = "high"
SEV = {"low": 0, "medium": 1, "high": 2}

# --- Path excludes ---------------------------------------------------------
# Files/dirs that INTENTIONALLY contain PII-like patterns or confidentiality
# tripwire words as fixtures or documentation. Scanning them yields guaranteed
# false positives (the content is there ON PURPOSE), so they are removed from
# the CHANGED-FILES gate. This list is deliberately tight -- only self-referential
# gate/test assets, never broad code directories. Each entry documents WHY it is
# safe. Matched against the repo-relative POSIX path of each changed file.
_EXCLUDE_DIR_PREFIXES = (
    # Content-guard injection fixtures embed phishing-style fake email
    # addresses at made-up external domains precisely so the injection-detection
    # tests have something to detect. Fabricated, not real PII.
    "tools/content-guard/test-samples/",
    # pii-guard's own positive-case fixtures: files that MUST contain PII-shaped
    # strings so the scanner's detection can be exercised.
    "tools/pii-guard/test-samples/",
)
_EXCLUDE_FILES = frozenset({
    # The gate's own CI doc necessarily quotes the confidentiality tripwire
    # phrases it detects -- documentation of the detector, not a leak.
    "tools/pii-guard/README-ci.md",
    # pii-guard's README likewise names the terms/patterns it flags.
    "tools/pii-guard/README.md",
})


def _is_excluded(relpath: str) -> bool:
    """True if a changed file is an intentional-fixture / gate-doc that must not
    be scanned (guaranteed false positives). Tight allowlist only."""
    p = Path(relpath).as_posix()
    if p in _EXCLUDE_FILES:
        return True
    return any(p.startswith(pref) for pref in _EXCLUDE_DIR_PREFIXES)

# --- Noise-floor allowlist -------------------------------------------------
# RFC-2606 reserved domains + documentation placeholder mailboxes.
_RESERVED_EMAIL = re.compile(
    r"@(?:[A-Za-z0-9\-]+\.)*example\.(?:com|net|org)$", re.IGNORECASE)
_PLACEHOLDER_LOCALPART = re.compile(
    r"^(?:noreply|no-reply|do-not-reply|donotreply|your[-_.]?email)\b",
    re.IGNORECASE)

# Binary extensions that are safe to publish (images / fonts / media). Data-
# bearing binaries (.db/.sqlite/.parquet/.pkl/.zip/...) are NOT here -- they
# stay gating because they can hide PII we cannot read.
_SAFE_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".mov", ".webm", ".wav", ".mp3", ".m4a",
}

# The two pii-guard credential DESCRIPTIONS that are pure heuristics (fire on
# any `key = value` shape). Genuine literal secrets in a recognised format are
# reported under their own high-precision descriptions (AWS/GitHub/Slack/
# Anthropic/OpenAI/Google key, JWT, PEM private key, Bearer token) and are
# NEVER dropped here.
_HEURISTIC_CRED_DESCS = {
    "Secret-like key=value assignment",
    "High-entropy secret assignment",
}

# A heuristic credential value is noise when the right-hand side is an
# expression / reference / env lookup / placeholder rather than an opaque
# literal secret.
_EXPR_SIGNS = re.compile(r"[()\[\]{}$]")
_DOTTED_IDENT = re.compile(r"[A-Za-z_]\w*\.[A-Za-z_]")
_REF_KEYWORDS = re.compile(
    r"\b(?:env|getenv|environ|os|self|resp|req|creds?|flow|token_getter"
    r"|tempfile|path|Path|strftime|process\.env|get|json)\b", re.IGNORECASE)
_PLACEHOLDER_VAL = re.compile(
    r"(?:changeme|xxxx|redacted|your[-_]|example|<[^>]*>|\.\.\.)",
    re.IGNORECASE)


def _cred_value(match_text: str) -> str:
    """Best-effort extraction of the RHS of a `key = value` / `key: value`."""
    for sep in ("=", ":"):
        if sep in match_text:
            return match_text.split(sep, 1)[1].strip().strip("'\"")
    return match_text.strip()


def is_noise(f: dict) -> bool:
    """True if finding f belongs to the sanctioned noise floor (drop it)."""
    klass = f.get("class")
    desc = f.get("description", "")
    match = f.get("match", "")

    if klass == "email":
        if _RESERVED_EMAIL.search(match) or _PLACEHOLDER_LOCALPART.match(match):
            return True
        return False

    if klass == "credential" and desc in _HEURISTIC_CRED_DESCS:
        val = _cred_value(match)
        if (_EXPR_SIGNS.search(val) or _DOTTED_IDENT.search(val)
                or _REF_KEYWORDS.search(val) or _PLACEHOLDER_VAL.search(val)):
            return True
        # An opaque literal (no code syntax) survives -> gates.
        return False

    if klass == "machine_specific":
        # EDWIN_HOME env convention (+ the BlueBubbles public project name, if
        # denylisted) are sanctioned. Medium severity, but drop explicitly.
        return True

    if klass == "binary_unverified":
        ext = Path(f.get("file", "")).suffix.lower()
        return ext in _SAFE_BINARY_EXTS

    # A denylisted person name on a LICENSE copyright line is a sanctioned
    # public attribution, not a leak.
    if klass == "person_name":
        fname = Path(f.get("file", "")).name.upper()
        if fname.startswith("LICENSE") and "copyright" in f.get("context", "").lower():
            return True
        return False

    return False


def run_pii_guard(targets, denylist):
    findings = []
    scanned = 0
    for t in targets:
        cmd = [sys.executable, str(PII_GUARD), "scan", t,
               "--json", "--fail-on", "low"]
        if denylist:
            cmd += ["--denylist", denylist]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 2:
            # usage/runtime error (e.g. bad denylist) -- surface it hard.
            sys.stderr.write(res.stderr or res.stdout)
            sys.exit(2)
        try:
            data = json.loads(res.stdout)
        except json.JSONDecodeError:
            sys.stderr.write(f"pii-guard produced no JSON for {t}:\n{res.stderr}\n")
            sys.exit(2)
        scanned += data.get("scanned", 0)
        findings.extend(data.get("findings", []))
    return findings, scanned


def main():
    p = argparse.ArgumentParser(prog="ci_gate")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--tree", metavar="DIR", help="Scan a whole directory")
    g.add_argument("--files", nargs="*", metavar="F", help="Scan explicit files")
    p.add_argument("--denylist", metavar="PATH", help="Denylist seed to use")
    p.add_argument("--audit", action="store_true",
                   help="Report only; always exit 0 (non-blocking audit mode)")
    args = p.parse_args()

    denylist = args.denylist
    if denylist and not Path(denylist).is_file():
        sys.stderr.write(f"denylist not found: {denylist}\n")
        sys.exit(2)

    if args.tree:
        targets = [args.tree]
    else:
        # A pii-guard denylist file necessarily *contains* the terms it forbids
        # (and confidentiality tripwires), so it self-matches. It is config, not
        # scannable content -- skip it. (The injected private seed is written
        # outside the repo, so it is never in the file list anyway.)
        targets = [f for f in (args.files or [])
                   if Path(f).is_file()
                   and not re.match(r"denylist.*\.json$", Path(f).name)
                   and not _is_excluded(f)]
        if not targets:
            print("ci_gate: no files to scan (empty diff) -- PASS")
            sys.exit(0)

    findings, scanned = run_pii_guard(targets, denylist)

    kept, dropped = [], 0
    for f in findings:
        if is_noise(f):
            dropped += 1
        else:
            kept.append(f)

    gating = [f for f in kept if SEV[f["severity"]] >= SEV[GATE_SEVERITY]]

    print(f"ci_gate: scanned {scanned} file(s); {len(findings)} raw finding(s); "
          f"{dropped} noise-floor dropped; {len(kept)} kept; "
          f"{len(gating)} gating (>= {GATE_SEVERITY}).")
    if gating:
        print("\nGENUINE PII / SECRET FINDINGS -- do NOT merge:")
        for f in sorted(gating, key=lambda x: (x["file"], x["line"])):
            loc = f"L{f['line']}" if f["line"] else "file"
            print(f"  {f['file']}:{loc} [{f['severity'].upper()}] "
                  f"{f['class']}: {f['description']}")

    if args.audit:
        print("(audit mode -- non-blocking)")
        sys.exit(0)
    sys.exit(1 if gating else 0)


if __name__ == "__main__":
    main()
