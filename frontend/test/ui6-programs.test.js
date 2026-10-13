import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React, { act } from 'react';
import { Simulate } from 'react-dom/test-utils';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';
import api from '../src/services/api.js';
import useAuthStore from '../src/store/authStore.js';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-programs-dom-'));
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const dependencies = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
]);

function absolutize(source) {
  for (const [specifier, url] of dependencies) {
    source = source.replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
    source = source.replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
  }
  return source;
}

function writeTemporary(name, source) {
  const target = path.join(temporary, name);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
}

async function compile(name, source) {
  const output = path.join(temporary, name);
  const transformed = await transformWithEsbuild(absolutize(source), output, { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  fs.writeFileSync(output, absolutize(transformed.code));
  return import(`${pathToFileURL(output).href}?ui6-programs=${process.pid}`);
}

// ReactDOM reads the DOM capabilities when it is imported. Bootstrap a minimal DOM first,
// then each test replaces it with its own isolated JSDOM instance.
const bootstrap = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6.bootstrap.test/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrap.window, document: bootstrap.window.document, navigator: bootstrap.window.navigator })) {
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { createRoot } = await import('react-dom/client');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const programPageSource = fs.readFileSync(sourcePath('pages', 'admin', 'ProgramsManagement.jsx'), 'utf8')
  .replace("'../../store/authStore.js'", JSON.stringify(pathToFileURL(sourcePath('store', 'authStore.js')).href))
  .replace("'../../hooks/useDialogFocus.js'", JSON.stringify(pathToFileURL(sourcePath('hooks', 'useDialogFocus.js')).href))
  .replace("'../../services/adminClosureProgramsService.js'", JSON.stringify(pathToFileURL(sourcePath('services', 'adminClosureProgramsService.js')).href));
const ProgramsManagement = (await compile('ProgramsManagement.mjs', programPageSource)).default;

const routeAuth = writeTemporary('route-auth.mjs', `
  let state = { user: null, isAuthenticated: false, isLoading: false, init: () => {} };
  export const __setRouteAuth = (next) => { state = { ...state, ...next }; };
  export default function useAuthStore(selector) { return typeof selector === 'function' ? selector(state) : state; }
  useAuthStore.subscribe = () => () => {};
`);
const roleGuardSource = fs.readFileSync(sourcePath('components', 'guards', 'RoleGuard.jsx'), 'utf8')
  .replace("'react-router-dom'", JSON.stringify(dependencies.get('react-router-dom')))
  .replace("'../../store/authStore'", JSON.stringify(routeAuth));
const roleGuard = await compile('RoleGuard.mjs', roleGuardSource);

let appSource = fs.readFileSync(sourcePath('App.jsx'), 'utf8')
  .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", `import { MemoryRouter, Routes, Route, Navigate, useLocation, useNavigate } from ${JSON.stringify(dependencies.get('react-router-dom'))};`)
  .replace("import { useLocation } from 'react-router-dom';", '')
  .replace("import useAuthStore from './store/authStore';", `import useAuthStore from ${JSON.stringify(routeAuth)};`)
  .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
  .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
  .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
  .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['master', 'supermaster'];")
  .replace("import { postLoginDestination } from './services/navigationService.js';", "const postLoginDestination = () => '/dashboard';")
  .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
  .replace("import useNotificationStore from './stores/notificationStore.js';", 'const useNotificationStore = { getState: () => ({ reset() {} }) };')
  .replace("import RoleGuard from './components/guards/RoleGuard';", `import RoleGuard from ${JSON.stringify(pathToFileURL(path.join(temporary, 'RoleGuard.mjs')).href)};`)
  .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6ProgramsEntries} initialIndex={globalThis.__ui6ProgramsIndex}>')
  .replace('</BrowserRouter>', '</MemoryRouter>');
appSource = appSource.replace(/const (\w+) = lazy\(\(\) => import\(['"][^'"]+['"]\)\);/g, (_line, name) => (
  name === 'AdminLayout'
    ? "const AdminLayout = ({ children }) => <main data-admin-layout=\"programs-route\">{children}</main>;"
    : `const ${name} = () => <div data-route-page=\"${name}\">${name}</div>;`
));
appSource = appSource
  .replace('function App() {', "function Ui6RouteProbe() { const location = useLocation(); const navigate = useNavigate(); return <><output data-route-location=\"true\">{location.pathname + location.search}</output><button type=\"button\" data-route-back=\"true\" onClick={() => navigate(-1)}>Test back</button></>; }\n\nfunction App() {")
  .replace('</Routes>', '</Routes><Ui6RouteProbe />');
