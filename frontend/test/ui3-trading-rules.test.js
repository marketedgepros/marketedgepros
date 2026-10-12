import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/pages/TradingRules.jsx', import.meta.url), 'utf8');
const visibleCopy = source.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, ' ');
const copyOnly = visibleCopy.replace(/className="[^"]*"/g, ' ');

test('trading rules page points visitors to program-specific settings without inventing global policy', () => {
  assert.match(visibleCopy, /Program-specific settings are displayed in the catalog and on each program details page/);
  assert.match(visibleCopy, /not a blanket set of live trading rules/);
  assert.match(visibleCopy, /No general live trading rules are published here as approved policy/);
  assert.match(visibleCopy, /href="\/programs"/);
});

test('trading rules page does not state unapproved thresholds, strategies, penalties, or capabilities', () => {
  for (const unsupported of [
    /5\s*%/, /10\s*%/, /stop-loss/i, /martingale/i, /latency arbitrage/i,
    /copy trading/i, /account termination/i, /profits? (?:will be )?forfeited/i,
    /MT5/i, /SLA/i, /funding/i, /profit split/i,
  ]) assert.doesNotMatch(copyOnly, unsupported);
  assert.doesNotMatch(source, /mailto:/i);
});

test('page keeps accessible semantic hierarchy and keyboard-visible CTA focus styling', () => {
  assert.match(source, /<main\b/);
  assert.match(source, /<h1\b/);
  assert.match(source, /aria-labelledby="program-settings-heading"/);
  assert.match(source, /focus-visible:outline/);
  assert.doesNotMatch(source, /\banimate-(?!none\b)|\btransition-all\b/);
});
