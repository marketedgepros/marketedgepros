import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const read = (...parts) => fs.readFileSync(sourcePath(...parts), 'utf8');
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const dependencies = new Map([
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
  ['react', dependencyUrl('react')],
]);
let serial = 0;

function makeImportable(code) {
  for (const [specifier, url] of dependencies) {
    code = code.replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
    code = code.replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
  }
  return code;
}

async function compile(name, source) {
  const transformed = await transformWithEsbuild(source, `${name}.jsx`, { loader: 'jsx', jsx: 'automatic' });
  const target = path.join(os.tmpdir(), `ui6-shell-${process.pid}-${serial += 1}.mjs`);
  fs.writeFileSync(target, makeImportable(transformed.code));
  try {
    return await import(`${pathToFileURL(target).href}?ui6=${serial}`);
  } finally {
    fs.rmSync(target, { force: true });
  }
}

function installDom() {
  const instance = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' });
  const previous = {};
  for (const key of ['window', 'document', 'HTMLElement', 'Node', 'Event', 'MouseEvent', 'IS_REACT_ACT_ENVIRONMENT']) {
    previous[key] = globalThis[key];
  }
  globalThis.window = instance.window;
  globalThis.document = instance.window.document;
  globalThis.HTMLElement = instance.window.HTMLElement;
  globalThis.Node = instance.window.Node;
  globalThis.Event = instance.window.Event;
  globalThis.MouseEvent = instance.window.MouseEvent;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  instance.window.requestAnimationFrame ??= (callback) => instance.window.setTimeout(callback, 0);
  instance.window.cancelAnimationFrame ??= (id) => instance.window.clearTimeout(id);
  instance.window.HTMLElement.prototype.scrollIntoView ??= () => {};
  return {
    host: instance.window.document.getElementById('root'),
    async close(root) {
      await act(async () => root.unmount());
      instance.window.close();
      for (const [key, value] of Object.entries(previous)) {
        if (value === undefined) delete globalThis[key];
        else globalThis[key] = value;
      }
    },
  };
}

function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { id: 'ui6-location' }, `${location.pathname}${location.search}${location.hash}`);
}

async function mount(Component, { initial = '/', props = {}, children = null } = {}) {
  const dom = installDom();
  const root = createRoot(dom.host);
  await act(async () => root.render(
    React.createElement(
      MemoryRouter,
      { initialEntries: [initial] },
      React.createElement(Component, props, children),
      React.createElement(LocationProbe),
    ),
  ));
  return {
    ...dom,
    root,
    location() { return dom.host.querySelector('#ui6-location').textContent; },
  };
}

async function click(element) {
  assert.ok(element, 'expected an actionable element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await Promise.resolve();
  });
}

function namedAnchor(host, label, parent = host) {
  return [...parent.querySelectorAll('a')].find((anchor) => anchor.textContent.trim() === label);
}

function namedButton(host, label) {
  return [...host.querySelectorAll('button')].find((button) => button.textContent.trim() === label);
}

