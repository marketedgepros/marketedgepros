import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';
import api from '../src/services/api.js';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-affiliate-dom-'));
let serial = 0;
const compiledUrls = new Map();

// JSDOM is intentionally the direct, exact dev dependency declared by frontend/package.json.
assert.equal(JSON.parse(fs.readFileSync(path.join(frontend, 'node_modules', 'jsdom', 'package.json'), 'utf8')).version, '28.1.0');

// react-dom/client observes the DOM during import. Bootstrap it before the lazy import,
// then each test receives a fresh JSDOM document below.
const bootstrapDom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://marketedgepros.com/' });
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

const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const externalImports = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
]);

function makeImportable(code) {
  for (const [specifier, url] of externalImports) {
    code = code
      .replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`)
      .replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
  }
  return code;
}

function writeModule(name, code) {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, code);
  return pathToFileURL(target).href;
}

async function compileSource(name, original, replacements = []) {
  let source = original;
  for (const [from, to] of replacements) source = source.replaceAll(from, to);
  const transformed = await transformWithEsbuild(makeImportable(source), `${name}.jsx`, { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  const target = path.join(tempDir, `${name}-${serial += 1}.mjs`);
  fs.writeFileSync(target, makeImportable(transformed.code));
  const url = pathToFileURL(target).href;
  compiledUrls.set(name, url);
  return import(`${url}?ui6-affiliate=${serial}`);
}

const authStub = writeModule('auth.mjs', `
  export default function useAuthStore(selector) {
    const state = globalThis.__ui6AffiliateAuth || { isAuthenticated: false, isLoading: false, user: null, init() {} };
    return typeof selector === 'function' ? selector(state) : state;
  }
  useAuthStore.subscribe = () => () => {};
`);
const layoutStub = writeModule('layout.mjs', 'export default function Layout({ children }) { return children; }\n');

const roleGuardModule = await compileSource(
  'RoleGuard',
  fs.readFileSync(sourcePath('components', 'guards', 'RoleGuard.jsx'), 'utf8'),
  [["'../../store/authStore'", JSON.stringify(authStub)]],
);
const roleGuardUrl = compiledUrls.get('RoleGuard');

const landingModule = await compileSource(
  'AffiliateLanding',
  fs.readFileSync(sourcePath('pages', 'affiliate', 'AffiliateLanding.jsx'), 'utf8'),
  [
    ["import Layout from '../../components/layout/Layout';", `import Layout from ${JSON.stringify(layoutStub)};`],
    ["import useAuthStore from '../../store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`],
    ["'../../services/affiliateProgramViewService'", JSON.stringify(sourceUrl('services', 'affiliateProgramViewService.js'))],
  ],
);
const dashboardModule = await compileSource(
  'AffiliateDashboard',
  fs.readFileSync(sourcePath('pages', 'affiliate', 'AffiliateDashboard.jsx'), 'utf8'),
  [
    ["import useAuthStore from '../../store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`],
    ["'../../services/affiliateViewService'", JSON.stringify(sourceUrl('services', 'affiliateViewService.js'))],
  ],
);
const payoutModule = await compileSource(
  'AffiliatePayout',
  fs.readFileSync(sourcePath('pages', 'affiliate', 'AffiliatePayout.jsx'), 'utf8'),
);
const recordUiModule = await compileSource(
  'AffiliateRecordUI',
  fs.readFileSync(sourcePath('components', 'affiliate', 'AffiliateRecordUI.jsx'), 'utf8'),
  [["'../../services/affiliateRecordViewService.js'", JSON.stringify(sourceUrl('services', 'affiliateRecordViewService.js'))]],
);
const recordUiUrl = compiledUrls.get('AffiliateRecordUI');
const commissionsModule = await compileSource(
  'Commissions',
  fs.readFileSync(sourcePath('pages', 'agent', 'Commissions.jsx'), 'utf8'),
  [
    ["import useAuthStore from '../../store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`],
    ["'../../services/affiliateRecordViewService.js'", JSON.stringify(sourceUrl('services', 'affiliateRecordViewService.js'))],
    ["'../../hooks/useAffiliateAccountRead.js'", JSON.stringify(sourceUrl('hooks', 'useAffiliateAccountRead.js'))],
    ["'../../components/affiliate/AffiliateRecordUI.jsx'", JSON.stringify(recordUiUrl)],
  ],
);
const tradersModule = await compileSource(
  'TradersManagement',
  fs.readFileSync(sourcePath('pages', 'agent', 'TradersManagement.jsx'), 'utf8'),
  [
    ["import useAuthStore from '../../store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`],
    ["'../../services/affiliateRecordViewService.js'", JSON.stringify(sourceUrl('services', 'affiliateRecordViewService.js'))],
    ["'../../hooks/useAffiliateAccountRead.js'", JSON.stringify(sourceUrl('hooks', 'useAffiliateAccountRead.js'))],
    ["'../../components/affiliate/AffiliateRecordUI.jsx'", JSON.stringify(recordUiUrl)],
  ],
);
const reportsModule = await compileSource(
  'Reports',
  fs.readFileSync(sourcePath('pages', 'agent', 'Reports.jsx'), 'utf8'),
  [
    ["import useAuthStore from '../../store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`],
    ["'../../services/affiliateViewService.js'", JSON.stringify(sourceUrl('services', 'affiliateViewService.js'))],
    ["'../../hooks/useAffiliateAccountRead.js'", JSON.stringify(sourceUrl('hooks', 'useAffiliateAccountRead.js'))],
    ["'../../components/affiliate/AffiliateRecordUI.jsx'", JSON.stringify(recordUiUrl)],
  ],
);

let appSource = fs.readFileSync(sourcePath('App.jsx'), 'utf8')
  .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", `import { MemoryRouter, Routes, Route, Navigate } from ${JSON.stringify(dependencyUrl('react-router-dom'))};`)
  .replace("import { useLocation } from 'react-router-dom';", `import { useLocation } from ${JSON.stringify(dependencyUrl('react-router-dom'))};`)
  .replace("import useAuthStore from './store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`)
  .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
  .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
  .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
  .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['admin'];")
  .replace("import { postLoginDestination } from './services/navigationService.js';", "const postLoginDestination = () => '/dashboard';")
  .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
  .replace("import useNotificationStore from './stores/notificationStore.js';", 'const useNotificationStore = { getState: () => ({ reset() {} }) };')
  .replace("import RoleGuard from './components/guards/RoleGuard';", `import RoleGuard from ${JSON.stringify(roleGuardUrl)};`)
  .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6AffiliateInitialEntries}>')
  .replace('</BrowserRouter>', '</MemoryRouter>');
appSource = appSource.replace(/const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\(['"][^'"]+['"]\)\);/g, (_all, name) => (
  `const ${name} = ({ children }) => <div data-ui6-route="${name}">{children || '${name}'}</div>;`
));
assert.equal((appSource.match(/=\s*lazy\(/g) || []).length, 0, 'all App lazy leaves are inert probes only in this test module');
appSource = appSource
  .replace('function App() {', 'function Ui6LocationProbe() { const location = useLocation(); return <output data-ui6-location="true">{location.pathname + location.search + location.hash}</output>; }\n\nfunction App() {')
  .replace('</Routes>', '</Routes><Ui6LocationProbe />');
const appModule = await compileSource('AffiliateRoutesApp', appSource);

const Landing = landingModule.default;
const Dashboard = dashboardModule.default;
const Payout = payoutModule.default;
const Commissions = commissionsModule.default;
const Traders = tradersModule.default;
const Reports = reportsModule.default;
const App = appModule.default;

function installDom(url = 'https://marketedgepros.com/') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url, pretendToBeVisual: true });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'HTMLAnchorElement',
    'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle', 'localStorage',
    'requestAnimationFrame', 'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT',
  ];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    HTMLAnchorElement: dom.window.HTMLAnchorElement,
    Node: dom.window.Node,
    Element: dom.window.Element,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    localStorage: dom.window.localStorage,
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom,
    root,
    host: dom.window.document.getElementById('root'),
    async close() {
      await act(async () => { root.unmount(); });
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      dom.window.close();
    },
  };
}

