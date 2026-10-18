import { compilePaymentHarness } from './paymentHarness.js';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';
import React, { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'customer-dashboard-'));
const sourceUrl = new URL('../src/pages/user/UserDashboard.jsx', import.meta.url);
const serviceUrl = new URL('../src/services/userDashboardViewService.js', import.meta.url).href;
const profileServiceUrl = new URL('../src/services/profileViewService.js', import.meta.url).href;
const accountSetupServiceUrl = new URL('../src/services/accountSetupViewService.js', import.meta.url).href;
const guideSourceUrl = new URL('../src/components/account/AccountSetupGuide.jsx', import.meta.url);
const policyModuleUrl = new URL('../src/services/programEvaluationPolicy.js', import.meta.url).href;
const policyOverride = {
  'services/programEvaluationPolicy.js': `export * from ${JSON.stringify(policyModuleUrl)};`,
};
const external = Object.fromEntries(['react', 'react/jsx-runtime', 'lucide-react', 'react-router-dom'].map((name) => [name, pathToFileURL(require.resolve(name)).href]));
const resolve = (text) => Object.entries(external).reduce((s, [name, url]) => s.replaceAll(`from '${name}'`, `from ${JSON.stringify(url)}`).replaceAll(`from "${name}"`, `from ${JSON.stringify(url)}`), text);
const guideSource = fs.readFileSync(guideSourceUrl, 'utf8')
  .replace("'../../services/accountSetupViewService.js'", JSON.stringify(accountSetupServiceUrl));
