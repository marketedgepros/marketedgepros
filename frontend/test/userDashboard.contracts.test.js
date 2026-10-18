import assert from 'node:assert/strict';
import test from 'node:test';

const {
  USER_DASHBOARD_ENDPOINT,
  UserDashboardContractError,
  loadUserDashboard,
  normalizeUserDashboard,
  recordedDecimalOrNull,
} = await import('../src/services/userDashboardViewService.js');

const recordedDashboard = {
  owner_context: { user_id: 1, tenant_id: 10 },
  user: { id: 1, tenant_id: 10, role: 'user', first_name: 'Recorded User' },
  statistics: {
    status_counts: { total: 2, pending: 0, active: 0, passed: 1, failed: 1, funded: 0 },
    status_counts_data_status: 'recorded_legacy_statuses',
    success_rate: 50,
    success_rate_data_status: 'recorded_legacy_statuses',
    total_profit: null,
    total_profit_data_status: 'unavailable_no_verified_provenance',
    total_spent: null,
    total_spent_data_status: 'unavailable_no_verified_provenance',
    data_quality: 'legacy_unverified',
  },
  recent_challenges: [
    {
      id: 10, user_id: 1, program_name: 'Recorded Zero', status: 'passed', status_data_status: 'recorded_not_verified', phase: 1, total_phases: 1,
      initial_balance: '1000.00', current_balance: '1000.00', profit: '0.00',
      balance_data_quality: 'legacy_unverified', profit_data_status: 'recorded_not_verified',
      progress: null, progress_data_status: 'unavailable_no_approved_rule_source', currency: null, created_at: '2026-10-01T12:00:00Z',
    },
    {
      id: 11, user_id: 1, program_name: 'Recorded Loss', status: 'failed', status_data_status: 'recorded_not_verified', phase: 1, total_phases: 1,
      initial_balance: '1000.00', current_balance: '900.00', profit: '-100.00',
      balance_data_quality: 'legacy_unverified', profit_data_status: 'recorded_not_verified',
      progress: null, progress_data_status: 'unavailable_no_approved_rule_source', currency: null, created_at: '2026-10-02T12:00:00+00:00',
    },
  ],
  data_quality: {
    challenge_statuses: 'legacy_unverified',
    trading_balances: 'legacy_unverified',
    financial_totals: 'unavailable_no_verified_provenance',
    provider_verification: 'not_available',
  },
};

test('dashboard service performs one cancelable request and preserves recorded zero and loss strings', async () => {
  const calls = [];
  const controller = new AbortController();
  const fakeApi = {
    get: async (...args) => {
      calls.push(args);
      return { data: recordedDashboard };
    },
  };

  const view = await loadUserDashboard(fakeApi, {
    signal: controller.signal,
    expectedOwner: { userId: 1, tenantId: 10 },
    role: 'user',
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], USER_DASHBOARD_ENDPOINT);
  assert.equal(calls[0][1].signal, controller.signal);
  assert.deepEqual(view.statistics.statusCounts, {
    total: 2, pending: 0, active: 0, passed: 1, failed: 1, funded: 0,
  });
  assert.equal(view.statistics.successRate, 50);
  assert.equal(view.statistics.totalProfit, null);
  assert.equal(view.statistics.totalSpent, null);
  assert.equal(view.recentChallenges[0].profit, '0.00');
  assert.equal(view.recentChallenges[1].profit, '-100.00');
  assert.equal(view.recentChallenges[0].progress, null);
  assert.equal(view.recentChallenges[0].currency, null);
  assert.equal(view.owner.userId, 1);
  assert.equal(view.user.tenantId, 10);
  assert.equal(JSON.stringify(view).includes('NaN'), false);
});

test('dashboard service rejects malformed identity and response fields rather than coercing them to empty account data', () => {
  const wrongRowOwner = structuredClone(recordedDashboard);
  wrongRowOwner.recent_challenges[0].user_id = 2;
  assert.throws(
    () => normalizeUserDashboard(wrongRowOwner, { expectedOwner: { userId: 1, tenantId: 10 }, role: 'user' }),
    UserDashboardContractError,
  );

  const malformed = structuredClone(recordedDashboard);
  malformed.user.id = '1';
  malformed.recent_challenges[0].initial_balance = '1e3';
  assert.throws(
    () => normalizeUserDashboard(malformed, { expectedOwner: { userId: 1, tenantId: 10 }, role: 'user' }),
    UserDashboardContractError,
  );

  assert.equal(recordedDecimalOrNull('0.00'), '0.00');
  assert.equal(recordedDecimalOrNull('-100.00'), '-100.00');
  assert.equal(recordedDecimalOrNull('NaN'), null);
});

test('dashboard service propagates API errors and rejects a structurally absent response', async () => {
  const failure = new Error('network unavailable');
  await assert.rejects(
    () => loadUserDashboard({ get: async () => { throw failure; } }),
    (error) => error === failure,
  );
  await assert.rejects(
    () => loadUserDashboard({ get: async () => ({ data: null }) }, {
      expectedOwner: { userId: 1, tenantId: 10 }, role: 'user',
    }),
    UserDashboardContractError,
  );
});
