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
assert.equal(require('jsdom/package.json').version, '28.1.0', 'UI6 DOM evidence requires the direct pinned jsdom package');

// React DOM is intentionally imported only after a small DOM bootstrap. This preserves
// React's delegated onChange behavior for the real source component under JSDOM.
const bootstrap = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6-bootstrap.invalid/' });
const bootstrapKeys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'Node', 'Event', 'MouseEvent', 'IS_REACT_ACT_ENVIRONMENT'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({
  window: bootstrap.window,
  document: bootstrap.window.document,
  navigator: bootstrap.window.navigator,
  HTMLElement: bootstrap.window.HTMLElement,
  HTMLInputElement: bootstrap.window.HTMLInputElement,
  HTMLSelectElement: bootstrap.window.HTMLSelectElement,
  Node: bootstrap.window.Node,
  Event: bootstrap.window.Event,
  MouseEvent: bootstrap.window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
})) Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
const reactModule = await import('react');
const React = reactModule.default;
const { act } = reactModule;
const { createRoot } = await import('react-dom/client');
const { MemoryRouter } = await import('react-router-dom');
const { Simulate } = await import('react-dom/test-utils');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const externalImports = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
]);
const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-challenges-dom-'));
const temporaryUrl = (name) => pathToFileURL(path.join(temporaryDirectory, name)).href;
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;

function makeImportable(source) {
  for (const [specifier, absolute] of externalImports) {
    source = source
      .replaceAll(`from '${specifier}'`, `from ${JSON.stringify(absolute)}`)
      .replaceAll(`from "${specifier}"`, `from ${JSON.stringify(absolute)}`);
  }
  return source;
}
function writeModule(name, source) {
  const target = path.join(temporaryDirectory, name);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
}
async function compile(name, source) {
  const transformed = await transformWithEsbuild(makeImportable(source), `${name}.jsx`, {
    loader: 'jsx', jsx: 'automatic', format: 'esm',
  });
  const target = path.join(temporaryDirectory, `${name}.mjs`);
  fs.writeFileSync(target, makeImportable(transformed.code));
  return import(`${pathToFileURL(target).href}?ui6=${process.pid}`);
}

const authStub = writeModule('auth-store.mjs', `
  export default function useAuthStore(selector) {
    const state = globalThis.__ui6ChallengesAuth || { user: null, isAuthenticated: false, isLoading: false, init() {} };
    return typeof selector === 'function' ? selector(state) : state;
  }
  useAuthStore.subscribe = () => () => {};
`);

const roleGuardSource = fs.readFileSync(sourcePath('components', 'guards', 'RoleGuard.jsx'), 'utf8')
  .replace("from '../../store/authStore';", `from ${JSON.stringify(authStub)};`);
const roleGuard = await compile('RoleGuard', roleGuardSource);

const pageSource = fs.readFileSync(sourcePath('pages', 'admin', 'ChallengesManagement.jsx'), 'utf8')
  .replace("from '../../store/authStore';", `from ${JSON.stringify(authStub)};`)
  .replace("from '../../hooks/useDialogFocus.js';", `from ${JSON.stringify(sourceUrl('hooks', 'useDialogFocus.js'))};`)
  .replace("from '../../services/adminClosureChallengesService';", `from ${JSON.stringify(sourceUrl('services', 'adminClosureChallengesService.js'))};`);
const challengePage = await compile('ChallengesManagement', pageSource);

