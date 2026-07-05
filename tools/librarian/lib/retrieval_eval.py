"""Retrieval-quality regression eval for the memory Qdrant collection.

Runs the graded query set (eval-queries.json) through the PRODUCTION
memory_search path -- replicating mcp-servers/qdrant/index.js exactly:

  dense  = Ollama qwen3-embedding:8b truncated to 2048 dims (Matryoshka)
  sparse = BM42 via the production helper (mcp-servers/qdrant/sparse_helper.py,
           spawned under the same python3.12 the MCP server uses)
  fusion = Qdrant Query API RRF over dense + sparse prefetch legs
  rerank = cross-encoder over the SELECTED results (same helper process,
           fastembed TextCrossEncoder), re-ordered by rerank score; the top
           rerank score drives no_strong_match. Selected-set scope means
           rerank can only reorder within the returned list (hit@8-safe).
           EVAL_RERANK=0 evals the degraded path (RRF order + dense-cosine
           answerability).
  post   = dense-cosine minScore floor, per-file chunk cap with backfill,
           no_strong_match answerability signal
  temporal = deterministic temporal query rewriting: leading/trailing
           temporal phrases are stripped into date filters BEFORE embedding.
           Runs the PRODUCTION parser (node mcp-servers/qdrant/temporal.js
           CLI) so the eval executes the exact same code, not a port. The
           clock is FROZEN at EVAL_NOW so relative phrases in eval queries
           ("this week") grade deterministically forever.
  boost  = summary-tier boost: `memory`-source candidates get their RRF
           fused score scaled by memory_boost (hybrid mode, no explicit
           source filter only). EVAL_MEMORY_BOOST=1 evals with it off.

Grades hit@3 / hit@8 per query (negative queries grade on no_strong_match),
appends each run to .eval-history.jsonl, and alerts on regressions:

  - aggregate hit@8 drops >= 2 vs the median of the last 5 runs, OR
  - any previously-passing query fails 2 consecutive runs.

Exit code 1 only on regression alerts (a stable-but-imperfect baseline is
not a failure). Sparse-helper failure degrades to dense-only, exactly like
production, and is WARNed -- if that tanks hit@8, the alert is real signal.

Invoked by `librarian eval` (tools/librarian/librarian). Stdlib-only, so it
runs under whatever python the librarian runs under.

Requires eval-queries.json (a graded query set with ground-truth file-path
expectations against your own corpus) and mcp-servers/qdrant/sparse_helper.py
+ temporal.js (the production sparse/temporal helpers). If eval-queries.json
is absent, run_eval() logs a warning and returns 0 (unconfigured, not a
failure) rather than crashing `librarian eval`.
"""

import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

LIBRARIAN_DIR = Path(__file__).resolve().parent.parent
EDWIN_HOME = Path(os.environ.get("EDWIN_HOME", LIBRARIAN_DIR.parent.parent))