const guideCode = await transformWithEsbuild(resolve(guideSource), guideSourceUrl.pathname, { loader: 'jsx', jsx: 'automatic' });
const guidePath = path.join(tmp, 'account-setup-guide.mjs');
fs.writeFileSync(guidePath, resolve(guideCode.code));
const guideUrl = pathToFileURL(guidePath).href;
const purchaseBuild = await compilePaymentHarness(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url), {
  prefix: 'customer-dashboard-payment',
  overrides: policyOverride,
});
const purchaseBuildUrl = purchaseBuild.targets.get(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url).pathname);
test.after(() => purchaseBuild.cleanup());
const source = fs.readFileSync(sourceUrl, 'utf8')
  .replace(/import useAuthStore from ['"]\.\.\/\.\.\/store\/authStore['"];/, 'const useAuthStore = () => null;')
  .replace("import api, { profileAPI } from '../../services/api';", "const api = { get: () => Promise.reject(new Error('synthetic API only')) }; const profileAPI = { get: () => Promise.reject(new Error('synthetic API only')) };")
  .replace("import AccountSetupGuide from '../../components/account/AccountSetupGuide';", `import AccountSetupGuide from ${JSON.stringify(guideUrl)};`)
  .replace("import ProgramPurchaseRecords from '../../components/payments/ProgramPurchaseRecords';", `import ProgramPurchaseRecords from ${JSON.stringify(purchaseBuildUrl)};`)
  .replace("import { createProfileApiTransport } from '../../services/profileViewService';", `import { createProfileApiTransport } from ${JSON.stringify(profileServiceUrl)};`)
  .replace("import { createAccountSetupViewService } from '../../services/accountSetupViewService';", `import { createAccountSetupViewService } from ${JSON.stringify(accountSetupServiceUrl)};`)
  .replace(/['"]\.\.\/\.\.\/services\/userDashboardViewService['"]/g, JSON.stringify(serviceUrl));
const code = await transformWithEsbuild(resolve(source), sourceUrl.pathname, { loader: 'jsx', jsx: 'automatic' });
const modulePath = path.join(tmp, 'dashboard.mjs');
fs.writeFileSync(modulePath, resolve(code.code));
const ui = await import(pathToFileURL(modulePath).href);
const { normalizeUserDashboard } = await import(serviceUrl);
const bootstrap = new JSDOM('<!doctype html><body></body>');
Object.defineProperty(globalThis, 'window', { configurable: true, writable: true, value: bootstrap.window });
Object.defineProperty(globalThis, 'document', { configurable: true, writable: true, value: bootstrap.window.document });
const { createRoot } = await import('react-dom/client');
delete globalThis.window; delete globalThis.document; bootstrap.window.close();
function harness() {
  const d = new JSDOM('<!doctype html><body><div id="root"></div></body>', { url: 'https://isolated.invalid/' });
  const before = new Map();
  for (const [key, value] of Object.entries({ window: d.window, document: d.window.document, navigator: d.window.navigator, HTMLElement: d.window.HTMLElement, Node: d.window.Node, IS_REACT_ACT_ENVIRONMENT: true })) {
    before.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const host = d.window.document.getElementById('root');
  const root = createRoot(host);
  return { host, root, async render(component) { await act(async () => root.render(React.createElement(MemoryRouter, null, component))); }, async close() { await act(async () => root.unmount()); for (const [key, descriptor] of before) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; } d.window.close(); } };
}
const click = async (node) => { assert.ok(node); await act(async () => node.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))); };
function payload(id = 1, { name = 'Recorded owner', count = 1 } = {}) {
  return {
    owner_context: { user_id: id, tenant_id: 10 }, user: { id, tenant_id: 10, role: 'user', first_name: name },
    statistics: { status_counts: { total: count, pending: 0, active: count, passed: 0, failed: 0, funded: 0 }, status_counts_data_status: 'recorded_legacy_statuses', success_rate: null, success_rate_data_status: 'unavailable_no_recorded_outcomes', total_profit: null, total_profit_data_status: 'unavailable_no_verified_provenance', total_spent: null, total_spent_data_status: 'unavailable_no_verified_provenance', data_quality: 'legacy_unverified' },
    recent_challenges: count ? [{ id: 11, user_id: id, program_name: 'Recorded challenge', status: 'active', status_data_status: 'recorded_not_verified', phase: null, total_phases: null, initial_balance: null, current_balance: '9999999999999999.123456789', balance_data_quality: 'legacy_unverified', profit: '0.00', profit_data_status: 'recorded_not_verified', progress: null, progress_data_status: 'unavailable_no_approved_rule_source', created_at: null, currency: null }] : [],
    data_quality: { challenge_statuses: 'legacy_unverified', trading_balances: 'legacy_unverified', financial_totals: 'unavailable_no_verified_provenance', provider_verification: 'not_available' },
  };
}
const view = (id = 1, options = {}) => normalizeUserDashboard(payload(id, options), { expectedOwner: { userId: id, tenantId: 10 }, role: 'user' });
const overview = (dashboard) => React.createElement(ui.DashboardOverview, { dashboard, onRefresh: () => {} });
const syntheticSetupService = {
  loadProfile: async () => ({ recordedFields: ['First name'], missingFields: ['Last name', 'Email address', 'Phone number'] }),
  loadDocuments: async () => ({ documentTypesShown: 3, documents: [], recordedCount: 0, allRequestedRecordsPresent: false, hasRejectedRecord: false }),
};

test('customer guide offers real next destinations without asserting profile completeness, KYC or funding', async () => {
  const h = harness();
  try {
    await h.render(overview(view(1, { name: null, count: 0 })));
    const guide = h.host.querySelector('[aria-labelledby="getting-started-heading"]');
    assert.match(guide.textContent, /Profile record is unavailable/);
    assert.match(guide.textContent, /Document records are unavailable/);
    assert.match(guide.textContent, /current catalog/);
    assert.match(guide.textContent, /MT5 and KYC-provider capabilities are unavailable from this account workspace\. Payment availability is checked separately in an order checkout; a stored purchase does not activate trading or payouts\./);
    assert.deepEqual([...guide.querySelectorAll('[data-setup-step] a')].map((a) => a.getAttribute('href')), ['/profile', '/documents', '/programs', '/support/create-ticket']);
    assert.equal(guide.querySelector('[aria-labelledby="setup-next-action-heading"] a').getAttribute('href'), '/profile');
    assert.equal(guide.querySelectorAll('input,[role="progressbar"]').length, 0);
    const toggle = guide.querySelector('[aria-controls="account-starting-guide"]');
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    await click(toggle); assert.equal(guide.querySelector('#account-starting-guide'), null);
    await click(toggle); assert.ok(guide.querySelector('#account-starting-guide'));
    assert.doesNotMatch(guide.textContent, /profile complete|verified identity|approved KYC|eligible payout/i);
    assert.doesNotMatch(guide.textContent, /trading (?:account )?activated|payouts? enabled|payment enables trading/i);
  } finally { await h.close(); }
});

test('guide switches using recorded counts only and resets its local collapse state on identity change', async () => {
  const h = harness();
  try {
    await h.render(overview(view()));
    let guide = h.host.querySelector('[aria-labelledby="getting-started-heading"]');
    assert.equal(guide.querySelectorAll('[data-setup-step] a')[2].getAttribute('href'), '/challenges');
    await click(guide.querySelector('[aria-controls="account-starting-guide"]'));
    await h.render(overview(view(2, { name: 'Second owner', count: 0 })));
    guide = h.host.querySelector('[aria-labelledby="getting-started-heading"]');
    assert.equal(guide.querySelector('[aria-controls="account-starting-guide"]').getAttribute('aria-expanded'), 'true');
    assert.equal(guide.querySelectorAll('[data-setup-step] a')[2].getAttribute('href'), '/programs');
    assert.doesNotMatch(h.host.textContent, /Recorded owner/);
    assert.equal(h.host.querySelectorAll('table').length, 0);
  } finally { await h.close(); }
});

test('mobile challenge cards and desktop table preserve exact recorded decimals, nulls and real links without currency inference', async () => {
  const h = harness();
  try {
    await h.render(overview(view()));
    const cards = h.host.querySelector('[aria-label="Latest recorded challenge cards"]');
    assert.match(cards.textContent, /9,999,999,999,999,999\.123456789/);
    assert.match(cards.textContent, /0\.00/);
    assert.match(cards.textContent, /Phase unavailable/);
    assert.match(cards.textContent, /Currency unavailable/);
    assert.match(cards.textContent, /ProgressUnavailable/);
    assert.equal(cards.querySelector('a').getAttribute('href'), '/challenges/11');
    assert.ok(cards.classList.contains('md:hidden'));
    const table = h.host.querySelector('[aria-label="Latest recorded challenges table"]');
    assert.ok(table.classList.contains('hidden')); assert.ok(table.classList.contains('md:block'));
    assert.match(table.textContent, /9,999,999,999,999,999\.123456789/);
    assert.doesNotMatch(h.host.textContent, /\$|Live balance|KYC approved|100% complete/);
  } finally { await h.close(); }
});

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const data = (id, client) => React.createElement(ui.UserDashboardData, { key: `true:${id}:10:user`, userId: id, tenantId: 10, role: 'user', apiClient: client, accountSetupService: syntheticSetupService });
test('dashboard enhancement performs one owner-bound read, aborts prior identity and never exposes late owner data or guide', async () => {
  const h = harness();
  const reads = [];
  const client = { get: (url, config) => { const pending = deferred(); reads.push({ url, config, pending }); return pending.promise; } };
  try {
    await h.render(data(1, client)); assert.equal(reads.length, 1); assert.equal(reads[0].url, '/users/dashboard');
    assert.equal(h.host.querySelector('[aria-labelledby="getting-started-heading"]'), null);
    await h.render(data(2, client)); assert.equal(reads.length, 2); assert.equal(reads[0].config.signal.aborted, true);
    await act(async () => reads[0].pending.resolve({ data: payload(1) }));
    assert.doesNotMatch(h.host.textContent, /Recorded owner/);
    await act(async () => reads[1].pending.resolve({ data: payload(2, { name: 'Second owner', count: 0 }) }));
    assert.match(h.host.textContent, /Second owner/); assert.ok(h.host.querySelector('[aria-labelledby="getting-started-heading"]'));
    assert.equal(reads.length, 3); assert.equal(reads[2].url, '/orders/purchases', 'one local owner-bound purchase collection read');
    await click(h.host.querySelector('[aria-controls="account-starting-guide"]')); assert.equal(reads.length, 3);
    await click([...h.host.querySelectorAll('button')].find((button) => button.textContent.includes('Refresh records')));
    assert.equal(reads.length, 4); assert.equal(reads[3].url, '/users/dashboard'); assert.equal(reads[2].config.signal.aborted, true); assert.equal(h.host.querySelector('[aria-labelledby="getting-started-heading"]'), null);
    await act(async () => reads[3].pending.reject(new Error('Synthetic timeout')));
    assert.match(h.host.textContent, /could not be verified/); assert.equal(h.host.querySelector('table'), null);
  } finally { await h.close(); }
});

test('owner mismatch remains fail-closed before customer enhancements are rendered', async () => {
  const h = harness();
  try {
    await h.render(data(2, { get: async () => ({ data: payload(1) }) }));
    assert.match(h.host.textContent, /could not be verified/);
    assert.equal(h.host.querySelector('[aria-labelledby="getting-started-heading"]'), null);
    assert.equal(h.host.querySelector('[aria-label="Latest recorded challenge cards"]'), null);
  } finally { await h.close(); }
});
test.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
