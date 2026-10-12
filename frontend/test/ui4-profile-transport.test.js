import assert from 'node:assert/strict';
import test from 'node:test';
import { File } from 'node:buffer';
import api, { profileAPI } from '../src/services/api.js';
import { createProfileApiTransport, createProfileViewService, profilePrincipalFromUser, validateAvatarFile } from '../src/services/profileViewService.js';

const user = { id: 1, tenant_id: null, role: 'guest', email: 'synthetic@example.invalid', first_name: 'Synthetic', last_name: 'User', phone: null, country_code: null, is_active: true, is_verified: false, two_factor_enabled: false, kyc_status: null, avatar_url: null, created_at: null, last_login_at: null };

test('profile explicit null tenant preserves existing GET/PUT contract but absent tenant is not guessed', async () => {
  const principal = profilePrincipalFromUser(user, true);
  assert.equal(principal.tenantId, null);
  assert.equal(profilePrincipalFromUser({ id: 1, role: 'guest' }, true), null);
  const service = createProfileViewService({ request: async () => ({ data: { user } }) });
  assert.equal((await service.getProfile(principal)).user.tenant_id, null);
  assert.equal(validateAvatarFile({ name: 'empty.png', type: 'image/png', size: 0 }).valid, false);
});

test('profile real Axios adapter receives AbortSignal and browser multipart boundaries for all five operations', async () => {
  const old = api.defaults.adapter;
  const calls = [];
  const ctrl = new AbortController();
  api.defaults.adapter = async (config) => {
    calls.push(config);
    return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
  };
  try {
    const transport = createProfileApiTransport(profileAPI);
    await transport.request({ method: 'GET', path: '/profile', signal: ctrl.signal });
    await transport.request({ method: 'PUT', path: '/profile', data: { first_name: 'Synthetic' }, signal: ctrl.signal });
    await transport.request({ method: 'POST', path: '/profile/avatar', data: new File(['synthetic'], 'avatar.png', { type: 'image/png' }), signal: ctrl.signal });
    await transport.request({ method: 'DELETE', path: '/profile/avatar', signal: ctrl.signal });
    await transport.request({ method: 'PUT', path: '/profile/password', data: { current_password: 'synthetic', new_password: 'synthetic-2' }, signal: ctrl.signal });
    assert.equal(calls.length, 5);
    assert.equal(calls[4]._skipAuthRefresh, true, 'wrong current-password 401 must not auto-refresh/retry a sensitive mutation');
    assert.ok(calls.every((c) => c.signal === ctrl.signal && c.withCredentials === true));
    assert.deepEqual(calls.map((c) => api.getUri(c)), ['/api/v1/profile', '/api/v1/profile', '/api/v1/profile/avatar', '/api/v1/profile/avatar', '/api/v1/profile/password']);
    assert.ok(calls[2].data instanceof FormData);
    assert.notEqual(calls[2].headers.get('Content-Type'), 'application/json');
    assert.notEqual(calls[2].headers.get('Content-Type'), 'multipart/form-data');
  } finally {
    api.defaults.adapter = old;
  }
});


test('password logout contract rejects queued/error/empty success messages before caller navigation', async () => {
  for (const message of ['queued', 'Completed.', 'Password change failed', '', null]) {
    const service = createProfileViewService({ request: async () => ({ data: { message } }) });
    await assert.rejects(service.changePassword({ current_password: 'synthetic', new_password: 'synthetic-2' }), /did not confirm/);
  }
  const service = createProfileViewService({ request: async () => ({ data: { message: 'Password changed successfully' } }) });
  assert.equal((await service.changePassword({ current_password: 'synthetic', new_password: 'synthetic-2' })).data.message, 'Password changed successfully');
});
