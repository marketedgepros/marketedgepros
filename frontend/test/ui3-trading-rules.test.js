import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/pages/TradingRules.jsx', import.meta.url), 'utf8');
const visibleCopy = source.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, ' ');
const copyOnly = visibleCopy.replace(/className="[^"]*"/g, ' ');

test('trading rules distinguish owner-approved standard model from explicit catalog rollout and immutable orders', () => {
  assert.match(visibleCopy, /Program-specific targets and settings are displayed above and on each program details page/);
  assert.match(visibleCopy, /Catalog assignment pending/);
  assert.match(visibleCopy, /only when its full policy is recorded/);
  assert.match(visibleCopy, /An existing order keeps the terms recorded with it/);
  assert.match(visibleCopy, /<Link to="\/programs"/);
  assert.match(source, /approvedEvaluationPolicy, evaluationPolicyForTerms/);
  assert.match(source, /data-shared-risk-policy/);
});

test('approved loss definitions do not invent strategy permissions, penalties, funding or payout schedule', () => {
  for (const unsupported of [/martingale/i, /latency arbitrage/i, /copy trading/i, /account termination/i, /profits? (?:will be )?forfeited/i, /MT5/i, /SLA/i, /non-refundable/i]) assert.doesNotMatch(copyOnly, unsupported);
  assert.match(copyOnly, /reset time and timezone still require confirmation/);
  assert.match(copyOnly, /No live account calculation is performed by this page/);
  assert.match(copyOnly, /eligible-profit definition.*explicit policy/);
  assert.match(copyOnly, /not a guaranteed return/);
  assert.doesNotMatch(source, /mailto:/i);
});

test('page keeps one shell main landmark, semantic hierarchy and keyboard-visible CTA focus styling', async () => {
  const layout = await readFile(new URL('../src/components/layout/Layout.jsx', import.meta.url), 'utf8');
  assert.match(source, /<Layout>/);
  assert.match(layout, /<main\b/);
  assert.doesNotMatch(source, /<main\b/);
  assert.match(source, /<h1\b/);
  assert.match(source, /aria-labelledby="program-settings-heading"/);
  assert.match(source, /focus-visible:outline/);
  assert.doesNotMatch(source, /\banimate-(?!none\b)|\btransition-all\b/);
});