const Navbar = (await compile(
  'LandingNavbar',
  read('components', 'layout', 'LandingNavbar.jsx')
    .replace("import useAuthStore from '../../store/authStore';", 'const useAuthStore = () => globalThis.__ui6Auth;'),
)).default;
const Footer = (await compile('LandingFooter', read('components', 'layout', 'LandingFooter.jsx'))).default;
const ChatWidget = (await compile(
  'ChatWidget',
  read('components', 'ChatWidget.jsx')
    .replace("import api from '../services/api';", 'const api = { post: (...args) => globalThis.__ui6ChatPost(...args) };'),
)).default;
const TraderLayout = (await compile(
  'TraderLayout',
  read('components', 'trader', 'TraderLayout.jsx')
    .replace("import useAuthStore from '../../store/authStore';", 'const useAuthStore = () => globalThis.__ui6Auth;')
    .replace("import { useDialogFocus } from '../../hooks/useDialogFocus.js';", `import { useDialogFocus } from ${JSON.stringify(pathToFileURL(sourcePath('hooks', 'useDialogFocus.js')).href)};`)
    .replace("import NotificationBell from '../notifications/NotificationBell';", 'const NotificationBell = () => null;')
    .replace("import { accountHome } from '../../services/navigationService.js';", "const accountHome = (user) => user?.role === 'trader' ? '/trader' : '/user/dashboard';"),
)).default;
const AffiliateLayout = (await compile(
  'AgentLayout',
  read('components', 'agent', 'AgentLayout.jsx')
    .replace("import useAuthStore from '../../store/authStore';", 'const useAuthStore = () => globalThis.__ui6Auth;')
    .replace("import { useDialogFocus } from '../../hooks/useDialogFocus.js';", `import { useDialogFocus } from ${JSON.stringify(pathToFileURL(sourcePath('hooks', 'useDialogFocus.js')).href)};`)
    .replace("import NotificationBell from '../notifications/NotificationBell';", 'const NotificationBell = () => null;'),
)).default;
const AdminLayout = (await compile(
  'AdminLayout',
  read('components', 'admin', 'AdminLayout.jsx')
    .replace("import useAuthStore from '../../store/authStore';", 'const useAuthStore = () => globalThis.__ui6Auth;')
    .replace("import { useDialogFocus } from '../../hooks/useDialogFocus.js';", `import { useDialogFocus } from ${JSON.stringify(pathToFileURL(sourcePath('hooks', 'useDialogFocus.js')).href)};`)
    .replace("import NotificationBell from '../notifications/NotificationBell';", 'const NotificationBell = () => null;'),
)).default;
const RoleGuard = (await compile(
  'RoleGuard',
  read('components', 'guards', 'RoleGuard.jsx')
    .replace("import useAuthStore from '../../store/authStore';", 'const useAuthStore = () => globalThis.__ui6Auth;'),
)).default;

