import { compilePaymentHarness } from './paymentHarness.js';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test, { after } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { transformWithEsbuild } from 'vite';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const compiledTargets = new Set();
const source = (relative) => path.join(frontendDirectory, 'src', relative);
const sourceUrl = (relative) => pathToFileURL(source(relative)).href;
const policyOverride = {
  'services/programEvaluationPolicy.js': `export * from ${JSON.stringify(sourceUrl('services/programEvaluationPolicy.js'))};`,
};

after(() => {
  for (const target of compiledTargets) fs.rmSync(target, { force: true });
});

const jsdomPackage = fs.readdirSync(path.join(frontendDirectory, 'node_modules', '.pnpm'))
  .find((entry) => entry.startsWith('jsdom@'));
if (!jsdomPackage) throw new Error('jsdom 28.1.0 is required for UI6 account DOM evidence.');
const { JSDOM } = await import(pathToFileURL(path.join(
  frontendDirectory,
  'node_modules',
  '.pnpm',
  jsdomPackage,
  'node_modules',
  'jsdom',
  'lib',
  'api.js',
)).href);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://ui6.account.test/' });
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLAnchorElement: dom.window.HTMLAnchorElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  File: dom.window.File,
  FormData: dom.window.FormData,
  URL: dom.window.URL,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });

const { createRoot } = await import('react-dom/client');
const { MemoryRouter, Route, Routes, useLocation } = await import('react-router-dom');

async function compileJsx(name, relative, mutate) {
  const sourcePath = source(relative);
  // Keep generated ESM underneath frontend/node_modules: package resolution stays
  // identical to the app, while Git's working tree never receives test residue.
  const targetPath = path.join(frontendDirectory, 'node_modules', `.ui6-account-${name}-${process.pid}.mjs`);
  compiledTargets.add(targetPath);
  const original = fs.readFileSync(sourcePath, 'utf8');
  const transformed = await transformWithEsbuild(mutate(original), sourcePath, {
    loader: 'jsx',
    jsx: 'automatic',
  });
  fs.writeFileSync(targetPath, transformed.code);
  try {
    return await import(`${pathToFileURL(targetPath).href}?ui6-account=${process.pid}`);
  } finally {
    fs.rmSync(targetPath, { force: true });
    compiledTargets.delete(targetPath);
  }
}

async function compileJsxDependency(name, relative, mutate) {
  const sourcePath = source(relative);
  const targetPath = path.join(frontendDirectory, 'node_modules', `.ui6-account-${name}-${process.pid}.mjs`);
  compiledTargets.add(targetPath);
  const transformed = await transformWithEsbuild(mutate(fs.readFileSync(sourcePath, 'utf8')), sourcePath, {
    loader: 'jsx',
    jsx: 'automatic',
  });
  fs.writeFileSync(targetPath, transformed.code);
  return pathToFileURL(targetPath).href;
}

const accountAuthStub = `const useAuthStore = (selector) => {
  const state = globalThis.__ui6AccountStore;
  return typeof selector === 'function' ? selector(state) : state;
};
useAuthStore.subscribe = () => () => {};`;

// Modules capture these adapter objects during import. Tests only replace the
// synthetic handlers, so no component can ever receive a live API client.
globalThis.__ui6ProfileApi = {
  get: (...args) => globalThis.__ui6ProfileHandlers.get(...args),
  update: (...args) => globalThis.__ui6ProfileHandlers.update(...args),
  uploadAvatar: (...args) => globalThis.__ui6ProfileHandlers.uploadAvatar(...args),
  deleteAvatar: (...args) => globalThis.__ui6ProfileHandlers.deleteAvatar(...args),
  changePassword: (...args) => globalThis.__ui6ProfileHandlers.changePassword(...args),
};
globalThis.__ui6KycApi = {
  get: (...args) => globalThis.__ui6KycHandlers.get(...args),
  post: (...args) => globalThis.__ui6KycHandlers.post(...args),
};

