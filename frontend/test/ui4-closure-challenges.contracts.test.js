import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';
import { AxiosError } from 'axios';
import api from '../src/services/api.js';
import {
  ADMIN_CLOSURE_CHALLENGE_ENDPOINTS,
  AdminClosureChallengesContractError,
  adminClosureChallengesPrincipalFromAuth,
  buildAdminClosureChallengeListParams,
  createAdminClosureChallengesService,
  normalizeAdminClosureChallengeDetailResponse,
  normalizeAdminClosureChallengeListResponse,
} from '../src/services/adminClosureChallengesService.js';

const owner = { user_id: 1, tenant_id: 7 };
const account = {
  login: 'recorded-71', server: null, group: 'legacy', status: 'active', balance: '0.00', equity: null,
  margin: '0.00', free_margin: null, margin_level: null, updated_at: '2026-10-12T12:00:00+00:00',
  data_status: 'unverified_legacy', provider_authenticated: false,
};
const challenge = (overrides = {}) => ({
  id: 71, user_id: 22, program: { id: 9, name: 'Recorded Evaluation' },
  user: { id: 22, name: 'Legacy Trader', email: 'trader@example.invalid' },
  legacy_status: 'active', legacy_payment_status: 'paid', current_phase: 1, total_phases: 2,
  initial_balance: '25000.00', current_balance: '25001.10', max_drawdown_observed: null,
  start_date: '2026-10-01T09:30:00', end_date: null, passed_at: null, created_at: '2026-10-01T09:30:00',
  data_status: 'unverified_legacy', provider_authenticated: false,
  mt5_account_binding: 'single_unverified_legacy', mt5_account: account,
  ...overrides,
});
const listPayload = (overrides = {}) => ({
  owner_context: owner, data_status: 'unverified_legacy', provider_authenticated: false,
  filters: { status: 'active', include_mt5: true }, challenges: [challenge()],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  ...overrides,
});
const detailPayload = (overrides = {}) => ({
  owner_context: owner, data_status: 'unverified_legacy', provider_authenticated: false,
  filters: { include_mt5: true }, challenge: challenge(), ...overrides,
});

test('closure admin challenge service uses canonical GET endpoints, local owner validation, skip-refresh, and exact decimals', async () => {
  const calls = [];
  const controller = new AbortController();
  const service = createAdminClosureChallengesService({
    get: async (path, config) => {
      calls.push({ path, config });
      return { data: path === ADMIN_CLOSURE_CHALLENGE_ENDPOINTS.list ? listPayload() : detailPayload() };
    },
  });
  const list = await service.list({ expectedOwner: owner, role: 'master', page: 1, perPage: 20, status: 'active', signal: controller.signal });
  const detail = await service.detail(71, { expectedOwner: owner, role: 'master', signal: controller.signal });

  assert.deepEqual(calls, [
    { path: '/challenges/admin/all', config: { params: { page: 1, per_page: 20, status: 'active', include_mt5: 'true' }, signal: controller.signal, _skipAuthRefresh: true } },
    { path: '/challenges/admin/71', config: { params: { include_mt5: 'true' }, signal: controller.signal, _skipAuthRefresh: true } },
  ]);
  assert.equal(list.ownerContext.user_id, 1);
  assert.equal(list.challenges[0].currentBalance, '25001.10');
  assert.equal(list.challenges[0].mt5Account.balance, '0.00');
  assert.equal(detail.challenge.id, 71);
  assert.deepEqual(Object.keys(service).sort(), ['detail', 'list']);
});

