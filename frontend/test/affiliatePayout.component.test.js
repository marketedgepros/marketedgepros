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
// Relative import rewriting is unnecessary: this presentational component only
// uses installed React/router/icons. Import via a local file URL for resolution.
const target = new URL('../node_modules/.cache-affiliate-payout-test.mjs', import.meta.url);
let Component;
try {
  fs.writeFileSync(target, transformed.code);
  Component = (await import(target.href)).default;
} finally {
  fs.rmSync(target, { force: true });
}
const markup = () => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Component)));


test('payout page renders real component with explicit unavailable state and no fake amount or form', () => {
  const html = markup();
  assert.match(html, /Payout execution is unavailable/);
  assert.match(html, /does not show a verified withdrawable balance or payout history/);
  assert.match(html, /not approved business or legal policy/);
  assert.doesNotMatch(html, /<form|<input|<button|\$[0-9]|15%|14 days|50 dollars/);
  assert.doesNotMatch(source, /fetch\(|axios|prepare_payout|claim_payout|confirm_payout|useEffect/);
});


test('payout page has only supported links, ordered requirements and accessible named sections', () => {
  const html = markup();
  const paths = [...html.matchAll(/href="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(paths, ['/affiliate/dashboard', '/affiliate/commissions', '/support/create-ticket']);
  for (const heading of ['Referral records', 'Payment records', 'Review status', 'Transfer handling']) {
    assert.ok(html.includes(heading));
  }
  assert.match(html, /<ol[^>]+aria-label="Conceptual checks for a possible future payout service"/);
  assert.equal([...html.matchAll(/<li /g)].length, 4);
  assert.equal([...html.matchAll(/aria-labelledby=/g)].length, 3);
  assert.match(source, /focus-visible:ring-2/);
  assert.match(source, /motion-reduce:transition-none/);
  assert.match(source, /sm:grid-cols-2/);
});


test('router excludes floating chat from payout page without removing supported support links', () => {
  const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(app, /if \(location\.pathname === '\/affiliate\/payout'\) return null;/);
  assert.match(app, /<AccountChatWidget\s*\/>/);
  assert.match(source, /to="\/support\/create-ticket"/);
});
