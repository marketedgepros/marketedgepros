import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = (...parts) => path.join(frontend, 'src', ...parts);
const srcUrl = (...parts) => pathToFileURL(src(...parts)).href;
const jsdomPackage = JSON.parse(fs.readFileSync(require.resolve('jsdom/package.json'), 'utf8'));
assert.equal(jsdomPackage.version, '28.1.0', 'UI6 catalog DOM evidence requires the pinned jsdom 28.1.0 package');

// ReactDOM is deliberately imported only after a DOM bootstrap. This avoids the
// synthetic-event feature detection racing the per-test JSDOM environments.
const bootstrap = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6-catalog.test/' });
const bootstrapKeys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'Node', 'Event', 'MouseEvent', 'IS_REACT_ACT_ENVIRONMENT'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({
  window: bootstrap.window,
  document: bootstrap.window.document,
  navigator: bootstrap.window.navigator,
  HTMLElement: bootstrap.window.HTMLElement,
  HTMLInputElement: bootstrap.window.HTMLInputElement,
  Node: bootstrap.window.Node,
  Event: bootstrap.window.Event,
  MouseEvent: bootstrap.window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
})) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
const React = (await import('react')).default;
const { act } = await import('react');
const { createRoot } = await import('react-dom/client');
const { MemoryRouter, Route, Routes, useLocation } = await import('react-router-dom');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-catalog-dom-'));
const external = new Map([
  ['react', pathToFileURL(require.resolve('react')).href],
  ['react/jsx-runtime', pathToFileURL(require.resolve('react/jsx-runtime')).href],
  ['react/jsx-dev-runtime', pathToFileURL(require.resolve('react/jsx-dev-runtime')).href],
  ['react-router-dom', pathToFileURL(require.resolve('react-router-dom')).href],
  ['lucide-react', pathToFileURL(require.resolve('lucide-react')).href],
]);
let serial = 0;
const externalize = (code) => [...external].reduce((out, [name, url]) => (
  out
    .replaceAll(`from '${name}'`, `from ${JSON.stringify(url)}`)
    .replaceAll(`from "${name}"`, `from ${JSON.stringify(url)}`)
), code);
const boundedImport = async (url, label) => Promise.race([
  import(`${url}?ui6-catalog=${process.pid}-${serial}`),
  new Promise((_, reject) => setTimeout(() => reject(new Error(`Timed out importing ${label}`)), 5000)),
]);
async function compile(name, sourceText) {
  const target = path.join(tempDir, `${name}-${serial += 1}.mjs`);
  const transformed = await transformWithEsbuild(externalize(sourceText), `${name}.jsx`, {
    loader: 'jsx', jsx: 'automatic', format: 'esm',
  });
  fs.writeFileSync(target, externalize(transformed.code));
  return boundedImport(pathToFileURL(target).href, name);
}
const replaceModule = (text, specifier, url) => text
  .replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`)
  .replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);

const authStubPath = path.join(tempDir, 'auth.mjs');
fs.writeFileSync(authStubPath, `
  export default function useAuthStore(selector) {
    const state = globalThis.__ui6CatalogAuth || { user: null, isAuthenticated: false, isLoading: false };
    return typeof selector === 'function' ? selector(state) : state;
  }