const ProgramRouteApp = (await compile('App.mjs', appSource)).default;
const routeAuthModule = await import(routeAuth);

function installDom(url = 'http://ui6.programs.test/admin/programs') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url, pretendToBeVisual: true });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement',
    'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle',
    'requestAnimationFrame', 'cancelAnimationFrame', 'localStorage', 'IS_REACT_ACT_ENVIRONMENT',
  ];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    Node: dom.window.Node,
    Element: dom.window.Element,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    localStorage: dom.window.localStorage,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(bindings)) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
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

const delay = () => new Promise((resolve) => setTimeout(resolve, 0));
async function settle() {
  for (let step = 0; step < 6; step += 1) await Promise.resolve();
  await delay();
  for (let step = 0; step < 6; step += 1) await Promise.resolve();
}
async function waitFor(predicate, label) {
  let last;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const result = predicate();
      if (result) return result;
    } catch (error) { last = error; }
    await act(async () => { await settle(); });
  }
  throw last || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected actionable DOM element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function submit(form) {
  assert.ok(form, 'expected form');
  await act(async () => {
    form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await settle();
  });
}
async function inputValue(element, value) {
  assert.ok(element, 'expected editable input');
  const prototype = element.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
  descriptor.set.call(element, value);
  await act(async () => {
    Simulate.change(element, { target: { name: element.name, value, type: element.type, checked: element.checked } });
    await settle();
  });
}
function bodyText(host = document.body) { return host.textContent.replace(/\s+/g, ' ').trim(); }
function exactButton(host, label) {
  return [...host.querySelectorAll('button')].find((item) => item.textContent.replace(/\s+/g, ' ').trim() === label);
}
function dialog(host) { return host.querySelector('[role="dialog"], [role="alertdialog"]'); }

const owner = { user_id: 41, tenant_id: 7, role: 'master' };
const principal = { id: 41, tenant_id: 7, role: 'master', first_name: 'Synthetic', last_name: 'Owner' };
function rawProgram(overrides = {}) {
  return {
    id: 19,
    tenant_id: 7,
    name: 'Recorded Evaluation',
    type: 'stored_legacy_type',
    description: null,
    account_size: '10000.00',
    profit_target: null,
    max_daily_loss: '0.00',
    max_total_loss: null,
    price: '199.99',
    profit_split: null,
    profit_split_percentage: '0.00',
    minimum_payout_amount: null,
    payout_mode: null,
    rules: { legacy: { exact: '0.00', missing: null } },
    is_active: true,
    created_at: null,
    updated_at: '2026-10-12T12:00:00Z',
    ...overrides,
  };
}
function axiosResponse(config, data) {
  return { data, status: 200, statusText: 'OK', headers: {}, config, request: {} };
}
function listPayload(page, programs, total = 21) {
  return {
    owner_context: owner,
    programs,
    pagination: { page, per_page: 20, total, pages: total === 0 ? 0 : Math.ceil(total / 20) },
  };
}

