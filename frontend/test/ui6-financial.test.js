import { compilePaymentHarness } from './paymentHarness.js';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = (relative) => path.join(frontend, 'src', relative);
const sourceUrl = (relative) => pathToFileURL(src(relative)).href;
const policyOverride = {
  'services/programEvaluationPolicy.js': `export * from ${JSON.stringify(sourceUrl('services/programEvaluationPolicy.js'))};`,
};
const jsdomPackage = require.resolve('jsdom/package.json');
assert.equal(JSON.parse(fs.readFileSync(jsdomPackage, 'utf8')).version, '28.1.0');
const { JSDOM } = await import(pathToFileURL(require.resolve('jsdom')).href);

// Bootstrap the JSDOM window before loading react-dom/client. This is required for
// React's controlled select onChange implementation to bind to this DOM.
const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'https://ui6-financial.test/', pretendToBeVisual: true,
});
for (const [key, value] of Object.entries({
  window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
  HTMLElement: dom.window.HTMLElement, HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement, HTMLAnchorElement: dom.window.HTMLAnchorElement,
  Node: dom.window.Node, Element: dom.window.Element, Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent, MutationObserver: dom.window.MutationObserver,
  getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
  requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
  cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
  IS_REACT_ACT_ENVIRONMENT: true,
})) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });

const reactModule = await import(pathToFileURL(require.resolve('react')).href);
const React = reactModule.default;
const { act } = reactModule;
const { createRoot } = await import(pathToFileURL(require.resolve('react-dom/client')).href);
const { MemoryRouter, Route, Routes, useLocation, useNavigate } = await import('react-router-dom');
const financial = await import(sourceUrl('services/financialRecordViewService.js'));
const adminPayments = await import(sourceUrl('services/adminPaymentRecordViewService.js'));

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'marketedge-ui6-financial-'));
fs.symlinkSync(path.join(frontend, 'node_modules'), path.join(temporary, 'node_modules'), 'dir');
let compiled = 0;
async function compile(name, relative, rewrite) {
  const input = src(relative);
  const result = await transformWithEsbuild(rewrite(fs.readFileSync(input, 'utf8')), input, {
    loader: 'jsx', jsx: 'automatic',
  });
  const output = path.join(temporary, `${name}-${process.pid}-${compiled += 1}.mjs`);
  fs.writeFileSync(output, result.code);
  const url = `${pathToFileURL(output).href}?ui6-financial=${compiled}`;
  return { url, module: await import(url) };
}

const authStub = `const useAuthStore = (selector) => {
  const state = globalThis.__ui6FinancialAuth;
  return typeof selector === 'function' ? selector(state) : state;
};`;
globalThis.__ui6FinancialActive = null;
globalThis.__ui6AdminPaymentActive = null;
globalThis.__ui6FinancialService = {
  wallet: (...args) => globalThis.__ui6FinancialActive.wallet(...args),
  selfWithdrawals: (...args) => globalThis.__ui6FinancialActive.selfWithdrawals(...args),
  adminWithdrawals: (...args) => globalThis.__ui6FinancialActive.adminWithdrawals(...args),
};
globalThis.__ui6AdminPaymentService = {
  loadPayments: (...args) => globalThis.__ui6AdminPaymentActive.loadPayments(...args),
  loadApprovalRequests: (...args) => globalThis.__ui6AdminPaymentActive.loadApprovalRequests(...args),
};

