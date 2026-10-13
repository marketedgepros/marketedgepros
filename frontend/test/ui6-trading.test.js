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
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;
const jsdomPackage = JSON.parse(fs.readFileSync(require.resolve('jsdom/package.json'), 'utf8'));
assert.equal(jsdomPackage.version, '28.1.0', 'UI6 requires the pinned direct jsdom package');

// React DOM is deliberately loaded after a small JSDOM bootstrap, so delegated
// change events are attached to a DOM-backed environment rather than SSR globals.
const bootstrap = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6.bootstrap.invalid/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrap.window, document: bootstrap.window.document, navigator: bootstrap.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
}
const { createRoot } = await import('react-dom/client');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-trading-dom-'));
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const dependencies = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
]);

function externalize(code) {
  for (const [specifier, url] of dependencies) {
    code = code.replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
    code = code.replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
  }
  return code;
}

function writeModule(name, source) {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
}

async function compile(relative, name, mutate = (value) => value) {
  const source = mutate(fs.readFileSync(sourcePath(...relative.split('/')), 'utf8'));
  const transformed = await transformWithEsbuild(source, sourcePath(...relative.split('/')), {
    loader: 'jsx', jsx: 'automatic', format: 'esm',
  });
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, externalize(transformed.code));
  return import(`${pathToFileURL(target).href}?ui6-trading=${process.pid}-${name}`);
}

const authStub = writeModule('auth.mjs', `
  const state = () => globalThis.__ui6TradingAuth || { user: null, isAuthenticated: false, isLoading: false, init() {} };
  export default function useAuthStore(selector) { const value = state(); return typeof selector === 'function' ? selector(value) : value; }
  useAuthStore.getState = () => state();
  useAuthStore.subscribe = () => () => {};
`);
const apiStub = writeModule('api.mjs', `
  export default { get: (...args) => globalThis.__ui6TradingAxios.get(...args) };
`);
const userLayoutStub = writeModule('user-layout.mjs', `
  import React from ${JSON.stringify(dependencyUrl('react'))};
  export default function UserLayout({ children }) { return React.createElement('main', { 'data-ui6-shell': 'user' }, children); }
`);
const recordedServiceActual = sourceUrl('services', 'recordedTradingViewService.js');
const recordedServiceStub = writeModule('recorded-service.mjs', `
  export { buildRecordedHistoryParams, downloadRecordedHistoryPage, isScalingAdmin, recordedIdentityKey, recordedPrincipal, PAGE_LIMIT } from ${JSON.stringify(recordedServiceActual)};
  export const createRecordedTradingViewService = () => ({
    history: (request) => globalThis.__ui6TradingRecorded.history(request),
    scaling: (request) => globalThis.__ui6TradingRecorded.scaling(request),
  });
`);

const recordedUi = await compile('components/trading/RecordedTradingUI.jsx', 'RecordedTradingUI.mjs', (text) => (
  text.replaceAll("'../../services/recordedTradingViewService.js'", JSON.stringify(recordedServiceActual))
));
const roleGuard = await compile('components/guards/RoleGuard.jsx', 'RoleGuard.mjs', (text) => (
  text.replace("'../../store/authStore'", JSON.stringify(authStub))
));

const challengeServiceActual = sourceUrl('services', 'challengeViewService.js');
const rolesActual = sourceUrl('constants', 'roles.js');
const challengeList = await compile('pages/user/MyChallenges.jsx', 'MyChallenges.mjs', (text) => text
  .replace("'../../services/api'", JSON.stringify(apiStub))
  .replace("'../../services/challengeViewService'", JSON.stringify(challengeServiceActual))
  .replace("'../../store/authStore'", JSON.stringify(authStub))
  .replace("'../../constants/roles.js'", JSON.stringify(rolesActual)));
