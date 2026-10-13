import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/pages/FAQ.jsx', import.meta.url), 'utf8');
const answerBlock = source.slice(source.indexOf('const categories = ['), source.indexOf('const allQuestions ='));

test('FAQ copy avoids unsupported funding, split, payout, platform, SLA, rating, and policy promises', () => {
  for (const unsupported of [
    'provides capital', '90% of the profits', 'within 24 hours', 'MetaTrader', 'TradingView',
    'Instant Funding', 'profit target is', 'drawdown', 'Expert Advisors', 'scale your account',
    'Add-ons are optional upgrades', '$75', 'PayPal', '1-3 business days', '24/7 support',
    'within 15 minutes', 'during news events', 'non-refundable', 'first profit withdrawal',
    'bank-level encryption', 'completely safe',
  ]) assert.equal(answerBlock.toLowerCase().includes(unsupported.toLowerCase()), false, `unexpected copy: ${unsupported}`);
  assert.match(answerBlock, /program listing/i);
  assert.match(answerBlock, /does not establish universal program terms/i);
  assert.match(answerBlock, /cannot confirm/i);
});

test('search has an explicit accessible no-results state and reset control', () => {
  assert.match(source, /No questions match your search\./);
  assert.match(source, /Clear search/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /type="search"/);
  assert.match(source, /htmlFor="faq-search"/);
});

test('accordions expose state and relationship for their answer panel', () => {
  assert.match(source, /aria-expanded=\{expanded\}/);
  assert.match(source, /aria-controls=\{answerId\}/);
  assert.match(source, /id=\{answerId\} hidden=\{!expanded\}/);
  assert.match(source, /focus-visible:ring-2/);
});

test('FAQ structured data is generated from the same safe questions and supported navigation remains', () => {
  assert.match(source, /questions: allQuestions\.map/);
  assert.match(source, /<StructuredData type="faq" data=\{faqData\}/);
  assert.match(source, /<Link to="\/programs"/);
  assert.match(source, /<Link to="\/contact"/);
});
