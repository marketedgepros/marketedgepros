import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test, { after } from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const sourcePath = (...parts) => path.join(frontendDirectory, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const compiledTargets = new Set();
let serial = 0;

// jsdom is the exact direct devDependency pinned in frontend/package.json (28.1.0).
const jsdomPackage = require(path.join(path.dirname(require.resolve('jsdom')), '..', 'package.json'));
assert.equal(jsdomPackage.version, '28.1.0', 'UI6 requires the pinned jsdom 28.1.0 dependency');
const { JSDOM } = await import(dependencyUrl('jsdom'));
const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'https://ui6-auth.test/',
  pretendToBeVisual: true,
});
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLAnchorElement: dom.window.HTMLAnchorElement,
  Node: dom.window.Node,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
window.requestAnimationFrame ??= (callback) => window.setTimeout(callback, 0);
window.cancelAnimationFrame ??= (id) => window.clearTimeout(id);

// ReactDOM is deliberately imported only after the DOM globals exist: React onChange is
// consequently exercised, rather than falling back to source/SSR-only evidence.
const { createRoot } = await import(dependencyUrl('react-dom/client'));
const { Simulate } = await import(dependencyUrl('react-dom/test-utils'));
const { MemoryRouter, Route, Routes, useLocation } = await import(dependencyUrl('react-router-dom'));

const dependencies = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['zustand', dependencyUrl('zustand')],
]);

function makeImportable(code) {
  for (const [specifier, url] of dependencies) {
    code = code.replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
    code = code.replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
  }
  return code;
}

async function compile(name, relative, mutate) {
  const original = fs.readFileSync(sourcePath(...relative.split('/')), 'utf8');
  const transformed = await transformWithEsbuild(mutate(original), sourcePath(...relative.split('/')), {
    loader: 'jsx',
    jsx: 'automatic',
  });
  const target = path.join(os.tmpdir(), `ui6-auth-${name}-${process.pid}-${serial += 1}.mjs`);
  compiledTargets.add(target);
  fs.writeFileSync(target, makeImportable(transformed.code));
  try {
    return await import(`${pathToFileURL(target).href}?ui6-auth=${serial}`);
  } finally {
    fs.rmSync(target, { force: true });
    compiledTargets.delete(target);
  }
}

after(() => {
  for (const target of compiledTargets) fs.rmSync(target, { force: true });
  dom.window.close();
});

const layoutStub = 'const Layout = ({ children }) => <main data-ui6-layout="auth">{children}</main>;';
const iconStub = 'const Icon = (props) => <svg aria-hidden="true" {...props} />;';
const authStoreStub = 'const useAuthStore = () => globalThis.__ui6AuthStore();';

// Keep the registration store and Axios request adapter live for delivery-status coverage.
// The only substitutions below are rendering-only dependencies that cannot run in jsdom.
const liveApi = (await import(sourceUrl('services', 'api.js'))).default;
const LiveAuthStore = (await compile('live-auth-store', 'store/authStore.js', (text) => text
  .replace("import { create } from 'zustand';", `import { create } from ${JSON.stringify(dependencyUrl('zustand'))};`)
  .replace("import { authAPI } from '../services/api.js';", `import { authAPI } from ${JSON.stringify(sourceUrl('services', 'api.js'))};`)
)).default;

