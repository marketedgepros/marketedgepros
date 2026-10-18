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
import { createAdminClosureKycService } from '../src/services/adminClosureKycService.js';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = (...parts) => path.join(frontend, 'src', ...parts);
const require = createRequire(import.meta.url);
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-kyc-dom-'));
const imports = new Map([
  ['react', pathToFileURL(require.resolve('react')).href],
  ['react/jsx-runtime', pathToFileURL(require.resolve('react/jsx-runtime')).href],
  ['react/jsx-dev-runtime', pathToFileURL(require.resolve('react/jsx-dev-runtime')).href],
  ['react-router-dom', pathToFileURL(require.resolve('react-router-dom')).href],
  ['lucide-react', pathToFileURL(require.resolve('lucide-react')).href],
]);

function portable(code) {
  for (const [name, target] of imports) {
    code = code.replaceAll(`from '${name}'`, `from ${JSON.stringify(target)}`);
    code = code.replaceAll(`from ${JSON.stringify(name)}`, `from ${JSON.stringify(target)}`);
  }
  return code;
}
function replaceSpec(code, from, to) {
  return code.replaceAll(`'${from}'`, JSON.stringify(to));
}
function writeModule(name, code) {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, code);
  return pathToFileURL(target).href;
}
async function compile(name, code) {
  const target = path.join(tempDir, name);
  const result = await transformWithEsbuild(portable(code), name, { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  fs.writeFileSync(target, portable(result.code));
  return import(`${pathToFileURL(target).href}?ui6-kyc=${process.pid}`);
}

const authStub = writeModule('auth.mjs', `
  let state = { user: null, isAuthenticated: false, isLoading: false, init() {} };
  export const __setAuth = next => { state = { ...state, ...next }; };
  export default function useAuthStore(selector) { return typeof selector === 'function' ? selector(state) : state; }
  useAuthStore.subscribe = () => () => {};
`);
const toastStub = writeModule('toast.mjs', `
  const messages = [];
  export const __reset = () => { messages.length = 0; };
  export const __all = () => [...messages];
  export const useToast = () => ({ success: value => messages.push(['success', value]), error: value => messages.push(['error', value]) });
`);
const notificationStub = writeModule('notification.mjs', 'export default function Notification() { return null; }\n');
const chatStub = writeModule('chat.mjs', 'export default function ChatWidget() { return null; }\n');
const rolesStub = writeModule('roles.mjs', `export const ADMIN_ROLES = ['master', 'supermaster'];\n`);
const navigationStub = writeModule('navigation.mjs', `export const postLoginDestination = () => '/dashboard';\n`);
const toastProviderStub = writeModule('toast-provider.mjs', `
  import React from ${JSON.stringify(imports.get('react'))};
  export const ToastProvider = ({ children }) => React.createElement(React.Fragment, null, children);
`);
const notificationStoreStub = writeModule('notification-store.mjs', 'export default { getState: () => ({ reset() {} }) };\n');

let pageCode = fs.readFileSync(src('pages', 'admin', 'KYCApprovalConnected.jsx'), 'utf8');
pageCode = replaceSpec(pageCode, '../../contexts/ToastContext', toastStub);
pageCode = replaceSpec(pageCode, '../../store/authStore', authStub);
pageCode = replaceSpec(pageCode, '../../hooks/useAdminClosureKyc.js', pathToFileURL(src('hooks', 'useAdminClosureKyc.js')).href);
pageCode = replaceSpec(pageCode, '../../hooks/useDialogFocus.js', pathToFileURL(src('hooks', 'useDialogFocus.js')).href);
pageCode = replaceSpec(pageCode, '../../services/adminClosureKycService.js', pathToFileURL(src('services', 'adminClosureKycService.js')).href);
const page = await compile('KYCApprovalConnected.mjs', pageCode);

let guardCode = fs.readFileSync(src('components', 'guards', 'RoleGuard.jsx'), 'utf8');
guardCode = replaceSpec(guardCode, '../../store/authStore', authStub);
await compile('RoleGuard.mjs', guardCode);
const guardUrl = pathToFileURL(path.join(tempDir, 'RoleGuard.mjs')).href;

let appCode = fs.readFileSync(src('App.jsx'), 'utf8');
for (const [from, to] of [
  ['./store/authStore', authStub],
  ['./components/Notification', notificationStub],
  ['./components/RouteScrollManager.js', new URL('../src/components/RouteScrollManager.js', import.meta.url).href],
  ['./components/ChatWidget', chatStub],
  ['./constants/roles', rolesStub],
  ['./services/navigationService.js', navigationStub],
  ['./contexts/ToastContext', toastProviderStub],
  ['./stores/notificationStore.js', notificationStoreStub],
  ['./components/guards/RoleGuard', guardUrl],
]) appCode = replaceSpec(appCode, from, to);
appCode = appCode
  .replace(`import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';`, `import { MemoryRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';`)
  .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6KycEntries} initialIndex={globalThis.__ui6KycIndex}>')
  .replace('</BrowserRouter>', '</MemoryRouter>')
  .replace(`const Login = lazy(() => import('./pages/Login'));`, `const Login = () => <div data-ui6-route='Login'>Login</div>;`)
  .replace(`const AdminLayout = lazy(() => import('./components/admin/AdminLayout'));`, `const AdminLayout = ({ children }) => <main data-ui6-admin-layout='true'>{children}</main>;`)
  .replace(`const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboardConnected'));`, `const AdminDashboard = () => <div data-ui6-route='AdminDashboard'>Admin dashboard</div>;`)
  .replace(`const KYCApproval = lazy(() => import('./pages/admin/KYCApprovalConnected'));`, `const KYCApproval = () => <div data-ui6-route='KYCApproval'>KYC approval</div>;`)
  .replace('function App() {', `function Ui6KycProbe() {
    const location = useLocation();
    const navigate = useNavigate();
    return <div><output data-ui6-location='true'>{location.pathname + location.search}</output><button type='button' data-ui6-back='true' onClick={() => navigate(-1)}>Back</button><button type='button' data-ui6-forward='true' onClick={() => navigate(1)}>Forward</button></div>;
  }
  function App() {`)
  .replace('</Routes>', '</Routes><Ui6KycProbe />');
const app = await compile('App.mjs', appCode);
const auth = await import(authStub);
const toasts = await import(toastStub);
const { MemoryRouter } = await import('react-router-dom');

const bootstrap = new JSDOM('<!doctype html><html><body></body></html>');
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrap.window, document: bootstrap.window.document, navigator: bootstrap.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
}
const { createRoot } = await import('react-dom/client');
const { Simulate } = await import('react-dom/test-utils');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const owner = Object.freeze({ user_id: 2, tenant_id: 10 });
const admin = Object.freeze({ id: 2, tenant_id: 10, role: 'master' });
const stamp = '2026-10-12T12:00:00Z';

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body><div id=app></div></body></html>', { url: 'https://ui6.kyc.test/admin/kyc-approval', pretendToBeVisual: true });
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'HTMLAnchorElement', 'Node', 'Event', 'MouseEvent', 'MutationObserver', 'getComputedStyle', 'IS_REACT_ACT_ENVIRONMENT'];
  const prior = new Map(keys.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement, HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement, HTMLAnchorElement: dom.window.HTMLAnchorElement,
    Node: dom.window.Node, Event: dom.window.Event, MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver, getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(bindings)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  let privateClicks = 0;
  const originalClick = dom.window.HTMLAnchorElement.prototype.click;
  dom.window.HTMLAnchorElement.prototype.click = function privateSyntheticClick() { privateClicks += 1; };
  const urlEvents = [];
  const root = createRoot(dom.window.document.getElementById('app'));
  return {
    dom, root, host: dom.window.document.getElementById('app'), urlEvents,
    domHooks: { document: dom.window.document, URL: { createObjectURL: blob => { urlEvents.push(`create:${blob.size}`); return 'blob:ui6-kyc'; }, revokeObjectURL: value => { urlEvents.push(`revoke:${value}`); } } },
    get privateClicks() { return privateClicks; },
    async close() {
      await act(async () => { root.unmount(); });
      dom.window.HTMLAnchorElement.prototype.click = originalClick;
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
  await new Promise(resolve => setTimeout(resolve, 0));
}
async function waitFor(predicate, label) {
  let last;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { const result = predicate(); if (result) return result; } catch (error) { last = error; }
    await act(async () => { await settle(); });
  }
  throw last || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected an actionable DOM element');
  await act(async () => { element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true })); await settle(); });
}
async function setValue(element, value) {
  assert.ok(element, 'expected an editable DOM control');
  const prototype = element instanceof window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
  await act(async () => { Simulate.change(element, { target: { value } }); await settle(); });
}
function button(host, label) {
  return [...host.querySelectorAll('button')].find(node => node.textContent.replace(/\s+/g, ' ').trim() === label);
}

