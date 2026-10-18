import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { pathToFileURL, fileURLToPath } from 'node:url';
import React, { act } from 'react';
import { transformWithEsbuild } from 'vite';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const pnpmDirectory = path.join(frontendDirectory, 'node_modules', '.pnpm');
const jsdomPackage = fs.readdirSync(pnpmDirectory).find((entry) => entry.startsWith('jsdom@'));

if (!jsdomPackage) throw new Error('The existing jsdom test dependency is unavailable.');

const { JSDOM } = await import(pathToFileURL(path.join(pnpmDirectory, jsdomPackage, 'node_modules', 'jsdom', 'lib', 'api.js')).href);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });

Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });

const { createRoot } = await import('react-dom/client');
const { MemoryRouter } = await import('react-router-dom');

const iconStub = 'const Icon = (props) => <svg {...props} />;';

async function loadAuthPage(fileName, replacements) {
  const sourcePath = path.join(frontendDirectory, 'src', 'pages', fileName);
  let source = fs.readFileSync(sourcePath, 'utf8');
  for (const [search, replacement] of replacements) {
    assert.ok(source.includes(search), `Expected import not found in ${fileName}: ${search}`);
    source = source.replace(search, replacement);
  }

  const transformed = await transformWithEsbuild(source, sourcePath, { loader: 'jsx', jsx: 'automatic' });
  const targetPath = path.join(testDirectory, `.${fileName.replace('.jsx', '')}-${process.pid}.ui5-auth.mjs`);
  fs.writeFileSync(targetPath, transformed.code);
  try {
    return (await import(`${pathToFileURL(targetPath).href}?ui5-auth=${process.pid}`)).default;
  } finally {
    fs.rmSync(targetPath, { force: true });
  }
}

const [Login, Register, ResetPassword] = await Promise.all([
  loadAuthPage('Login.jsx', [
    ["import { postLoginDestination } from '../services/navigationService.js';", "const postLoginDestination = () => '/dashboard';"],
    ["import Layout from '../components/layout/Layout';", 'const Layout = ({ children }) => <main>{children}</main>;'],
    ["import useAuthStore from '../store/authStore';", "const useAuthStore = () => ({ login: async () => ({}), login2FA: async () => ({}), pending2FA: null, cancel2FA: () => {}, error: null, clearError: () => {} });"],
    ["import { LogIn, Mail, Lock, AlertCircle } from 'lucide-react';", `${iconStub} const LogIn = Icon, Mail = Icon, Lock = Icon, AlertCircle = Icon;`],
  ]),
  loadAuthPage('Register.jsx', [
    ["import Layout from '../components/layout/Layout';", 'const Layout = ({ children }) => <main>{children}</main>;'],
    ["import useAuthStore from '../store/authStore';", "const useAuthStore = () => ({ register: async () => ({}), error: null, clearError: () => {} });"],
    ["import { UserPlus, Mail, Lock, User, Phone, AlertCircle } from 'lucide-react';", `${iconStub} const UserPlus = Icon, Mail = Icon, Lock = Icon, User = Icon, Phone = Icon, AlertCircle = Icon;`],
  ]),
  loadAuthPage('ResetPassword.jsx', [
    ["import Layout from '../components/layout/Layout';", 'const Layout = ({ children }) => <main>{children}</main>;'],
    ["import { Lock, AlertCircle, CheckCircle, Eye, EyeOff, Mail } from 'lucide-react';", `${iconStub} const Lock = Icon, AlertCircle = Icon, CheckCircle = Icon, Eye = Icon, EyeOff = Icon, Mail = Icon;`],
    ['import api from "../services/api";', 'const api = { post: async () => ({}) };'],
  ]),
]);

async function renderPage(Component, entry = '/') {
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => {
    root.render(React.createElement(MemoryRouter, { initialEntries: [entry] }, React.createElement(Component)));
  });
  return root;
}

async function unmount(root) {
  await act(async () => root.unmount());
}

function labelFor(id) {
  const label = [...document.querySelectorAll('label')].find((candidate) => candidate.htmlFor === id);
  assert.ok(label, `Missing label for #${id}`);
  assert.equal(label.control, document.getElementById(id), `Label for #${id} must control the input`);
}

test('UI-5: שדות Login ו-Register מרונדרים עם labels וקיבוץ שמות שמסתגל למובייל', async () => {
  let root = await renderPage(Login, '/login');
  try {
    labelFor('login-email');
    labelFor('login-password');
    assert.equal(document.querySelector('h1')?.textContent, 'Welcome Back');
  } finally {
    await unmount(root);
  }

  root = await renderPage(Register, '/register');
  try {
    for (const id of ['first_name', 'last_name', 'email', 'phone', 'password', 'confirmPassword', 'referral_code']) {
      labelFor(id);
    }
    const nameGrid = document.getElementById('first_name').closest('.grid');
    assert.ok(nameGrid?.classList.contains('grid-cols-1'));
    assert.ok(nameGrid?.classList.contains('sm:grid-cols-2'));
    assert.equal(document.querySelector('h1')?.textContent, 'Create Account');
  } finally {
    await unmount(root);
  }
});

test('UI-5: כפתורי חשיפת הסיסמה במסך ResetPassword בעלי שם ומשנים את סוג השדה בפועל', async () => {
  const root = await renderPage(ResetPassword, '/reset-password');
  try {
    for (const id of ['reset-password-email', 'reset-password-code', 'new-password', 'confirm-new-password']) {
      labelFor(id);
    }

    const password = document.getElementById('new-password');
    const confirmation = document.getElementById('confirm-new-password');
    const showPassword = document.querySelector('button[aria-label="Show new password"]');
    const showConfirmation = document.querySelector('button[aria-label="Show confirm new password"]');

    assert.equal(password?.type, 'password');
    assert.equal(confirmation?.type, 'password');
    assert.equal(showPassword?.getAttribute('aria-controls'), 'new-password');
    assert.equal(showPassword?.getAttribute('aria-pressed'), 'false');

    await act(async () => {
      showPassword.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      showConfirmation.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    assert.equal(password?.type, 'text');
    assert.equal(confirmation?.type, 'text');
    assert.equal(document.querySelector('button[aria-label="Hide new password"]')?.getAttribute('aria-pressed'), 'true');
    assert.equal(document.querySelector('button[aria-label="Hide confirm new password"]')?.getAttribute('aria-controls'), 'confirm-new-password');
  } finally {
    await unmount(root);
  }
});
