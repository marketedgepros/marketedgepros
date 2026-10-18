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
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { createAdminClosureSettingsService } from '../src/services/adminClosureSettingsService.js';

// Install a DOM before react-dom/client is evaluated so delegated input changes are active.
const bootstrapDom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://ui6.settings.test/' });
const bootstrapKeys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'Node', 'Event', 'MouseEvent', 'IS_REACT_ACT_ENVIRONMENT'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({
  window: bootstrapDom.window,
  document: bootstrapDom.window.document,
  navigator: bootstrapDom.window.navigator,
  HTMLElement: bootstrapDom.window.HTMLElement,
  HTMLInputElement: bootstrapDom.window.HTMLInputElement,
  Node: bootstrapDom.window.Node,
  Event: bootstrapDom.window.Event,
  MouseEvent: bootstrapDom.window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
})) Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
const { createRoot } = await import('react-dom/client');
const { Simulate } = await import('react-dom/test-utils');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrapDom.window.close();

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-settings-dom-'));
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const externalImports = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
]);

function absolutizeExternalImports(source) {
  for (const [specifier, url] of externalImports) {
    source = source.replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
    source = source.replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
  }
  return source;
}
function writeModule(name, source) {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
}
async function compileModule(name, source) {
  const transformed = await transformWithEsbuild(absolutizeExternalImports(source), `${name}.jsx`, {
    loader: 'jsx', jsx: 'automatic', format: 'esm',
  });
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, absolutizeExternalImports(transformed.code));
  return import(`${pathToFileURL(target).href}?ui6-settings=${process.pid}`);
}

const authStub = writeModule('auth.mjs', `
  let state = { user: null, isAuthenticated: false, isLoading: false, init: () => {} };
  export const __setAuth = (next) => { state = { ...state, ...next }; };
  export default function useAuthStore(selector) { return typeof selector === 'function' ? selector(state) : state; }
  useAuthStore.subscribe = () => () => {};
`);
const settingsServiceStub = writeModule('settings-service.mjs', `
  import {
    adminClosureSettingsError as actualError,
    isAdminClosureSettingsContactEmail as actualContactEmailValidator,
  } from ${JSON.stringify(sourceUrl('services', 'adminClosureSettingsService.js'))};
  export const adminClosureSettingsError = actualError;
  export const isAdminClosureSettingsContactEmail = actualContactEmailValidator;
  const bound = (operation, options) => {
    globalThis.__ui6SettingsBindings.push({ operation, expectedOwner: options?.expectedOwner, signal: options?.signal, draft: options?.draft });
  };
  export const loadAdminClosureSettings = (options = {}) => {
    bound('load', options);
    return globalThis.__ui6SettingsService.loadSettings(options);
  };
  export const saveAdminClosureSettings = (options = {}) => {
    bound('save', options);
    return globalThis.__ui6SettingsService.saveSettings(options);
  };
`);
const noopModule = writeModule('noop.mjs', 'export default function Noop() { return null; }');
const toastModule = writeModule('toast.mjs', `export const ToastProvider = ({ children }) => children;`);
const notificationStoreModule = writeModule('notification-store.mjs', `export default { getState: () => ({ reset() {} }) };`);
const rolesModule = writeModule('roles.mjs', `export const ADMIN_ROLES = ['supermaster', 'master'];`);
const navigationModule = writeModule('navigation.mjs', `export const postLoginDestination = () => '/dashboard';`);

let settingsSource = fs.readFileSync(sourcePath('pages', 'admin', 'Settings.jsx'), 'utf8');
settingsSource = settingsSource
  .replaceAll('../../store/authStore.js', authStub)
  .replaceAll('../../services/adminClosureSettingsService.js', settingsServiceStub)
  .replaceAll('../../hooks/useAdminClosureSettings.js', sourceUrl('hooks', 'useAdminClosureSettings.js'));
const settingsPage = await compileModule('Settings.mjs', settingsSource);

let guardSource = fs.readFileSync(sourcePath('components', 'guards', 'RoleGuard.jsx'), 'utf8');
guardSource = guardSource.replaceAll('../../store/authStore', authStub);
const guardModule = await compileModule('RoleGuard.mjs', guardSource);
const guardUrl = pathToFileURL(path.join(tempDir, 'RoleGuard.mjs')).href;

