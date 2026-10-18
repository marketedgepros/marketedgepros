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
import { createAdminInsightViewService } from '../src/services/adminInsightViewService.js';

const require = createRequire(import.meta.url);
assert.equal(require('jsdom/package.json').version, '28.1.0', 'UI6 DOM evidence requires the pinned jsdom package');

// React DOM must see a DOM at module initialization so controlled-change handlers are installed.
const bootstrapDom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6.insights.test/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrapDom.window, document: bootstrapDom.window.document, navigator: bootstrapDom.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
}
const { createRoot } = await import('react-dom/client');
const { MemoryRouter, useLocation } = await import('react-router-dom');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrapDom.window.close();

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const source = (...parts) => path.join(frontendDirectory, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(source(...parts)).href;
const tempDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-insights-dom-'));
const externalImports = new Map([
  ['react', pathToFileURL(require.resolve('react')).href],
  ['react/jsx-runtime', pathToFileURL(require.resolve('react/jsx-runtime')).href],
  ['react/jsx-dev-runtime', pathToFileURL(require.resolve('react/jsx-dev-runtime')).href],
  ['react-router-dom', pathToFileURL(require.resolve('react-router-dom')).href],
  ['lucide-react', pathToFileURL(require.resolve('lucide-react')).href],
]);

function makeImportable(text) {
  let result = text;
  for (const [specifier, url] of externalImports) {
    result = result
      .replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`)
      .replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
  }
  return result;
}
function replaceSpecifier(text, specifier, target) {
  return text
    .replaceAll(`'${specifier}'`, JSON.stringify(target))
    .replaceAll(`"${specifier}"`, JSON.stringify(target));
}
function writeModule(name, text) {
  const target = path.join(tempDirectory, name);
  fs.writeFileSync(target, makeImportable(text));
  return pathToFileURL(target).href;
}
async function compileText(name, text, sourceName = `${name}.jsx`) {
  const target = path.join(tempDirectory, name);
  const transformed = await transformWithEsbuild(makeImportable(text), sourceName, { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  fs.writeFileSync(target, makeImportable(transformed.code));
  return import(`${pathToFileURL(target).href}?ui6-insights=${process.pid}`);
}
async function compileSource(relative, outputName, replacements = []) {
  const input = source(...relative.split('/'));
  let text = fs.readFileSync(input, 'utf8');
  for (const [specifier, target] of replacements) text = replaceSpecifier(text, specifier, target);
  return compileText(outputName, text, input);
}

const authStub = writeModule('auth.mjs', `
  let state = { user: null, isAuthenticated: false, isLoading: false, init: () => {} };
  export const __setAuth = (next) => { state = { ...state, ...next, init: next.init || state.init || (() => {}) }; };
  export default function useAuthStore(selector) { return typeof selector === 'function' ? selector(state) : state; }
  useAuthStore.subscribe = () => () => {};
`);
const insightServiceStub = writeModule('insight-service.mjs', `
  export { ADMIN_INSIGHT_DAYS } from ${JSON.stringify(sourceUrl('services', 'adminInsightViewService.js'))};
  export const loadAdminInsight = (request) => globalThis.__ui6InsightsService.loadAdminInsight(request);
`);

const ui = await compileSource('components/admin/AdminInsightUI.jsx', 'AdminInsightUI.mjs');
const dashboard = await compileSource('pages/admin/AdminDashboardConnected.jsx', 'AdminDashboardConnected.mjs', [
  ['../../store/authStore.js', authStub],
  ['../../services/adminInsightViewService.js', insightServiceStub],
  ['../../hooks/useAdminInsightRead.js', sourceUrl('hooks', 'useAdminInsightRead.js')],
  ['../../components/admin/AdminInsightUI.jsx', pathToFileURL(path.join(tempDirectory, 'AdminInsightUI.mjs')).href],
]);
const analytics = await compileSource('pages/admin/AnalyticsDashboard.jsx', 'AnalyticsDashboard.mjs', [
  ['../../store/authStore.js', authStub],
  ['../../services/adminInsightViewService.js', insightServiceStub],
  ['../../hooks/useAdminInsightRead.js', sourceUrl('hooks', 'useAdminInsightRead.js')],
  ['../../components/admin/AdminInsightUI.jsx', pathToFileURL(path.join(tempDirectory, 'AdminInsightUI.mjs')).href],
  ['./AdminDashboardConnected.jsx', pathToFileURL(path.join(tempDirectory, 'AdminDashboardConnected.mjs')).href],
]);
const roleGuard = await compileSource('components/guards/RoleGuard.jsx', 'RoleGuard.mjs', [
  ['../../store/authStore', authStub],
]);

let appSource = fs.readFileSync(source('App.jsx'), 'utf8');
appSource = replaceSpecifier(appSource, './store/authStore', authStub)
  .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", `import { MemoryRouter, Routes, Route, Navigate, useLocation } from ${JSON.stringify(externalImports.get('react-router-dom'))};`)
  .replace("import { useLocation } from 'react-router-dom';", '')
  .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
  .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
  .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
  .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['master', 'supermaster'];")
  .replace("import { postLoginDestination } from './services/navigationService.js';", "const postLoginDestination = () => '/dashboard';")
  .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
  .replace("import useNotificationStore from './stores/notificationStore.js';", 'const useNotificationStore = { getState: () => ({ reset() {} }) };')
  .replace("import RoleGuard from './components/guards/RoleGuard';", `import RoleGuard from ${JSON.stringify(pathToFileURL(path.join(tempDirectory, 'RoleGuard.mjs')).href)};`)
  .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6InsightsInitialEntries}>')
  .replace('</BrowserRouter>', '</MemoryRouter>');
appSource = appSource.replace(/^const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\((['"])[^'"]+\2\)\);$/gm, (_all, name) => (
  `const ${name} = ({ children }) => <div data-route-page="${name}">{children || '${name}'}</div>;`
));
assert.equal((appSource.match(/=\s*lazy\(/g) || []).length, 0, 'test router leaves no lazy module import unresolved');
appSource = appSource
  .replace('function App() {', 'function Ui6RouteLocation() { const location = useLocation(); return <output data-ui6-location="true">{location.pathname + location.search}</output>; }\n\nfunction App() {')
  .replace('</Routes>', '</Routes><Ui6RouteLocation />');
const app = await compileText('AppRouter.mjs', appSource, source('App.jsx'));
const auth = await import(authStub);

const owner = { user_id: 9, tenant_id: 7, role: 'master' };
const ownerContext = { user_id: owner.user_id, tenant_id: owner.tenant_id };
const asOf = '2026-10-12T13:00:00Z';

function canonicalCounts(empty = false) {
  return empty ? { users: 0, challenges: 0, payments: 0 } : { users: 1, challenges: 1, payments: 1 };
}
function canonicalDistributions(counts) {
  return {
    user_roles: counts.users ? [{ code: 'master', count: counts.users }] : [],
    user_kyc: counts.users ? [{ code: 'unverified', count: counts.users }] : [],
    challenge_status: counts.challenges ? [{ code: 'active', count: counts.challenges }] : [],
    payment_status: counts.payments ? [{ code: 'pending', count: counts.payments }] : [],
  };
}
function dailyRows(days, counts) {
  const asOfDay = new Date(Date.UTC(2026, 9, 12));
  return Array.from({ length: days }, (_value, index) => {
    const date = new Date(asOfDay);
    date.setUTCDate(asOfDay.getUTCDate() - (days - 1 - index));
    return {
      date: date.toISOString().slice(0, 10),
      users: index === days - 1 ? counts.users : 0,
      challenges: index === days - 1 ? counts.challenges : 0,
      payments: index === days - 1 ? counts.payments : 0,
    };
  });
}
function canonicalPayload(kind, days, { empty = false, wrongOwner = false } = {}) {
  const counts = canonicalCounts(empty);
  return {
    owner_context: wrongOwner ? { user_id: owner.user_id + 1, tenant_id: owner.tenant_id } : ownerContext,
    record_verification: 'unverified_legacy',
    settlement_enabled: false,
    as_of: asOf,
    filters: { days: kind === 'dashboard' ? null : days },
    counts,
    distributions: canonicalDistributions(counts),
    recent_users: kind === 'dashboard' && counts.users ? [{ id: 41, role: 'master', is_active: true, kyc_status: 'unverified', created_at: '2026-10-12T12:00:00Z' }] : [],
    recent_payments: kind === 'dashboard' && counts.payments ? [{ id: 71, user_id: 41, amount: '0.00', currency: 'EUR', payment_type: 'challenge_purchase', status: 'pending', created_at: '2026-10-12T11:00:00Z' }] : [],
    daily_activity: kind === 'dashboard' ? [] : dailyRows(days, counts),
  };
}
function boundSyntheticService(modes, records) {
  const realService = createAdminInsightViewService({
    get: async (endpoint, config) => {
      const mode = modes.shift();
      assert.ok(mode, `a synthetic response mode exists for ${endpoint}`);
      const kind = endpoint === '/admin/dashboard/stats' ? 'dashboard' : 'analytics';
      const days = kind === 'dashboard' ? null : config.params?.days;
      records.transport.push({ endpoint, config, mode, kind, days });
      assert.equal(config._skipAuthRefresh, true, 'insight request cannot trigger auth refresh/replay');
      assert.equal(config.timeout, 5000, 'insight request retains the bounded transport timeout');
      assert.ok(config.signal instanceof AbortSignal, 'insight transport receives the owner-bound abort signal');
      assert.equal(config.signal.aborted, false, 'a displayed request is not already aborted');
      return { data: canonicalPayload(kind, days, { empty: mode === 'empty', wrongOwner: mode === 'bad_owner' }), status: 200, statusText: 'OK', headers: {}, config };
    },
  });
  return {
    loadAdminInsight(request) {
      records.requests.push(request);
      assert.deepEqual(request.expectedOwner, owner, 'the connected component passes only the active authenticated owner');
      assert.ok(request.signal instanceof AbortSignal, 'the component request carries the identity-bound signal');
      assert.equal(request.signal.aborted, false, 'the component never reuses an aborted signal');
      return realService.loadAdminInsight(request);
    },
  };
}

function installDom(url = 'http://ui6.insights.test/admin/dashboard') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url, pretendToBeVisual: true });
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT'];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Node: dom.window.Node,
    Element: dom.window.Element,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
  const host = dom.window.document.getElementById('root');
  const root = createRoot(host);
  return {
    dom,
    host,
    root,
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
async function settle() {
  await Promise.resolve();
  await Promise.resolve();
}
async function waitFor(predicate, label) {
  let last;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      if (predicate()) return;
    } catch (error) { last = error; }
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); await settle(); });
  }
  throw last || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected an actionable DOM element');
  const view = element.ownerDocument.defaultView;
  await act(async () => {
    element.dispatchEvent(new view.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function changeSelect(element, value) {
  assert.ok(element, 'expected a select control');
  const view = element.ownerDocument.defaultView;
  const setter = Object.getOwnPropertyDescriptor(view.HTMLSelectElement.prototype, 'value').set;
  const previous = element.value;
  setter.call(element, value);
  element._valueTracker?.setValue(previous);
  await act(async () => {
    element.dispatchEvent(new view.Event('change', { bubbles: true, cancelable: true }));
    await settle();
  });
}
function locationValue(host) {
  return host.querySelector('[data-ui6-location="true"]')?.textContent;
}
function buttonNamed(host, label, within = host) {
  return [...within.querySelectorAll('button')].find((button) => button.textContent.replace(/\s+/g, ' ').trim() === label);
}
function headerRefresh(host) {
  return [...host.querySelectorAll('button')].find((button) => button.textContent.includes('Refresh records') && !button.closest('[role="alert"]'));
}
function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { 'data-ui6-probe': 'true' }, `${location.pathname}${location.search}`);
}

// The actual App route expressions and actual ProtectedRoute/RoleGuard execute here.
// Leaf lazy pages are intentionally inert only to keep unrelated product domains out of this focused test.
test('UI6 insights routes execute guest, forbidden, permitted, and MemoryRouter remount outcomes', { concurrency: false }, async () => {
  const routes = [
    ['/admin', 'AdminDashboard'],
    ['/admin/dashboard', 'AdminDashboard'],
    ['/admin/analytics', 'AnalyticsDashboard'],
  ];
  for (const [pathname, page] of routes) {
    let view = installDom(`http://ui6.insights.test${pathname}`);
    try {
      auth.__setAuth({ user: null, isAuthenticated: false, isLoading: false, init: () => {} });
      globalThis.__ui6InsightsInitialEntries = [pathname];
      await act(async () => { view.root.render(React.createElement(app.default)); await settle(); });
      await waitFor(() => locationValue(view.host)?.startsWith('/login?redirect='), `guest redirect ${pathname}`);
      assert.equal(locationValue(view.host), `/login?redirect=${encodeURIComponent(pathname)}`, `${pathname} preserves its return path for a guest`);
    } finally { await view.close(); }

    view = installDom(`http://ui6.insights.test${pathname}`);
    try {
      auth.__setAuth({ user: { id: 9, tenant_id: 7, role: 'trader' }, isAuthenticated: true, isLoading: false, init: () => {} });
      globalThis.__ui6InsightsInitialEntries = [pathname];
      await act(async () => { view.root.render(React.createElement(app.default)); await settle(); });
      await waitFor(() => /Access Denied/.test(view.host.textContent), `forbidden role ${pathname}`);
      assert.equal(view.host.querySelector(`[data-route-page="${page}"]`), null, `${pathname} does not render the protected leaf for a forbidden role`);
    } finally { await view.close(); }

    view = installDom(`http://ui6.insights.test${pathname}`);
    try {
      auth.__setAuth({ user: { id: 9, tenant_id: 7, role: 'master' }, isAuthenticated: true, isLoading: false, init: () => {} });
      globalThis.__ui6InsightsInitialEntries = [pathname];
      await act(async () => { view.root.render(React.createElement(app.default)); await settle(); });
      await waitFor(() => view.host.querySelector(`[data-route-page="${page}"]`), `permitted ${pathname}`);
      assert.equal(locationValue(view.host), pathname);
    } finally { await view.close(); }

    // A fresh Router mount is the deterministic refresh/back-equivalent for these routes;
    // it does not fabricate an unrelated data mutation.
    view = installDom(`http://ui6.insights.test${pathname}`);
    try {
      auth.__setAuth({ user: { id: 9, tenant_id: 7, role: 'master' }, isAuthenticated: true, isLoading: false, init: () => {} });
      globalThis.__ui6InsightsInitialEntries = [pathname];
      await act(async () => { view.root.render(React.createElement(app.default)); await settle(); });
      await waitFor(() => view.host.querySelector(`[data-route-page="${page}"]`), `remount ${pathname}`);
      assert.equal(locationValue(view.host), pathname, `${pathname} remains valid after a Router remount`);
    } finally { await view.close(); }
  }
});

