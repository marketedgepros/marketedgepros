import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createProfileApiTransport,
  createProfileViewService,
  ProfileContractError,
} from '../src/services/profileViewService.js';

const principal = { id: 41, tenantId: 7, role: 'trader', key: 'principal-41' };

const fullUser = (overrides = {}) => ({
  id: 41,
  email: 'trader@example.test',
  first_name: 'Ada',
  last_name: 'Lovelace',
  phone: '+12025550123',
  country_code: 'US',
  is_active: true,
  is_verified: false,
  two_factor_enabled: false,
  kyc_status: 'pending',
  role: 'trader',
  tenant_id: 7,
  avatar_url: null,
  created_at: '2026-01-01T00:00:00',
  last_login_at: null,
  ...overrides,
});

const response = (user, extras = {}) => ({ data: { message: 'Completed.', user, ...extras } });

test('profile service uses exact endpoint paths, allowed personal payload, and abort signal', async () => {
  const calls = [];
  const transport = {
    request: async (request) => {
      calls.push(request);
      return response(fullUser());
    },
  };
  const service = createProfileViewService(transport);
  const controller = new AbortController();

  const fetched = await service.getProfile(principal, controller.signal);
  const updated = await service.updateProfile({
    first_name: ' Ada ',
    last_name: ' Byron ',
    phone: ' +12025550124 ',
    email: 'must-not-be-sent@example.test',
    role: 'admin',
    tenant_id: 999,
  }, principal, controller.signal);

  assert.equal(fetched.user.id, 41);
  assert.deepEqual(updated.payload, {
    first_name: 'Ada',
    last_name: 'Byron',
    phone: '+12025550124',
  });
  assert.deepEqual(calls, [
    { method: 'GET', path: '/profile', signal: controller.signal },
    {
      method: 'PUT',
      path: '/profile',
      data: { first_name: 'Ada', last_name: 'Byron', phone: '+12025550124' },
      signal: controller.signal,
    },
  ]);
});

test('an abort signal rejects an unresolved old request before it can report success', async () => {
  let resolveRequest;
  const service = createProfileViewService({
    request: () => new Promise((resolve) => { resolveRequest = resolve; }),
  });
  const controller = new AbortController();
  const pending = service.getProfile(principal, controller.signal);

  controller.abort();
  await assert.rejects(pending, (error) => error?.name === 'AbortError');
  // Resolving the underlying legacy API promise afterwards must have no visible
  // service success result for the cancelled caller.
  resolveRequest(response(fullUser()));
});

test('avatar and password operations use their established paths and typed success contracts', async () => {
  const calls = [];
  const avatar = { name: 'avatar.PNG', type: 'image/png', size: 5 * 1024 * 1024 };
  const transport = {
    request: async (request) => {
      calls.push(request);
      if (request.path === '/profile/avatar' && request.method === 'POST') {
        const avatarUrl = 'https://marketedgepros-storage.ams3.cdn.digitaloceanspaces.com/profiles/41/avatar.png';
        return response(fullUser({ avatar_url: avatarUrl }), { avatar_url: avatarUrl });
      }
      if (request.path === '/profile/avatar') return response(fullUser({ avatar_url: null }));
      if (request.path === '/profile/password') return { data: { message: 'Password changed successfully' } };
      throw new Error('Unexpected request');
    },
  };
  const service = createProfileViewService(transport);
  const controller = new AbortController();

  const uploaded = await service.uploadAvatar(avatar, principal, controller.signal);
  const deleted = await service.deleteAvatar(principal, controller.signal);
  const password = await service.changePassword({ current_password: 'OldPass1!', new_password: 'NewPass1!' }, controller.signal);

  assert.match(uploaded.avatarUrl, /digitaloceanspaces\.com\/profiles\/41/);
  assert.equal(deleted.user.avatar_url, null);
  assert.deepEqual(password.payload, { current_password: 'OldPass1!', new_password: 'NewPass1!' });
  assert.deepEqual(calls.map(({ method, path, data, signal }) => ({ method, path, data, signal })), [
    { method: 'POST', path: '/profile/avatar', data: avatar, signal: controller.signal },
    { method: 'DELETE', path: '/profile/avatar', data: undefined, signal: controller.signal },
    {
      method: 'PUT',
      path: '/profile/password',
      data: { current_password: 'OldPass1!', new_password: 'NewPass1!' },
      signal: controller.signal,
    },
  ]);
});

test('malformed, cross-tenant, and unsafe avatar responses reject instead of reporting success', async () => {
  const service = createProfileViewService({
    request: async (request) => {
      if (request.path === '/profile') return response({ ...fullUser(), tenant_id: 8 });
      if (request.path === '/profile/avatar') {
        return response(fullUser({ avatar_url: 'https://attacker.example/collect.png' }), {
          avatar_url: 'https://attacker.example/collect.png',
        });
      }
      return { data: { message: 'Completed.' } };
    },
  });

  await assert.rejects(service.getProfile(principal), ProfileContractError);
  await assert.rejects(
    service.uploadAvatar({ name: 'avatar.jpg', type: 'image/jpeg', size: 1 }, principal),
    /unsafe avatar URL/i,
  );

  const incompleteService = createProfileViewService({
    request: async () => response(Object.fromEntries(Object.entries(fullUser()).filter(([key]) => key !== 'role'))),
  });
  await assert.rejects(incompleteService.updateProfile({}, principal), /incomplete user: role/i);
});

test('shared profileAPI adapter preserves existing update/upload/delete/password method ownership', async () => {
  const calls = [];
  const api = {
    get: async (options) => { calls.push(['get', options]); return response(fullUser()); },
    update: async (payload, options) => { calls.push(['update', payload, options]); return response(fullUser()); },
    uploadAvatar: async (file, options) => { calls.push(['uploadAvatar', file, options]); return response(fullUser({ avatar_url: null })); },
    deleteAvatar: async (options) => { calls.push(['deleteAvatar', options]); return response(fullUser()); },
    changePassword: async (payload, options) => { calls.push(['changePassword', payload, options]); return { data: { message: 'done' } }; },
  };
  const transport = createProfileApiTransport(api);
  const signal = new AbortController().signal;

  await transport.request({ method: 'GET', path: '/profile', signal });
  await transport.request({ method: 'PUT', path: '/profile', data: { first_name: 'Ada' }, signal });
  await transport.request({ method: 'POST', path: '/profile/avatar', data: 'file', signal });
  await transport.request({ method: 'DELETE', path: '/profile/avatar', signal });
  await transport.request({ method: 'PUT', path: '/profile/password', data: { new_password: 'x' }, signal });

  assert.deepEqual(calls, [
    ['get', { signal }],
    ['update', { first_name: 'Ada' }, { signal }],
    ['uploadAvatar', 'file', { signal }],
    ['deleteAvatar', { signal }],
    ['changePassword', { new_password: 'x' }, { signal }],
  ]);
});
