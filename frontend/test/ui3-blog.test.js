import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const file = new URL('../src/pages/Blog.jsx', import.meta.url);
let source = fs.readFileSync(file, 'utf8')
  .replace(/import Layout from ['"]\.\.\/components\/layout\/Layout['"];?/, 'const Layout = ({ children }) => <div>{children}</div>;')
  .replace(/import api from ['"]\.\.\/services\/api['"];?/, 'const api = { get: async () => ({ data: {} }) };');
const transformed = await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' });
const target = new URL('../node_modules/.cache-ui3-blog-component.mjs', import.meta.url);
let component;
try {
  fs.writeFileSync(target, transformed.code);
  component = (await import(target.href)).default;
} finally {
  fs.rmSync(target, { force: true });
}
const render = () => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(component)));

test('blog provides concise navy/cyan public presentation and truthful newsletter availability navigation', () => {
  const html = render();
  assert.match(html, /Trading articles/);
  assert.match(html, /mep-screen/);
  assert.match(html, /focus:ring-cyan/);
  assert.match(html, /Newsletter subscriptions are not available/);
  assert.match(html, /href="\/contact"/);
  assert.doesNotMatch(html, /<form|Successfully subscribed|Subscribe/);
});

test('blog does not publish unsupported metrics, weekly promises, or fake tag controls', () => {
  const html = render();
  assert.doesNotMatch(html, /150\+|10K\+|Weekly Posts|exclusive tips|Popular Tags|cursor-pointer/);
  assert.doesNotMatch(source, /newsletter\/subscribe|setNewsletterStatus|popularTags/);
});

test('category consumer follows declared categories payload and uses category name as API value', () => {
  assert.match(source, /response\.data\?\.categories/);
  assert.match(source, /category\.name\)/);
  assert.match(source, /key=\{category\.name\}/);
  assert.doesNotMatch(source, /cat\.id|cat\.slug/);
});

test('retry retains selected category and search handles missing dynamic text safely', () => {
  assert.match(source, /fetchPosts\(1, selectedCategory\)/);
  assert.match(source, /typeof post\.title === 'string'/);
  assert.match(source, /typeof post\.excerpt === 'string'/);
  assert.match(source, /No posts match your search/);
  assert.match(source, /No posts are available in this view/);
  assert.doesNotMatch(source, /post\.title\.toLowerCase\(\)|post\.excerpt\.toLowerCase\(\)|\|\| 5\} min read/);
});