# --- CONFIG -------------------------------------------------------------------
# Mirrors the `config` object + memory_search logic in
# mcp-servers/qdrant/index.js. If a retrieval parameter changes THERE
# (fusion legs, group cap, thresholds, candidate over-fetch), change it HERE
# too, then re-run `librarian eval` to re-baseline. A silent divergence means
# the eval stops measuring what production actually does.
CONFIG = {
    "qdrant_url": os.environ.get("QDRANT_URL", "http://localhost:6333"),
    "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    "embedding_model": "qwen3-embedding:8b",   # config.embeddingModel
    "collection": os.environ.get("QDRANT_COLLECTION", "edwin-memory"),  # config.collection
    "dense_dims": 2048,                        # Matryoshka truncation in embed()
    "min_score": 0.55,                         # config.minScore (dense-cosine floor)
    "no_match_threshold": 0.65,                # config.noMatchThreshold (answerability)
    "max_chunks_per_file": 2,                  # config.maxChunksPerFile (per-file grouping)
    "candidate_multiplier": 3,                 # config.candidateMultiplier (over-fetch)
    "limit": 8,                                # eval grades hit@3/hit@8
    "sparse_python": os.environ.get("SPARSE_PYTHON", "/opt/homebrew/bin/python3.12"),  # config.sparsePython
    "sparse_helper": str(EDWIN_HOME / "mcp-servers" / "qdrant" / "sparse_helper.py"),
    # --- Cross-encoder rerank stage (mirrors index.js rerank* config) ---
    "rerank_enabled": os.environ.get("EVAL_RERANK", "1") != "0",  # config.rerankEnabled
    "rerank_model": os.environ.get("RERANK_MODEL",
                                   "Xenova/ms-marco-MiniLM-L-12-v2"),  # config.rerankModel
    "rerank_max_docs": 24,                     # config.rerankMaxDocs
    "rerank_doc_max_chars": 1500,              # config.rerankDocMaxChars
    "rerank_no_match_threshold": -5.0,         # config.rerankNoMatchThreshold
    # --- Summary-tier boost (mirrors config.memoryBoost) ---
    "memory_boost": float(os.environ.get("EVAL_MEMORY_BOOST", "1.15")),
    # --- Recency / importance weighting (mirrors config.recency* in index.js) ---
    # Reorders the already-selected result set by an age-decay bonus; never
    # changes membership (hit@8 preserved). EVAL_RECENCY=0 evals with it off.
    "recency_enabled": os.environ.get("EVAL_RECENCY", "1") != "0",
    "recency_half_life_days": float(os.environ.get("RECENCY_HALF_LIFE_DAYS", "90")),
    "recency_neutral": float(os.environ.get("RECENCY_NEUTRAL", "0.5")),
    "recency_rerank_weight": float(os.environ.get("RECENCY_RERANK_WEIGHT", "1.0")),
    "importance_rerank_weight": float(os.environ.get("IMPORTANCE_RERANK_WEIGHT", "0.5")),
    "recency_mult_weight": float(os.environ.get("RECENCY_MULT_WEIGHT", "0.15")),
    "importance_mult_weight": float(os.environ.get("IMPORTANCE_MULT_WEIGHT", "0.10")),
    # --- Temporal query rewriting: run the PRODUCTION parser via its CLI ---
    "temporal_parser": str(EDWIN_HOME / "mcp-servers" / "qdrant" / "temporal.js"),
    # Frozen clock for the parser: relative phrases in eval queries resolve
    # to the same dates on every run (production uses the live clock; the
    # parse CODE is identical -- only `now` is pinned here). Override via
    # EVAL_NOW when baselining a fresh query set.
    "eval_now": os.environ.get("EVAL_NOW", datetime.now().astimezone().isoformat(timespec="seconds")),
}

QUERIES_FILE = LIBRARIAN_DIR / "eval-queries.json"
HISTORY_FILE = LIBRARIAN_DIR / ".eval-history.jsonl"
HISTORY_WINDOW = 5  # regression baseline: median hit@8 over the last N runs


# --- HTTP helpers ---------------------------------------------------------------

