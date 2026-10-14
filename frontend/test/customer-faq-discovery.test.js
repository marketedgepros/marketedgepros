import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(frontend, 'src/pages/FAQ.jsx'), 'utf8');
const policyUrl = pathToFileURL(path.join(frontend, 'src/services/programEvaluationPolicy.js')).href;
const bootstrap = new JSDOM('<!doctype html><html><body></body></html>');
const keys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'Node', 'Event', 'MouseEvent', 'IS_REACT_ACT_ENVIRONMENT'];
function bind(dom) {
  const before = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const key of keys) Object.defineProperty(globalThis, key, { value: key === 'IS_REACT_ACT_ENVIRONMENT' ? true : dom.window[key], configurable: true, writable: true });
  return () => {
    for (const [key, descriptor] of before) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  };
}
const restoreBootstrap = bind(bootstrap);
const React = (await import('react')).default;
const { act } = await import('react');
const { createRoot } = await import('react-dom/client');
const { MemoryRouter, useLocation } = await import('react-router-dom');
restoreBootstrap();
bootstrap.window.close();
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'customer-faq-'));
let compiled = source
  .replace(/from ['"][^'"]+programEvaluationPolicy\.js['"]/, `from ${JSON.stringify(policyUrl)}`)
  .replace(/import Layout from ['"][^'"]+['"];?/, 'const Layout = ({ children }) => <>{children}</>;')
  .replace(/import StructuredData from ['"][^'"]+['"];?/, 'const StructuredData = ({ data }) => <script type="application/ld+json" data-faq-schema>{JSON.stringify(data)}</script>;');
for (const name of ['react', 'react-router-dom', 'lucide-react']) {
  compiled = compiled.replaceAll(`from '${name}'`, `from ${JSON.stringify(pathToFileURL(require.resolve(name)).href)}`);
}
const transformed = await transformWithEsbuild(compiled, 'FAQ.jsx', { loader: 'jsx', jsx: 'transform', format: 'esm' });
const target = path.join(dir, 'FAQ.mjs');
fs.writeFileSync(target, transformed.code);
const FAQ = (await import(pathToFileURL(target).href)).default;
function LocationProbe() {
  return React.createElement('output', { 'data-location': true }, useLocation().pathname);
}
async function mount() {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://faq.test/faq', pretendToBeVisual: true });
  const restore = bind(dom);
  const host = document.getElementById('root');
  const root = createRoot(host);
  await act(async () => root.render(React.createElement(MemoryRouter, { initialEntries: ['/faq'] }, React.createElement(FAQ), React.createElement(LocationProbe))));
  return { host, async close() { await act(async () => root.unmount()); restore(); dom.window.close(); } };
}
const button = (host, text) => [...host.querySelectorAll('button')].find((node) => node.textContent.trim() === text);
const questions = (host) => [...host.querySelectorAll('button[aria-expanded]')];
async function click(node) {
  assert.ok(node);
  await act(async () => node.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })));
}
async function search(host, value) {
  const node = host.querySelector('#faq-search');
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(node, value);
    node.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
}

test('customer FAQ: approved question/answer copy and complete schema remain consistent while topics filter DOM', async () => {
  const block = source.slice(source.indexOf('const categories = ['), source.indexOf('const allQuestions ='));
  assert.equal(createHash('sha256').update(block).digest('hex'), '1322eaa1b431bb33cc9aa10a81e818fe200aa22b3ab6698977357de9ce42a4a1');
  const harness = await mount();
  try {
    const { host } = harness;
    const schema = () => JSON.parse(host.querySelector('[data-faq-schema]').textContent);
    const baseline = schema();
    assert.equal(baseline.questions.length, 11);
    assert.equal(questions(host).length, 11);
    assert.equal(button(host, 'All topics').getAttribute('aria-pressed'), 'true');
    for (const [name, count] of [['Getting Started', 3], ['Programs & Rules', 3], ['Account & Payments', 3], ['Help & Information', 2]]) {
      await click(button(host, name));
      assert.equal(questions(host).length, count);
      assert.equal(button(host, name).getAttribute('aria-pressed'), 'true');
      assert.equal(host.querySelectorAll('button[aria-pressed="true"]').length, 1);
      assert.deepEqual(schema(), baseline);
    }
    await click(button(host, 'Reset filters'));
    assert.equal(questions(host).length, 11);
  } finally { await harness.close(); }
});

