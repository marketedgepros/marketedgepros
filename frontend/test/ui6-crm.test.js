import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';
import {
  AdminClosureCrmContractError,
  createAdminClosureCrmService,
} from '../src/services/adminClosureCrmService.js';

const bootstrapDom = new JSDOM('<!doctype html><html><body></body></html>');
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrapDom.window, document: bootstrapDom.window.document, navigator: bootstrapDom.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
}
const { createRoot } = await import('react-dom/client');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrapDom.window.close();

const repoFrontend = fileURLToPath(new URL('..', import.meta.url));
const scratchRoot = os.tmpdir();
const tempDir = fs.mkdtempSync(path.join(scratchRoot, 'ui6-crm-dom-'));
const localRequire = createRequire(import.meta.url);
const externalImports = new Map([
  ['react', pathToFileURL(localRequire.resolve('react')).href],
  ['react/jsx-runtime', pathToFileURL(localRequire.resolve('react/jsx-runtime')).href],
  ['react-router-dom', pathToFileURL(localRequire.resolve('react-router-dom')).href],
  ['lucide-react', pathToFileURL(localRequire.resolve('lucide-react')).href],
]);
const absolutizeExternalImports = (source) => [...externalImports].reduce(
  (result, [specifier, absoluteUrl]) => result
    .replaceAll(`from '${specifier}'`, `from ${JSON.stringify(absoluteUrl)}`)
    .replaceAll(`from \"${specifier}\"`, `from ${JSON.stringify(absoluteUrl)}`),
  source,
);
const tempUrl = (name) => pathToFileURL(path.join(tempDir, name)).href;
const writeModule = (name, source) => {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
};

const authStub = writeModule('auth.mjs', `
  let state = { user: null, isAuthenticated: false, isLoading: false, init: () => {} };
  export const __setAuth = (next) => { state = { ...state, ...next }; };
  export default function useAuthStore(selector) { return selector ? selector(state) : state; }
  useAuthStore.subscribe = () => () => {};
`);
const toastStub = writeModule('toast.mjs', `
  const log = [];
  export const __resetToasts = () => { log.length = 0; };
  export const __toasts = () => [...log];
  export const useToast = () => ({
    success: (message) => log.push(['success', message]),
    error: (message) => log.push(['error', message]),
    warning: (message) => log.push(['warning', message]),
  });
`);
const identityStub = writeModule('identity.mjs', `
  export default function useAdminClosureCrmIdentityGuard(principal) {
    return {
      start() {
        const controller = new AbortController();
        return { principal, signal: controller.signal, isCurrent: () => true, finish() {}, cancel() { controller.abort(); } };
      },
    };
  }
`);
const layoutStub = writeModule('layout.mjs', `
  import React from ${JSON.stringify(externalImports.get('react'))};
  export default function AdminLayout({ children }) { return React.createElement('main', { 'data-admin-layout': 'crm-local' }, children); }
`);
const crmStub = writeModule('crm-service.mjs', `
  export const ADMIN_CLOSURE_CRM_STATUSES = ['new', 'contacted', 'qualified', 'proposal', 'negotiation', 'converted', 'lost'];
  export const ADMIN_CLOSURE_CRM_SOURCES = ['website', 'referral', 'affiliate', 'social_media'];
  let service = {};
  export const __setService = (next) => { service = next; };
  export const createAdminClosureCrmService = () => new Proxy({}, { get: (_target, key) => (...args) => service[key](...args) });
  export const adminClosureCrmError = () => 'CRM data could not be loaded or its response could not be verified. No empty result or saved change has been assumed.';
  export const isAdminClosureCrmRequestCanceled = (error) => error?.name === 'AbortError' || error?.code === 'ERR_CANCELED';
  export const formatAdminClosureCrmBudget = (value) => value === null ? 'Not specified' : value + ' (currency unavailable)';
  export const parseAdminClosureCrmRouteLeadId = (value) => typeof value === 'string' && /^[1-9][0-9]{0,9}$/.test(value) && Number(value) <= 2147483647 ? Number(value) : null;
  export const adminClosureCrmPrincipalFromAuth = (user, isAuthenticated) => (
    isAuthenticated === true && ['master', 'supermaster'].includes(user?.role) && Number.isInteger(user?.id) && user.id > 0 && Number.isInteger(user?.tenant_id) && user.tenant_id > 0
      ? { owner: { user_id: user.id, tenant_id: user.tenant_id }, role: user.role, key: JSON.stringify([true, user.id, user.tenant_id, user.role]) }
      : null
  );
`);

