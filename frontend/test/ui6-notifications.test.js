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
assert.equal(require('jsdom/package.json').version, '28.1.0', 'UI6 notification DOM evidence requires the pinned JSDOM 28.1.0');
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-notifications-dom-'));
let serial = 0;

// ReactDOM is deliberately imported only after a document exists.  Components
// themselves are source modules; only their import specifiers are made portable
// in the temporary ESM copies below.
const bootstrap = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6.bootstrap.test/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrap.window, document: bootstrap.window.document, navigator: bootstrap.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
}
const { createRoot } = await import('react-dom/client');
const { Simulate } = await import('react-dom/test-utils');
const { MemoryRouter, Route, Routes, useLocation, useNavigate } = await import('react-router-dom');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const dependencies = new Map([
  ['react', pathToFileURL(require.resolve('react')).href],
  ['react/jsx-runtime', pathToFileURL(require.resolve('react/jsx-runtime')).href],
  ['react/jsx-dev-runtime', pathToFileURL(require.resolve('react/jsx-dev-runtime')).href],
  ['react-router-dom', pathToFileURL(require.resolve('react-router-dom')).href],
  ['lucide-react', pathToFileURL(require.resolve('lucide-react')).href],
]);

function externalize(source) {
  let output = source;
  for (const [specifier, absolute] of dependencies) {
    output = output
      .replaceAll(`from '${specifier}'`, `from ${JSON.stringify(absolute)}`)
      .replaceAll(`from "${specifier}"`, `from ${JSON.stringify(absolute)}`);
  }
  return output;
}

function writeTemp(name, source) {
  const target = path.join(tempDir, `${name}-${process.pid}-${serial += 1}.mjs`);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
}

async function compileSource(name, relative, replacements = []) {
  let source = fs.readFileSync(sourcePath(...relative), 'utf8');
  for (const [from, to] of replacements) source = source.replaceAll(from, to);
  const transformed = await transformWithEsbuild(externalize(source), sourcePath(...relative), {
    loader: 'jsx', jsx: 'automatic', format: 'esm',
  });
  const target = writeTemp(name, externalize(transformed.code));
  return import(`${target}?ui6-notifications=${serial}`);
}

const authUrl = sourceUrl('store', 'authStore.js');
const notificationStoreUrl = sourceUrl('stores', 'notificationStore.js');
const notificationViewUrl = sourceUrl('services', 'notificationViewService.js');
const dateUtilsUrl = sourceUrl('utils', 'dateUtils.js');
const tabNavigationUrl = sourceUrl('hooks', 'useTabNavigation.js');

const dropdownModule = await compileSource('NotificationDropdown', ['components', 'notifications', 'NotificationDropdown.jsx'], [
  ["'../../store/authStore'", JSON.stringify(authUrl)],
  ["'../../stores/notificationStore'", JSON.stringify(notificationStoreUrl)],
  ["'../../services/notificationViewService'", JSON.stringify(notificationViewUrl)],
  ["'../../utils/dateUtils'", JSON.stringify(dateUtilsUrl)],
]);
const bellSource = fs.readFileSync(sourcePath('components', 'notifications', 'NotificationBell.jsx'), 'utf8')
  .replaceAll("'../../store/authStore'", JSON.stringify(authUrl))
  .replaceAll("'../../stores/notificationStore'", JSON.stringify(notificationStoreUrl))
  .replaceAll("'./NotificationDropdown'", JSON.stringify(pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((entry) => entry.startsWith('NotificationDropdown-')))).href));
