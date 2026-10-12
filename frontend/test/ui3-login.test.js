import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/pages/Login.jsx', import.meta.url), 'utf8');

test('login does not offer a nonfunctional remember preference', () => {
  assert.doesNotMatch(source, /Remember me/);
  assert.match(source, /to="\/forgot-password"/);
});

test('2FA code instruction is programmatically associated with its field', () => {
  assert.match(source, /<label htmlFor="two-factor-code"[\s\S]*?Enter the 6-digit code from your authenticator app/);
  assert.match(source, /<input\s+id="two-factor-code"[\s\S]*?autoComplete="one-time-code"/);
});

test('login keeps authStore as error source and preserves role-aware local navigation', () => {
  assert.match(source, /catch\s*\{\s*\/\/ authStore owns login errors/);
  assert.match(source, /navigate\(postLoginDestination\(result\.user, location\.search\), \{ replace: true \}\)/);
  assert.match(source, /login\(formData\.email, formData\.password\)/);
});
