"""Dense (Ollama/qwen3) and sparse (fastembed/BM42) embedding."""

import json
import math
import sys
import time
import urllib.request
import urllib.error

from .config import (OLLAMA_URL, EMBEDDING_MODEL, EMBEDDING_DIM,
                     OLLAMA_TIMEOUT, OLLAMA_RETRIES, SPARSE_MODEL)


class DenseEmbedder:
    """Generate dense embeddings via Ollama."""

    def __init__(self, url: str = OLLAMA_URL, model: str = EMBEDDING_MODEL,
                 dim: int = EMBEDDING_DIM):
        self.url = url.rstrip("/")
        self.model = model
        self.dim = dim
        self._verify()

    def _verify(self):
        """Check Ollama is running and model is available."""
        try:
            req = urllib.request.Request(f"{self.url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                # Check if our model is available (with or without :latest)
                found = any(self.model in m or m.startswith(self.model.split(":")[0])
                           for m in models)
                if not found:
                    print(f"ERROR: Model '{self.model}' not found in Ollama.", file=sys.stderr)
                    print(f"  Available: {models}", file=sys.stderr)
                    print(f"  Run: ollama pull {self.model}", file=sys.stderr)
                    raise SystemExit(1)
        except urllib.error.URLError as e:
            print(f"ERROR: Cannot connect to Ollama at {self.url}: {e}", file=sys.stderr)
            print("  Is Ollama running?", file=sys.stderr)
            raise SystemExit(1)

    # Maximum text length to send to Ollama (chars). Longer texts can crash
    # the embedding model with NaN/500 errors. 32K chars ≈ 8K tokens.
    MAX_TEXT_LEN = 32000

    def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns vector of length self.dim."""
        if not text or not text.strip():
            return [0.0] * self.dim

        # Truncate very long texts to prevent Ollama crashes
        if len(text) > self.MAX_TEXT_LEN:
            text = text[:self.MAX_TEXT_LEN]

        payload = json.dumps({
            "model": self.model,
            "input": text,
            "truncate": True,
        }).encode()

        for attempt in range(OLLAMA_RETRIES):
            try:
                req = urllib.request.Request(
                    f"{self.url}/api/embed",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                    raw = resp.read().decode()
                    # Ollama can return NaN values which break json.loads
                    raw = raw.replace("NaN", "0.0").replace("Infinity", "0.0").replace("-Infinity", "0.0")
                    data = json.loads(raw)
                    embeddings = data.get("embeddings", [])
                    if not embeddings:
                        print(f"  WARNING: Ollama returned empty embeddings for text ({len(text)} chars)",
                              file=sys.stderr)
                        return [0.0] * self.dim
                    vec = embeddings[0]
                    # Check for NaN values and replace with 0.0
                    if any(math.isnan(v) or math.isinf(v) for v in vec):
                        print(f"  WARNING: NaN/Inf in embeddings for text ({len(text)} chars), zeroing",
                              file=sys.stderr)
                        vec = [0.0 if (math.isnan(v) or math.isinf(v)) else v for v in vec]
                    # Truncate to desired dim (Matryoshka)
                    if len(vec) > self.dim:
                        vec = vec[:self.dim]
                    return vec
            except Exception as e:
                if attempt < OLLAMA_RETRIES - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  Ollama retry {attempt + 1}/{OLLAMA_RETRIES} "
                          f"(waiting {wait}s): {e}", file=sys.stderr)
                    time.sleep(wait)
                else:
                    raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Sequential calls to Ollama.

        Returns zero vectors for any text that fails embedding (instead of
        crashing the entire batch). Allows partial indexing of files where
        some chunks have problematic content.
        """
        results = []
        for t in texts:
            try:
                results.append(self.embed(t))
            except Exception as e:
                print(f"  WARNING: Embedding failed for chunk ({len(t)} chars): {e}",
                      file=sys.stderr)
                results.append([0.0] * self.dim)
        return results


class SparseEmbedder:
    """Generate sparse embeddings via fastembed BM42."""

    def __init__(self, model_name: str = SPARSE_MODEL):
        self.model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from fastembed import SparseTextEmbedding
            self._model = SparseTextEmbedding(model_name=self.model_name)

    def embed(self, text: str) -> tuple[list[int], list[float]]:
        """Returns (indices, values) for Qdrant SparseVector."""
        if not text or not text.strip():
            return [], []
        self._ensure_model()
        results = list(self._model.embed([text]))
        if not results:
            return [], []
        sparse = results[0]
        return sparse.indices.tolist(), sparse.values.tolist()

    def embed_batch(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        """Batch sparse embedding."""
        self._ensure_model()
        results = list(self._model.embed(texts))
        return [(r.indices.tolist(), r.values.tolist()) for r in results]