let appSource = fs.readFileSync(sourcePath('App.jsx'), 'utf8');
appSource = `import ChallengePage from ${JSON.stringify(temporaryUrl('ChallengesManagement.mjs'))};\n${appSource}`
  .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", "import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';")
  .replace("import { useLocation } from 'react-router-dom';", "import { useLocation, useNavigate } from 'react-router-dom';")
  .replace("import useAuthStore from './store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`)
  .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
  .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
  .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
  .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['master', 'supermaster'];")
  .replace("import { postLoginDestination } from './services/navigationService.js';", "const postLoginDestination = () => '/dashboard';")
  .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
  .replace("import useNotificationStore from './stores/notificationStore.js';", 'const useNotificationStore = { getState: () => ({ reset() {} }) };')
  .replace("import RoleGuard from './components/guards/RoleGuard';", `import RoleGuard from ${JSON.stringify(temporaryUrl('RoleGuard.mjs'))};`)
  .replace("const ChallengesManagement = lazy(() => import('./pages/admin/ChallengesManagement'));", 'const ChallengesManagement = ChallengePage;')
  .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6ChallengeEntries} initialIndex={globalThis.__ui6ChallengeInitialIndex}>')
  .replace('</BrowserRouter>', '</MemoryRouter>');
appSource = appSource.replace(/const (\w+) = lazy\(\(\) => import\(['"][^'"]+['"]\)\);/g, (_match, name) => {
  if (name === 'AdminLayout') return 'const AdminLayout = ({ children }) => <main data-admin-layout="challenge-route">{children}</main>;';
  if (name === 'Login') return 'const Login = () => <main data-page="Login">Login</main>;';
  return `const ${name} = () => <main data-page="${name}">${name}</main>;`;
});
appSource = appSource.replace('function App() {', `
function UI6ChallengeLocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <aside><output data-ui6-challenge-location="true">{location.pathname + location.search}</output><button type="button" data-ui6-challenge-back="true" onClick={() => navigate(-1)}>Router back</button><button type="button" data-ui6-challenge-forward="true" onClick={() => navigate(1)}>Router forward</button></aside>;
}
function App() {`);
appSource = appSource.replace('</Routes>', '</Routes><UI6ChallengeLocationProbe />');
const app = await compile('ChallengesAppRouter', appSource);
const api = (await import(sourceUrl('services', 'api.js'))).default;

const owner = Object.freeze({ user_id: 1, tenant_id: 7 });
const principal = Object.freeze({ owner, role: 'master', key: '[true,1,7,"master"]' });

function rawChallenge(id, status = 'active') {
  const userId = 100 + id;
  return {
    id,
    user_id: userId,
    program: { id: 9, name: 'Synthetic Evaluation' },
    user: { id: userId, name: `Synthetic User ${id}`, email: `user${id}@example.invalid` },
    legacy_status: status,
    legacy_payment_status: 'paid',
    current_phase: 1,
    total_phases: 2,
    initial_balance: '25000.00',
    current_balance: '25001.10',
    max_drawdown_observed: null,
    start_date: '2026-10-01T09:30:00Z',
    end_date: null,
    passed_at: null,
    created_at: '2026-10-01T09:30:00Z',
    data_status: 'unverified_legacy',
    provider_authenticated: false,
    mt5_account_binding: 'single_unverified_legacy',
    mt5_account: {
      login: `recorded-${id}`,
      server: 'legacy.example.invalid',
      group: 'legacy',
      status,
      balance: '25001.10',
      equity: '25001.10',
      margin: '0.00',
      free_margin: null,
      margin_level: null,
      updated_at: '2026-10-01T09:30:00Z',
      data_status: 'unverified_legacy',
      provider_authenticated: false,
    },
  };
}
function listPayload(params, { ownerContext = owner, empty = false } = {}) {
  const page = params.page;
  const status = params.status ?? null;
  const total = empty ? 0 : (status ? 20 : 40);
  const start = (page - 1) * params.per_page + 1;
  const count = Math.min(params.per_page, Math.max(0, total - (page - 1) * params.per_page));
  const rows = Array.from({ length: count }, (_unused, index) => rawChallenge(start + index, status || 'active'));
  return {
    owner_context: ownerContext,
    data_status: 'unverified_legacy',
    provider_authenticated: false,
    filters: { status, include_mt5: params.include_mt5 === 'true' },
    challenges: rows,
    pagination: { page, per_page: params.per_page, total, pages: Math.ceil(total / params.per_page) },
  };
}
function detailPayload(id, ownerContext = owner) {
  return {
    owner_context: ownerContext,
    data_status: 'unverified_legacy',
    provider_authenticated: false,
    filters: { include_mt5: true },
    challenge: rawChallenge(id),
  };
}
function response(config, data) {
  return { data, status: 200, statusText: 'OK', headers: {}, config, request: {} };
}