function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { 'data-ui6-location': 'true' }, `${location.pathname}${location.search}${location.hash}`);
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function waitFor(predicate, label) {
  let lastError;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const result = predicate();
      if (result) return result;
    } catch (error) { lastError = error; }
    await act(async () => { await settle(); });
  }
  throw lastError || new Error(`Timed out waiting for ${label}`);
}

async function mount(Component, { entry = '/', props = {}, url = 'https://marketedgepros.com/' } = {}) {
  const harness = installDom(url);
  await act(async () => {
    harness.root.render(React.createElement(MemoryRouter, { initialEntries: [entry] },
      React.createElement(Component, props),
      React.createElement(LocationProbe),
    ));
    await settle();
  });
  return harness;
}

async function click(element) {
  assert.ok(element, 'expected an actionable DOM element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}

async function setControlValue(element, value) {
  assert.ok(element, 'expected an input/select control');
  const prototype = element.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
  const previous = element.value;
  if (setter) setter.call(element, value);
  else element.value = value;
  element._valueTracker?.setValue(previous);
  const reactPropsKey = Object.keys(element).find((key) => key.startsWith('__reactProps$'));
  const reactProps = reactPropsKey ? element[reactPropsKey] : null;
  await act(async () => {
    if (typeof reactProps?.onChange === 'function') reactProps.onChange({ target: element });
    else {
      element.dispatchEvent(new window.Event('input', { bubbles: true, cancelable: true }));
      element.dispatchEvent(new window.Event('change', { bubbles: true, cancelable: true }));
    }
    await settle();
  });
}

function text() { return document.body.textContent.replace(/\s+/g, ' ').trim(); }
function button(label) { return [...document.querySelectorAll('button')].find((item) => item.textContent.replace(/\s+/g, ' ').trim() === label || item.textContent.includes(label)); }
function anchorByText(label) { return [...document.querySelectorAll('a')].find((item) => item.textContent.replace(/\s+/g, ' ').trim().includes(label)); }
function response(config, data, status = 200) {
  return { data, status, statusText: status === 201 ? 'Created' : 'OK', headers: {}, config, request: {} };
}
function setAuth(user = null) {
  globalThis.__ui6AffiliateAuth = {
    isAuthenticated: Boolean(user), isLoading: false, user,
    init() {}, logout: async () => ({ acknowledged: true }),
  };
}

const owner = { user_id: 19, tenant_id: 6 };
const affiliateUser = { id: owner.user_id, tenant_id: owner.tenant_id, role: 'affiliate', first_name: 'Avery' };
const flags = { verification: 'unverified_legacy', payouts_enabled: false, available_for_payout: null, currency: null };

function dashboardPayload({ ownerContext = owner, links = [{ id: 71, name: 'Campaign A', url: 'https://marketedgepros.com/?ref=AFFILIATE7', clicks: 23, conversions: 4 }], referrals = [{ id: 91, status: 'converted', click_date: '2026-10-12T09:00:00Z', commission_amount: '7.00', currency: null }] } = {}) {
  return {
    owner_context: ownerContext,
    stats: {
      total_clicks: 23, total_conversions: 4, total_revenue: '100.00', total_commission: '12.50',
      pending_commission: '2.00', approved_commission: '3.50', paid_commission: '7.00',
      available_for_payout: null, payouts_enabled: false, commission_verification: 'unverified_legacy', currency: null,
    },
    links,
    link_pagination: { total: links.length, limit: 50, truncated: false },
    recent_referrals: referrals,
  };
}

function commissionRow(id, status = 'approved') {
  return { id, amount: '25.00', type: 'referral', status, created_at: '2026-10-12T10:00:00Z', approved_at: '2026-10-13T10:00:00Z', paid_at: null, currency: null };
}
function commissionsPayload({ page = 1, status = null, ownerContext = owner } = {}) {
  const rows = status === 'approved'
    ? [commissionRow(501, 'approved')]
    : page === 2 ? [commissionRow(221, 'paid')]
      : Array.from({ length: 20 }, (_, index) => commissionRow(201 + index, index % 2 ? 'approved' : 'pending'));
  const total = status === 'approved' ? 1 : 21;
  return {
    owner_context: ownerContext, ...flags,
    pagination: { page, per_page: 20, total, pages: status === 'approved' ? 1 : 2 }, filters: { status }, commissions: rows,
  };
}
function referralsPayload({ page = 1, status = null, empty = false } = {}) {
  const rows = empty ? [] : [{ id: 301, status: status || 'converted', click_date: '2026-10-12T10:00:00Z', conversion_date: null, purchase_amount: '100.00', commission_amount: '25.00', currency: null }];
  return {
    owner_context: owner, ...flags,
    pagination: { page, per_page: 20, total: rows.length, pages: rows.length ? 1 : 0 }, filters: { status }, referrals: rows,
  };
}

// This executes the real App router expressions and real ProtectedRoute/RoleGuard.
// Only non-affiliate lazy leaves are inert local probes so unrelated domains cannot make a request.
test('UI6 affiliate App routes execute guest, forbidden, permitted, and fresh-remount outcomes through MemoryRouter', { concurrency: false }, async () => {
  const routes = [
    ['/affiliate/dashboard', 'AffiliateDashboard'],
    ['/affiliate/traders', 'TradersManagement'],
    ['/affiliate/commissions', 'Commissions'],
    ['/affiliate/reports', 'Reports'],
    ['/affiliate/payout', 'AffiliatePayout'],
  ];
  for (const [route, leaf] of routes) {
    setAuth(null);
    globalThis.__ui6AffiliateInitialEntries = [route];
    let harness = installDom('https://marketedgepros.com/');
    try {
      await act(async () => { harness.root.render(React.createElement(App)); await settle(); });
      await waitFor(() => document.querySelector('[data-ui6-location]')?.textContent.startsWith('/login?redirect='), `guest redirect ${route}`);
      assert.equal(document.querySelector('[data-ui6-location]').textContent, `/login?redirect=${encodeURIComponent(route)}`);
    } finally { await harness.close(); }

    setAuth({ ...affiliateUser, role: 'trader' });
    globalThis.__ui6AffiliateInitialEntries = [route];
    harness = installDom('https://marketedgepros.com/');
    try {
      await act(async () => { harness.root.render(React.createElement(App)); await settle(); });
      await waitFor(() => text().includes('Access Denied'), `forbidden role ${route}`);
      assert.equal(document.querySelector(`[data-ui6-route="${leaf}"]`), null, 'forbidden role cannot render affiliate leaf');
    } finally { await harness.close(); }

    setAuth(affiliateUser);
    globalThis.__ui6AffiliateInitialEntries = [route];
    harness = installDom('https://marketedgepros.com/');
    try {
      await act(async () => { harness.root.render(React.createElement(App)); await settle(); });
      await waitFor(() => document.querySelector(`[data-ui6-route="${leaf}"]`), `permitted ${route}`);
      assert.equal(document.querySelector('[data-ui6-location]').textContent, route);
    } finally { await harness.close(); }

    // Fresh MemoryRouter mount is the deterministic refresh equivalent for these routes.
    setAuth(affiliateUser);
    globalThis.__ui6AffiliateInitialEntries = [route];
    harness = installDom('https://marketedgepros.com/');
    try {
      await act(async () => { harness.root.render(React.createElement(App)); await settle(); });
      await waitFor(() => document.querySelector(`[data-ui6-route="${leaf}"]`), `fresh remount ${route}`);
    } finally { await harness.close(); }
  }
});

test('UI6 affiliate landing DOM accepts only acknowledged synthetic registration and routes the actual support/dashboard controls', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const calls = [];
  let registrationAttempts = 0;
  api.defaults.adapter = async (config) => {
    calls.push({ method: String(config.method).toLowerCase(), url: config.url, data: config.data });
    if (config.url === '/affiliate/info') {
      return response(config, { program: { is_active: true, commission_rate: 0, min_payout: 50, cookie_duration_days: 30, terms: 'Synthetic only' } });
    }
    if (config.url === '/affiliate/register') {
      registrationAttempts += 1;
      const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
      assert.deepEqual(body, {}, 'the source component submits the canonical empty registration payload');
      return response(config, { message: 'Synthetic registration acknowledgement', link: { url: 'https://marketedgepros.com/ref/FIXTURE' } }, registrationAttempts === 1 ? 202 : 201);
    }
    throw new Error(`unexpected synthetic landing request ${config.url}`);
  };
  try {
    setAuth(null);
    let harness = await mount(Landing, { entry: '/affiliate', url: 'https://marketedgepros.com/affiliate' });
    try {
      await waitFor(() => button('Sign in to continue'), 'guest landing readiness');
      await click(button('Sign in to continue'));
      assert.equal(document.querySelector('[data-ui6-location]').textContent, '/login?redirect=%2Faffiliate');
      assert.equal(calls.filter((call) => call.method === 'post').length, 0, 'guest click never posts registration');
    } finally { await harness.close(); }

    setAuth(affiliateUser);
    harness = await mount(Landing, { entry: '/affiliate', url: 'https://marketedgepros.com/affiliate' });
    try {
      await waitFor(() => button('Open affiliate dashboard'), 'authorized landing readiness');
      await click(button('Open affiliate dashboard'));
      assert.equal(document.querySelector('[data-ui6-location]').textContent, '/affiliate/dashboard');
      assert.equal(calls.filter((call) => call.method === 'post').length, 0, 'affiliate role click does not register again');
    } finally { await harness.close(); }

    setAuth({ id: 20, tenant_id: 6, role: 'trader' });
    harness = await mount(Landing, { entry: '/affiliate', url: 'https://marketedgepros.com/affiliate' });
    try {
      await waitFor(() => button('Register interest'), 'registration readiness');
      await click(button('Register interest'));
      await waitFor(() => document.querySelector('[role="alert"]'), 'rejected 202 acknowledgement');
      assert.match(text(), /could not be loaded/i);
      assert.equal(document.querySelector('a[href="https://marketedgepros.com/ref/FIXTURE"]'), null, 'bad acknowledgement publishes no referral link');

      await click(button('Register interest'));
      await waitFor(() => document.querySelector('a[href="https://marketedgepros.com/ref/FIXTURE"]'), '201 acknowledged registration');
      const referral = document.querySelector('a[href="https://marketedgepros.com/ref/FIXTURE"]');
      assert.equal(referral.target, '_blank');
      assert.equal(referral.rel, 'noreferrer');
      assert.match(text(), /does not create a commission or confirm eligibility for a payout/i);
      const support = anchorByText('Contact support about affiliate access');
      assert.equal(support.getAttribute('href'), '/support/create-ticket');
      await click(support);
      assert.equal(document.querySelector('[data-ui6-location]').textContent, '/support/create-ticket');
      const visitSupport = anchorByText('Visit support');
      assert.equal(visitSupport.getAttribute('href'), '/support');
    } finally { await harness.close(); }
    assert.equal(calls.filter((call) => call.url === '/affiliate/register').length, 2);
  } finally {
    api.defaults.adapter = originalAdapter;
  }
});

test('UI6 affiliate landing DOM keeps registration disabled through a synthetic availability timeout', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  let releaseAvailability;
  let postCount = 0;
  api.defaults.adapter = (config) => {
    if (config.url === '/affiliate/info') return new Promise((resolve, reject) => {
      releaseAvailability = () => reject(Object.assign(new Error('Synthetic availability timeout'), {
        response: { data: { error: 'Synthetic availability timeout' } }, config,
      }));
    });
    if (config.url === '/affiliate/register') postCount += 1;
    throw new Error(`unexpected synthetic availability request ${config.url}`);
  };
  setAuth({ id: 20, tenant_id: 6, role: 'trader' });
  const harness = await mount(Landing, { entry: '/affiliate', url: 'https://marketedgepros.com/affiliate' });
  try {
    await waitFor(() => button('Loading availability…'), 'availability loading control');
    assert.equal(button('Loading availability…').disabled, true, 'loading source state cannot submit registration');
    releaseAvailability();
    await waitFor(() => text().includes('Program availability could not be confirmed.'), 'availability failure message');
    assert.equal(button('Program information unavailable').disabled, true, 'failed availability cannot fabricate registration success');
    assert.equal(postCount, 0);
  } finally {
    await harness.close();
    api.defaults.adapter = originalAdapter;
  }
});

