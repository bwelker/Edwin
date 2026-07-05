/**
 * Edwin Qdrant MCP Server
 *
 * Exposes Edwin's vector store (Qdrant) to Claude Code via MCP.
 * Uses edwin-memory collection with hybrid search (dense + sparse).
 *
 * Tools:
 *   memory_search  — semantic search with source/date/people filters
 *   memory_get     — file content by path + optional line range
 *   memory_status  — health check (Qdrant, Ollama, vector count)
 *
 * Transport: stdio
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { QdrantClient } from '@qdrant/js-client-rest';
import { spawn } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';
import { z } from 'zod';
import { parseTemporal } from './temporal.js';
import { formatSearchResponse } from './format.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Config (from env vars, with sane defaults)
// ---------------------------------------------------------------------------

const config = {
  qdrantUrl: process.env.QDRANT_URL || `http://localhost:${process.env.EDWIN_QDRANT_PORT || '6380'}`,
  ollamaUrl: process.env.OLLAMA_URL || 'http://localhost:11434',
  embeddingModel: process.env.EMBEDDING_MODEL || process.env.EDWIN_EMBED_MODEL || 'qwen3-embedding:8b',
  collection: process.env.COLLECTION || 'edwin-memory',
  workspacePath: process.env.WORKSPACE_PATH || `${process.env.HOME}/Edwin`,
  sparsePython: process.env.SPARSE_PYTHON || '/opt/homebrew/bin/python3.12',
  maxResults: 10,
  // Default cosine floor. Calibrated against a multi-query eval: real
  // personal-content hits go as low as ~0.57 top cosine, observed junk
  // floor is ~0.50-0.53. A higher floor (e.g. 0.6) would drop real hits.
  minScore: 0.55,
  // Below this top dense cosine, retrieval likely found nothing solid and
  // the response carries no_strong_match: true. Calibrated: real hits are
  // mostly >= 0.67; junk mostly < 0.60. Borderline zone 0.57-0.68 exists
  // (semantically in-domain junk can reach 0.74), so treat as advisory.
  noMatchThreshold: 0.65,
  // Per-file result cap (dedup-heavy sources flood otherwise) and how many
  // candidates to over-fetch to backfill the freed slots.
  maxChunksPerFile: 2,
  candidateMultiplier: 3,
  // --- Cross-encoder rerank stage ---
  // Reranks the SELECTED results (post-floor, post-grouping) with a
  // cross-encoder running in the same python helper as BM42 (fastembed
  // TextCrossEncoder). Scoping to the selected set (not the candidate
  // block) means reranking can only reorder within the returned list --
  // it provably cannot push a hit out of the results (hit@8-safe; block-
  // level reranking was measured to regress hit@8 on an internal eval).
  // Any failure degrades to plain RRF order -- never breaks memory_search.
  rerankEnabled: process.env.RERANK_DISABLED !== '1',
  rerankModel: process.env.RERANK_MODEL || 'Xenova/ms-marco-MiniLM-L-12-v2',
  rerankMaxDocs: 24,      // safety cap on how many selected results get scored
  rerankTimeoutMs: 2000,  // per-search budget; first call gets 20s (model load)
  rerankDocMaxChars: 1500, // cap per-doc chars sent to the helper (512-token model)
  // Answerability cutoff on the top rerank score (raw ms-marco logit,
  // scored on context+text docs). Calibrated on an internal eval set plus
  // junk/real probes: junk tops around -9.7..-6.0, real answerable tops
  // roughly 2..9 with occasional hard real queries down around -4. Cutoff
  // -5.0 sits between the worst real and the best-behaving junk, with a
  // margin on each side -- vs the dense threshold's much narrower margin.
  // When rerank is degraded, the dense-cosine noMatchThreshold applies
  // instead.
  rerankNoMatchThreshold: -5.0,
  // --- Summary-tier boost ---
  // The `memory` source is the distilled, highest-signal tier (curated
  // session summaries, decisions -- cheap RAPTOR). Multiplier applied to the
  // RRF fused score of memory-source candidates in hybrid mode, ONLY when
  // the caller passed no explicit source filter. Tuned empirically on an
  // internal eval: with rerank ON the exact value matters less; on the
  // DEGRADED no-rerank path (real production path when the helper dies) a
  // too-high boost value regresses hit@3 by letting a stale summary
  // outrank the expected memory doc, while a modest 1.15 held all metrics.
  // MEMORY_BOOST=1 disables.
  memoryBoost: Number(process.env.MEMORY_BOOST ?? 1.15),

  // --- Recency / importance weighting on retrieval ranking ---
  // Generative-Agents pattern: recent (and important) memories surface
  // higher WITHOUT deleting old ones (memory is an archive).
  //
  // Scoped to REORDER the already-selected result set ONLY (like the rerank
  // stage) -- it can change the order of returned results but never their
  // MEMBERSHIP, so it provably cannot push a hit out of hit@8. Two knobs
  // because the two active sort scales differ: an ADDITIVE logit bonus on
  // the reranked path (rerank scores are unbounded logits, ~[-10,10]) and a
  // MULTIPLICATIVE factor on the degraded RRF/dense path (bounded scores).
  //
  // Recency is a bounded BONUS (recent lifted, old never pushed below its
  // relevance baseline) so a still-highly-relevant old memory can't be
  // buried: at the default weights the recency swing (~1 logit) is dwarfed
  // by the relevance spread (real-vs-junk ~10 logits). Importance is a
  // CENTERED term (payload.importance in [0,1]; absent -> 0.5 neutral -> no
  // effect) -- wired for a future importance signal, inert until one exists.
  recencyEnabled: process.env.RECENCY_DISABLED !== '1',
  // Exponential half-life in days: recency=1.0 at age 0, 0.5 at halfLife,
  // 0.25 at 2*halfLife. 90d gives a gentle gradient across a multi-month
  // corpus without burying relevant older material. RECENCY_DISABLED=1 off.
  recencyHalfLifeDays: Number(process.env.RECENCY_HALF_LIFE_DAYS ?? 90),
  // Recency assigned to UNDATED docs (curation files, some memory-tier):
  // 0.5 places them mid-pack -- above ancient dated docs, below fresh ones
  // -- rather than penalizing them to the bottom for a missing date.
  recencyNeutral: Number(process.env.RECENCY_NEUTRAL ?? 0.5),
  // Additive logit bonus on the reranked path: finalScore = rerankScore +
  // recencyRerankWeight * recency. 1.0 => today +1.0, one half-life +0.5.
  recencyRerankWeight: Number(process.env.RECENCY_RERANK_WEIGHT ?? 1.0),
  // Additive logit term for importance (centered at 0.5): +/- this*0.5 max.
  importanceRerankWeight: Number(process.env.IMPORTANCE_RERANK_WEIGHT ?? 0.5),
  // Multiplicative recency factor on the DEGRADED (no-rerank) path, applied
  // to the RRF fused / dense cosine sort score: *(1 + recencyMultWeight *
  // recency). 0.15 mirrors the memoryBoost magnitude (15%).
  recencyMultWeight: Number(process.env.RECENCY_MULT_WEIGHT ?? 0.15),
  // Multiplicative importance factor (centered): *(1 + w*(importance-0.5)).
  importanceMultWeight: Number(process.env.IMPORTANCE_MULT_WEIGHT ?? 0.10),
};

const qdrant = new QdrantClient({ url: config.qdrantUrl });

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Generate embedding via Ollama (qwen3-embedding:8b, truncated to 2048 dims).
 */