const challengeDetail = await compile('pages/ChallengeDetails.jsx', 'ChallengeDetails.mjs', (text) => text
  .replace("'../services/api'", JSON.stringify(apiStub))
  .replace("'../services/challengeViewService'", JSON.stringify(challengeServiceActual))
  .replace("'../store/authStore'", JSON.stringify(authStub))
  .replace("'../constants/roles.js'", JSON.stringify(rolesActual)));
const recordedHookActual = sourceUrl('hooks', 'useRecordedTradingRead.js');
const scaling = await compile('pages/ScalingProgress.jsx', 'ScalingProgress.mjs', (text) => text
  .replace("'../components/layout/UserLayout'", JSON.stringify(userLayoutStub))
  .replace("'../store/authStore'", JSON.stringify(authStub))
  .replace("'../hooks/useRecordedTradingRead'", JSON.stringify(recordedHookActual))
  .replace("'../services/recordedTradingViewService.js'", JSON.stringify(recordedServiceStub))
  .replace("'../components/trading/RecordedTradingUI'", JSON.stringify(pathToFileURL(path.join(tempDir, 'RecordedTradingUI.mjs')).href)));
const history = await compile('pages/trader/TradingHistory.jsx', 'TradingHistory.mjs', (text) => text
  .replace("'../../store/authStore'", JSON.stringify(authStub))
  .replace("'../../hooks/useRecordedTradingRead'", JSON.stringify(recordedHookActual))
  .replace("'../../services/recordedTradingViewService.js'", JSON.stringify(recordedServiceStub))
  .replace("'../../components/trading/RecordedTradingUI'", JSON.stringify(pathToFileURL(path.join(tempDir, 'RecordedTradingUI.mjs')).href)));

function appRouterSource() {
  const roleGuardUrl = pathToFileURL(path.join(tempDir, 'RoleGuard.mjs')).href;
  let text = fs.readFileSync(sourcePath('App.jsx'), 'utf8')
    .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", "import { MemoryRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';")
    .replace("import { useLocation } from 'react-router-dom';", '')
    .replace("import useAuthStore from './store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`)
    .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
    .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
    .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
    .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['master', 'supermaster'];")
    .replace("import { postLoginDestination } from './services/navigationService.js';", "const postLoginDestination = () => '/dashboard';")
    .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
    .replace("import useNotificationStore from './stores/notificationStore.js';", 'const useNotificationStore = { getState: () => ({ reset() {} }) };')
    .replace("import RoleGuard from './components/guards/RoleGuard';", `import RoleGuard from ${JSON.stringify(roleGuardUrl)};`)
    .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6TradingInitialEntries}>')
    .replace('</BrowserRouter>', '</MemoryRouter>');
  text = text.replace(/const (\w+) = lazy\(\(\) => import\(['"][^'"]+['"]\)\);/g, (_whole, name) => (
    `const ${name} = ({ children }) => <div data-ui6-page="${name}">{children || '${name}'}</div>;`
  ));
  text = text.replace('function App() {', "function LocationProbe() { const location = useLocation(); return <output data-ui6-location=\"true\">{location.pathname + location.search}</output>; }\n\nfunction App() {");
  text = text.replace('</Routes>', '</Routes><LocationProbe />');
  return text;
}
const app = await compile('App.jsx', 'App.mjs', () => appRouterSource());

function installDom(url = 'http://ui6.trading.test/') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url, pretendToBeVisual: true });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'HTMLAnchorElement',
    'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle',
    'requestAnimationFrame', 'cancelAnimationFrame', 'URL', 'IS_REACT_ACT_ENVIRONMENT',
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
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    URL: dom.window.URL,
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

