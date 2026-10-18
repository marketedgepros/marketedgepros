import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../src/pages/HowItWorks.jsx', import.meta.url), 'utf8');

test('how-it-works preserves its layout and directs visitors to the declared catalog route', () => {
  assert.match(source, /import Layout from ['"]\.\.\/components\/layout\/Layout['"]/);
  assert.match(source, /<Layout>[\s\S]*<main[\s\S]*<\/main>[\s\S]*<\/Layout>/);
  assert.ok((source.match(/href="\/programs"/g) || []).length >= 1);
  assert.match(source, /Browse current programs/);
});

test('process text defers terms and rules to the current program details', () => {
  assert.match(source, /currently listed/);
  assert.match(source, /displayed objectives, account size, price, terms, and trading rules/);
  assert.match(source, /specific program/);
  assert.match(source, /Participation or approval is not guaranteed/);
});

test('public copy does not assert unsupported funding, payout, platform, split, or performance facts', () => {
  const forbiddenClaims = [
    /funded account/i,
    /within\s+24\s+hours/i,
    /live\s+MT5/i,
    /real\s+capital/i,
    /keep\s+up\s+to\s+\d+%/i,
    /profit\s+target.*\d+\s*[-–]\s*\d+%/i,
    /withdraw(?:al|als)\s+(?:anytime|on-demand)/i,
    /\d+\s*[-–]\s*\d+\s+business days/i,
    /no minimum withdrawal/i,
    /join thousands/i,
  ];
  for (const pattern of forbiddenClaims) assert.doesNotMatch(source, pattern, `unexpected claim: ${pattern}`);
});

test('page uses accessible focus styling and a restrained navy/cyan visual system', () => {
  assert.match(source, /mep-screen/);
  assert.match(source, /text-cyan-300/);
  assert.match(source, /focus-visible:outline/);
  assert.match(source, /aria-labelledby="process-heading"/);
  assert.match(source, /aria-hidden="true"/);
});