test('UI6 affiliate dashboard DOM binds identity/signal, fails closed on wrong owner, copies only acknowledged canonical data, and navigates', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const calls = [];
  let resolveFirst;
  let dashboardCalls = 0;
  api.defaults.adapter = (config) => {
    assert.equal(config.url, '/affiliate/dashboard');
    assert.equal(String(config.method).toLowerCase(), 'get');
    assert.ok(config.signal instanceof AbortSignal, 'dashboard read carries a concrete abort signal');
    assert.equal(config.signal.aborted, false, 'dashboard signal starts active');
    calls.push(config);
    dashboardCalls += 1;
    if (dashboardCalls === 1) return new Promise((resolve) => { resolveFirst = () => resolve(response(config, dashboardPayload({ ownerContext: { user_id: 99, tenant_id: owner.tenant_id } }))); });
    if (dashboardCalls === 2) return Promise.resolve(response(config, dashboardPayload()));
    return Promise.resolve(response(config, dashboardPayload({ links: [], referrals: [] })));
  };
  setAuth(affiliateUser);
  const harness = await mount(Dashboard, { entry: '/affiliate/dashboard', url: 'https://marketedgepros.com/affiliate/dashboard' });
  const clipboardWrites = [];
  const priorClipboard = Object.getOwnPropertyDescriptor(window.navigator, 'clipboard');
  Object.defineProperty(window.navigator, 'clipboard', { configurable: true, value: { writeText: async (value) => { clipboardWrites.push(value); } } });
  try {
    await waitFor(() => document.querySelector('[aria-busy="true"]'), 'dashboard loading state');
    resolveFirst();
    await waitFor(() => text().includes('Affiliate dashboard is unavailable'), 'owner mismatch failure');
    assert.match(text(), /owner context does not match/i);
    const failureSupport = anchorByText('Contact support');
    assert.equal(failureSupport.getAttribute('href'), '/support/create-ticket');
    await click(failureSupport);
    assert.equal(document.querySelector('[data-ui6-location]').textContent, '/support/create-ticket');

    await click(document.querySelector('[aria-label="Refresh affiliate dashboard data"]'));
    await waitFor(() => text().includes('Campaign A'), 'owner-acknowledged dashboard response');
    assert.equal(document.querySelector('input[aria-label="Canonical referral link 71"]').value, 'https://marketedgepros.com/?ref=AFFILIATE7');
    await click(document.querySelector('[aria-label="Copy referral link 71"]'));
    await waitFor(() => text().includes('Referral link copied.'), 'clipboard acknowledgement');
    assert.deepEqual(clipboardWrites, ['https://marketedgepros.com/?ref=AFFILIATE7']);

    for (const [label, destination] of [
      ['My traders', '/affiliate/traders'], ['Commissions', '/affiliate/commissions'], ['Reports', '/affiliate/reports'],
      ['Payout status', '/affiliate/payout'], ['Support', '/support/create-ticket'],
    ]) {
      const link = [...document.querySelectorAll('a')].find((item) => item.textContent.trim() === label);
      assert.equal(link.getAttribute('href'), destination, label);
      await click(link);
      assert.equal(document.querySelector('[data-ui6-location]').textContent, destination, label);
    }

    await click(document.querySelector('[aria-label="Refresh affiliate dashboard data"]'));
    await waitFor(() => text().includes('No referral links were returned for this account.'), 'empty dashboard links');
    assert.match(text(), /No recent referral activity was returned/);
    assert.equal(calls.length, 3, 'initial bad-owner, acknowledged retry, and explicit empty refresh each created one bound GET');
  } finally {
    if (priorClipboard) Object.defineProperty(window.navigator, 'clipboard', priorClipboard);
    else delete window.navigator.clipboard;
    await harness.close();
    api.defaults.adapter = originalAdapter;
  }
});