async function compilePage(relativeSource, outputName, replacements) {
  let source = fs.readFileSync(path.join(repoFrontend, relativeSource), 'utf8');
  for (const [from, to] of replacements) source = source.replaceAll(from, to);
  source = absolutizeExternalImports(source);
  const transformed = await transformWithEsbuild(source, path.join(repoFrontend, relativeSource), { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  const output = path.join(tempDir, outputName);
  fs.writeFileSync(output, absolutizeExternalImports(transformed.code));
  return import(`${pathToFileURL(output).href}?ui6=${process.pid}`);
}

const crmPage = await compilePage('src/pages/admin/CRM.jsx', 'CRM.mjs', [
  ['../../components/admin/AdminLayout', layoutStub],
  ['../../contexts/ToastContext', toastStub],
  ['../../hooks/useAdminClosureCrmIdentityGuard', identityStub],
  ['../../hooks/useDialogFocus', pathToFileURL(path.join(repoFrontend, 'src/hooks/useDialogFocus.js')).href],
  ['../../store/authStore', authStub],
  ['../../services/adminClosureCrmService', crmStub],
]);
const detailsPage = await compilePage('src/pages/admin/LeadDetails.jsx', 'LeadDetails.mjs', [
  ['../../contexts/ToastContext', toastStub],
  ['../../hooks/useAdminClosureCrmIdentityGuard', identityStub],
  ['../../hooks/useDialogFocus', pathToFileURL(path.join(repoFrontend, 'src/hooks/useDialogFocus.js')).href],
  ['../../store/authStore', authStub],
  ['../../services/adminClosureCrmService', crmStub],
]);
const auth = await import(authStub);
const toasts = await import(toastStub);
const crmModule = await import(crmStub);

const roleGuardSource = fs.readFileSync(path.join(repoFrontend, 'src/components/guards/RoleGuard.jsx'), 'utf8')
  .replaceAll('../../store/authStore', authStub);
const roleGuardCompiled = await transformWithEsbuild(absolutizeExternalImports(roleGuardSource), 'RoleGuard.jsx', { loader: 'jsx', jsx: 'automatic', format: 'esm' });
const roleGuardFile = path.join(tempDir, 'RoleGuard.mjs');
fs.writeFileSync(roleGuardFile, absolutizeExternalImports(roleGuardCompiled.code));
const roleGuardUrl = pathToFileURL(roleGuardFile).href;
const routeLayoutStub = writeModule('route-layout.mjs', `import React from ${JSON.stringify(externalImports.get('react'))}; export default function RouteLayout({ children }) { return React.createElement('main', { 'data-route-layout': 'true' }, children); }`);
const routeCrmStub = writeModule('route-crm.mjs', `import React from ${JSON.stringify(externalImports.get('react'))}; export default function RouteCrm() { return React.createElement('p', { 'data-route-page': 'crm' }, 'CRM route reached'); }`);
const routeDetailsStub = writeModule('route-details.mjs', `import React from ${JSON.stringify(externalImports.get('react'))}; export default function RouteDetails() { return React.createElement('p', { 'data-route-page': 'lead-details' }, 'Lead details route reached'); }`);
const routeGenericStub = writeModule('route-generic.mjs', `import React from ${JSON.stringify(externalImports.get('react'))}; export default function RouteGeneric({ children }) { return React.createElement('div', { 'data-route-page': 'generic' }, children); }`);
const notificationStub = writeModule('notification.mjs', `import React from ${JSON.stringify(externalImports.get('react'))}; export default function Notification() { return null; }`);
const chatStub = writeModule('chat.mjs', `import React from ${JSON.stringify(externalImports.get('react'))}; export default function ChatWidget() { return null; }`);
const rolesStub = writeModule('roles.mjs', `export const ADMIN_ROLES = ['master', 'supermaster'];`);
const navigationStub = writeModule('navigation.mjs', `export const postLoginDestination = () => '/dashboard';`);
const toastProviderStub = writeModule('toast-provider.mjs', `import React from ${JSON.stringify(externalImports.get('react'))}; export const ToastProvider = ({ children }) => React.createElement(React.Fragment, null, children);`);
const notificationsStoreStub = writeModule('notifications-store.mjs', `export default { getState: () => ({ reset() {} }) };`);

let appSource = fs.readFileSync(path.join(repoFrontend, 'src/App.jsx'), 'utf8');
appSource = appSource.replace(/lazy\(\(\) => import\((['"])([^'"]+)\1\)\)/g, (_full, _quote, specifier) => {
  const target = specifier.endsWith('/components/admin/AdminLayout') ? routeLayoutStub
    : specifier.endsWith('/pages/admin/CRM') ? routeCrmStub
      : specifier.endsWith('/pages/admin/LeadDetails') ? routeDetailsStub
        : routeGenericStub;
  return `lazy(() => import(${JSON.stringify(target)}))`;
});
for (const [from, to] of [
  ['./store/authStore', authStub],
  ['./components/Notification', notificationStub],
  ['./components/RouteScrollManager.js', new URL('../src/components/RouteScrollManager.js', import.meta.url).href],
  ['./components/ChatWidget', chatStub],
  ['./constants/roles', rolesStub],
  ['./services/navigationService.js', navigationStub],
  ['./contexts/ToastContext', toastProviderStub],
  ['./stores/notificationStore.js', notificationsStoreStub],
  ['./components/guards/RoleGuard', roleGuardUrl],
]) appSource = appSource.replaceAll(from, to);
const appCompiled = await transformWithEsbuild(absolutizeExternalImports(appSource), 'App.jsx', { loader: 'jsx', jsx: 'automatic', format: 'esm' });
const appFile = path.join(tempDir, 'App.mjs');
fs.writeFileSync(appFile, absolutizeExternalImports(appCompiled.code));
const appModule = await import(`${pathToFileURL(appFile).href}?ui6=${process.pid}`);

const owner = { user_id: 9, tenant_id: 4 };
const lead = (patch = {}) => ({
  id: 22,
  first_name: 'Ada',
  last_name: 'Lead',
  email: 'ada@example.invalid',
  phone: '+100000000',
  country_code: 'US',
  status: 'new',
  source: 'website',
  score: 50,
  assigned_to: 9,
  assigned_user: { id: 9, name: 'Admin Owner' },
  interested_program_id: null,
  budget: '10.50',
  company: 'Synthetic Co',
  job_title: null,
  notes: null,
  tags: [],
  next_follow_up: null,
  converted_at: null,
  lost_reason: null,
  lost_at: null,
  created_at: '2026-10-12T10:00:00',
  updated_at: '2026-10-12T10:00:00',
  ...patch,
});
const note = (patch = {}) => ({ id: 31, lead_id: 22, content: 'Persisted note', created_at: '2026-10-12T10:00:00', created_by: { name: 'Admin Owner' }, ...patch });
const activity = (patch = {}) => ({ id: 41, lead_id: 22, activity_type: 'follow_up', subject: null, description: 'Persisted activity', outcome: null, scheduled_at: '2026-10-12T11:00:00', completed: false, completed_at: null, created_at: '2026-10-12T10:00:00', created_by: { id: 9, name: 'Admin Owner' }, ...patch });

function syntheticService(log) {
  const bind = (operation, request) => {
    log.push({ operation, request });
    assert.deepEqual(request.expectedOwner, owner, `${operation} must receive the active owner`);
    assert.equal(request.role, 'supermaster', `${operation} must receive the permitted role`);
    assert.ok(request.signal instanceof AbortSignal, `${operation} must carry an identity-bound signal`);
  };
  return {
    async loadLeads(request) {
      bind('loadLeads', request);
      const empty = request.search === 'no result';
      return { leads: empty ? [] : [lead()], pagination: empty ? { page: 1, per_page: 20, total: 0, pages: 0 } : { page: request.page, per_page: 20, total: 21, pages: 2 } };
    },
    async loadStats(request) { bind('loadStats', request); return { stats: { total: 21, new: 1, contacted: 0, qualified: 0, converted: 0 } }; },
    async createLead(request) {
      bind('createLead', request);
      return { lead: lead({ id: 33, first_name: 'Grace', last_name: 'Hopper' }) };
    },
    async loadLead(request) { bind('loadLead', request); assert.equal(request.leadId, 22); return { lead: lead() }; },
    async loadNotes(request) { bind('loadNotes', request); assert.equal(request.leadId, 22); return { notes: [note()] }; },
    async loadActivities(request) { bind('loadActivities', request); assert.equal(request.leadId, 22); return { activities: [activity()] }; },
    async updateLead(request) {
      bind('updateLead', request);
      assert.equal(request.leadId, 22);
      assert.equal(request.payload.expected_updated_at, '2026-10-12T10:00:00');
      return { lead: lead({ status: request.payload.status ?? 'contacted', score: request.payload.score ?? 50, notes: request.payload.notes ?? null }) };
    },
    async addNote(request) { bind('addNote', request); assert.equal(request.leadId, 22); return { note: note({ id: 32, content: request.content }) }; },
    async addActivity(request) { bind('addActivity', request); assert.equal(request.leadId, 22); return { activity: activity({ id: 42, description: request.payload.description, scheduled_at: request.payload.scheduled_at }) }; },
    async markConverted(request) { bind('markConverted', request); assert.equal(request.leadId, 22); return { lead: lead({ status: 'converted' }) }; },
    async deleteLead(request) { bind('deleteLead', request); assert.equal(request.leadId, 22); return { ownerContext: owner, leadId: 22 }; },
  };
}

function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { 'data-location': 'true' }, `${location.pathname}${location.search}`);
}

function installDom(url = 'http://crm.test/admin/crm') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url });
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'Event', 'MouseEvent', 'KeyboardEvent', 'getComputedStyle', 'IS_REACT_ACT_ENVIRONMENT'];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    getComputedStyle: dom.window.getComputedStyle,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(bindings)) {
    Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
  }
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
  await Promise.resolve();
}
async function waitFor(predicate, label) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (predicate()) return;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); await settle(); });
  }
  assert.fail(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected an interactive element');
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    await settle();
  });
}
async function setControlValue(element, value, event = 'input') {
  const previous = element.value;
  element.value = value;
  element._valueTracker?.setValue(previous);
  const reactPropsKey = Object.keys(element).find((key) => key.startsWith('__reactProps$'));
  const reactProps = reactPropsKey ? element[reactPropsKey] : null;
  await act(async () => {
    if (typeof reactProps?.onChange === 'function') reactProps.onChange({ target: element });
    else {
      element.dispatchEvent(new Event(event, { bubbles: true, cancelable: true }));
      if (event === 'input') element.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
    }
    await settle();
  });
}
function buttonByText(container, text) {
  return [...container.querySelectorAll('button')].find((button) => button.textContent.trim() === text || button.textContent.includes(text));
}
function nestedControl(container, labelText, selector = 'input') {
  const label = [...container.querySelectorAll('label')].find((candidate) => candidate.textContent.includes(labelText));
  assert.ok(label, `label ${labelText} is rendered`);
  const control = label.querySelector(selector);
  assert.ok(control, `${labelText} contains ${selector}`);
  return control;
}

