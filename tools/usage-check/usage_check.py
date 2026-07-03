#!/usr/bin/env python3
"""
usage_check.py -- poll the user's Claude Max (20x) plan usage gauges and write
them to $EDWIN_HOME/memory/usage-status.json for Edwin to read.

DISCOVERED ENDPOINT (one-time discovery via chrome-devtools MCP against a live,
logged-in claude.ai session on 2026-07-03):

    GET https://claude.ai/api/organizations/{org_id}/usage
    Auth:   Cookie: sessionKey=sk-ant-sid02-...
            (the claude.ai *browser session* cookie -- NOT the Claude Code OAuth
            token in the "Claude Code-credentials" keychain entry, and NOT an
            api.anthropic.com API key. Those were tried first per the agreed
            approach and both rejected: the OAuth token 403s on this claude.ai
            route, and 403s with account_session_invalid on the api.anthropic.com
            mirror of the path -- this usage pane is a claude.ai/consumer surface
            with its own session auth, confirmed empirically.)

    claude.ai sits behind Cloudflare bot-fingerprinting. A plain `curl`/`requests`
    TLS handshake gets a 403 "Just a moment..." Cloudflare challenge page even with
    a fully valid sessionKey cookie (verified: this happened before adding
    impersonation). The fix is TLS/JA3 impersonation of a real Chrome client via
    `curl_cffi` (`impersonate="chrome"`). With that alone, the ephemeral
    `cf_clearance`/`__cf_bm` cookies are NOT required -- sessionKey + chrome TLS
    impersonation is sufficient (verified empirically, see session notes).

Response shape (subset actually used; org may add fields over time):
    {
      "limits": [
        {"kind": "session",       "percent": 3,  "resets_at": "...", ...},
        {"kind": "weekly_all",    "percent": 53, "resets_at": "...", ...},
        {"kind": "weekly_scoped", "percent": 92, "resets_at": "...",
         "scope": {"model": {"display_name": "Fable"}}, ...}
      ],
      "spend": {
        "used":  {"amount_minor": 0, "currency": "USD", "exponent": 2},
        "limit": {"amount_minor": 4000, "currency": "USD", "exponent": 2},
        "percent": 0, "enabled": false, ...
      }
    }

Credentials live at ~/.edwin/credentials/claude-usage/env (mode 600):
    CLAUDE_USAGE_ORG_ID=...
    CLAUDE_USAGE_SESSION_KEY=sk-ant-sid02-...

FAIL LOUD: on any HTTP/auth/shape failure, this script does NOT overwrite the
last-good numbers. It writes {"ok": false, "error": ..., "checked_at": ...,
"last_good": {...previous ok payload...}} so Edwin can flag "usage-check broke"
instead of silently reporting stale numbers as fresh.

Known limitation: the sessionKey cookie is a browser session credential, not an
OAuth token -- there is no programmatic refresh path. claude.ai session cookies
are normally long-lived (weeks+), so this should be rare, but if this script
starts failing with an auth-shaped error (401/403 without a Cloudflare challenge
body), the fix is manual: re-harvest CLAUDE_USAGE_SESSION_KEY from a logged-in
claude.ai browser session (chrome-devtools MCP -> list_network_requests against
https://claude.ai/settings/usage -> Cookie header -> sessionKey=...) and update
~/.edwin/credentials/claude-usage/env.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CRED_FILE = Path.home() / ".edwin/credentials/claude-usage/env"
EDWIN_HOME = Path(os.environ.get("EDWIN_HOME", Path.home() / "Edwin"))
STATUS_FILE = EDWIN_HOME / "memory/usage-status.json"
USAGE_URL_TMPL = "https://claude.ai/api/organizations/{org}/usage"
TIMEOUT_SECS = 20
MAX_ATTEMPTS = 2
RETRY_DELAY_SECS = 3


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_credentials():
    if not CRED_FILE.exists():
        raise RuntimeError(f"credentials file missing: {CRED_FILE}")
    env = {}
    for line in CRED_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    org_id = env.get("CLAUDE_USAGE_ORG_ID")
    session_val = env.get("CLAUDE_USAGE_SESSION_KEY")
    if not org_id or not session_val:
        raise RuntimeError(
            f"credentials file present but missing CLAUDE_USAGE_ORG_ID/"
            f"CLAUDE_USAGE_SESSION_KEY: {CRED_FILE}"
        )
    return org_id, session_val


def fetch_usage(org_id, session_val):
    from curl_cffi import requests as curl_requests

    url = USAGE_URL_TMPL.format(org=org_id)
    last_exc = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = curl_requests.get(
                url,
                headers={"Cookie": f"sessionKey={session_val}", "Accept": "*/*"},
                impersonate="chrome",
                timeout=TIMEOUT_SECS,
            )
            if resp.status_code != 200:
                body_snippet = resp.text[:300] if resp.text else ""
                if "Just a moment" in body_snippet or "cf-browser-verification" in body_snippet:
                    reason = "cloudflare_challenge"
                elif resp.status_code in (401, 403):
                    reason = "auth_failed"
                else:
                    reason = "http_error"
                raise RuntimeError(
                    f"{reason}: HTTP {resp.status_code} from usage endpoint "
                    f"(body: {body_snippet!r})"
                )
            data = resp.json()
            return data, resp.headers.get("request-id")
        except Exception as e:  # noqa: BLE001 -- deliberately broad, we fail-loud upstream
            last_exc = e
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECS)
    raise RuntimeError(f"fetch failed after {MAX_ATTEMPTS} attempts: {last_exc}")


def extract_gauges(data):
    limits = data.get("limits")
    spend = data.get("spend")
    if not isinstance(limits, list) or not isinstance(spend, dict):
        raise RuntimeError(
            "unexpected JSON shape: missing/invalid 'limits' list or 'spend' dict"
        )

    def find_limit(kind, model_name=None):
        for item in limits:
            if item.get("kind") != kind:
                continue
            if model_name is not None:
                scope = item.get("scope") or {}
                model = scope.get("model") or {}
                if model.get("display_name") != model_name:
                    continue
            return item
        return None

    session_limit = find_limit("session")
    weekly_all_limit = find_limit("weekly_all")
    fable_limit = find_limit("weekly_scoped", model_name="Fable")

    if session_limit is None or weekly_all_limit is None:
        raise RuntimeError(
            "unexpected JSON shape: required 'session' or 'weekly_all' limit "
            "entries not found in 'limits'"
        )

    def pct_reset(item):
        if item is None:
            return None
        return {"percent": item.get("percent"), "resets_at": item.get("resets_at")}

    used = spend.get("used") or {}
    limit = spend.get("limit") or {}
    used_exp = used.get("exponent", 2)
    limit_exp = limit.get("exponent", 2)
    used_usd = (
        used.get("amount_minor", 0) / (10 ** used_exp)
        if used.get("amount_minor") is not None
        else None
    )
    limit_usd = (
        limit.get("amount_minor", 0) / (10 ** limit_exp)
        if limit.get("amount_minor") is not None
        else None
    )

    # The API does not return a reset date for the monthly credits pot; the
    # claude.ai UI shows "Resets <month> 1" which we reproduce client-side as
    # the first of next UTC month. Flagged as computed, not API-sourced.
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month_start = now.replace(
            year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    else:
        next_month_start = now.replace(
            month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

    return {
        "session": pct_reset(session_limit),
        "weekly_all_models": pct_reset(weekly_all_limit),
        "weekly_fable": pct_reset(fable_limit),  # None if Fable limit not present
        "credits": {
            "used_usd": used_usd,
            "limit_usd": limit_usd,
            "percent": spend.get("percent"),
            "enabled": spend.get("enabled"),
            "resets_at": next_month_start.isoformat(),
            "resets_at_source": "computed_first_of_next_month_utc",
        },
    }


def load_existing_status():
    if not STATUS_FILE.exists():
        return None
    try:
        return json.loads(STATUS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def build_last_good(existing):
    """Carry forward the best known-good payload, whether the last write was
    itself ok:true or an error state that already carried a last_good."""
    if existing is None:
        return None
    if existing.get("ok") is True:
        good = dict(existing)
        good.pop("ok", None)
        return good
    if existing.get("ok") is False and existing.get("last_good"):
        return existing["last_good"]
    return None


def write_status(payload):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(STATUS_FILE)


def main():
    existing = load_existing_status()
    try:
        org_id, session_val = load_credentials()
        data, request_id = fetch_usage(org_id, session_val)
        gauges = extract_gauges(data)
        payload = {
            "ok": True,
            "fetched_at": now_iso(),
            "source": USAGE_URL_TMPL.format(org=org_id),
            "request_id": request_id,
            **gauges,
        }
        write_status(payload)
        print(json.dumps(payload, indent=2))
        return 0
    except Exception as e:  # noqa: BLE001 -- top-level fail-loud boundary
        last_good = build_last_good(existing)
        payload = {
            "ok": False,
            "error": str(e),
            "checked_at": now_iso(),
            "last_good": last_good,
        }
        write_status(payload)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