`);
const authStub = pathToFileURL(authStubPath).href;

let hookSource = fs.readFileSync(src('hooks', 'useProgramCatalog.js'), 'utf8');
hookSource = replaceModule(hookSource, '../services/programCatalogViewService.js', srcUrl('services', 'programCatalogViewService.js'));
hookSource = replaceModule(hookSource, '../store/authStore', authStub);
const hookModule = await compile('use-program-catalog', hookSource);
const hookUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('use-program-catalog-')))).href;

let uiSource = fs.readFileSync(src('components', 'programs', 'CatalogUI.jsx'), 'utf8');
uiSource = uiSource
  .replace(/import Layout from ['"]\.\.\/layout\/Layout['"];?/, 'const Layout = ({ children }) => <main data-ui6-layout="catalog">{children}</main>;')
  .replace(/['"]\.\.\/\.\.\/services\/programCatalogViewService['"]/, JSON.stringify(srcUrl('services', 'programCatalogViewService.js')));
const catalogUi = await compile('catalog-ui', uiSource);
const catalogUiUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('catalog-ui-')))).href;

let selectorSource = fs.readFileSync(src('components', 'programs', 'ProgramSelector.jsx'), 'utf8').replace(/import ['"][^'"]+\.css['"];?/, '');
selectorSource = replaceModule(selectorSource, './CatalogUI', catalogUiUrl);
selectorSource = replaceModule(selectorSource, '../../services/programCatalogViewService', srcUrl('services', 'programCatalogViewService.js'));
const ProgramSelector = (await compile('program-selector', selectorSource)).default;
const selectorUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('program-selector-')))).href;

let comparisonSource = fs.readFileSync(src('components', 'programs', 'ProgramComparison.jsx'), 'utf8').replace(/import ['"][^'"]+\.css['"];?/, '');
comparisonSource = replaceModule(comparisonSource, '../../services/programCatalogViewService', srcUrl('services', 'programCatalogViewService.js'));
const ProgramComparison = (await compile('program-comparison', comparisonSource)).default;
const comparisonUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('program-comparison-')))).href;

let previewSource = fs.readFileSync(src('components', 'programs', 'CatalogPreview.jsx'), 'utf8');
previewSource = replaceModule(previewSource, '../../hooks/useProgramCatalog', hookUrl);
previewSource = replaceModule(previewSource, './CatalogUI', catalogUiUrl);
previewSource = replaceModule(previewSource, './ProgramSelector', selectorUrl);
const CatalogPreview = (await compile('catalog-preview', previewSource)).default;
const previewUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('catalog-preview-')))).href;

let programsSource = fs.readFileSync(src('pages', 'ProgramsNew.jsx'), 'utf8');
programsSource = replaceModule(programsSource, '../hooks/useProgramCatalog', hookUrl);
programsSource = replaceModule(programsSource, '../services/programCatalogViewService', srcUrl('services', 'programCatalogViewService.js'));
programsSource = replaceModule(programsSource, '../components/programs/CatalogUI', catalogUiUrl);
programsSource = replaceModule(programsSource, '../components/programs/ProgramSelector', selectorUrl);
programsSource = replaceModule(programsSource, '../components/programs/ProgramComparison', comparisonUrl);
const ProgramsNew = (await compile('programs-new', programsSource)).default;

let detailsSource = fs.readFileSync(src('pages', 'ProgramDetails.jsx'), 'utf8');
detailsSource = replaceModule(detailsSource, '../store/authStore', authStub);
detailsSource = replaceModule(detailsSource, '../hooks/useProgramCatalog', hookUrl);
detailsSource = replaceModule(detailsSource, '../services/programCatalogViewService', srcUrl('services', 'programCatalogViewService.js'));
detailsSource = replaceModule(detailsSource, '../components/programs/CatalogUI', catalogUiUrl);
const ProgramDetails = (await compile('program-details', detailsSource)).default;

let loginSource = fs.readFileSync(src('pages', 'Login.jsx'), 'utf8');
loginSource = loginSource.replace(/import Layout from ['"]\.{2}\/components\/layout\/Layout['"];?/, 'const Layout = ({ children }) => <main>{children}</main>;');
loginSource = replaceModule(loginSource, '../store/authStore', authStub);
loginSource = replaceModule(loginSource, '../services/navigationService.js', srcUrl('services', 'navigationService.js'));
const Login = (await compile('login-return', loginSource)).default;

let checkoutSource = fs.readFileSync(src('pages', 'Checkout.jsx'), 'utf8');
checkoutSource = replaceModule(checkoutSource, '../store/authStore', authStub);
checkoutSource = replaceModule(checkoutSource, '../hooks/useProgramCatalog', hookUrl);
checkoutSource = replaceModule(checkoutSource, '../constants/roles', srcUrl('constants', 'roles.js'));
checkoutSource = replaceModule(checkoutSource, '../services/programCatalogViewService', srcUrl('services', 'programCatalogViewService.js'));
checkoutSource = replaceModule(checkoutSource, '../services/orderQuoteViewService', srcUrl('services', 'orderQuoteViewService.js'));
checkoutSource = replaceModule(checkoutSource, '../components/programs/CatalogUI', catalogUiUrl);
const Checkout = (await compile('checkout', checkoutSource)).default;

let lightningSource = fs.readFileSync(src('pages', 'LightningChallenge.jsx'), 'utf8');
lightningSource = lightningSource
  .replace(/import Layout from ['"]\.\.\/components\/layout\/Layout['"];?/, 'const Layout = ({ children }) => <main data-ui6-layout="lightning">{children}</main>;')
  .replace(/import SEO from ['"]\.\.\/components\/SEO['"];?/, 'const SEO = () => null;');
lightningSource = replaceModule(lightningSource, '../components/programs/CatalogPreview', previewUrl);
const LightningChallenge = (await compile('lightning-challenge', lightningSource)).default;

const api = (await import(srcUrl('services', 'api.js'))).default;
const { normalizeCatalogList } = await import(srcUrl('services', 'programCatalogViewService.js'));

function terms(name, type) {
  return {
    name, type, description: null, account_size: '25000.00', profit_target: '8.00',
    max_daily_loss: '4.00', max_total_loss: '8.00', profit_split: '80.00',
    profit_split_percentage: '80.00', minimum_payout_amount: null, payout_mode: null,
    rules: { synthetic_rule: 'Recorded synthetic value' },
  };
}
function program(id = 12, type = 'two_phase', name = 'Two phase synthetic') {
  const value = terms(name, type);
  return {
    ...value, id, tenant_id: 1, currency: 'USD', price: '199.99', is_active: true, terms: value,
    addons: [{ id: 9, program_id: id, name: 'Synthetic add-on', description: 'Synthetic option', price: '2.50', price_type: 'percentage', benefits: {}, is_active: true }],
  };
}
function selectorProgram(id, { name, type, accountSize, price }) {
  const value = terms(name, type);
  value.account_size = accountSize;
  value.profit_target = null;
  value.max_daily_loss = null;
  value.max_total_loss = null;
  value.profit_split = null;
  return {
    ...value, id, tenant_id: 1, currency: 'USD', price, is_active: true, terms: value,
  };
}
const listFixture = () => ({ programs: [program(12, 'two_phase', 'Two phase synthetic'), program(13, 'lightning', 'Lightning synthetic')] });
function quoteFixture({ ownerId = 41 } = {}) {
  const snapshotTerms = terms('Two phase synthetic', 'two_phase');
  return {
    replayed: false,
    order: {
      id: 'synthetic-order-12', program_id: 12, user_id: ownerId, tenant_id: 1,
      amount_minor: '21999', amount: '219.99', currency: 'USD', state: 'quoted', paid: false,
      snapshot_hash: 'a'.repeat(64),
      snapshot: {
        schema: 1, kind: 'purchase_quote', program_id: 12, currency: 'USD', amount: '219.99', entitlement: false,
        user_id: ownerId, tenant_id: 1, base_amount: '199.99', terms: snapshotTerms,
        addons: [{ id: 9, name: 'Synthetic add-on', price_type: 'percentage', catalog_price: '2.50', amount: '20.00', benefits: {} }],
      },
    },
  };
}
const response = (config, data) => ({ data, status: 200, statusText: 'OK', headers: {}, config, request: { synthetic: true } });
const apiError = (status = 500, message = 'Synthetic catalog failure') => Object.assign(new Error(message), { response: { status, data: { error: message } } });

function installDom(pathname = '/') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: `http://ui6-catalog.test${pathname}`, pretendToBeVisual: true });
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLAnchorElement', 'Node', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle', 'localStorage', 'IS_REACT_ACT_ENVIRONMENT'];
  const before = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement, HTMLInputElement: dom.window.HTMLInputElement, HTMLAnchorElement: dom.window.HTMLAnchorElement,
    Node: dom.window.Node, Event: dom.window.Event, MouseEvent: dom.window.MouseEvent, KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver, getComputedStyle: dom.window.getComputedStyle.bind(dom.window), localStorage: dom.window.localStorage,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(bindings)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom, root, host: dom.window.document.getElementById('root'),
    async close() {
      await act(async () => root.unmount());
      for (const [key, descriptor] of before) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      dom.window.close();
    },
  };
}
async function settle() {
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await Promise.resolve();
}
async function waitFor(check, label) {
  let lastError;
  for (let count = 0; count < 80; count += 1) {
    try { const value = check(); if (value) return value; } catch (error) { lastError = error; }
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); await settle(); });
  }
  throw lastError || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected a DOM action target');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
