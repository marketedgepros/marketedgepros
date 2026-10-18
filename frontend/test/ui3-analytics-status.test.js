import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';

const file = new URL('../src/components/privacy/AnalyticsStatus.jsx', import.meta.url);
const target = new URL('../node_modules/.cache-ui3-analytics-status.mjs', import.meta.url);
let AnalyticsStatus;
try {
  fs.writeFileSync(target, (await transformWithEsbuild(fs.readFileSync(file, 'utf8'), file.pathname,
    { loader: 'jsx', jsx: 'automatic' })).code);
  AnalyticsStatus = (await import(target.href)).default;
} finally {
  fs.rmSync(target, { force: true });
}

test('analytics status is accessible, explicit and does not simulate an activation or consent control', () => {
  const html = renderToStaticMarkup(React.createElement(AnalyticsStatus));
  assert.match(html, /id="analytics-status"/);
  assert.match(html, /aria-labelledby="analytics-status-heading"/);
  assert.match(html, /Optional analytics is off/);
  assert.match(html, /does not load the Google Analytics integration/);
  assert.match(html, /does not clear account data or cookies left by earlier visits/);
  assert.match(html, /not an approval or replacement/);
  assert.doesNotMatch(html, /<button|<input|<form|<script|<iframe/);
});

test('initial HTML and executable source do not load or invoke retired tracking scripts', () => {
  const root = new URL('../src/', import.meta.url);
  const files = [new URL('../index.html', import.meta.url).pathname];
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const name = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(name);
      else if (/\.(jsx?|tsx?|html)$/.test(name)) files.push(name);
    }
  }
  walk(root.pathname);
  for (const name of files) {
    const source = fs.readFileSync(name, 'utf8');
    assert.doesNotMatch(source, /googletagmanager\.com|google-analytics\.com|G-WVYMLVKRFP|\bgtag\s*\(|\bfbq\s*\(|dataLayer\.push/, name);
  }
});

test('cookie route and footer share a real anchor and expose the unresolved policy status', () => {
  const page = fs.readFileSync(new URL('../src/pages/CookiePolicy.jsx', import.meta.url), 'utf8');
  const footer = fs.readFileSync(new URL('../src/components/layout/LandingFooter.jsx', import.meta.url), 'utf8');
  assert.match(page, /<AnalyticsStatus\s*\/>/);
  assert.match(page, /Cookie policy draft — awaiting approval/);
  assert.match(page, /has not been confirmed as the/);
  assert.match(footer, /to: '\/cookie-policy#analytics-status'/);
});