function exactLeadForContract(patch = {}) { return lead(patch); }

test('UI6 CRM Router renders both CRM paths only for a permitted admin; guest redirects and a forbidden role is denied', async () => {
  const harness = installDom('http://crm.test/admin/crm');
  try {
    const renderAt = async (pathname, nextAuth) => {
      await act(async () => { harness.root.render(null); await settle(); });
      auth.__setAuth({ user: null, isAuthenticated: false, isLoading: false, ...nextAuth });
      harness.dom.window.history.replaceState({}, '', pathname);
      await act(async () => { harness.root.render(React.createElement(appModule.default)); await settle(); });
      await waitFor(() => harness.container.innerHTML.length > 0 || harness.dom.window.location.pathname === '/login', `route ${pathname}`);
    };

    await renderAt('/admin/crm', {});
    await waitFor(() => harness.dom.window.location.pathname === '/login', 'guest redirect');
    assert.equal(harness.dom.window.location.search, '?redirect=%2Fadmin%2Fcrm');

    await renderAt('/admin/crm', { isAuthenticated: true, user: { id: 7, tenant_id: 4, role: 'trader' } });
    await waitFor(() => /Access Denied/.test(harness.container.textContent), 'forbidden-role boundary');
    assert.equal(harness.container.querySelector('[data-route-page="crm"]'), null);

    await renderAt('/admin/crm', { isAuthenticated: true, user: { id: 9, tenant_id: 4, role: 'supermaster' } });
    await waitFor(() => harness.container.querySelector('[data-route-page="crm"]'), 'permitted list route');
    assert.ok(harness.container.querySelector('[data-route-page="crm"]'));

    await renderAt('/admin/crm/22', { isAuthenticated: true, user: { id: 9, tenant_id: 4, role: 'supermaster' } });
    await waitFor(() => harness.container.querySelector('[data-route-page="lead-details"]'), 'permitted detail route');
    assert.ok(harness.container.querySelector('[data-route-layout="true"]'), 'detail path retains the application AdminLayout');
  } finally {
    await harness.close();
  }
});