async function embed(text) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000);
  try {
    const resp = await fetch(`${config.ollamaUrl}/api/embed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: config.embeddingModel, input: text, truncate: true }),
      signal: controller.signal,
    });
    if (!resp.ok) throw new Error(`Ollama embed failed: ${resp.status}`);
    const data = await resp.json();
    let vec = data.embeddings[0];
    // Truncate to 2048 dims (Matryoshka)
    if (vec.length > 2048) vec = vec.slice(0, 2048);
    return vec;
  } catch (err) {
    if (err.name === 'AbortError') throw new Error('Ollama embedding timed out after 30s — is Ollama running?');
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// Sparse (BM42) query embedding via a persistent python helper.
// fastembed has no JS build, so we keep one warm python child around
// (model load ~1-2s once, then per-query ms). Any failure here degrades
// search to dense-only -- it must never break memory_search.
// ---------------------------------------------------------------------------

const sparseHelper = {
  proc: null,
  pending: new Map(), // id -> {resolve, reject, timer}
  nextId: 1,
  buf: '',
  lastSpawnAttempt: 0,
};

function sparseHelperStart() {
  const now = Date.now();
  if (sparseHelper.proc) return;
  // Respawn backoff: don't hammer a broken helper more than once/30s
  if (now - sparseHelper.lastSpawnAttempt < 30000) throw new Error('sparse helper in backoff');
  sparseHelper.lastSpawnAttempt = now;

  const proc = spawn(config.sparsePython, [resolve(__dirname, 'sparse_helper.py')], {
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  proc.stdout.on('data', (data) => {
    sparseHelper.buf += data.toString();
    let idx;
    while ((idx = sparseHelper.buf.indexOf('\n')) >= 0) {
      const line = sparseHelper.buf.slice(0, idx).trim();
      sparseHelper.buf = sparseHelper.buf.slice(idx + 1);
      if (!line) continue;
      try {
        const msg = JSON.parse(line);
        const p = sparseHelper.pending.get(msg.id);
        if (p) {
          sparseHelper.pending.delete(msg.id);
          clearTimeout(p.timer);
          if (msg.error) p.reject(new Error(msg.error));
          else p.resolve(msg);
        }
      } catch { /* ignore malformed line */ }
    }
  });
  proc.stderr.on('data', (d) => console.error(`[sparse-helper] ${d.toString().trim()}`));
  proc.on('exit', (code) => {
    console.error(`[sparse-helper] exited (code ${code})`);
    for (const [, p] of sparseHelper.pending) {
      clearTimeout(p.timer);
      p.reject(new Error('sparse helper exited'));
    }
    sparseHelper.pending.clear();
    sparseHelper.proc = null;
    sparseHelper.buf = '';
  });
  proc.on('error', (err) => {
    console.error(`[sparse-helper] spawn error: ${err.message}`);
    sparseHelper.proc = null;
  });
  sparseHelper.proc = proc;
}

/**
 * Send one JSON-lines request to the helper, resolve on its reply.
 * Throws on any failure (caller falls back). Shared by sparse + rerank.
 */
function helperRequest(payload, timeoutMs, label) {
  sparseHelperStart();
  if (!sparseHelper.proc) return Promise.reject(new Error('sparse helper unavailable'));
  const id = sparseHelper.nextId++;
  return new Promise((resolveP, rejectP) => {
    const timer = setTimeout(() => {
      sparseHelper.pending.delete(id);
      rejectP(new Error(`${label} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    sparseHelper.pending.set(id, { resolve: resolveP, reject: rejectP, timer });
    try {
      sparseHelper.proc.stdin.write(JSON.stringify({ id, ...payload }) + '\n');
    } catch (err) {
      sparseHelper.pending.delete(id);
      clearTimeout(timer);
      rejectP(err);
    }
  });
}