const bellTransformed = await transformWithEsbuild(externalize(bellSource), sourcePath('components', 'notifications', 'NotificationBell.jsx'), { loader: 'jsx', jsx: 'automatic', format: 'esm' });
const bellUrl = writeTemp('NotificationBell-real', externalize(bellTransformed.code));
const bellModuleReal = await import(`${bellUrl}?ui6-notifications=${serial}`);
const notificationsModule = await compileSource('Notifications', ['pages', 'Notifications.jsx'], [
  ["'../store/authStore'", JSON.stringify(authUrl)],
  ["'../stores/notificationStore'", JSON.stringify(notificationStoreUrl)],
  ["'../services/notificationViewService'", JSON.stringify(notificationViewUrl)],
  ["'../utils/dateUtils'", JSON.stringify(dateUtilsUrl)],
  ["'../hooks/useTabNavigation'", JSON.stringify(tabNavigationUrl)],
]);
const settingsModule = await compileSource('NotificationSettings', ['pages', 'settings', 'NotificationSettings.jsx'], [
  ["'../../store/authStore'", JSON.stringify(authUrl)],
  ["'../../stores/notificationStore'", JSON.stringify(notificationStoreUrl)],
]);

async function compileAppRouter() {
  let source = fs.readFileSync(sourcePath('App.jsx'), 'utf8');
  const notificationsUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((entry) => entry.startsWith('Notifications-')))).href;
  const settingsUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((entry) => entry.startsWith('NotificationSettings-')))).href;
  source = `import NotificationsPage from ${JSON.stringify(notificationsUrl)};\nimport NotificationSettingsPage from ${JSON.stringify(settingsUrl)};\n${source}`;
  source = source
    .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", "import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';")
    .replace("import useAuthStore from './store/authStore';", `import useAuthStore from ${JSON.stringify(authUrl)};`)
    .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
    .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
    .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
    .replace("import { ADMIN_ROLES } from './constants/roles';", `import { ADMIN_ROLES } from ${JSON.stringify(sourceUrl('constants', 'roles.js'))};`)
    .replace("import { postLoginDestination } from './services/navigationService.js';", `import { postLoginDestination } from ${JSON.stringify(sourceUrl('services', 'navigationService.js'))};`)
    .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
    .replace("import useNotificationStore from './stores/notificationStore.js';", `import useNotificationStore from ${JSON.stringify(notificationStoreUrl)};`)
    .replace("import RoleGuard from './components/guards/RoleGuard';", 'const RoleGuard = ({ children }) => children;');
  source = source.replace(/const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\((['"])[^'"]+\2\)\);/g, (_line, name) => {
    if (name === 'Notifications') return 'const Notifications = NotificationsPage;';
    if (name === 'NotificationSettings') return 'const NotificationSettings = NotificationSettingsPage;';
    if (name === 'UserLayout') return 'const UserLayout = ({ children }) => <main data-ui6-user-layout="true">{children}</main>;';
    if (name === 'Login') return 'const Login = () => <p data-ui6-login="true">Login</p>;';
    return `const ${name} = () => <div data-ui6-route-probe=${JSON.stringify(name)}>${name}</div>;`;
  });
  source = source
    .replaceAll('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6NotificationEntries}>')
    .replaceAll('</BrowserRouter>', '</MemoryRouter>')
    .replace('function App() {', "function Ui6LocationProbe() { const location = useLocation(); return <output data-ui6-location=\"true\">{location.pathname + location.search}</output>; }\n\nfunction App() {")
    .replace('</Routes>', '</Routes><Ui6LocationProbe />');
  const transformed = await transformWithEsbuild(externalize(source), sourcePath('App.jsx'), { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  const target = writeTemp('AppRouter', externalize(transformed.code));
  return import(`${target}?ui6-notifications=${serial}`);
}
const appModule = await compileAppRouter();

const Notifications = notificationsModule.default;
const NotificationSettings = settingsModule.default;
const NotificationBell = bellModuleReal.default;
const { default: api } = await import(authUrl.replace('/store/authStore.js', '/services/api.js'));
const { default: useAuthStore } = await import(authUrl);
const { default: useNotificationStore } = await import(notificationStoreUrl);

const owner = { user_id: 1, tenant_id: 10 };
const otherOwner = { user_id: 2, tenant_id: 10 };
const actor = { id: 1, tenant_id: 10, role: 'trader' };

function notification(id, type = 'system', patch = {}) {
  return {
    id,
    user_id: owner.user_id,
    type,
    title: `Synthetic ${type} ${id}`,
    message: `Recorded synthetic ${type} notification ${id}.`,
    data: null,
    priority: 'normal',
    is_read: false,
    read_at: null,
    created_at: '2026-10-12T10:00:00Z',
    ...patch,
  };
}

function preference(patch = {}) {
  const categories = {
    withdrawal: true, commission: true, kyc: true, payment: true, challenge: true, system: true,
  };
  const email = {
    withdrawal: false, commission: false, kyc: false, payment: false, challenge: false, system: false,
  };
  return {
    id: null,
    persisted: false,
    in_app: { ...categories, ...patch.in_app },
    email: { ...email, ...patch.email },
    settings: { email_enabled: true, email_frequency: 'instant', ...patch.settings },
    ...patch,
    owner_context: patch.owner_context ?? owner,
  };
}

function axiosResponse(config, data) {
  return { data, status: 200, statusText: 'OK', headers: {}, config, request: {} };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

function installDom(pathname = '/') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
    url: `http://ui6.notifications.test${pathname}`,
    pretendToBeVisual: true,
  });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLButtonElement', 'HTMLAnchorElement',
    'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle',
    'requestAnimationFrame', 'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT',
  ];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
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
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  return {
    dom,
    host: dom.window.document.getElementById('root'),
    async close(root) {
      if (root) await act(async () => { root.unmount(); });
      dom.window.close();
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
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
  let last;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const value = predicate();
      if (value) return value;
    } catch (error) { last = error; }
    await act(async () => { await settle(); });
  }
  throw last || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected a real interactive element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function setChecked(element, checked) {
  assert.ok(element, 'expected a checkbox/radio control');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked').set;
  setter.call(element, checked);
  await act(async () => {
    Simulate.change(element, { target: { checked, value: element.value } });
    await settle();
  });
}
function buttonByText(container, text, occurrence = 0) {
  return [...container.querySelectorAll('button')].filter((button) => button.textContent.replace(/\s+/g, ' ').trim() === text)[occurrence];
}
function visible(container = document.body) { return container.textContent.replace(/\s+/g, ' ').trim(); }
function pagePayload(config, rows, total = rows.length, pages = Math.max(1, Math.ceil(total / (config.params?.per_page ?? 20))) ) {
  return {
    owner_context: owner,
    notifications: rows,
    total,
    page: config.params.page,
    per_page: config.params.per_page,
    pages,
  };
}
function assertBound(config, label) {
  assert.ok(config.signal instanceof AbortSignal, `${label} carries a concrete AbortSignal`);
  assert.equal(config.signal.aborted, false, `${label} starts under the active identity`);
}
function setActor(next = actor) {
  useAuthStore.setState({
    user: next ? { ...next } : null,
    isAuthenticated: Boolean(next),
    isLoading: false,
    init: async () => {},
  });
}
function resetNotifications() {
  useNotificationStore.getState().reset();
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
}
function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { 'data-ui6-location': 'true' }, `${location.pathname}${location.search}`);
}
function BackControl() {
  const navigate = useNavigate();
  return React.createElement('button', { type: 'button', 'data-ui6-back': 'true', onClick: () => navigate(-1) }, 'Synthetic router back');
}

