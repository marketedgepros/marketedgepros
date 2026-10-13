import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hookPath = path.join(frontend, 'src', 'hooks', 'useScrollReveal.js');
const homePath = path.join(frontend, 'src', 'pages', 'NewHomePage.jsx');
const stylePath = path.join(frontend, 'src', 'components', 'visual', 'homeMotion.css');
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'marketedge-home-visual-'));
const reactUrl = pathToFileURL(require.resolve('react')).href;

const bootstrapDom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://homepage-visual.bootstrap.test/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrapDom.window, document: bootstrapDom.window.document, navigator: bootstrapDom.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
}
const { createRoot } = await import('react-dom/client');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrapDom.window.close();

async function loadHook() {
  const source = fs.readFileSync(hookPath, 'utf8');
  const transformed = await transformWithEsbuild(source, hookPath, { loader: 'js', format: 'esm' });
  const target = path.join(tempDir, `useScrollReveal-${Date.now()}-${Math.random().toString(16).slice(2)}.mjs`);
  const code = transformed.code.replace(/from ["']react["']/g, `from ${JSON.stringify(reactUrl)}`);
  fs.writeFileSync(target, code);
  return import(`${pathToFileURL(target).href}?visual=${Date.now()}`);
}

function installDom({ reducedMotion = false, IntersectionObserver } = {}) {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
    url: 'http://homepage-visual.test/',
    pretendToBeVisual: true,
  });
  const listeners = new Set();
  const mediaQuery = {
    matches: reducedMotion,
    addEventListener: (event, listener) => { if (event === 'change') listeners.add(listener); },
    removeEventListener: (event, listener) => { if (event === 'change') listeners.delete(listener); },
  };
  dom.window.matchMedia = () => mediaQuery;
  if (IntersectionObserver) dom.window.IntersectionObserver = IntersectionObserver;

  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'IS_REACT_ACT_ENVIRONMENT'];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(values)) {
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  }

  return {
    container: dom.window.document.getElementById('root'),
    listenerCount: () => listeners.size,
    restore: () => {
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      dom.window.close();
    },
  };
}

async function mountReveal(useScrollReveal, container) {
  function Probe() {
    const reveal = useScrollReveal();
    return React.createElement('section', {
      ref: reveal.ref,
      className: reveal.className,
      'data-reveal-state': reveal.state,
    }, 'Visible homepage content');
  }

  const root = createRoot(container);
  await act(async () => root.render(React.createElement(Probe)));
  return { root, target: container.querySelector('section') };
}

class FakeIntersectionObserver {
  static instances = [];

  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.disconnectCalls = 0;
    this.unobserveCalls = 0;
    FakeIntersectionObserver.instances.push(this);
  }

  observe(target) {
    this.target = target;
  }

  unobserve(target) {
    assert.equal(target, this.target);
    this.unobserveCalls += 1;
  }

  disconnect() {
    this.disconnectCalls += 1;
  }

  reveal() {
    this.callback([{ target: this.target, isIntersecting: true }]);
  }
}

test('homepage restored artwork keeps source paths, intrinsic dimensions, and truthful accessible descriptions', () => {
  const page = fs.readFileSync(homePath, 'utf8');

  assert.match(page, /src="\/images\/abstract-trading-flow\.webp"[^>]*alt=""[^>]*width="1536"[^>]*height="1024"/);
  assert.match(page, /src="\/images\/hero-trading-3d\.webp"[^>]*alt="Decorative illustration of trading charts on three screens"[^>]*width="1536"[^>]*height="1024"/);
  assert.match(page, /src="\/images\/stats-globe-hologram\.webp"[^>]*alt=""[^>]*width="1024"[^>]*height="1024"/);
  assert.match(page, /Illustrative artwork, not a live platform view or account performance\./);
  assert.match(page, /A quote is not a payment, funded account, or account activation/);
  assert.match(page, /Payment availability is checked separately for your account in checkout/);
  assert.match(page, /<figure[^>]*>/);
  assert.match(page, /<figcaption[^>]*>/);
});

test('visual CSS bounds illumination, reserves hover for fine pointers, and disables motion for reduced motion', () => {
  const css = fs.readFileSync(stylePath, 'utf8');
  assert.match(css, /animation:\s*homeMotionGlowBreath\s+2\.4s\s+ease-in-out\s+infinite;/);
  assert.equal([...css.matchAll(/animation:[^;]*infinite/g)].length, 4, "only four visible-section decorative layers repeat");
  assert.match(css, /@media \(hover: hover\) and \(pointer: fine\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /transform:\s*none\s*!important/);
  assert.match(css, /animation:\s*none\s*!important/);
});

test('scroll reveal uses one observer, reveals once, and disposes its work after intersection', async () => {
  FakeIntersectionObserver.instances = [];
  const dom = installDom({ IntersectionObserver: FakeIntersectionObserver });
  try {
    const { default: useScrollReveal } = await loadHook();
    const { root, target } = await mountReveal(useScrollReveal, dom.container);
    const observer = FakeIntersectionObserver.instances[0];

    assert.equal(FakeIntersectionObserver.instances.length, 1);
    assert.equal(target.dataset.revealState, 'pending');
    assert.match(target.className, /scroll-reveal--pending/);
    assert.equal(observer.options.threshold, 0.08);

    await act(async () => observer.reveal());
    assert.equal(target.dataset.revealState, 'revealed');
    assert.match(target.className, /scroll-reveal--revealed/);
    assert.equal(observer.unobserveCalls, 1);
    assert.equal(observer.disconnectCalls, 1);

    await act(async () => root.unmount());
    assert.equal(observer.disconnectCalls, 1, 'cleanup does not leave a second active observer');
  } finally {
    dom.restore();
  }
});

test('scroll reveal leaves content static without an observer and skips observer work for reduced motion', async () => {
  const withoutObserver = installDom();
  try {
    const { default: useScrollReveal } = await loadHook();
    const { root, target } = await mountReveal(useScrollReveal, withoutObserver.container);
    assert.equal(target.dataset.revealState, 'visible');
    assert.equal(target.className, '');
    await act(async () => root.unmount());
  } finally {
    withoutObserver.restore();
  }

  FakeIntersectionObserver.instances = [];
  const reduced = installDom({ reducedMotion: true, IntersectionObserver: FakeIntersectionObserver });
  try {
    const { default: useScrollReveal } = await loadHook();
    const { root, target } = await mountReveal(useScrollReveal, reduced.container);
    assert.equal(target.dataset.revealState, 'visible');
    assert.equal(target.className, '');
    assert.equal(FakeIntersectionObserver.instances.length, 0);
    assert.equal(reduced.listenerCount(), 1);
    await act(async () => root.unmount());
    assert.equal(reduced.listenerCount(), 0, 'media preference listener is cleaned up');
  } finally {
    reduced.restore();
  }
});

test('reveal implementation has no animation frame or polling loop', () => {
  const hook = fs.readFileSync(hookPath, 'utf8');
  assert.doesNotMatch(hook, /requestAnimationFrame|setInterval/);
  assert.match(hook, /observer\.unobserve\(target\)/);
  assert.match(hook, /observer\.disconnect\(\)/);
});