function button(host, text) {
  return [...host.querySelectorAll('button')].find((node) => node.textContent.replace(/\s+/g, ' ').trim() === text);
}
function anchor(host, text) {
  return [...host.querySelectorAll('a')].find((node) => node.textContent.replace(/\s+/g, ' ').trim().includes(text));
}
function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { 'data-location': 'true', 'data-state': JSON.stringify(location.state ?? null) }, `${location.pathname}${location.search}${location.hash}`);
}
const h = React.createElement;
async function renderRouter(harness, child, initial, key = 'ui6') {
  await act(async () => {
    harness.root.render(h(MemoryRouter, { initialEntries: [initial], key }, child, h(LocationProbe)));
    await settle();
  });
}
function assertSignal(config, operation) {
  assert.ok(config.signal instanceof AbortSignal, `${operation} carries a concrete AbortSignal`);
  assert.equal(config.signal.aborted, false, `${operation} starts before cancellation`);
}

// This is DOM behavior through the real hook and production view-service source;
// its adapter is synthetic and cannot contact a provider or persisted store.
test('UI6 catalog: Programs DOM loads via a signal-bound synthetic catalog, filters, anchors, and retry/empty states', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/programs');
  let mode = 'held';
  let releaseList;
  const gate = new Promise((resolve) => { releaseList = resolve; });
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config);
    assert.equal(config.method, 'get');
    assert.equal(config.url, '/programs/');
    assertSignal(config, 'catalog list');
    if (mode === 'held') { await gate; return response(config, listFixture()); }
    if (mode === 'failure') throw apiError();
    if (mode === 'empty') return response(config, { programs: [] });
    return response(config, listFixture());
  };
  globalThis.__ui6CatalogAuth = { user: null, isAuthenticated: false, isLoading: false };
  try {
    await renderRouter(harness, h(ProgramsNew), '/programs', 'programs-held');
    await waitFor(() => harness.host.querySelector('[aria-busy="true"]'), 'catalog loading DOM state');
    releaseList();
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'catalog result');

    const comparison = anchor(harness.host, 'Compare programs');
    assert.equal(comparison.getAttribute('href'), '#program-comparison');
    assert.ok(harness.host.querySelector('#program-comparison'), 'the hash target is a real DOM element');

    const comparisonFilter = harness.host.querySelector('[aria-label="Filter by program type"]');
    await click(button(comparisonFilter, 'Two phase'));
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/programs?filter=two_phase');
    assert.equal(button(comparisonFilter, 'Two phase').getAttribute('aria-pressed'), 'true');
    assert.equal(harness.host.querySelector('#program-catalog').textContent.includes('Lightning synthetic'), false, 'filter changes the rendered cards rather than a source-only value');

    const detail = anchor(harness.host, 'View rules & options');
    assert.equal(detail.getAttribute('href'), '/programs/12');
    await click(detail);
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/programs/12');

    mode = 'failure';
    await renderRouter(harness, h(ProgramsNew), '/programs', 'programs-failure');
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'catalog failure state');
    assert.match(harness.host.textContent, /The current catalog could not be loaded\. No saved or substitute prices are being shown\./);
    const support = anchor(harness.host, 'Contact support');
    assert.equal(support.getAttribute('href'), '/support/create-ticket');
    await click(support);
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/support/create-ticket');

    mode = 'success';
    await renderRouter(harness, h(ProgramsNew), '/programs', 'programs-retry');
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'fresh mount before retry assertion');
    mode = 'failure';
    await renderRouter(harness, h(ProgramsNew), '/programs', 'programs-retry-failure');
    await waitFor(() => button(harness.host, 'Try again'), 'retry control');
    const readsBeforeRetry = calls.length;
    mode = 'success';
    await click(button(harness.host, 'Try again'));
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'retry result');
    assert.equal(calls.length, readsBeforeRetry + 1, 'Retry creates a fresh signal-bound catalog read');

    mode = 'empty';
    await renderRouter(harness, h(ProgramsNew), '/programs', 'programs-empty');
    await waitFor(() => harness.host.textContent.includes('No active programs available'), 'empty catalog state');
    assert.equal(button(harness.host, 'Try again'), undefined, 'empty data never invents a retryable successful catalog');
    mode = 'success';
    globalThis.__ui6CatalogAuth = { user: { id: 41, tenant_id: 1, role: 'user' }, isAuthenticated: true, isLoading: false };
    await renderRouter(harness, h(ProgramsNew), '/programs', 'programs-permitted-remount');
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'permitted public catalog remount');
    assert.match(harness.host.innerHTML, /(?:sm|md|xl):/, 'the shared catalog DOM retains its responsive layout classes');
    assert.ok(calls.every((config) => config.url === '/programs/' && config.method === 'get'), 'catalog UI issued no write or provider activation');
  } finally {
    api.defaults.adapter = previousAdapter;
    await harness.close();
  }
});

