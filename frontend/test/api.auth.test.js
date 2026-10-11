import assert from 'node:assert/strict';
import test from 'node:test';

// api.js reads these browser globals only when an interceptor runs. Defining them
// here keeps the same-origin helper deterministic under Node's built-in test runner.
globalThis.window = {
  location: {
    origin: 'https://app.marketedgepros.test',
    pathname: '/login',
  },
};

const {
  isCompleteRefreshResponse,
  isSameOriginRequest,
  shouldAttachCsrfToken,
} = await import('../src/services/api.js');

test('same-origin CSRF helper accepts only unsafe same-origin API requests', () => {
  const csrfToken = 'csrf-test-token';

  assert.equal(
    shouldAttachCsrfToken({ method: 'post', url: '/auth/login', baseURL: '/api/v1' }, csrfToken),
    true,
  );
  assert.equal(
    shouldAttachCsrfToken({ method: 'get', url: '/profile', baseURL: '/api/v1' }, csrfToken),
    false,
  );
  assert.equal(
    shouldAttachCsrfToken(
      { method: 'delete', url: 'https://attacker.example/collect', baseURL: '/api/v1' },
      csrfToken,
    ),
    false,
  );
  assert.equal(
    isSameOriginRequest('https://app.marketedgepros.test/api/v1/profile', '/api/v1'),
    true,
  );
  assert.equal(
    isSameOriginRequest('//attacker.example/collect', '/api/v1'),
    false,
  );
});

test('refresh responses must rotate access, refresh, and CSRF tokens together', () => {
  assert.equal(
    isCompleteRefreshResponse({
      access_token: 'new-access',
      refresh_token: 'new-refresh',
      csrf_token: 'new-csrf',
    }),
    true,
  );
  assert.equal(
    isCompleteRefreshResponse({
      access_token: 'new-access',
      refresh_token: 'new-refresh',
    }),
    false,
  );
  assert.equal(isCompleteRefreshResponse('<html>not JSON</html>'), false);
});