test('UI6 CRM list DOM interactions keep the active owner bound and show only acknowledged synthetic results', async () => {
  const harness = installDom();
  const calls = [];
  auth.__setAuth({ user: { id: 9, tenant_id: 4, role: 'supermaster' }, isAuthenticated: true, isLoading: false });
  toasts.__resetToasts();
  crmModule.__setService(syntheticService(calls));
  try {
    await act(async () => {
      harness.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/crm'] }, React.createElement(React.Fragment, null, React.createElement(crmPage.default), React.createElement(LocationProbe))));
      await settle();
    });
    await waitFor(() => harness.container.textContent.includes('Ada Lead'), 'initial scoped list');
    assert.match(harness.container.querySelector('[data-admin-layout="crm-local"]').textContent, /CRM leads/);

    await click(buttonByText(harness.container, 'Add lead'));
    await waitFor(() => harness.container.querySelector('[role="dialog"]'), 'add modal');
    await click(buttonByText(harness.container, 'Cancel'));
    assert.equal(harness.container.querySelector('[role="dialog"]'), null, 'Cancel closes a non-saving add dialog');

    await click(buttonByText(harness.container, 'Add lead'));
    await click(harness.container.querySelector('[aria-label="Close add lead dialog"]'));
    assert.equal(harness.container.querySelector('[role="dialog"]'), null, 'close icon closes a non-saving add dialog');

    await click(buttonByText(harness.container, 'Add lead'));
    await setControlValue(nestedControl(harness.container, 'First name'), 'Grace');
    await setControlValue(nestedControl(harness.container, 'Last name'), 'Hopper');
    await setControlValue(nestedControl(harness.container, 'Email'), 'grace@example.invalid');
    const addForm = harness.container.querySelector('[role="dialog"] form');
    await act(async () => { addForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await settle(); });
    await waitFor(() => harness.container.querySelector('[role="dialog"]') === null, 'acknowledged add result');
    assert.ok(toasts.__toasts().some(([level, message]) => level === 'success' && /Grace Hopper/.test(message)), 'success is shown only after the synthetic acknowledged lead');

    await click(buttonByText(harness.container, 'Pipeline'));
    assert.equal(buttonByText(harness.container, 'Pipeline').getAttribute('aria-pressed'), 'true');
    await click(buttonByText(harness.container, 'Ada Lead'));
    await waitFor(() => harness.container.querySelector('[data-location]').textContent === '/admin/crm/22', 'pipeline navigation');

    await click(buttonByText(harness.container, 'Table'));
    const row = harness.container.querySelector('tbody tr');
    await click(row);
    await waitFor(() => harness.container.querySelector('[data-location]').textContent === '/admin/crm/22', 'table row navigation');

    await click(buttonByText(harness.container, 'Next'));
    await waitFor(() => calls.filter(({ operation, request }) => operation === 'loadLeads' && request.page === 2).length > 0, 'next-page request');
    await click(buttonByText(harness.container, 'Previous'));
    await waitFor(() => calls.filter(({ operation, request }) => operation === 'loadLeads' && request.page === 1).length >= 2, 'previous-page request');

    await setControlValue(harness.container.querySelector('input[placeholder="Search name, email, phone"]'), 'no result');
    assert.doesNotMatch(harness.container.textContent, /No matching leads/, 'typing changes only the explicit-search draft');
    await click(buttonByText(harness.container, 'Apply search'));
    await waitFor(() => /No matching leads/.test(harness.container.textContent), 'verified empty list state');
    await click(buttonByText(harness.container, 'Clear filters'));
    await waitFor(() => harness.container.textContent.includes('Ada Lead'), 'cleared filter result');

    const mutations = calls.filter(({ operation }) => operation === 'createLead');
    assert.equal(mutations.length, 1);
    assert.deepEqual(mutations[0].request.payload, {
      first_name: 'Grace', last_name: 'Hopper', email: 'grace@example.invalid', phone: '', company: '', source: 'website', status: 'new', budget: '',
    });
    assert.ok(calls.every(({ request }) => request.expectedOwner.user_id === 9 && request.expectedOwner.tenant_id === 4), 'each list action keeps its owner binding');
  } finally {
    await harness.close();
  }
});