function listPayload(rows = [{ user_id: 3 }]) {
  return {
    owner_context: owner, review_scope: 'recorded_document_only', filters: { status: 'pending' },
    pagination: { page: 1, per_page: 20, total: rows.length, pages: rows.length ? 1 : 0 },
    submissions: rows.map(row => ({ user_id: 3, kyc_status: 'pending', submitted_at: stamp, documents: { id_proof: 'pending', address_proof: 'not_uploaded', selfie: 'not_uploaded', bank_statement: 'not_uploaded' }, ...row })),
  };
}
function detailPayload() {
  const document = (type, pending = type === 'id_proof') => ({ type, name: type === 'id_proof' ? 'ID proof' : type.replaceAll('_', ' '), status: pending ? 'pending' : 'not_uploaded', uploaded_at: pending ? stamp : null, notes: null, download_url: pending ? `/api/v1/kyc/documents/3/${type}/download` : null });
  return { owner_context: owner, review_scope: 'recorded_document_only', user: { id: 3, display_name: 'Synthetic subject' }, kyc_status: 'pending', submitted_at: stamp, documents: ['id_proof', 'address_proof', 'selfie', 'bank_statement'].map(type => document(type)) };
}
function reviewPayload(data, responseOwner) {
  return { owner_context: responseOwner, review_scope: 'recorded_document_only', review_recorded: true, user: { id: 3 }, document: { type: 'id_proof', status: data.status, notes: data.notes, uploaded_at: stamp, download_url: '/api/v1/kyc/documents/3/id_proof/download' } };
}

