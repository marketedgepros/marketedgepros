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
import api from '../src/services/api.js';

const require = createRequire(import.meta.url);
assert.equal(require('jsdom/package.json').version, '28.1.0', 'UI6 support evidence requires the pinned direct jsdom dev dependency');

// React DOM is loaded only after a minimal DOM is available, so controlled onChange
// handlers are exercised rather than reduced to source/import evidence.
const bootstrapDom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6-support.bootstrap/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrapDom.window, document: bootstrapDom.window.document, navigator: bootstrapDom.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
}
const { createRoot } = await import('react-dom/client');
const { Simulate } = await import('react-dom/test-utils');
const { MemoryRouter, Route, Routes, useLocation } = await import('react-router-dom');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrapDom.window.close();

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const sourcePath = (...parts) => path.join(frontendDirectory, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;
const tempDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-support-dom-'));
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
  const target = path.join(tempDirectory, name);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
}
async function compileModule(name, originalPath, mutate) {
  const original = fs.readFileSync(originalPath, 'utf8');
  const transformed = await transformWithEsbuild(
    absolutizeExternalImports(mutate(original)),
    originalPath,
    { loader: 'jsx', jsx: 'automatic', format: 'esm' },
  );
  const target = path.join(tempDirectory, name);
  fs.writeFileSync(target, absolutizeExternalImports(transformed.code));
  return import(`${pathToFileURL(target).href}?ui6-support=${process.pid}-${name}`);
}

const authStub = writeModule('auth-store.mjs', `
  let state = { user: null, isAuthenticated: false, isLoading: false, init: () => {} };
  export const __setAuth = (next) => { state = { user: null, isAuthenticated: false, isLoading: false, init: () => {}, ...next }; };
  export default function useAuthStore(selector) { return typeof selector === 'function' ? selector(state) : state; }
  useAuthStore.subscribe = () => () => {};
`);
const layoutStub = writeModule('layout.mjs', `
  import React from ${JSON.stringify(externalImports.get('react'))};
  export default function Layout({ children }) { return React.createElement('section', { 'data-ui6-support-layout': 'true' }, children); }
`);
const seoStub = writeModule('seo.mjs', 'export default function SEO() { return null; }\n');
const notificationStub = writeModule('notification.mjs', 'export default function Notification() { return null; }\n');
const chatStub = writeModule('chat.mjs', 'export default function ChatWidget() { return null; }\n');
const rolesStub = writeModule('roles.mjs', "export const ADMIN_ROLES = ['admin'];\n");
const navigationStub = writeModule('navigation.mjs', "export const postLoginDestination = () => '/user/dashboard';\n");
const toastProviderStub = writeModule('toast-provider.mjs', `
  import React from ${JSON.stringify(externalImports.get('react'))};
  export const ToastProvider = ({ children }) => React.createElement(React.Fragment, null, children);
`);
const notificationsStoreStub = writeModule('notifications-store.mjs', 'export default { getState: () => ({ reset() {} }) };\n');
const roleGuardStub = writeModule('role-guard.mjs', 'export default function RoleGuard({ children }) { return children; }\n');
const supportServiceUrl = sourceUrl('services', 'supportTicketViewService.js');

function pageSourceWithIsolatedPresentationDependencies(source) {
  return source
    .replaceAll("'../../components/layout/Layout'", JSON.stringify(layoutStub))
    .replaceAll("'../../components/SEO'", JSON.stringify(seoStub))
    .replaceAll("'../../store/authStore'", JSON.stringify(authStub))
    // This remains the real support-ticket view service. Its api import is the real
    // Axios instance, whose adapter is replaced below with an in-process fixture.
    .replaceAll("'../../services/supportTicketViewService'", JSON.stringify(supportServiceUrl));
}

const createTicketModule = await compileModule(
  'CreateTicket.mjs',
  sourcePath('pages', 'support', 'CreateTicket.jsx'),
  pageSourceWithIsolatedPresentationDependencies,
);
const myTicketsModule = await compileModule(
  'MyTickets.mjs',
  sourcePath('pages', 'support', 'MyTickets.jsx'),
  pageSourceWithIsolatedPresentationDependencies,
);
const ticketDetailModule = await compileModule(
  'TicketDetail.mjs',
  sourcePath('pages', 'support', 'TicketDetail.jsx'),
  pageSourceWithIsolatedPresentationDependencies,
);
const auth = await import(authStub);