test('UI6 CRM lead details DOM actions use bound acknowledged mutations; mailto remains only an external-client boundary', async () => {
  const harness = installDom('http://crm.test/admin/crm/22');
  const calls = [];
  auth.__setAuth({ user: { id: 9, tenant_id: 4, role: 'supermaster' }, isAuthenticated: true, isLoading: false });
  toasts.__resetToasts();
  crmModule.__setService(syntheticService(calls));
  try {
    await act(async () => {
      harness.root.render(React.createElement(MemoryRouter, { initialEntries: ['/admin/crm/22'] }, React.createElement(Routes, null,
        React.createElement(Route, { path: '/admin/crm/:id', element: React.createElement(React.Fragment, null, React.createElement(detailsPage.default), React.createElement(LocationProbe)) }),
        React.createElement(Route, { path: '*', element: React.createElement(LocationProbe) }),
      )));
      await settle();
    });
    await waitFor(() => harness.container.textContent.includes('Ada Lead'), 'lead detail response');

    const originalWindow = globalThis.window;
    const outboundWindow = { location: { href: '' } };
    const emailButton = buttonByText(harness.container, 'Open email client');
    await act(async () => {
      globalThis.window = outboundWindow;
      emailButton.dispatchEvent(new harness.dom.window.MouseEvent('click', { bubbles: true, cancelable: true }));
      await settle();
      globalThis.window = originalWindow;
    });
    assert.equal(outboundWindow.location.href, 'mailto:ada@example.invalid');
    assert.equal(calls.filter(({ operation }) => !operation.startsWith('load')).length, 0, 'opening a local mail client is not a CRM write or provider send');

    await click(buttonByText(harness.container, 'Notes (1)'));
    await setControlValue(harness.container.querySelector('#lead-note'), 'A scoped internal note');
    await click(buttonByText(harness.container, 'Save note'));
    await waitFor(() => harness.container.textContent.includes('A scoped internal note'), 'acknowledged note');

    await click(buttonByText(harness.container, 'Activity (1)'));
    await click(buttonByText(harness.container, 'Overview'));
    await click(buttonByText(harness.container, 'Add follow-up activity'));
    await waitFor(() => harness.container.querySelector('[role="dialog"]'), 'activity dialog');
    await click(buttonByText(harness.container, 'Cancel'));
    assert.equal(harness.container.querySelector('[role="dialog"]'), null, 'activity cancel closes dialog');
    await click(buttonByText(harness.container, 'Add follow-up activity'));
    await click(harness.container.querySelector('[aria-label="Close add activity dialog"]'));
    assert.equal(harness.container.querySelector('[role="dialog"]'), null, 'activity close icon closes dialog');
    await click(buttonByText(harness.container, 'Add follow-up activity'));
    await setControlValue(nestedControl(harness.container, 'Activity date and time'), '2026-10-13T10:30');
    await setControlValue(nestedControl(harness.container, 'Description', 'textarea'), 'Follow up internally');
    await click(buttonByText(harness.container, 'Save activity'));
    await waitFor(() => harness.container.querySelector('[role="dialog"]') === null, 'acknowledged activity');

    await click(buttonByText(harness.container, 'Edit supported fields'));
    await waitFor(() => harness.container.querySelector('[role="dialog"]'), 'edit dialog');
    await click(buttonByText(harness.container, 'Cancel'));
    assert.equal(harness.container.querySelector('[role="dialog"]'), null, 'edit cancel closes dialog');
    await click(buttonByText(harness.container, 'Edit supported fields'));
    await click(harness.container.querySelector('[aria-label="Close edit lead dialog"]'));
    assert.equal(harness.container.querySelector('[role="dialog"]'), null, 'edit close icon closes dialog');
    await click(buttonByText(harness.container, 'Edit supported fields'));
    await setControlValue(nestedControl(harness.container, 'Score (0–100)'), '55');
    await click(buttonByText(harness.container, 'Save changes'));
    await waitFor(() => harness.container.querySelector('[role="dialog"]') === null, 'acknowledged edit');

    await click(buttonByText(harness.container, 'contacted'));
    await waitFor(() => toasts.__toasts().some(([, message]) => /Status saved as contacted/.test(message)), 'acknowledged status');
    await click(buttonByText(harness.container, 'Mark converted'));
    await waitFor(() => toasts.__toasts().some(([, message]) => /set to converted/.test(message)), 'acknowledged conversion');

    harness.dom.window.confirm = () => true;
    await click(buttonByText(harness.container, 'Delete'));
    await waitFor(() => harness.container.querySelector('[data-location]').textContent === '/admin/crm', 'acknowledged delete navigation');

    await act(async () => {
      harness.root.render(React.createElement(MemoryRouter, { key: 'reload-valid-detail', initialEntries: ['/admin/crm/22'] }, React.createElement(Routes, null,
        React.createElement(Route, { path: '/admin/crm/:id', element: React.createElement(React.Fragment, null, React.createElement(detailsPage.default), React.createElement(LocationProbe)) }),
        React.createElement(Route, { path: '*', element: React.createElement(LocationProbe) }),
      )));
      await settle();
    });
    await waitFor(() => harness.container.textContent.includes('Ada Lead'), 'reloaded valid detail for Back');
    await click(buttonByText(harness.container, 'Back to CRM'));
    await waitFor(() => harness.container.querySelector('[data-location]').textContent === '/admin/crm', 'valid-detail Back navigation');

    await act(async () => {
      harness.root.render(React.createElement(MemoryRouter, { key: 'invalid-detail', initialEntries: ['/admin/crm/not-a-number'] }, React.createElement(Routes, null,
        React.createElement(Route, { path: '/admin/crm/:id', element: React.createElement(React.Fragment, null, React.createElement(detailsPage.default), React.createElement(LocationProbe)) }),
        React.createElement(Route, { path: '*', element: React.createElement(LocationProbe) }),
      )));
      await settle();
    });
    await waitFor(() => /Lead details are unavailable/.test(harness.container.textContent), 'invalid route safe failure');
    await click(buttonByText(harness.container, 'Back to CRM'));
    await waitFor(() => harness.container.querySelector('[data-location]').textContent === '/admin/crm', 'invalid-detail Back navigation');

    const operations = calls.map(({ operation }) => operation);
    for (const required of ['loadLead', 'loadNotes', 'loadActivities', 'addNote', 'addActivity', 'updateLead', 'markConverted', 'deleteLead']) assert.ok(operations.includes(required), required);
    assert.equal(calls.find(({ operation }) => operation === 'addNote').request.content, 'A scoped internal note');
    assert.equal(calls.find(({ operation }) => operation === 'addActivity').request.payload.scheduled_at, '2026-10-13T10:30:00');
    assert.ok(calls.filter(({ operation }) => ['addNote', 'addActivity', 'updateLead', 'markConverted', 'deleteLead'].includes(operation)).every(({ request }) => request.expectedOwner.user_id === 9 && request.expectedOwner.tenant_id === 4), 'every detail mutation carried the owner context');
  } finally {
    await harness.close();
  }
});