function syntheticBoundService(hooks) {
  const requests = [];
  const adapterCalls = [];
  const listPlan = ['hold', 'failure', 'empty', 'populated', 'populated'];
  const reviewPlan = ['bad-owner', 'success'];
  let releaseList;
  const adapter = {
    async get(endpoint, config) {
      adapterCalls.push({ method: 'get', endpoint, config });
      assert.equal(config._skipAuthRefresh, true, `${endpoint} must suppress credential replay`);
      assert.ok(config.signal instanceof AbortSignal, `${endpoint} must have a scoped AbortSignal`);
      assert.equal(config.signal.aborted, false, `${endpoint} cannot begin aborted`);
      if (endpoint === '/kyc/admin/submissions') {
        assert.deepEqual(config.params, { status: 'pending', page: 1, per_page: 20 });
        const plan = listPlan.shift() || 'populated';
        if (plan === 'hold') return new Promise(resolve => { releaseList = () => resolve({ data: listPayload() }); });
        if (plan === 'failure') {
          const error = new Error('synthetic list failure');
          error.response = { data: { error: 'Synthetic pending-list failure' } };
          throw error;
        }
        return { data: plan === 'empty' ? listPayload([]) : listPayload() };
      }
      if (endpoint === '/kyc/admin/submissions/3') return { data: detailPayload() };
      if (endpoint === '/api/v1/kyc/documents/3/id_proof/download') return { data: new Blob(['synthetic private KYC document']) };
      throw new Error(`Unexpected synthetic GET ${endpoint}`);
    },
    async put(endpoint, data, config) {
      adapterCalls.push({ method: 'put', endpoint, data, config });
      assert.equal(endpoint, '/kyc/admin/submissions/3/documents/id_proof');
      assert.equal(config._skipAuthRefresh, true, 'review must suppress credential replay');
      assert.ok(config.signal instanceof AbortSignal, 'review must have an identity signal');
      assert.equal(config.signal.aborted, false, 'review cannot begin aborted');
      const responseOwner = reviewPlan.shift() === 'bad-owner' ? { user_id: 91, tenant_id: 10 } : owner;
      return { data: reviewPayload(data, responseOwner) };
    },
  };
  const real = createAdminClosureKycService(adapter, hooks);
  const bind = (operation, request) => {
    requests.push({ operation, request });
    assert.deepEqual(request.expectedOwner, owner, `${operation} receives the exact current owner`);
    assert.ok(request.signal instanceof AbortSignal, `${operation} receives the exact identity signal`);
    assert.equal(request.signal.aborted, false, `${operation} starts before any cancellation`);
  };
  return {
    requests, adapterCalls,
    releaseInitialList() { assert.ok(releaseList, 'initial list request exists'); releaseList(); },
    service: Object.freeze({
      loadSubmissions(request) { bind('loadSubmissions', request); return real.loadSubmissions(request); },
      loadSubmission(request) { bind('loadSubmission', request); return real.loadSubmission(request); },
      downloadDocument(request) { bind('downloadDocument', request); return real.downloadDocument(request); },
      reviewDocument(request) { bind('reviewDocument', request); return real.reviewDocument(request); },
    }),
  };
}