const RoleDashboardModule = await compileJsx('role-dashboard', 'components/RoleBasedDashboard.jsx', (text) => text
  .replace("import useAuthStore from '../store/authStore';", accountAuthStub)
  .replace("import { accountHome } from '../services/navigationService.js';", `import { accountHome } from ${JSON.stringify(sourceUrl('services/navigationService.js'))};`));
const ProfileModule = await compileJsx('profile', 'pages/user/Profile.jsx', (text) => text
  .replace("import useAuthStore from '../../store/authStore';", accountAuthStub)
  .replace("import { profileAPI } from '../../services/api';", 'const profileAPI = globalThis.__ui6ProfileApi;')
  .replace("import useDialogFocus from '../../hooks/useDialogFocus';", `import useDialogFocus from ${JSON.stringify(sourceUrl('hooks/useDialogFocus.js'))};`)
  .replace("import useTabNavigation from '../../hooks/useTabNavigation';", `import useTabNavigation from ${JSON.stringify(sourceUrl('hooks/useTabNavigation.js'))};`)
  .replace("} from '../../services/profileViewService';", `} from ${JSON.stringify(sourceUrl('services/profileViewService.js'))};`));
const DocumentsModule = await compileJsx('documents', 'pages/user/Documents.jsx', (text) => text
  .replace("import api from '../../services/api';", 'const api = globalThis.__ui6KycApi;')
  .replace("import useAuthStore from '../../store/authStore';", accountAuthStub)
  .replace("} from '../../services/kycViewService';", `} from ${JSON.stringify(sourceUrl('services/kycViewService.js'))};`));
const AccountSetupGuideUrl = await compileJsxDependency('account-setup-guide', 'components/account/AccountSetupGuide.jsx', (text) => text
  .replace("'../../services/accountSetupViewService.js'", JSON.stringify(sourceUrl('services/accountSetupViewService.js'))));
const purchaseBuild = await compilePaymentHarness(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url), {
  prefix: 'ui6-account-payment',
  overrides: policyOverride,
});
const purchaseBuildUrl = purchaseBuild.targets.get(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url).pathname);
after(() => purchaseBuild.cleanup());
const UserDashboardModule = await compileJsx('user-dashboard', 'pages/user/UserDashboard.jsx', (text) => text
  .replace("import useAuthStore from '../../store/authStore';", accountAuthStub)
  .replace("import api, { profileAPI } from '../../services/api';", "const api = { get: () => Promise.reject(new Error('synthetic UI6 API only')) }; const profileAPI = { get: () => Promise.reject(new Error('synthetic UI6 API only')) };")
  .replace("import AccountSetupGuide from '../../components/account/AccountSetupGuide';", `import AccountSetupGuide from ${JSON.stringify(AccountSetupGuideUrl)};`)
  .replace("import ProgramPurchaseRecords from '../../components/payments/ProgramPurchaseRecords';", `import ProgramPurchaseRecords from ${JSON.stringify(purchaseBuildUrl)};`)
  .replace("import { createProfileApiTransport } from '../../services/profileViewService';", `import { createProfileApiTransport } from ${JSON.stringify(sourceUrl('services/profileViewService.js'))};`)
  .replace("import { createAccountSetupViewService } from '../../services/accountSetupViewService';", `import { createAccountSetupViewService } from ${JSON.stringify(sourceUrl('services/accountSetupViewService.js'))};`)
  .replace("} from '../../services/userDashboardViewService';", `} from ${JSON.stringify(sourceUrl('services/userDashboardViewService.js'))};`));
globalThis.__ui6AccountRoleDashboard = RoleDashboardModule.default;

