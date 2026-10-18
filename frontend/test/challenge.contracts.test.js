import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildChallengeListParams,
  ChallengeViewRequestGate,
  CHALLENGE_LIST_ENDPOINT,
  createChallengeViewService,
  getChallengeProgressPath,
  normaliseChallengeListResponse,
  normaliseChallengeProgressResponse,
  validateChallengeId,
} from '../src/services/challengeViewService.js';

const recordedChallenge = (overrides = {}) => ({
  id: 41,
  user_id: 9,
  program: { id: 7, name: 'Recorded Evaluation' },
  legacy_status: 'active',
  legacy_payment_status: 'paid',
  current_phase: 0,
  total_phases: 2,
  initial_balance: '0.00',
  current_balance: null,
  max_drawdown_observed: '-0.00',
  start_date: null,
  end_date: null,
  passed_at: null,
  created_at: '2026-10-11T12:00:00+00:00',
  data_status: 'unverified_legacy',
  provider_authenticated: false,
  ...overrides,
});

const recordedList = (overrides = {}) => ({
  challenges: [recordedChallenge()],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  data_status: 'unverified_legacy',
  provider_authenticated: false,
  ...overrides,
});

const recordedProgress = (overrides = {}) => ({
  challenge: recordedChallenge(),
  progress: {
    initial_balance: '0.00',
    current_balance: null,
    profit_loss: '0.00',
    profit_target_percent: null,
    profit_target_amount: null,
    profit_progress_percent: null,
    trading_days: null,
    min_trading_days: null,
    data_status: 'unverified_legacy',
    provider_authenticated: false,
  },
  mt5_account: {
    login: 'legacy-41',
    server: null,
    group: 'legacy',
    status: 'unknown',
    balance: null,
    equity: '0.00',
    margin: null,
    free_margin: null,
    margin_level: null,
    updated_at: null,
    data_status: 'unverified_legacy',
    provider_authenticated: false,
  },
  data_status: 'unverified_legacy',
  provider_authenticated: false,
  ...overrides,
});

test('challenge list service uses the canonical owner endpoint with bounded, single-value query params', async () => {
  const calls = [];
  const controller = new AbortController();
  const service = createChallengeViewService({
    get: async (...args) => {
      calls.push(args);
      return { data: recordedList({ pagination: { page: 2, per_page: 25, total: 26, pages: 2 } }) };
    },
  });

  const view = await service.getMyChallenges({ page: 2, perPage: 25, status: 'active', signal: controller.signal });

  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], CHALLENGE_LIST_ENDPOINT);
  assert.deepEqual(calls[0][1], {
    params: { page: 2, per_page: 25, status: 'active' },
    signal: controller.signal,
  });
  assert.equal(view.pagination.page, 2, 'server pagination must match the requested context');
  assert.equal(view.challenges[0].initial_balance, '0.00');
  assert.equal(view.challenges[0].current_balance, null);
  assert.equal(view.challenges[0].current_phase, 0);

  assert.deepEqual(buildChallengeListParams(), { page: 1, per_page: 20 });
  for (const invalid of [0, -1, 1.5, Number.NaN, 1001, '1']) {
    assert.throws(() => buildChallengeListParams({ page: invalid }), /Page must be an integer/i);
  }
  for (const invalid of [0, 101, 1.5, '20']) {
    assert.throws(() => buildChallengeListParams({ perPage: invalid }), /Per-page count must be an integer/i);
  }
  assert.throws(() => buildChallengeListParams({ status: '' }), /Status must be/i);
  assert.throws(() => buildChallengeListParams({ status: 'x'.repeat(21) }), /Status must be/i);
  assert.throws(() => buildChallengeListParams({ status: ['active'] }), /Status must be/i);
});

test('progress service calls only the canonical progress route and preserves nullable exact stored decimals', async () => {
  const calls = [];
  const service = createChallengeViewService({
    get: async (...args) => {
      calls.push(args);
      return { data: recordedProgress() };
    },
  });

  const view = await service.getChallengeProgress(41);

  assert.deepEqual(calls, [[
    '/challenges/41/progress',
    { signal: undefined },
  ]]);
  assert.equal(getChallengeProgressPath(41), '/challenges/41/progress');
  assert.equal(view.progress.profit_loss, '0.00');
  assert.equal(view.progress.current_balance, null);
  assert.equal(view.mt5_account.balance, null);
  assert.equal(view.mt5_account.equity, '0.00');
  assert.equal(view.challenge.provider_authenticated, false);
  assert.throws(() => validateChallengeId(0), /Challenge ID must be an integer/i);
  assert.throws(() => validateChallengeId(2147483648), /Challenge ID must be an integer/i);
  assert.throws(() => getChallengeProgressPath('41'), /Challenge ID must be an integer/i);
});