async function mountContent(view, service) {
  await act(async () => {
    view.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/kyc-approval'] }, React.createElement(page.KYCApprovalContent, { user: admin, isAuthenticated: true, service })));
    await settle();
  });
}

test('UI6 KYC route executes guest, forbidden, permitted, back-forward and refresh-remount bounds in JSDOM', { concurrency: false }, async () => {
  async function render(entries, index, state) {
    const view = installDom();
    auth.__setAuth({ user: null, isAuthenticated: false, isLoading: false, init() {}, ...state });
    globalThis.__ui6KycEntries = entries;
    globalThis.__ui6KycIndex = index;
    await act(async () => { view.root.render(React.createElement(app.default)); await settle(); });
    return view;
  }
  let view = await render(['/admin/kyc-approval'], 0, {});
  try {
    await waitFor(() => view.host.querySelector('[data-ui6-location]')?.textContent === '/login?redirect=%2Fadmin%2Fkyc-approval', 'guest redirect');
    assert.equal(view.host.querySelector('[data-ui6-route=KYCApproval]'), null, 'guest cannot reach KYC content');
  } finally { await view.close(); }
  view = await render(['/admin/kyc-approval'], 0, { isAuthenticated: true, user: { id: 8, tenant_id: 10, role: 'trader' } });
  try {
    await waitFor(() => /Access Denied/.test(view.host.textContent), 'forbidden role view');
    assert.equal(view.host.querySelector('[data-ui6-route=KYCApproval]'), null, 'forbidden role cannot reach KYC content');
  } finally { await view.close(); }
  view = await render(['/admin/dashboard', '/admin/kyc-approval'], 1, { isAuthenticated: true, user: admin });
  try {
    await waitFor(() => view.host.querySelector('[data-ui6-route=KYCApproval]'), 'permitted KYC route');
    assert.ok(view.host.querySelector('[data-ui6-admin-layout]'), 'permitted route retains one admin layout');
    await click(view.host.querySelector('[data-ui6-back]'));
    await waitFor(() => view.host.querySelector('[data-ui6-route=AdminDashboard]'), 'Router back');
    await click(view.host.querySelector('[data-ui6-forward]'));
    await waitFor(() => view.host.querySelector('[data-ui6-route=KYCApproval]'), 'Router forward');
  } finally { await view.close(); }
  view = await render(['/admin/kyc-approval'], 0, { isAuthenticated: true, user: admin });
  try {
    await waitFor(() => view.host.querySelector('[data-ui6-route=KYCApproval]'), 'permitted refresh remount');
  } finally {
    await view.close();
    delete globalThis.__ui6KycEntries;
    delete globalThis.__ui6KycIndex;
  }
});