const pause = () => new Promise((resolve) => setTimeout(resolve, 0));
async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await pause();
}
async function waitFor(predicate, label) {
  let error;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const value = predicate();
      if (value) return value;
    } catch (caught) { error = caught; }
    await act(async () => { await settle(); });
  }
  throw error || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected an actionable DOM element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function submit(element) {
  assert.ok(element, 'expected a form');
  await act(async () => {
    element.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await settle();
  });
}
async function setControlValue(element, value) {
  assert.ok(element, 'expected a form control');
  const prototype = element.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
  const previous = element.value;
  setter.call(element, value);
  element._valueTracker?.setValue(previous);
  const reactPropsKey = Object.keys(element).find((key) => key.startsWith('__reactProps$'));
  await act(async () => {
    const props = reactPropsKey ? element[reactPropsKey] : null;
    if (typeof props?.onChange === 'function') props.onChange({ target: element });
    else {
      element.dispatchEvent(new window.Event('input', { bubbles: true, cancelable: true }));
      element.dispatchEvent(new window.Event('change', { bubbles: true, cancelable: true }));
    }
    await settle();
  });
}
function text(host) { return host.textContent.replace(/\s+/g, ' ').trim(); }
function button(host, label) {
  return [...host.querySelectorAll('button')].find((item) => item.textContent.replace(/\s+/g, ' ').trim() === label);
}
function location(host) { return host.querySelector('[data-ui6-location="true"]')?.textContent; }
function LocationProbe() {
  const { useLocation } = require('react-router-dom');
  const current = useLocation();
  return React.createElement('output', { 'data-ui6-location': 'true' }, `${current.pathname}${current.search}${current.hash}`);
}
function response(data) { return { data }; }

const owner = { user_id: 9, tenant_id: 7 };
const trader = { id: 9, tenant_id: 7, role: 'trader' };
function challengeRow(overrides = {}) {
  return {
    id: 41,
    user_id: 9,
    program: { id: 7, name: 'Recorded Evaluation' },
    legacy_status: 'active',
    legacy_payment_status: 'recorded',
    current_phase: 1,
    total_phases: 2,
    initial_balance: '10000.00',
    current_balance: '10025.00',
    max_drawdown_observed: '-2.00',
    start_date: '2026-10-01T00:00:00Z',
    end_date: null,
    passed_at: null,
    created_at: '2026-10-01T00:00:00Z',
    data_status: 'unverified_legacy',
    provider_authenticated: false,
    ...overrides,
  };
}
function listPayload(page, challenges, overrides = {}) {
  return {
    owner_context: owner,
    challenges,
    pagination: { page, per_page: 20, total: 21, pages: 2 },
    data_status: 'unverified_legacy',
    provider_authenticated: false,
    ...overrides,
  };
}
function detailPayload(overrides = {}) {
  return {
    owner_context: owner,
    challenge: challengeRow(),
    progress: {
      initial_balance: '10000.00', current_balance: '10025.00', profit_loss: '25.00',
      profit_target_percent: null, profit_target_amount: null, profit_progress_percent: null,
      trading_days: 1, min_trading_days: null, data_status: 'unverified_legacy', provider_authenticated: false,
    },
    mt5_account: null,
    data_status: 'unverified_legacy', provider_authenticated: false,
    ...overrides,
  };
}
function recordedTrade(overrides = {}) {
  return {
    id: 701,
    challenge_id: 41,
    symbol: 'EURUSD',
    trade_type: 'buy',
    volume: '0.10',
    open_price: '1.10000',
    close_price: '1.10100',
    profit: '10.00',
    commission: '0.00',
    swap: '0.00',
    status: 'closed',
    open_time: '2026-10-01T10:00:00Z',
    close_time: '2026-10-01T11:00:00Z',
    ...overrides,
  };
}
function historyView({ page = 1, total = 21, rows = [recordedTrade()], filters = { symbol: '', type: 'all', period: 'all' } } = {}) {
  return {
    owner_context: owner,
    data_status: 'unverified_legacy',
    provider_authenticated: false,
    currency: null,
    trades: rows,
    pagination: { page, per_page: 20, total, pages: Math.ceil(total / 20) },
    filters,
    statistics: { total_trades: total, winning_trades: null, losing_trades: null, total_profit: null },
  };
}