// This runs the current App route expression with actual ProtectedRoute and actual RoleGuard.
// Lazy leaf pages are inert probes only; actual ProgramsManagement is mounted in the DOM test below.
test('UI6 programs Router runs guest, forbidden, permitted, refresh-remount and MemoryRouter back outcomes', { concurrency: false }, async () => {
  const harness = installDom();
  async function render(entries, index, auth) {
    routeAuthModule.__setRouteAuth({ user: null, isAuthenticated: false, isLoading: false, init: () => {}, ...auth });
    globalThis.__ui6ProgramsEntries = entries;
    globalThis.__ui6ProgramsIndex = index;
    await act(async () => { harness.root.render(null); await settle(); });
    await act(async () => { harness.root.render(React.createElement(ProgramRouteApp)); await settle(); });
  }
  try {
    await render(['/admin/programs'], 0, {});
    await waitFor(() => harness.host.querySelector('[data-route-page="Login"]'), 'guest /admin/programs redirect');
    assert.equal(harness.host.querySelector('[data-route-location="true"]').textContent, '/login?redirect=%2Fadmin%2Fprograms');

    await render(['/admin/programs'], 0, { user: { ...principal, role: 'trader' }, isAuthenticated: true });
    await waitFor(() => bodyText(harness.host).includes('Access Denied'), 'forbidden role state');
    assert.equal(harness.host.querySelector('[data-route-page="ProgramsManagement"]'), null, 'forbidden role cannot reach programs leaf');

    await render(['/admin/dashboard', '/admin/programs'], 1, { user: principal, isAuthenticated: true });
    await waitFor(() => harness.host.querySelector('[data-route-page="ProgramsManagement"]'), 'permitted programs route');
    assert.ok(harness.host.querySelector('[data-admin-layout="programs-route"]'), 'permitted route retains AdminLayout');
    await click(harness.host.querySelector('[data-route-back="true"]'));
    await waitFor(() => harness.host.querySelector('[data-route-page="AdminDashboard"]'), 'MemoryRouter back');

    await render(['/admin/programs'], 0, { user: principal, isAuthenticated: true });
    await waitFor(() => harness.host.querySelector('[data-route-page="ProgramsManagement"]'), 'permitted refresh remount');
  } finally {
    await harness.close();
  }
});

