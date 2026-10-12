import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const page = await readFile(new URL('../src/pages/LightningChallenge.jsx', import.meta.url), 'utf8');

test('Lightning page retains its layout, SEO and live catalog source', () => {
  assert.match(page, /import Layout from ['"]\.\.\/components\/layout\/Layout['"]/);
  assert.match(page, /import SEO from ['"]\.\.\/components\/SEO['"]/);
  assert.match(page, /import CatalogPreview from ['"]\.\.\/components\/programs\/CatalogPreview['"]/);
  assert.match(page, /<CatalogPreview type="lightning"\s*\/>/);
  assert.match(page, /type="lightning"/);
});

test('Lightning copy avoids unsupported product promises and static terms', () => {
  for (const phrase of [
    /get funded/i, /fastest path/i, /profit target/i, /profit split/i,
    /bi-weekly payout/i, /scale up to/i, /minimum trading days/i,
    /weekend holding/i, /news trading/i, /expert advisors/i,
    /free retake/i, /hundreds of traders/i, /guaranteed/i,
  ]) assert.doesNotMatch(page, phrase, `unsupported copy remains: ${phrase}`);
  assert.match(page, /funding eligibility or timing/);
  assert.match(page, /payout availability or timing/);
  assert.match(page, /Quotes, if available, are unpaid/);
});

test('Lightning CTAs use real page anchors and trading-rule navigation', () => {
  assert.match(page, /href="#programs"/);
  assert.match(page, /id="programs"/);
  assert.match(page, /href="#important-information"/);
  assert.match(page, /id="important-information"/);
  assert.match(page, /href="\/trading-rules"/);
  assert.doesNotMatch(page, /<form\b|onSubmit\s*=|handleGetStarted/);
});

test('Lightning presentation uses navy/cyan, semantic headings, focus and reduced motion', () => {
  assert.match(page, /bg-\[#0b1220\]/);
  assert.match(page, /text-cyan-300|bg-cyan-400/);
  assert.match(page, /<main\b/);
  assert.match(page, /<h1\b/);
  assert.match(page, /focus-visible:ring/);
  assert.match(page, /motion-reduce:transition-none/);
});
