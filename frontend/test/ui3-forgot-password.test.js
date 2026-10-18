import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../src/pages/ForgotPassword.jsx', import.meta.url), 'utf8');

test('reset request success remains neutral for anti-enumeration behavior', () => {
  assert.match(source, /If an account exists for/);
  assert.match(source, /If eligible, use the code on the next page/);
  assert.doesNotMatch(source, /We've sent a 6-digit reset code/);
  assert.doesNotMatch(source, /code has been sent to/);
});

test('page retains the supported request and reset navigation flow', () => {
  assert.match(source, /api\.post\('\/auth\/password\/reset-request', \{ email \}\)/);
  assert.match(source, /navigate\('\/reset-password', \{ state: \{ email \} \}\)/);
  assert.match(source, /to="\/login"/);
  assert.match(source, /Failed to send reset code\. Please try again\./);
});

test('email control has a programmatic label and email autofill semantics', () => {
  assert.match(source, /htmlFor="reset-email"/);
  assert.match(source, /id="reset-email"/);
  assert.match(source, /name="email"/);
  assert.match(source, /autoComplete="email"/);
  assert.match(source, /type="email"/);
});

test('success feedback is announced accessibly', () => {
  assert.match(source, /role="status" aria-live="polite"/);
});