function installDom(url = 'http://ui6-challenges.invalid/admin/challenges') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url, pretendToBeVisual: true });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'Node', 'Element',
    'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle', 'localStorage',
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
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom,
    root,
    host: dom.window.document.getElementById('root'),
    async close() {
      await act(async () => root.unmount());
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      dom.window.close();
    },
  };
}

const delay = () => new Promise((resolve) => setTimeout(resolve, 0));
async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await delay();
}
async function waitFor(predicate, label) {
  let failure;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const value = predicate();
      if (value) return value;
    } catch (error) { failure = error; }
    await act(async () => { await settle(); });
  }
  throw failure || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected current DOM action control');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function setControlValue(element, value) {
  assert.ok(element, 'expected current DOM form control');
  const prototype = element.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
  setter.call(element, value);
  await act(async () => {
    Simulate.change(element, { target: { value } });
    await settle();
  });
}
function text(host) { return host.textContent.replace(/\s+/g, ' ').trim(); }
function button(host, label) {
  return [...host.querySelectorAll('button')].find((candidate) => candidate.textContent.replace(/\s+/g, ' ').trim() === label);
}
function location(host) { return host.querySelector('[data-ui6-challenge-location="true"]')?.textContent; }

// The current App route expression, current ProtectedRoute and current RoleGuard execute here;
// unrelated lazy leaves remain inert probes only. The actual ChallengesManagement page remains live.
test('UI6 challenges route executes guest, forbidden, permitted, MemoryRouter back/forward, and refresh-remount with active source components', { concurrency: false }, async () => {
  const view = installDom();
  const previousAdapter = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, params: config.params, signal: config.signal, skip: config._skipAuthRefresh, live: !config.signal?.aborted });
    assert.equal(config.method, 'get');
    assert.equal(config.url, '/challenges/admin/all');
    assert.equal(config._skipAuthRefresh, true);
    assert.ok(config.signal instanceof AbortSignal);
    return response(config, listPayload(config.params));
  };
  let key = 0;
  async function render(entries, initialIndex, auth) {
    globalThis.__ui6ChallengeEntries = entries;
    globalThis.__ui6ChallengeInitialIndex = initialIndex;
    globalThis.__ui6ChallengesAuth = { isLoading: false, init() {}, ...auth };
    await act(async () => {
      view.root.render(React.createElement(app.default, { key: `route-${key += 1}` }));
      await settle();
    });
  }
  try {
    await render(['/admin/challenges'], 0, { isAuthenticated: false, user: null });
    await waitFor(() => location(view.host) === '/login?redirect=%2Fadmin%2Fchallenges', 'guest redirect');
    assert.equal(calls.length, 0, 'guest route must not initiate a scoped record read');

    await render(['/admin/challenges'], 0, { isAuthenticated: true, user: { id: 4, tenant_id: 7, role: 'trader' } });
    await waitFor(() => /Access Denied/.test(text(view.host)), 'forbidden role boundary');
    assert.equal(view.host.querySelector('[data-admin-layout="challenge-route"]'), null, 'forbidden role does not render the source page');
    assert.equal(calls.length, 0, 'forbidden route must not initiate a scoped record read');

    await render(['/admin/dashboard', '/admin/challenges'], 1, { isAuthenticated: true, user: { id: 1, tenant_id: 7, role: 'master' } });
    await waitFor(() => text(view.host).includes('Challenge snapshots'), 'permitted route and synthetic read');
    assert.equal(location(view.host), '/admin/challenges');
    assert.equal(calls.length, 1);
    const challengeRoot = view.host.querySelector('[data-admin-layout="challenge-route"] > div');
    assert.match(challengeRoot.className, /p-4/);
    assert.match(challengeRoot.className, /sm:p-6/);
    assert.match(text(view.host), /Scoped recorded legacy data/);

    await click(view.host.querySelector('[data-ui6-challenge-back="true"]'));
    await waitFor(() => location(view.host) === '/admin/dashboard', 'MemoryRouter back');
    await click(view.host.querySelector('[data-ui6-challenge-forward="true"]'));
    await waitFor(() => location(view.host) === '/admin/challenges' && text(view.host).includes('Challenge snapshots'), 'MemoryRouter forward');

    const beforeRefreshRemount = calls.length;
    await render(['/admin/challenges'], 0, { isAuthenticated: true, user: { id: 1, tenant_id: 7, role: 'master' } });
    await waitFor(() => text(view.host).includes('Challenge snapshots'), 'permitted refresh-remount');
    assert.ok(calls.length > beforeRefreshRemount, 'a remount performs a new identity-scoped read');
    assert.ok(calls.every((call) => call.live && call.skip === true && call.signal instanceof AbortSignal));
  } finally {
    api.defaults.adapter = previousAdapter;
    delete globalThis.__ui6ChallengeEntries;
    delete globalThis.__ui6ChallengeInitialIndex;
    delete globalThis.__ui6ChallengesAuth;
    await view.close();
  }
});

