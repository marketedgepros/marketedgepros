import assert from 'node:assert/strict';
import test from 'node:test';
import React, { act, lazy, Suspense } from 'react';
import { JSDOM } from 'jsdom';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom';
import RouteScrollManager from '../src/components/RouteScrollManager.js';

const h = React.createElement;
async function fixture(entry = '/source', delayed = false) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'https://scroll.example.test/' });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
  const calls = [];
  window.scrollTo = (options) => calls.push(['window', options]);
  dom.window.HTMLElement.prototype.scrollTo = function (options) { calls.push(['container', this.id, options]); };
  dom.window.HTMLElement.prototype.scrollIntoView = function (options) { calls.push(['anchor', this.id, options]); };
  let navigate;
  let resolvePage;
  const DelayedPage = lazy(() => new Promise((resolve) => { resolvePage = resolve; }));
  function Probe() { navigate = useNavigate(); return null; }
  function Page() { return h('main', { id: 'admin-scroll', 'data-route-scroll-container': true }, h('h2', { id: 'section with space' }, 'Destination')); }
  const root = createRoot(document.getElementById('root'));
  await act(async () => root.render(h(MemoryRouter, { initialEntries: [entry] },
    h(Probe), h(Suspense, { fallback: h('span', null, 'loading') },
      h(RouteScrollManager), h(Routes, null,
        h(Route, { path: '/source', element: h(Page) }),
        h(Route, { path: '/destination', element: delayed ? h(DelayedPage) : h(Page) }))))));
  return {
    calls,
    async go(to, options) { await act(async () => navigate(to, options)); },
    async ready() { await act(async () => resolvePage({ default: Page })); },
    async close() { await act(async () => root.unmount()); dom.window.close(); },
  };
}

test('route scroll: new path PUSH and REPLACE reset window and marked admin container instantly', async () => {
  const f = await fixture();
  try {
    assert.deepEqual(f.calls, [], 'initial load does not override native reload restoration');
    await f.go('/destination');
    assert.deepEqual(f.calls, [['window', { top: 0, left: 0, behavior: 'instant' }], ['container', 'admin-scroll', { top: 0, left: 0, behavior: 'instant' }]]);
    f.calls.length = 0;
    await f.go('/source', { replace: true });
    assert.equal(f.calls.length, 2);
    assert.equal(f.calls[0][1].top, 0);
  } finally { await f.close(); }
});

test('route scroll: POP, query-only and same-path navigation do not reset reading position', async () => {
  const f = await fixture();
  try {
    await f.go('/source?filter=active');
    await f.go('/source');
    assert.deepEqual(f.calls, []);
    await f.go('/destination');
    f.calls.length = 0;
    await f.go(-1);
    assert.deepEqual(f.calls, [], 'back navigation stays owned by native history');
  } finally { await f.close(); }
});

test('route scroll: decoded same-page and cross-page anchors target the committed DOM, never the top', async () => {
  const f = await fixture();
  try {
    await f.go('/source#section%20with%20space');
    assert.deepEqual(f.calls.map((x) => x.slice(0, 2)), [['anchor', 'section with space']]);
    f.calls.length = 0;
    await f.go('/destination#section%20with%20space');
    assert.deepEqual(f.calls.map((x) => x.slice(0, 2)), [['anchor', 'section with space']]);
    f.calls.length = 0;
    await f.go('/source#%broken');
    assert.equal(f.calls[0][0], 'window', 'malformed/missing hash fails safely to new-page top');
  } finally { await f.close(); }
});

test('route scroll: lazy destination resolves before anchor lookup; no polling or stale scheduled scroll', async () => {
  const f = await fixture('/source', true);
  try {
    await f.go('/destination#section%20with%20space');
    assert.deepEqual(f.calls, [], 'loading fallback must not scroll');
    await f.ready();
    assert.deepEqual(f.calls.map((x) => x.slice(0, 2)), [['anchor', 'section with space']]);
  } finally { await f.close(); }
});
