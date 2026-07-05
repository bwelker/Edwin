# pii-guard in CI (public Edwin repo)

The `PII Guard` workflow (`.github/workflows/pii-guard.yml`) is a **leak gate**:
it fails a build when a change introduces personal, business, or secret data
into this public repository.

## How the gate is layered

1. **Structural detection** — emails, phone numbers, `/Users/…` and `/home/…`
   paths, PEM private keys, AWS/GitHub/Slack/Anthropic/OpenAI/Google keys, JWTs,
   Bearer tokens, high-entropy secret assignments. **Needs no seed** and always
   runs, even on external-contributor PRs that cannot read repo secrets.
2. **Generic committed template** — `denylist.public.json`. Confidentiality
   tripwires (`CONFIDENTIAL`, `DO NOT DISTRIBUTE`, …) plus the `EDWIN_HOME`
   convention. It carries **no private entity seed**, so nothing sensitive lives
   in this repo.
3. **Private seed (optional, recommended)** — the full person / family / staff /
   phone / email denylist, injected at CI time from the **`PII_DENYLIST`**
   Actions secret. It is written to a temp file **outside** the repo and is
   **never committed**. This gives full name-recall without the seed ever
   touching the public tree.

## The NEVER-PORT component-name gate

Structural detection (layer 1) cannot catch a leaked **internal identifier** —
a private tool / skill / project / component name, a machine or workspace id, or
a private place name — because those are ordinary-looking words, not emails,
keys, or paths. A private component name reached a public file once this way.

To close that class, put those identifiers in the private seed under
`sensitive_projects`, `machine_terms`, and `locations`. `ci_gate.py` treats a
denylist hit on any of those (classes `sensitive_project`, `machine_specific`,
`location`) as **always-gating**: it fails the build regardless of the *medium*
severity `pii-guard` assigns, via `ALWAYS_GATE_CLASSES`. Person names, business
terms, emails, phones, keys, and paths already gate at `high` on their own, so
they need no special handling. These sections only ever match the injected
private seed, so external-contributor PRs (which cannot read the secret) are
unaffected — nothing of these classes ever fires without the seed.

## What blocks vs. what only reports

- **`pii-gate` (blocking)** scans the **changed files** in the push/PR. A build
  fails only when the change *introduces* a genuine finding — the accepted
  pre-existing baseline does not red every run.
- **`pii-audit` (non-blocking)** scans the **whole tree** and prints the full
  noise floor + any baseline findings for maintainers to clean up over time.

The documented **noise floor** — `EDWIN_HOME`, RFC-2606 reserved `example.*`
email domains, credential heuristics firing on bare variable assignments (no
literal secret), and safe image/font/media binaries — is subtracted by
`ci_gate.py` before gating, so legitimately-clean code does not fail.

## Setting the `PII_DENYLIST` secret

The secret's value is the **entire JSON** of a private denylist in the same
shape as `denylist.public.json` (sections: `person_names`,
`direct_reports_and_colleagues`, `business_terms`, `sensitive_projects`,
`locations`, `machine_terms`, `known_phone_digits`, `known_emails`).

**Via the GitHub UI**

1. Repo → **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `PII_DENYLIST`.
3. Value: paste the full JSON of your private denylist.
4. Save.

**Via the `gh` CLI**

```bash
gh secret set PII_DENYLIST < /path/to/private-denylist.json
```

If the secret is absent, the gate still runs (structural + generic template)
and emits a CI notice that private-name recall is off. If the secret is present
but not valid JSON, `pii-guard` exits with a usage error and the build fails —
fix the secret value.

## Running locally

```bash
# gate an explicit set of files (what CI does on the diff)
python tools/pii-guard/ci_gate.py --files path/to/file1 path/to/file2 \
  --denylist /path/to/private-denylist.json

# non-blocking full-tree audit
python tools/pii-guard/ci_gate.py --tree . \
  --denylist /path/to/private-denylist.json --audit

# raw scanner (all findings, no noise-floor subtraction)
python tools/pii-guard/pii-guard scan . --json --denylist /path/to/denylist.json
```

Exit codes: `0` PASS, `1` FAIL (do not merge), `2` usage/runtime error.
