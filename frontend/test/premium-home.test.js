import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';
import React, { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';
const require = createRequire(import.meta.url);
const src = new URL('../src/', import.meta.url);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'premium-home-'));
const urls = Object.fromEntries(['react', 'react/jsx-runtime', 'react-router-dom', 'lucide-react'].map((name) => [name, pathToFileURL(require.resolve(name)).href]));
const externalize = (text) => Object.entries(urls).reduce((s, [name, url]) => s.replaceAll(`from '${name}'`, `from ${JSON.stringify(url)}`).replaceAll(`from "${name}"`, `from ${JSON.stringify(url)}`), text);
async function compile(name, text) {
  const code = await transformWithEsbuild(externalize(text), name + '.jsx', { loader: 'jsx', format: 'esm', jsx: 'automatic' });
  const target = path.join(tmp, name + '.mjs'); fs.writeFileSync(target, externalize(code.code));
  return { url: pathToFileURL(target).href, module: await import(pathToFileURL(target).href) };
}
const reveal = await compile('reveal', fs.readFileSync(new URL('hooks/useScrollReveal.js', src), 'utf8'));
const ambient = await compile('ambient', fs.readFileSync(new URL('hooks/useAmbientMotion.js', src), 'utf8').replace("'./useScrollReveal'", JSON.stringify(reveal.url)));
const showcase = await compile('showcase', fs.readFileSync(new URL('components/visual/PlatformShowcase.jsx', src), 'utf8'));
const bootstrap = new JSDOM('<!doctype html><body></body>');
Object.defineProperty(globalThis, 'window', { configurable: true, writable: true, value: bootstrap.window });
Object.defineProperty(globalThis, 'document', { configurable: true, writable: true, value: bootstrap.window.document });
const { createRoot } = await import('react-dom/client');
delete globalThis.window; delete globalThis.document; bootstrap.window.close();
function dom({ reduced = false, observer = true } = {}) {
  const d = new JSDOM('<!doctype html><body><div id="root"></div></body>', { url: 'https://isolated.invalid/', pretendToBeVisual: true });
  const listeners = new Set();
  d.window.matchMedia = () => ({ matches: reduced, addEventListener: (_, fn) => listeners.add(fn), removeEventListener: (_, fn) => listeners.delete(fn) });
  const instances = [];
  class Observer {
    constructor(cb) { this.cb = cb; this.disconnected = false; instances.push(this); }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
    visible(value) { this.cb([{ target: this.target, isIntersecting: value }]); }
  }
  if (observer) d.window.IntersectionObserver = Observer;
  const previous = new Map();
  for (const [key, value] of Object.entries({ window: d.window, document: d.window.document, navigator: d.window.navigator, HTMLElement: d.window.HTMLElement, Node: d.window.Node, IS_REACT_ACT_ENVIRONMENT: true })) {
    previous.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  }
  const host = d.window.document.getElementById('root'); const root = createRoot(host);
  return { d, host, root, instances, listeners, async close() { await act(async () => root.unmount()); for (const [k, desc] of previous) { if (desc) Object.defineProperty(globalThis, k, desc); else delete globalThis[k]; } d.window.close(); } };
}
const click = async (node) => { assert.ok(node); await act(async () => node.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))); };
test('premium workspace changes real visible content and destinations without customer data or provider actions', async () => {
  const h = dom();
  try {
    await act(async () => h.root.render(React.createElement(MemoryRouter, null, React.createElement(showcase.module.default))));
    assert.match(h.host.textContent, /Illustrative preview · not live data/);
    assert.equal(h.host.querySelector('a').getAttribute('href'), '/profile');
    const buttons = [...h.host.querySelectorAll('button')];
    await click(buttons.find((b) => b.textContent === 'Challenges'));
    assert.equal(h.host.querySelector('a').getAttribute('href'), '/challenges');
    assert.match(h.host.textContent, /See the details behind the challenge/);
    assert.equal(buttons.filter((b) => b.getAttribute('aria-pressed') === 'true').length, 1);
    await click(buttons.find((b) => b.textContent === 'Support'));
    assert.equal(h.host.querySelector('a').getAttribute('href'), '/support/my-tickets');
    assert.match(h.host.textContent, /Keep the conversation together/);
    assert.match(h.host.querySelector('[aria-live]').textContent, /Support workspace preview selected/);
    assert.equal(h.host.querySelectorAll('input,canvas,video,iframe').length, 0);
    assert.ok(h.host.querySelector('[aria-label="Illustrative workspace preview"] [aria-hidden="true"]'));
  } finally { await h.close(); }
});
function Probe() {
  const m = ambient.module.default();
  return React.createElement('section', { ref: m.ref, 'data-running': String(m.running) }, React.createElement('button', { disabled: m.reduced, onClick: m.togglePaused }, m.paused ? 'Resume' : 'Pause'));
}
test('ambient motion pauses offscreen, on document hide and by user, then cleans its observer/listener', async () => {
  const h = dom();
  try {
    await act(async () => h.root.render(React.createElement(Probe)));
    const running = () => h.host.querySelector('section').dataset.running;
    assert.equal(running(), 'false'); assert.equal(h.instances.length, 1);
    const o = h.instances[0];
    await act(async () => o.visible(true)); assert.equal(running(), 'true');
    await click(h.host.querySelector('button')); assert.equal(running(), 'false');
    await click(h.host.querySelector('button')); assert.equal(running(), 'true');
    await act(async () => o.visible(false)); assert.equal(running(), 'false');
    await act(async () => o.visible(true));
    Object.defineProperty(h.d.window.document, 'visibilityState', { configurable: true, value: 'hidden' });
    await act(async () => h.d.window.document.dispatchEvent(new h.d.window.Event('visibilitychange'))); assert.equal(running(), 'false');
    Object.defineProperty(h.d.window.document, 'visibilityState', { configurable: true, value: 'visible' });
    await act(async () => h.d.window.document.dispatchEvent(new h.d.window.Event('visibilitychange'))); assert.equal(running(), 'true');
    await act(async () => h.root.unmount()); assert.equal(o.disconnected, true); assert.equal(h.listeners.size, 0);
    // A late observer delivery must not perform work after cleanup.
    o.visible(true);
  } finally { await h.close(); }
});
test('reduced motion and unavailable observer keep ambient illustration static', async () => {
  for (const options of [{ reduced: true }, { observer: false }]) {
    const h = dom(options);
    try { await act(async () => h.root.render(React.createElement(Probe))); if (h.instances.length) await act(async () => h.instances[0].visible(true)); assert.equal(h.host.querySelector('section').dataset.running, 'false'); if (options.reduced) assert.equal(h.host.querySelector('button').disabled, true); }
    finally { await h.close(); }
  }
});
test('premium motion is bounded, pauses by data attribute, has no feed or polling, and preserves own image paths', () => {
  const css = fs.readFileSync(new URL('components/visual/homeMotion.css', src), 'utf8');
  const hook = fs.readFileSync(new URL('hooks/useAmbientMotion.js', src), 'utf8');
  const home = fs.readFileSync(new URL('pages/NewHomePage.jsx', src), 'utf8');
  assert.doesNotMatch(css, /infinite/); assert.match(css, /premiumLightSweep 8s ease-in-out 2/); assert.match(css, /premiumArtworkFloat 6s ease-in-out 3/);
  assert.match(css, /animation-play-state: paused/); assert.match(css, /prefers-reduced-motion: reduce/); assert.doesNotMatch(hook, /requestAnimationFrame|setInterval|fetch\(/);
  assert.match(home, /CatalogPreview interactive/); assert.match(home, /Pause visual motion/); assert.match(home, /hero-trading-3d.webp/);
});
test.after(() => fs.rmSync(tmp, { force: true, recursive: true }));

const homeSource = fs.readFileSync(new URL('pages/NewHomePage.jsx', src), 'utf8')
  .replace(/import SchemaMarkup[^;]+;/, 'const SchemaMarkup = () => null;')
  .replace(/import CatalogPreview[^;]+;/, 'const CatalogPreview = () => null;')
  .replace(/import Layout[^;]+;/, 'const Layout = ({children}) => <main>{children}</main>;')
  .replace("'../hooks/useScrollReveal'", JSON.stringify(reveal.url))
  .replace("'../hooks/useAmbientMotion'", JSON.stringify(ambient.url))
  .replace("'../components/visual/PlatformShowcase'", JSON.stringify(showcase.url))
  .replace(/import '[^']+\.css';/, '');
const homeModule = await compile('centred-globe-home', homeSource);
test('centred globe uses real help destinations, shared pause, independent visibility and a static reduced-motion fallback', async () => {
  for (const reduced of [false,true]) {
    const h = dom({reduced});
    try {
      await act(async () => h.root.render(React.createElement(MemoryRouter,null,React.createElement(homeModule.module.default))));
      const globe=h.host.querySelector('#home-help');
      assert.ok(globe); assert.equal(globe.getAttribute('aria-labelledby'),'home-help-heading');
      assert.equal(globe.querySelector('img').getAttribute('src'),'/images/stats-globe-hologram.webp');
      const originalImage=globe.querySelector('img');
      const motionHost=h.host.querySelector('.home-motion');
      assert.equal(motionHost.dataset.motionReplay,'false');
      assert.equal(globe.querySelector('img').getAttribute('loading'),'lazy');
      assert.ok(globe.querySelector('[aria-hidden="true"] img'));
      assert.deepEqual([...globe.querySelectorAll('a')].map(a=>a.getAttribute('href')),['/faq','/support','/programs']);
      const observer=h.instances.find(o=>o.target===globe); assert.ok(observer);
      await act(async()=>observer.visible(true));
      assert.equal(globe.dataset.motionRunning,String(!reduced));
      if (!reduced) {
        await click(globe.querySelector('button'));
        assert.equal(globe.dataset.motionRunning,'false');
        assert.equal(h.host.querySelector('.home-motion').dataset.visualPaused,'true');
        await click(globe.querySelector('button'));
        assert.equal(globe.dataset.motionRunning,'true');
        assert.equal(motionHost.dataset.motionReplay,'true');
        assert.equal(globe.querySelector('img'),originalImage);
        const heroButton=h.host.querySelector('.premium-hero button');
        await click(heroButton);
        assert.equal(globe.dataset.motionRunning,'false');
        await click(heroButton);
        assert.equal(globe.dataset.motionRunning,'true');
        assert.equal(motionHost.dataset.motionReplay,'false');
        assert.equal(globe.querySelector('img'),originalImage);
        await act(async()=>observer.visible(false)); assert.equal(globe.dataset.motionRunning,'false');
        await act(async()=>observer.visible(true));
        assert.equal(motionHost.dataset.motionReplay,'false');
      } else assert.equal(globe.querySelector('button').disabled,true);
      assert.equal(globe.querySelectorAll('canvas,video,iframe').length,0);
    } finally { await h.close(); }
  }
  const css=fs.readFileSync(new URL('components/visual/homeMotion.css',src),'utf8');
  assert.match(css,/homeHelpGlobeFloat 8s ease-in-out 3/);
  assert.match(css,/width: min\(112vw, 42rem\)/);
  assert.match(css,/\.home-help-globe\[data-motion-running="true"\]/);
  assert.doesNotMatch(css,/infinite/);
});

test('resume uses equivalent finite keyframes for every ambient layer, including the visible mobile light', () => {
  const css=fs.readFileSync(new URL('components/visual/homeMotion.css',src),'utf8');
  for (const name of ['premiumLightSweep','premiumArtworkFloat','homeMotionGlowBreath','homeHelpGlobeFloat']) {
    const block=(n)=>new RegExp('@keyframes '+n+' \\{([\\s\\S]*?)\\n\\}').exec(css)?.[1].trim().replace(/\s+/g,' ');
    assert.ok(block(name));assert.equal(block(name+'Replay'),block(name));
    assert.match(css,new RegExp('animation-name: '+name+'Replay'));
  }
  assert.doesNotMatch(css,/\.premium-hero__beam \{ animation: none; \}/);
  assert.match(css,/radial-gradient\(ellipse at 60% 22%/);
});
