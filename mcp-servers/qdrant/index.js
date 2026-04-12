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
import { readFileSync, existsSync } from 'fs';
import { resolve } from 'path';
import { z } from 'zod';

// ---------------------------------------------------------------------------
// Config (from env vars, with sane defaults)
// ---------------------------------------------------------------------------

const config = {
  qdrantUrl: process.env.QDRANT_URL || `http://localhost:${process.env.EDWIN_QDRANT_PORT || '6380'}`,
  ollamaUrl: process.env.OLLAMA_URL || 'http://localhost:11434',
  embeddingModel: process.env.EMBEDDING_MODEL || process.env.EDWIN_EMBED_MODEL || 'qwen3-embedding:8b',
  collection: process.env.COLLECTION || 'edwin-memory',
  workspacePath: process.env.WORKSPACE_PATH || `${process.env.HOME}/Edwin`,
  maxResults: 10,
  minScore: 0.3,
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

/**
 * Build Qdrant payload filter from optional search parameters.
 *
 * Note on `people`: the indexer never populated a `people` payload field,
 * so we fall back to full-text match on the `text` field. When P1-3 adds
 * proper `people` metadata, switch to: { key: 'people', match: { any: people } }
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
  'Semantic search across Edwin memory (Qdrant vectors). Supports source, date, and people filters.',
  {
    query: z.string().describe('Natural language search query'),
    sources: z.array(z.string()).optional().describe('Filter by data source (e.g. "fireflies", "o365-mail", "imessage")'),
    maxResults: z.number().optional().describe('Max results to return (default 10)'),
    minScore: z.number().optional().describe('Min cosine similarity 0-1 (default 0.3)'),
    dateFrom: z.string().optional().describe('ISO date — only results on or after this date'),
    dateTo: z.string().optional().describe('ISO date — only results on or before this date'),
    people: z.array(z.string()).optional().describe('Filter by people mentioned in content'),
  },
  async ({ query, sources, maxResults, minScore, dateFrom, dateTo, people }) => {
    try {
      const vector = await embed(query);
      const limit = maxResults || config.maxResults;
      const threshold = minScore || config.minScore;
      const filter = buildFilter({ sources, dateFrom, dateTo, people });

      const searchResult = await qdrant.query(config.collection, {
        query: vector,
        using: 'text-dense',
        limit,
        score_threshold: threshold,
        with_payload: true,
        ...(filter && { filter }),
      });

      const results = (searchResult.points || []).map((hit) => ({
        path: hit.payload?.file_path || '',
        startLine: hit.payload?.start_line || 1,
        endLine: hit.payload?.end_line || 1,
        score: hit.score,
        snippet: hit.payload?.text || '',
        context: hit.payload?.context || '',
        source: hit.payload?.source || 'memory',
        connector: hit.payload?.connector || '',
        date: hit.payload?.date || null,
        subject: hit.payload?.subject || null,
        title: hit.payload?.title || null,
        participants: hit.payload?.participants || null,
      }));

      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            results,
            count: results.length,
            provider: 'qdrant',
            model: config.embeddingModel,
            collection: config.collection,
          }, null, 2),
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
          content: [{ type: 'text', text: JSON.stringify({ text: '', path: filePath, error: 'File not found' }) }],
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
}

main().catch((err) => {
  console.error('[edwin-qdrant] Fatal:', err);
  process.exit(1);
});