// This runs the exact current App route expressions with the source notification
// pages; unrelated lazy routes are inert local probes only.
test('UI6 notifications: actual App router redirects a guest, permits authenticated roles, and remounts both source routes', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const originalAuth = useAuthStore.getState();
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ method: config.method, url: config.url, params: config.params, signal: config.signal });
    assertBound(config, `${config.method} ${config.url}`);
    if (config.url === '/notifications/') return axiosResponse(config, pagePayload(config, [notification(7, 'system')], 1, 1));
    if (config.url === '/notifications/preferences') return axiosResponse(config, preference());
    if (config.url === '/notifications/unread-count') return axiosResponse(config, { owner_context: owner, count: 1 });
    throw new Error(`Unexpected route request ${config.method} ${config.url}`);
  };
  let view;
  try {
    setActor(null);
    globalThis.__ui6NotificationEntries = ['/notifications'];
    view = installDom('/notifications');
    let root = createRoot(view.host);
    await act(async () => { root.render(React.createElement(appModule.default)); await settle(); });
    await waitFor(() => view.host.querySelector('[data-ui6-location]')?.textContent === '/login?redirect=%2Fnotifications', 'guest redirect through actual App route');
    assert.equal(calls.length, 0, 'guest redirect cannot start a notification request');
    await view.close(root);

    setActor({ ...actor, role: 'trader' });
    globalThis.__ui6NotificationEntries = ['/notifications'];
    view = installDom('/notifications');
    root = createRoot(view.host);
    await act(async () => { root.render(React.createElement(appModule.default)); await settle(); });
    await waitFor(() => visible(view.host).includes('Notifications'), 'trader is permitted on /notifications');
    assert.ok(view.host.querySelector('[data-ui6-user-layout]'), 'current App wraps the route in its router-owned user layout');
    assert.match(view.host.querySelector('div.mx-auto')?.className ?? '', /sm:p-6/, 'mounted page retains its shared responsive desktop/mobile utility');
    await view.close(root);

    setActor({ ...actor, role: 'master' });
    globalThis.__ui6NotificationEntries = ['/settings/notifications'];
    view = installDom('/settings/notifications');
    root = createRoot(view.host);
    await act(async () => { root.render(React.createElement(appModule.default)); await settle(); });
    await waitFor(() => visible(view.host).includes('Notification settings'), 'authenticated non-user role is not forbidden by the current route');
    assert.match(view.host.querySelector('div.mx-auto')?.className ?? '', /sm:p-6/, 'settings DOM retains shared responsive utility');
    await view.close(root);

    setActor({ ...actor, role: 'trader' });
    globalThis.__ui6NotificationEntries = ['/notifications'];
    view = installDom('/notifications');
    root = createRoot(view.host);
    await act(async () => { root.render(React.createElement(appModule.default)); await settle(); });
    await waitFor(() => visible(view.host).includes('Synthetic system 7'), 'MemoryRouter remount refreshes the source page');
    assert.equal(calls.filter((call) => call.url === '/notifications/').length, 2, 'a fresh mount is a bounded fresh source read, not cached fake data');
    await view.close(root);
  } finally {
    if (view?.dom?.window && view.host?.isConnected) await view.close(undefined);
    api.defaults.adapter = originalAdapter;
    useNotificationStore.getState().reset();
    useAuthStore.setState(originalAuth, true);
    delete globalThis.__ui6NotificationEntries;
  }
});

