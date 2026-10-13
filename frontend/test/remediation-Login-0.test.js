import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test, { afterEach } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { transformWithEsbuild } from 'vite';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const pnpmDirectory = path.join(frontendDirectory, 'node_modules', '.pnpm');
const jsdomPackage = fs.readdirSync(pnpmDirectory).find((entry) => entry.startsWith('jsdom@'));

if (!jsdomPackage) throw new Error('The existing jsdom test dependency is unavailable.');

const { JSDOM } = await import(pathToFileURL(path.join(pnpmDirectory, jsdomPackage, 'node_modules', 'jsdom', 'lib', 'api.js')).href);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://app.marketedgepros.test/login' });

Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  localStorage: dom.window.localStorage,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });

const { createRoot } = await import('react-dom/client');
const { authAPI } = await import('../src/services/api.js');
const { default: useAuthStore } = await import('../src/store/authStore.js');

const originalAuthAPI = {
  getCurrentUser: authAPI.getCurrentUser,
  login: authAPI.login,
  login2FA: authAPI.login2FA,
  logout: authAPI.logout,
};

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function authenticatedResponse(userId = 1) {
  return {
    data: {
      user: { id: userId, role: 'user' },
      access_token: `access-${userId}`,
      refresh_token: `refresh-${userId}`,
      csrf_token: `csrf-${userId}`,
    },
  };
}

function resetAuthStore() {
  const state = useAuthStore.getState();
  state.clear2FAPending();
  state.clearAuthenticatedSession();
  useAuthStore.setState({ error: null, isLoading: false });
  localStorage.clear();
}

afterEach(() => {
  Object.assign(authAPI, originalAuthAPI);
  resetAuthStore();
  document.body.innerHTML = '';
  delete globalThis.__remediationAuthState;
  delete globalThis.__remediationNavigations;
});

test('Login:0 preserves the normal login and two-factor success flow', async () => {
  let twoFactorPayload;
  authAPI.login = async () => ({
    data: { requires_2fa: true, user_id: 17, challenge_token: 'challenge-17' },
  });
  authAPI.login2FA = async (payload) => {
    twoFactorPayload = payload;
    return authenticatedResponse(17);
  };

  const challenge = await useAuthStore.getState().login('trader@example.test', 'Password1');
  assert.deepEqual(challenge, {
    requires2FA: true,
    userId: 17,
    challengeToken: 'challenge-17',
  });

  const result = await useAuthStore.getState().login2FA(17, '123456');
  assert.deepEqual(twoFactorPayload, {
    user_id: 17,
    token: '123456',
    challenge_token: 'challenge-17',
  });
  assert.deepEqual(result, { success: true, user: { id: 17, role: 'user' } });
  assert.equal(useAuthStore.getState().isAuthenticated, true);
  assert.equal(localStorage.getItem('access_token'), 'access-17');
});

test('Login:0 ignores a deferred 2FA success after Back to Login cancels the challenge', async () => {
  const request = deferred();
  authAPI.login2FA = () => request.promise;

  useAuthStore.getState().start2FAPending(41, 'old-challenge');
  const verification = useAuthStore.getState().login2FA(41, '123456');
  useAuthStore.getState().cancel2FA();
  request.resolve(authenticatedResponse(41));

  assert.deepEqual(await verification, { stale: true });
  assert.equal(useAuthStore.getState().pending2FA, null);
  assert.equal(useAuthStore.getState().isAuthenticated, false);
  assert.equal(useAuthStore.getState().error, null);
  assert.equal(localStorage.getItem('access_token'), null);
});

test('Login:0 keeps the newer challenge when an older login response resolves later', async () => {
  const oldRequest = deferred();
  const newRequest = deferred();
  let requests = 0;
  authAPI.login = () => (++requests === 1 ? oldRequest.promise : newRequest.promise);

  const oldLogin = useAuthStore.getState().login('old@example.test', 'Password1');
  const newLogin = useAuthStore.getState().login('new@example.test', 'Password2');
  newRequest.resolve({
    data: { requires_2fa: true, user_id: 22, challenge_token: 'new-challenge' },
  });

  assert.deepEqual(await newLogin, {
    requires2FA: true,
    userId: 22,
    challengeToken: 'new-challenge',
  });

  oldRequest.resolve(authenticatedResponse(11));
  assert.deepEqual(await oldLogin, { stale: true });
  assert.deepEqual(useAuthStore.getState().pending2FA, {
    userId: 22,
    challengeToken: 'new-challenge',
  });
  assert.equal(useAuthStore.getState().isAuthenticated, false);
  assert.equal(localStorage.getItem('access_token'), null);
});