test('UI6 catalog: ProgramSelector uses normalized props without mutation, preserves duplicate choices, and discards stale selections', { concurrency: false }, async () => {
  const harness = installDom('/programs');
  const initialPrograms = Object.freeze(normalizeCatalogList({ programs: [
    selectorProgram(21, { name: 'Custom Duplicate A', type: 'custom_route', accountSize: '25000.00', price: '199.99' }),
    selectorProgram(22, { name: 'Custom Duplicate B', type: 'custom_route', accountSize: '25000.00', price: '299.99' }),
    selectorProgram(23, { name: 'Custom Fifty', type: 'custom_route', accountSize: '50000.00', price: '399.99' }),
    selectorProgram(24, { name: 'One phase fixture', type: 'one_phase', accountSize: '10000.00', price: '109.99' }),
  ] }));
  const inputOrder = initialPrograms.map((program) => program.id);
  const replacementPrograms = Object.freeze(normalizeCatalogList({ programs: [
    selectorProgram(29, { name: 'Fresh replacement', type: 'fresh_type', accountSize: '15000.00', price: '149.99' }),
  ] }));
  try {
    await renderRouter(harness, h(ProgramSelector, { programs: initialPrograms }), '/programs', 'program-selector');
    await waitFor(() => harness.host.querySelector('[data-selected-program-id="21"]'), 'initial normalized selection');
    assert.equal(button(harness.host, 'custom route').getAttribute('aria-pressed'), 'true', 'an unknown normalized type remains a selectable type');
    assert.match(harness.host.textContent, /Not specified/, 'NULL rules are rendered by ProgramRules, not coerced to zero');

    const duplicateGroup = harness.host.querySelector('[aria-label="Program chooser: choose matching program"]');
    assert.ok(duplicateGroup, 'duplicate type/size records retain a dedicated selection group');
    await click(button(duplicateGroup, 'Custom Duplicate B #22'));
    await waitFor(() => harness.host.querySelector('[data-selected-program-id="22"]'), 'duplicate program selection');
    assert.equal(anchor(harness.host, 'Review selected program').getAttribute('href'), '/programs/22', 'the selected card retains its concrete program route');
    assert.match(harness.host.textContent, /USD 299\.99/, 'the selected duplicate uses its exact catalog price');

    await click(button(harness.host, 'USD 50,000.00'));
    await waitFor(() => harness.host.querySelector('[data-selected-program-id="23"]'), 'account size selection');
    await click(button(harness.host, 'One phase'));
    await waitFor(() => harness.host.querySelector('[data-selected-program-id="24"]'), 'type selection');
    assert.deepEqual(initialPrograms.map((program) => program.id), inputOrder, 'selector interactions never sort or mutate the supplied normalized list');

    await renderRouter(harness, h(ProgramSelector, { programs: replacementPrograms }), '/programs', 'program-selector');
    await waitFor(() => harness.host.querySelector('[data-selected-program-id="29"]'), 'fresh prop selection');
    assert.equal(harness.host.textContent.includes('One phase fixture'), false, 'a removed selected ID never renders as a stale foreign card');
    assert.equal(anchor(harness.host, 'Review selected program').getAttribute('href'), '/programs/29');

    await renderRouter(harness, h(ProgramSelector, { programs: [] }), '/programs', 'program-selector');
    await waitFor(() => !harness.host.querySelector('[data-program-selector]'), 'empty selector props');
    assert.equal(harness.host.querySelector('[data-selected-program-id]'), null, 'empty data does not retain a selected card');
  } finally {
    await harness.close();
  }
});