def _post(url, body, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def embed_dense(text):
    """Dense query embedding -- mirrors embed() in index.js."""
    r = _post(f"{CONFIG['ollama_url']}/api/embed",
              {"model": CONFIG["embedding_model"], "input": text, "truncate": True})
    return r["embeddings"][0][:CONFIG["dense_dims"]]


# --- Sparse (BM42) via the production helper ------------------------------------

class SparseHelper:
    """Runs the exact sparse embedder production uses: sparse_helper.py under
    python3.12, JSON-lines protocol. One warm process for the whole eval run."""

    def __init__(self):
        env = dict(os.environ, RERANK_MODEL=CONFIG["rerank_model"])
        self.proc = subprocess.Popen(
            [CONFIG["sparse_python"], CONFIG["sparse_helper"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env=env,
        )
        self.next_id = 1

    def _request(self, payload):
        rid = self.next_id
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"id": rid, **payload}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("sparse helper exited")
        msg = json.loads(line)
        if msg.get("error"):
            raise RuntimeError(msg["error"])
        return msg

    def embed(self, text):
        msg = self._request({"text": text})
        return msg["indices"], msg["values"]

    def rerank(self, query, docs):
        return self._request({"op": "rerank", "query": query, "docs": docs})["scores"]

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
        except Exception:
            pass


# --- Temporal query rewriting (mirrors the pre-parse in index.js) ----------------

def parse_temporal(text):
    """Runs the production temporal parser (temporal.js CLI) so the eval
    cannot drift from index.js. Returns the parse dict ({query, phrase,
    dateFrom, dateTo?}) or None. Any failure (node missing, timeout) means
    no rewrite -- same degradation direction as a conservative parser."""
    try:
        out = subprocess.run(
            ["node", CONFIG["temporal_parser"], text, CONFIG["eval_now"]],
            capture_output=True, text=True, timeout=15,
        )
        msg = json.loads(out.stdout)
    except Exception:
        return None
    return msg if msg.get("match") else None


# --- Production search path ------------------------------------------------------

def _build_filter(filters):
    """Mirrors buildFilter() in index.js (sources / dateFrom / dateTo)."""
    if not filters:
        return None
    must = []
    if filters.get("sources"):
        must.append({"key": "source", "match": {"any": filters["sources"]}})
    if filters.get("dateFrom"):
        must.append({"key": "date", "range": {"gte": filters["dateFrom"]}})
    if filters.get("dateTo"):
        must.append({"key": "date", "range": {"lte": filters["dateTo"]}})
    return {"must": must} if must else None


def _qdrant_query(body):
    r = _post(f"{CONFIG['qdrant_url']}/collections/{CONFIG['collection']}/points/query",
              body, timeout=60)
    return r["result"]["points"]


# --- Recency / importance weighting (mirrors index.js recency helpers) ----------
# Aged against a FROZEN clock (EVAL_NOW) so recency grades deterministically on
# every run, exactly as the temporal parser is frozen.

def _recency_now_ms():
    dt = datetime.fromisoformat(CONFIG["eval_now"])
    return dt.timestamp() * 1000.0


NOW_MS = _recency_now_ms()

_DATE_RE = __import__("re").compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _parse_date_ms(date_str):
    if not date_str or not isinstance(date_str, str):
        return None
    m = _DATE_RE.match(date_str)
    if not m:
        return None
    from calendar import timegm
    return timegm((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                   0, 0, 0, 0, 0, 0)) * 1000.0


def recency_score(date_str):
    ms = _parse_date_ms(date_str)
    if ms is None:
        return CONFIG["recency_neutral"]
    age_days = max(0.0, (NOW_MS - ms) / 86400000.0)
    return 0.5 ** (age_days / CONFIG["recency_half_life_days"])


def importance_score(payload):
    try:
        v = float(payload.get("importance"))
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, v))