test('Login:0 ignores a deferred login error after cancellation', async () => {
  const request = deferred();
  authAPI.login = () => request.promise;

  const login = useAuthStore.getState().login('cancelled@example.test', 'Password1');
  useAuthStore.getState().cancel2FA();
  request.reject({ response: { data: { error: 'This old error must not appear.' } } });

  assert.deepEqual(await login, { stale: true });
  assert.equal(useAuthStore.getState().error, null);
  assert.equal(useAuthStore.getState().pending2FA, null);
});

test('Login:0 ignores a deferred 2FA error after a newer login creates its own challenge', async () => {
  const oldVerification = deferred();
  authAPI.login2FA = () => oldVerification.promise;
  authAPI.login = async () => ({
    data: { requires_2fa: true, user_id: 73, challenge_token: 'newer-challenge' },
  });

  useAuthStore.getState().start2FAPending(72, 'older-challenge');
  const verification = useAuthStore.getState().login2FA(72, '123456');
  const newerLogin = await useAuthStore.getState().login('newer@example.test', 'Password1');
  oldVerification.reject({ response: { data: { error: 'This old error must not appear.' } } });

  assert.deepEqual(await verification, { stale: true });
  assert.deepEqual(newerLogin, {
    requires2FA: true,
    userId: 73,
    challengeToken: 'newer-challenge',
  });
  assert.deepEqual(useAuthStore.getState().pending2FA, {
    userId: 73,
    challengeToken: 'newer-challenge',
  });
  assert.equal(useAuthStore.getState().error, null);
});

test('Login:0 ignores late init success after logout and late init failure after a new login', async () => {
  const lateSuccess = deferred();
  authAPI.getCurrentUser = () => lateSuccess.promise;
  authAPI.logout = async () => {};
  localStorage.setItem('access_token', 'session-hint');

  const initialisation = useAuthStore.getState().init();
  await useAuthStore.getState().logout();
  lateSuccess.resolve({ data: { user: { id: 'old-user', role: 'user' } } });

  assert.deepEqual(await initialisation, { stale: true });
  assert.equal(useAuthStore.getState().isAuthenticated, false);
  assert.equal(useAuthStore.getState().user, null);

  const lateFailure = deferred();
  authAPI.getCurrentUser = () => lateFailure.promise;
  authAPI.login = async () => ({
    data: { requires_2fa: true, user_id: 91, challenge_token: 'current-challenge' },
  });
  localStorage.setItem('access_token', 'second-session-hint');

  const secondInitialisation = useAuthStore.getState().init();
  const currentLogin = await useAuthStore.getState().login('current@example.test', 'Password1');
  lateFailure.reject({ response: { data: { error: 'This old init error must not appear.' } } });

  assert.deepEqual(await secondInitialisation, { stale: true });
  assert.deepEqual(currentLogin, {
    requires2FA: true,
    userId: 91,
    challengeToken: 'current-challenge',
  });
  assert.deepEqual(useAuthStore.getState().pending2FA, {
    userId: 91,
    challengeToken: 'current-challenge',
  });
  assert.equal(useAuthStore.getState().error, null);
});

