import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';

const file = new URL('../src/pages/AboutUs.jsx', import.meta.url);
const source = fs.readFileSync(file, 'utf8');
const isolatedSource = source.replace("import Layout from '../components/layout/Layout';", 'const Layout = ({ children }) => children;');
const transformed = await transformWithEsbuild(isolatedSource, file.pathname, { loader: 'jsx', jsx: 'automatic' });
const target = new URL('../node_modules/.cache-ui3-about-us-test.mjs', import.meta.url);
let AboutUs;
try {
  fs.writeFileSync(target, transformed.code);
  AboutUs = (await import(target.href)).default;
} finally {
  fs.rmSync(target, { force: true });
}
const html = renderToStaticMarkup(React.createElement(AboutUs));

test('About Us renders company overview and useful catalog navigation', () => {
  assert.match(html, /About MarketEdgePros/);
  assert.match(html, /A clear place to explore our programs/);
  assert.match(html, /program information in an online catalog/);
  assert.match(html, /Browse programs/);
  assert.match(html, /View program catalog/);
  assert.deepEqual([...html.matchAll(/href="([^"]+)"/g)].map((match) => match[1]), ['/programs', '/programs']);
});

test('About Us does not publish unverified people, milestones, ratings, statistics, or commercial promises', () => {
  assert.doesNotMatch(html, /David Chen|Sarah Williams|Michael Rodriguez|Emma Thompson|Company Founded|First 1,000 Traders|Global Recognition|Achievements|Industry Leader/);
  assert.doesNotMatch(html, /\$10M|5,000|120\+|90%|85%|300%|top 5|funded trader|profit split|instant payout|time limits on challenges|substantial trading capital/);
  assert.match(html, /does not establish program or payment terms/);
  assert.match(html, /Availability and displayed terms are specific to each program/);
});

test('About Us preserves accessible section names, visible focus, reduced motion, and responsive layout', () => {
  assert.match(html, /<main/);
  assert.match(html, /aria-labelledby="about-title"/);
  assert.match(html, /aria-labelledby="approach-title"/);
  assert.match(html, /aria-labelledby="next-title"/);
  assert.match(source, /focus-visible:ring-2/);
  assert.match(source, /motion-reduce:transition-none/);
  assert.match(source, /md:grid-cols-3/);
});