let appSource = fs.readFileSync(sourcePath('App.jsx'), 'utf8');
appSource = appSource
  .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", "import { MemoryRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';")
  .replaceAll('./store/authStore', authStub)
  .replaceAll('./components/Notification', noopModule)
  .replaceAll('./components/RouteScrollManager.js', new URL('../src/components/RouteScrollManager.js', import.meta.url).href)
  .replaceAll('./components/ChatWidget', noopModule)
  .replaceAll('./constants/roles', rolesModule)
  .replaceAll('./services/navigationService.js', navigationModule)
  .replaceAll('./contexts/ToastContext', toastModule)
  .replaceAll('./stores/notificationStore.js', notificationStoreModule)
  .replaceAll('./components/guards/RoleGuard', guardUrl);
appSource = appSource.replace(/lazy\(\(\) => import\((['"])([^'"]+)\1\)\)/g, (_full, _quote, specifier) => {
  if (specifier === './pages/admin/Settings') return `lazy(() => import(${JSON.stringify(pathToFileURL(path.join(tempDir, 'Settings.mjs')).href)}))`;
  if (specifier === './components/admin/AdminLayout') return "({ children }) => <main data-ui6-admin-layout=\"settings\">{children}</main>";
  return `() => <div data-ui6-leaf=${JSON.stringify(specifier)} />`;
});
appSource = appSource
  .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6SettingsEntries} initialIndex={globalThis.__ui6SettingsInitialIndex}>')
  .replace('</BrowserRouter>', '</MemoryRouter>')
  .replace('function App() {', `function UI6RouteProbe() {
    const location = useLocation();
    const navigate = useNavigate();
    return <><output data-ui6-location>{location.pathname + location.search}</output><button type="button" data-ui6-back onClick={() => navigate(-1)}>Back</button><button type="button" data-ui6-forward onClick={() => navigate(1)}>Forward</button></>;
  }

  function App() {`)
  .replace('</Routes>', '</Routes><UI6RouteProbe />');
const appModule = await compileModule('App.mjs', appSource);
const auth = await import(authStub);

const owner = { user_id: 71, tenant_id: 17, role: 'supermaster' };
const draft = { name: 'Recorded tenant', contact_email: null, contact_phone: '+10000000000' };
const rootUser = { id: owner.user_id, tenant_id: owner.tenant_id, role: owner.role, first_name: 'Root', last_name: 'Admin' };

function rawPayload(tenantSettings = draft, ownerContext = { user_id: owner.user_id, tenant_id: owner.tenant_id }) {
  return {
    owner_context: ownerContext,
    scope: { kind: 'tenant', tenant_id: owner.tenant_id },
    tenant_settings: tenantSettings,
    capabilities: {
      tenant_contact: 'persisted',
      global_system: 'unavailable_no_persistence',
      payment_providers: 'unavailable_no_persistence',
    },
  };
}
function response(config, data) {
  return { data, status: 200, statusText: 'OK', headers: {}, config, request: {} };
}
function deferred() {
  let resolve;
  const promise = new Promise((next) => { resolve = next; });
  return { promise, resolve };
}
function toPayload(mode, submittedDraft = draft) {
  if (mode === 'bad_owner') return rawPayload(draft, { user_id: 72, tenant_id: owner.tenant_id });
  if (mode === 'bad_ack') return rawPayload({ ...submittedDraft, name: 'A different acknowledgement' });
  if (mode && typeof mode === 'object') return rawPayload(mode);
  return rawPayload(submittedDraft);
}
function createSyntheticSettingsService({ reads = [], writes = [], clientCalls = [] } = {}) {
  const take = async (queue, fallback) => {
    const next = queue.length ? queue.shift() : fallback;
    return next && typeof next.then === 'function' ? next : next;
  };
  const client = {
    async get(endpoint, config) {
      clientCalls.push({ method: 'get', endpoint, config });
      const mode = await take(reads, 'good');
      return response(config, toPayload(mode));
    },
    async put(endpoint, body, config) {
      clientCalls.push({ method: 'put', endpoint, body, config });
      const mode = await take(writes, 'good');
      return response(config, toPayload(mode, body.tenant_settings));
    },
  };
  return createAdminClosureSettingsService(client);
}

function installDom(url = 'https://ui6.settings.test/admin/settings') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url, pretendToBeVisual: true });
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT'];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
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
  for (const [key, value] of Object.entries(bindings)) Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom,
    root,
    container: dom.window.document.getElementById('root'),
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
async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}
async function waitFor(check, label) {
  let lastError;
  for (let attempts = 0; attempts < 80; attempts += 1) {
    try {
      const value = check();
      if (value) return value;
    } catch (error) { lastError = error; }
    await act(async () => { await settle(); });
  }
  throw lastError || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected an actionable control');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function submit(form) {
  assert.ok(form, 'expected settings form');
  await act(async () => {
    form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await settle();
  });
}
async function setInput(element, value) {
  assert.ok(element, 'expected controlled input');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const previous = element.value;
  setter.call(element, value);
  element._valueTracker?.setValue(previous);
  await act(async () => {
    element.dispatchEvent(new window.Event('input', { bubbles: true, cancelable: true }));
    element.dispatchEvent(new window.Event('change', { bubbles: true, cancelable: true }));
    Simulate.change(element, { target: { value } });
    await settle();
  });
}
function button(container, text) {
  return [...container.querySelectorAll('button')].find((node) => node.textContent.replace(/\s+/g, ' ').trim() === text);
}
function bodyText(container) { return container.textContent.replace(/\s+/g, ' ').trim(); }
function configureService(options) {
  globalThis.__ui6SettingsBindings = [];
  const clientCalls = [];
  globalThis.__ui6SettingsService = createSyntheticSettingsService({ ...options, clientCalls });
  return clientCalls;
}
function assertBoundTransport(clientCalls, expectedLoads, expectedSaves) {
  const bindings = globalThis.__ui6SettingsBindings;
  assert.equal(bindings.filter((call) => call.operation === 'load').length, expectedLoads);
  assert.equal(bindings.filter((call) => call.operation === 'save').length, expectedSaves);
  for (const call of bindings) {
    assert.deepEqual(call.expectedOwner, owner, `${call.operation} retains root owner binding`);
    assert.ok(call.signal instanceof AbortSignal, `${call.operation} gets an abort-bound signal`);
  }
  for (const call of clientCalls) {
    assert.equal(call.endpoint, '/admin/settings');
    assert.equal(call.config.timeout, 5000);
    assert.equal(call.config._skipAuthRefresh, true);
    assert.ok(call.config.signal instanceof AbortSignal);
  }
}