function appSourceWithSupportPages(source) {
  source = source
    .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", "import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';")
    .replace("import useAuthStore from './store/authStore';", `import useAuthStore from ${JSON.stringify(authStub)};`)
    .replace("import Notification from './components/Notification';", `import Notification from ${JSON.stringify(notificationStub)};`)
    .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
    .replace("import ChatWidget from './components/ChatWidget';", `import ChatWidget from ${JSON.stringify(chatStub)};`)
    .replace("import { ADMIN_ROLES } from './constants/roles';", `import { ADMIN_ROLES } from ${JSON.stringify(rolesStub)};`)
    .replace("import { postLoginDestination } from './services/navigationService.js';", `import { postLoginDestination } from ${JSON.stringify(navigationStub)};`)
    .replace("import { ToastProvider } from './contexts/ToastContext';", `import { ToastProvider } from ${JSON.stringify(toastProviderStub)};`)
    .replace("import useNotificationStore from './stores/notificationStore.js';", `import useNotificationStore from ${JSON.stringify(notificationsStoreStub)};`)
    .replace("import RoleGuard from './components/guards/RoleGuard';", `import RoleGuard from ${JSON.stringify(roleGuardStub)};`)
    .replace("const CreateTicket = lazy(() => import('./pages/support/CreateTicket'));", `const CreateTicket = lazy(() => import(${JSON.stringify(pathToFileURL(path.join(tempDirectory, 'CreateTicket.mjs')).href)}));`)
    .replace("const MyTickets = lazy(() => import('./pages/support/MyTickets'));", `const MyTickets = lazy(() => import(${JSON.stringify(pathToFileURL(path.join(tempDirectory, 'MyTickets.mjs')).href)}));`)
    .replace("const TicketDetail = lazy(() => import('./pages/support/TicketDetail'));", `const TicketDetail = lazy(() => import(${JSON.stringify(pathToFileURL(path.join(tempDirectory, 'TicketDetail.mjs')).href)}));`)
    .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6SupportRouteEntries}>')
    .replace('</BrowserRouter>', '</MemoryRouter>');
  source = source.replace(/^const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\(['"]\.\/[^'"]+['"]\)\);$/gm, (_line, name) => `const ${name} = () => <div data-ui6-route-probe=${JSON.stringify(name)}>${name}</div>;`);
  assert.equal((source.match(/=\s*lazy\(/g) || []).length, 3, 'only the three actual support route pages remain lazy in the router probe');
  source = source.replace('function App() {', "function UI6SupportLocationProbe() { const location = useLocation(); return <output data-ui6-support-location=\"true\">{location.pathname + location.search}</output>; }\n\nfunction App() {");
  source = source.replace('</Routes>', '</Routes><UI6SupportLocationProbe />');
  return source;
}
const appModule = await compileModule('App.mjs', sourcePath('App.jsx'), appSourceWithSupportPages);