/**
 * BM42 sparse query embedding. Throws on any failure (caller falls back
 * to dense-only). First call after (re)spawn tolerates model load time.
 */
function sparseEmbed(text) {
  const firstCall = sparseHelper.pending.size === 0 && sparseHelper.nextId <= 2;
  const timeoutMs = firstCall ? 20000 : 6000;
  return helperRequest({ text }, timeoutMs, 'sparse embed');
}

let rerankWarm = false;

/**
 * Cross-encoder rerank: one relevance score (raw logit) per doc, same
 * order as `docs`. Throws on any failure (caller keeps RRF order).
 * First call tolerates model load time; after that the strict per-search
 * budget applies.
 */
async function rerankScores(query, docs) {
  const timeoutMs = rerankWarm ? config.rerankTimeoutMs : 20000;
  const msg = await helperRequest({ op: 'rerank', query, docs }, timeoutMs, 'rerank');
  if (!Array.isArray(msg.scores) || msg.scores.length !== docs.length) {
    throw new Error('rerank returned malformed scores');
  }
  rerankWarm = true;
  return msg.scores;
}

// ---------------------------------------------------------------------------
// Recency / importance weighting
// ---------------------------------------------------------------------------

/**
 * Parse a payload `date` value to epoch ms. Handles both corpus formats:
 * day precision ("2026-06-17") and full timestamps
 * ("2026-01-29T12:45:11+00:00"). Anything unparseable -> null (neutral).
 */
