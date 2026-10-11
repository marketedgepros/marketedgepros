import assert from 'node:assert/strict';
import test from 'node:test';

class MemoryStorage {
  #values = new Map();

  clear() { this.#values.clear(); }
  getItem(key) { return this.#values.has(key) ? this.#values.get(key) : null; }
  removeItem(key) { this.#values.delete(key); }
  setItem(key, value) { this.#values.set(key, String(value)); }
}

globalThis.localStorage = new MemoryStorage();
globalThis.document = {
  addEventListener() {},
  removeEventListener() {},
};
globalThis.window = {
  location: {
    origin: 'https://app.marketedgepros.test',
    pathname: '/login',
  },
};

const { authAPI } = await import('../src/services/api.js');
const { default: useAuthStore } = await import('../src/store/authStore.js');

test('2FA uses an in-memory challenge and rejects a mismatched caller user ID', async () => {
  const originalLogin = authAPI.login;
  const originalLogin2FA = authAPI.login2FA;
  let login2FAPayload;

  try {
    localStorage.setItem('user', JSON.stringify({ id: 'stale-user' }));
    localStorage.setItem('access_token', 'stale-access');
    localStorage.setItem('refresh_token', 'stale-refresh');
    localStorage.setItem('csrf_token', 'stale-csrf');

    authAPI.login = async () => ({
      data: {
        requires_2fa: true,
        user_id: 41,
        challenge_token: 'signed-password-proof',
      },
    });
    authAPI.login2FA = async (payload) => {
      login2FAPayload = payload;
      return {
        data: {
          user: { id: 41, role: 'user' },
          access_token: 'fresh-access',
          refresh_token: 'fresh-refresh',
          csrf_token: 'fresh-csrf',
        },
      };
    };

    const pendingResult = await useAuthStore.getState().login('user@example.test', 'not-a-real-password');
    assert.deepEqual(pendingResult, {
      requires2FA: true,
      userId: 41,
      challengeToken: 'signed-password-proof',
    });
    assert.deepEqual(useAuthStore.getState().pending2FA, {
      userId: 41,
      challengeToken: 'signed-password-proof',
    });
    assert.equal(localStorage.getItem('user'), null);
    assert.equal(localStorage.getItem('access_token'), null);
    assert.equal(localStorage.getItem('refresh_token'), null);
    assert.equal(localStorage.getItem('csrf_token'), null);

    const completeResult = await useAuthStore.getState().login2FA(41, '123456');
    assert.deepEqual(login2FAPayload, {
      user_id: 41,
      token: '123456',
      challenge_token: 'signed-password-proof',
    });
    assert.equal(completeResult.success, true);
    assert.equal(useAuthStore.getState().pending2FA, null);
    assert.equal(localStorage.getItem('access_token'), 'fresh-access');
    assert.equal(localStorage.getItem('refresh_token'), 'fresh-refresh');
    assert.equal(localStorage.getItem('csrf_token'), 'fresh-csrf');

    await useAuthStore.getState().login('user@example.test', 'not-a-real-password');
    await assert.rejects(
      () => useAuthStore.getState().login2FA('41', '123456'),
      /expired/,
    );
    assert.equal(login2FAPayload.user_id, 41);
    assert.equal(useAuthStore.getState().pending2FA, null);
  } finally {
    authAPI.login = originalLogin;
    authAPI.login2FA = originalLogin2FA;
    useAuthStore.getState().clear2FAPending();
    useAuthStore.getState().clearAuthenticatedSession();
    localStorage.clear();
  }
});