test('UI6 KYC management DOM binds selection, private download, refresh states, acknowledgement, owner response and both dialog closes', { concurrency: false }, async () => {
  const view = installDom();
  const synthetic = syntheticBoundService(view.domHooks);
  toasts.__reset();
  try {
    await mountContent(view, synthetic.service);
    await waitFor(() => view.host.querySelector('[aria-busy=true]'), 'initial DOM loading');
    synthetic.releaseInitialList();
    await waitFor(() => button(view.host, 'Review documents'), 'populated list');
    assert.ok(view.host.querySelector('.overflow-x-auto'), 'table has the source responsive overflow wrapper');
    assert.ok([...view.host.querySelectorAll('[class]')].some(node => String(node.className).includes('sm:flex-row')), 'source DOM exposes shared responsive breakpoint classes');

    await click(button(view.host, 'Refresh records'));
    await waitFor(() => view.host.querySelector('[role=alert]')?.textContent.includes('Synthetic pending-list failure'), 'failure after refresh');
    await click(button(view.host, 'Refresh records'));
    await waitFor(() => /No pending KYC submissions/.test(view.host.textContent), 'empty after refresh');
    await click(button(view.host, 'Refresh records'));
    await waitFor(() => button(view.host, 'Review documents'), 'recovered list after refresh');

    await click(button(view.host, 'Review documents'));
    await waitFor(() => /Selected recorded submission/.test(view.host.textContent), 'selected detail');
    assert.ok(synthetic.requests.some(({ operation, request }) => operation === 'loadSubmission' && request.userId === 3), 'selection calls owner-bound detail service');

    await click(button(view.host, 'Download privately'));
    await waitFor(() => synthetic.requests.some(({ operation }) => operation === 'downloadDocument'), 'private download request');
    await waitFor(() => view.privateClicks === 1, 'private download DOM click');
    assert.equal(view.privateClicks, 1, 'one temporary private-download anchor is clicked');
    assert.deepEqual(view.urlEvents, ['create:30', 'revoke:blob:ui6-kyc'], 'the private blob URL is revoked');
    assert.equal(synthetic.adapterCalls.find(call => call.endpoint === '/api/v1/kyc/documents/3/id_proof/download').config.responseType, 'blob', 'download uses the canonical blob route');

    await click(button(view.host, 'Record approval'));
    await waitFor(() => view.host.querySelector('[role=dialog]'), 'approval dialog');
    await click(view.host.querySelector(`[aria-label='Close recorded document review dialog']`));
    await waitFor(() => !view.host.querySelector('[role=dialog]'), 'header dialog close');

    await click(button(view.host, 'Record approval'));
    await waitFor(() => view.host.querySelector('[role=dialog]'), 'reopened approval dialog');
    const acknowledgement = view.host.querySelector('#kyc-review-acknowledgement');
    const saveApproval = button(view.host, 'Save recorded approval');
    await setValue(acknowledgement, 'REVIEW 9 id_proof');
    assert.equal(saveApproval.disabled, true, 'bad acknowledgement never enables a write');
    assert.equal(synthetic.adapterCalls.filter(call => call.method === 'put').length, 0, 'bad acknowledgement made no synthetic mutation');
    await setValue(acknowledgement, 'REVIEW 3 id_proof');
    assert.equal(saveApproval.disabled, false, 'canonical acknowledgement enables the review action');
    await click(saveApproval);
    await waitFor(() => toasts.__all().some(([kind]) => kind === 'error'), 'owner-mismatch failure toast');
    assert.ok(view.host.querySelector('[role=dialog]'), 'owner mismatch does not close the dialog');
    assert.equal(view.host.textContent.includes('Confirmed saved response'), false, 'owner mismatch has no displayed outcome');

    await click(button(view.host, 'Save recorded approval'));
    await waitFor(() => !view.host.querySelector('[role=dialog]') && /Confirmed saved response: User #3, ID proof, recorded as approved\./.test(view.host.textContent), 'acknowledged owner-matching response');
    const writes = synthetic.adapterCalls.filter(call => call.method === 'put');
    assert.equal(writes.length, 2, 'first owner mismatch was rejected and second response acknowledged');
    assert.deepEqual(writes[1].data, { status: 'approved', notes: null, acknowledgement: 'REVIEW 3 id_proof', expected_uploaded_at: stamp }, 'UI state becomes the canonical review payload');

    await waitFor(() => button(view.host, 'Review documents'), 'post-acknowledgement refresh');
    await click(button(view.host, 'Review documents'));
    await waitFor(() => button(view.host, 'Record rejection'), 'detail after refresh');
    await click(button(view.host, 'Record rejection'));
    await waitFor(() => view.host.querySelector('[role=dialog]'), 'rejection dialog');
    const saveRejection = button(view.host, 'Save recorded rejection');
    await setValue(view.host.querySelector('#kyc-review-acknowledgement'), 'REVIEW 3 id_proof');
    assert.equal(saveRejection.disabled, true, 'rejection needs a recorded reason');
    await setValue(view.host.querySelector('#kyc-review-note'), 'Synthetic recorded reason');
    assert.equal(saveRejection.disabled, false, 'reason plus exact acknowledgement enable rejection');
    await click(button(view.host, 'Cancel'));
    await waitFor(() => !view.host.querySelector('[role=dialog]'), 'cancel dialog close');
    assert.equal(synthetic.adapterCalls.filter(call => call.method === 'put').length, 2, 'cancelled rejection performs no mutation');
    assert.ok(synthetic.requests.every(({ request }) => request.expectedOwner.user_id === 2 && request.expectedOwner.tenant_id === 10), 'each source action remains owner-bound');
  } finally {
    await view.close();
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
