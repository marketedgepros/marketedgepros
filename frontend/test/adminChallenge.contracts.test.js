import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ADMIN_CHALLENGE_VIEW_ENDPOINT,
  AdminChallengeViewContractError,
  createAdminChallengeViewService,
  mapAdminChallengeViewResponse,
  normalizeAdminChallengeViewParams,
} from '../src/services/adminChallengeViewService.js';

const challenge = ({
  id = 71,
  status = 'active',
  binding = 'single_unverified_legacy',
  account = undefined,
} = {}) => ({
  id,
  user_id: 22,
  program: { id: 9, name: 'Evaluation 25K' },
  user: { id: 22, name: 'Legacy Trader', email: 'trader@example.test' },
  legacy_status: status,
  legacy_payment_status: 'paid',
  current_phase: 1,
  total_phases: 2,
  initial_balance: '25000.00',
  current_balance: '25001.10',
  max_drawdown_observed: null,
  start_date: '2026-10-01T09:30:00',
  end_date: null,
  passed_at: null,
  created_at: '2026-10-01T09:30:00',
  data_status: 'unverified_legacy',
  provider_authenticated: false,
  mt5_account_binding: binding,
  mt5_account: account === undefined && binding === 'single_unverified_legacy' ? {
    login: '10000071',
    server: 'legacy.example.test:443',
    group: null,
    status: 'active',
    balance: '25001.10',
    equity: null,
    margin: '0.00',
    free_margin: null,
    margin_level: null,
    updated_at: '2026-10-02T10:00:00+00:00',
    data_status: 'unverified_legacy',
    provider_authenticated: false,
  } : account,
});

const payload = ({ challenges = [challenge()], page = 2, perPage = 20, total = 21, providerAuthenticated = false } = {}) => ({
  challenges,
  pagination: { page, per_page: perPage, total, pages: Math.ceil(total / perPage) },
  data_status: 'unverified_legacy',
  provider_authenticated: providerAuthenticated,
});

test('admin challenge view uses the canonical GET path and bounded named query payload', async () => {
  const calls = [];
  const client = {
    get: async (path, config) => {
      calls.push({ path, config });
      return { data: payload() };
    },
    post: async () => { throw new Error('POST must never be called by a read-only challenge view'); },
  };
  const service = createAdminChallengeViewService(client);
  const controller = new AbortController();

  const result = await service.list({ page: 2, perPage: 20, status: 'active', includeMt5: true, signal: controller.signal });

  assert.deepEqual(calls, [{
    path: ADMIN_CHALLENGE_VIEW_ENDPOINT,
    config: {
      params: { page: 2, per_page: 20, include_mt5: 'true', status: 'active' },
      signal: controller.signal,
    },
  }]);
  assert.equal(result.pagination.total, 21);
  assert.equal(result.challenges[0].legacyStatus, 'active');
  assert.equal(result.challenges[0].currentBalance, '25001.10');
  assert.equal(typeof result.challenges[0].currentBalance, 'string');
  assert.equal(Number.isNaN(result.challenges[0].currentBalance), false);
  assert.equal(result.challenges[0].providerAuthenticated, false);
});

test('admin challenge view supports provider mode false without inventing an account or zero balance', async () => {
  const calls = [];
  const client = {
    get: async (path, config) => {
      calls.push({ path, config });
      return {
        data: payload({
          page: 1,
          perPage: 20,
          total: 1,
          challenges: [challenge({ binding: 'not_requested', account: null })],
        }),
      };
    },
  };

  const result = await createAdminChallengeViewService(client).list({ includeMt5: false });

  assert.deepEqual(calls[0], {
    path: ADMIN_CHALLENGE_VIEW_ENDPOINT,
    config: { params: { page: 1, per_page: 20, include_mt5: 'false' }, signal: undefined },
  });
  assert.equal(result.providerAuthenticated, false);
  assert.equal(result.challenges[0].mt5AccountBinding, 'not_requested');
  assert.equal(result.challenges[0].mt5Account, null);
  assert.equal(result.challenges[0].maxDrawdownObserved, null);
});

test('admin challenge view refuses invalid request bounds before any API call', async () => {
  let getCalls = 0;
  const service = createAdminChallengeViewService({ get: async () => { getCalls += 1; return { data: {} }; } });

  for (const options of [
    { page: 0 }, { page: 1001 }, { page: 1.5 }, { perPage: 101 }, { perPage: NaN },
    { status: 'x'.repeat(21) }, { status: '   ' }, { includeMt5: 'false' },
  ]) {
    await assert.rejects(service.list(options), AdminChallengeViewContractError);
  }
  assert.equal(getCalls, 0);
  assert.deepEqual(normalizeAdminChallengeViewParams(), { page: 1, perPage: 20, status: null, includeMt5: true });
});

test('admin challenge view fails closed for malformed data, authenticated-provider claims, and ambiguous account selection', () => {
  const request = { page: 2, perPage: 20, status: 'active', includeMt5: true };
  assert.throws(
    () => mapAdminChallengeViewResponse(payload({ providerAuthenticated: true }), request),
    /provider authentication/i,
  );
  assert.throws(
    () => mapAdminChallengeViewResponse(payload({ challenges: [challenge({ account: { ...challenge().mt5_account, balance: 25001.1 } })] }), request),
    /exact legacy decimal/i,
  );
  assert.throws(
    () => mapAdminChallengeViewResponse(payload({ challenges: [challenge({ binding: 'ambiguous', account: challenge().mt5_account })] }), request),
    /non-single legacy binding/i,
  );
  assert.throws(
    () => mapAdminChallengeViewResponse(payload({ challenges: [{ ...challenge(), user: { ...challenge().user, id: 99 } }] }), request),
    /challenge owner/i,
  );
  assert.throws(
    () => mapAdminChallengeViewResponse(payload({ challenges: [challenge({ status: 'funded' })] }), request),
    /requested legacy status/i,
  );
});