const owner = { user_id: 9, tenant_id: 4 };
const user = { id: 9, tenant_id: 4, role: 'trader', first_name: 'Ada', last_name: 'Owner', email: 'ada@example.invalid' };
const iso = '2026-10-12T10:00:00Z';
const rawTicket = (overrides = {}) => ({
  id: 41,
  ticket_number: 'TICKET-000041',
  user_id: owner.user_id,
  subject: 'Synthetic support request',
  description: 'A synthetic account support request.',
  category: 'account',
  priority: 'high',
  status: 'open',
  created_at: iso,
  updated_at: null,
  first_response_at: null,
  resolved_at: null,
  closed_at: null,
  rating: null,
  feedback: null,
  ...overrides,
});
const rawMessage = (overrides = {}) => ({
  id: 52,
  ticket_id: 41,
  user_id: owner.user_id,
  message: 'A customer-visible synthetic reply.',
  is_staff: false,
  is_internal: false,
  created_at: iso,
  ...overrides,
});
function listPayload(page = 1, status = null, tickets = [rawTicket()]) {
  const totalTickets = status === 'closed' ? 0 : 20;
  const totalPages = Math.ceil(totalTickets / 10);
  return {
    owner_context: owner,
    tickets,
    pagination: {
      page,
      per_page: 10,
      total_tickets: totalTickets,
      total_pages: totalPages,
      has_next: page < totalPages,
      has_prev: page > 1,
    },
  };
}
function detailPayload(page = 1, state = 'open') {
  const messages = [rawMessage({ id: page === 1 ? 52 : 53, message: page === 1 ? 'First visible reply.' : 'Second visible reply.' })];
  return {
    owner_context: owner,
    ...rawTicket({ status: state, messages }),
    message_pagination: {
      page,
      per_page: 50,
      total_messages: 51,
      total_pages: 2,
      has_next: page < 2,
      has_prev: page > 1,
    },
  };
}
function emptyDetailPayload() {
  return {
    owner_context: owner,
    ...rawTicket({ messages: [] }),
    message_pagination: {
      page: 1,
      per_page: 50,
      total_messages: 0,
      total_pages: 0,
      has_next: false,
      has_prev: false,
    },
  };
}
function axiosResponse(config, data, status = 200) {
  return { data, status, statusText: 'OK', headers: {}, config, request: { synthetic: true } };
}
function bodyOf(config) {
  return typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
}
function assertBoundSyntheticRequest(config, mutation = false) {
  assert.ok(config.signal instanceof AbortSignal, 'the real service request carries a component-bound abort signal');
  assert.equal(config.signal.aborted, false, 'the current synthetic request is not aborted');
  if (mutation) assert.equal(config._skipAuthRefresh, true, 'support mutations suppress auth-refresh replay');
}

function installDom(pathname = '/') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
    url: `http://ui6-support.test${pathname}`,
    pretendToBeVisual: true,
  });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'HTMLSelectElement',
    'HTMLAnchorElement', 'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle',
    'localStorage', 'requestAnimationFrame', 'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT',
  ];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
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
  for (const [key, value] of Object.entries(bindings)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
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
  return React.createElement('output', { 'data-ui6-location': 'true' }, `${location.pathname}${location.search}`);
}
const text = (container = document.body) => container.textContent.replace(/\s+/g, ' ').trim();
async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
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
  assert.ok(element, 'expected an actionable DOM element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function submit(form) {
  assert.ok(form, 'expected a form');
  await act(async () => {
    form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await settle();
  });
}
async function setControlValue(element, value) {
  assert.ok(element, 'expected a controlled input');
  const prototype = element.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : (element.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype);
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
  const previous = element.value;
  setter.call(element, value);
  element._valueTracker?.setValue(previous);
  await act(async () => {
    Simulate.change(element, { target: { value, name: element.name } });
    await settle();
  });
}
function button(container, label, occurrence = 0) {
  return [...container.querySelectorAll('button')].filter((candidate) => text(candidate) === label)[occurrence];
}
function anchor(container, href, occurrence = 0) {
  return container.querySelectorAll(`a[href="${href}"]`)[occurrence];
}
async function renderPage(harness, Page, initial, route = null, key = initial) {
  const page = route
    ? React.createElement(Routes, null,
      React.createElement(Route, { path: route, element: React.createElement(Page) }),
      React.createElement(Route, { path: '*', element: React.createElement('p', { 'data-ui6-route-change': 'true' }, 'Synthetic route destination') }),
    )
    : React.createElement(Page);
  await act(async () => {
    harness.root.render(React.createElement(MemoryRouter, { key, initialEntries: [initial] }, page, React.createElement(LocationProbe)));
    await settle();
  });
}

