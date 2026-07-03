/**
 * Tests for the deterministic temporal query rewriter (RAG item 5).
 * Run: node --test mcp-servers/qdrant/test/
 *
 * Clock is frozen at Thu 2026-07-02 22:00 America/New_York, so:
 *   today        = 2026-07-02 (Thursday)
 *   yesterday    = 2026-07-01
 *   this week    = Mon 2026-06-29 .. Sun 2026-07-05
 *   last week    = Mon 2026-06-22 .. Sun 2026-06-28
 *   last month   = 2026-06-01 .. 2026-06-30
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { parseTemporal } from '../temporal.js';

const NOW = new Date('2026-07-02T22:00:00-04:00');
const p = (q) => parseTemporal(q, NOW);

const EOD = 'T23:59:59Z';

test('trailing "last week" strips and maps to previous Mon-Sun', () => {
  const r = p('what did we discuss about the tunnel last week');
  assert.equal(r.query, 'what did we discuss about the tunnel');
  assert.equal(r.dateFrom, '2026-06-22');
  assert.equal(r.dateTo, `2026-06-28${EOD}`);
});

test('trailing "this week" maps to current Mon-Sun', () => {
  const r = p('project dashboard results this week');
  assert.equal(r.query, 'project dashboard results');
  assert.equal(r.dateFrom, '2026-06-29');
  assert.equal(r.dateTo, `2026-07-05${EOD}`);
});

test('trailing "yesterday" with question mark', () => {
  const r = p('what happened with the indexer yesterday?');
  assert.equal(r.query, 'what happened with the indexer');
  assert.equal(r.dateFrom, '2026-07-01');
  assert.equal(r.dateTo, `2026-07-01${EOD}`);
});

test('trailing "today"', () => {
  const r = p('meetings scheduled today');
  assert.equal(r.query, 'meetings scheduled');
  assert.equal(r.dateFrom, '2026-07-02');
  assert.equal(r.dateTo, `2026-07-02${EOD}`);
});

test('trailing "last month" maps to previous calendar month', () => {
  const r = p('what did we decide about the project last month');
  assert.equal(r.query, 'what did we decide about the project');
  assert.equal(r.dateFrom, '2026-06-01');
  assert.equal(r.dateTo, `2026-06-30${EOD}`);
});

test('"recently" = 14-day window', () => {
  const r = p('anything from Jamie recently');
  assert.equal(r.query, 'anything from Jamie');
  assert.equal(r.dateFrom, '2026-06-18');
  assert.equal(r.dateTo, `2026-07-02${EOD}`);
});

test('"in June" resolves to June of the current year (most recent past)', () => {
  const r = p('the pilot launch in June');
  assert.equal(r.query, 'the pilot launch');
  assert.equal(r.dateFrom, '2026-06-01');
  assert.equal(r.dateTo, `2026-06-30${EOD}`);
});

test('"in August" asked in July resolves to LAST year', () => {
  const r = p('vendor call notes in August');
  assert.equal(r.query, 'vendor call notes');
  assert.equal(r.dateFrom, '2025-08-01');
  assert.equal(r.dateTo, `2025-08-31${EOD}`);
});

test('"on Monday" = most recent Monday (single day)', () => {
  const r = p('what did Jamie say on Monday');
  assert.equal(r.query, 'what did Jamie say');
  assert.equal(r.dateFrom, '2026-06-29');
  assert.equal(r.dateTo, `2026-06-29${EOD}`);
});

test('"3 days ago" = single day', () => {
  const r = p('backfill status 3 days ago');
  assert.equal(r.query, 'backfill status');
  assert.equal(r.dateFrom, '2026-06-29');
  assert.equal(r.dateTo, `2026-06-29${EOD}`);
});

test('"since June 15" = open-ended dateFrom, no dateTo', () => {
  const r = p('emails from Alex since June 15');
  assert.equal(r.query, 'emails from Alex');
  assert.equal(r.dateFrom, '2026-06-15');
  assert.equal(r.dateTo, undefined);
});

test('"since last week" hits the since-rule, not the bare last-week rule', () => {
  const r = p('PRs merged since last week');
  assert.equal(r.query, 'PRs merged');
  assert.equal(r.dateFrom, '2026-06-22');
  assert.equal(r.dateTo, undefined);
});

test('"in the last 7 days" = rolling window ending today', () => {
  const r = p('PRs merged in the last 7 days');
  assert.equal(r.query, 'PRs merged');
  assert.equal(r.dateFrom, '2026-06-25');
  assert.equal(r.dateTo, `2026-07-02${EOD}`);
});

test('leading "Yesterday," strips and maps', () => {
  const r = p('Yesterday, what did I promise Jamie');
  assert.equal(r.query, 'what did I promise Jamie');
  assert.equal(r.dateFrom, '2026-07-01');
  assert.equal(r.dateTo, `2026-07-01${EOD}`);
});

// --- negatives: cases that must NOT be rewritten -----------------------------

test('NEG possessive: "last week\'s plan file" untouched', () => {
  assert.equal(p("where is last week's plan file"), null);
});

test('NEG possessive leading: "yesterday\'s meeting notes" untouched', () => {
  assert.equal(p("yesterday's meeting notes"), null);
});

test('NEG adjectival month without preposition: "the June report" untouched', () => {
  assert.equal(p('summarize the June report'), null);
});

test('NEG mid-sentence temporal: "last week about the tunnel" untouched', () => {
  assert.equal(p('what did we decide last week about the tunnel'), null);
});

test('NEG whole-query temporal: bare "yesterday" untouched (nothing to embed)', () => {
  assert.equal(p('yesterday'), null);
});

test('NEG mid-sentence "recently": untouched', () => {
  assert.equal(p('recently updated files list'), null);
});

test('NEG "since" with a non-date: untouched', () => {
  assert.equal(p('everything broken since the migration'), null);
});
