import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const file = new URL('../src/pages/Register.jsx', import.meta.url);
let source = fs.readFileSync(file, 'utf8');
source = source
  .replace(/import Layout from ['"]\.\.\/components\/layout\/Layout['"];?/, 'const Layout = ({ children }) => <main>{children}</main>;')
  .replace(/import \{ useToast \} from ['"]\.\.\/contexts\/ToastContext['"];?/, '')
  .replace(/import \{ UserPlus, Mail, Lock, User, Phone, AlertCircle \} from ['"]lucide-react['"];?/, 'const Icon = () => null; const UserPlus = Icon, Mail = Icon, Lock = Icon, User = Icon, Phone = Icon, AlertCircle = Icon;')
  .replace(/import useAuthStore from ['"]\.\.\/store\/authStore['"];?/, 'const useAuthStore = () => ({ register: async () => ({}), error: null, clearError: () => {} });');
const transformed = await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' });
const target = new URL('../node_modules/.cache-ui3-register-test.mjs', import.meta.url);
let Register;
try {
  fs.writeFileSync(target, transformed.code);
  Register = (await import(target.href)).default;
} finally {
  fs.rmSync(target, { force: true });
}
const markup = () => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Register)));

test('register source has meaningful password mismatch feedback and no undefined toast path', () => {
  assert.match(source, /Passwords do not match\. Please enter the same password in both fields\./);
  assert.match(source, /role="alert"/);
  assert.doesNotMatch(source, /toast\.warning|useToast/);
  assert.match(markup(), /Create Account/);
});

test('all register fields are explicitly labelled and retain optional referral semantics', () => {
  const html = markup();
  for (const id of ['first_name', 'last_name', 'email', 'phone', 'password', 'confirmPassword', 'referral_code']) {
    assert.match(html, new RegExp(`<label[^>]+for="${id}"`));
    assert.match(html, new RegExp(`<input[^>]+id="${id}"`));
  }
  assert.match(html, /Referral Code \(Optional\)/);
  assert.match(source, /country_code: 'US'/); // existing backend/auth payload unchanged
});

test('registration payload excludes confirmation, preserves referral query, and navigates only after register resolves', () => {
  assert.match(source, /const \{ confirmPassword, \.\.\.registerData \} = formData/);
  assert.match(source, /register\(registerData\)/);
  assert.match(source, /searchParams\.get\('ref'\)/);
  assert.match(source, /navigate\('\/verify-email', \{ state: \{ email: formData\.email, emailDeliveryStatus \} \}\)/);
  assert.match(source, /catch \{[\s\S]*?do not navigate on failure/);
  assert.match(source, /to="\/login"/);
});