// This runs the current App route expression, current ProtectedRoute and current RoleGuard.
test('UI6 settings route applies guest and forbidden guards, permits root administration, and remounts through MemoryRouter', { concurrency: false }, async () => {
  const harness = installDom();
  const clientCalls = configureService({ reads: ['good', 'good'] });
  let sequence = 0;
  async function render(entries, initialIndex, nextAuth) {
    auth.__setAuth({ user: null, isAuthenticated: false, isLoading: false, init: () => {}, ...nextAuth });
    globalThis.__ui6SettingsEntries = entries;
    globalThis.__ui6SettingsInitialIndex = initialIndex;
    await act(async () => { harness.root.render(React.createElement(appModule.default, { key: `route-${sequence += 1}` })); await settle(); });
  }
  try {
    await render(['/admin/settings'], 0, {});
    await waitFor(() => harness.container.querySelector('[data-ui6-location]')?.textContent === '/login?redirect=%2Fadmin%2Fsettings', 'guest redirect');
    assert.equal(globalThis.__ui6SettingsBindings.length, 0, 'guest route cannot start a settings transport');

    await render(['/admin/settings'], 0, { isAuthenticated: true, user: { id: 80, tenant_id: 17, role: 'trader' } });
    await waitFor(() => /Access Denied/.test(bodyText(harness.container)), 'forbidden role state');
    assert.equal(harness.container.querySelector('#admin-closure-tenant-name'), null, 'forbidden role never reaches the form');
    assert.equal(globalThis.__ui6SettingsBindings.length, 0, 'forbidden role cannot start a settings transport');

    await render(['/admin/dashboard', '/admin/settings'], 1, { isAuthenticated: true, user: rootUser });
    await waitFor(() => harness.container.querySelector('#admin-closure-tenant-name'), 'permitted root settings route');
    assert.equal(harness.container.querySelector('[data-ui6-admin-layout="settings"]') !== null, true, 'the route retains its single admin layout');
    assert.match(harness.container.querySelector('[data-ui6-location]').textContent, /^\/admin\/settings$/);

    await click(harness.container.querySelector('[data-ui6-back]'));
    await waitFor(() => harness.container.querySelector('[data-ui6-location]').textContent === '/admin/dashboard', 'MemoryRouter back');
    await click(harness.container.querySelector('[data-ui6-forward]'));
    await waitFor(() => harness.container.querySelector('#admin-closure-tenant-name'), 'forward remount settings');
    assertBoundTransport(clientCalls, 2, 0);
  } finally {
    await harness.close();
    delete globalThis.__ui6SettingsService;
    delete globalThis.__ui6SettingsBindings;
  }
});