test('customer FAQ: topic + case-insensitive question/answer search handles empty results and distinct resets', async () => {
  const harness = await mount();
  try {
    const { host } = harness;
    await click(button(host, 'Account & Payments'));
    await search(host, '  PAYOUT  ');
    assert.equal(questions(host).length, 1);
    assert.match(host.querySelector('[role="status"]').textContent, /1 matching question in Account & Payments/);
    await search(host, 'this FAQ does not establish fees');
    assert.equal(questions(host).length, 1, 'answers are searched, not only headings');
    await search(host, 'synthetic-no-match');
    assert.equal(questions(host).length, 0);
    assert.match(host.querySelector('[role="status"]').textContent, /No questions match your search/);
    assert.equal(host.querySelector('#faq-search').getAttribute('aria-describedby'), 'faq-results-status');
    await click(button(host, 'Clear search'));
    assert.equal(questions(host).length, 3);
    assert.equal(button(host, 'Account & Payments').getAttribute('aria-pressed'), 'true');
    await search(host, 'contact');
    assert.equal(questions(host).length, 0, 'search never leaks results from another selected topic');
    await click(button(host, 'Reset filters'));
    assert.equal(questions(host).length, 11);
    assert.equal(host.querySelector('#faq-search').value, '');
  } finally { await harness.close(); }
});

test('customer FAQ: native-button semantics and accordion relationships persist and filters close old answers', async () => {
  const harness = await mount();
  try {
    const { host } = harness;
    const controls = host.querySelector('[aria-label="Filter questions by topic"]');
    assert.match(controls.className, /flex-wrap/);
    for (const node of controls.querySelectorAll('button')) {
      assert.equal(node.type, 'button');
      assert.equal(node.tabIndex, 0);
      assert.match(node.className, /focus-visible:ring-2/);
    }
    const first = questions(host)[0];
    first.focus();
    assert.equal(document.activeElement, first);
    await click(first);
    assert.equal(first.getAttribute('aria-expanded'), 'true');
    assert.equal(host.querySelector(`#${first.getAttribute('aria-controls')}`).hidden, false);
    await click(questions(host)[1]);
    assert.equal(first.getAttribute('aria-expanded'), 'false');
    assert.equal(host.querySelectorAll('button[aria-expanded="true"]').length, 1);
    await search(host, 'program');
    assert.equal(host.querySelectorAll('button[aria-expanded="true"]').length, 0);
    await click(questions(host)[0]);
    await click(button(host, 'Getting Started'));
    assert.equal(host.querySelectorAll('button[aria-expanded="true"]').length, 0);
    for (const node of questions(host)) assert.ok(host.querySelector(`#${node.getAttribute('aria-controls')}`));
    assert.match(source, /motion-reduce:transition-none/);
  } finally { await harness.close(); }
});

test('customer FAQ: answer links reach concrete existing routes through the real router, without network/storage code', async () => {
  const harness = await mount();
  try {
    const { host } = harness;
    for (const [question, label, route] of [
      ['Where can I find current program details?', 'View current programs', '/programs'],
      ['Where can I ask a question?', 'View contact options', '/contact'],
      ['Where can I find information about privacy and security?', 'View privacy information', '/privacy-policy'],
    ]) {
      await click(button(host, question));
      const control = button(host, question);
      const panel = host.querySelector(`#${control.getAttribute('aria-controls')}`);
      const link = [...panel.querySelectorAll('a')].find((node) => node.textContent.trim() === label);
      assert.equal(link.getAttribute('href'), route);
      await click(link);
      assert.equal(host.querySelector('[data-location]').textContent, route);
    }
    assert.doesNotMatch(source, /fetch\(|localStorage|sessionStorage|setInterval|axios|useEffect/);
  } finally { await harness.close(); }
});

test.after(() => fs.rmSync(dir, { recursive: true, force: true }));