def production_search(query_text, vector, sparse_vec, qfilter, helper=None,
                      boost_memory=True):
    """Replicates the memory_search tool body in index.js.

    `query_text` is the (possibly temporally-rewritten) text -- it feeds the
    reranker exactly like searchText does in index.js. `boost_memory` is
    False when the query spec carries an explicit source filter (mirrors
    `!sources?.length` in index.js).

    Returns (selected_paths, top_dense, top_rerank, no_strong_match,
    search_mode) where selected_paths is the final ranked result list
    (payload file_path per hit) and top_rerank is None when the rerank
    stage did not run (disabled or degraded).
    """
    limit = CONFIG["limit"]
    candidate_limit = max(limit * CONFIG["candidate_multiplier"], 20)
    payload_fields = ["file_path", "text", "context", "source"]

    # Dense candidates always fetched: they carry the cosine scores used for
    # the minScore floor and the answerability signal.
    dense_body = {
        "query": vector, "using": "text-dense", "limit": candidate_limit,
        "with_payload": payload_fields,
    }
    if qfilter:
        dense_body["filter"] = qfilter
    dense_pts = _qdrant_query(dense_body)

    if sparse_vec:
        indices, values = sparse_vec
        prefetch = []
        for leg in (
            {"query": vector, "using": "text-dense", "limit": candidate_limit},
            {"query": {"indices": indices, "values": values},
             "using": "text-sparse", "limit": candidate_limit},
        ):
            if qfilter:
                leg["filter"] = qfilter
            prefetch.append(leg)
        hybrid_pts = _qdrant_query({
            "prefetch": prefetch, "query": {"fusion": "rrf"},
            "limit": candidate_limit, "with_payload": payload_fields,
        })
        dense_scores = {str(p["id"]): p["score"] for p in dense_pts}
        candidates = [
            {"path": p["payload"].get("file_path", ""),
             "payload": p["payload"],
             "fused": p["score"],
             "dense": dense_scores.get(str(p["id"]))}
            for p in hybrid_pts
        ]
        search_mode = "hybrid-rrf"

        # Summary-tier boost -- mirrors the memoryBoost block in index.js:
        # scale memory-source RRF scores, re-sort. Hybrid mode only, and only
        # when the caller passed no explicit source filter.
        if CONFIG["memory_boost"] != 1 and boost_memory:
            boosted = False
            for c in candidates:
                if c["payload"].get("source") == "memory":
                    c["fused"] *= CONFIG["memory_boost"]
                    boosted = True
            if boosted:
                candidates.sort(key=lambda c: c["fused"], reverse=True)
    else:
        candidates = [
            {"path": p["payload"].get("file_path", ""),
             "payload": p["payload"], "dense": p["score"]}
            for p in dense_pts
        ]
        search_mode = "dense-fallback"

    top_dense = max((c["dense"] for c in candidates if c["dense"] is not None),
                    default=0.0)

    # minScore floor on dense cosine; sparse-only hits (dense=None) are kept.
    floored = [c for c in candidates
               if c["dense"] is None or c["dense"] >= CONFIG["min_score"]]

    # Per-file grouping: cap chunks per file, backfill from next-ranked files.
    per_file = {}
    selected = []
    for c in floored:
        if len(selected) >= limit:
            break
        n = per_file.get(c["path"], 0)
        if n >= CONFIG["max_chunks_per_file"]:
            continue
        per_file[c["path"]] = n + 1
        selected.append(c)

    # Cross-encoder rerank stage -- mirrors the rerank block in index.js:
    # score the SELECTED results, re-order them by rerank score (reordering
    # within the returned list only -- hit@8-safe). Failure keeps RRF order.
    top_rerank = None
    if CONFIG["rerank_enabled"] and helper is not None and selected:
        block = selected[:CONFIG["rerank_max_docs"]]
        docs = []
        for c in block:
            p = c["payload"]
            doc = (p.get("context") + "\n" + (p.get("text") or "")
                   if p.get("context") else (p.get("text") or ""))
            docs.append(doc[:CONFIG["rerank_doc_max_chars"]])
        try:
            scores = helper.rerank(query_text, docs)
            for c, s in zip(block, scores):
                c["rerank"] = s
            # Answerability uses the MAX raw rerank logit (order-independent).
            top_rerank = max(c["rerank"] for c in block)
            # Recency / importance re-ranking (additive, logit scale). Membership
            # unchanged -> hit@8 preserved; only reorders the block.
            if CONFIG["recency_enabled"]:
                for c in block:
                    rec = recency_score(c["payload"].get("date"))
                    imp = importance_score(c["payload"])
                    c["final"] = (c["rerank"]
                                  + CONFIG["recency_rerank_weight"] * rec
                                  + CONFIG["importance_rerank_weight"]
                                  * ((imp if imp is not None else 0.5) - 0.5))
                block.sort(key=lambda c: c["final"], reverse=True)
            else:
                block.sort(key=lambda c: c["rerank"], reverse=True)
            selected = block + selected[CONFIG["rerank_max_docs"]:]
            search_mode = ("hybrid-rerank" if search_mode == "hybrid-rrf"
                           else "dense-rerank")
        except Exception:
            pass  # graceful degradation, exactly like production

    # Recency / importance re-ranking on the DEGRADED (no-rerank) path: reorder
    # the already-selected set by a recency-scaled primary score. Membership is
    # locked, so this only reorders the returned list (hit@8 preserved).
    if CONFIG["recency_enabled"] and top_rerank is None and selected:
        for c in selected:
            rec = recency_score(c["payload"].get("date"))
            imp = importance_score(c["payload"])
            base = c.get("fused")
            if base is None:
                base = c.get("dense") or 0.0
            c["final"] = (base
                          * (1 + CONFIG["recency_mult_weight"] * rec)
                          * (1 + CONFIG["importance_mult_weight"]
                             * ((imp if imp is not None else 0.5) - 0.5)))
        selected.sort(key=lambda c: c["final"], reverse=True)

    selected_paths = [c["path"] for c in selected]

    # Answerability: rerank score when the stage ran, dense cosine otherwise.
    if top_rerank is not None:
        no_strong_match = top_rerank < CONFIG["rerank_no_match_threshold"]
    else:
        no_strong_match = top_dense < CONFIG["no_match_threshold"]
    return selected_paths, top_dense, top_rerank, no_strong_match, search_mode


# --- Grading ----------------------------------------------------------------------