// The actual App source executes its actual ProtectedRoute. Only unrelated lazy pages,
// chrome, and metadata are isolated; the three support pages and their real service remain.
test('UI6 support routes execute ProtectedRoute guest redirects and mount all three source pages for an authenticated account', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const routeCalls = [];
  api.defaults.adapter = async (config) => {
    routeCalls.push(config);
    assertBoundSyntheticRequest(config);
    if (config.method === 'get' && config.url === '/support/tickets/my') return axiosResponse(config, listPayload());
    if (config.method === 'get' && config.url === '/support/tickets/TICKET-000041') return axiosResponse(config, detailPayload());
    throw new Error(`Unexpected App-router synthetic request ${config.method} ${config.url}`);
  };
  const harness = installDom('/support/create-ticket');
  try {
    for (const pathName of ['/support/create-ticket', '/support/my-tickets', '/support/ticket/TICKET-000041']) {
      auth.__setAuth({ user: null, isAuthenticated: false });
      globalThis.__ui6SupportRouteEntries = [pathName];
      await act(async () => { harness.root.render(React.createElement(appModule.default, { key: `guest-${pathName}` })); await settle(); });
      const location = await waitFor(() => {
        const probe = harness.host.querySelector('[data-ui6-support-location]');
        return probe?.textContent.startsWith('/login?redirect=') ? probe : null;
      }, `guest redirect for ${pathName}`);
      assert.equal(location.textContent, `/login?redirect=${encodeURIComponent(pathName)}`, `ProtectedRoute preserves ${pathName} as the login return path`);
    }

    for (const [pathName, expected] of [
      ['/support/create-ticket', 'Create a support ticket'],
      ['/support/my-tickets', 'My tickets'],
      ['/support/ticket/TICKET-000041', 'Synthetic support request'],
    ]) {
      auth.__setAuth({ user, isAuthenticated: true });
      globalThis.__ui6SupportRouteEntries = [pathName];
      await act(async () => { harness.root.render(React.createElement(appModule.default, { key: `permitted-${pathName}` })); await settle(); });
      await waitFor(() => text(harness.host).includes(expected), `permitted support page ${pathName}`);
      assert.equal(harness.host.querySelector('[data-ui6-support-location]').textContent, pathName);
    }
    assert.ok(routeCalls.every((config) => config.url.startsWith('/support/tickets')), 'the route probe contacted only the synthetic support adapter');
  } finally {
    api.defaults.adapter = originalAdapter;
    await harness.close();
  }
});

test('UI6 support default pages render unavailable state for an absent principal and make no private request', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  let requests = 0;
  api.defaults.adapter = async () => { requests += 1; throw new Error('private support request must not start without a principal'); };
  try {
    for (const [Page, initial, route, expected] of [
      [createTicketModule.default, '/support/create-ticket', null, 'Support is unavailable'],
      [myTicketsModule.default, '/support/my-tickets', null, 'Tickets are unavailable'],
      [ticketDetailModule.default, '/support/ticket/TICKET-000041', '/support/ticket/:ticketNumber', 'Ticket unavailable'],
    ]) {
      auth.__setAuth({ user: null, isAuthenticated: false });
      const harness = installDom(initial);
      try {
        await renderPage(harness, Page, initial, route, `unavailable-${initial}`);
        await waitFor(() => text(harness.host).includes(expected), expected);
        assert.ok(harness.host.querySelector('[role="status"]'), `${initial} has an explicit unavailable status`);
      } finally { await harness.close(); }
    }
    assert.equal(requests, 0, 'no unavailable UI rendered a fake result or private support request');
  } finally { api.defaults.adapter = originalAdapter; }
});