test('UI6 catalog: CatalogPreview keeps its default card list and interactive selection makes no additional catalog read', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/');
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config);
    assert.equal(config.method, 'get');
    assert.equal(config.url, '/programs/');
    return response(config, listFixture());
  };
  try {
    globalThis.__ui6CatalogAuth = { user: null, isAuthenticated: false, isLoading: false };
    await renderRouter(harness, h(CatalogPreview, { interactive: true }), '/', 'interactive-preview');
    await waitFor(() => harness.host.querySelector('[data-program-selector]'), 'interactive preview selector');
    assert.equal(harness.host.querySelectorAll('[data-selected-program-id]').length, 1, 'interactive preview renders one current selected card');
    await click(button(harness.host, 'Lightning'));
    await waitFor(() => harness.host.querySelector('[data-selected-program-id="13"]'), 'interactive preview type selection');
    assert.equal(anchor(harness.host, 'Review selected program').getAttribute('href'), '/programs/13');
    assert.equal(calls.length, 1, 'changing an interactive selection only consumes the already-loaded catalog result');
  } finally {
    api.defaults.adapter = previousAdapter;
    await harness.close();
  }
});

test('UI6 catalog: detail DOM handles public guest/permitted destinations and BackToPrograms Router action', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/programs/12');
  const calls = [];
  let detailMode = 'success';
  api.defaults.adapter = async (config) => {
    calls.push(config);
    assert.equal(config.method, 'get');
    assert.equal(config.url, '/programs/12');
    assertSignal(config, 'catalog detail');
    if (detailMode === 'failure') throw apiError();
    return response(config, program());
  };
  const routes = h(Routes, null,
    h(Route, { path: '/programs/:id', element: h(ProgramDetails) }),
    h(Route, { path: '*', element: h('p', null, 'destination reached') }),
  );
  try {
    globalThis.__ui6CatalogAuth = { user: null, isAuthenticated: false, isLoading: false };
    await renderRouter(harness, routes, '/programs/12', 'detail-guest');
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'guest public detail');
    await click(button(harness.host, 'Check quote availability'));
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/login?redirect=%2Fprograms%2F12%2Fcheckout');
    assert.deepEqual(JSON.parse(harness.host.querySelector('[data-location]').getAttribute('data-state')), { from: '/programs/12/checkout' });

    globalThis.__ui6CatalogAuth = { user: { id: 41, tenant_id: 1, role: 'user' }, isAuthenticated: true, isLoading: false };
    await renderRouter(harness, routes, '/programs/12', 'detail-permitted');
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'permitted public detail');
    await click(button(harness.host, 'Check quote availability'));
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/programs/12/checkout');

    await renderRouter(harness, routes, '/programs/12', 'detail-back');
    await waitFor(() => anchor(harness.host, 'All programs'), 'BackToPrograms link');
    const back = anchor(harness.host, 'All programs');
    assert.equal(back.getAttribute('href'), '/programs');
    await click(back);
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/programs');
    detailMode = 'failure';
    await renderRouter(harness, routes, '/programs/12', 'detail-failure');
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'detail catalog failure');
    detailMode = 'success';
    await click(button(harness.host, 'Try again'));
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'detail retry result');
    assert.match(harness.host.innerHTML, /(?:sm|lg):/, 'detail DOM retains shared responsive layout classes');
    assert.ok(calls.length >= 3, 'remount/Router returns re-read the current public catalog detail');
  } finally {
    api.defaults.adapter = previousAdapter;
    await harness.close();
  }
});