def _path_matches(path, patterns):
    p = path.lower()
    for pat in patterns:
        pat = pat.lower()
        if any(ch in pat for ch in "*?["):
            if fnmatch(p, pat):
                return True
        elif pat in p:
            return True
    return False


def grade(paths, expected):
    """Rank (1-based) of the first result matching any expected pattern, or None."""
    for rank, path in enumerate(paths, start=1):
        if _path_matches(path, expected):
            return rank
    return None


# --- History + regression detection ------------------------------------------------

def _query_passed(q):
    return bool(q.get("negative_pass")) if q.get("negative") else bool(q.get("pass8"))


def load_history():
    if not HISTORY_FILE.exists():
        return []
    entries = []
    for line in HISTORY_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def detect_regressions(history, current):
    """Regression rules:
    1. Aggregate hit@8 drops >= 2 vs the median of the last HISTORY_WINDOW runs.
    2. Any query that passed in some earlier run fails in BOTH the current run
       and the immediately previous run (2 consecutive failures).
    `history` is prior runs only (current NOT included).

    Mode continuity: runs are only compared against prior runs with the SAME
    rerank mode (entries without a `rerank` field are pre-rerank -> False).
    A rerank on/off switch therefore starts a fresh baseline instead of
    false-alarming against the other mode's numbers."""
    alerts = []
    history = [e for e in history
               if bool(e.get("rerank", False)) == bool(current.get("rerank", False))]

    prior = history[-HISTORY_WINDOW:]
    if prior:
        med = statistics.median(e["hit8"] for e in prior)
        if med - current["hit8"] >= 2:
            alerts.append(
                f"ALERT: aggregate hit@8 dropped to {current['hit8']} "
                f"(median of last {len(prior)} runs: {med:g})"
            )

    if history:
        prev = {q["id"]: q for q in history[-1].get("queries", [])}
        ever_passed = set()
        for entry in history:
            for q in entry.get("queries", []):
                if _query_passed(q):
                    ever_passed.add(q["id"])
        for q in current["queries"]:
            if _query_passed(q):
                continue
            pq = prev.get(q["id"])
            if pq is not None and not _query_passed(pq) and q["id"] in ever_passed:
                alerts.append(
                    f"ALERT: previously-passing query '{q['id']}' has failed "
                    f"2 consecutive runs"
                )
    return alerts


# --- Main -----------------------------------------------------------------------