test('closure admin challenge response rejects cross-account payloads, provider claims, invalid MT5 bindings, and invalid bounds before transport', async () => {
  assert.throws(
    () => normalizeAdminClosureChallengeListResponse(listPayload({ owner_context: { user_id: 2, tenant_id: 7 } }), {
      expectedOwner: owner,
      params: buildAdminClosureChallengeListParams({ status: 'active' }),
    }),
    /owner context/i,
  );
  assert.throws(
    () => normalizeAdminClosureChallengeDetailResponse(detailPayload({ provider_authenticated: true }), {
      expectedOwner: owner, challengeId: 71, params: { include_mt5: 'true' },
    }),
    /verification boundary/i,
  );
  assert.throws(
    () => normalizeAdminClosureChallengeListResponse(listPayload({
      challenges: [challenge({ mt5_account_binding: 'ambiguous', mt5_account: account })],
    }), { expectedOwner: owner, params: buildAdminClosureChallengeListParams({ status: 'active' }) }),
    /non-single MT5 binding/i,
  );
  let calls = 0;
  const service = createAdminClosureChallengesService({ get: async () => { calls += 1; return { data: listPayload() }; } });
  for (const invalid of [{ page: 0 }, { perPage: 101 }, { page: 502, perPage: 20 }, { status: ' ' }, { includeMt5: 'true' }]) {
    await assert.rejects(() => service.list({ expectedOwner: owner, role: 'master', ...invalid }), AdminClosureChallengesContractError);
  }
  assert.equal(calls, 0);
});

test('closure admin challenge principal is independently keyed by authenticated id, tenant, and admin role', () => {
  const principal = adminClosureChallengesPrincipalFromAuth({ id: 1, tenant_id: 7, role: 'master' }, true);
  assert.deepEqual(principal.owner, owner);
  assert.notEqual(principal.key, adminClosureChallengesPrincipalFromAuth({ id: 1, tenant_id: 8, role: 'master' }, true).key);
  assert.notEqual(principal.key, adminClosureChallengesPrincipalFromAuth({ id: 1, tenant_id: 7, role: 'supermaster' }, true).key);
  assert.equal(adminClosureChallengesPrincipalFromAuth({ id: 1, tenantId: 7, role: 'master' }, true), null);
  assert.equal(adminClosureChallengesPrincipalFromAuth({ id: 1, tenant_id: 7, role: 'trader' }, true), null);
});

test('actual Axios admin challenge GET does not refresh or replay a 401 and preserves AbortSignal', async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, signal: config.signal, skip: config._skipAuthRefresh });
    throw new AxiosError('Synthetic unauthorized', 'ERR_BAD_REQUEST', config, {}, {
      status: 401, data: { error: 'Unauthorized' }, headers: {}, config,
    });
  };
  try {
    const controller = new AbortController();
    await assert.rejects(
      () => createAdminClosureChallengesService().list({ expectedOwner: owner, role: 'master', signal: controller.signal }),
      (error) => error.response?.status === 401,
    );
    assert.deepEqual(calls, [{ url: '/challenges/admin/all', method: 'get', signal: controller.signal, skip: true }]);
    controller.abort();
    await assert.rejects(
      () => createAdminClosureChallengesService().detail(71, { expectedOwner: owner, role: 'master', signal: controller.signal }),
      (error) => error.name === 'AbortError' || error.code === 'ERR_CANCELED',
    );
    assert.equal(calls.length, 1, 'an already aborted detail read must not enter Axios');
  } finally {
    api.defaults.adapter = original;
  }
});

const pageFile = new URL('../src/pages/admin/ChallengesManagement.jsx', import.meta.url);
const pageTarget = new URL(`../src/pages/admin/.ui4-closure-challenges-${process.pid}.mjs`, import.meta.url);
const source = fs.readFileSync(pageFile, 'utf8')
  .replace("from '../../store/authStore';", "from '../../store/authStore.js';")
  .replace("from '../../services/adminClosureChallengesService';", "from '../../services/adminClosureChallengesService.js';");
const compiled = await transformWithEsbuild(source, pageFile.pathname, { loader: 'jsx', jsx: 'automatic' });
let pageModule;
try {
  fs.writeFileSync(pageTarget, compiled.code);
  pageModule = await import(`${pageTarget.href}?ui4=${process.pid}`);
} finally {
  fs.rmSync(pageTarget, { force: true });
}

test('closure admin challenge UI renders a role-safe unavailable state without a network effect', () => {
  const html = renderToStaticMarkup(React.createElement(pageModule.ChallengesManagementContent, { principal: null }));
  assert.match(html, /role="status"/);
  assert.match(html, /Challenge records are unavailable/);
  assert.match(html, /No account creation, funding, reset, capital command/);
});