function parseDateMs(dateStr) {
  if (!dateStr || typeof dateStr !== 'string') return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr);
  if (!m) return null;
  // Interpret the day at UTC midnight — consistent with how the corpus
  // stamps dates (UTC-or-day precision) and the temporal filter boundaries.
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isFinite(ms) ? ms : null;
}

/**
 * Recency score in [0,1]: 1.0 at age 0, halving every `halfLifeDays`.
 * Undated docs return the configured neutral value (mid-pack, not buried).
 * Future-dated docs (clock skew) clamp to 1.0.
 */
function recencyScore(dateStr, nowMs, halfLifeDays, neutral) {
  const ms = parseDateMs(dateStr);
  if (ms === null) return neutral;
  const ageDays = Math.max(0, (nowMs - ms) / 86400000);
  return Math.pow(0.5, ageDays / halfLifeDays);
}

/**
 * Importance in [0,1] from an optional payload.importance field. Absent or
 * malformed -> null, which callers treat as 0.5 (neutral, zero effect).
 * Wired ahead of an importance signal; inert until the indexer populates it.
 */
function importanceScore(payload) {
  const v = Number(payload?.importance);
  if (!Number.isFinite(v)) return null;
  return Math.min(1, Math.max(0, v));
}

/**
 * Build Qdrant payload filter from optional search parameters.
 *
 * Note on `people`: the indexer never populated a `people` payload field,
 * so we fall back to full-text match on the `text` field. When richer
 * people metadata is added to the indexer, switch to:
 * { key: 'people', match: { any: people } }
 */