test('UI6 insights DOM renders every recorded admin and count-card anchor with its exact static destination', { concurrency: false }, async () => {
  const view = installDom();
  try {
    await act(async () => {
      view.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/dashboard'] }, React.createElement(React.Fragment, null,
        React.createElement(dashboard.AdminInsightQuickLinks, { current: '/admin/dashboard' }),
        React.createElement(ui.AdminInsightCountCards, { counts: canonicalCounts() }),
        React.createElement(LocationProbe),
      )));
      await settle();
    });
    for (const destination of ['/admin/dashboard', '/admin/users', '/admin/challenges', '/admin/kyc-approval', '/admin/payments', '/admin/analytics']) {
      assert.ok(view.host.querySelector(`a[href="${destination}"]`), `quick-link anchor ${destination}`);
    }
    assert.equal(view.host.querySelector('a[href="/admin/dashboard"]').getAttribute('aria-current'), 'page');
    for (const destination of ['/admin/users', '/admin/challenges', '/admin/payments']) {
      const anchors = view.host.querySelectorAll(`a[href="${destination}"]`);
      assert.ok(anchors.length >= 2, `${destination} has both a named route anchor and a count-card href`);
    }
    assert.equal(view.host.querySelector('[data-ui6-probe="true"]').textContent, '/admin/dashboard');
  } finally { await view.close(); }
});