test('customer detail: successful direct and 2FA sign-in returns through real Login and navigation service to selected checkout', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/programs/12');
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config);
    assert.equal(config.method, 'get', 'no quote or payment is submitted on return');
    assert.equal(config.url, '/programs/12');
    return response(config, program());
  };
  const routes = () => h(Routes, null,
    h(Route, { path: '/programs/:id', element: h(ProgramDetails) }),
    h(Route, { path: '/login', element: h(Login) }),
    h(Route, { path: '/programs/:programId/checkout', element: h(Checkout) }),
  );
  const type = async (node, value) => act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(node, value);
    node.dispatchEvent(new window.Event('input', { bubbles: true }));
    await settle();
  });
  const submit = async () => act(async () => {
    harness.host.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await settle();
  });
  try {
    for (const twoFactor of [false, true]) {
      const principal = { id: 41, tenant_id: 1, role: 'user' };
      const state = {
        user: null, isAuthenticated: false, isLoading: false, pending2FA: null,
        error: null, clearError() {}, cancel2FA() { state.pending2FA = null; },
        async login(email, password) {
          assert.equal(email, 'synthetic@example.test');
          assert.equal(password, 'SyntheticPassword9');
          if (twoFactor) { state.pending2FA = { userId: 41 }; return { requires2FA: true, userId: 41 }; }
          state.user = principal; state.isAuthenticated = true;
          return { requires2FA: false, user: principal };
        },
        async login2FA(userId, token) {
          assert.equal(userId, 41); assert.equal(token, '123456');
          assert.ok(state.pending2FA, 'transient password proof is retained until verification');
          state.user = principal; state.isAuthenticated = true; state.pending2FA = null;
          return { user: principal };
        },
      };
      globalThis.__ui6CatalogAuth = state;
      await renderRouter(harness, routes(), '/programs/12', `return-${twoFactor}`);
      await waitFor(() => button(harness.host, 'Check quote availability'), 'selected program');
      await click(button(harness.host, 'Check quote availability'));
      assert.equal(harness.host.querySelector('[data-location]').textContent, '/login?redirect=%2Fprograms%2F12%2Fcheckout');
      await type(harness.host.querySelector('#login-email'), 'synthetic@example.test');
      await type(harness.host.querySelector('#login-password'), 'SyntheticPassword9');
      await submit();
      if (twoFactor) {
        await waitFor(() => harness.host.querySelector('#two-factor-code'), '2FA challenge');
        assert.equal(harness.host.querySelector('[data-location]').textContent, '/login?redirect=%2Fprograms%2F12%2Fcheckout');
        await type(harness.host.querySelector('#two-factor-code'), '123456');
        await submit();
      }
      await waitFor(() => harness.host.querySelector('[data-location]').textContent === '/programs/12/checkout', 'actual selected checkout return');
      await waitFor(() => button(harness.host, 'Request server quote'), 'real unpaid checkout UI');
      assert.match(harness.host.textContent, /Quotes only\. Payments are not enabled\./);
    }
    assert.ok(calls.length >= 4);
  } finally { api.defaults.adapter = previousAdapter; await harness.close(); }
});

test('customer detail: jump links and help destinations use current catalog without extra reads or inferred missing values', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/programs/12');
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config);
    assert.equal(config.method, 'get');
    assert.equal(config.url, '/programs/12');
    const value = program();
    value.terms.profit_target = null;
    value.profit_target = null;
    value.terms.rules.synthetic_missing = null;
    return response(config, value);
  };
  const routes = h(Routes, null,
    h(Route, { path: '/programs/:id', element: h(ProgramDetails) }),
    h(Route, { path: '*', element: h('p', null, 'help destination reached') }),
  );
  try {
    globalThis.__ui6CatalogAuth = { user: null, isAuthenticated: false, isLoading: false };
    await renderRouter(harness, routes, '/programs/12', 'detail-jumps');
    await waitFor(() => harness.host.querySelector('[aria-label="On this program page"]'), 'detail navigation');
    const nav = harness.host.querySelector('[aria-label="On this program page"]');
    assert.match(nav.className, /flex-wrap/);
    const before = calls.length;
    for (const target of ['program-rules', 'program-addons', 'program-additional', 'program-next-step']) {
      const link = nav.querySelector(`a[href="/programs/12#${target}"]`);
      assert.ok(link);
      const node = harness.host.querySelector(`#${target}`);
      assert.ok(node);
      assert.match(node.className, /scroll-mt-28/);
      await click(link);
      assert.equal(harness.host.querySelector('[data-location]').textContent, `/programs/12#${target}`);
    }
    assert.equal(calls.length, before, 'hash-only navigation never requests catalog again');
    const ruleLabel = [...harness.host.querySelectorAll('dt')].find((node) => node.textContent === 'Profit target');
    assert.equal(ruleLabel.nextElementSibling.textContent, 'Not specified');
    assert.match(harness.host.textContent, /does not mean zero or no restriction/);
    assert.match(harness.host.textContent, /USD 199\.99/);
    assert.match(harness.host.textContent, /Quotes only\. Payments are not enabled\./);
    assert.match(harness.host.textContent, /does not confirm that a quote is available/);
    await click(anchor(harness.host, 'Browse FAQ'));
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/faq');
    await renderRouter(harness, routes, '/programs/12', 'detail-contact');
    await waitFor(() => anchor(harness.host, 'Contact options'), 'contact help');
    await click(anchor(harness.host, 'Contact options'));
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/contact');
  } finally { api.defaults.adapter = previousAdapter; await harness.close(); }
});