test('UI6 CreateTicket DOM submits canonical data through the real service, withholds success on bad owner ack, then navigates and resets only after valid ack', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const writes = [];
  let attempt = 0;
  let releaseFirstWrite;
  const firstWrite = new Promise((resolve) => { releaseFirstWrite = resolve; });
  api.defaults.adapter = async (config) => {
    assert.equal(config.method, 'post');
    assert.equal(config.url, '/support/tickets/my');
    assertBoundSyntheticRequest(config, true);
    const body = bodyOf(config);
    writes.push({ body, signal: config.signal, skip: config._skipAuthRefresh });
    assert.deepEqual(body, {
      subject: 'Login code rejected',
      description: 'The synthetic account rejects a valid code.',
      category: 'technical',
      priority: 'high',
    }, 'the real view service removes all account identity and unknown form fields');
    attempt += 1;
    if (attempt === 1) await firstWrite;
    return axiosResponse(config, {
      owner_context: attempt === 1 ? { user_id: 10, tenant_id: 4 } : owner,
      ticket: rawTicket({
        subject: body.subject,
        description: body.description,
        category: body.category,
        priority: body.priority,
      }),
    }, 201);
  };
  auth.__setAuth({ user, isAuthenticated: true });
  const harness = installDom('/support/create-ticket');
  try {
    await renderPage(harness, createTicketModule.default, '/support/create-ticket');
    await waitFor(() => harness.host.querySelector('#ticket-subject'), 'ticket form');
    await setControlValue(harness.host.querySelector('#ticket-subject'), 'Login code rejected');
    await setControlValue(harness.host.querySelector('#ticket-category'), 'technical');
    await setControlValue(harness.host.querySelector('#ticket-priority'), 'high');
    await setControlValue(harness.host.querySelector('#ticket-description'), 'The synthetic account rejects a valid code.');
    const form = harness.host.querySelector('form');
    assert.match(form.className, /sm:p-7/, 'the rendered form keeps its source responsive spacing contract');

    await submit(form);
    await waitFor(() => button(harness.host, 'Creating ticket…'), 'create loading state');
    assert.equal(harness.host.querySelector('#ticket-subject').disabled, true, 'loading prevents a duplicate form edit');
    releaseFirstWrite();
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'rejected owner acknowledgement');
    assert.match(text(harness.host.querySelector('[role="alert"]')), /owner context does not match/i);
    assert.equal(text(harness.host).includes('Ticket created'), false, 'an invalid owner acknowledgement cannot expose success');

    await submit(form);
    await waitFor(() => text(harness.host).includes('Ticket created'), 'owner-validated create acknowledgement');
    assert.equal(writes.length, 2);
    await click(button(harness.host, 'View ticket'));
    assert.equal(harness.host.querySelector('[data-ui6-location]').textContent, '/support/ticket/TICKET-000041', 'created ticket navigation uses the exact encoded ticket destination');
    await click(button(harness.host, 'Create another ticket'));
    await waitFor(() => harness.host.querySelector('#ticket-subject'), 'fresh ticket draft');
    assert.equal(harness.host.querySelector('#ticket-subject').value, '', 'create-another clears state only after the confirmed creation view');
  } finally {
    api.defaults.adapter = originalAdapter;
    await harness.close();
  }
});

