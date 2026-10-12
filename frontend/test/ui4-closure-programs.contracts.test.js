import assert from 'node:assert/strict';
import test from 'node:test';
import { AxiosError, CanceledError } from 'axios';
import api from '../src/services/api.js';
import {
  ADMIN_PROGRAMS_ENDPOINT,
  AdminProgramsContractError,
  adminProgramsPrincipalFromAuth,
  deleteAdminProgram,
  loadAdminPrograms,
  saveAdminProgram,
  serializeProgramMutation,
} from '../src/services/adminClosureProgramsService.js';

const owner = { userId: 41, tenantId: 7, role: 'master' };
const ownerContext = { user_id: 41, tenant_id: 7, role: 'master' };

const rawProgram = (overrides = {}) => ({
  id: 19,
  tenant_id: 7,
  name: 'Recorded Evaluation',
  type: 'stored_legacy_type',
  description: null,
  account_size: '10000.00',
  profit_target: null,
  max_daily_loss: '0.00',
  max_total_loss: null,
  price: '199.99',
  profit_split: null,
  profit_split_percentage: '0.00',
  minimum_payout_amount: null,
  payout_mode: null,
  rules: { legacy: { exact: '0.00', missing: null } },
  is_active: true,
  created_at: null,
  updated_at: '2026-10-12T12:00:00Z',
  ...overrides,
});

const listPayload = (overrides = {}) => ({
  owner_context: ownerContext,
  programs: [rawProgram()],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  ...overrides,
});

const mutationPayload = (overrides = {}) => ({
  owner_context: ownerContext,
  program: rawProgram(),
  ...overrides,
});

const draft = (overrides = {}) => ({
  name: 'Recorded Evaluation',
  type: 'stored_legacy_type',
  description: '',
  accountSize: '10000.00',
  profitTarget: '',
  maxDailyLoss: '0.00',
  maxTotalLoss: '',
  price: '199.99',
  profitSplit: '',
  profitSplitPercentage: '0.00',
  minimumPayoutAmount: '',
  payoutMode: '',
  rules: '{"legacy":{"exact":"0.00","missing":null}}',
  isActive: true,
  ...overrides,
});

test('UI4 programs principal is independently derived from authenticated id, tenant, and role before any transport', async () => {
  const principal = adminProgramsPrincipalFromAuth({ id: 41, tenant_id: 7, role: 'master' }, true);
  assert.deepEqual(principal.owner, owner);
  assert.notEqual(principal.key, adminProgramsPrincipalFromAuth({ id: 41, tenant_id: 8, role: 'master' }, true).key);
  assert.notEqual(principal.key, adminProgramsPrincipalFromAuth({ id: 41, tenant_id: 7, role: 'supermaster' }, true).key);
  for (const [user, authenticated] of [
    [{ id: 41, tenant_id: 7, role: 'trader' }, true],
    [{ id: 41, tenantId: 7, role: 'master' }, true],
    [{ id: 0, tenant_id: 7, role: 'master' }, true],
    [{ id: 41, tenant_id: 7, role: 'master' }, false],
  ]) {
    assert.equal(adminProgramsPrincipalFromAuth(user, authenticated), null);
  }

  let calls = 0;
  await assert.rejects(
    () => loadAdminPrograms({ get: async () => { calls += 1; return { data: listPayload() }; } }, {
      expectedOwner: { ...owner, tenantId: null },
    }),
    AdminProgramsContractError,
  );
  await assert.rejects(
    () => loadAdminPrograms({ get: async () => { calls += 1; return { data: listPayload() }; } }, {
      expectedOwner: owner, page: 1, perPage: 51,
    }),
    /pagination/i,
  );
  assert.equal(calls, 0, 'invalid independent principal/query must not enter transport');
});

test('UI4 programs list uses the canonical scoped request and preserves exact decimal strings and nulls', async () => {
  const calls = [];
  const controller = new AbortController();
  const result = await loadAdminPrograms({
    get: async (path, config) => {
      calls.push({ path, config });
      return { data: listPayload() };
    },
  }, { expectedOwner: owner, signal: controller.signal, page: 1, perPage: 20 });

  assert.deepEqual(calls, [{
    path: ADMIN_PROGRAMS_ENDPOINT,
    config: {
      params: { page: '1', per_page: '20' },
      signal: controller.signal,
      _skipAuthRefresh: true,
    },
  }]);
  assert.equal(result.owner.tenantId, 7);
  assert.equal(result.programs[0].accountSize, '10000.00');
  assert.equal(result.programs[0].maxDailyLoss, '0.00');
  assert.equal(result.programs[0].profitTarget, null);
  assert.equal(result.programs[0].maxTotalLoss, null);
  assert.equal(result.programs[0].profitSplit, null);
  assert.equal(result.programs[0].minimumPayoutAmount, null);
  assert.deepEqual(result.programs[0].rules, { legacy: { exact: '0.00', missing: null } });

  await assert.rejects(
    () => loadAdminPrograms({ get: async () => ({ data: listPayload({ owner_context: { ...ownerContext, tenant_id: 8 } }) }) }, {
      expectedOwner: owner,
    }),
    /owner context/i,
  );
});

