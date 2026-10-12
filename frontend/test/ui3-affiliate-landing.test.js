import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/pages/affiliate/AffiliateLanding.jsx', import.meta.url), 'utf8');

test('affiliate landing retains public sign-in and authorized-dashboard destinations', () => {
  assert.match(source, /navigate\(`\/login\?redirect=\$\{encodeURIComponent\('\/affiliate'\)\}`\)/);
  assert.match(source, /navigate\('\/affiliate\/dashboard'\)/);
  assert.match(source, /user\?\.role === 'affiliate'/);
});

test('registration result is not described as a commission or payout approval', () => {
  assert.match(source, /await registerAffiliate\(\)/);
  assert.match(source, /does not create a commission or confirm eligibility for a payout/);
  assert.match(source, /A link is not a commission/);
  assert.doesNotMatch(source, /Current commission rate|Minimum payout:|Cookie Duration/);
});

test('only same-origin HTTPS URL values returned by the service are rendered as links', () => {
  assert.match(source, /typeof link\.url !== 'string'/);
  assert.match(source, /parsed\.protocol !== 'https:'/);
  assert.match(source, /parsed\.origin !== base/);
  assert.ok(source.includes("link.url.startsWith('//')"));
  assert.match(source, /safeAffiliateUrl\(registration\.link\)/);
  assert.match(source, /target="_blank" rel="noreferrer"/);
});

test('inactive and unavailable program states are explicit and registration remains conditional', () => {
  assert.match(source, /programState === 'inactive' \? 'Registration unavailable'/);
  assert.match(source, /Program availability could not be confirmed/);
  assert.match(source, /programState === 'ready' && program\?\.isActive === true/);
  assert.match(source, /disabled=\{!canRegister\}/);
});
