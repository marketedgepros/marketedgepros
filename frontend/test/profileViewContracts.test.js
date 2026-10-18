import test from 'node:test';
import assert from 'node:assert/strict';
import {
  isSafeAvatarUrl,
  personalDraftFromUser,
  profilePrincipalFromUser,
  safeAvatarUrl,
  tenantIdFromUser,
  validateAvatarFile,
} from '../src/services/profileViewService.js';

const origin = 'https://app.example.test';

test('profile content principal is keyed by authenticated id, tenant and role', () => {
  const trader = { id: 1, tenant_id: 22, role: 'trader' };
  const sameTrader = { id: 1, tenant: { id: 22 }, role: 'trader' };
  const otherTenant = { id: 1, tenantId: 23, role: 'trader' };
  const otherRole = { id: 1, tenant_id: 22, role: 'affiliate' };

  const first = profilePrincipalFromUser(trader, true);
  assert.equal(tenantIdFromUser(sameTrader), 22);
  assert.equal(first.key, profilePrincipalFromUser(sameTrader, true).key);
  assert.notEqual(first.key, profilePrincipalFromUser(otherTenant, true).key);
  assert.notEqual(first.key, profilePrincipalFromUser(otherRole, true).key);
  assert.equal(profilePrincipalFromUser({ id: 1, role: 'trader' }, true), null);
  assert.equal(profilePrincipalFromUser(trader, false), null);
});

test('avatar URLs allow only canonical local profile uploads or the established DO CDN host', () => {
  const local = '/uploads/profiles/41/avatar.png';
  const cdn = 'https://marketedgepros-storage.ams3.cdn.digitaloceanspaces.com/profiles/41/avatar.webp';

  assert.equal(isSafeAvatarUrl(local, origin), true);
  assert.equal(isSafeAvatarUrl(cdn, origin), true);
  assert.equal(safeAvatarUrl(local, origin), local);
  assert.equal(isSafeAvatarUrl('/uploads/kyc/41/passport.png', origin), false);
  assert.equal(isSafeAvatarUrl('https://app.example.test/uploads/profiles/41/avatar.png', origin), false);
  assert.equal(isSafeAvatarUrl('http://marketedgepros-storage.ams3.cdn.digitaloceanspaces.com/profiles/41/avatar.png', origin), false);
  assert.equal(isSafeAvatarUrl('https://marketedgepros-storage.ams3.cdn.digitaloceanspaces.com.evil.example/profiles/41/avatar.png', origin), false);
  assert.equal(isSafeAvatarUrl('https://name:secret@marketedgepros-storage.ams3.cdn.digitaloceanspaces.com/profiles/41/avatar.png', origin), false);
  assert.equal(isSafeAvatarUrl('javascript:alert(1)', origin), false);
  assert.equal(safeAvatarUrl('https://attacker.example/avatar.png', origin), null);
});

test('avatar preflight requires matching supported MIME and extension and permits exactly 5 MiB', () => {
  assert.deepEqual(validateAvatarFile({
    name: 'avatar.jpeg', type: 'image/jpeg', size: 5 * 1024 * 1024,
  }), { valid: true });
  assert.equal(validateAvatarFile({ name: 'avatar.svg', type: 'image/svg+xml', size: 20 }).valid, false);
  assert.equal(validateAvatarFile({ name: 'avatar.png', type: 'text/plain', size: 20 }).valid, false);
  assert.equal(validateAvatarFile({ name: 'avatar.png', type: 'image/png', size: 5 * 1024 * 1024 + 1 }).valid, false);
  assert.equal(validateAvatarFile({ name: 'avatar.png', type: 'image/png', size: Number.NaN }).valid, false);
});

test('draft projection has no email, tenant, role, password, or avatar field', () => {
  assert.deepEqual(personalDraftFromUser({
    first_name: 'Ada',
    last_name: 'Lovelace',
    phone: '+12025550123',
    email: 'ada@example.test',
    tenant_id: 7,
    role: 'trader',
    avatar_url: '/uploads/profiles/1/avatar.png',
  }), {
    first_name: 'Ada',
    last_name: 'Lovelace',
    phone: '+12025550123',
  });
});