const Login = (await compile('login', 'pages/Login.jsx', (text) => text
  .replace("import { postLoginDestination } from '../services/navigationService.js';", 'const postLoginDestination = (user, search) => globalThis.__ui6PostLogin(user, search);')
  .replace("import Layout from '../components/layout/Layout';", layoutStub)
  .replace("import useAuthStore from '../store/authStore';", authStoreStub)
  .replace("import { LogIn, Mail, Lock, AlertCircle } from 'lucide-react';", `${iconStub} const LogIn = Icon, Mail = Icon, Lock = Icon, AlertCircle = Icon;`)
)).default;
const Register = (await compile('register', 'pages/Register.jsx', (text) => text
  .replace("import Layout from '../components/layout/Layout';", layoutStub)
  .replace("import useAuthStore from '../store/authStore';", authStoreStub)
  .replace("import { UserPlus, Mail, Lock, User, Phone, AlertCircle } from 'lucide-react';", `${iconStub} const UserPlus = Icon, Mail = Icon, Lock = Icon, User = Icon, Phone = Icon, AlertCircle = Icon;`)
)).default;
const VerifyEmail = (await compile('verify-email', 'pages/VerifyEmail.jsx', (text) => text
  .replace("import { useToast } from '../contexts/ToastContext';", 'const useToast = () => globalThis.__ui6Toast;')
  .replace("import Layout from '../components/layout/Layout';", layoutStub)
  .replace("import { Mail, AlertCircle, CheckCircle, RefreshCw } from 'lucide-react';", `${iconStub} const Mail = Icon, AlertCircle = Icon, CheckCircle = Icon, RefreshCw = Icon;`)
  .replace("import api from '../services/api';", 'const api = { post: (...args) => globalThis.__ui6Api.post(...args) };')
)).default;
const ForgotPassword = (await compile('forgot-password', 'pages/ForgotPassword.jsx', (text) => text
  .replace("import Layout from '../components/layout/Layout';", layoutStub)
  .replace('import api from "../services/api";', 'const api = { post: (...args) => globalThis.__ui6Api.post(...args) };')
  .replace("import { Mail, AlertCircle, CheckCircle, ArrowLeft } from 'lucide-react';", `${iconStub} const Mail = Icon, AlertCircle = Icon, CheckCircle = Icon, ArrowLeft = Icon;`)
)).default;
const ResetPassword = (await compile('reset-password', 'pages/ResetPassword.jsx', (text) => text
  .replace("import Layout from '../components/layout/Layout';", layoutStub)
  .replace('import api from "../services/api";', 'const api = { post: (...args) => globalThis.__ui6Api.post(...args) };')
  .replace("import { Lock, AlertCircle, CheckCircle, Eye, EyeOff, Mail } from 'lucide-react';", `${iconStub} const Lock = Icon, AlertCircle = Icon, CheckCircle = Icon, Eye = Icon, EyeOff = Icon, Mail = Icon;`)
)).default;

// This is the actual App router with only test-only dependencies and leaf lazy pages narrowed
// to probes. It keeps PublicRoute, its loading state, and its redirect policy from source live.
const AuthRouter = (await compile('router', 'App.jsx', (text) => {
  const authStub = `const useAuthStore = () => globalThis.__ui6RouterAuth; useAuthStore.subscribe = () => () => {};`;
  text = text
    .replace("import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';", "import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';")
    .replace("import useAuthStore from './store/authStore';", authStub)
    .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
    .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
    .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
    .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['admin'];")
    .replace("import { postLoginDestination } from './services/navigationService.js';", `import { postLoginDestination } from ${JSON.stringify(sourceUrl('services', 'navigationService.js'))};`)
    .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
    .replace("import useNotificationStore from './stores/notificationStore.js';", 'const useNotificationStore = { getState: () => ({ reset: () => {} }) };')
    .replace("import RoleGuard from './components/guards/RoleGuard';", 'const RoleGuard = ({ children }) => children;')
    .replace('<BrowserRouter>', '<MemoryRouter initialEntries={globalThis.__ui6RouterEntries}>')
    .replace('</BrowserRouter>', '</MemoryRouter>');
  text = text.replace(/^const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\([^\n]+\)\);$/gm, 'const $1 = () => <output data-ui6-route="$1">$1</output>;');
  text = text.replace('function App() {', 'function LocationProbe() { const location = useLocation(); return <output data-ui6-location>{location.pathname + location.search}</output>; }\n\nfunction App() {');
  text = text.replace('</Routes>', '</Routes><LocationProbe />');
  return text;
})).default;

function h(type, props, ...children) { return React.createElement(type, props, ...children); }
function LocationProbe() {
  const location = useLocation();
  return h('output', { 'data-ui6-location': true }, `${location.pathname}${location.search}`);
}
function LocationStateProbe() {
  const currentLocation = useLocation();
  return h('output', { 'data-ui6-location-state': true }, JSON.stringify(currentLocation.state));
}

async function render(Component, initialEntries = ['/']) {
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => {
    root.render(h(
      MemoryRouter,
      { initialEntries },
      h(Routes, null, h(Route, { path: '*', element: h(Component) })),
      h(LocationProbe),
    ));
    await Promise.resolve();
  });
  return root;
}

async function renderRegistrationFlow(initialEntries = ['/register']) {
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => {
    root.render(h(
      MemoryRouter,
      { initialEntries },
      h(Routes, null,
        h(Route, { path: '/register', element: h(Register) }),
        h(Route, { path: '/verify-email', element: h(VerifyEmail) }),
      ),
      h(LocationProbe),
      h(LocationStateProbe),
    ));
    await Promise.resolve();
  });
  return root;
}