test('UI6 notifications: page DOM drives refresh, retry, filters, paging, acknowledged read/delete/read-all, and Router settings navigation', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const originalAuth = useAuthStore.getState();
  const initialRead = deferred();
  const calls = [];
  let initialPending = true;
  let failNextList = false;
  let emptyNextList = false;
  const markAttempts = new Map();
  setActor(actor);
  api.defaults.adapter = async (config) => {
    const method = String(config.method || 'get').toLowerCase();
    calls.push({ method, url: config.url, params: config.params, data: config.data, signal: config.signal });
    assertBound(config, `${method} ${config.url}`);
    if (method === 'get' && config.url === '/notifications/') {
      if (initialPending) {
        initialPending = false;
        return initialRead.promise;
      }
      if (failNextList) {
        failNextList = false;
        throw new Error('Synthetic notification list failure');
      }
      if (emptyNextList) {
        emptyNextList = false;
        return axiosResponse(config, pagePayload(config, [], 0, 0));
      }
      const filter = config.params.type;
      const page = config.params.page;
      assert.ok(!Object.values(config.params).includes(null), 'page request does not serialize null filters');
      if (filter === 'kyc') return axiosResponse(config, pagePayload(config, [notification(7, 'kyc')], 1, 1));
      if (page === 2) return axiosResponse(config, pagePayload(config, [notification(10, 'challenge')], 40, 2));
      return axiosResponse(config, pagePayload(config, [
        notification(7, 'kyc'), notification(8, 'challenge'), notification(9, 'system', { is_read: true, read_at: '2026-10-12T10:01:00Z' }),
      ], 40, 2));
    }
    if (method === 'post' && config.url === '/notifications/7/read') {
      const attempt = (markAttempts.get(7) ?? 0) + 1;
      markAttempts.set(7, attempt);
      return axiosResponse(config, {
        owner_context: attempt === 1 ? otherOwner : owner,
        notification: notification(7, 'kyc', { is_read: true, read_at: '2026-10-12T10:02:00Z' }),
      });
    }
    if (method === 'post' && config.url === '/notifications/8/read') return axiosResponse(config, {
      owner_context: owner,
      notification: notification(8, 'challenge', { is_read: true, read_at: '2026-10-12T10:02:00Z' }),
    });
    if (method === 'post' && config.url === '/notifications/read-all') return axiosResponse(config, {
      owner_context: owner, message: 'Notifications marked as read', count: 2,
    });
    if (method === 'delete' && config.url === '/notifications/9') return axiosResponse(config, {
      owner_context: owner,
      notification: notification(9, 'system', { is_deleted: true, is_read: true, read_at: '2026-10-12T10:01:00Z' }),
    });
    if (method === 'get' && config.url === '/notifications/unread-count') return axiosResponse(config, { owner_context: owner, count: 0 });
    throw new Error(`Unexpected page request ${method} ${config.url}`);
  };
  const view = installDom('/notifications');
  const root = createRoot(view.host);
  try {
    await act(async () => {
      root.render(React.createElement(MemoryRouter, { initialEntries: ['/notifications'] }, React.createElement(React.Fragment, null, React.createElement(Notifications), React.createElement(LocationProbe))));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[aria-label="Loading notifications"]'), 'initial DOM loading state');
    initialRead.resolve(axiosResponse({ method: 'get', url: '/notifications/', params: { page: 1, per_page: 20 } }, pagePayload({ params: { page: 1, per_page: 20 } }, [
      notification(7, 'kyc'), notification(8, 'challenge'), notification(9, 'system', { is_read: true, read_at: '2026-10-12T10:01:00Z' }),
    ], 40, 2)));
    await waitFor(() => visible(view.host).includes('Synthetic kyc 7'), 'initial owner-matched page response');

    failNextList = true;
    await click(buttonByText(view.host, 'Refresh'));
    await waitFor(() => visible(view.host).includes('Synthetic notification list failure'), 'refresh failure is visible and has no fabricated rows');
    assert.equal(view.host.querySelectorAll('article').length, 0, 'failed refresh clears stale rows');
    await click(buttonByText(view.host, 'Try again'));
    await waitFor(() => visible(view.host).includes('Synthetic challenge 8'), 'retry obtains a fresh verified response');

    await click(buttonByText(view.host, 'KYC'));
    await waitFor(() => buttonByText(view.host, 'KYC').getAttribute('aria-selected') === 'true', 'KYC tab state');
    assert.equal(calls.at(-1).params.type, 'kyc', 'filter action binds the tab to canonical GET parameters');
    await click(buttonByText(view.host, 'All'));
    await waitFor(() => buttonByText(view.host, 'All').getAttribute('aria-selected') === 'true', 'all tab recovery');

    await click(buttonByText(view.host, 'Next'));
    await waitFor(() => visible(view.host).includes('Page 2 of 2'), 'next page response');
    assert.equal(calls.at(-1).params.page, 2, 'Next invokes the bounded second page request');
    await click(buttonByText(view.host, 'Previous'));
    await waitFor(() => visible(view.host).includes('Page 1 of 2'), 'previous page response');
    assert.equal(calls.at(-1).params.page, 1, 'Previous invokes the bounded first page request');

    await click(buttonByText(view.host, 'Mark read'));
    await waitFor(() => visible(view.host).includes('Notification response owner does not match the active account'), 'bad owner acknowledgement is surfaced');
    assert.ok(buttonByText(view.host, 'Mark read'), 'unacknowledged read leaves the row actionable');
    await click(buttonByText(view.host, 'Mark read'));
    await waitFor(() => {
      const kycArticle = [...view.host.querySelectorAll('article')].find((article) => article.textContent.includes('Synthetic kyc 7'));
      return kycArticle && !buttonByText(kycArticle, 'Mark read');
    }, 'owner-matched read acknowledgement updates the recorded row in the DOM');

    const challengeArticle = [...view.host.querySelectorAll('article')].find((article) => article.textContent.includes('Synthetic challenge 8'));
    await click(challengeArticle.querySelector('button'));
    await waitFor(() => view.host.querySelector('[data-ui6-location]').textContent === '/challenges', 'opened notification navigates only after matching read acknowledgement');

    await click(view.host.querySelector('[aria-label="Delete Synthetic system 9"]'));
    await waitFor(() => !visible(view.host).includes('Synthetic system 9'), 'owner-matched delete acknowledgement removes only the recorded row');
    await click(buttonByText(view.host, 'Mark all read'));
    await waitFor(() => ![...view.host.querySelectorAll('button')].some((button) => button.textContent.trim() === 'Mark read'), 'read-all acknowledgement updates every remaining page row');

    emptyNextList = true;
    await click(buttonByText(view.host, 'Refresh'));
    await waitFor(() => visible(view.host).includes('No notifications found.'), 'verified empty result is rendered distinctly from failure');

    // Restore a real source page response before exercising the settings action.
    await click(buttonByText(view.host, 'Refresh'));
    await waitFor(() => visible(view.host).includes('Synthetic kyc 7'), 'page recovers from empty with a fresh GET');
    await click(buttonByText(view.host, 'Settings'));
    await waitFor(() => view.host.querySelector('[data-ui6-location]').textContent === '/settings/notifications', 'settings control uses MemoryRouter destination');

    const writes = calls.filter((call) => ['post', 'delete'].includes(call.method));
    assert.deepEqual(writes.map((call) => [call.method, call.url]), [
      ['post', '/notifications/7/read'], ['post', '/notifications/7/read'], ['post', '/notifications/8/read'], ['delete', '/notifications/9'], ['post', '/notifications/read-all'],
    ]);
  } finally {
    await view.close(root);
    api.defaults.adapter = originalAdapter;
    useNotificationStore.getState().reset();
    useAuthStore.setState(originalAuth, true);
  }
});

test('UI6 notifications: bell and dropdown DOM bind count, modal-like open/close, acknowledged actions, and View all Router navigation', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const originalAuth = useAuthStore.getState();
  const calls = [];
  let deleteAttempts = 0;
  let rows = [
    notification(31, 'system'), notification(32, 'commission'), notification(33, 'challenge'), notification(34, 'system'),
  ];
  setActor({ ...actor, role: 'affiliate' });
  api.defaults.adapter = async (config) => {
    const method = String(config.method || 'get').toLowerCase();
    calls.push({ method, url: config.url, params: config.params, signal: config.signal });
    assertBound(config, `${method} ${config.url}`);
    if (method === 'get' && config.url === '/notifications/unread-count') return axiosResponse(config, { owner_context: owner, count: rows.filter((row) => !row.is_read).length });
    if (method === 'get' && config.url === '/notifications/') {
      assert.deepEqual(config.params, { page: 1, per_page: 10 }, 'dropdown uses its bounded canonical list query');
      return axiosResponse(config, pagePayload(config, rows, rows.length, 1));
    }
    if (method === 'post' && config.url === '/notifications/31/read') {
      rows = rows.map((row) => row.id === 31 ? { ...row, is_read: true, read_at: '2026-10-12T10:04:00Z' } : row);
      return axiosResponse(config, { owner_context: owner, notification: rows.find((row) => row.id === 31) });
    }
    if (method === 'post' && config.url === '/notifications/32/read') {
      rows = rows.map((row) => row.id === 32 ? { ...row, is_read: true, read_at: '2026-10-12T10:05:00Z' } : row);
      return axiosResponse(config, { owner_context: owner, notification: rows.find((row) => row.id === 32) });
    }
    if (method === 'delete' && config.url === '/notifications/33') {
      deleteAttempts += 1;
      if (deleteAttempts === 1) return axiosResponse(config, { owner_context: otherOwner, notification: { ...rows.find((row) => row.id === 33), is_deleted: true } });
      const deleted = { ...rows.find((row) => row.id === 33), is_deleted: true };
      rows = rows.filter((row) => row.id !== 33);
      return axiosResponse(config, { owner_context: owner, notification: deleted });
    }
    if (method === 'post' && config.url === '/notifications/read-all') {
      rows = rows.map((row) => ({ ...row, is_read: true, read_at: row.read_at ?? '2026-10-12T10:06:00Z' }));
      return axiosResponse(config, { owner_context: owner, message: 'Notifications marked as read', count: 2 });
    }
    throw new Error(`Unexpected dropdown request ${method} ${config.url}`);
  };
  const view = installDom('/affiliate/dashboard');
  const root = createRoot(view.host);
  try {
    await act(async () => {
      root.render(React.createElement(MemoryRouter, { initialEntries: ['/affiliate/dashboard'] }, React.createElement(React.Fragment, null, React.createElement(NotificationBell), React.createElement(LocationProbe))));
      await settle();
    });
    await waitFor(() => calls.filter((call) => call.url === '/notifications/unread-count').length === 1, 'initial owner-bound unread count');
    const bell = view.host.querySelector('button[aria-label="Notifications"]');
    await click(bell);
    await waitFor(() => view.host.querySelector('#notification-dropdown'), 'bell opens the actual dropdown');
    assert.equal(bell.getAttribute('aria-expanded'), 'true');
    await waitFor(() => visible(view.host).includes('Synthetic commission 32'), 'dropdown list response');

    const systemArticle = [...view.host.querySelectorAll('#notification-dropdown article')].find((article) => article.textContent.includes('Synthetic system 31'));
    await click(buttonByText(systemArticle, 'Read'));
    await waitFor(() => !buttonByText(systemArticle, 'Read'), 'dropdown direct Read waits for acknowledged mutation');

    const commissionArticle = [...view.host.querySelectorAll('#notification-dropdown article')].find((article) => article.textContent.includes('Synthetic commission 32'));
    await click(commissionArticle.querySelector('button'));
    await waitFor(() => view.host.querySelector('[data-ui6-location]').textContent === '/affiliate/commissions', 'dropdown open action uses role-safe destination');
    await waitFor(() => !view.host.querySelector('#notification-dropdown'), 'opened item closes the dropdown after navigation');

    await click(bell);
    await waitFor(() => view.host.querySelector('#notification-dropdown'), 'bell reopens after navigation');
    const deleteControl = view.host.querySelector('[aria-label="Delete Synthetic challenge 33"]');
    await click(deleteControl);
    await waitFor(() => visible(view.host).includes('Notification response owner does not match the active account'), 'bad delete owner acknowledgement is not treated as success');
    assert.ok(view.host.querySelector('[aria-label="Delete Synthetic challenge 33"]'), 'bad acknowledgement leaves the recorded dropdown item intact');
    await click(view.host.querySelector('[aria-label="Delete Synthetic challenge 33"]'));
    await waitFor(() => !view.host.querySelector('[aria-label="Delete Synthetic challenge 33"]'), 'matching delete acknowledgement removes the dropdown item');

    await click(buttonByText(view.host.querySelector('#notification-dropdown'), 'Mark all read'));
    await waitFor(() => ![...view.host.querySelectorAll('#notification-dropdown button')].some((button) => ['Read', 'Mark all read'].includes(button.textContent.trim() === 'Read' ? 'Read' : '')), 'read-all changes dropdown rows after acknowledgement');
    await click(buttonByText(view.host.querySelector('#notification-dropdown'), 'View all notifications'));
    await waitFor(() => view.host.querySelector('[data-ui6-location]').textContent === '/notifications', 'View all navigates through MemoryRouter');
    assert.equal(view.host.querySelector('#notification-dropdown'), null, 'View all also invokes the supplied close callback');
    assert.ok(calls.every((call) => call.signal instanceof AbortSignal), 'each bell/dropdown transport retained a signal bound by the active store identity');
  } finally {
    await view.close(root);
    api.defaults.adapter = originalAdapter;
    useNotificationStore.getState().reset();
    useAuthStore.setState(originalAuth, true);
  }
});

