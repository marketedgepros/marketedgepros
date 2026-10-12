import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

async function compile(name, rewrite = source => source) {
  const path = new URL(`../src/${name}`, import.meta.url);
  const target = new URL(`../node_modules/.ui5-feedback-${name.replaceAll('/', '-')}-${process.pid}.mjs`, import.meta.url);
  const source = rewrite(readFileSync(path, 'utf8'));
  const result = await transformWithEsbuild(source, name, { loader: 'jsx', jsx: 'automatic' });
  writeFileSync(target, result.code);
  try { return await import(target.href); } finally { rmSync(target, { force: true }); }
}

function dom() {
  const instance = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' });
  globalThis.window = instance.window;
  globalThis.document = instance.window.document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  instance.window.HTMLElement.prototype.scrollIntoView = function (options) { globalThis.__ui5Scroll = options; };
  instance.window.matchMedia = () => ({ matches: true });
  return { instance, root: createRoot(document.getElementById('root')), host: document.getElementById('root') };
}

const Notification = await compile('components/Notification.jsx', s => s.replace("import { notificationService } from '../services/notifications';", "const notificationService = { subscribe(callback) { globalThis.__ui5Notify = callback; return () => { globalThis.__ui5Notify = null; }; } };"));
const Toast = await compile('contexts/ToastContext.jsx');
const Chat = await compile('components/ChatWidget.jsx', s => s.replace("import api from '../services/api';", "const api = { post: (...args) => globalThis.__ui5Post(...args) };"));

test('notification is named, announces error, wraps long copy and can be dismissed', async () => {
  const d = dom();
  try {
    await act(async () => d.root.render(React.createElement(Notification.default)));
    await act(async () => globalThis.__ui5Notify({ id: 'fixture', message: 'x'.repeat(700), type: 'error', duration: 60000 }));
    assert.ok(d.host.querySelector('[role="alert"]'));
    assert.match(d.host.querySelector('p').className, /min-w-0.*break-words/);
    assert.match(d.host.firstElementChild.className, /inset-x-4/);
    await act(async () => d.host.querySelector('[aria-label="Dismiss notification"]').click());
    assert.equal(d.host.textContent, '');
  } finally { await act(async () => d.root.unmount()); d.instance.window.close(); }
});

test('toast announces status and supports an explicitly named dismiss action', async () => {
  const d = dom();
  function Trigger() {
    const toast = Toast.useToast();
    return React.createElement('button', { onClick: () => toast.info('Long status '.repeat(80), 0) }, 'Show status');
  }
  try {
    await act(async () => d.root.render(React.createElement(Toast.ToastProvider, null, React.createElement(Trigger))));
    await act(async () => d.host.querySelector('button').click());
    assert.ok(d.host.querySelector('[role="status"]'));
    assert.match(d.host.querySelector('[aria-label="Status messages"]').className, /inset-x-4/);
    await act(async () => d.host.querySelector('[aria-label="Dismiss status message"]').click());
    assert.equal(d.host.querySelector('[role="status"]'), null);
  } finally { await act(async () => d.root.unmount()); d.instance.window.close(); }
});

test('chat quick question fills exact draft and explicit Send submits once without stale draft', async () => {
  const d = dom(); const calls = [];
  globalThis.__ui5Post = async (...args) => { calls.push(args); return { data: { message: 'Synthetic response' } }; };
  try {
    await act(async () => d.root.render(React.createElement(Chat.default)));
    await act(async () => d.host.querySelector('[aria-label="Open chat"]').click());
    const quick = [...d.host.querySelectorAll('button')].find(b => b.textContent === 'What trading programs do you offer?');
    await act(async () => quick.click());
    const input = d.host.querySelector('[aria-label="Message to account assistant"]');
    assert.equal(input.value, quick.textContent);
    assert.equal(document.activeElement, input);
    assert.equal(calls.length, 0);
    await act(async () => d.host.querySelector('[aria-label="Send message"]').click());
    assert.deepEqual(calls, [['/chat/message', { message: 'What trading programs do you offer?' }]]);
    assert.ok(d.host.querySelector('[role="log"]'));
    assert.equal(globalThis.__ui5Scroll.behavior, 'auto');
    assert.doesNotMatch(d.host.textContent, /Powered by GPT-5/);
    await act(async () => d.host.querySelector('[aria-label="Close chat"]').click());
    assert.ok(d.host.querySelector('[aria-label="Open chat"]'));
  } finally { await act(async () => d.root.unmount()); d.instance.window.close(); delete globalThis.__ui5Post; }
});

test('shared CSS uses a coherent font, visible focus and motion opt-out without hiding overflow', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');
  assert.match(css, /--font-sans: Inter, system-ui/);
  assert.match(css, /:focus-visible[\s\S]*outline: 2px solid #22d3ee/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation-iteration-count: 1 !important/);
  assert.match(css, /scroll-behavior: auto !important/);
  assert.doesNotMatch(css, /overflow-x:\s*hidden/);
  assert.match(css, /font-variant-numeric: tabular-nums/);
});
