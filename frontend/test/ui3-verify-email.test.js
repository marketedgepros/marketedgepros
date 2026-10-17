import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = fs.readFileSync(new URL('../src/pages/VerifyEmail.jsx', import.meta.url), 'utf8');

test('verify email copy does not claim a code was already sent on direct visits', () => {
  assert.match(source, /emailFromState\s*\?\s*\(/);
  assert.match(source, /Enter your email address and the 6-digit verification code to continue/);
  assert.match(source, /Enter the 6-digit verification code for/);
  assert.doesNotMatch(source, /We've sent a 6-digit verification code to/);
});

test('resend remains anti-enumerating and only describes the conditional outcome', () => {
  assert.match(source, /If the account is eligible, a verification email has been requested\. If nothing arrives, try again later\./);
  assert.match(source, /api\.post\('\/auth\/resend-verification', \{ email \}\)/);
  assert.doesNotMatch(source, /Verification code sent! Please check your email\./);
  assert.match(source, /setResendCooldown\(120\)/);
});

test('verification contract and success transition are preserved without fabricated success', () => {
  assert.match(source, /api\.post\('\/auth\/verify-email', \{ email, code \}\)/);
  assert.match(source, /setSuccess\(true\)/);
  assert.match(source, /navigate\('\/login', \{ state: \{ message: 'Email verified successfully! Please login\.' \} \}\)/);
  assert.match(source, /Your email has been successfully verified/);
});

test('form fields are explicitly labeled, keyboard-friendly, and retain six-digit validation', () => {
  assert.match(source, /htmlFor="verify-email"/);
  assert.match(source, /id="verify-email"[^>]+type="email"[^>]+autoComplete="email"/);
  assert.match(source, /htmlFor="verification-code"/);
  assert.match(source, /inputMode="numeric" autoComplete="one-time-code"/);
  assert.match(source, /disabled=\{isLoading \|\| code\.length !== 6\}/);
  assert.match(source, /role="alert"/);
  assert.match(source, /focus-visible:ring-2/);
  assert.match(source, /motion-reduce:/);
});

test('navigation remains the supported login route; no unsupported endpoints or form success were introduced', () => {
  assert.match(source, /<Link to="\/login"/);
  assert.match(source, /type="button" onClick=\{handleResend\}/);
  assert.doesNotMatch(source, /setTimeout\(\(\) =>\s*toast|api\.post\('(?:\/contact|\/newsletter|\/course)/);
});