test('UI6 notifications: settings DOM retries a failed read and exposes mutated preference state only after an owner-matched canonical save acknowledgement', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const originalAuth = useAuthStore.getState();
  const firstPreferences = deferred();
  const calls = [];
  let pendingFirst = true;
  let saveAttempts = 0;
  setActor(actor);
  api.defaults.adapter = async (config) => {
    const method = String(config.method || 'get').toLowerCase();
    calls.push({ method, url: config.url, data: config.data, signal: config.signal });
    assertBound(config, `${method} ${config.url}`);
    if (method === 'get' && config.url === '/notifications/preferences') {
      if (pendingFirst) {
        pendingFirst = false;
        return firstPreferences.promise;
      }
      return axiosResponse(config, preference());
    }
    if (method === 'put' && config.url === '/notifications/preferences') {
      saveAttempts += 1;
      const payload = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
      const expected = {
        in_app: { withdrawal: true, commission: true, kyc: true, payment: false, challenge: true, system: true },
        email: { withdrawal: false, commission: false, kyc: false, payment: false, challenge: false, system: false },
        settings: { email_enabled: true, email_frequency: 'daily' },
      };
      assert.deepEqual(payload, expected, 'save strips read-only metadata and submits only the canonical mutated preference payload');
      const receipt = preference({ ...payload, id: 44, persisted: true });
      return axiosResponse(config, { owner_context: saveAttempts === 1 ? otherOwner : owner, preferences: receipt });
    }
    throw new Error(`Unexpected settings request ${method} ${config.url}`);
  };
  const view = installDom('/settings/notifications');
  const root = createRoot(view.host);
  try {
    await act(async () => {
      root.render(React.createElement(MemoryRouter, { initialEntries: ['/settings/notifications'] }, React.createElement(NotificationSettings)));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[aria-label="Loading notification settings"]'), 'settings loading state');
    firstPreferences.reject(new Error('Synthetic preference read failure'));
    await waitFor(() => visible(view.host).includes('Synthetic preference read failure'), 'failed settings read shown as no preferences');
    await click(buttonByText(view.host, 'Try again'));
    await waitFor(() => visible(view.host).includes('In-app notifications'), 'retry renders a verified synthetic preferences record');

    await setChecked(view.host.querySelector('[aria-label="Enable in-app Payments notifications"]'), false);
    const daily = view.host.querySelector('input[type="radio"][value="daily"]');
    await setChecked(daily, true);
    assert.equal(view.host.querySelector('[aria-label="Enable in-app Payments notifications"]').checked, false, 'mutated draft is reflected in the mounted DOM before save');
    assert.equal(daily.checked, true, 'mutated frequency is reflected in the mounted DOM before save');

    await click(buttonByText(view.host, 'Save preferences'));
    await waitFor(() => visible(view.host).includes('Unable to save notification preferences. The saved state is unknown; refresh before trying again.'), 'bad save owner acknowledgement is converted to the safe unknown-state UI message');
    assert.equal(visible(view.host).includes('Preferences saved.'), false, 'bad acknowledgement cannot display preference-save success');
    assert.equal(view.host.querySelector('[aria-label="Enable in-app Payments notifications"]').disabled, false, 'draft remains editable after rejected acknowledgement');

    await click(buttonByText(view.host, 'Save preferences'));
    await waitFor(() => visible(view.host).includes('Preferences saved.'), 'matching persisted response reveals the success state');
    assert.equal(saveAttempts, 2, 'rejected acknowledgement required a new explicit save attempt');
    assert.equal(calls.filter((call) => call.method === 'put').length, 2);
  } finally {
    await view.close(root);
    api.defaults.adapter = originalAdapter;
    useNotificationStore.getState().reset();
    useAuthStore.setState(originalAuth, true);
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