test('UI6 affiliate payout DOM exposes only unavailable information and real internal Router anchors', { concurrency: false }, async () => {
  for (const [label, destination] of [
    ['Back to affiliate dashboard', '/affiliate/dashboard'], ['Open commissions', '/affiliate/commissions'], ['Create a ticket', '/support/create-ticket'],
  ]) {
    const harness = await mount(Payout, { entry: '/affiliate/payout', url: 'https://marketedgepros.com/affiliate/payout' });
    try {
      assert.match(text(), /Payout execution is unavailable/);
      assert.equal(document.querySelectorAll('button, form, input').length, 0, 'the unavailable payout page has no submit-capable control');
      const link = anchorByText(label);
      assert.equal(link.getAttribute('href'), destination, label);
      await click(link);
      assert.equal(document.querySelector('[data-ui6-location]').textContent, destination, label);
    } finally { await harness.close(); }
  }
});

test('UI6 affiliate commissions DOM binds filter/page/CSV/retry to owner-validated synthetic reads', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const calls = [];
  let badOwner = false;
  api.defaults.adapter = async (config) => {
    assert.equal(config.url, '/affiliate/commissions');
    assert.equal(String(config.method).toLowerCase(), 'get');
    assert.ok(config.signal instanceof AbortSignal, 'commission read carries a signal');
    assert.equal(config.signal.aborted, false, 'commission signal starts active');
    assert.equal(config.params.per_page, 20);
    calls.push({ params: { ...config.params }, signal: config.signal });
    return response(config, commissionsPayload({
      page: config.params.page,
      status: config.params.status ?? null,
      ownerContext: badOwner ? { user_id: 20, tenant_id: owner.tenant_id } : owner,
    }));
  };
  setAuth(affiliateUser);
  const harness = await mount(Commissions, { entry: '/affiliate/commissions', url: 'https://marketedgepros.com/affiliate/commissions' });
  const urlApi = globalThis.URL;
  const priorCreate = urlApi.createObjectURL;
  const priorRevoke = urlApi.revokeObjectURL;
  const priorAnchorClick = window.HTMLAnchorElement.prototype.click;
  const downloads = [];
  urlApi.createObjectURL = (blob) => { downloads.push(['blob', blob.type]); return 'blob:ui6-affiliate-commissions'; };
  urlApi.revokeObjectURL = (value) => { downloads.push(['revoke', value]); };
  window.HTMLAnchorElement.prototype.click = function syntheticDownloadClick() { downloads.push(['click', this.download, this.href]); };
  try {
    await waitFor(() => text().includes('#201'), 'initial owner-validated commissions');
    assert.match(text(), /25\.00/);

    await setControlValue(document.getElementById('commission-status'), 'approved');
    await waitFor(() => calls.some((call) => call.params.status === 'approved'), 'approved filter request');
    await waitFor(() => text().includes('#501'), 'approved filtered acknowledgement');
    await click(document.querySelector('[aria-label="Export current verified commissions page"]'));
    assert.deepEqual(downloads.slice(0, 3), [
      ['blob', 'text/csv;charset=utf-8'],
      ['click', 'unverified-affiliate-commissions-page-1.csv', 'blob:ui6-affiliate-commissions'],
      ['revoke', 'blob:ui6-affiliate-commissions'],
    ]);
    assert.doesNotMatch(text(), /Current-page export could not be created/);

    await setControlValue(document.getElementById('commission-status'), 'all');
    await waitFor(() => text().includes('#201'), 'all-status response');
    await click(button('Next page'));
    await waitFor(() => text().includes('Page 2 · 21 server records · 2 server pages'), 'next page request');
    assert.ok(calls.some((call) => call.params.page === 2 && !('status' in call.params)), 'Next binds page two with canonical no-filter params');
    await click(button('Previous page'));
    await waitFor(() => text().includes('Page 1 · 21 server records · 2 server pages'), 'previous page request');
    await click(button('Next page'));
    await waitFor(() => text().includes('Page 2 · 21 server records · 2 server pages'), 'second page for first action');
    await click(button('First page'));
    await waitFor(() => text().includes('Page 1 · 21 server records · 2 server pages'), 'first page action');

    badOwner = true;
    await click(document.querySelector('[aria-label="Refresh affiliate records"]'));
    await waitFor(() => text().includes('Affiliate records could not be verified'), 'wrong-owner failure');
    assert.match(text(), /owner context does not match/i);
    assert.equal(document.querySelector('tbody'), null, 'wrong owner cannot retain a success table');
    badOwner = false;
    await click(button('Retry records'));
    await waitFor(() => text().includes('#201'), 'retry requires a fresh owner-acknowledged response');
    assert.ok(calls.every((call) => call.signal instanceof AbortSignal), 'every commission request remains abort-bound');
  } finally {
    urlApi.createObjectURL = priorCreate;
    urlApi.revokeObjectURL = priorRevoke;
    window.HTMLAnchorElement.prototype.click = priorAnchorClick;
    await harness.close();
    api.defaults.adapter = originalAdapter;
  }
});