test('UI6 MyTickets DOM binds retry, refresh, filters, pages, and both create/ticket anchors to owner-validated synthetic reads', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const reads = [];
  let firstRead = true;
  let releaseFirstRead;
  const firstReadGate = new Promise((resolve) => { releaseFirstRead = resolve; });
  api.defaults.adapter = async (config) => {
    assert.equal(config.method, 'get');
    assert.equal(config.url, '/support/tickets/my');
    assertBoundSyntheticRequest(config);
    reads.push({ params: { ...config.params }, signal: config.signal });
    if (firstRead) {
      firstRead = false;
      await firstReadGate;
      throw new Error('Synthetic support list is unavailable');
    }
    const page = config.params.page;
    const status = config.params.status ?? null;
    if (status === 'closed') return axiosResponse(config, listPayload(page, status, []));
    return axiosResponse(config, listPayload(page, status, [rawTicket({ id: page === 2 ? 42 : 41, ticket_number: page === 2 ? 'TICKET-000042' : 'TICKET-000041' })]));
  };
  auth.__setAuth({ user, isAuthenticated: true });
  const harness = installDom('/support/my-tickets');
  try {
    await renderPage(harness, myTicketsModule.default, '/support/my-tickets');
    await waitFor(() => harness.host.querySelector('[role="status"]') && text(harness.host).includes('Loading tickets…'), 'initial list loading');
    releaseFirstRead();
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'initial list failure');
    await click(button(harness.host, 'Try again'));
    await waitFor(() => text(harness.host).includes('Synthetic support request'), 'retried ticket list');
    assert.match(harness.host.querySelector('header').className, /sm:px-6/, 'the rendered list header retains its responsive spacing contract');

    const headerCreate = anchor(harness.host, '/support/create-ticket');
    assert.ok(headerCreate, 'the header New ticket control is a real Router anchor');
    await click(headerCreate);
    assert.equal(harness.host.querySelector('[data-ui6-location]').textContent, '/support/create-ticket');

    await renderPage(harness, myTicketsModule.default, '/support/my-tickets', null, 'list-reset');
    await waitFor(() => text(harness.host).includes('Synthetic support request'), 'remounted ticket list after navigation');
    const beforeRefresh = reads.length;
    await click(button(harness.host, 'Refresh'));
    await waitFor(() => reads.length === beforeRefresh + 1, 'bound refresh request');

    await click(button(harness.host, 'Open'));
    await waitFor(() => reads.some((entry) => entry.params.status === 'open' && entry.params.page === 1), 'open filter request');
    await click(button(harness.host, 'Next'));
    await waitFor(() => reads.some((entry) => entry.params.status === 'open' && entry.params.page === 2), 'next ticket page request');
    await click(button(harness.host, 'Previous'));
    await waitFor(() => reads.filter((entry) => entry.params.status === 'open' && entry.params.page === 1).length >= 2, 'previous ticket page request');

    await click(anchor(harness.host, '/support/ticket/TICKET-000041'));
    assert.equal(harness.host.querySelector('[data-ui6-location]').textContent, '/support/ticket/TICKET-000041', 'ticket card has the exact detail destination');
    await click(button(harness.host, 'Closed'));
    await waitFor(() => text(harness.host).includes('No closed tickets found'), 'canonical empty filtered result');
    const emptyCreate = anchor(harness.host, '/support/create-ticket');
    assert.ok(emptyCreate, 'the empty state exposes its own real create-ticket anchor');
    await click(emptyCreate);
    assert.equal(harness.host.querySelector('[data-ui6-location]').textContent, '/support/create-ticket');
    assert.ok(reads.every(({ signal }) => signal instanceof AbortSignal), 'each list action retained its active component signal');
  } finally {
    api.defaults.adapter = originalAdapter;
    await harness.close();
  }
});