const ProtectedModule = await compileJsx('protected-route', 'App.jsx', (text) => text
  .replace("const RoleBasedDashboard = lazy(() => import('./components/RoleBasedDashboard'));", 'const RoleBasedDashboard = globalThis.__ui6AccountRoleDashboard;')
  .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", "import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';")
  .replace("import { useState, useEffect, lazy, Suspense } from 'react';", "import { useState, useEffect } from 'react'; const lazy = () => ({ children }) => children || <output data-ui6-account-route={useLocation().pathname}>{useLocation().pathname}</output>; const Suspense = ({ children }) => children;")
  .replace("import useAuthStore from './store/authStore';", accountAuthStub)
  .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
  .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(sourceUrl('components/RouteScrollManager.js'))};`)
  .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
  .replace("import { ADMIN_ROLES } from './constants/roles';", `import { ADMIN_ROLES } from ${JSON.stringify(sourceUrl('constants/roles.js'))};`)
  .replace("import { postLoginDestination } from './services/navigationService.js';", "const postLoginDestination = () => '/user/dashboard';")
  .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
  .replace("import useNotificationStore from './stores/notificationStore.js';", "const useNotificationStore = { getState: () => ({ reset: () => {} }) };")
  .replace("import RoleGuard from './components/guards/RoleGuard';", 'const RoleGuard = ({ children }) => children;')
  .replace('<BrowserRouter>', "<MemoryRouter initialEntries={[globalThis.__ui6AccountEntry || '/']}>")
  .replace('</BrowserRouter>', '</MemoryRouter>')
  .concat('\nexport { ProtectedRoute };\n'));
const RoleGuardModule = await compileJsx('role-guard', 'components/guards/RoleGuard.jsx', (text) => text
  .replace("import useAuthStore from '../../store/authStore';", accountAuthStub));

const RoleBasedDashboard = RoleDashboardModule.default;
const Profile = ProfileModule.default;
const Documents = DocumentsModule.default;
const { DashboardOverview, DashboardReadState } = UserDashboardModule;
const { ProtectedRoute } = ProtectedModule;
const AccountApp = ProtectedModule.default;
const RoleGuard = RoleGuardModule.default;
const h = React.createElement;
const fragment = (...children) => h(React.Fragment, null, ...children);

function LocationProbe() {
  const location = useLocation();
  const value = `${location.pathname}${location.search}`;
  return h('output', { 'data-location': value }, value);
}

async function render(ui, entry = '/') {
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => {
    root.render(React.createElement(MemoryRouter, { initialEntries: [entry] }, ui));
  });
  return root;
}

async function renderAccountApp(entry) {
  globalThis.__ui6AccountEntry = entry;
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => {
    root.render(h(AccountApp));
  });
  return root;
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function click(element) {
  assert.ok(element, 'expected an interactive element');
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  });
  await settle();
}

async function unmount(root) {
  await act(async () => root.unmount());
}

function setInput(input, value) {
  assert.ok(input, 'expected an input');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
  });
}

async function submit(form) {
  await act(async () => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await settle();
}

const fullProfile = (overrides = {}) => ({
  id: 41,
  tenant_id: 7,
  role: 'user',
  email: 'account@example.test',
  first_name: 'Ada',
  last_name: 'Lovelace',
  phone: '+12025550123',
  country_code: 'US',
  is_active: true,
  is_verified: false,
  two_factor_enabled: false,
  kyc_status: 'pending',
  avatar_url: '/uploads/profiles/41/avatar.png',
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
  ...overrides,
});

function profileResponse(user) {
  return { data: { message: 'Completed.', user } };
}

function kycRow(type, overrides = {}) {
  return {
    type,
    name: type.replaceAll('_', ' '),
    status: 'not_uploaded',
    uploaded_at: null,
    notes: null,
    url: null,
    ...overrides,
  };
}

function kycPayload(rows) {
  return {
    data: {
      overall_status: 'pending',
      statistics: { total: 4, uploaded: 1, approved: 1, pending: 0, rejected: 0 },
      documents: rows,
    },
  };
}

test('UI6 account: ProtectedRoute and RoleGuard render guest, permitted, and forbidden outcomes in the active Router source', async () => {
  globalThis.__ui6AccountStore = { isAuthenticated: false, isLoading: false, user: null };
  let root = await render(h(Routes, null,
    h(Route, { path: '/profile', element: h(ProtectedRoute, null, h('span', null, 'permitted')) }),
    h(Route, { path: '/login', element: fragment(h('span', null, 'login page'), h(LocationProbe)) }),
  ), '/profile?tab=security');
  try {
    await settle();
    assert.equal(document.querySelector('[data-location]').textContent, '/login?redirect=%2Fprofile%3Ftab%3Dsecurity');
    assert.equal(document.body.textContent.includes('permitted'), false);
  } finally {
    await unmount(root);
  }

  globalThis.__ui6AccountStore = { isAuthenticated: true, isLoading: false, user: { id: 41, role: 'user' } };
  root = await render(h(Routes, null,
    h(Route, { path: '/documents', element: h(ProtectedRoute, { userOnly: true }, fragment(h('span', null, 'permitted'), h(LocationProbe))) }),
  ), '/documents');
  try {
    assert.equal(document.body.textContent.includes('permitted'), true);
    assert.equal(document.querySelector('[data-location]').textContent, '/documents');
  } finally {
    await unmount(root);
  }

  globalThis.__ui6AccountStore = { isAuthenticated: true, isLoading: false, user: { id: 9, role: 'supermaster' } };
  root = await render(h(Routes, null,
    h(Route, { path: '/documents', element: h(ProtectedRoute, { userOnly: true }, h('span', null, 'forbidden')) }),
    h(Route, { path: '/admin', element: fragment(h('span', null, 'admin page'), h(LocationProbe)) }),
  ), '/documents');
  try {
    await settle();
    assert.equal(document.querySelector('[data-location]').textContent, '/admin');
    assert.equal(document.body.textContent.includes('forbidden'), false);
  } finally {
    await unmount(root);
  }

  globalThis.__ui6AccountStore = { isAuthenticated: true, isLoading: false, user: { id: 9, role: 'affiliate' } };
  root = await render(h(RoleGuard, { allowedRoles: ['trader'] }, h('span', null, 'trader-only')), '/trader');
  try {
    assert.match(document.body.textContent, /Access Denied/);
    assert.equal(document.body.textContent.includes('trader-only'), false);
  } finally {
    await unmount(root);
  }

  globalThis.__ui6AccountStore = { isAuthenticated: true, isLoading: false, user: { id: 42, role: 'trader' } };
  root = await render(h(RoleGuard, { allowedRoles: ['trader'] }, h('span', null, 'trader-only')), '/trader');
  try {
    assert.equal(document.body.textContent.includes('trader-only'), true);
  } finally {
    await unmount(root);
  }
});

test('UI6 account: role dashboard dispatches absent and authenticated accounts to the actual destination', async () => {
  globalThis.__ui6AccountStore = { user: null };
  let root = await render(fragment(h(RoleBasedDashboard), h(LocationProbe)), '/dashboard');
  try {
    await settle();
    assert.equal(document.querySelector('[data-location]').textContent, '/login');
  } finally {
    await unmount(root);
  }

  globalThis.__ui6AccountStore = { user: { id: 41, role: 'trader' } };
  root = await render(fragment(h(RoleBasedDashboard), h(LocationProbe)), '/dashboard');
  try {
    await settle();
    assert.equal(document.querySelector('[data-location]').textContent, '/trader');
  } finally {
    await unmount(root);
  }
});

test('UI6 account: live App Router redirects protected account entries and mounts each allowed account path', async () => {
  const user = { id: 41, tenant_id: 7, role: 'user' };
  const trader = { id: 42, tenant_id: 7, role: 'trader' };
  const admin = { id: 9, tenant_id: 7, role: 'supermaster' };
  const cases = [
    { entry: '/dashboard', state: { isAuthenticated: false, isLoading: false, user: null }, expected: '/login' },
    { entry: '/dashboard', state: { isAuthenticated: true, isLoading: false, user }, expected: '/user/dashboard' },
    { entry: '/dashboard', state: { isAuthenticated: true, isLoading: false, user: trader }, expected: '/trader' },
    { entry: '/dashboard', state: { isAuthenticated: true, isLoading: false, user: { id: 9, tenant_id: 7, role: 'affiliate' } }, expected: '/affiliate/dashboard' },
    { entry: '/dashboard', state: { isAuthenticated: true, isLoading: false, user: { id: 9, tenant_id: 7, role: 'supermaster' } }, expected: '/admin' },
    { entry: '/kyc', state: { isAuthenticated: false, isLoading: false, user: null }, expected: '/login' },
    { entry: '/kyc', state: { isAuthenticated: true, isLoading: false, user }, expected: '/kyc' },
    { entry: '/profile', state: { isAuthenticated: true, isLoading: false, user }, expected: '/profile' },
    { entry: '/documents', state: { isAuthenticated: true, isLoading: false, user }, expected: '/documents' },
    { entry: '/settings', state: { isAuthenticated: true, isLoading: false, user }, expected: '/settings' },
    { entry: '/user/dashboard', state: { isAuthenticated: true, isLoading: false, user }, expected: '/user/dashboard' },
    { entry: '/trader', state: { isAuthenticated: true, isLoading: false, user: trader }, expected: '/trader' },
    { entry: '/trader/documents', state: { isAuthenticated: true, isLoading: false, user: trader }, expected: '/trader/documents' },
    { entry: '/profile', state: { isAuthenticated: true, isLoading: false, user: admin }, expected: '/admin' },
    { entry: '/documents', state: { isAuthenticated: true, isLoading: false, user: admin }, expected: '/admin' },
    { entry: '/settings', state: { isAuthenticated: true, isLoading: false, user: admin }, expected: '/admin' },
    { entry: '/agent', state: { isAuthenticated: false, isLoading: false, user: null }, expected: '/login' },
    { entry: '/agent/traders', state: { isAuthenticated: false, isLoading: false, user: null }, expected: '/login' },
    { entry: '/agent/commissions', state: { isAuthenticated: false, isLoading: false, user: null }, expected: '/login' },
    { entry: '/agent/reports', state: { isAuthenticated: false, isLoading: false, user: null }, expected: '/login' },
    { entry: '/agent', state: { isAuthenticated: true, isLoading: false, user: { id: 43, tenant_id: 7, role: 'affiliate' } }, expected: '/affiliate/dashboard' },
    { entry: '/agent/traders', state: { isAuthenticated: true, isLoading: false, user: { id: 43, tenant_id: 7, role: 'affiliate' } }, expected: '/affiliate/traders' },
    { entry: '/agent/commissions', state: { isAuthenticated: true, isLoading: false, user: { id: 43, tenant_id: 7, role: 'affiliate' } }, expected: '/affiliate/commissions' },
    { entry: '/agent/reports', state: { isAuthenticated: true, isLoading: false, user: { id: 43, tenant_id: 7, role: 'affiliate' } }, expected: '/affiliate/reports' },
  ];

  try {
    for (const current of cases) {
      globalThis.__ui6AccountStore = { ...current.state, init: () => {} };
      const root = await renderAccountApp(current.entry);
      try {
        await settle();
        const marker = document.querySelector('[data-ui6-account-route]');
        assert.ok(marker, `${current.entry} mounted a lazy route marker`);
        assert.equal(marker.textContent, current.expected, `${current.entry} resolves to its protected destination`);
      } finally {
        await unmount(root);
      }
    }
  } finally {
    delete globalThis.__ui6AccountEntry;
  }
});

test('UI6 account: profile DOM binds tabs, avatar confirmation, personal write acknowledgement, and password sign-out', async () => {
  const calls = [];
  const store = {
    isAuthenticated: true,
    user: fullProfile(),
    updateUser: (user) => { calls.push(['updateUser', user]); },
    clearAuthenticatedSession: () => { calls.push(['clearAuthenticatedSession']); },
  };
  globalThis.__ui6AccountStore = store;
  globalThis.__ui6ProfileHandlers = {
    get: async () => { calls.push(['get']); return profileResponse(fullProfile()); },
    update: async (payload) => { calls.push(['update', payload]); return profileResponse(fullProfile(payload)); },
    uploadAvatar: async () => { calls.push(['uploadAvatar']); return profileResponse(fullProfile()); },
    deleteAvatar: async () => { calls.push(['deleteAvatar']); return profileResponse(fullProfile({ avatar_url: null })); },
    changePassword: async (payload) => { calls.push(['changePassword', payload]); return { data: { message: 'Password changed successfully' } }; },
  };
  const root = await render(fragment(h(Profile), h(LocationProbe)), '/profile');
  try {
    await settle();
    assert.deepEqual(calls[0], ['get']);

    const avatarInput = document.getElementById('profile-avatar-file');
    let pickerClicks = 0;
    avatarInput.click = () => { pickerClicks += 1; };
    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Upload new photo')));
    assert.equal(pickerClicks, 1, 'the visible control opens the bound file input only after profile readiness');

    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Delete photo')));
    assert.ok(document.querySelector('[role="dialog"]'));
    await click([...document.querySelectorAll('[role="dialog"] button')].find((node) => node.textContent.includes('Cancel')));
    assert.equal(document.querySelector('[role="dialog"]'), null);
    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Delete photo')));
    await click([...document.querySelectorAll('[role="dialog"] button')].find((node) => node.textContent === 'Delete photo'));
    assert.ok(calls.some((entry) => entry[0] === 'deleteAvatar'), 'delete is invoked only after explicit dialog confirmation and server-shaped response');
    assert.match(document.body.textContent, /profile photo was deleted/i);

    await click(document.getElementById('profile-security-tab'));
    assert.ok(document.getElementById('profile-security-panel'));
    await click(document.getElementById('profile-personal-tab'));
    assert.ok(document.getElementById('profile-personal-panel'));
    setInput(document.getElementById('profile-first-name'), 'Grace');
    setInput(document.getElementById('profile-last-name'), 'Hopper');
    setInput(document.getElementById('profile-phone'), '+12025550124');
    await submit(document.getElementById('profile-personal-panel'));
    assert.deepEqual(calls.find((entry) => entry[0] === 'update'), ['update', { first_name: 'Grace', last_name: 'Hopper', phone: '+12025550124' }]);
    assert.match(document.body.textContent, /profile details were saved/i, 'success appears only after the complete returned user acknowledgement');

    await click(document.getElementById('profile-security-tab'));
    setInput(document.getElementById('profile-current-password'), 'OldPass1!');
    setInput(document.getElementById('profile-new-password'), 'NewPass1!');
    setInput(document.getElementById('profile-confirm-password'), 'Mismatch1!');
    await submit(document.getElementById('profile-security-panel'));
    assert.match(document.body.textContent, /New passwords do not match/);
    assert.equal(calls.some((entry) => entry[0] === 'changePassword'), false, 'mismatched password never produces a write');

    setInput(document.getElementById('profile-confirm-password'), 'NewPass1!');
    await submit(document.getElementById('profile-security-panel'));
    assert.deepEqual(calls.find((entry) => entry[0] === 'changePassword'), ['changePassword', { current_password: 'OldPass1!', new_password: 'NewPass1!' }]);
    assert.ok(calls.some((entry) => entry[0] === 'clearAuthenticatedSession'));
    assert.equal(document.querySelector('[data-location]').textContent, '/login');
  } finally {
    await unmount(root);
  }
});

test('UI6 account: profile retry with a late initial failure needs a fresh request before controls become available', async () => {
  let gets = 0;
  globalThis.__ui6AccountStore = {
    isAuthenticated: true,
    user: fullProfile(),
    updateUser: () => {},
    clearAuthenticatedSession: () => {},
  };
  globalThis.__ui6ProfileHandlers = {
    get: async () => {
      gets += 1;
      if (gets === 1) throw new Error('synthetic unavailable profile');
      return profileResponse(fullProfile());
    },
    update: async () => profileResponse(fullProfile()),
    uploadAvatar: async () => profileResponse(fullProfile()),
    deleteAvatar: async () => profileResponse(fullProfile({ avatar_url: null })),
    changePassword: async () => ({ data: { message: 'Password changed successfully' } }),
  };
  const root = await render(h(Profile), '/profile');
  try {
    await settle();
    assert.match(document.body.textContent, /could not load the current profile/i);
    const retry = [...document.querySelectorAll('button')].find((node) => node.textContent.includes('Retry loading profile'));
    await click(retry);
    assert.equal(gets, 2);
    assert.equal(document.getElementById('profile-first-name').disabled, false);
  } finally {
    await unmount(root);
  }
});

test('UI6 account: documents DOM requires a principal, posts only an acknowledged matching pending record, and binds downloads to that owner', async () => {
  const calls = [];
  const rows = [
    kycRow('id_proof'),
    kycRow('address_proof', { status: 'approved', uploaded_at: '2026-10-12T08:00:00Z', url: '/api/v1/kyc/documents/41/address_proof/download' }),
    kycRow('selfie'),
    kycRow('bank_statement'),
  ];
  globalThis.__ui6AccountStore = { isAuthenticated: true, user: { id: 41, tenant_id: 7, role: 'user' } };
  globalThis.__ui6KycHandlers = {
    get: async (path, config) => {
      calls.push(['get', path, config]);
      if (path === '/kyc/documents') return kycPayload(rows);
      return { data: new Blob(['synthetic document'], { type: 'application/pdf' }) };
    },
    post: async (path, formData, config) => {
      calls.push(['post', path, formData, config]);
      return { data: { document: { type: 'id_proof', name: 'ID Proof', status: 'pending', uploaded_at: '2026-10-12T08:00:00Z' } } };
    },
  };
  const originalAnchorClick = window.HTMLAnchorElement.prototype.click;
  const originalCreateObjectURL = window.URL.createObjectURL;
  const originalRevokeObjectURL = window.URL.revokeObjectURL;
  let anchorClicks = 0;
  window.HTMLAnchorElement.prototype.click = function clickSyntheticDownload() { anchorClicks += 1; };
  window.URL.createObjectURL = () => 'blob:ui6-account';
  window.URL.revokeObjectURL = () => {};
  const root = await render(h(Documents), '/documents');
  try {
    await settle();
    assert.equal(calls.filter((entry) => entry[0] === 'get' && entry[1] === '/kyc/documents').length, 1);
    const file = new File(['synthetic only'], 'identity.pdf', { type: 'application/pdf' });
    const input = document.getElementById('kyc-file-id_proof');
    Object.defineProperty(input, 'files', { configurable: true, value: [file] });
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true, cancelable: true })));
    await settle();
    const post = calls.find((entry) => entry[0] === 'post');
    assert.equal(post[1], '/kyc/documents/id_proof/upload');
    assert.equal(post[2].get('file').name, 'identity.pdf');
    assert.equal(post[3].headers['Content-Type'], undefined, 'multipart boundary remains browser-owned');
    assert.ok(calls.filter((entry) => entry[0] === 'get' && entry[1] === '/kyc/documents').length >= 2, 'acknowledged upload must refresh recorded status rather than invent it');

    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Download recorded document')));
    const download = calls.find((entry) => entry[0] === 'get' && entry[1] === '/kyc/documents/41/address_proof/download');
    assert.equal(download[2].responseType, 'blob');
    assert.equal(anchorClicks, 1, 'one principal-bound temporary download click is produced');

    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Refresh status')));
    assert.ok(calls.filter((entry) => entry[0] === 'get' && entry[1] === '/kyc/documents').length >= 3);
  } finally {
    window.HTMLAnchorElement.prototype.click = originalAnchorClick;
    window.URL.createObjectURL = originalCreateObjectURL;
    window.URL.revokeObjectURL = originalRevokeObjectURL;
    await unmount(root);
  }

  globalThis.__ui6AccountStore = { isAuthenticated: false, user: null };
  globalThis.__ui6KycHandlers = {
    get: async () => { throw new Error('no request permitted for absent principal'); },
    post: async () => { throw new Error('no request permitted for absent principal'); },
  };
  const unavailableRoot = await render(h(Documents), '/documents');
  try {
    await settle();
    assert.match(document.body.textContent, /account session is not active/i);
    assert.equal([...document.querySelectorAll('button')].some((node) => node.textContent.includes('Retry status check')), false);
  } finally {
    await unmount(unavailableRoot);
  }
});

test('UI6 account: documents failure retry is a new read, never a successful synthetic write', async () => {
  let reads = 0;
  globalThis.__ui6AccountStore = { isAuthenticated: true, user: { id: 41, tenant_id: 7, role: 'user' } };
  globalThis.__ui6KycHandlers = {
    get: async (path) => {
      assert.equal(path, '/kyc/documents');
      reads += 1;
      if (reads === 1) throw { response: { data: { error: 'Synthetic recorded status failure' } } };
      return kycPayload([kycRow('id_proof'), kycRow('address_proof'), kycRow('selfie'), kycRow('bank_statement')]);
    },
    post: async () => { throw new Error('not reached'); },
  };
  const root = await render(h(Documents), '/documents');
  try {
    await settle();
    assert.match(document.body.textContent, /Synthetic recorded status failure/);
    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Retry status check')));
    assert.equal(reads, 2);
    assert.match(document.body.textContent, /Recorded document status/);
  } finally {
    await unmount(root);
  }
});

test('UI6 account: user dashboard links and refresh/retry controls change Router state or invoke only their supplied retry callback', async () => {
  const dashboard = {
    owner: { userId: 41, tenantId: 7 },
    user: { id: 41, tenantId: 7, role: 'user', firstName: 'Ada' },
    statistics: { statusCounts: { total: 1, active: 1, passed: 0, failed: 0, funded: 0 }, successRate: null },
    recentChallenges: [{ id: 10, programName: 'Recorded challenge', phase: 1, totalPhases: 2, status: 'active', statusDataStatus: 'recorded', currentBalance: '1000.00', profit: '0.00', profitDataStatus: 'recorded', progressDataStatus: 'unavailable', createdAt: '2026-02-28T12:00:00Z' }],
  };
  let refreshes = 0;
  let retries = 0;
  const root = await render(fragment(
    h(DashboardOverview, { dashboard, onRefresh: () => { refreshes += 1; } }),
    h(DashboardReadState, { state: 'error', onRetry: () => { retries += 1; } }),
    h(LocationProbe),
  ), '/user/dashboard');
  try {
    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Refresh records')));
    assert.equal(refreshes, 1);
    await click([...document.querySelectorAll('button')].find((node) => node.textContent.includes('Retry dashboard')));
    assert.equal(retries, 1);

    const destinations = [
      ['All challenges', '/challenges'],
      ['Programs', '/programs'],
      ['Documents', '/documents'],
      ['Support', '/support/my-tickets'],
      ['Profile', '/profile'],
      ['Recorded challenge', '/challenges/10'],
    ];
    for (const [label, destination] of destinations) {
      await click([...document.querySelectorAll('a')].find((node) => node.textContent.includes(label)));
      assert.equal(document.querySelector('[data-location]').textContent, destination, label);
    }
  } finally {
    await unmount(root);
  }
});

// The frozen inventory included an unused lazy import, not an actual route.
// This regression checks both the production route expression and import graph
// boundary; the DOM route test above exercises its actual role dispatch.
test('UI6 account: retired Dashboard leaf has no App import or route expression and the shared path uses the canonical role dispatcher', () => {
  const app = fs.readFileSync(source('App.jsx'), 'utf8');
  assert.equal(/import\(['"]\.\/pages\/Dashboard['"]\)/.test(app), false);
  assert.equal(/<Dashboard\s*\/>/.test(app), false);
  assert.match(app, /path="\/dashboard"[\s\S]*?<RoleBasedDashboard\s*\/>/);
  assert.ok(fs.existsSync(source('pages/Dashboard.jsx')), 'retirement removes no source file or data');
});
