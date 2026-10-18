import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const file = new URL('../src/pages/affiliate/AffiliatePayout.jsx', import.meta.url);
const source = fs.readFileSync(file, 'utf8');
const transformed = await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' });
const target = new URL('../node_modules/.cache-ui3-affiliate-payout-test.mjs', import.meta.url);
let Component;
try {
  fs.writeFileSync(target, transformed.code);
  Component = (await import(target.href)).default;
} finally {
  fs.rmSync(target, { force: true });
}
const render = () => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Component)));

test('payout page clearly states unavailable status and distinguishes technical preconditions from policy', () => {
  const html = render();
  assert.match(html, /Payout execution is unavailable/);
  assert.match(html, /not approved business or legal policy/);
  assert.match(html, /not approved program terms, binding eligibility requirements/);
  assert.match(html, /does not submit payouts, collect payout methods, or verify withdrawal eligibility/);
  assert.doesNotMatch(html, /<form\b|<input\b|<button\b|\$\s?\d|\b15%\b|\b14 days\b|\b50 dollars\b/i);
  assert.doesNotMatch(source, /fetch\s*\(|axios|prepare_payout|claim_payout|confirm_payout|useEffect/);
});

test('future check outline is framed as conceptual and has accessible structure', () => {
  const html = render();
  assert.match(html, /Conceptual outline/);
  assert.match(html, /Possible checks before a future payout service/);
  assert.match(html, /<ol[^>]+aria-label="Conceptual checks for a possible future payout service"/);
  assert.equal([...html.matchAll(/<li\b/g)].length, 4);
  assert.equal([...html.matchAll(/aria-labelledby=/g)].length, 3);
  for (const text of ['Referral records', 'Payment records', 'Review status', 'Transfer handling']) {
    assert.ok(html.includes(text), `missing conceptual section: ${text}`);
  }
  assert.match(source, /focus-visible:ring-2/);
  assert.match(source, /motion-reduce:transition-none/);
  assert.match(source, /sm:grid-cols-2/);
});

test('page keeps only the supported internal destinations and avoids claims of current records', () => {
  const html = render();
  const paths = [...html.matchAll(/href="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(paths, ['/affiliate/dashboard', '/affiliate/commissions', '/support/create-ticket']);
  assert.match(html, /Open the commissions page\./);
  assert.doesNotMatch(html, /See current commission records|verified payout data|completed verification/);
  assert.match(source, /to="\/affiliate\/commissions"/);
  assert.match(source, /to="\/support\/create-ticket"/);
});