function compiledAppSource() {
  const navigationUrl = pathToFileURL(sourcePath('services', 'navigationService.js')).href;
  let source = read('App.jsx')
    .replace("import { useState, useEffect, lazy, Suspense } from 'react';", "import React, { useState, useEffect, lazy, Suspense } from 'react';")
    .replace("import useAuthStore from './store/authStore';", `const useAuthStore = () => globalThis.__ui6Auth; useAuthStore.subscribe = () => () => {};`)
    .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
    .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(pathToFileURL(path.join(frontend, 'src/components/RouteScrollManager.js')).href)};`)
    .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => React.createElement("div", { "data-chat": "true" });')
    .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['admin'];")
    .replace("import { postLoginDestination } from './services/navigationService.js';", `import { postLoginDestination } from ${JSON.stringify(navigationUrl)};`)
    .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
    .replace("import useNotificationStore from './stores/notificationStore.js';", 'const useNotificationStore = { getState: () => ({ reset: () => { globalThis.__ui6ResetCount = (globalThis.__ui6ResetCount || 0) + 1; } }) };')
    .replace("import RoleGuard from './components/guards/RoleGuard';", 'const RoleGuard = ({ children }) => children;')
    .replace('import { BrowserRouter, Routes, Route, Navigate } from \'react-router-dom\';', 'import { MemoryRouter, Routes, Route, Navigate } from \'react-router-dom\';')
    .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6InitialEntries}>')
    .replace('</BrowserRouter>', '</MemoryRouter>');
  source = source.replace(/^const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\([^\n]+\)\);$/gm, 'const $1 = () => null;');
  assert.equal((source.match(/=\s*lazy\(/g) || []).length, 0, 'every lazy page is replaced only in the test module');
  source = source.replace('function App() {', 'function LocationProbe() { const location = useLocation(); return <output id="app-location">{location.pathname + location.search + location.hash}</output>; }\n\nfunction App() {');
  source = source.replace('</Routes>', '</Routes><LocationProbe />');
  return source;
}

const App = (await compile('AppRouter', compiledAppSource())).default;

async function mountApp(initial, auth) {
  globalThis.__ui6Auth = auth;
  globalThis.__ui6InitialEntries = [initial];
  const dom = installDom();
  const root = createRoot(dom.host);
  await act(async () => root.render(React.createElement(App)));
  await act(async () => { await Promise.resolve(); });
  return {
    ...dom,
    root,
    location() { return dom.host.querySelector('#app-location').textContent; },
  };
}

function authFixture(user, events = []) {
  return {
    isAuthenticated: Boolean(user),
    isLoading: false,
    user,
    init() { events.push('init'); },
    async logout() { events.push('logout'); return { acknowledged: true }; },
  };
}

test('UI6 actual App router executes guest, role, public-return, legal-alias and 404 boundaries', async () => {
  let view = await mountApp('/support/my-tickets?filter=open', authFixture(null));
  try {
    assert.equal(view.location(), '/login?redirect=%2Fsupport%2Fmy-tickets%3Ffilter%3Dopen');
  } finally { await view.close(view.root); }

  view = await mountApp('/profile', authFixture({ id: 'admin-1', role: 'admin' }));
  try {
    assert.equal(view.location(), '/admin');
  } finally { await view.close(view.root); }

  view = await mountApp('/login?redirect=%2Fsupport%2Fmy-tickets', authFixture({ id: 'user-1', role: 'user' }));
  try {
    assert.equal(view.location(), '/support/my-tickets');
  } finally { await view.close(view.root); }

  for (const [alias, destination] of [['/terms', '/terms-of-service'], ['/privacy', '/privacy-policy']]) {
    view = await mountApp(alias, authFixture(null));
    try {
      assert.equal(view.location(), destination, alias);
    } finally { await view.close(view.root); }
  }

  view = await mountApp('/does-not-exist', authFixture(null));
  try {
    assert.equal(view.host.querySelector('a[href="/"]').textContent.trim(), 'Go to Home');
  } finally { await view.close(view.root); }
});

test('UI6 RoleGuard executes anonymous redirect and supplies a real forbidden-state dashboard anchor', async () => {
  globalThis.__ui6Auth = authFixture(null);
  let view = await mount(RoleGuard, { initial: '/admin', props: { allowedRoles: ['admin'] }, children: React.createElement('p', null, 'private') });
  try {
    assert.equal(view.location(), '/login');
  } finally { await view.close(view.root); }

  globalThis.__ui6Auth = authFixture({ id: 'user-1', role: 'user' });
  view = await mount(RoleGuard, { props: { allowedRoles: ['admin'] }, children: React.createElement('p', null, 'private') });
  try {
    const fallback = namedAnchor(view.host, 'Go to Dashboard');
    assert.equal(fallback.getAttribute('href'), '/dashboard');
    assert.match(view.host.textContent, /Access Denied/);
  } finally { await view.close(view.root); }
});

test('UI6 public shell performs internal router navigation, mobile pair-closing and logout acknowledgement ordering', async () => {
  globalThis.__ui6Auth = authFixture(null);
  for (const [label, destination] of [
    ['MarketEdgePros', '/'], ['Programs', '/programs'], ['About', '/about'], ['Blog', '/blog'], ['Support', '/support'], ['Login', '/login'], ['View programs', '/programs'],
  ]) {
    const view = await mount(Navbar);
    try {
      await click(label === 'MarketEdgePros' ? view.host.querySelector('a[href="/"]') : namedAnchor(view.host, label));
      assert.equal(view.location(), destination, label);
    } finally { await view.close(view.root); }
  }

  let view = await mount(Navbar);
  try {
    await click(view.host.querySelector('[aria-controls="mobile-navigation"]'));
    const menu = view.host.querySelector('#mobile-navigation');
    assert.ok(menu);
    await click(namedAnchor(view.host, 'Programs', menu));
    assert.equal(view.location(), '/programs');
    assert.equal(view.host.querySelector('#mobile-navigation'), null, 'mobile Link closes through its paired onClick');
  } finally { await view.close(view.root); }

  view = await mount(Navbar);
  try {
    await click(view.host.querySelector('[aria-controls="mobile-navigation"]'));
    const menu = view.host.querySelector('#mobile-navigation');
    const localAnchor = namedAnchor(view.host, 'How It Works', menu);
    localAnchor.addEventListener('click', (event) => event.preventDefault(), { once: true });
    await click(localAnchor);
    assert.equal(view.host.querySelector('#mobile-navigation'), null, 'plain hash anchor closes through its paired onClick');
  } finally { await view.close(view.root); }

  const events = [];
  globalThis.__ui6Auth = authFixture({ id: 'user-1', role: 'user', first_name: 'Ada' }, events);
  view = await mount(Navbar);
  try {
    await click(namedAnchor(view.host, 'Dashboard'));
    assert.equal(view.location(), '/dashboard');
    await click(namedButton(view.host, 'Logout'));
    assert.deepEqual(events.filter((event) => event === 'logout'), ['logout']);
    assert.equal(view.location(), '/');
  } finally { await view.close(view.root); }

  globalThis.__ui6Auth = authFixture({ id: 'user-1', role: 'user', first_name: 'Ada' }, events);
  view = await mount(Navbar);
  try {
    await click(view.host.querySelector('[aria-controls="mobile-navigation"]'));
    await click(namedAnchor(view.host, 'Dashboard', view.host.querySelector('#mobile-navigation')));
    assert.equal(view.location(), '/dashboard');
    assert.equal(view.host.querySelector('#mobile-navigation'), null);
  } finally { await view.close(view.root); }

  globalThis.__ui6Auth = authFixture(null);
  for (const [label, destination] of [['Login', '/login'], ['View programs', '/programs']]) {
    view = await mount(Navbar);
    try {
      await click(view.host.querySelector('[aria-controls="mobile-navigation"]'));
      await click(namedAnchor(view.host, label, view.host.querySelector('#mobile-navigation')));
      assert.equal(view.location(), destination, label);
      assert.equal(view.host.querySelector('#mobile-navigation'), null);
    } finally { await view.close(view.root); }
  }

  globalThis.__ui6Auth = authFixture({ id: 'user-1', role: 'user', first_name: 'Ada' }, events);
  view = await mount(Navbar);
  try {
    await click(view.host.querySelector('[aria-controls="mobile-navigation"]'));
    await click(namedButton(view.host.querySelector('#mobile-navigation'), 'Logout'));
    assert.equal(view.location(), '/');
    assert.equal(view.host.querySelector('#mobile-navigation'), null);
  } finally { await view.close(view.root); }
});

test('UI6 chat shell executes open, minimize/maximize and close without contacting a provider', async () => {
  const calls = [];
  globalThis.__ui6ChatPost = async (...args) => {
    calls.push(args);
    return { data: { message: 'Synthetic assistant acknowledgement' } };
  };
  const view = await mount(ChatWidget);
  try {
    await click(view.host.querySelector('[aria-label="Open chat"]'));
    await click(view.host.querySelector('[aria-label="Minimize"]'));
    assert.ok(view.host.querySelector('[aria-label="Maximize"]'));
    await click(view.host.querySelector('[aria-label="Maximize"]'));
    assert.ok(view.host.querySelector('[aria-label="Close chat"]'));
    const quick = [...view.host.querySelectorAll('button')].find((button) => button.textContent === 'What trading programs do you offer?');
    await click(quick);
    await click(view.host.querySelector('[aria-label="Send message"]'));
    assert.deepEqual(calls, [['/chat/message', { message: 'What trading programs do you offer?' }]]);
    assert.match(view.host.textContent, /Synthetic assistant acknowledgement/);
    await click(view.host.querySelector('[aria-label="Close chat"]'));
    assert.ok(view.host.querySelector('[aria-label="Open chat"]'));
  } finally {
    delete globalThis.__ui6ChatPost;
    await view.close(view.root);
  }
});

test('UI6 footer exposes each internal destination as a real Router anchor and preserves external links as unverified boundaries', async () => {
  const internal = [
    '/about', '/how-it-works', '/blog', '/careers', '/contact', '/programs', '/programs#program-comparison', '/support', '/faq', '/trading-rules', '/affiliate',
    '/terms-of-service', '/privacy-policy', '/risk-disclosure', '/refund-policy', '/cookie-policy', '/cookie-policy#analytics-status', '/',
  ];
  for (const destination of internal) {
    const view = await mount(Footer);
    try {
      const anchor = view.host.querySelector(`a[href="${destination}"]`);
      assert.ok(anchor, destination);
      await click(anchor);
      assert.equal(view.location(), destination, destination);
    } finally { await view.close(view.root); }
  }

  const view = await mount(Footer);
  try {
    for (const destination of ['/contact', '/terms-of-service', '/privacy-policy', '/risk-disclosure']) {
      assert.ok(view.host.querySelectorAll(`a[href="${destination}"]`).length >= 2, `${destination} is rendered at each recorded footer expression`);
    }
    const external = [...view.host.querySelectorAll('a[target="_blank"]')];
    assert.equal(external.length, 6);
    for (const anchor of external) {
      assert.match(anchor.getAttribute('href'), /^https:\/\//);
      assert.equal(anchor.getAttribute('rel'), 'noopener noreferrer');
    }
  } finally { await view.close(view.root); }

  for (const [destination, occurrence] of [['/contact', 1], ['/terms-of-service', 1], ['/privacy-policy', 1], ['/risk-disclosure', 1]]) {
    const duplicateView = await mount(Footer);
    try {
      await click(duplicateView.host.querySelectorAll(`a[href="${destination}"]`)[occurrence]);
      assert.equal(duplicateView.location(), destination, `${destination} duplicate expression`);
    } finally { await duplicateView.close(duplicateView.root); }
  }
});

async function exerciseAccountShell(Component, fixture, expected) {
  const events = [];
  globalThis.__ui6Auth = authFixture(fixture, events);
  let view = await mount(Component, { initial: expected.home, children: React.createElement('p', null, 'content') });
  try {
    for (const destination of expected.destinations) {
      assert.ok(view.host.querySelector(`a[href="${destination}"]`), destination);
    }
    const open = view.host.querySelector('[aria-label="Open navigation menu"]');
    await click(open);
    assert.equal(open.getAttribute('aria-expanded'), 'true');
    const item = view.host.querySelector(`a[href="${expected.destinations[0]}"]`);
    await click(item);
    assert.equal(view.location(), expected.destinations[0]);
    assert.equal(view.host.querySelector('[aria-label="Open navigation menu"]').getAttribute('aria-expanded'), 'false', 'item Link and close handler are paired');
  } finally { await view.close(view.root); }

  for (const destination of expected.destinations) {
    globalThis.__ui6Auth = authFixture(fixture, events);
    const destinationView = await mount(Component, { initial: expected.home });
    try {
      await click(destinationView.host.querySelector(`a[href="${destination}"]`));
      assert.equal(destinationView.location(), destination, destination);
    } finally { await destinationView.close(destinationView.root); }
  }

  for (const occurrence of [0, 1]) {
    globalThis.__ui6Auth = authFixture(fixture, events);
    const homeView = await mount(Component, { initial: expected.home });
    try {
      const homeLinks = homeView.host.querySelectorAll(`a[href="${expected.home}"]`);
      assert.ok(homeLinks.length >= 2, 'both recorded account-home expressions render real anchors');
      await click(homeLinks[occurrence]);
      assert.equal(homeView.location(), expected.home);
    } finally { await homeView.close(homeView.root); }
  }

  globalThis.__ui6Auth = authFixture(fixture, events);
  view = await mount(Component, { initial: expected.home });
  try {
    await click(view.host.querySelector('[aria-label="Open navigation menu"]'));
    const backdrop = [...view.host.querySelectorAll('div[aria-hidden="true"]')].find((element) => element.className.includes('fixed inset-0'));
    await click(backdrop);
    assert.equal(view.host.querySelector('[aria-label="Open navigation menu"]').getAttribute('aria-expanded'), 'false');
    await click(namedButton(view.host, 'Logout'));
    assert.deepEqual(events.filter((event) => event === 'logout'), ['logout']);
    assert.equal(view.location(), '/login');
  } finally { await view.close(view.root); }

  globalThis.__ui6Auth = authFixture(fixture, events);
  view = await mount(Component, { initial: expected.home });
  try {
    await click(view.host.querySelector('[aria-label="Open navigation menu"]'));
    await click(view.host.querySelector('[aria-label="Close navigation menu"]'));
    assert.equal(view.host.querySelector('[aria-label="Open navigation menu"]').getAttribute('aria-expanded'), 'false');
  } finally { await view.close(view.root); }
}

test('UI6 trader and affiliate shells bind every recorded menu destination, close actions and acknowledged logout to Router outcomes', async () => {
  await exerciseAccountShell(
    TraderLayout,
    { id: 'trader-1', role: 'trader', first_name: 'Taylor', email: 'taylor@example.test' },
    { home: '/trader', destinations: ['/challenges', '/scaling', '/wallet', '/trader/history', '/trader/withdrawals', '/documents', '/profile', '/support/my-tickets'] },
  );
  await exerciseAccountShell(
    AffiliateLayout,
    { id: 'affiliate-1', role: 'affiliate', first_name: 'Avery', email: 'avery@example.test' },
    { home: '/affiliate/dashboard', destinations: ['/affiliate/dashboard', '/affiliate/traders', '/affiliate/commissions', '/affiliate/reports', '/profile', '/support/my-tickets'] },
  );
});

test('UI6 admin shell binds mobile open/close, item navigation, support and acknowledged logout to Router outcomes', async () => {
  const events = [];
  globalThis.__ui6Auth = authFixture({ id: 'admin-1', role: 'admin', first_name: 'Admin', last_name: 'User', email: 'admin@example.test' }, events);
  let view = await mount(AdminLayout, { initial: '/admin/dashboard', children: React.createElement('p', null, 'admin content') });
  try {
    for (const destination of ['/admin/dashboard', '/admin/users', '/admin/programs', '/admin/challenges', '/admin/payments', '/admin/withdrawals', '/admin/crm', '/admin/kyc-approval', '/admin/payment-approvals', '/admin/analytics', '/admin/settings']) {
      assert.ok(view.host.querySelector(`a[href="${destination}"]`), destination);
    }
    await click(view.host.querySelector('[aria-label="Open administration menu"]'));
    await click(view.host.querySelector('a[href="/admin/users"]'));
    assert.equal(view.location(), '/admin/users');
    assert.equal(view.host.querySelector('[aria-label="Open administration menu"]').getAttribute('aria-expanded'), 'false');
    await click(view.host.querySelector('[aria-label="Open administration menu"]'));
    const backdrop = [...view.host.querySelectorAll('div')].find((element) => element.className.includes('fixed inset-0 bg-black/50'));
    await click(backdrop);
    assert.equal(view.host.querySelector('[aria-label="Open administration menu"]').getAttribute('aria-expanded'), 'false');
    await click(view.host.querySelector('a[href="/"]'));
    assert.equal(view.location(), '/');
    await click(view.host.querySelector('a[href="/support/my-tickets"]'));
    assert.equal(view.location(), '/support/my-tickets');
    await click(namedButton(view.host, 'Logout'));
    assert.deepEqual(events.filter((event) => event === 'logout'), ['logout']);
    assert.equal(view.location(), '/login');
  } finally { await view.close(view.root); }
});
