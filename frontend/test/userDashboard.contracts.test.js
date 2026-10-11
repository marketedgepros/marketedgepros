import assert from 'node:assert/strict';
import test from 'node:test';

const {
  USER_DASHBOARD_ENDPOINT,
  loadUserDashboard,
  normalizeUserDashboard,
  recordedDecimalOrNull,
} = await import('../src/services/userDashboardViewService.js');

const recordedDashboard = {
  user: { first_name: 'Recorded User' },
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
      id: 10, program_name: 'Recorded Zero', status: 'passed', phase: 1, total_phases: 1,
      initial_balance: '1000.00', current_balance: '1000.00', profit: '0.00',
      progress: null, created_at: '2026-10-01T12:00:00',
    },
    {
      id: 11, program_name: 'Recorded Loss', status: 'failed', phase: 1, total_phases: 1,
      initial_balance: '1000.00', current_balance: '900.00', profit: '-100.00',
      progress: null, created_at: '2026-10-02T12:00:00',
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

  const view = await loadUserDashboard(fakeApi, { signal: controller.signal });

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
  assert.equal(JSON.stringify(view).includes('NaN'), false);
});

test('dashboard service marks malformed fields unavailable rather than coercing them to zero or NaN', () => {
  const view = normalizeUserDashboard({
    user: { first_name: 7 },
    statistics: {
      status_counts: { total: '2', pending: -1, active: Number.NaN, passed: 1.5, failed: null },
      success_rate: '50',
      total_profit: 1234,
      total_spent: '0.00',
    },
    recent_challenges: [{
      id: '10', program_name: 8, status: null, phase: -1, total_phases: '1',
      initial_balance: '1e3', current_balance: 'Infinity', profit: '0/0', progress: 100,
      created_at: 'not-a-date',
    }],
  });

  assert.deepEqual(view.statistics.statusCounts, {
    total: null, pending: null, active: null, passed: null, failed: null, funded: null,
  });
  assert.equal(view.statistics.successRate, null);
  assert.equal(view.statistics.totalProfit, null);
  assert.equal(view.statistics.totalSpent, null);
  assert.equal(view.user.firstName, null);
  assert.deepEqual(view.recentChallenges[0], {
    id: null,
    programName: null,
    status: null,
    statusDataStatus: null,
    phase: null,
    totalPhases: null,
    initialBalance: null,
    currentBalance: null,
    balanceDataQuality: null,
    profit: null,
    profitDataStatus: null,
    progress: null,
    progressDataStatus: null,
    createdAt: 'not-a-date',
  });
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
    () => loadUserDashboard({ get: async () => ({ data: null }) }),
    /Dashboard response is unavailable/,
  );
});