test('UI6 shared affiliate record DOM dispatches retry, refresh, bounded last page, and real navigation controls', { concurrency: false }, async () => {
  const pages = [];
  let retries = 0;
  let refreshes = 0;
  const harness = installDom('https://marketedgepros.com/affiliate/commissions');
  try {
    await act(async () => {
      harness.root.render(React.createElement(MemoryRouter, { initialEntries: ['/affiliate/commissions'] },
        React.createElement(recordUiModule.AffiliateRecordHeader, { eyebrow: 'Synthetic', title: 'Records', summary: 'Synthetic only', onRefresh: () => { refreshes += 1; } }),
        React.createElement(recordUiModule.AffiliateRecordReadState, { loading: true, onRetry: () => { retries += 1; } }),
        React.createElement(recordUiModule.AffiliateRecordReadState, { error: 'Synthetic read failure', onRetry: () => { retries += 1; } }),
        React.createElement(recordUiModule.AffiliateRecordPagination, { pagination: { page: 3, per_page: 20, total: 21, pages: 2 }, onPage: (page) => pages.push(page) }),
        React.createElement(LocationProbe),
      ));
      await settle();
    });
    assert.ok(document.querySelector('[aria-busy="true"]'), 'the shared source component exposes an accessible loading state');
    await click(button('Refresh records'));
    await click(button('Retry records'));
    await click(button('Last available page'));
    assert.equal(refreshes, 1);
    assert.equal(retries, 1);
    assert.deepEqual(pages, [2], 'beyond-total state clamps its explicit Last control to the server last page');
    const support = document.querySelector('a[href="/support/create-ticket"]');
    assert.ok(support, 'shared navigation renders a real support anchor');
    await click(support);
    assert.equal(document.querySelector('[data-ui6-location]').textContent, '/support/create-ticket');
  } finally { await harness.close(); }
});