test('UI4 programs create, edit, toggle, and delete accept only their server-confirmed acknowledgements', async () => {
  const calls = [];
  const controller = new AbortController();
  const client = {
    post: async (path, body, config) => {
      calls.push({ method: 'post', path, body, config });
      return { data: mutationPayload({ program: rawProgram({ id: 20 }) }) };
    },
    put: async (path, body, config) => {
      calls.push({ method: 'put', path, body, config });
      return { data: mutationPayload({ program: rawProgram({
        name: body.name,
        price: body.price,
        is_active: body.is_active,
      }) }) };
    },
    delete: async (path, config) => {
      calls.push({ method: 'delete', path, config });
      return { data: { owner_context: ownerContext, deleted_program_id: 19 } };
    },
  };

  const created = await saveAdminProgram(client, { expectedOwner: owner, draft: draft(), signal: controller.signal });
  const edited = await saveAdminProgram(client, {
    expectedOwner: owner, programId: 19, signal: controller.signal,
    draft: draft({ name: 'Recorded Evaluation Updated', price: '200.00' }),
  });
  const toggled = await saveAdminProgram(client, {
    expectedOwner: owner, programId: 19, signal: controller.signal,
    draft: draft({ isActive: false }),
  });
  const deleted = await deleteAdminProgram(client, { expectedOwner: owner, programId: 19, signal: controller.signal });

  assert.equal(created.program.id, 20);
  assert.equal(edited.program.name, 'Recorded Evaluation Updated');
  assert.equal(edited.program.price, '200.00');
  assert.equal(toggled.program.isActive, false);
  assert.deepEqual(deleted, { owner: owner, deletedProgramId: 19 });
  assert.deepEqual(calls[0], {
    method: 'post',
    path: ADMIN_PROGRAMS_ENDPOINT,
    body: {
      name: 'Recorded Evaluation', type: 'stored_legacy_type', description: null,
      account_size: '10000.00', profit_target: null, max_daily_loss: '0.00', max_total_loss: null,
      price: '199.99', profit_split: null, profit_split_percentage: '0.00',
      minimum_payout_amount: null, payout_mode: null,
      rules: { legacy: { exact: '0.00', missing: null } }, is_active: true,
    },
    config: { signal: controller.signal, _skipAuthRefresh: true },
  });
  assert.equal(calls[1].method, 'put');
  assert.equal(calls[1].path, `${ADMIN_PROGRAMS_ENDPOINT}/19`);
  assert.equal(calls[2].body.is_active, false);
  assert.deepEqual(calls[3], {
    method: 'delete', path: `${ADMIN_PROGRAMS_ENDPOINT}/19`,
    config: { signal: controller.signal, _skipAuthRefresh: true },
  });

  await assert.rejects(
    () => saveAdminProgram({ put: async () => ({ data: mutationPayload({ program: rawProgram({ id: 99 }) }) }) }, {
      expectedOwner: owner, programId: 19, draft: draft(),
    }),
    /did not match the requested program/i,
  );
  await assert.rejects(
    () => deleteAdminProgram({ delete: async () => ({ data: { owner_context: ownerContext, deleted_program_id: 99 } }) }, {
      expectedOwner: owner, programId: 19,
    }),
    /did not match the request/i,
  );

  assert.throws(
    () => serializeProgramMutation(draft({ payoutMode: 'not\u0001ascii' })),
    /payout_mode/i,
  );
});

test('UI4 programs reaches Axios with AbortSignal, does not refresh/replay a 401, and refuses a response cancelled in flight', async () => {
  const originalAdapter = api.defaults.adapter;
  const calls = [];
  let mode = 'unauthorized';
  api.defaults.adapter = (config) => {
    calls.push({ url: config.url, method: config.method, signal: config.signal, skip: config._skipAuthRefresh });
    if (mode === 'unauthorized') {
      const response = { status: 401, data: { error: 'Unauthorized' }, headers: {}, config };
      return Promise.reject(new AxiosError('Synthetic unauthorized', 'ERR_BAD_REQUEST', config, {}, response));
    }
    return new Promise((resolve, reject) => {
      const rejectCanceled = () => reject(new CanceledError('Synthetic cancellation', config));
      if (config.signal?.aborted) rejectCanceled();
      else config.signal?.addEventListener('abort', rejectCanceled, { once: true });
    });
  };
  try {
    await assert.rejects(
      () => loadAdminPrograms(api, { expectedOwner: owner }),
      (error) => error.response?.status === 401,
    );
    assert.deepEqual(calls, [{ url: ADMIN_PROGRAMS_ENDPOINT, method: 'get', signal: undefined, skip: true }]);

    mode = 'pending';
    const controller = new AbortController();
    const pending = loadAdminPrograms(api, { expectedOwner: owner, signal: controller.signal });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(calls.length, 2);
    assert.equal(calls[1].signal, controller.signal);
    controller.abort();
    await assert.rejects(pending, (error) => error.name === 'AbortError' || error.code === 'ERR_CANCELED');
    assert.equal(calls.length, 2, 'cancellation must not cause a retry or replay');

    const postResponseController = new AbortController();
    await assert.rejects(
      () => loadAdminPrograms({
        get: async () => {
          postResponseController.abort();
          return { data: listPayload() };
        },
      }, { expectedOwner: owner, signal: postResponseController.signal }),
      (error) => error.name === 'AbortError',
    );
  } finally {
    api.defaults.adapter = originalAdapter;
  }
});