// This uses the unmodified current App routing source with leaf pages inert only;
// the tested ProtectedRoute and real RoleGuard still execute in MemoryRouter.
test('UI6 trading App Router enforces guest, user-only/admin, trader role, and remount boundaries', { concurrency: false }, async () => {
  async function renderAt(pathname, auth) {
    const view = installDom(`http://ui6.trading.test${pathname}`);
    globalThis.__ui6TradingAuth = { user: null, isAuthenticated: false, isLoading: false, init() {}, ...auth };
    globalThis.__ui6TradingInitialEntries = [pathname];
    await act(async () => { view.root.render(React.createElement(app.default)); await settle(); });
    await waitFor(() => location(view.host), `router outcome for ${pathname}`);
    return view;
  }

  let view = await renderAt('/challenges', {});
  try {
    assert.equal(location(view.host), '/login?redirect=%2Fchallenges');
  } finally { await view.close(); }

  for (const [privatePath, redirect] of [
    ['/scaling', '/login?redirect=%2Fscaling'],
    ['/challenges/41', '/login?redirect=%2Fchallenges%2F41'],
    ['/trader/history', '/login?redirect=%2Ftrader%2Fhistory'],
  ]) {
    view = await renderAt(privatePath, {});
    try {
      assert.equal(location(view.host), redirect, `${privatePath} guest boundary`);
    } finally { await view.close(); }
  }

  view = await renderAt('/challenges/41', { isAuthenticated: true, user: { id: 1, tenant_id: 7, role: 'master' } });
  try {
    assert.equal(location(view.host), '/admin', 'administrators are redirected by the live userOnly route boundary');
  } finally { await view.close(); }

  view = await renderAt('/challenges', { isAuthenticated: true, user: trader });
  try {
    assert.ok(view.host.querySelector('[data-ui6-page="MyChallenges"]'));
  } finally { await view.close(); }

  view = await renderAt('/challenges/41', { isAuthenticated: true, user: trader });
  try {
    assert.ok(view.host.querySelector('[data-ui6-page="ChallengeDetails"]'));
  } finally { await view.close(); }

  view = await renderAt('/trader/history', { isAuthenticated: true, user: { id: 8, tenant_id: 7, role: 'affiliate' } });
  try {
    assert.match(text(view.host), /Access Denied/);
    assert.equal(view.host.querySelector('[data-ui6-page="TradingHistory"]'), null);
  } finally { await view.close(); }

  view = await renderAt('/trader/history', { isAuthenticated: true, user: trader });
  try {
    assert.ok(view.host.querySelector('[data-ui6-page="TradingHistory"]'));
  } finally { await view.close(); }

  view = await renderAt('/scaling', { isAuthenticated: true, user: trader });
  try {
    assert.ok(view.host.querySelector('[data-ui6-page="ScalingProgress"]'));
    assert.match(location(view.host), /^\/scaling$/);
  } finally { await view.close(); }

  // A fresh MemoryRouter mount represents refresh without needing a browser sweep.
  view = await renderAt('/scaling', { isAuthenticated: true, user: trader });
  try {
    assert.ok(view.host.querySelector('[data-ui6-page="ScalingProgress"]'));
  } finally { await view.close(); }
});