async function loadLoginWithControlledAuth() {
  const sourcePath = path.join(frontendDirectory, 'src', 'pages', 'Login.jsx');
  let source = fs.readFileSync(sourcePath, 'utf8');
  const replacements = [
    ["import { postLoginDestination } from '../services/navigationService.js';", "const postLoginDestination = () => '/dashboard';"],
    ["import { useNavigate, Link, useLocation } from 'react-router-dom';", "const useNavigate = () => (destination, options) => globalThis.__remediationNavigations.push({ destination, options }); const useLocation = () => ({ search: '' }); const Link = ({ children, ...props }) => <a {...props}>{children}</a>;"],
    ["import Layout from '../components/layout/Layout';", 'const Layout = ({ children }) => <main>{children}</main>;'],
    ["import useAuthStore from '../store/authStore';", 'const useAuthStore = () => globalThis.__remediationAuthState;'],
    ["import { LogIn, Mail, Lock, AlertCircle } from 'lucide-react';", 'const Icon = (props) => <svg {...props} />; const LogIn = Icon, Mail = Icon, Lock = Icon, AlertCircle = Icon;'],
  ];

  for (const [search, replacement] of replacements) {
    assert.ok(source.includes(search), `Expected Login import not found: ${search}`);
    source = source.replace(search, replacement);
  }

  const transformed = await transformWithEsbuild(source, sourcePath, { loader: 'jsx', jsx: 'automatic' });
  const targetPath = path.join(testDirectory, `.Login-${process.pid}.remediation-login-0.mjs`);
  fs.writeFileSync(targetPath, transformed.code);
  try {
    return (await import(`${pathToFileURL(targetPath).href}?remediation-login-0=${process.pid}`)).default;
  } finally {
    fs.rmSync(targetPath, { force: true });
  }
}

test('Login:0 component never navigates when a cancelled 2FA request later resolves successfully', async () => {
  const Login = await loadLoginWithControlledAuth();
  const firstLogin = deferred();
  const verification = deferred();
  let cancelCalls = 0;
  globalThis.__remediationNavigations = [];
  globalThis.__remediationAuthState = {
    login: () => firstLogin.promise,
    login2FA: () => verification.promise,
    pending2FA: null,
    cancel2FA: () => { cancelCalls += 1; },
    error: null,
    clearError: () => {},
  };

  const root = createRoot(document.body.appendChild(document.createElement('div')));
  await act(async () => {
    root.render(React.createElement(Login));
  });

  await act(async () => {
    document.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });

  globalThis.__remediationAuthState.pending2FA = { userId: 44, challengeToken: 'challenge-44' };
  await act(async () => {
    firstLogin.resolve({ requires2FA: true, userId: 44, challengeToken: 'challenge-44' });
    await Promise.resolve();
  });

  await act(async () => {
    document.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  const backToLogin = [...document.querySelectorAll('button')]
    .find((button) => button.textContent.includes('Back to Login'));
  assert.ok(backToLogin, 'The cancel control must be rendered for the pending challenge.');

  await act(async () => {
    backToLogin.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  const signIn = [...document.querySelectorAll('button')].find((button) => button.textContent.trim() === 'Sign In');
  assert.ok(signIn, 'Cancellation returns to the password form immediately.');
  assert.equal(signIn.disabled, false, 'A canceled verification does not keep a new sign-in attempt disabled.');
  verification.resolve({ success: true, user: { id: 44, role: 'user' } });
  await act(async () => {
    await Promise.resolve();
  });

  assert.equal(cancelCalls, 1);
  assert.deepEqual(globalThis.__remediationNavigations, []);
  await act(async () => root.unmount());
});

test('Register:0, VerifyEmail:0 and ForgotPassword:0 retain their approved client-side guards', () => {
  const registerSource = fs.readFileSync(path.join(frontendDirectory, 'src', 'pages', 'Register.jsx'), 'utf8');
  const verifySource = fs.readFileSync(path.join(frontendDirectory, 'src', 'pages', 'VerifyEmail.jsx'), 'utf8');
  const forgotSource = fs.readFileSync(path.join(frontendDirectory, 'src', 'pages', 'ForgotPassword.jsx'), 'utf8');

  assert.match(registerSource, /password\.length >= 8/);
  assert.match(registerSource, /\[A-Z\]/);
  assert.match(registerSource, /\[a-z\]/);
  assert.match(registerSource, /\\d/);
  assert.match(registerSource, /special character is recommended, not required/i);
  assert.match(registerSource, /if \(!meetsPasswordPolicy\(formData\.password\)\)/);

  assert.match(verifySource, /const isValidEmail/);
  assert.match(verifySource, /disabled=\{resending \|\| resendCooldown > 0 \|\| !isValidEmail\(email\)\}/);
  assert.match(verifySource, /Enter a valid email address before requesting a new verification code\./);
  assert.match(verifySource, /Unable to process the request right now\. Please try again\./);
  assert.match(verifySource, /clearTimeout\(redirectTimerRef\.current\)/);

  assert.match(forgotSource, /clearTimeout\(redirectTimerRef\.current\)/);
  assert.match(forgotSource, /if \(!isMountedRef\.current\) return;/);
});