def run_eval(timestamp=None, log=print):
    """Run the full eval. Returns exit code: 1 on regression ALERTs, else 0.

    If eval-queries.json is not present (no graded query set configured for
    this deployment), logs a warning and returns 0 rather than crashing --
    `librarian eval` degrades the same way `librarian quality` does when
    spot-checks.json is missing."""
    if not QUERIES_FILE.exists():
        log(f"[WARN] {QUERIES_FILE} not found -- retrieval eval is unconfigured, skipping")
        return 0

    ts = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
    queries = json.loads(QUERIES_FILE.read_text())["queries"]

    helper = None
    try:
        helper = SparseHelper()
        helper.embed("warmup")  # pay BM42 model load once, up front
        if CONFIG["rerank_enabled"]:
            try:
                helper.rerank("warmup", ["warmup"])  # pay cross-encoder load too
            except Exception as e:
                log(f"[WARN] reranker unavailable ({e}) -- RRF-order fallback, "
                    f"exactly like production degradation")
    except Exception as e:
        log(f"[WARN] sparse helper unavailable ({e}) -- dense-only fallback, "
            f"exactly like production degradation")
        helper = None

    per_query = []
    latencies = []
    modes = set()

    for spec in queries:
        qid, kind, text = spec["id"], spec["kind"], spec["query"]
        negative = bool(spec.get("negative"))
        filters = dict(spec.get("filters") or {})

        # Temporal query rewriting -- mirrors index.js: parse only when the
        # spec passes no explicit date filter (explicit always wins), embed
        # the rewritten text, merge the parsed range into the filters.
        search_text = text
        if not filters.get("dateFrom") and not filters.get("dateTo"):
            parsed = parse_temporal(text)
            if parsed:
                search_text = parsed["query"]
                filters["dateFrom"] = parsed["dateFrom"]
                if parsed.get("dateTo"):
                    filters["dateTo"] = parsed["dateTo"]

        qfilter = _build_filter(filters)
        boost_memory = not filters.get("sources")

        t0 = time.time()
        try:
            vector = embed_dense(search_text)
            sparse_vec = None
            if helper:
                try:
                    sparse_vec = helper.embed(search_text)
                except Exception as e:
                    log(f"[WARN] {qid}: sparse embed failed ({e}), dense-only")
            paths, top_dense, top_rerank, no_strong_match, mode = \
                production_search(search_text, vector, sparse_vec, qfilter,
                                  helper, boost_memory=boost_memory)
            err = None
        except Exception as e:
            paths, top_dense, top_rerank, no_strong_match, mode = \
                [], 0.0, None, True, "error"
            err = str(e)[:200]
        elapsed_ms = (time.time() - t0) * 1000
        latencies.append(elapsed_ms)
        modes.add(mode)

        row = {
            "id": qid, "kind": kind, "negative": negative,
            "top_dense": round(top_dense, 3),
            "no_strong_match": no_strong_match,
            "mode": mode,
            "latency_ms": round(elapsed_ms),
        }
        if search_text != text:
            row["rewritten"] = search_text
            row["parsed_dateFrom"] = filters.get("dateFrom")
            if filters.get("dateTo"):
                row["parsed_dateTo"] = filters["dateTo"]
        if top_rerank is not None:
            row["top_rerank"] = round(top_rerank, 3)
        if err:
            row["error"] = err
        if negative:
            row["negative_pass"] = no_strong_match
            status = "PASS" if no_strong_match else "FAIL"
            log(f"[{status}] {qid:26} ({kind}) negative probe -- "
                f"no_strong_match={no_strong_match} top_dense={top_dense:.3f}")
        else:
            rank = grade(paths, spec["expected"])
            row["rank"] = rank
            row["pass3"] = rank is not None and rank <= 3
            row["pass8"] = rank is not None and rank <= 8
            mark = f"hit@{rank}" if rank else "MISS"
            status = "PASS" if row["pass8"] else "FAIL"
            log(f"[{status}] {qid:26} ({kind}) {mark:7} top_dense={top_dense:.3f}"
                + (f"  [ERROR: {err}]" if err else ""))
        per_query.append(row)

    if helper:
        helper.close()

    positives = [q for q in per_query if not q["negative"]]
    negatives = [q for q in per_query if q["negative"]]
    reranked = any(m in ("hybrid-rerank", "dense-rerank") for m in modes)
    lat_sorted = sorted(latencies)
    entry = {
        "ts": ts,
        "hit3": sum(1 for q in positives if q["pass3"]),
        "hit8": sum(1 for q in positives if q["pass8"]),
        "positives": len(positives),
        "negatives_passed": sum(1 for q in negatives if q["negative_pass"]),
        "negatives": len(negatives),
        "latency_p50_ms": round(statistics.median(latencies)) if latencies else None,
        "latency_p95_ms": (round(lat_sorted[min(len(lat_sorted) - 1,
                                                -(-len(lat_sorted) * 95 // 100) - 1)])
                           if lat_sorted else None),
        "search_modes": sorted(modes),
        "rerank": reranked,
        "rerank_model": CONFIG["rerank_model"] if reranked else None,
        "config": {k: CONFIG[k] for k in
                   ("min_score", "no_match_threshold", "max_chunks_per_file",
                    "candidate_multiplier", "limit", "rerank_enabled",
                    "rerank_max_docs", "rerank_no_match_threshold",
                    "memory_boost", "recency_enabled",
                    "recency_half_life_days", "recency_rerank_weight",
                    "recency_mult_weight")},
        "queries": per_query,
    }

    history = load_history()
    alerts = detect_regressions(history, entry)
    entry["alerts"] = alerts

    if os.environ.get("EVAL_NO_HISTORY") == "1":
        log("[INFO] EVAL_NO_HISTORY=1 -- run not appended to history")
    else:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_FILE.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log(f"\nRetrieval eval ({'rerank' if reranked else 'no-rerank'}): "
        f"hit@3 {entry['hit3']}/{entry['positives']}, "
        f"hit@8 {entry['hit8']}/{entry['positives']}, "
        f"negative probes {entry['negatives_passed']}/{entry['negatives']}, "
        f"latency p50 {entry['latency_p50_ms']}ms p95 {entry['latency_p95_ms']}ms "
        f"(history: {len(history) + 1} runs)")
    for a in alerts:
        log(a)

    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(run_eval())