test('UI6 CRM real mutation contracts reject owner or acknowledgement mismatches instead of accepting mocked writes', async () => {
  const expectedOwner = { user_id: 9, tenant_id: 4 };
  const badOwner = { user_id: 10, tenant_id: 4 };
  const controller = new AbortController();
  const service = createAdminClosureCrmService({
    post: async (endpoint) => {
      if (endpoint.endsWith('/notes')) return { data: { owner_context: expectedOwner, note: note({ lead_id: 23 }) } };
      if (endpoint.endsWith('/activities')) return { data: { owner_context: expectedOwner, activity: activity({ lead_id: 23 }) } };
      return { data: { owner_context: badOwner, lead: exactLeadForContract() } };
    },
    patch: async () => ({ data: { owner_context: expectedOwner, lead: exactLeadForContract({ id: 23 }) } }),
    delete: async () => ({ data: { owner_context: expectedOwner, lead_id: 23 } }),
  });
  const base = { expectedOwner, role: 'supermaster', leadId: 22, signal: controller.signal };
  await assert.rejects(
    service.createLead({ expectedOwner, role: 'supermaster', signal: controller.signal, payload: { first_name: 'Ada', last_name: 'Lead', email: 'ada@example.invalid' } }),
    AdminClosureCrmContractError,
  );
  await assert.rejects(
    service.updateLead({ ...base, payload: { status: 'contacted', expected_updated_at: '2026-10-12T10:00:00' } }),
    AdminClosureCrmContractError,
  );
  await assert.rejects(service.addNote({ ...base, content: 'Bound note' }), AdminClosureCrmContractError);
  await assert.rejects(service.addActivity({ ...base, payload: { activity_type: 'follow_up', description: 'Bound activity', scheduled_at: '2026-10-12T11:00:00' } }), AdminClosureCrmContractError);
  await assert.rejects(service.markConverted(base), AdminClosureCrmContractError);
  await assert.rejects(service.deleteLead(base), AdminClosureCrmContractError);
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