test('UI6 programs management DOM binds retry, dialogs, pagination and server-confirmed owner acknowledgements', { concurrency: false }, async () => {
  const harness = installDom();
  const originalAuth = useAuthStore.getState();
  const originalAdapter = api.defaults.adapter;
  const requests = [];
  const reads = ['failure', 'list', 'empty', 'list', 'page2', 'list'];
  let pageOneRecords = [rawProgram()];
  const pageTwoRecords = [rawProgram({ id: 39, name: 'Second page program' })];
  let catalogTotal = 21;
  let releaseInitialRead;
  const initialRead = new Promise((resolve) => { releaseInitialRead = resolve; });
  let createAttempt = 0;
  let updateAttempt = 0;
  let deleteAttempt = 0;
  api.defaults.adapter = async (config) => {
    const method = String(config.method || 'get').toLowerCase();
    requests.push({ method, url: config.url, params: config.params, data: config.data, signal: config.signal, skip: config._skipAuthRefresh });
    assert.equal(config._skipAuthRefresh, true, 'program transport never asks the auth interceptor to replay');
    assert.ok(config.signal instanceof AbortSignal, 'program transport is abortable');
    assert.equal(config.signal.aborted, false, 'active synthetic request is not pre-aborted');
    if (method === 'get' && config.url === '/admin/programs') {
      const mode = reads.shift();
      if (mode === 'failure') {
        await initialRead;
        throw new Error('Synthetic initial catalog failure');
      }
      if (mode === 'empty') return axiosResponse(config, listPayload(1, [], 0));
      if (mode === 'page2' || config.params.page === '2') {
        assert.deepEqual(config.params, { page: '2', per_page: '20' });
        return axiosResponse(config, listPayload(2, pageTwoRecords, catalogTotal));
      }
      assert.deepEqual(config.params, { page: '1', per_page: '20' });
      return axiosResponse(config, listPayload(1, pageOneRecords, catalogTotal));
    }
    const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
    if (method === 'post' && config.url === '/admin/programs') {
      createAttempt += 1;
      assert.deepEqual(body, {
        name: 'Created Program', type: 'stored_type', description: null,
        account_size: '25000.00', profit_target: null, max_daily_loss: null, max_total_loss: null,
        price: '199.99', profit_split: null, profit_split_percentage: null,
        minimum_payout_amount: null, payout_mode: null, rules: {}, is_active: true,
      });
      const created = rawProgram({ id: 20, name: 'Created Program', type: 'stored_type', account_size: '25000.00', max_daily_loss: null, price: '199.99', rules: {} });
      if (createAttempt === 2) {
        pageOneRecords = [created, ...pageOneRecords];
        catalogTotal += 1;
      }
      return axiosResponse(config, {
        owner_context: createAttempt === 1 ? { ...owner, user_id: 99 } : owner,
        program: created,
      });
    }
    if (method === 'put' && config.url === '/admin/programs/19') {
      updateAttempt += 1;
      assert.equal(body.name, 'Recorded Updated');
      if (updateAttempt === 2) pageOneRecords = pageOneRecords.map((program) => (
        program.id === 19 ? { ...program, name: 'Recorded Updated' } : program
      ));
      return axiosResponse(config, {
        owner_context: owner,
        program: rawProgram({ id: updateAttempt === 1 ? 99 : 19, name: 'Recorded Updated' }),
      });
    }
    if (method === 'delete' && config.url === '/admin/programs/19') {
      deleteAttempt += 1;
      assert.equal(body, undefined);
      if (deleteAttempt === 2) {
        pageOneRecords = pageOneRecords.filter((program) => program.id !== 19);
        catalogTotal -= 1;
      }
      return axiosResponse(config, { owner_context: owner, deleted_program_id: deleteAttempt === 1 ? 99 : 19 });
    }
    throw new Error(`Unexpected synthetic transport request: ${method} ${config.url}`);
  };
  useAuthStore.setState({ user: principal, isAuthenticated: true, isLoading: false, error: null, init: async () => {} });
  try {
    await act(async () => { harness.root.render(React.createElement(ProgramsManagement)); await settle(); });
    await waitFor(() => harness.host.querySelector('[aria-busy="true"]'), 'initial catalog loading');
    await act(async () => { releaseInitialRead(); await settle(); });
    await waitFor(() => harness.host.querySelector('[role="alert"]') && exactButton(harness.host, 'Retry catalog request'), 'initial catalog failure');
    const responsiveHeader = harness.host.querySelector('header');
    assert.match(responsiveHeader.className, /sm:flex-row/, 'actual shared header carries its responsive desktop/mobile layout contract');

    await click(exactButton(harness.host, 'Retry catalog request'));
    await waitFor(() => bodyText(harness.host).includes('Recorded Evaluation'), 'retry list acknowledgement');
    assert.match(harness.host.querySelector('table').className, /min-w-\[1100px\]/, 'actual table exposes narrow-screen horizontal containment');

    await click(exactButton(harness.host, 'Refresh records'));
    await waitFor(() => bodyText(harness.host).includes('No persisted program records'), 'synthetic empty catalog response');
    await click(exactButton(harness.host, 'Refresh records'));
    await waitFor(() => bodyText(harness.host).includes('Recorded Evaluation'), 'refresh list recovery');

    await click(exactButton(harness.host, 'Next'));
    await waitFor(() => bodyText(harness.host).includes('Page 2 of 2'), 'next pagination');
    await click(exactButton(harness.host, 'Previous'));
    await waitFor(() => bodyText(harness.host).includes('Page 1 of 2'), 'previous pagination');

    await click(harness.host.querySelector('[aria-label="View Recorded Evaluation"]'));
    await waitFor(() => dialog(harness.host) && bodyText(dialog(harness.host)).includes('Program record'), 'view dialog');
    await click(exactButton(dialog(harness.host), 'Close'));
    await waitFor(() => !dialog(harness.host), 'view close');

    await click(exactButton(harness.host, 'Create program'));
    await waitFor(() => dialog(harness.host) && bodyText(dialog(harness.host)).includes('Create persisted program'), 'create dialog');
    await click(exactButton(dialog(harness.host), 'Cancel'));
    await waitFor(() => !dialog(harness.host), 'create cancel');

    await click(exactButton(harness.host, 'Create program'));
    const createForm = dialog(harness.host).querySelector('form');
    await inputValue(createForm.querySelector('#program-name'), 'Created Program');
    await inputValue(createForm.querySelector('#program-type'), 'stored_type');
    await inputValue(createForm.querySelector('#program-accountSize'), '25000.00');
    await inputValue(createForm.querySelector('#program-price'), '199.99');
    await submit(createForm);
    await waitFor(() => bodyText(dialog(harness.host)).includes('owner context does not match'), 'bad create owner acknowledgement rejection');
    assert.ok(dialog(harness.host), 'bad owner acknowledgement cannot close create dialog');
    assert.equal(dialog(harness.host).querySelector('#program-name').value, 'Created Program', 'draft remains available but no created table row is inferred from a rejected acknowledgement');
    assert.equal(harness.host.querySelectorAll('tbody tr').length, 1, 'rejected create does not mutate the program table');
    await submit(createForm);
    await waitFor(() => !dialog(harness.host) && bodyText(harness.host).includes('Created the server-confirmed program record.'), 'owner-acknowledged create');
    await waitFor(() => harness.host.querySelectorAll('tbody tr').length === 2, 'canonical created range');
    assert.deepEqual([...harness.host.querySelectorAll('tbody tr td:nth-child(2) p:first-child')].map((node) => node.textContent), ['Created Program', 'Recorded Evaluation'], 'create refetches the current canonical server range instead of inserting a local row');

    await click(harness.host.querySelector('[aria-label="Edit Recorded Evaluation"]'));
    await waitFor(() => dialog(harness.host) && bodyText(dialog(harness.host)).includes('Edit persisted program'), 'edit dialog');
    const editForm = dialog(harness.host).querySelector('form');
    await inputValue(editForm.querySelector('#program-name'), 'Recorded Updated');
    await submit(editForm);
    await waitFor(() => bodyText(dialog(harness.host)).includes('did not match the requested program'), 'bad update acknowledgement rejection');
    assert.ok(dialog(harness.host), 'bad update acknowledgement cannot close editor');
    assert.ok(bodyText(harness.host).includes('Recorded Evaluation'), 'old table record remains before valid update acknowledgement');
    await submit(editForm);
    await waitFor(() => !dialog(harness.host) && bodyText(harness.host).includes('Saved the server-confirmed program record.'), 'matching update acknowledgement');
    assert.ok(bodyText(harness.host).includes('Recorded Updated'), 'mutated display comes from matching server acknowledgement');
    assert.deepEqual([...harness.host.querySelectorAll('tbody tr td:nth-child(2) p:first-child')].map((node) => node.textContent), ['Created Program', 'Recorded Updated']);

    await click(harness.host.querySelector('[aria-label="Delete Recorded Updated"]'));
    await waitFor(() => dialog(harness.host)?.getAttribute('role') === 'alertdialog', 'delete dialog');
    await click(exactButton(dialog(harness.host), 'Cancel'));
    await waitFor(() => !dialog(harness.host), 'delete cancel');
    await click(harness.host.querySelector('[aria-label="Delete Recorded Updated"]'));
    await click(exactButton(dialog(harness.host), 'Confirm server deletion'));
    await waitFor(() => bodyText(dialog(harness.host)).includes('did not match the request'), 'bad delete acknowledgement rejection');
    assert.ok(dialog(harness.host), 'bad deletion acknowledgement cannot close confirmation');
    assert.ok(bodyText(harness.host).includes('Recorded Updated'), 'rejected deletion leaves acknowledged row visible');
    await click(exactButton(dialog(harness.host), 'Confirm server deletion'));
    await waitFor(() => !dialog(harness.host) && bodyText(harness.host).includes('Deleted the server-confirmed program record.'), 'matching delete acknowledgement');
    await waitFor(() => bodyText(harness.host).includes('21 scoped records'), 'canonical delete range');
    assert.deepEqual([...harness.host.querySelectorAll('tbody tr td:nth-child(2) p:first-child')].map((node) => node.textContent), ['Created Program'], 'delete refetches the canonical server range and removes only the confirmed record');

    const readPages = requests.filter((request) => request.method === 'get').map((request) => request.params.page);
    assert.deepEqual(readPages, ['1', '1', '1', '1', '2', '1', '1', '1'], 'retry, refresh, pagination, create refetch, and delete refetch bind canonical page values');
    assert.equal(createAttempt, 2);
    assert.equal(updateAttempt, 2);
    assert.equal(deleteAttempt, 2);
    assert.ok(requests.every((request) => request.skip === true && request.signal instanceof AbortSignal), 'every source service request remained scoped and cancelable');
  } finally {
    api.defaults.adapter = originalAdapter;
    useAuthStore.setState(originalAuth, true);
    await harness.close();
  }
});

test.after(() => {
  fs.rmSync(temporary, { recursive: true, force: true });
});