test('UI6 trading challenges DOM rejects a wrong owner then binds retry, list navigation, pagination and program actions', { concurrency: false }, async () => {
  const view = installDom();
  let releaseFirst;
  let pageTwoCalls = 0;
  const calls = [];
  globalThis.__ui6TradingAxios = {
    get: (endpoint, config) => {
      calls.push({ endpoint, config });
      assert.equal(endpoint, '/challenges/my-challenges');
      assert.ok(config.signal instanceof AbortSignal, 'list request has an AbortSignal');
      assert.equal(config.signal.aborted, false, 'active list request is not already cancelled');
      assert.deepEqual(config.params, { page: config.params.page, per_page: 20 });
      if (calls.length === 1) return new Promise((resolve) => { releaseFirst = resolve; });
      if (config.params.page === 1) return Promise.resolve(response(listPayload(1, [challengeRow()])));
      pageTwoCalls += 1;
      return Promise.resolve(response(listPayload(2, pageTwoCalls === 1 ? [challengeRow({ id: 42 })] : [])));
    },
  };
  const principal = { key: 'challenge-owner-9-7-trader', ready: true, expectedOwner: owner };
  try {
    await act(async () => {
      view.root.render(React.createElement(require('react-router-dom').MemoryRouter, { initialEntries: ['/challenges'] },
        React.createElement(React.Fragment, null, React.createElement(challengeList.MyChallengesContent, { principal }), React.createElement(LocationProbe))));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[role="status"]'), 'initial list loading state');
    releaseFirst(response(listPayload(1, [challengeRow()], { owner_context: { user_id: 10, tenant_id: 7 } })));
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'owner-rejected list response');
    assert.match(text(view.host), /Challenges could not be loaded/);
    assert.doesNotMatch(text(view.host), /Recorded Evaluation/, 'wrong owner cannot become rendered challenge data');

    await click(button(view.host, 'Retry'));
    await waitFor(() => text(view.host).includes('Recorded Evaluation'), 'acknowledged owner-bound list response');
    assert.equal(calls.length, 2, 'Retry started a new real service request');
    assert.match(view.host.innerHTML, /sm:flex-row/, 'responsive shared list markup is present in the real DOM');

    await click(button(view.host, 'Browse Programs'));
    assert.equal(location(view.host), '/programs');
    await click(button(view.host, 'View recorded details'));
    assert.equal(location(view.host), '/challenges/41');

    await click(button(view.host, 'Next'));
    await waitFor(() => text(view.host).includes('Page 2 of 2'), 'next page result');
    await click(button(view.host, 'Previous'));
    await waitFor(() => text(view.host).includes('Page 1 of 2'), 'previous page result');
    await click(button(view.host, 'Next'));
    await waitFor(() => text(view.host).includes('No records on this page'), 'empty second page');
    await click(button(view.host, 'Return to first page'));
    await waitFor(() => text(view.host).includes('Page 1 of 2'), 'return-to-first result');
    await click(button(view.host, 'Next'));
    await waitFor(() => text(view.host).includes('No records on this page'), 'empty page repeats from synthetic source');
    await click(button(view.host, 'Browse Programs'));
    assert.equal(location(view.host), '/programs');
    assert.ok(calls.every(({ config }) => config.signal instanceof AbortSignal), 'every DOM read remained cancellation-bound');
  } finally {
    await view.close();
    delete globalThis.__ui6TradingAxios;
  }
});

test('UI6 trading challenge detail DOM rejects an owner mismatch and only exposes confirmed detail navigation after retry', { concurrency: false }, async () => {
  const view = installDom();
  let requests = 0;
  globalThis.__ui6TradingAxios = {
    get: async (endpoint, config) => {
      requests += 1;
      assert.equal(endpoint, '/challenges/41/progress');
      assert.ok(config.signal instanceof AbortSignal, 'detail request carries an AbortSignal');
      assert.equal(config.signal.aborted, false);
      if (requests === 1) return response(detailPayload({ owner_context: { user_id: 10, tenant_id: 7 } }));
      return response(detailPayload());
    },
  };
  const principal = { key: 'challenge-owner-9-7-trader', ready: true, expectedOwner: owner };
  try {
    await act(async () => {
      view.root.render(React.createElement(require('react-router-dom').MemoryRouter, { initialEntries: ['/challenges/41'] },
        React.createElement(React.Fragment, null, React.createElement(challengeDetail.ChallengeDetailsContent, { id: '41', principal }), React.createElement(LocationProbe))));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'detail owner mismatch failure');
    assert.doesNotMatch(text(view.host), /Recorded Evaluation/, 'wrong-owner progress is not shown as a detail acknowledgement');
    await click(button(view.host, 'Back to challenges'));
    assert.equal(location(view.host), '/challenges');
    await click(button(view.host, 'Retry'));
    await waitFor(() => text(view.host).includes('Recorded Evaluation'), 'confirmed detail after retry');
    assert.equal(requests, 2);
    assert.match(view.host.innerHTML, /md:grid-cols-2/, 'responsive detail markup is emitted to DOM');
    const backLink = view.host.querySelector('a[href="/challenges"]');
    assert.ok(backLink, 'ready-state return action is an exact Router anchor');
    await click(backLink);
    assert.equal(location(view.host), '/challenges');
  } finally {
    await view.close();
    delete globalThis.__ui6TradingAxios;
  }
});

test('UI6 trading scaling DOM keeps the synthetic caller and signal bound while retry/refresh and support navigation remain read-only', { concurrency: false }, async () => {
  const view = installDom();
  let calls = 0;
  globalThis.__ui6TradingAuth = { isAuthenticated: true, isLoading: false, user: trader };
  globalThis.__ui6TradingRecorded = {
    scaling: async (request) => {
      calls += 1;
      assert.deepEqual(request.expectedOwner, { user_id: 9, tenant_id: 7, role: 'trader' });
      assert.equal(request.admin, false);
      assert.equal(request.page, 1);
      assert.ok(request.signal instanceof AbortSignal, 'scaling read receives identity-bound signal');
      assert.equal(request.signal.aborted, false);
      if (calls === 1) throw new Error('synthetic read failure');
      return {
        owner_context: owner, data_status: 'unverified_legacy', provider_authenticated: false, currency: null,
        data: null, scaling_enabled: false,
      };
    },
  };
  try {
    await act(async () => {
      view.root.render(React.createElement(require('react-router-dom').MemoryRouter, { initialEntries: ['/scaling'] },
        React.createElement(React.Fragment, null, React.createElement(scaling.default), React.createElement(LocationProbe))));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'scaling failure state');
    assert.match(text(view.host), /No zero balance or empty result has been assumed/);
    await click(button(view.host, 'Retry recorded data'));
    await waitFor(() => text(view.host).includes('No recorded scaling plan'), 'validated empty scaling read');
    assert.match(text(view.host), /Scale-up is not enabled/);
    assert.doesNotMatch(text(view.host), /Scale Up Now|eligible to scale/);
    await click(button(view.host, 'Refresh records'));
    await waitFor(() => calls === 3, 'refresh launches a third scoped read');
    const support = view.host.querySelector('a[href="/support/my-tickets"]');
    assert.ok(support, 'support action is a real exact-destination anchor');
    await click(support);
    assert.equal(location(view.host), '/support/my-tickets');
    assert.match(view.host.innerHTML, /sm:flex-row/, 'responsive scaling markup is emitted to DOM');
  } finally {
    await view.close();
    delete globalThis.__ui6TradingRecorded;
    delete globalThis.__ui6TradingAuth;
  }
});

test('UI6 trading history DOM retries owner-bound reads, pages, applies canonical filters, exports current CSV, and follows both exact links', { concurrency: false }, async () => {
  const view = installDom();
  const requests = [];
  globalThis.__ui6TradingAuth = { isAuthenticated: true, isLoading: false, user: trader };
  globalThis.__ui6TradingRecorded = {
    history: async (request) => {
      requests.push(request);
      assert.deepEqual(request.expectedOwner, { user_id: 9, tenant_id: 7, role: 'trader' });
      assert.ok(request.signal instanceof AbortSignal, 'history request carries identity-bound signal');
      assert.equal(request.signal.aborted, false);
      const { page, symbol, type, period } = request;
      if (requests.length === 1) throw new Error('synthetic initial history failure');
      if (symbol === 'EURUSD') {
        assert.deepEqual({ page, symbol, type, period }, { page: 1, symbol: 'EURUSD', type: 'buy', period: 'week' });
        return historyView({ total: 1, filters: { symbol, type, period } });
      }
      if (requests.length === 7) return historyView({ rows: [], total: 0 });
      return historyView({ page, rows: [recordedTrade({ id: 700 + page })] });
    },
    scaling: async () => { throw new Error('not used by history'); },
  };
  const originalCreateObjectUrl = window.URL.createObjectURL;
  const originalRevokeObjectUrl = window.URL.revokeObjectURL;
  const originalAnchorClick = window.HTMLAnchorElement.prototype.click;
  const downloads = [];
  window.URL.createObjectURL = (blob) => { downloads.push(['create', blob.type]); return 'blob:ui6-trading'; };
  window.URL.revokeObjectURL = (url) => { downloads.push(['revoke', url]); };
  window.HTMLAnchorElement.prototype.click = function syntheticDownloadClick() { downloads.push(['click', this.download]); };
  try {
    await act(async () => {
      view.root.render(React.createElement(require('react-router-dom').MemoryRouter, { initialEntries: ['/trader/history'] },
        React.createElement(React.Fragment, null, React.createElement(history.default), React.createElement(LocationProbe))));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'initial history failure');
    await click(button(view.host, 'Retry recorded data'));
    await waitFor(() => text(view.host).includes('EURUSD'), 'acknowledged recorded history');

    await click(button(view.host, 'Next page'));
    await waitFor(() => text(view.host).includes('Page 2 · 2 recorded pages'), 'next recorded page');
    await click(button(view.host, 'Previous page'));
    await waitFor(() => text(view.host).includes('Page 1 · 2 recorded pages'), 'previous recorded page');
    await click(button(view.host, 'Next page'));
    await waitFor(() => text(view.host).includes('Page 2 · 2 recorded pages'), 'second page before first-page control');
    await click(button(view.host, 'First page'));
    await waitFor(() => text(view.host).includes('Page 1 · 2 recorded pages'), 'first-page result');

    await click(button(view.host, 'Refresh records'));
    await waitFor(() => text(view.host).includes('No recorded trades for these filters'), 'validated empty history result');

    const form = view.host.querySelector('form[aria-label="Recorded trade filters"]');
    const [symbol] = form.querySelectorAll('input');
    const selects = form.querySelectorAll('select');
    await setControlValue(symbol, 'eurusd');
    await setControlValue(selects[0], 'buy');
    await setControlValue(selects[1], 'week');
    assert.equal(button(view.host, 'Export current page').disabled, true, 'dirty filters cannot export a stale page');
    await submit(form);
    await waitFor(() => text(view.host).includes('EURUSD'), 'filtered current page');
    assert.equal(requests.length, 8);
    assert.deepEqual(requests[7] && {
      page: requests[7].page, per_page: requests[7].per_page, symbol: requests[7].symbol, type: requests[7].type, period: requests[7].period,
    }, { page: 1, per_page: 20, symbol: 'EURUSD', type: 'buy', period: 'week' });

    await click(button(view.host, 'Export current page'));
    assert.deepEqual(downloads, [
      ['create', 'text/csv;charset=utf-8'], ['click', 'unverified-trading-history-page-1.csv'], ['revoke', 'blob:ui6-trading'],
    ]);
    const challenges = view.host.querySelector('a[href="/challenges"]');
    const support = view.host.querySelector('a[href="/support/my-tickets"]');
    assert.ok(challenges && support, 'both recorded footer destinations are exact Router anchors');
    await click(challenges);
    assert.equal(location(view.host), '/challenges');
    await click(support);
    assert.equal(location(view.host), '/support/my-tickets');
    assert.match(view.host.innerHTML, /lg:grid-cols-4/, 'responsive history markup is emitted to DOM');
  } finally {
    window.URL.createObjectURL = originalCreateObjectUrl;
    window.URL.revokeObjectURL = originalRevokeObjectUrl;
    window.HTMLAnchorElement.prototype.click = originalAnchorClick;
    await view.close();
    delete globalThis.__ui6TradingRecorded;
    delete globalThis.__ui6TradingAuth;
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
