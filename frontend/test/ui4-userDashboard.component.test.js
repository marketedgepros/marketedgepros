import { compilePaymentHarness } from './paymentHarness.js';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const serviceUrl = new URL('../src/services/userDashboardViewService.js', import.meta.url).href;
const uiTarget = new URL('../node_modules/.cache-ui4-user-dashboard.mjs', import.meta.url);
const guideTarget = new URL('../node_modules/.cache-ui4-account-setup.mjs', import.meta.url);
const profileServiceUrl = new URL('../src/services/profileViewService.js', import.meta.url).href;
const setupServiceUrl = new URL('../src/services/accountSetupViewService.js', import.meta.url).href;
const policyModuleUrl = new URL('../src/services/programEvaluationPolicy.js', import.meta.url).href;
const policyOverride = {
  'services/programEvaluationPolicy.js': `export * from ${JSON.stringify(policyModuleUrl)};`,
};
const service = await import(serviceUrl);
const purchaseBuild = await compilePaymentHarness(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url), {
  prefix: 'ui4-userDashboard-payment',
  overrides: policyOverride,
});
const purchaseBuildUrl = purchaseBuild.targets.get(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url).pathname);
test.after(() => purchaseBuild.cleanup());
let ui;
try {
  const guideFile = new URL('../src/components/account/AccountSetupGuide.jsx', import.meta.url);
  const guideSource = fs.readFileSync(guideFile, 'utf8').replace("'../../services/accountSetupViewService.js'", JSON.stringify(setupServiceUrl));
  fs.writeFileSync(guideTarget, (await transformWithEsbuild(guideSource, guideFile.pathname, { loader: 'jsx', jsx: 'automatic' })).code);
  const sourceFile = new URL('../src/pages/user/UserDashboard.jsx', import.meta.url);
  const source = fs.readFileSync(sourceFile, 'utf8')
    .replace(/import useAuthStore from ['"]\.\.\/\.\.\/store\/authStore['"];/, "const useAuthStore = () => ({ isAuthenticated: true, user: { id: 1, tenant_id: 10, role: 'user' } });")
    .replace("import api, { profileAPI } from '../../services/api';", "const api = { get: () => { throw new Error('SSR must not request an API'); } }; const profileAPI = api;")
    .replace("import AccountSetupGuide from '../../components/account/AccountSetupGuide';", `import AccountSetupGuide from ${JSON.stringify(guideTarget.href)};`)
  .replace("import ProgramPurchaseRecords from '../../components/payments/ProgramPurchaseRecords';", `import ProgramPurchaseRecords from ${JSON.stringify(purchaseBuildUrl)};`)
    .replace("import { createProfileApiTransport } from '../../services/profileViewService';", `import { createProfileApiTransport } from ${JSON.stringify(profileServiceUrl)};`)
    .replace("import { createAccountSetupViewService } from '../../services/accountSetupViewService';", `import { createAccountSetupViewService } from ${JSON.stringify(setupServiceUrl)};`)
    .replace(/['"]\.\.\/\.\.\/services\/userDashboardViewService['"]/g, JSON.stringify(serviceUrl));
  fs.writeFileSync(uiTarget, (await transformWithEsbuild(source, sourceFile.pathname, { loader: 'jsx', jsx: 'automatic' })).code);
  ui = await import(uiTarget.href);
} finally {
  fs.rmSync(uiTarget, { force: true });
  fs.rmSync(guideTarget, { force: true });
}

const response = () => ({
  owner_context: { user_id: 1, tenant_id: 10 },
  user: { id: 1, tenant_id: 10, role: 'user', first_name: 'Owner One' },
  statistics: {
    status_counts: { total: 1, pending: 0, active: 1, passed: 0, failed: 0, funded: 0 },
    status_counts_data_status: 'recorded_legacy_statuses',
    success_rate: null,
    success_rate_data_status: 'unavailable_no_recorded_outcomes',
    total_profit: null,
    total_profit_data_status: 'unavailable_no_verified_provenance',
    total_spent: null,
    total_spent_data_status: 'unavailable_no_verified_provenance',
    data_quality: 'legacy_unverified',
  },
  recent_challenges: [{
    id: 10,
    user_id: 1,
    program_name: 'Recorded challenge',
    status: 'active',
    status_data_status: 'recorded_not_verified',
    phase: 1,
    total_phases: 2,
    initial_balance: '1000.00',
    current_balance: '1000.00',
    balance_data_quality: 'legacy_unverified',
    profit: '0.00',
    profit_data_status: 'recorded_not_verified',
    progress: null,
    progress_data_status: 'unavailable_no_approved_rule_source',
    created_at: '2026-02-28T12:00:00Z',
    currency: null,
  }],
  data_quality: {
    challenge_statuses: 'legacy_unverified',
    trading_balances: 'legacy_unverified',
    financial_totals: 'unavailable_no_verified_provenance',
    provider_verification: 'not_available',
  },
});

const ownerOptions = { expectedOwner: { userId: 1, tenantId: 10 }, role: 'user' };
const render = (component) => renderToStaticMarkup(React.createElement(MemoryRouter, null, component));
const ssrSetupService = { loadProfile: () => { throw new Error('SSR must not run setup effects'); }, loadDocuments: () => { throw new Error('SSR must not run setup effects'); } };

test('injected Axios-free API receives AbortSignal and rejects owner-one data under an owner-two browser context', async () => {
  const calls = [];
  const controller = new AbortController();
  const apiClient = {
    get: async (...args) => {
      calls.push(args);
      return { data: response() };
    },
  };

  const view = await service.loadUserDashboard(apiClient, { ...ownerOptions, signal: controller.signal });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], service.USER_DASHBOARD_ENDPOINT);
  assert.equal(calls[0][1].signal, controller.signal);
  assert.equal(view.owner.userId, 1);

  await assert.rejects(
    () => service.loadUserDashboard(apiClient, {
      expectedOwner: { userId: 2, tenantId: 10 }, role: 'user',
    }),
    service.UserDashboardContractError,
  );
});

test('the complete contract fails closed for omitted collections, malformed money, invalid calendar dates, and non-null currency', () => {
  const missingCollection = response();
  delete missingCollection.recent_challenges;
  assert.throws(() => service.normalizeUserDashboard(missingCollection, ownerOptions), service.UserDashboardContractError);

  const malformedAmount = response();
  malformedAmount.recent_challenges[0].current_balance = 1000;
  assert.throws(() => service.normalizeUserDashboard(malformedAmount, ownerOptions), service.UserDashboardContractError);

  const impossibleDate = response();
  impossibleDate.recent_challenges[0].created_at = '2026-02-31T12:00:00Z';
  assert.throws(() => service.normalizeUserDashboard(impossibleDate, ownerOptions), service.UserDashboardContractError);

  const madeUpCurrency = response();
  madeUpCurrency.recent_challenges[0].currency = 'USD';
  assert.throws(() => service.normalizeUserDashboard(madeUpCurrency, ownerOptions), service.UserDashboardContractError);
});

test('actual React dashboard overview presents recorded values without false currency, progress, or financial placeholders', () => {
  const view = service.normalizeUserDashboard(response(), ownerOptions);
  const html = render(React.createElement(ui.DashboardOverview, {
    dashboard: view,
    onRefresh: () => {},
    accountSetupService: ssrSetupService,
  }));

  assert.match(html, /Recorded legacy status — not provider verified/);
  assert.match(html, /1,000\.00/);
  assert.match(html, /Currency unavailable/);
  assert.match(html, /href="\/challenges\/10"/);
  assert.match(html, /aria-label="Latest recorded challenges table"/);
  assert.match(html, /tabindex="0"/);
  assert.doesNotMatch(html, /\$/);
  assert.doesNotMatch(html, /Total Profit|Target unavailable|Program not recorded|Welcome back/);
});

test('actual React read states keep loading, error, and successful empty responses distinct', () => {
  const loading = render(React.createElement(ui.DashboardReadState, { state: 'loading', onRetry: () => {} }));
  assert.match(loading, /role="status"/);
  assert.match(loading, /aria-busy="true"/);

  const failed = render(React.createElement(ui.DashboardReadState, { state: 'error', onRetry: () => {} }));
  assert.match(failed, /role="alert"/);
  assert.match(failed, /Retry dashboard/);

  const emptyView = service.normalizeUserDashboard({ ...response(), recent_challenges: [] }, ownerOptions);
  const empty = render(React.createElement(ui.DashboardOverview, {
    dashboard: emptyView,
    onRefresh: () => {},
    accountSetupService: ssrSetupService,
  }));
  assert.match(empty, /No recent challenge records were returned/);
  assert.doesNotMatch(empty, /role="alert"|Retry dashboard/);
});