function buildFilter({ sources, dateFrom, dateTo, people }) {
  const must = [];

  if (sources?.length) {
    must.push({ key: 'source', match: { any: sources } });
  }

  if (dateFrom) {
    must.push({ key: 'date', range: { gte: dateFrom } });
  }

  if (dateTo) {
    must.push({ key: 'date', range: { lte: dateTo } });
  }

  // Text-match workaround — see note above
  if (people?.length) {
    for (const person of people) {
      must.push({ key: 'text', match: { text: person } });
    }
  }

  return must.length > 0 ? { must } : undefined;
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const server = new McpServer({
  name: 'edwin-qdrant',
  version: '0.1.0',
});

// -- memory_search ----------------------------------------------------------

server.tool(
  'memory_search',
  'Hybrid semantic search across Edwin memory (Qdrant, dense qwen3 + sparse BM42 fused with RRF, then cross-encoder reranked). Supports source, date, and people filters. Unambiguous leading/trailing temporal phrases ("last week", "in June", "since June 15") are auto-stripped into date filters (response shows rewritten_query + parsed_range); explicit dateFrom/dateTo disable that. Curated memory-source summaries get a small rank boost unless sources is set. Results are then recency-weighted (recent memories surface higher via a bounded age-decay bonus that reorders — never drops — results; old highly-relevant memories are not buried). Response includes no_strong_match when retrieval found nothing solid.',
  {
    query: z.string().describe('Natural language search query. A leading/trailing temporal phrase is parsed into date filters automatically.'),
    sources: z.array(z.string()).optional().describe('Filter by data source (e.g. "fireflies", "o365-mail", "imessage")'),
    maxResults: z.number().optional().describe('Max results to return (default 10)'),
    minScore: z.number().optional().describe('Min cosine similarity 0-1 (default 0.3)'),
    dateFrom: z.string().optional().describe('ISO date — only results on or after this date. Passing this (or dateTo) disables temporal phrase parsing.'),
    dateTo: z.string().optional().describe('ISO date — only results on or before this date. Passing this (or dateFrom) disables temporal phrase parsing.'),
    people: z.array(z.string()).optional().describe('Filter by people mentioned in content'),
    detail: z.enum(['concise', 'detailed']).optional().describe('Response verbosity (default "concise": content + one relevance score per hit, snippets capped at maxSnippetChars). "detailed" adds all pipeline scores (dense/RRF/rerank/recency), config metadata, and untruncated snippets — for retrieval debugging.'),
    maxSnippetChars: z.number().optional().describe('Per-hit snippet cap in concise mode (default 2000; 0 = uncapped). Truncated hits carry a marker telling how to fetch the full text via memory_get.'),
  },
  async ({ query, sources, maxResults, minScore, dateFrom, dateTo, people, detail, maxSnippetChars }) => {
    try {
      // --- Temporal query rewriting ---
      // Deterministic pre-parse (temporal.js, NOT an LLM call): an
      // unambiguous leading/trailing temporal phrase ("last week", "in
      // June", "3 days ago", "since June 15") is stripped from the text we
      // embed and converted into date filters instead -- the phrase only
      // muddies the embedding. Explicit caller-passed dateFrom/dateTo
      // ALWAYS win: if either is present, no parsing happens at all.
      let searchText = query;
      let parsedRange = null;
      if (!dateFrom && !dateTo) {
        const parsed = parseTemporal(query);
        if (parsed) {
          searchText = parsed.query;
          dateFrom = parsed.dateFrom;
          dateTo = parsed.dateTo;
          parsedRange = {
            phrase: parsed.phrase,
            dateFrom: parsed.dateFrom,
            ...(parsed.dateTo && { dateTo: parsed.dateTo }),
          };
        }
      }

      const vector = await embed(searchText);
      const limit = maxResults || config.maxResults;
      const threshold = minScore ?? config.minScore;
      const filter = buildFilter({ sources, dateFrom, dateTo, people });
      // Over-fetch so per-file grouping can backfill freed slots
      const candidateLimit = Math.max(limit * config.candidateMultiplier, 20);

      // Sparse query embedding (BM42, same model as the indexer). Any
      // failure degrades to dense-only -- never break search.
      let sparseVec = null;
      try {
        sparseVec = await sparseEmbed(searchText);
      } catch (err) {
        console.error(`[edwin-qdrant] sparse embed failed, dense-only fallback: ${err.message}`);
      }

      // Dense candidates always fetched: they carry the cosine scores used
      // for minScore filtering and the answerability signal (RRF scores are
      // rank-based and not comparable to a cosine threshold).
      const densePromise = qdrant.query(config.collection, {
        query: vector,
        using: 'text-dense',
        limit: candidateLimit,
        with_payload: true,
        ...(filter && { filter }),
      });

      let candidates;
      let searchMode;

      if (sparseVec) {
        // Hybrid: RRF fusion of dense + sparse legs (Qdrant Query API)
        const [hybridResult, denseRes] = await Promise.all([
          qdrant.query(config.collection, {
            prefetch: [
              {
                query: vector,
                using: 'text-dense',
                limit: candidateLimit,
                ...(filter && { filter }),
              },
              {
                query: { indices: sparseVec.indices, values: sparseVec.values },
                using: 'text-sparse',
                limit: candidateLimit,
                ...(filter && { filter }),
              },
            ],
            query: { fusion: 'rrf' },
            limit: candidateLimit,
            with_payload: true,
          }),
          densePromise,
        ]);
        const denseScores = new Map(
          (denseRes.points || []).map((p) => [String(p.id), p.score]),
        );
        candidates = (hybridResult.points || []).map((hit) => ({
          hit,
          fusedScore: hit.score,
          denseScore: denseScores.get(String(hit.id)) ?? null,
        }));
        searchMode = 'hybrid-rrf';

        // --- Summary-tier boost ---
        // `memory` source = the distilled tier; nudge its candidates above
        // equivalently-scored raw chunks by scaling their RRF fused score.
        // Skipped when the caller filtered sources explicitly (they already
        // said which tier they want) and in dense-fallback mode (cosine
        // scores feed the minScore floor and must stay unscaled).
        if (config.memoryBoost !== 1 && !sources?.length) {
          let boosted = false;
          for (const c of candidates) {
            if (c.hit.payload?.source === 'memory') {
              c.fusedScore *= config.memoryBoost;
              boosted = true;
            }
          }
          if (boosted) candidates.sort((a, b) => b.fusedScore - a.fusedScore);
        }
      } else {
        const denseResult = await densePromise;
        candidates = (denseResult.points || []).map((hit) => ({
          hit,
          fusedScore: null,
          denseScore: hit.score,
        }));
        searchMode = 'dense-fallback';
      }

      // Answerability signal: best cosine among dense candidates
      const topDense = candidates.reduce(
        (m, c) => (c.denseScore !== null && c.denseScore > m ? c.denseScore : m),
        0,
      );

      // minScore floor on dense cosine. Sparse-only hits (lexical matches
      // outside the dense top-K, e.g. exact ticket IDs) have no cosine and
      // are kept -- they matched for a different, stronger reason.
      const floored = candidates.filter(
        (c) => c.denseScore === null || c.denseScore >= threshold,
      );

      // Per-file grouping: cap chunks per file, backfill from next-ranked
      // distinct files (duplicate-heavy sources flood results otherwise).
      const perFile = new Map();
      let selected = [];
      for (const c of floored) {
        if (selected.length >= limit) break;
        const path = c.hit.payload?.file_path || '';
        const n = perFile.get(path) || 0;
        if (n >= config.maxChunksPerFile) continue;
        perFile.set(path, n + 1);
        selected.push(c);
      }

      // Clock for recency weighting — read once so every candidate in this
      // search is aged against the same instant.
      const nowMs = Date.now();

      // --- Cross-encoder rerank stage ---------------------------------------
      // Score the SELECTED results as (query, chunk) pairs and re-order by
      // relevance. The top score also drives no_strong_match (calibrated,
      // unlike the dense-cosine stopgap). Any failure (helper down, timeout)
      // keeps the RRF order unchanged -- graceful degradation, logged only.
      let topRerank = null;
      if (config.rerankEnabled && selected.length > 0) {
        const block = selected.slice(0, config.rerankMaxDocs);
        const docs = block.map((c) => {
          const p = c.hit.payload || {};
          const doc = p.context ? `${p.context}\n${p.text || ''}` : (p.text || '');
          return doc.slice(0, config.rerankDocMaxChars);
        });
        try {
          const scores = await rerankScores(searchText, docs);
          block.forEach((c, i) => { c.rerankScore = scores[i]; });
          // Answerability uses the MAX raw rerank logit, independent of the
          // final order — recency below may reorder the block, but "is there
          // anything strongly relevant here?" must stay a relevance question,
          // preserving the calibrated rerankNoMatchThreshold semantics.
          topRerank = Math.max(...block.map((c) => c.rerankScore));
          // --- Recency / importance re-ranking (additive, logit scale) ------
          // Fold a bounded recency bonus (+ centered importance term) into
          // each rerank logit, then sort by the combined score. Membership is
          // unchanged (still the same block) — this only reorders, so hit@8
          // is preserved; a large relevance gap dwarfs the ~1-logit recency
          // swing, so a highly-relevant old memory stays on top.
          if (config.recencyEnabled) {
            for (const c of block) {
              const p = c.hit.payload || {};
              const rec = recencyScore(p.date, nowMs, config.recencyHalfLifeDays, config.recencyNeutral);
              const imp = importanceScore(p);
              c.recency = rec;
              c.importance = imp;
              c.finalScore = c.rerankScore
                + config.recencyRerankWeight * rec
                + config.importanceRerankWeight * ((imp ?? 0.5) - 0.5);
            }
            block.sort((a, b) => b.finalScore - a.finalScore);
          } else {
            block.sort((a, b) => b.rerankScore - a.rerankScore);
          }
          selected = block.concat(selected.slice(config.rerankMaxDocs));
          searchMode = searchMode === 'hybrid-rrf' ? 'hybrid-rerank' : 'dense-rerank';
        } catch (err) {
          console.error(`[edwin-qdrant] rerank failed, keeping RRF order: ${err.message}`);
        }
      }

      // --- Recency / importance re-ranking on the DEGRADED path -------------
      // When rerank did NOT run (disabled or helper down), reorder the ALREADY
      // -selected set by a recency/importance-scaled version of its primary
      // sort score (RRF fused, or dense cosine in fallback). Membership is
      // locked, so this only reorders the returned list — never changes which
      // docs are returned. This is the path where recency matters most: it's
      // the only "freshness" signal when the cross-encoder is unavailable.
      if (config.recencyEnabled && topRerank === null && selected.length > 0) {
        for (const c of selected) {
          const p = c.hit.payload || {};
          const rec = recencyScore(p.date, nowMs, config.recencyHalfLifeDays, config.recencyNeutral);
          const imp = importanceScore(p);
          c.recency = rec;
          c.importance = imp;
          const base = c.fusedScore ?? c.denseScore ?? 0;
          c.finalScore = base
            * (1 + config.recencyMultWeight * rec)
            * (1 + config.importanceMultWeight * ((imp ?? 0.5) - 0.5));
        }
        selected.sort((a, b) => b.finalScore - a.finalScore);
      }

      const results = selected.map((c) => ({
        path: c.hit.payload?.file_path || '',
        startLine: c.hit.payload?.start_line || 1,
        endLine: c.hit.payload?.end_line || 1,
        score: c.denseScore,          // cosine similarity (null = sparse-only hit)
        fusedScore: c.fusedScore,     // RRF fusion score (null in dense-fallback)
        rerankScore: c.rerankScore ?? null, // cross-encoder logit (null = not reranked)
        recencyScore: c.recency ?? null,    // age-decay weight in [0,1] (null = recency off)
        finalScore: c.finalScore ?? null,   // combined rank score after recency/importance
        snippet: c.hit.payload?.text || '',
        context: c.hit.payload?.context || '',
        source: c.hit.payload?.source || 'memory',
        connector: c.hit.payload?.connector || '',
        date: c.hit.payload?.date || null,
        subject: c.hit.payload?.subject || null,
        title: c.hit.payload?.title || null,
        participants: c.hit.payload?.participants || null,
      }));

      // Answerability: the cross-encoder gives a directly calibrated
      // relevance score, so when rerank ran, its top score decides
      // no_strong_match. When degraded, fall back to the dense-cosine
      // threshold (the pre-rerank stopgap).
      let noStrongMatch;
      let noMatchWhy;
      if (topRerank !== null) {
        noStrongMatch = topRerank < config.rerankNoMatchThreshold;
        noMatchWhy = `top rerank score ${topRerank.toFixed(2)} < ${config.rerankNoMatchThreshold}`;
      } else {
        noStrongMatch = topDense < config.noMatchThreshold;
        noMatchWhy = `best cosine ${topDense.toFixed(3)} < ${config.noMatchThreshold}`;
      }
      const response = {
        results,
        count: results.length,
        provider: 'qdrant',
        model: config.embeddingModel,
        collection: config.collection,
        search_mode: searchMode,
        // Temporal rewriting transparency: what was actually embedded and
        // which date range the stripped phrase resolved to.
        ...(parsedRange && {
          rewritten_query: searchText,
          parsed_range: parsedRange,
        }),
        top_dense_score: topDense ? Number(topDense.toFixed(3)) : 0,
        ...(topRerank !== null && {
          rerank_model: config.rerankModel,
          top_rerank_score: Number(topRerank.toFixed(3)),
        }),
        ...(config.recencyEnabled && {
          recency_weighting: {
            half_life_days: config.recencyHalfLifeDays,
            rerank_weight: config.recencyRerankWeight,
            mult_weight: config.recencyMultWeight,
          },
        }),
        no_strong_match: noStrongMatch,
      };
      if (noStrongMatch) {
        response.warning =
          `No strong match: ${noMatchWhy}. ` +
          'Results are likely tangential -- treat as "memory has nothing solid on this" ' +
          'rather than an answer.';
      }

      return {
        content: [{ type: 'text', text: formatSearchResponse(response, detail || 'concise', maxSnippetChars ?? undefined) }],
      };
    } catch (err) {
      return {
        content: [{ type: 'text', text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  },
);

// -- memory_get -------------------------------------------------------------

server.tool(
  'memory_get',
  'Read content of a memory file by path, with optional line range.',
  {
    filePath: z.string().describe('Absolute path, or path relative to workspace'),
    from: z.number().optional().describe('Starting line number (1-indexed, default 1)'),
    count: z.number().optional().describe('Number of lines to return (default: all)'),
  },
  async ({ filePath, from, count }) => {
    try {
      const fullPath = filePath.startsWith('/')
        ? filePath
        : resolve(config.workspacePath, filePath);

      if (!existsSync(fullPath)) {
        return {
          content: [{ type: 'text', text: JSON.stringify({
            text: '',
            path: filePath,
            error: `File not found: ${fullPath}. Relative paths resolve against ${config.workspacePath}; if the file lives elsewhere, pass an absolute path — memory_search results return absolute paths you can pass through unchanged.`,
          }) }],
        };
      }

      const content = readFileSync(fullPath, 'utf-8');
      const lines = content.split('\n');
      const start = (from || 1) - 1;
      const selected = count ? lines.slice(start, start + count) : lines.slice(start);

      return {
        content: [{
          type: 'text',
          text: JSON.stringify({ text: selected.join('\n'), path: filePath, lines: selected.length }),
        }],
      };
    } catch (err) {
      return {
        content: [{ type: 'text', text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  },
);

// -- memory_status ----------------------------------------------------------

server.tool(
  'memory_status',
  'Health check: Qdrant connectivity, Ollama connectivity, vector count, embedding model.',
  async () => {
    const status = {
      qdrant: { connected: false, url: config.qdrantUrl, collection: config.collection, vectorCount: null },
      ollama: { connected: false, url: config.ollamaUrl, model: config.embeddingModel },
      reranker: {
        enabled: config.rerankEnabled,
        model: config.rerankModel,
        warm: rerankWarm,
        helperAlive: !!sparseHelper.proc,
      },
    };

    // Check Qdrant
    try {
      const info = await qdrant.getCollection(config.collection);
      status.qdrant.connected = true;
      status.qdrant.vectorCount = info.points_count ?? null;
    } catch (err) {
      status.qdrant.error = err.message;
    }

    // Check Ollama
    try {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 5000);
      const resp = await fetch(`${config.ollamaUrl}/api/tags`, { signal: controller.signal });
      clearTimeout(tid);
      if (resp.ok) {
        const data = await resp.json();
        status.ollama.connected = true;
        const models = (data.models || []).map((m) => m.name);
        status.ollama.availableModels = models;
        status.ollama.modelLoaded = models.some((n) => n.includes(config.embeddingModel));
      }
    } catch (err) {
      status.ollama.error = err.message;
    }

    return {
      content: [{ type: 'text', text: JSON.stringify(status, null, 2) }],
    };
  },
);

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // Log to stderr (stdout is the MCP transport)
  console.error(`[edwin-qdrant] MCP server running — Qdrant: ${config.qdrantUrl}, Collection: ${config.collection}`);
  // Warm the sparse helper so the first search doesn't pay BM42 model load
  sparseEmbed('warmup').then(
    () => console.error('[edwin-qdrant] sparse helper warm (hybrid search ready)'),
    (err) => console.error(`[edwin-qdrant] sparse helper warmup failed (dense-only until it recovers): ${err.message}`),
  );
  // Warm the cross-encoder too (lazy-loads in the same helper, ~2s once)
  if (config.rerankEnabled) {
    rerankScores('warmup', ['warmup']).then(
      () => console.error(`[edwin-qdrant] reranker warm (${config.rerankModel})`),
      (err) => console.error(`[edwin-qdrant] reranker warmup failed (RRF-order until it recovers): ${err.message}`),
    );
  }
}

main().catch((err) => {
  console.error('[edwin-qdrant] Fatal:', err);
  process.exit(1);
});
