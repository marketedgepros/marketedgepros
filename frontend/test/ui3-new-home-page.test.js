import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, '../src/pages/NewHomePage.jsx'), 'utf8');

test('homepage retains the existing layout, metadata component, catalog source and router links', () => {
  assert.match(source, /import SchemaMarkup from/);
  assert.match(source, /import CatalogPreview from/);
  assert.match(source, /import Layout from/);
  assert.match(source, /<Layout>[\s\S]*<SchemaMarkup\s*\/>[\s\S]*<CatalogPreview\s+interactive\s*\/>[\s\S]*<\/Layout>/);
  for (const route of ['/programs', '/how-it-works', '/faq', '/support']) {
    assert.ok(source.includes(`to="${route}"`), `expected supported navigation to ${route}`);
  }
});

test('homepage public copy does not promise funding, payout, splits, platform availability or fabricated proof', () => {
  const forbidden = [
    /\$\s?(?:10K|25K|50|400K|400,000|10M)/i,
    /\b(?:get funded|instant funding|funding programs|payouts? anytime|profit split|scale your account|receive your funded account)\b/i,
    /\b(?:MT4|MT5|MetaTrader|TradingView)\b/i,
    /\b(?:testimonial|what our traders say|top rated|verified payouts|successful funded traders|active traders)\b/i,
    /\b(?:24 hours|instant|guarantee|no time limits|no hidden conditions|2-4 weeks)\b/i,
  ];
  for (const expression of forbidden) assert.doesNotMatch(source, expression);
});

test('homepage explains catalog and quote limitations and exposes accessible focus treatment', () => {
  assert.match(source, /displayed price and terms/);
  assert.match(source, /quote is not a payment/);
  assert.match(source, /Payment availability is checked separately for your account in checkout/);
  assert.match(source, /focus-visible:outline-none/);
  assert.match(source, /focus-visible:ring-2/);
});