async function renderRouter(entry, auth) {
  globalThis.__ui6RouterEntries = [entry];
  globalThis.__ui6RouterAuth = auth;
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => {
    root.render(h(AuthRouter));
    await Promise.resolve();
  });
  return root;
}

async function unmount(root) {
  if (root) await act(async () => { root.unmount(); });
  document.body.innerHTML = '';
}

const delay = () => new Promise((resolve) => setTimeout(resolve, 0));
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await delay();
  });
}
async function waitFor(check, label) {
  let latest;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const result = check();
      if (result) return result;
    } catch (error) { latest = error; }
    await settle();
  }
  throw latest || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'an actionable DOM element exists');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await Promise.resolve();
  });
}
async function submit(form) {
  assert.ok(form, 'a form exists');
  await act(async () => {
    form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}
async function type(input, value) {
  assert.ok(input, 'an input exists');
  const ownSetter = Object.getOwnPropertyDescriptor(input, 'value')?.set;
  const prototypeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  // React tracks the element's own setter. Calling the native prototype setter first
  // leaves that tracker stale, so the dispatched input event is an actual mutation.
  (prototypeSetter && ownSetter !== prototypeSetter ? prototypeSetter : ownSetter).call(input, value);
  await act(async () => {
    input.dispatchEvent(new window.Event('input', { bubbles: true, cancelable: true }));
    input.dispatchEvent(new window.Event('change', { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}
function location() { return document.querySelector('[data-ui6-location]')?.textContent; }
function text() { return document.body.textContent.replace(/\s+/g, ' ').trim(); }
function button(label) { return [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === label); }
function anchor(destination, occurrence = 0) { return document.querySelectorAll(`a[href="${destination}"]`)[occurrence]; }
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function authState(overrides = {}) {
  const state = {
    user: null,
    error: null,
    pending2FA: null,
  };
  state.clearError = () => { state.error = null; };
  state.cancel2FA = () => { state.pending2FA = null; };
  return Object.assign(state, overrides);
}

async function populateValidRegistration(email) {
  const fields = {
    first_name: 'Ada',
    last_name: 'Lovelace',
    email,
    phone: '+12025550123',
    password: 'StrongValue42!',
    confirmPassword: 'StrongValue42!',
  };
  for (const [id, value] of Object.entries(fields)) await type(document.getElementById(id), value);
}

test('UI6 auth router renders public guest routes, redirects authenticated login/register, exposes loading, and remounts safely', { concurrency: false }, async () => {
  let root;
  try {
    root = await renderRouter('/login', { isAuthenticated: false, isLoading: false, user: null, init() {} });
    assert.equal(document.querySelector('[data-ui6-route="Login"]')?.textContent, 'Login');
    assert.equal(document.querySelector('[data-ui6-location]').textContent, '/login');
    await unmount(root);

    root = await renderRouter('/register', { isAuthenticated: false, isLoading: false, user: null, init() {} });
    assert.equal(document.querySelector('[data-ui6-route="Register"]')?.textContent, 'Register');
    await unmount(root);

    root = await renderRouter('/login?redirect=%2Fsupport', { isAuthenticated: true, isLoading: false, user: { id: 'u-1', role: 'user' }, init() {} });
    await waitFor(() => document.querySelector('[data-ui6-location]')?.textContent === '/support', 'authenticated public-route redirect');
    await unmount(root);

    root = await renderRouter('/register', { isAuthenticated: false, isLoading: true, user: null, init() {} });
    assert.equal(document.querySelector('[role="status"]')?.textContent.replace(/\s+/g, ' ').trim(), 'Loading...');
    await unmount(root);

    for (const path of ['/verify-email', '/forgot-password', '/reset-password']) {
      root = await renderRouter(path, { isAuthenticated: true, isLoading: false, user: { id: 'administrator', role: 'admin' }, init() {} });
      assert.equal(document.querySelector('[data-ui6-route]')?.getAttribute('data-ui6-route'), ({ '/verify-email': 'VerifyEmail', '/forgot-password': 'ForgotPassword', '/reset-password': 'ResetPassword' })[path]);
      await unmount(root);
    }

    // MemoryRouter remount is the permitted refresh/back equivalent for static public paths.
    root = await renderRouter('/login', { isAuthenticated: false, isLoading: false, user: null, init() {} });
    assert.equal(document.querySelector('[data-ui6-route="Login"]')?.textContent, 'Login');
  } finally {
    await unmount(root);
  }
});

test('UI6 Login binds normal and 2FA credentials to synthetic acknowledgements, shows failure, cancels challenge, and navigates via real Links', { concurrency: false }, async () => {
  const state = authState();
  const calls = [];
  let mode = 'failure';
  let pending;
  globalThis.__ui6AuthStore = () => state;
  globalThis.__ui6PostLogin = (user, search) => (user.role === 'trader' && search === '?redirect=%2Fprograms' ? '/programs' : '/user/dashboard');
  state.login = async (email, password) => {
    calls.push(['login', email, password]);
    if (mode === 'failure') {
      state.error = 'Synthetic sign-in failure';
      throw new Error('rejected');
    }
    if (mode === 'direct') return pending.promise;
    assert.equal(mode, 'challenge');
    state.pending2FA = { userId: 'auth-user-7' };
    return { requires2FA: true, userId: 'auth-user-7' };
  };
  state.login2FA = async (userId, token) => {
    calls.push(['login2FA', userId, token]);
    assert.deepEqual(state.pending2FA, { userId: 'auth-user-7' }, '2FA action is bound to its transient owner challenge');
    return { user: { id: 'auth-user-7', role: 'trader' } };
  };
  let cancelCount = 0;
  state.cancel2FA = () => { cancelCount += 1; state.pending2FA = null; };
  let root;
  try {
    root = await render(Login, ['/login?redirect=%2Fprograms']);
    assert.equal(anchor('/forgot-password')?.textContent.trim(), 'Forgot password?');
    assert.equal(anchor('/register')?.textContent.trim(), 'Sign up');
    await click(anchor('/forgot-password'));
    assert.equal(location(), '/forgot-password');
    await unmount(root);

    root = await render(Login, ['/login?redirect=%2Fprograms']);
    await type(document.getElementById('login-email'), 'trader@example.test');
    await type(document.getElementById('login-password'), 'NotARealPassword9');
    await submit(document.querySelector('form'));
    await waitFor(() => document.querySelector('[role="alert"]'), 'login rejection visible');
    assert.match(text(), /Synthetic sign-in failure/);
    assert.equal(location(), '/login?redirect=%2Fprograms', 'rejected request never navigates');

    mode = 'direct';
    pending = deferred();
    await type(document.getElementById('login-password'), 'BetterPassword9');
    await submit(document.querySelector('form'));
    assert.equal(button('Signing in...')?.disabled, true, 'pending acknowledgement exposes a loading state');
    assert.equal(location(), '/login?redirect=%2Fprograms', 'result is withheld until acknowledgement resolves');
    await act(async () => { pending.resolve({ requires2FA: false, user: { id: 'auth-user-7', role: 'trader' } }); await Promise.resolve(); });
    await waitFor(() => location() === '/programs', 'acknowledged direct login navigation');

    await unmount(root);
    state.error = null;
    mode = 'challenge';
    root = await render(Login, ['/login']);
    await type(document.getElementById('login-email'), 'trader@example.test');
    await type(document.getElementById('login-password'), 'ChallengePassword9');
    await submit(document.querySelector('form'));
    await waitFor(() => document.getElementById('two-factor-code'), '2FA challenge form');
    await type(document.getElementById('two-factor-code'), '12ab3456');
    assert.equal(document.getElementById('two-factor-code').value, '123456', 'challenge token is digit-only and bounded');
    await click(button('Back to Login'));
    await waitFor(() => document.getElementById('login-email'), 'cancel returns to initial login form');
    assert.ok(cancelCount >= 1, 'cancel handler clears the transient challenge');

    mode = 'challenge';
    await submit(document.querySelector('form'));
    await waitFor(() => document.getElementById('two-factor-code'), 'second 2FA challenge form');
    await type(document.getElementById('two-factor-code'), '987654');
    await submit(document.querySelector('form'));
    await waitFor(() => location() === '/user/dashboard', 'acknowledged 2FA navigation');
    assert.deepEqual(calls, [
      ['login', 'trader@example.test', 'NotARealPassword9'],
      ['login', 'trader@example.test', 'BetterPassword9'],
      ['login', 'trader@example.test', 'ChallengePassword9'],
      ['login', 'trader@example.test', 'ChallengePassword9'],
      ['login2FA', 'auth-user-7', '987654'],
    ]);
  } finally {
    delete globalThis.__ui6AuthStore;
    delete globalThis.__ui6PostLogin;
    await unmount(root);
  }
});

test('UI6 Register validates locally, sends canonical mutated payload only to the synthetic service, and waits for acknowledgement before navigation', { concurrency: false }, async () => {
  const state = authState();
  const calls = [];
  let mode = 'reject';
  let pending;
  state.register = async (payload) => {
    calls.push(payload);
    if (mode === 'reject') {
      state.error = 'Synthetic registration rejection';
      throw new Error('rejected');
    }
    return pending.promise;
  };
  globalThis.__ui6AuthStore = () => state;
  let root;
  try {
    root = await render(Register, ['/register?ref=REF-42']);
    await waitFor(() => document.getElementById('referral_code')?.value === 'REF-42', 'referral query hydration');
    assert.equal(anchor('/login')?.textContent.trim(), 'Sign in');
    const fields = {
      first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.test', phone: '+12025550123', password: 'StrongValue42!', confirmPassword: 'DifferentValue42!', referral_code: 'REF-42',
    };
    for (const [id, value] of Object.entries(fields)) await type(document.getElementById(id), value);
    await submit(document.querySelector('form'));
    assert.match(text(), /Passwords do not match/);
    assert.equal(calls.length, 0, 'local mismatch cannot reach the service');

    await type(document.getElementById('confirmPassword'), 'StrongValue42!');
    await submit(document.querySelector('form'));
    await waitFor(() => document.querySelector('[role="alert"]')?.textContent.includes('Synthetic registration rejection'), 'registration failure visible');
    assert.equal(location(), '/register?ref=REF-42', 'rejected registration does not navigate');

    mode = 'ack';
    pending = deferred();
    await type(document.getElementById('first_name'), 'Grace');
    await submit(document.querySelector('form'));
    assert.equal(button('Creating Account...')?.disabled, true, 'pending registration is visibly disabled');
    assert.equal(location(), '/register?ref=REF-42');
    await act(async () => { pending.resolve({ verification_email_status: 'accepted', user: { id: 'synthetic-user' } }); await Promise.resolve(); });
    await waitFor(() => location() === '/verify-email', 'acknowledged registration route');
    assert.deepEqual(calls, [
      { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.test', phone: '+12025550123', password: 'StrongValue42!', country_code: 'US', referral_code: 'REF-42' },
      { first_name: 'Grace', last_name: 'Lovelace', email: 'ada@example.test', phone: '+12025550123', password: 'StrongValue42!', country_code: 'US', referral_code: 'REF-42' },
    ], 'confirmPassword is never sent and the displayed mutation is the canonical service payload');
  } finally {
    delete globalThis.__ui6AuthStore;
    await unmount(root);
  }
});

test('UI6 Register carries live Axios 201 accepted and 202 unavailable delivery states into VerifyEmail without a session', { concurrency: false }, async () => {
  const registrationCalls = [];
  const resendCalls = [];
  const toastCalls = [];
  const originalAdapter = liveApi.defaults.adapter;
  let response = { status: 201, data: { verification_email_status: 'accepted' } };
  liveApi.defaults.adapter = async (config) => {
    registrationCalls.push({
      method: config.method,
      url: config.url,
      data: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
      status: response.status,
    });
    return {
      data: response.data,
      status: response.status,
      statusText: response.status === 201 ? 'Created' : 'Accepted',
      headers: {},
      config,
      request: {},
    };
  };
  globalThis.__ui6AuthStore = () => LiveAuthStore();
  globalThis.__ui6Toast = { warning(message) { toastCalls.push(message); } };
  globalThis.__ui6Api = {
    post: async (url, payload) => {
      resendCalls.push([url, payload]);
      return { data: { acknowledgement: 'accepted' } };
    },
  };
  let root;
  try {
    LiveAuthStore.setState({ user: null, isAuthenticated: false, error: null, isLoading: false, pending2FA: null });
    root = await renderRegistrationFlow();
    await populateValidRegistration('accepted@example.test');
    await submit(document.querySelector('form'));
    await waitFor(() => location() === '/verify-email', '201 accepted registration navigation');
    assert.deepEqual(JSON.parse(document.querySelector('[data-ui6-location-state]').textContent), {
      email: 'accepted@example.test',
      emailDeliveryStatus: 'accepted',
    });
    assert.equal(document.getElementById('verify-email'), null, 'the acknowledged email is carried in navigation state');
    assert.match(text(), /accepted@example\.test/);
    assert.equal(document.querySelector('[role="status"]'), null, '201 does not render the unavailable-delivery notice');

    await unmount(root);
    response = { status: 202, data: { verification_email_status: 'unavailable' } };
    LiveAuthStore.setState({ user: null, isAuthenticated: false, error: null, isLoading: false, pending2FA: null });
    root = await renderRegistrationFlow();
    await populateValidRegistration('pending@example.test');
    await submit(document.querySelector('form'));
    await waitFor(() => location() === '/verify-email', '202 unavailable registration navigation');
    assert.deepEqual(JSON.parse(document.querySelector('[data-ui6-location-state]').textContent), {
      email: 'pending@example.test',
      emailDeliveryStatus: 'unavailable',
    });
    assert.match(document.querySelector('[role="status"]')?.textContent, /account was created, but the verification email was not accepted for delivery/i);
    assert.equal(LiveAuthStore.getState().isAuthenticated, false, 'a pending account response never creates a login session');
    assert.equal(LiveAuthStore.getState().user, null);

    await click(button('Resend verification code'));
    await waitFor(() => button('Resend code in 120s'), 'unavailable-delivery resend cooldown');
    assert.equal(button('Resend code in 120s').disabled, true, 'the full 120-second cooldown begins after acknowledgement');
    assert.deepEqual(resendCalls, [['/auth/resend-verification', { email: 'pending@example.test' }]]);
    assert.deepEqual(toastCalls, ['If the account is eligible, a verification email has been requested. If nothing arrives, try again later.']);
    assert.doesNotMatch(toastCalls[0], /\b(?:sent|delivered)\b/i, 'generic resend copy does not promise delivery');
    assert.equal(registrationCalls.some((call) => call.url.includes('/auth/login')), false, 'neither delivery status attempts login');
    assert.deepEqual(registrationCalls, [
      {
        method: 'post',
        url: '/auth/register',
        data: {
          first_name: 'Ada', last_name: 'Lovelace', email: 'accepted@example.test', phone: '+12025550123', password: 'StrongValue42!', country_code: 'US', referral_code: '',
        },
        status: 201,
      },
      {
        method: 'post',
        url: '/auth/register',
        data: {
          first_name: 'Ada', last_name: 'Lovelace', email: 'pending@example.test', phone: '+12025550123', password: 'StrongValue42!', country_code: 'US', referral_code: '',
        },
        status: 202,
      },
    ], 'both responses traverse the actual authStore registration adapter with their HTTP statuses');
  } finally {
    liveApi.defaults.adapter = originalAdapter;
    LiveAuthStore.setState({ user: null, isAuthenticated: false, error: null, isLoading: false, pending2FA: null });
    delete globalThis.__ui6AuthStore;
    delete globalThis.__ui6Toast;
    delete globalThis.__ui6Api;
    await unmount(root);
  }
});

test('UI6 Register renders a live Axios global 503 error and does not navigate to verification', { concurrency: false }, async () => {
  const requests = [];
  const originalAdapter = liveApi.defaults.adapter;
  liveApi.defaults.adapter = async (config) => {
    requests.push({ method: config.method, url: config.url });
    const error = new Error('Request failed with status code 503');
    error.config = config;
    error.response = {
      data: { error: 'Registration is temporarily unavailable. Please try again later.' },
      status: 503,
      statusText: 'Service Unavailable',
      headers: {},
      config,
    };
    error.isAxiosError = true;
    throw error;
  };
  globalThis.__ui6AuthStore = () => LiveAuthStore();
  let root;
  try {
    LiveAuthStore.setState({ user: null, isAuthenticated: false, error: null, isLoading: false, pending2FA: null });
    root = await render(Register, ['/register']);
    await populateValidRegistration('outage@example.test');
    await submit(document.querySelector('form'));
    await waitFor(() => document.querySelector('[role="alert"]'), '503 registration alert');
    assert.match(document.querySelector('[role="alert"]').textContent, /Registration is temporarily unavailable\. Please try again later\./);
    assert.equal(location(), '/register', 'a global service failure never advances to email verification');
    assert.equal(document.querySelector('[data-ui6-location-state]'), null);
    assert.deepEqual(requests, [{ method: 'post', url: '/auth/register' }]);
  } finally {
    liveApi.defaults.adapter = originalAdapter;
    delete globalThis.__ui6AuthStore;
    await unmount(root);
    LiveAuthStore.setState({ error: null, isLoading: false });
  }
});

test('UI6 VerifyEmail binds six-digit verification and resend requests to a narrowed synthetic API, with response-only success and anti-enumerating cooldown', { concurrency: false }, async () => {
  const calls = [];
  const toastCalls = [];
  let verifyMode = 'reject';
  let pending;
  globalThis.__ui6Toast = { warning(message) { toastCalls.push(message); } };
  globalThis.__ui6Api = {
    post: async (url, payload) => {
      calls.push([url, payload]);
      if (url === '/auth/verify-email') {
        if (verifyMode === 'reject') throw Object.assign(new Error('rejected'), { response: { data: { error: 'Synthetic verification rejection' } } });
        return pending.promise;
      }
      assert.equal(url, '/auth/resend-verification');
      return { data: { acknowledgement: 'accepted' } };
    },
  };
  let root;
  try {
    root = await render(VerifyEmail, ['/verify-email']);
    await type(document.getElementById('verify-email'), 'verify@example.test');
    await type(document.getElementById('verification-code'), 'ab12x3456');
    assert.equal(document.getElementById('verification-code').value, '123456');
    await submit(document.querySelector('form'));
    await waitFor(() => document.querySelector('[role="alert"]'), 'verification rejection visible');
    assert.match(text(), /Synthetic verification rejection/);

    verifyMode = 'ack';
    pending = deferred();
    await type(document.getElementById('verification-code'), '654321');
    await submit(document.querySelector('form'));
    await waitFor(() => button('Verifying…'), 'verification loading state');
    assert.equal(button('Verifying…').disabled, true);
    assert.doesNotMatch(text(), /Email verified/, 'success must not render before the synthetic acknowledgement');
    await act(async () => { pending.resolve({ data: { acknowledgement: 'accepted' } }); await Promise.resolve(); });
    await waitFor(() => text().includes('Email verified'), 'verification acknowledgement result');
    assert.deepEqual(calls.slice(0, 2), [
      ['/auth/verify-email', { email: 'verify@example.test', code: '123456' }],
      ['/auth/verify-email', { email: 'verify@example.test', code: '654321' }],
    ]);
    await unmount(root);

    root = await render(VerifyEmail, [{ pathname: '/verify-email', state: { email: 'known@example.test' } }]);
    assert.equal(document.getElementById('verify-email'), null, 'route state binds the known email without a duplicate editable email field');
    await click(button('Resend verification code'));
    await waitFor(() => text().includes('Resend code in 120s'), 'resend cooldown acknowledgement');
    assert.deepEqual(calls.at(-1), ['/auth/resend-verification', { email: 'known@example.test' }]);
    assert.deepEqual(toastCalls, ['If the account is eligible, a verification email has been requested. If nothing arrives, try again later.']);
    assert.equal(anchor('/login')?.getAttribute('href'), '/login');

    await unmount(root);
    root = await render(VerifyEmail, ['/verify-email?email=prefill%40example.test']);
    assert.equal(document.getElementById('verify-email'), null, 'a valid query email is prefilled rather than duplicated as an editable field');
    assert.match(text(), /prefill@example\.test/);
    await type(document.getElementById('verification-code'), 'x112233');
    assert.equal(document.getElementById('verification-code').value, '112233');
    await submit(document.querySelector('form'));
    await waitFor(() => text().includes('Email verified'), 'query-prefilled verification acknowledgement');
    assert.deepEqual(calls.at(-1), ['/auth/verify-email', { email: 'prefill@example.test', code: '112233' }]);
  } finally {
    delete globalThis.__ui6Api;
    delete globalThis.__ui6Toast;
    await unmount(root);
  }
});

test('UI6 ForgotPassword submits the canonical email to synthetic acknowledgement, retains neutral result semantics, renders failure, and keeps both login Links', { concurrency: false }, async () => {
  const calls = [];
  let mode = 'reject';
  let pending;
  globalThis.__ui6Api = {
    post: async (url, payload) => {
      calls.push([url, payload]);
      assert.equal(url, '/auth/password/reset-request');
      if (mode === 'reject') throw Object.assign(new Error('rejected'), { response: { data: { error: 'Synthetic reset request rejection' } } });
      return pending.promise;
    },
  };
  let root;
  try {
    root = await render(ForgotPassword, ['/forgot-password']);
    assert.equal(document.querySelectorAll('a[href="/login"]').length, 2, 'each recorded login Link is a real DOM anchor');
    await type(document.getElementById('reset-email'), 'forgot@example.test');
    await submit(document.querySelector('form'));
    await waitFor(() => document.querySelector('[role="alert"]'), 'forgot-password failure visible');
    assert.match(text(), /Synthetic reset request rejection/);

    mode = 'ack';
    pending = deferred();
    await type(document.getElementById('reset-email'), 'neutral@example.test');
    await submit(document.querySelector('form'));
    await waitFor(() => button('Sending Code...'), 'forgot-password loading state');
    assert.equal(button('Sending Code...').disabled, true);
    assert.doesNotMatch(text(), /Check Your Email/, 'request outcome is withheld until acknowledgement');
    await act(async () => { pending.resolve({ data: { acknowledgement: 'accepted' } }); await Promise.resolve(); });
    await waitFor(() => document.querySelector('[role="status"]'), 'neutral reset-request result');
    assert.match(text(), /If an account exists for neutral@example\.test/);
    assert.match(text(), /If eligible, use the code on the next page/);
    assert.doesNotMatch(text(), /password reset email (?:was|has been) (?:sent|delivered)/i, 'the reset acknowledgement remains conditional rather than claiming delivery');
    assert.deepEqual(calls, [
      ['/auth/password/reset-request', { email: 'forgot@example.test' }],
      ['/auth/password/reset-request', { email: 'neutral@example.test' }],
    ]);
  } finally {
    delete globalThis.__ui6Api;
    await unmount(root);
  }
});

test('UI6 ResetPassword validates before transport, binds canonical reset payload to synthetic acknowledgement, exposes transport failure, and renders its login Link', { concurrency: false }, async () => {
  const calls = [];
  let mode = 'reject';
  let pending;
  globalThis.__ui6Api = {
    post: async (url, payload) => {
      calls.push([url, payload]);
      assert.equal(url, '/auth/password/reset-with-code');
      if (mode === 'reject') throw Object.assign(new Error('rejected'), { response: { data: { error: 'Synthetic password reset rejection' } } });
      return pending.promise;
    },
  };
  let root;
  try {
    root = await render(ResetPassword, ['/reset-password']);
    assert.equal(anchor('/login')?.getAttribute('href'), '/login');
    await type(document.getElementById('reset-password-email'), 'reset@example.test');
    await type(document.getElementById('reset-password-code'), 'x123456');
    assert.equal(document.getElementById('reset-password-code').value, '123456');
    await type(document.getElementById('new-password'), 'StrongValue42!');
    await type(document.getElementById('confirm-new-password'), 'DifferentValue42!');
    await submit(document.querySelector('form'));
    assert.match(text(), /Passwords do not match/);
    assert.equal(calls.length, 0, 'local password mismatch cannot reach transport');

    await unmount(root);
    root = await render(ResetPassword, ['/reset-password']);
    await type(document.getElementById('reset-password-email'), 'reset@example.test');
    await type(document.getElementById('reset-password-code'), '123456');
    await type(document.getElementById('new-password'), 'StrongValue42!');
    await type(document.getElementById('confirm-new-password'), 'StrongValue42!');
    await submit(document.querySelector('form'));
    await waitFor(() => document.querySelector('[role="alert"]')?.textContent.includes('Synthetic password reset rejection'), 'reset rejection visible');
    assert.equal(calls.length, 1);

    mode = 'ack';
    pending = deferred();
    await type(document.getElementById('new-password'), 'UpdatedValue42!');
    await type(document.getElementById('confirm-new-password'), 'UpdatedValue42!');
    await submit(document.querySelector('form'));
    assert.equal(button('Resetting Password...')?.disabled, true);
    assert.doesNotMatch(text(), /Password Reset Successfully/, 'success waits for acknowledgement');
    await act(async () => { pending.resolve({ data: { acknowledgement: 'accepted' } }); await Promise.resolve(); });
    await waitFor(() => document.querySelector('[role="status"]'), 'reset acknowledgement result');
    assert.equal(text().includes('Password Reset Successfully!'), true);
    assert.deepEqual(calls, [
      ['/auth/password/reset-with-code', { email: 'reset@example.test', code: '123456', new_password: 'StrongValue42!' }],
      ['/auth/password/reset-with-code', { email: 'reset@example.test', code: '123456', new_password: 'UpdatedValue42!' }],
    ]);
  } finally {
    delete globalThis.__ui6Api;
    await unmount(root);
  }
});