test('UI6 challenges DOM binds refresh, filter, page boundaries, local search, read-only detail and close to owner-validated synthetic reads', { concurrency: false }, async () => {
  const view = installDom();
  const previousAdapter = api.defaults.adapter;
  const calls = [];
  let releaseInitial;
  let firstList = true;
  let listMode = 'valid';
  let detailMode = 'valid';
  api.defaults.adapter = async (config) => {
    const request = {
      url: config.url,
      method: config.method,
      params: config.params,
      signal: config.signal,
      skip: config._skipAuthRefresh,
      liveOnEntry: !config.signal?.aborted,
    };
    calls.push(request);
    assert.equal(config.method, 'get', 'the management surface exposes only read calls');
    assert.equal(config._skipAuthRefresh, true, 'read must not replay an authentication refresh');
    assert.ok(config.signal instanceof AbortSignal, 'each source request carries a concrete AbortSignal');
    assert.equal(config.signal.aborted, false, 'a new source request cannot start cancelled');
    if (config.url === '/challenges/admin/all') {
      if (firstList) {
        firstList = false;
        return new Promise((resolve) => { releaseInitial = () => resolve(response(config, listPayload(config.params))); });
      }
      if (listMode === 'badOwner') return response(config, listPayload(config.params, { ownerContext: { user_id: 99, tenant_id: 7 } }));
      if (listMode === 'empty') return response(config, listPayload(config.params, { empty: true }));
      return response(config, listPayload(config.params));
    }
    const match = /^\/challenges\/admin\/(\d+)$/.exec(config.url);
    assert.ok(match, `only canonical challenge detail paths are allowed: ${config.url}`);
    const id = Number(match[1]);
    if (detailMode === 'badOwner') return response(config, detailPayload(id, { user_id: 99, tenant_id: 7 }));
    return response(config, detailPayload(id));
  };
  try {
    await act(async () => {
      view.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/challenges'] }, React.createElement(challengePage.ChallengesManagementContent, { principal })));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[role="status"]')?.textContent.includes('Loading recorded legacy snapshots'), 'initial loading state');
    assert.equal(button(view.host, 'Manual refresh').disabled, true, 'manual refresh stays disabled while its active read is unresolved');
    releaseInitial();
    await waitFor(() => text(view.host).includes('Synthetic User 1') && text(view.host).includes('Server page 1 of 2'), 'validated initial list');
    assert.equal(button(view.host, 'Previous').disabled, true, 'previous page is bounded at one');

    await click(button(view.host, 'Next'));
    await waitFor(() => text(view.host).includes('Server page 2 of 2') && text(view.host).includes('Synthetic User 21'), 'next page result');
    assert.equal(button(view.host, 'Next').disabled, true, 'next page is bounded at server last page');
    await click(button(view.host, 'Previous'));
    await waitFor(() => text(view.host).includes('Server page 1 of 2'), 'previous page result');

    await setControlValue(view.host.querySelector('select'), 'active');
    await waitFor(() => text(view.host).includes('Server page 1 of 1'), 'server-side status filter result');
    assert.deepEqual(calls.filter((call) => call.url === '/challenges/admin/all').at(-1).params, {
      page: 1, per_page: 20, status: 'active', include_mt5: 'true',
    });
    await setControlValue(view.host.querySelector('input[type="search"]'), 'no current row');
    await waitFor(() => text(view.host).includes('No recorded snapshots match this page and local search.'), 'local filter empty state');
    await setControlValue(view.host.querySelector('input[type="search"]'), 'Synthetic User 1');
    await waitFor(() => button(view.host, 'View detail'), 'local filter recovery');

    listMode = 'badOwner';
    await click(button(view.host, 'Manual refresh'));
    await waitFor(() => view.host.querySelector('[role="alert"]')?.textContent.includes('could not be loaded or validated'), 'owner mismatch is not displayed as a result');
    assert.doesNotMatch(text(view.host), /Synthetic User 1/, 'rejected owner response cannot remain projected');
    listMode = 'valid';
    await click(button(view.host, 'Manual refresh'));
    await waitFor(() => text(view.host).includes('Synthetic User 1'), 'validated refresh recovery');

    listMode = 'empty';
    await click(button(view.host, 'Manual refresh'));
    await waitFor(() => text(view.host).includes('No recorded snapshots match this page and local search.'), 'server empty state');
    listMode = 'valid';
    await click(button(view.host, 'Manual refresh'));
    await waitFor(() => button(view.host, 'View detail'), 'empty-state refresh recovery');

    detailMode = 'badOwner';
    await click(button(view.host, 'View detail'));
    await waitFor(() => view.host.querySelector('[role="dialog"]'), 'detail panel opens');
    await waitFor(() => view.host.querySelector('[role="dialog"] [role="alert"]')?.textContent.includes('could not be loaded or validated'), 'detail owner mismatch stays an error');
    await click(view.host.querySelector('button[aria-label="Close challenge detail"]'));
    await waitFor(() => !view.host.querySelector('[role="dialog"]'), 'failed detail close');

    detailMode = 'valid';
    await click(button(view.host, 'View detail'));
    await waitFor(() => view.host.querySelector('[role="dialog"]')?.textContent.includes('Synthetic User 1'), 'validated detail result');
    assert.match(view.host.querySelector('[role="dialog"]').textContent, /Read-only boundary/);
    assert.match(view.host.querySelector('[role="dialog"]').textContent, /Provider or settlement commands remain unavailable/);
    await click(view.host.querySelector('button[aria-label="Close challenge detail"]'));
    await waitFor(() => !view.host.querySelector('[role="dialog"]'), 'validated detail close');

    const listCalls = calls.filter((call) => call.url === '/challenges/admin/all');
    assert.ok(listCalls.some((call) => call.params.page === 2), 'Next binds page 2 to the source service');
    assert.ok(listCalls.some((call) => call.params.status === 'active'), 'filter binds canonical status to the source service');
    assert.ok(calls.some((call) => call.url === '/challenges/admin/1'), 'View detail binds the selected ID to the source service');
    assert.ok(calls.every((call) => call.method === 'get' && call.skip === true && call.liveOnEntry), 'no write, refresh replay, or pre-cancelled transport is fabricated');
  } finally {
    api.defaults.adapter = previousAdapter;
    await view.close();
  }
});

test.after(() => {
  fs.rmSync(temporaryDirectory, { recursive: true, force: true });
});