test('UI6 dashboard DOM binds retry and header refresh to owner-checked canonical acknowledgements only', { concurrency: false }, async () => {
  const records = { requests: [], transport: [] };
  globalThis.__ui6InsightsService = boundSyntheticService(['bad_owner', 'success', 'empty', 'success'], records);
  auth.__setAuth({ user: { id: owner.user_id, tenant_id: owner.tenant_id, role: owner.role }, isAuthenticated: true, isLoading: false, init: () => {} });
  const view = installDom();
  try {
    await act(async () => {
      view.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/dashboard'] }, React.createElement(dashboard.default)));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'rejected owner acknowledgement');
    assert.equal(view.host.textContent.includes('Current count in this server-provided scope'), false, 'a mismatched owner response cannot become a visible dashboard success');

    const retry = buttonNamed(view.host, 'Refresh records', view.host.querySelector('[role="alert"]'));
    await click(retry);
    await waitFor(() => view.host.textContent.includes('Current count in this server-provided scope'), 'valid dashboard acknowledgement');
    assert.ok(view.host.textContent.includes('Source snapshot:'), 'canonical acknowledged data is rendered after the correct owner response');

    await click(headerRefresh(view.host));
    await waitFor(() => view.host.textContent.includes('No recorded rows in this snapshot'), 'acknowledged canonical empty dashboard');
    assert.equal(view.host.textContent.includes('Current count in this server-provided scope'), false, 'empty acknowledgement does not retain stale records');

    await click(headerRefresh(view.host));
    await waitFor(() => view.host.textContent.includes('Current count in this server-provided scope'), 'dashboard recovery refresh');
    assert.deepEqual(records.requests.map(({ kind, days }) => [kind, days]), [
      ['dashboard', null], ['dashboard', null], ['dashboard', null], ['dashboard', null],
    ]);
    assert.deepEqual(records.transport.map(({ endpoint, config }) => [endpoint, config.params]), [
      ['/admin/dashboard/stats', undefined], ['/admin/dashboard/stats', undefined],
      ['/admin/dashboard/stats', undefined], ['/admin/dashboard/stats', undefined],
    ]);
  } finally {
    await view.close();
    delete globalThis.__ui6InsightsService;
  }
});

test('UI6 analytics DOM binds retry, bounded day filter, and refresh to owner-checked canonical acknowledgements only', { concurrency: false }, async () => {
  const records = { requests: [], transport: [] };
  globalThis.__ui6InsightsService = boundSyntheticService(['bad_owner', 'success', 'success', 'empty'], records);
  auth.__setAuth({ user: { id: owner.user_id, tenant_id: owner.tenant_id, role: owner.role }, isAuthenticated: true, isLoading: false, init: () => {} });
  const view = installDom('http://ui6.insights.test/admin/analytics');
  try {
    await act(async () => {
      view.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/analytics'] }, React.createElement(analytics.default)));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'analytics owner acknowledgement rejection');
    assert.equal(view.host.textContent.includes('Current count in this server-provided scope'), false, 'analytics has no successful result after bad owner acknowledgement');

    await click(buttonNamed(view.host, 'Refresh records', view.host.querySelector('[role="alert"]')));
    await waitFor(() => view.host.textContent.includes('Current count in this server-provided scope'), 'valid default analytics acknowledgement');
    assert.equal(view.host.querySelector('#admin-insight-days').value, '30');

    await changeSelect(view.host.querySelector('#admin-insight-days'), '7');
    await waitFor(() => records.requests.length === 3 && view.host.querySelector('#admin-insight-days').value === '7' && view.host.textContent.includes('Current count in this server-provided scope'), 'bounded seven-day filter result');
    assert.ok(view.host.textContent.includes('Daily record creation'), 'canonical filtered daily rows are rendered');

    await click(headerRefresh(view.host));
    await waitFor(() => view.host.textContent.includes('No records were created in this UTC range'), 'canonical empty analytics refresh');
    assert.deepEqual(records.requests.map(({ kind, days }) => [kind, days]), [
      ['analytics', 30], ['analytics', 30], ['analytics', 7], ['analytics', 7],
    ]);
    assert.deepEqual(records.transport.map(({ endpoint, config }) => [endpoint, config.params]), [
      ['/analytics/comprehensive', { days: 30 }], ['/analytics/comprehensive', { days: 30 }],
      ['/analytics/comprehensive', { days: 7 }], ['/analytics/comprehensive', { days: 7 }],
    ]);
  } finally {
    await view.close();
    delete globalThis.__ui6InsightsService;
  }
});

test.after(() => {
  fs.rmSync(tempDirectory, { recursive: true, force: true });
  delete globalThis.__ui6InsightsInitialEntries;
  delete globalThis.__ui6InsightsService;
});
