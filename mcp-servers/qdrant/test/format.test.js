/**
 * Tests for the memory_search response formatter (token-efficiency layer).
 * Run: node --test mcp-servers/qdrant/test/
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  roundScore,
  effectiveScore,
  conciseResult,
  formatSearchResponse,
  truncateSnippet,
  DEFAULT_SNIPPET_CHARS,
} from '../format.js';

const fullHit = {
  path: '/srv/edwin/memory/sessions/2026-07-01-summary.md',
  startLine: 12,
  endLine: 40,
  score: 0.6591354608535767,
  fusedScore: 0.016393442622950821,
  rerankScore: 4.482913017272949,
  recencyScore: 0.97734,
  finalScore: 5.460253,
  snippet: 'Alex decided to move the challenger to prod.',
  context: 'Session summary from 2026-07-01 covering the challenger rollout.',
  source: 'memory',
  connector: '',
  date: '2026-07-01',
  subject: null,
  title: null,
  participants: null,
};

const sparseOnlyHit = {
  ...fullHit,
  score: null,          // sparse-only: no dense cosine
  rerankScore: null,
  recencyScore: null,
  finalScore: null,
  fusedScore: 0.0159,
};

const envelope = {
  results: [fullHit],
  count: 1,
  provider: 'qdrant',
  model: 'qwen3-embedding:8b',
  collection: 'edwin-memory',
  search_mode: 'hybrid-rerank',
  top_dense_score: 0.659,
  recency_weighting: { half_life_days: 90, rerank_weight: 1, mult_weight: 0.15 },
  rerank_model: 'Xenova/ms-marco-MiniLM-L-12-v2',
  no_strong_match: false,
};

test('roundScore rounds numbers, passes null through', () => {
  assert.equal(roundScore(0.6591354608535767), 0.659);
  assert.equal(roundScore(null), null);
  assert.equal(roundScore(undefined), undefined);
});

test('effectiveScore prefers finalScore, then rerank, then dense, then fused', () => {
  assert.equal(effectiveScore(fullHit), 5.460253);
  assert.equal(effectiveScore({ ...fullHit, finalScore: null }), 4.482913017272949);
  assert.equal(effectiveScore({ ...fullHit, finalScore: null, rerankScore: null }), 0.6591354608535767);
  assert.equal(effectiveScore(sparseOnlyHit), 0.0159);
});

test('conciseResult keeps content, drops empty/null metadata and score plumbing', () => {
  const c = conciseResult(fullHit);
  assert.deepEqual(Object.keys(c).sort(), ['context', 'date', 'lines', 'path', 'score', 'snippet', 'source']);
  assert.equal(c.lines, '12-40');
  assert.equal(c.score, 5.46);
  assert.ok(!('fusedScore' in c) && !('rerankScore' in c) && !('connector' in c));
  assert.ok(!('subject' in c) && !('title' in c) && !('participants' in c));
});

test('conciseResult keeps title/subject/participants when present', () => {
  const c = conciseResult({ ...fullHit, title: 'Weekly Dispatch', participants: ['Alice', 'Bob'] });
  assert.equal(c.title, 'Weekly Dispatch');
  assert.deepEqual(c.participants, ['Alice', 'Bob']);
});

test('concise envelope drops config echo, keeps decision signals, is compact', () => {
  const text = formatSearchResponse(envelope, 'concise');
  const obj = JSON.parse(text);
  assert.deepEqual(Object.keys(obj).sort(), ['count', 'no_strong_match', 'results', 'search_mode']);
  assert.equal(obj.search_mode, 'hybrid-rerank');
  assert.ok(!text.includes('\n'), 'concise output must be compact (no pretty-print)');
});

test('concise keeps temporal-rewrite transparency and warning when present', () => {
  const text = formatSearchResponse({
    ...envelope,
    rewritten_query: 'tunnel status',
    parsed_range: { phrase: 'last week', dateFrom: '2026-06-22', dateTo: '2026-06-28T23:59:59Z' },
    no_strong_match: true,
    warning: 'No strong match: top rerank score -6.10 < -5. Results are likely tangential.',
  }, 'concise');
  const obj = JSON.parse(text);
  assert.equal(obj.rewritten_query, 'tunnel status');
  assert.equal(obj.parsed_range.dateFrom, '2026-06-22');
  assert.equal(obj.no_strong_match, true);
  assert.match(obj.warning, /No strong match/);
});

test('detailed keeps every field (rounded) and pretty-prints', () => {
  const text = formatSearchResponse(envelope, 'detailed');
  const obj = JSON.parse(text);
  assert.equal(obj.provider, 'qdrant');
  assert.equal(obj.rerank_model, 'Xenova/ms-marco-MiniLM-L-12-v2');
  assert.ok('recency_weighting' in obj);
  const r = obj.results[0];
  assert.equal(r.score, 0.659);
  assert.equal(r.rerankScore, 4.483);
  assert.equal(r.fusedScore, 0.016393);
  assert.equal(r.connector, '');
  assert.ok(text.includes('\n'), 'detailed output is pretty-printed');
});

test('default detail is concise', () => {
  const text = formatSearchResponse(envelope);
  assert.ok(!JSON.parse(text).provider);
});

test('truncateSnippet caps long text with an actionable marker', () => {
  const long = 'x'.repeat(54445);
  const t = truncateSnippet(long, 2000);
  assert.ok(t.length < 2200, `got ${t.length}`);
  assert.match(t, /\+52445 chars truncated — memory_get/);
  // short text and cap=0 pass through untouched
  assert.equal(truncateSnippet('short', 2000), 'short');
  assert.equal(truncateSnippet(long, 0), long);
  assert.equal(truncateSnippet(null, 2000), null);
});

test('concise caps giant snippets by default; detailed never truncates', () => {
  const giant = { ...fullHit, snippet: 's'.repeat(30000) };
  const c = conciseResult(giant);
  assert.ok(c.snippet.length <= DEFAULT_SNIPPET_CHARS + 150);
  assert.match(c.snippet, /truncated/);
  const d = JSON.parse(formatSearchResponse({ ...envelope, results: [giant] }, 'detailed'));
  assert.equal(d.results[0].snippet.length, 30000);
});

test('formatSearchResponse honors custom maxSnippetChars', () => {
  const giant = { ...fullHit, snippet: 's'.repeat(5000) };
  const o = JSON.parse(formatSearchResponse({ ...envelope, results: [giant] }, 'concise', 500));
  assert.ok(o.results[0].snippet.length < 700);
  const uncapped = JSON.parse(formatSearchResponse({ ...envelope, results: [giant] }, 'concise', 0));
  assert.equal(uncapped.results[0].snippet.length, 5000);
});

test('token economics: concise is materially smaller than detailed', () => {
  const ten = { ...envelope, results: Array(10).fill(fullHit), count: 10 };
  const concise = formatSearchResponse(ten, 'concise');
  const detailed = formatSearchResponse(ten, 'detailed');
  assert.ok(concise.length < detailed.length * 0.6,
    `expected >40% char reduction, got ${(100 - 100 * concise.length / detailed.length).toFixed(1)}% (${concise.length} vs ${detailed.length})`);
});