test('customer detail: same-mount identity/route changes hide old navigation and terms while held or failed', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/programs/12');
  let mode = 'success';
  let release;
  let signal;
  api.defaults.adapter = async (config) => {
    assert.equal(config.method, 'get');
    signal = config.signal;
    if (mode === 'held') await new Promise((resolve) => { release = resolve; });
    if (mode === 'failure') throw apiError();
    return response(config, program(Number(config.url.split('/').at(-1))));
  };
  const routes = () => h(Routes, null,
    h(Route, { path: '/programs/:id', element: h(ProgramDetails) }),
    h(Route, { path: '*', element: h('p', null, 'destination') }),
  );
  try {
    globalThis.__ui6CatalogAuth = { user: null, isAuthenticated: false, isLoading: false };
    await renderRouter(harness, routes(), '/programs/12', 'detail-scope');
    await waitFor(() => harness.host.querySelector('#program-next-step'), 'initial detail');
    const oldSignal = signal;
    mode = 'held';
    globalThis.__ui6CatalogAuth = { user: { id: 41, tenant_id: 1 }, isAuthenticated: true, isLoading: false };
    // The stub is not a subscribed store: renew the element to model the render
    // that a real Zustand identity subscription emits, retaining the same router.
    await renderRouter(harness, routes(), '/programs/12', 'detail-scope');
    await waitFor(() => release && harness.host.querySelector('[aria-busy="true"]'), 'identity read held');
    assert.equal(oldSignal.aborted, true);
    assert.equal(harness.host.querySelector('#program-next-step'), null);
    assert.equal(harness.host.querySelector('[aria-label="On this program page"]'), null);
    assert.equal(harness.host.textContent.includes('USD 199.99'), false);
    mode = 'success';
    await act(async () => { release(); await settle(); });
    await waitFor(() => harness.host.querySelector('#program-next-step'), 'identity read restored');
    mode = 'failure';
    await renderRouter(harness, routes(), '/programs/99', 'detail-new-route');
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'new route error');
    assert.equal(harness.host.querySelector('#program-next-step'), null);
    assert.equal(harness.host.querySelector('[aria-label="On this program page"]'), null);
  } finally { api.defaults.adapter = previousAdapter; await harness.close(); }
});

test('UI6 catalog: checkout DOM blocks guest/admin routes and reveals an unpaid quote only after matching synthetic owner acknowledgement', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/programs/12/checkout');
  const calls = [];
  let quoteMode = 'bad-owner';
  let catalogMode = 'success';
  let releaseCatalog;
  let catalogGate;
  api.defaults.adapter = async (config) => {
    calls.push(config);
    assertSignal(config, 'checkout request');
    if (config.method === 'get') {
      assert.equal(config.url, '/programs/12');
      if (catalogMode === 'held') await catalogGate;
      if (catalogMode === 'failure') throw apiError();
      return response(config, program());
    }
    assert.equal(config.method, 'post');
    assert.equal(config.url, '/orders/');
    const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
    assert.deepEqual(body, { program_id: 12, addon_ids: [9] }, 'mutated add-on state is the canonical quote payload');
    assert.match(config.headers['Idempotency-Key'], /^[A-Za-z0-9_-]{16,128}$/);
    return response(config, quoteFixture({ ownerId: quoteMode === 'bad-owner' ? 99 : 41 }));
  };
  const checkoutRoutes = h(Routes, null,
    h(Route, { path: '/programs/:programId/checkout', element: h(Checkout) }),
    h(Route, { path: '*', element: h('p', null, 'destination reached') }),
  );
  try {
    globalThis.__ui6CatalogAuth = { user: null, isAuthenticated: false, isLoading: false };
    await renderRouter(harness, checkoutRoutes, '/programs/12/checkout', 'checkout-guest');
    await waitFor(() => harness.host.querySelector('[data-location]').textContent === '/login', 'guest checkout redirect');
    assert.deepEqual(JSON.parse(harness.host.querySelector('[data-location]').getAttribute('data-state')), { from: '/programs/12/checkout' });

    globalThis.__ui6CatalogAuth = { user: { id: 7, tenant_id: 1, role: 'master' }, isAuthenticated: true, isLoading: false };
    await renderRouter(harness, checkoutRoutes, '/programs/12/checkout', 'checkout-admin');
    await waitFor(() => harness.host.querySelector('[data-location]').textContent === '/admin', 'forbidden administrator checkout redirect');

    globalThis.__ui6CatalogAuth = { user: { id: 41, tenant_id: 1, role: 'user' }, isAuthenticated: true, isLoading: false };
    await renderRouter(harness, checkoutRoutes, '/programs/12/checkout', 'checkout-user');
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'permitted checkout catalog');
    const rules = anchor(harness.host, 'View all rules');
    assert.equal(rules.getAttribute('href'), '/programs/12');
    await click(rules);
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/programs/12');

    await renderRouter(harness, checkoutRoutes, '/programs/12/checkout', 'checkout-user-quote');
    await waitFor(() => harness.host.querySelector('input[type="checkbox"]'), 'add-on control');
    await click(harness.host.querySelector('input[type="checkbox"]'));
    await click(button(harness.host, 'Request server quote'));
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'owner mismatch rejection');
    assert.match(harness.host.textContent, /Quote owner and brand is unavailable or invalid/);
    assert.equal(harness.host.textContent.includes('Quoted — not paid'), false, 'a mismatched owner acknowledgement is never shown as a quote');
    const postCalls = calls.filter((config) => config.method === 'post');
    assert.equal(postCalls.length, 1);

    quoteMode = 'success';
    await click(button(harness.host, 'Retry server quote'));
    await waitFor(() => harness.host.textContent.includes('Quoted — not paid'), 'matching owner acknowledgement');
    assert.match(harness.host.textContent, /USD 219\.99/);
    const retryCalls = calls.filter((config) => config.method === 'post');
    assert.equal(retryCalls.length, 2);
    assert.equal(retryCalls[0].headers['Idempotency-Key'], retryCalls[1].headers['Idempotency-Key'], 'unchanged selection retries with the same idempotency key');

    const support = anchor(harness.host, 'Ask about availability');
    assert.equal(support.getAttribute('href'), '/support/create-ticket');
    await click(support);
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/support/create-ticket');

    catalogMode = 'held';
    catalogGate = new Promise((resolve) => { releaseCatalog = resolve; });
    await renderRouter(harness, checkoutRoutes, '/programs/12/checkout', 'checkout-loading-remount');
    await waitFor(() => harness.host.querySelector('[aria-busy="true"]'), 'checkout loading state');
    releaseCatalog();
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'checkout reload after loading');
    assert.match(harness.host.innerHTML, /(?:sm|lg):/, 'checkout DOM retains its shared responsive layout classes');

    catalogMode = 'failure';
    await renderRouter(harness, checkoutRoutes, '/programs/12/checkout', 'checkout-failure');
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'checkout catalog failure');
    catalogMode = 'success';
    await click(button(harness.host, 'Try again'));
    await waitFor(() => harness.host.textContent.includes('Two phase synthetic'), 'checkout retry after failure');
    assert.ok(calls.every((config) => ['get', 'post'].includes(config.method)), 'checkout test made only synthetic catalog reads and quote requests');
  } finally {
    api.defaults.adapter = previousAdapter;
    await harness.close();
  }
});

