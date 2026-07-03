#!/opt/homebrew/bin/python3.12
"""Persistent BM42 sparse embedder + cross-encoder reranker for the
edwin-qdrant MCP server.

Spawned once by index.js and kept alive. Protocol: JSON lines on stdin,
JSON lines on stdout.

  sparse (default op, backward compatible):
    in:  {"id": 1, "text": "query text"}
    out: {"id": 1, "indices": [...], "values": [...]}

  rerank (cross-encoder relevance scores, one per doc, raw logits):
    in:  {"id": 2, "op": "rerank", "query": "...", "docs": ["...", ...]}
    out: {"id": 2, "scores": [...]}

  out on error: {"id": N, "error": "..."}

Sparse uses the exact same model as the indexer (lib/embedder.py):
Qdrant/bm42-all-minilm-l6-v2-attentions, query_embed().
Rerank uses fastembed TextCrossEncoder (model from RERANK_MODEL env,
default Xenova/ms-marco-MiniLM-L-12-v2 -- chosen via the 2026-07-02
librarian eval; ~210ms for the 8-10 selected results on the Studio's CPU).
Models load lazily on first use (~1-2s each), then per-query ms.
"""

import json
import os
import sys

MODEL_NAME = "Qdrant/bm42-all-minilm-l6-v2-attentions"
RERANK_MODEL = os.environ.get("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-12-v2")
# Persistent model cache -- fastembed's default lives under the macOS
# per-user temp directory, which the OS purges; a purge would force a
# silent re-download (or an offline failure) on the next helper start.
EDWIN_HOME = os.environ.get("EDWIN_HOME", os.path.expanduser("~/Edwin"))
CACHE_DIR = os.path.join(EDWIN_HOME, "data/models/fastembed-cache")

_model = None
_reranker = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import SparseTextEmbedding
        _model = SparseTextEmbedding(model_name=MODEL_NAME, cache_dir=CACHE_DIR)
    return _model


def _get_reranker():
    global _reranker
    if _reranker is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _reranker = TextCrossEncoder(model_name=RERANK_MODEL, cache_dir=CACHE_DIR)
    return _reranker


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            if req.get("op") == "rerank":
                scores = list(_get_reranker().rerank(req["query"], req["docs"]))
                out = {"id": req_id, "scores": [float(s) for s in scores]}
            else:
                emb = list(_get_model().query_embed(req["text"]))[0]
                out = {"id": req_id,
                       "indices": emb.indices.tolist(),
                       "values": emb.values.tolist()}
        except Exception as e:  # never die on a bad request
            out = {"id": req_id, "error": str(e)[:300]}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