test('UI6 affiliate traders and reports DOM use owner/signal-bound synthetic data and show their empty/read-only states', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const calls = [];
  let referralEmpty = false;
  api.defaults.adapter = async (config) => {
    assert.ok(config.signal instanceof AbortSignal, 'record/dashboard reads carry a signal');
    assert.equal(config.signal.aborted, false, 'read signal starts active');
    calls.push({ url: config.url, params: config.params ? { ...config.params } : null });
    if (config.url === '/affiliate/referrals') {
      return response(config, referralsPayload({ page: config.params.page, status: config.params.status ?? null, empty: referralEmpty }));
    }
    if (config.url === '/affiliate/dashboard') return response(config, dashboardPayload({ links: [], referrals: [] }));
    throw new Error(`unexpected synthetic affiliate read ${config.url}`);
  };
  setAuth(affiliateUser);
  let harness = await mount(Traders, { entry: '/affiliate/traders', url: 'https://marketedgepros.com/affiliate/traders' });
  try {
    await waitFor(() => text().includes('#301'), 'referrals initial response');
    referralEmpty = true;
    await setControlValue(document.getElementById('referral-status'), 'converted');
    await waitFor(() => text().includes('No referral records were returned for this server-filtered page.'), 'empty filtered referrals');
    referralEmpty = false;
    await click(document.querySelector('[aria-label="Refresh affiliate records"]'));
    await waitFor(() => text().includes('#301'), 'referral refresh acknowledgement');
    assert.ok(calls.some((call) => call.url === '/affiliate/referrals' && call.params.status === 'converted'), 'filter is passed to the actual record service');
  } finally { await harness.close(); }

  harness = await mount(Reports, { entry: '/affiliate/reports', url: 'https://marketedgepros.com/affiliate/reports' });
  try {
    await waitFor(() => text().includes('Dashboard record overview'), 'reports dashboard projection');
    assert.match(text(), /No recent referral activity was returned by the dashboard/);
    const before = calls.filter((call) => call.url === '/affiliate/dashboard').length;
    await click(document.querySelector('[aria-label="Refresh affiliate records"]'));
    await waitFor(() => calls.filter((call) => call.url === '/affiliate/dashboard').length === before + 1, 'reports refresh request');
    assert.match(text(), /Currency unavailable/);
  } finally {
    await harness.close();
    api.defaults.adapter = originalAdapter;
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
