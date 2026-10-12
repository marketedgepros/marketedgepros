import assert from 'node:assert/strict';
import test from 'node:test';
import api from '../src/services/api.js';
import {
  ChallengeViewRequestGate,
  createChallengeViewService,
  normaliseChallengeListResponse,
  normaliseChallengeProgressResponse,
  normaliseExpectedOwner,
} from '../src/services/challengeViewService.js';

const owner = { user_id: 9, tenant_id: null };

const recordedChallenge = (overrides = {}) => ({
  id: 41,
  user_id: 9,
  program: { id: 7, name: 'Recorded Evaluation' },
  legacy_status: 'active',
  legacy_payment_status: 'paid',
  current_phase: 0,
  total_phases: 2,
  initial_balance: '0.00',
  current_balance: '0',
  max_drawdown_observed: '-0.00',
  start_date: null,
  end_date: null,
  passed_at: null,
  created_at: '2026-10-11T12:00:00+00:00',
  data_status: 'unverified_legacy',
  provider_authenticated: false,
  ...overrides,
});

const listPayload = (overrides = {}) => ({
  challenges: [recordedChallenge()],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  owner_context: owner,
  data_status: 'unverified_legacy',
  provider_authenticated: false,
  ...overrides,
});

const progressPayload = (overrides = {}) => ({
  challenge: recordedChallenge(),
  progress: {
    initial_balance: '0.00',
    current_balance: '0',
    profit_loss: '0.00',
    profit_target_percent: null,
    profit_target_amount: null,
    profit_progress_percent: null,
    trading_days: 0,
    min_trading_days: null,
    data_status: 'unverified_legacy',
    provider_authenticated: false,
  },
  mt5_account: null,
  owner_context: owner,
  data_status: 'unverified_legacy',
  provider_authenticated: false,
  ...overrides,
});

test('UI4 challenge owner contract rejects wrong owner, wrong brand, and foreign challenge rows before projection', () => {
  const list = normaliseChallengeListResponse(listPayload(), { expectedOwner: owner });
  assert.equal(list.challenges[0].initial_balance, '0.00');
  assert.equal(list.challenges[0].current_balance, '0');
  assert.equal(list.challenges[0].current_phase, 0);
  assert.deepEqual(list.owner_context, owner);

  const progress = normaliseChallengeProgressResponse(progressPayload(), 41, { expectedOwner: owner });
  assert.equal(progress.progress.current_balance, '0');
  assert.equal(progress.progress.profit_loss, '0.00');
  assert.equal(progress.progress.trading_days, 0);

  assert.throws(
    () => normaliseChallengeListResponse(listPayload({ owner_context: { user_id: 10, tenant_id: null } }), { expectedOwner: owner }),
    /owner context does not match/i,
  );
  assert.throws(
    () => normaliseChallengeProgressResponse(progressPayload({ owner_context: { user_id: 9, tenant_id: 77 } }), 41, { expectedOwner: owner }),
    /owner context does not match/i,
  );
  assert.throws(
    () => normaliseChallengeListResponse(listPayload({ challenges: [recordedChallenge({ user_id: 10 })] }), { expectedOwner: owner }),
    /different account/i,
  );
  assert.throws(
    () => normaliseChallengeProgressResponse(progressPayload({ challenge: recordedChallenge({ user_id: 10 }) }), 41, { expectedOwner: owner }),
    /different account/i,
  );
  assert.throws(
    () => normaliseChallengeListResponse(listPayload({ owner_context: { user_id: 9 } }), { expectedOwner: owner }),
    /incomplete/i,
  );
});

test('UI4 expectedOwner is strict typed while nullable tenant remains an explicit supported owner value', () => {
  assert.deepEqual(normaliseExpectedOwner({ user_id: 9, tenant_id: null }), owner);
  assert.deepEqual(normaliseExpectedOwner({ user_id: 9, tenant_id: 4 }), { user_id: 9, tenant_id: 4 });
  for (const invalid of [
    null,
    { user_id: '9', tenant_id: null },
    { user_id: 0, tenant_id: null },
    { user_id: 9 },
    { user_id: 9, tenant_id: undefined },
    { user_id: 9, tenant_id: '4' },
    { user_id: 9, tenant_id: 0 },
  ]) {
    assert.throws(() => normaliseExpectedOwner(invalid), /owner|integer/i);
  }
});

test('UI4 challenge service forwards AbortSignal to Axios and validates expectedOwner on the returned payload', async () => {
  const previousAdapter = api.defaults.adapter;
  const calls = [];
  const controller = new AbortController();
  api.defaults.adapter = async (config) => {
    calls.push(config);
    return {
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
      data: listPayload(),
    };
  };

  try {
    const service = createChallengeViewService(api);
    const result = await service.getMyChallenges({
      page: 1,
      perPage: 20,
      signal: controller.signal,
      expectedOwner: owner,
    });
    assert.equal(result.challenges[0].id, 41);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].signal, controller.signal);
    assert.equal(calls[0].url, '/challenges/my-challenges');
  } finally {
    api.defaults.adapter = previousAdapter;
  }
});

test('UI4 late response for an abandoned route is cancelled and cannot become the current projection', async () => {
  let releaseResponse;
  const service = createChallengeViewService({
    get: () => new Promise((resolve) => { releaseResponse = resolve; }),
  });
  const controller = new AbortController();
  const pending = service.getChallengeProgress(41, { signal: controller.signal, expectedOwner: owner });
  const gate = new ChallengeViewRequestGate();
  const route41 = gate.begin({ mode: 'detail', id: 41, identity: 'user:9|tenant:null|role:user' });
  const route42 = gate.begin({ mode: 'detail', id: 42, identity: 'user:9|tenant:null|role:user' });

  controller.abort();
  releaseResponse({ data: progressPayload() });

  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(gate.isCurrent(route41), false, 'a late route-41 response is stale once route 42 starts');
  assert.equal(gate.isCurrent(route42), true);
});