test('UI6 catalog: Lightning DOM exposes real hash targets, static rule boundary, preview router action, and public remount', { concurrency: false }, async () => {
  const previousAdapter = api.defaults.adapter;
  const harness = installDom('/lightning-challenge');
  const calls = [];
  let lightningMode = 'success';
  let releaseLightning;
  let lightningGate;
  api.defaults.adapter = async (config) => {
    calls.push(config);
    assert.equal(config.method, 'get');
    assert.equal(config.url, '/programs/');
    assertSignal(config, 'lightning catalog preview');
    if (lightningMode === 'held') await lightningGate;
    if (lightningMode === 'failure') throw apiError();
    if (lightningMode === 'empty') return response(config, { programs: [] });
    return response(config, listFixture());
  };
  try {
    globalThis.__ui6CatalogAuth = { user: null, isAuthenticated: false, isLoading: false };
    await renderRouter(harness, h(LightningChallenge), '/lightning-challenge', 'lightning-guest');
    await waitFor(() => harness.host.textContent.includes('Lightning synthetic'), 'guest lightning catalog');
    for (const target of ['programs', 'important-information']) {
      const link = harness.host.querySelector(`a[href="#${target}"]`);
      assert.ok(link, `hash anchor #${target} is real`);
      assert.equal(harness.host.querySelector(`#${target}`) !== null, true, `hash target #${target} exists in the same DOM`);
    }
    const rules = anchor(harness.host, 'Review published trading rules');
    assert.equal(rules.getAttribute('href'), '/trading-rules', 'external static route remains an anchor boundary, not a provider action');
    const compare = anchor(harness.host, 'Compare all current programs');
    assert.equal(compare.getAttribute('href'), '/programs');
    await click(compare);
    assert.equal(harness.host.querySelector('[data-location]').textContent, '/programs');

    lightningMode = 'held';
    lightningGate = new Promise((resolve) => { releaseLightning = resolve; });
    await renderRouter(harness, h(LightningChallenge), '/lightning-challenge', 'lightning-loading');
    await waitFor(() => harness.host.querySelector('[aria-busy="true"]'), 'lightning loading state');
    releaseLightning();
    await waitFor(() => harness.host.textContent.includes('Lightning synthetic'), 'lightning loading recovery');
    lightningMode = 'failure';
    await renderRouter(harness, h(LightningChallenge), '/lightning-challenge', 'lightning-failure');
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'lightning catalog failure');
    lightningMode = 'success';
    await click(button(harness.host, 'Try again'));
    await waitFor(() => harness.host.textContent.includes('Lightning synthetic'), 'lightning retry result');
    lightningMode = 'empty';
    await renderRouter(harness, h(LightningChallenge), '/lightning-challenge', 'lightning-empty');
    await waitFor(() => harness.host.textContent.includes('No active programs available'), 'lightning empty catalog');
    assert.equal(button(harness.host, 'Try again'), undefined, 'empty Lightning catalog does not fabricate a successful retry');

    lightningMode = 'success';
    globalThis.__ui6CatalogAuth = { user: { id: 41, tenant_id: 1, role: 'user' }, isAuthenticated: true, isLoading: false };
    await renderRouter(harness, h(LightningChallenge), '/lightning-challenge', 'lightning-permitted-remount');
    await waitFor(() => harness.host.textContent.includes('Lightning synthetic'), 'permitted public remount');
    assert.match(harness.host.innerHTML, /(?:sm|lg):/, 'Lightning DOM retains shared responsive layout classes');
    assert.ok(calls.length >= 6, 'MemoryRouter remount confirms the public route has no retained success state');
  } finally {
    api.defaults.adapter = previousAdapter;
    await harness.close();
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