test('challenge response validation fails closed for malformed records, duplicate IDs, and mismatched detail context', () => {
  assert.throws(() => normaliseChallengeListResponse(null), /unavailable/i);
  assert.throws(
    () => normaliseChallengeListResponse(recordedList({
      challenges: [recordedChallenge(), recordedChallenge()],
      pagination: { page: 1, per_page: 20, total: 2, pages: 1 },
    })),
    /duplicate/i,
  );
  assert.throws(
    () => normaliseChallengeListResponse(recordedList({
      challenges: [recordedChallenge({ initial_balance: 0 })],
    })),
    /exact decimal/i,
  );
  assert.throws(
    () => normaliseChallengeListResponse(recordedList({
      challenges: [recordedChallenge({ program: { id: 7, name: '' } })],
    })),
    /program name is invalid/i,
  );
  assert.throws(
    () => normaliseChallengeListResponse(recordedList({
      pagination: { page: 1, per_page: 20, total: 0, pages: 1 },
    })),
    /inconsistent/i,
  );
  assert.throws(
    () => normaliseChallengeProgressResponse(recordedProgress({
      challenge: recordedChallenge({ id: 42 }),
    }), 41),
    /does not match/i,
  );
  assert.throws(
    () => normaliseChallengeProgressResponse(recordedProgress({
      mt5_account: { ...recordedProgress().mt5_account, balance: '' },
    }), 41),
    /exact decimal/i,
  );
});

test('unknown financial flags never become a verified UI context', () => {
  const view = normaliseChallengeProgressResponse(recordedProgress({
    challenge: recordedChallenge({ data_status: 'verified', provider_authenticated: true }),
    progress: { ...recordedProgress().progress, data_status: 'provider_verified', provider_authenticated: true },
    mt5_account: { ...recordedProgress().mt5_account, data_status: 'authenticated', provider_authenticated: true },
    data_status: 'approved',
    provider_authenticated: true,
  }), 41);

  assert.equal(view.data_status, 'unverified_legacy');
  assert.equal(view.provider_authenticated, false);
  assert.equal(view.challenge.data_status, 'unverified_legacy');
  assert.equal(view.progress.provider_authenticated, false);
  assert.equal(view.mt5_account.provider_authenticated, false);
});

test('service propagates adapter errors and stale request tokens cannot represent the current context', async () => {
  const adapterFailure = new Error('synthetic transport failure');
  const service = createChallengeViewService({
    get: async () => { throw adapterFailure; },
  });
  await assert.rejects(
    () => service.getMyChallenges(),
    (error) => error === adapterFailure,
  );

  const gate = new ChallengeViewRequestGate();
  const first = gate.begin({ mode: 'list', page: 1 });
  assert.equal(gate.isCurrent(first), true);
  const second = gate.begin({ mode: 'list', page: 2 });
  assert.equal(gate.isCurrent(first), false, 'the late page-one completion must be rejected');
  assert.equal(gate.isCurrent(second), true);
  gate.invalidate();
  assert.equal(gate.isCurrent(second), false, 'unmount/route cleanup invalidates the active context');
  assert.throws(() => gate.begin(null), /context is invalid/i);
});

test('real configured Axios composes canonical paths once without a duplicated api/v1 segment', async () => {
  const { default: api } = await import('../src/services/api.js');
  const previousAdapter = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config);
    return {
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
      data: config.url.endsWith('/progress') ? recordedProgress() : recordedList(),
    };
  };

  try {
    const service = createChallengeViewService(api);
    await service.getMyChallenges({ page: 1, perPage: 20 });
    await service.getChallengeProgress(41);

    assert.equal(api.getUri(calls[0]), '/api/v1/challenges/my-challenges?page=1&per_page=20');
    assert.equal(api.getUri(calls[1]), '/api/v1/challenges/41/progress');
    assert.equal(calls[0].withCredentials, true);
    assert.equal(calls[0].url.includes('/api/v1/api/v1'), false);
    assert.equal(calls[1].url, '/challenges/41/progress');
  } finally {
    api.defaults.adapter = previousAdapter;
  }
});

test('challenge list rejects wrong pagination context, inconsistent totals, and excess rows', async () => {
  const service = createChallengeViewService({ get: async () => ({ data: recordedList() }) });
  await assert.rejects(() => service.getMyChallenges({ page: 2 }), /requested context/i);
  await assert.rejects(() => service.getMyChallenges({ perPage: 10 }), /requested context/i);
  await assert.rejects(() => service.getMyChallenges({ status: 'failed' }), /requested context/i);
  assert.throws(() => normaliseChallengeListResponse(recordedList({
    pagination: { page: 1, per_page: 20, total: 50, pages: 1 },
  })), /inconsistent/i);
  assert.throws(() => normaliseChallengeListResponse(recordedList({
    pagination: { page: 1, per_page: 1, total: 2, pages: 2 },
    challenges: [recordedChallenge(), recordedChallenge({ id: 42 })],
  })), /bounds/i);
  const emptyLaterPage = normaliseChallengeListResponse(recordedList({
    pagination: { page: 2, per_page: 20, total: 1, pages: 1 }, challenges: [],
  }));
  assert.deepEqual(emptyLaterPage.challenges, [], 'shrinking datasets may return an empty requested page');
});