test('UI6 TicketDetail DOM preserves owner/ack boundaries for retry, refresh, links, message pages, reply, close, and rating', { concurrency: false }, async () => {
  const originalAdapter = api.defaults.adapter;
  const calls = [];
  let detailReads = 0;
  let replyAttempts = 0;
  let pendingFailures = 1;
  let emptyDetailOnNextRead = false;
  let releaseInitialFailure;
  const initialFailureGate = new Promise((resolve) => { releaseInitialFailure = resolve; });
  api.defaults.adapter = async (config) => {
    calls.push({ method: config.method, url: config.url, params: config.params, data: bodyOf(config), signal: config.signal, skip: config._skipAuthRefresh });
    if (config.method === 'get' && config.url === '/support/tickets/TICKET-000041') {
      assertBoundSyntheticRequest(config);
      detailReads += 1;
      if (pendingFailures > 0) {
        pendingFailures -= 1;
        if (detailReads === 1) await initialFailureGate;
        throw new Error('Synthetic ticket detail is unavailable');
      }
      if (emptyDetailOnNextRead) {
        emptyDetailOnNextRead = false;
        return axiosResponse(config, emptyDetailPayload());
      }
      return axiosResponse(config, detailPayload(config.params.page));
    }
    if (config.method === 'post' && config.url === '/support/tickets/TICKET-000041/messages') {
      assertBoundSyntheticRequest(config, true);
      assert.deepEqual(bodyOf(config), { message: 'Please confirm the account status.' });
      replyAttempts += 1;
      return axiosResponse(config, {
        owner_context: replyAttempts === 1 ? { user_id: 10, tenant_id: 4 } : owner,
        ticket_message: rawMessage({ message: 'Please confirm the account status.' }),
      }, 201);
    }
    if (config.method === 'post' && config.url === '/support/tickets/41/close') {
      assertBoundSyntheticRequest(config, true);
      assert.deepEqual(bodyOf(config), {});
      return axiosResponse(config, { owner_context: owner, ticket: rawTicket({ status: 'closed' }) });
    }
    if (config.method === 'post' && config.url === '/support/tickets/41/rate') {
      assertBoundSyntheticRequest(config, true);
      assert.deepEqual(bodyOf(config), { rating: 5 });
      return axiosResponse(config, { owner_context: owner, ticket: rawTicket({ status: 'closed', rating: 5 }) });
    }
    throw new Error(`Unexpected detail synthetic request ${config.method} ${config.url}`);
  };
  auth.__setAuth({ user, isAuthenticated: true });
  const harness = installDom('/support/ticket/TICKET-000041');
  try {
    await renderPage(harness, ticketDetailModule.default, '/support/ticket/TICKET-000041', '/support/ticket/:ticketNumber');
    await waitFor(() => harness.host.querySelector('[role="status"]') && text(harness.host).includes('Loading ticket…'), 'initial detail loading');
    releaseInitialFailure();
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'detail failure');
    const unavailableBack = anchor(harness.host, '/support/my-tickets');
    assert.ok(unavailableBack, 'unavailable detail state has a real My tickets anchor');
    await click(unavailableBack);
    assert.equal(harness.host.querySelector('[data-ui6-location]').textContent, '/support/my-tickets');
    pendingFailures = 1;
    await renderPage(harness, ticketDetailModule.default, '/support/ticket/TICKET-000041', '/support/ticket/:ticketNumber', 'retry-detail');
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'second detail failure for retry control');
    await click(button(harness.host, 'Try again'));
    await waitFor(() => text(harness.host).includes('Synthetic support request'), 'retried detail');
    assert.match(harness.host.querySelector('header').className, /sm:px-6/, 'the rendered detail header retains its responsive spacing contract');

    const beforeRefresh = detailReads;
    await click(button(harness.host, 'Refresh'));
    await waitFor(() => detailReads === beforeRefresh + 1, 'detail refresh request');

    await click(button(harness.host, 'More messages'));
    await waitFor(() => calls.some((call) => call.url === '/support/tickets/TICKET-000041' && call.params.page === 2), 'second message page');
    await click(button(harness.host, 'Previous messages'));
    await waitFor(() => calls.filter((call) => call.url === '/support/tickets/TICKET-000041' && call.params.page === 1).length >= 2, 'previous message page');

    await setControlValue(harness.host.querySelector('#ticket-reply'), 'Please confirm the account status.');
    const replyForm = harness.host.querySelector('form');
    await submit(replyForm);
    await waitFor(() => harness.host.querySelector('[role="alert"]'), 'rejected message owner acknowledgement');
    assert.match(text(harness.host.querySelector('[role="alert"]')), /owner context does not match/i);
    assert.equal(text(harness.host).includes('Your reply was confirmed.'), false, 'bad owner ack cannot expose a reply success notice');
    await submit(replyForm);
    await waitFor(() => text(harness.host).includes('Your reply was confirmed.'), 'confirmed reply acknowledgement');

    await click(button(harness.host, 'Close ticket'));
    await waitFor(() => text(harness.host).includes('Ticket closed.'), 'confirmed close acknowledgement');
    await click(harness.host.querySelector('button[aria-label="Rate 5 out of 5"]'));
    await waitFor(() => text(harness.host).includes('Thank you for rating this closed ticket.'), 'confirmed rating acknowledgement');
    emptyDetailOnNextRead = true;
    await click(button(harness.host, 'Refresh'));
    await waitFor(() => text(harness.host).includes('There are no customer-visible replies on this message page.'), 'empty message page after refresh');
    assert.ok(calls.every((call) => call.signal instanceof AbortSignal), 'all reads and mutations carry a concrete component signal');
    assert.equal(replyAttempts, 2, 'the reply was retried only after the UI exposed the failed acknowledgement');
    const headerBack = anchor(harness.host, '/support/my-tickets');
    await click(headerBack);
    assert.equal(harness.host.querySelector('[data-ui6-location]').textContent, '/support/my-tickets', 'header My tickets link is exact');
  } finally {
    api.defaults.adapter = originalAdapter;
    await harness.close();
  }
});

test.after(() => {
  fs.rmSync(tempDirectory, { recursive: true, force: true });
});