const financialUrl = sourceUrl('services/financialRecordViewService.js');
const adminPaymentUrl = sourceUrl('services/adminPaymentRecordViewService.js');
const financialHookUrl = sourceUrl('hooks/useFinancialRecordRead.js');
const adminPaymentHookUrl = sourceUrl('hooks/useAdminPaymentRead.js');
const rolesUrl = sourceUrl('constants/roles.js');
const financialUi = await compile('financial-ui', 'components/financial/FinancialRecordUI.jsx', (text) => text
  .replace(/['"]\.\.\/\.\.\/services\/financialRecordViewService\.js['"]/g, JSON.stringify(financialUrl)));
const adminPaymentUi = await compile('admin-payment-ui', 'components/admin/AdminPaymentRecordUI.jsx', (text) => text
  .replace(/['"]\.\.\/\.\.\/services\/adminPaymentRecordViewService\.js['"]/g, JSON.stringify(adminPaymentUrl)));

const financialPageRewrite = (text, uiUrl, statusName) => text
  .replace(/import useAuthStore from ["']\.\.\/\.\.\/store\/authStore\.js["'];/, authStub)
  .replace(/import useFinancialRecordRead from ["']\.\.\/\.\.\/hooks\/useFinancialRecordRead\.js["'];/, `import useFinancialRecordRead from ${JSON.stringify(financialHookUrl)};`)
  .replace(/import \{\s*createFinancialRecordViewService,[\s\S]*?\} from "\.\.\/\.\.\/services\/financialRecordViewService\.js";/,
    `import { ${statusName} } from ${JSON.stringify(financialUrl)};\nconst createFinancialRecordViewService = () => globalThis.__ui6FinancialService;\nconst financialRecordError = () => 'Synthetic record read rejected without inference.';`)
  .replace(/['"]\.\.\/\.\.\/components\/financial\/FinancialRecordUI\.jsx['"]/g, JSON.stringify(uiUrl));

const Wallet = (await compile('wallet', 'pages/user/Wallet.jsx', (text) => financialPageRewrite(
  text, financialUi.url, 'FINANCIAL_BALANCE_TYPES, FINANCIAL_RECORD_PAGE_SIZE',
))).module.default;
const TraderWithdrawals = (await compile('trader-withdrawals', 'pages/trader/Withdrawals.jsx', (text) => financialPageRewrite(
  text, financialUi.url, 'FINANCIAL_RECORD_PAGE_SIZE, FINANCIAL_WITHDRAWAL_STATUSES',
))).module.default;
const AdminWithdrawals = (await compile('admin-withdrawals', 'pages/admin/WithdrawalManagement.jsx', (text) => financialPageRewrite(
  text, financialUi.url, 'FINANCIAL_RECORD_PAGE_SIZE, FINANCIAL_WITHDRAWAL_STATUSES',
))).module.default;
const purchaseBuild = await compilePaymentHarness(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url), {
  prefix: 'ui6-financial-payment',
  overrides: policyOverride,
});
const purchaseBuildUrl = purchaseBuild.targets.get(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url).pathname);
test.after(() => purchaseBuild.cleanup());
const Payments = (await compile('payments', 'pages/admin/PaymentsManagementConnected.jsx', (text) => text
  .replace('import ProgramPurchaseRecords from "../../components/payments/ProgramPurchaseRecords.jsx";', `import ProgramPurchaseRecords from ${JSON.stringify(purchaseBuildUrl)};`)
  .replace(/import useAuthStore from ["']\.\.\/\.\.\/store\/authStore\.js["'];/, authStub)
  .replace(/import \{\s*createAdminPaymentRecordViewService,\s*\} from "\.\.\/\.\.\/services\/adminPaymentRecordViewService\.js";/, 'const createAdminPaymentRecordViewService = () => globalThis.__ui6AdminPaymentService;')
  .replace(/import useAdminPaymentRead from ["']\.\.\/\.\.\/hooks\/useAdminPaymentRead\.js["'];/, `import useAdminPaymentRead from ${JSON.stringify(adminPaymentHookUrl)};`)
  .replace(/['"]\.\.\/\.\.\/components\/admin\/AdminPaymentRecordUI\.jsx['"]/g, JSON.stringify(adminPaymentUi.url))
)).module.default;
const PaymentApprovals = (await compile('payment-approvals', 'pages/admin/PaymentApprovals.jsx', (text) => text
  .replace(/import useAuthStore from ["']\.\.\/\.\.\/store\/authStore\.js["'];/, authStub)
  .replace(/import \{ ROLES \} from ["']\.\.\/\.\.\/constants\/roles\.js["'];/, `import { ROLES } from ${JSON.stringify(rolesUrl)};`)
  .replace(/import \{\s*createAdminPaymentRecordViewService,\s*\} from "\.\.\/\.\.\/services\/adminPaymentRecordViewService\.js";/, 'const createAdminPaymentRecordViewService = () => globalThis.__ui6AdminPaymentService;')
  .replace(/import useAdminPaymentRead from ["']\.\.\/\.\.\/hooks\/useAdminPaymentRead\.js["'];/, `import useAdminPaymentRead from ${JSON.stringify(adminPaymentHookUrl)};`)
  .replace(/['"]\.\.\/\.\.\/components\/admin\/AdminPaymentRecordUI\.jsx['"]/g, JSON.stringify(adminPaymentUi.url))
)).module.default;
const RoleGuard = (await compile('role-guard', 'components/guards/RoleGuard.jsx', (text) => text
  .replace("import useAuthStore from '../../store/authStore';", authStub)
)).module.default;
const ProtectedRoute = (await compile('protected-route', 'App.jsx', (text) => text
  .replace("import { useState, useEffect, lazy, Suspense } from 'react';", "import { useState, useEffect } from 'react'; const lazy = () => () => null; const Suspense = ({ children }) => children;")
  .replace("import useAuthStore from './store/authStore';", authStub)
  .replace("import Notification from './components/Notification';", 'const Notification = () => null;')
  .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
  .replace("import ChatWidget from './components/ChatWidget';", 'const ChatWidget = () => null;')
  .replace("import { ADMIN_ROLES } from './constants/roles';", "const ADMIN_ROLES = ['supermaster', 'master'];")
  .replace("import { postLoginDestination } from './services/navigationService.js';", "const postLoginDestination = () => '/dashboard';")
  .replace("import { ToastProvider } from './contexts/ToastContext';", 'const ToastProvider = ({ children }) => children;')
  .replace("import useNotificationStore from './stores/notificationStore.js';", "const useNotificationStore = { getState: () => ({ reset: () => {} }) };")
  .replace("import RoleGuard from './components/guards/RoleGuard';", 'const RoleGuard = ({ children }) => children;')
  .concat('\nexport { ProtectedRoute };\n')
)).module.ProtectedRoute;

const h = React.createElement;
const owner = { user_id: 9, tenant_id: 7 };
const stamp = '2026-10-12T10:00:00Z';
function setAuth(user, isAuthenticated = Boolean(user)) {
  globalThis.__ui6FinancialAuth = { user, isAuthenticated, isLoading: false, init: async () => {} };
}
async function settle(rounds = 2) {
  for (let i = 0; i < rounds; i += 1) await act(async () => {
    await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0));
  });
}
async function waitFor(check, label) {
  let last;
  for (let i = 0; i < 80; i += 1) {
    try { const value = check(); if (value) return value; } catch (error) { last = error; }
    await settle(1);
  }
  throw last || new Error(`Timed out waiting for ${label}`);
}
async function mount(ui, entry = '/') {
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => root.render(h(MemoryRouter, { initialEntries: [entry] }, ui)));
  return root;
}
async function unmount(root) {
  if (root) await act(async () => root.unmount());
  document.body.innerHTML = '';
}
async function click(element) {
  assert.ok(element, 'expected interactive DOM element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}
async function selectValue(element, value) {
  assert.ok(element, 'expected source select element');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  await act(async () => {
    setter.call(element, value);
    element.dispatchEvent(new window.Event('input', { bubbles: true, cancelable: true }));
    element.dispatchEvent(new window.Event('change', { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}
const button = (text, occurrence = 0) => [...document.querySelectorAll('button')]
  .filter((element) => element.textContent.replace(/\s+/g, ' ').trim() === text)[occurrence];
const anchor = (destination) => document.querySelector(`a[href="${destination}"]`);
function LocationProbe() {
  const location = useLocation();
  const value = `${location.pathname}${location.search}`;
  return h('output', { 'data-location': value }, value);
}
function BackDestination() {
  const navigate = useNavigate();
  return h(React.Fragment, null, h(LocationProbe), h('button', { onClick: () => navigate(-1) }, 'Back to records'));
}

const financialFlags = () => ({ owner_context: owner, balance_verification: 'unverified_legacy', payouts_enabled: false, available_for_payout: null, currency: null });
const walletPayload = () => ({ ...financialFlags(), wallet: { id: 31, user_id: owner.user_id, main_balance: '0.00', commission_balance: null, bonus_balance: '10.25', is_active: true, last_transaction_at: stamp, created_at: stamp } });
function transactionPayload(params = {}, empty = false) {
  const page = params.page || 1;
  const balance = params.balance_type || 'main';
  return {
    ...financialFlags(), wallet_id: 31,
    transactions: Array.from({ length: empty ? 0 : 20 }, (_, i) => ({ id: page * 100 + i + 1, wallet_id: 31, type: 'credit', balance_type: balance, amount: String(i + 1), balance_before: null, balance_after: String(i + 1), created_at: stamp })),
    pagination: { page, per_page: params.per_page, total: empty ? 0 : 40, pages: empty ? 0 : 2 }, filters: { balance_type: params.balance_type || null },
  };
}
function withdrawalPayload(params = {}, admin = false, empty = false) {
  const page = params.page || 1;
  const status = params.status || 'pending';
  return {
    ...financialFlags(),
    withdrawals: Array.from({ length: empty ? 0 : 20 }, (_, i) => ({ id: page * 100 + i + 1, user_id: admin ? 40 + i : owner.user_id, amount: String(i + 1), fee: null, net_amount: null, payment_method: 'bank_transfer', status, created_at: stamp, approved_at: null, processed_at: null, completed_at: null })),
    pagination: { page, per_page: params.per_page, total: empty ? 0 : 40, pages: empty ? 0 : 2 }, filters: { status: params.status || null },
  };
}
function financialHarness({ failFirstWallet = false, empty = false, missingWallet = false } = {}) {
  const transport = []; const calls = []; const releases = [];
  let failWallet = failFirstWallet; let held = false;
  const client = { get: async (endpoint, config = {}) => {
    transport.push({ endpoint, config });
    if (held) await new Promise((resolve) => releases.push(resolve));
    if (failWallet && endpoint === '/wallet/balance') { failWallet = false; throw new Error('synthetic financial outage'); }
    if (missingWallet && endpoint === '/wallet/balance') {
      const error = new Error('synthetic canonical wallet missing');
      error.response = { status: 404, data: { error: 'Wallet not found', code: 'WALLET_NOT_FOUND', reason: 'unverified_legacy' } };
      throw error;
    }
    if (endpoint === '/wallet/balance') return { data: walletPayload() };
    if (endpoint === '/wallet/transactions') return { data: transactionPayload(config.params, empty) };
    if (endpoint === '/traders/withdrawals') return { data: withdrawalPayload(config.params, false, empty) };
    if (endpoint === '/wallet/admin/withdrawals') return { data: withdrawalPayload(config.params, true, empty) };
    throw new Error(`unexpected synthetic endpoint ${endpoint}`);
  }};
  const actual = financial.createFinancialRecordViewService(client);
  globalThis.__ui6FinancialActive = {
    wallet: (options) => { calls.push({ method: 'wallet', options }); return actual.wallet(options); },
    selfWithdrawals: (options) => { calls.push({ method: 'selfWithdrawals', options }); return actual.selfWithdrawals(options); },
    adminWithdrawals: (options) => { calls.push({ method: 'adminWithdrawals', options }); return actual.adminWithdrawals(options); },
  };
  return { transport, calls, hold: () => { held = true; }, release: () => { held = false; releases.splice(0).forEach((resolve) => resolve()); } };
}

const adminFlags = () => ({ owner_context: owner, record_verification: 'unverified_legacy', settlement_enabled: false });
function paymentPayload(params = {}, empty = false) {
  const page = params.page || 1; const status = params.status || 'pending'; const type = params.type || 'challenge_purchase';
  return {
    ...adminFlags(),
    payments: Array.from({ length: empty ? 0 : 20 }, (_, i) => ({ id: page * 100 + i + 1, user_id: 40 + i, amount: String(i + 1), currency: 'USD', payment_type: type, payment_method: `synthetic-method-${page}-${i + 1}`, status, created_at: stamp })),
    pagination: { page, per_page: params.per_page, total: empty ? 0 : 40, pages: empty ? 0 : 2 }, filters: { status: params.status || null, type: params.type || null },
  };
}
function approvalPayload(params = {}, empty = false) {
  const page = params.page || 1;
  return {
    ...adminFlags(),
    requests: Array.from({ length: empty ? 0 : 20 }, (_, i) => ({ id: page * 100 + i + 1, requested_by: 4, requested_for: 40 + i, challenge_id: null, payment_id: 100 + i, amount: String(i + 1), payment_type: i % 2 ? 'cash' : 'free', status: 'pending', created_at: stamp, reviewed_at: null })),
    pagination: { page, per_page: params.per_page, total: empty ? 0 : 40, pages: empty ? 0 : 2 }, filters: { status: 'pending' },
  };
}
function adminPaymentHarness({ failFirstPayment = false, empty = false } = {}) {
  const transport = []; const calls = []; const releases = [];
  let failPayment = failFirstPayment; let held = false;
  const client = { get: async (endpoint, config = {}) => {
    transport.push({ endpoint, config });
    if (held) await new Promise((resolve) => releases.push(resolve));
    if (failPayment && endpoint === '/admin/payments') { failPayment = false; throw new Error('synthetic payment outage'); }
    if (endpoint === '/admin/payments') return { data: paymentPayload(config.params, empty) };
    if (endpoint === '/payment-approvals/pending') return { data: approvalPayload(config.params, empty) };
    throw new Error(`unexpected synthetic endpoint ${endpoint}`);
  }};
  const actual = adminPayments.createAdminPaymentRecordViewService(client);
  globalThis.__ui6AdminPaymentActive = {
    loadPayments: (options) => { calls.push({ method: 'loadPayments', options }); return actual.loadPayments(options); },
    loadApprovalRequests: (options) => { calls.push({ method: 'loadApprovalRequests', options }); return actual.loadApprovalRequests(options); },
  };
  return { transport, calls, hold: () => { held = true; }, release: () => { held = false; releases.splice(0).forEach((resolve) => resolve()); } };
}

function GuardRoute({ route, allowedRoles, userOnly, text }) {
  const child = allowedRoles ? h(RoleGuard, { allowedRoles }, h('p', null, text)) : h('p', null, text);
  return h(Routes, null,
    h(Route, { path: route, element: h(ProtectedRoute, { userOnly }, child) }),
    h(Route, { path: '/login', element: h(LocationProbe) }),
    h(Route, { path: '/admin', element: h(LocationProbe) }),
  );
}

test('UI6 financial: active source guards execute guest, permitted, and forbidden route outcomes in MemoryRouter', { concurrency: false }, async () => {
  let root;
  const location = () => document.querySelector('[data-location]')?.textContent;
  try {
    setAuth(null, false);
    root = await mount(h(GuardRoute, { route: '/wallet', userOnly: true, text: 'wallet allowed' }), '/wallet');
    await waitFor(() => location() === '/login?redirect=%2Fwallet', 'wallet guest redirect');
    await unmount(root);
    setAuth({ id: 9, tenant_id: 7, role: 'trader' });
    root = await mount(h(GuardRoute, { route: '/wallet', userOnly: true, text: 'wallet allowed' }), '/wallet');
    await waitFor(() => document.body.textContent.includes('wallet allowed'), 'wallet permitted');
    await unmount(root);
    setAuth({ id: 9, tenant_id: 7, role: 'master' });
    root = await mount(h(GuardRoute, { route: '/wallet', userOnly: true, text: 'wallet forbidden' }), '/wallet');
    await waitFor(() => location() === '/admin', 'wallet forbidden redirect');
    assert.equal(document.body.textContent.includes('wallet forbidden'), false);
    await unmount(root);

    setAuth(null, false);
    root = await mount(h(GuardRoute, { route: '/trader/withdrawals', allowedRoles: ['trader'], text: 'trader allowed' }), '/trader/withdrawals');
    await waitFor(() => location() === '/login?redirect=%2Ftrader%2Fwithdrawals', 'trader guest redirect');
    await unmount(root);
    setAuth({ id: 9, tenant_id: 7, role: 'trader' });
    root = await mount(h(GuardRoute, { route: '/trader/withdrawals', allowedRoles: ['trader'], text: 'trader allowed' }), '/trader/withdrawals');
    await waitFor(() => document.body.textContent.includes('trader allowed'), 'trader permitted');
    await unmount(root);
    setAuth({ id: 9, tenant_id: 7, role: 'affiliate' });
    root = await mount(h(GuardRoute, { route: '/trader/withdrawals', allowedRoles: ['trader'], text: 'trader forbidden' }), '/trader/withdrawals');
    await waitFor(() => document.body.textContent.includes('Access Denied'), 'trader forbidden');
    await unmount(root);

    for (const [route, permitted] of [['/admin/payments', 'master'], ['/admin/payment-approvals', 'supermaster'], ['/admin/withdrawals', 'master']]) {
      setAuth({ id: 9, tenant_id: 7, role: permitted });
      root = await mount(h(GuardRoute, { route, allowedRoles: ['supermaster', 'master'], text: `${route} allowed` }), route);
      await waitFor(() => document.body.textContent.includes(`${route} allowed`), `${route} permitted`);
      await unmount(root);
      setAuth({ id: 9, tenant_id: 7, role: 'trader' });
      root = await mount(h(GuardRoute, { route, allowedRoles: ['supermaster', 'master'], text: `${route} forbidden` }), route);
      await waitFor(() => document.body.textContent.includes('Access Denied'), `${route} forbidden`);
      assert.equal(document.body.textContent.includes(`${route} forbidden`), false);
      await unmount(root);
    }
  } finally { await unmount(root); }
});

test('UI6 financial: Wallet DOM retry/filter/page/refresh publish only acknowledged synthetic owner-bound reads', { concurrency: false }, async () => {
  const harness = financialHarness({ failFirstWallet: true });
  setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'trader' });
  let root;
  try {
    root = await mount(h(Routes, null,
      h(Route, { path: '/wallet', element: h(Wallet) }),
      h(Route, { path: '/dashboard', element: h(BackDestination) }),
    ), '/wallet');
    const failure = await waitFor(() => document.querySelector('[role="alert"]'), 'wallet synthetic error');
    await click(failure.querySelector('button'));
    await waitFor(() => document.body.textContent.includes('#101'), 'wallet retry acknowledgement');
    assert.deepEqual(harness.calls[1].options.expectedOwner, owner);
    assert.ok(harness.calls[1].options.signal instanceof AbortSignal);
    harness.transport.slice(-2).forEach((call) => assert.equal(call.config.signal, harness.calls[1].options.signal));
    for (const destination of ['/dashboard', '/documents', '/support/my-tickets', '/trader/withdrawals']) assert.ok(anchor(destination), `Wallet has exact ${destination} anchor`);

    await click(anchor('/dashboard'));
    await waitFor(() => document.querySelector('[data-location]')?.textContent === '/dashboard', 'wallet link navigation');
    await click(button('Back to records'));
    await waitFor(() => document.body.textContent.includes('#101'), 'wallet remount after MemoryRouter back');

    await selectValue(document.querySelector('#wallet-balance-type'), 'main');
    await waitFor(() => harness.transport.some((call) => call.endpoint === '/wallet/transactions' && call.config.params.balance_type === 'main'), 'wallet filter transport');
    const filtered = harness.transport.find((call) => call.endpoint === '/wallet/transactions' && call.config.params.balance_type === 'main');
    assert.deepEqual(filtered.config.params, { page: 1, per_page: 20, balance_type: 'main' });
    await click(button('Next page'));
    await waitFor(() => document.body.textContent.includes('#201'), 'wallet next acknowledgement');
    await click(button('Previous page'));
    await waitFor(() => document.body.textContent.includes('#101'), 'wallet previous acknowledgement');
    await click(button('Next page'));
    await waitFor(() => document.body.textContent.includes('#201'), 'wallet next again acknowledgement');
    await click(button('First page'));
    await waitFor(() => document.body.textContent.includes('#101'), 'wallet first acknowledgement');

    harness.hold();
    await click(document.querySelector('[aria-label="Refresh wallet records"]'));
    await waitFor(() => document.querySelector('[role="status"][aria-busy="true"]'), 'wallet loading before refresh response');
    assert.equal(document.body.textContent.includes('#101'), false, 'stale rows are hidden before acknowledgement');
    harness.release();
    await waitFor(() => document.body.textContent.includes('#101'), 'wallet refresh acknowledgement');
  } finally { harness.release(); await unmount(root); }
});

test('UI6 financial: source withdrawal pages use exact Link destinations and owner/signal-bound synthetic filter and refresh reads', { concurrency: false }, async () => {
  let root;
  try {
    let harness = financialHarness();
    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'trader' });
    root = await mount(h(TraderWithdrawals), '/trader/withdrawals');
    await waitFor(() => document.body.textContent.includes('#101'), 'trader initial response');
    for (const destination of ['/trader', '/trader/documents', '/support/my-tickets']) assert.ok(anchor(destination), `Trader withdrawals has exact ${destination} anchor`);
    await selectValue(document.querySelector('#withdrawal-status'), 'completed');
    await waitFor(() => [...document.querySelectorAll('tbody tr')].some((row) => row.textContent.includes('completed')), 'trader filtered rows');
    const traderFilter = harness.transport.find((call) => call.endpoint === '/traders/withdrawals' && call.config.params.status === 'completed');
    assert.deepEqual(traderFilter.config.params, { page: 1, per_page: 20, status: 'completed' });
    harness.hold();
    await click(document.querySelector('[aria-label="Refresh withdrawal records"]'));
    await waitFor(() => document.querySelector('[role="status"][aria-busy="true"]'), 'trader refresh loading');
    harness.release();
    await waitFor(() => [...document.querySelectorAll('tbody tr')].some((row) => row.textContent.includes('completed')), 'trader refresh acknowledgement');
    assert.deepEqual(harness.calls.at(-1).options.expectedOwner, owner);
    assert.ok(harness.calls.at(-1).options.signal instanceof AbortSignal);
    await unmount(root);

    harness = financialHarness();
    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'master' });
    root = await mount(h(AdminWithdrawals), '/admin/withdrawals');
    await waitFor(() => document.body.textContent.includes('#101'), 'admin withdrawal initial response');
    assert.ok(anchor('/admin'), 'Admin withdrawals has exact /admin anchor');
    await selectValue(document.querySelector('#admin-withdrawal-status'), 'approved');
    await waitFor(() => [...document.querySelectorAll('tbody tr')].some((row) => row.textContent.includes('approved')), 'admin filtered rows');
    const adminFilter = harness.transport.find((call) => call.endpoint === '/wallet/admin/withdrawals' && call.config.params.status === 'approved');
    assert.deepEqual(adminFilter.config.params, { page: 1, per_page: 20, status: 'approved' });
    await click(document.querySelector('[aria-label="Refresh administrative withdrawal records"]'));
    await waitFor(() => [...document.querySelectorAll('tbody tr')].some((row) => row.textContent.includes('approved')), 'admin refresh acknowledgement');
    assert.deepEqual(harness.calls.at(-1).options.expectedOwner, owner);
    assert.ok(harness.calls.at(-1).options.signal instanceof AbortSignal);
  } finally { await unmount(root); }
});

test('UI6 financial: payment DOM retry/filter/pagination/refresh and approval restriction execute source controls without a live provider', { concurrency: false }, async () => {
  let root;
  try {
    let harness = adminPaymentHarness({ failFirstPayment: true });
    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'master' });
    root = await mount(h(Payments), '/admin/payments');
    const failure = await waitFor(() => document.querySelector('[role="alert"]'), 'payment synthetic error');
    await click(failure.querySelector('button'));
    await waitFor(() => document.body.textContent.includes('synthetic-method-1-1'), 'payment retry acknowledgement');
    assert.deepEqual(harness.calls[1].options.expectedOwner, owner);
    assert.ok(harness.calls[1].options.signal instanceof AbortSignal);
    await selectValue(document.querySelector('#payment-record-status'), 'completed');
    await selectValue(document.querySelector('#payment-record-purpose'), 'withdrawal');
    await waitFor(() => [...document.querySelectorAll('tbody tr')].some((row) => row.textContent.includes('Withdrawal') && row.textContent.includes('completed')), 'payment filter acknowledgement');
    const filtered = harness.transport.find((call) => call.endpoint === '/admin/payments' && call.config.params.status === 'completed' && call.config.params.type === 'withdrawal');
    assert.deepEqual(filtered.config.params, { page: 1, per_page: 20, status: 'completed', type: 'withdrawal' });
    await click(button('Next page'));
    await waitFor(() => document.body.textContent.includes('synthetic-method-2-1'), 'payment next acknowledgement');
    await click(button('Previous page'));
    await waitFor(() => document.body.textContent.includes('synthetic-method-1-1'), 'payment previous acknowledgement');
    await click(button('Next page'));
    await waitFor(() => document.body.textContent.includes('synthetic-method-2-1'), 'payment next again acknowledgement');
    await click(button('First page'));
    await waitFor(() => document.body.textContent.includes('synthetic-method-1-1'), 'payment first acknowledgement');
    harness.hold();
    await click(button('Refresh records'));
    await waitFor(() => document.querySelector('[role="status"][aria-busy="true"]'), 'payment refresh loading');
    harness.release();
    await waitFor(() => document.body.textContent.includes('synthetic-method-1-1'), 'payment refresh acknowledgement');
    await unmount(root);

    harness = adminPaymentHarness();
    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'master' });
    root = await mount(h(PaymentApprovals), '/admin/payment-approvals');
    await waitFor(() => document.querySelector('[role="alert"]'), 'master approval restriction');
    assert.equal(harness.calls.length, 0, 'restricted master page sends no approval request');
    assert.equal(document.querySelectorAll('button').length, 0, 'restriction exposes no fake approval action');
    await unmount(root);

    harness = adminPaymentHarness();
    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'supermaster' });
    root = await mount(h(PaymentApprovals), '/admin/payment-approvals');
    await waitFor(() => document.body.textContent.includes('Pending legacy approval requests'), 'supermaster approval response');
    await waitFor(() => document.querySelector('tbody tr'), 'approval rows');
    harness.hold();
    await click(button('Refresh records'));
    await waitFor(() => document.querySelector('[role="status"][aria-busy="true"]'), 'approval refresh loading');
    harness.release();
    await waitFor(() => document.querySelector('tbody tr'), 'approval refresh acknowledgement');
    assert.deepEqual(harness.calls.at(-1).options.expectedOwner, owner);
    assert.ok(harness.calls.at(-1).options.signal instanceof AbortSignal);
  } finally { await unmount(root); }
});

test('UI6 financial: source pages distinguish synthetic missing and empty records without inventing a financial outcome', { concurrency: false }, async () => {
  let root;
  try {
    financialHarness({ missingWallet: true });
    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'trader' });
    root = await mount(h(Wallet), '/wallet');
    await waitFor(() => document.body.textContent.includes('No legacy wallet record was found'), 'canonical wallet missing view');
    assert.equal(document.body.textContent.includes('Recorded wallet transactions'), false);
    await unmount(root);

    financialHarness({ empty: true });
    root = await mount(h(Wallet), '/wallet');
    await waitFor(() => document.body.textContent.includes('No wallet transactions were returned for this page'), 'wallet empty view');
    await unmount(root);
    root = await mount(h(TraderWithdrawals), '/trader/withdrawals');
    await waitFor(() => document.body.textContent.includes('No withdrawal records were returned for this page'), 'trader empty view');
    await unmount(root);

    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'master' });
    root = await mount(h(AdminWithdrawals), '/admin/withdrawals');
    await waitFor(() => document.body.textContent.includes('No scoped withdrawal records were returned for this page'), 'admin withdrawal empty view');
    await unmount(root);

    adminPaymentHarness({ empty: true });
    root = await mount(h(Payments), '/admin/payments');
    await waitFor(() => document.body.textContent.includes('No recorded payment records'), 'payment empty view');
    await unmount(root);
    setAuth({ id: owner.user_id, tenant_id: owner.tenant_id, role: 'supermaster' });
    root = await mount(h(PaymentApprovals), '/admin/payment-approvals');
    await waitFor(() => document.body.textContent.includes('No pending legacy requests'), 'approval empty view');
  } finally { await unmount(root); }
});

test('UI6 financial: FinancialPagination Last available page click changes DOM only after the synthetic page acknowledgement', { concurrency: false }, async () => {
  const syntheticPageService = { load: async ({ expectedOwner, page }) => ({ owner: expectedOwner, page }) };
  function Harness() {
    const [page, setPage] = React.useState(3);
    const [ack, setAck] = React.useState('waiting');
    const onPage = (next) => syntheticPageService.load({ expectedOwner: owner, page: next }).then((response) => {
      assert.deepEqual(response.owner, owner); setPage(response.page); setAck(`acknowledged page ${response.page}`);
    });
    return h(React.Fragment, null,
      h(financialUi.module.FinancialPagination, { pagination: { page, per_page: 20, total: 40, pages: 2 }, onPage }),
      h('output', { 'data-ack': 'page' }, ack),
    );
  }
  let root;
  try {
    root = await mount(h(Harness));
    await click(button('Last available page'));
    await waitFor(() => document.querySelector('[data-ack="page"]')?.textContent === 'acknowledged page 2', 'last page acknowledgement');
    assert.match(document.body.textContent, /Page 2/);
  } finally { await unmount(root); }
});

test.after(() => {
  delete globalThis.__ui6FinancialActive;
  delete globalThis.__ui6AdminPaymentActive;
  delete globalThis.__ui6FinancialService;
  delete globalThis.__ui6AdminPaymentService;
  fs.rmSync(temporary, { recursive: true, force: true });
  dom.window.close();
});