test('UI6 settings DOM refresh and save show only owner-bound acknowledged synthetic persistence', { concurrency: false }, async () => {
  const initialRead = deferred();
  const harness = installDom();
  const clientCalls = configureService({
    reads: [initialRead.promise, 'bad_owner', 'good'],
    writes: ['bad_ack', 'good'],
  });
  auth.__setAuth({ user: rootUser, isAuthenticated: true, isLoading: false, init: () => {} });
  try {
    await act(async () => {
      harness.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/settings'] }, React.createElement(Routes, null,
        React.createElement(Route, { path: '/admin/settings', element: React.createElement(settingsPage.default) }),
      )));
      await settle();
    });
    await waitFor(() => harness.container.querySelector('[role="status"][aria-busy="true"]'), 'initial loading state');
    initialRead.resolve('good');
    await waitFor(() => harness.container.querySelector('#admin-closure-tenant-name'), 'initial acknowledged read');
    assert.match(harness.container.querySelector('header').className, /sm:|lg:/, 'shared responsive header classes are reflected in the DOM');
    assert.match(harness.container.querySelector('form > div').className, /lg:grid-cols-2/, 'wide-form layout invariant is present without a browser claim');

    await click(button(harness.container, 'Refresh persisted values'));
    await waitFor(() => /Persisted settings are unavailable/.test(bodyText(harness.container)), 'owner-mismatched read failure');
    assert.equal(harness.container.querySelector('#admin-closure-tenant-name'), null, 'bad owner acknowledgement exposes no persisted form value');
    assert.doesNotMatch(bodyText(harness.container), /Saved from the server persistence acknowledgement/, 'read failure cannot fabricate success');

    await click(button(harness.container, 'Refresh persisted values'));
    await waitFor(() => harness.container.querySelector('#admin-closure-tenant-name'), 'owner-bound refresh recovery');
    const name = harness.container.querySelector('#admin-closure-tenant-name');
    await setInput(name, 'Updated tenant');
    await waitFor(() => /Unsaved changes are local until the server acknowledges persistence/.test(bodyText(harness.container)), 'local dirty draft');

    const form = harness.container.querySelector('form');
    await submit(form);
    await waitFor(() => /Settings acknowledgement does not match the submitted tenant draft/.test(bodyText(harness.container)), 'mismatched acknowledgement rejected');
    assert.equal(harness.container.querySelector('#admin-closure-tenant-name').value, 'Updated tenant', 'rejected acknowledgement cannot overwrite draft');
    assert.doesNotMatch(bodyText(harness.container), /Saved from the server persistence acknowledgement/, 'bad acknowledgement has no success state');

    await submit(form);
    await waitFor(() => /Saved from the server persistence acknowledgement/.test(bodyText(harness.container)), 'matching acknowledged save');
    assert.match(bodyText(harness.container), /The form matches the latest server acknowledgement/);
    const unavailable = harness.container.querySelector('#unavailable-settings-heading').closest('section');
    assert.equal(unavailable.querySelectorAll('input, button, select, textarea').length, 0, 'unavailable provider categories expose no activation control');
    assertBoundTransport(clientCalls, 3, 2);
    const writes = clientCalls.filter((call) => call.method === 'put');
    assert.deepEqual(writes.map((call) => call.body), [
      { tenant_settings: { name: 'Updated tenant', contact_email: null, contact_phone: '+10000000000' } },
      { tenant_settings: { name: 'Updated tenant', contact_email: null, contact_phone: '+10000000000' } },
    ], 'both form submissions use the canonical mutated payload; only the matching acknowledgement becomes visible');
  } finally {
    await harness.close();
    delete globalThis.__ui6SettingsService;
    delete globalThis.__ui6SettingsBindings;
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
