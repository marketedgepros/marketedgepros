import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { compilePaymentHarness, purchaseRecordsFixture } from './paymentHarness.js';
import { mapOrderQuoteResponse, normalizeQuoteContext } from '../src/services/orderQuoteViewService.js';
import * as service from '../src/services/orderPaymentViewService.js';

const policyModuleUrl = new URL('../src/services/programEvaluationPolicy.js', import.meta.url).href;
const policyOverride = {
  'services/programEvaluationPolicy.js': `export * from ${JSON.stringify(policyModuleUrl)};`,
};
const principal = { id: 2, tenant_id: 1, role: 'trader' };
const orderId = '00000000-0000-4000-8000-000000000012';
const address = 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb';
const terms = { name: 'Synthetic program', type: 'one_phase', description: null, account_size: '10000.00', profit_target: null, max_daily_loss: null, max_total_loss: null, profit_split: null, profit_split_percentage: null, minimum_payout_amount: null, payout_mode: null, rules: {} };
const instantTerms = { ...terms, name: 'Instant Funding historical record', type: 'instant_funding', profit_target: '0.00', max_daily_loss: '5.00', max_total_loss: '10.00', profit_split: '90.00', profit_split_percentage: '90.00', rules: { drawdown_type: 'static' } };
const quotePayload = ({ programId = 12, quoteTerms = terms } = {}) => ({ replayed: false, order: { id: orderId, user_id: 2, tenant_id: 1, program_id: programId, amount_minor: '1999', amount: '19.99', currency: 'USD', state: 'quoted', paid: false, snapshot_hash: 'a'.repeat(64), snapshot: { schema: 1, kind: 'purchase_quote', program_id: programId, user_id: 2, tenant_id: 1, currency: 'USD', amount: '19.99', base_amount: '19.99', entitlement: false, addons: [], terms: quoteTerms } } });
const quote = () => mapOrderQuoteResponse(quotePayload(), normalizeQuoteContext(12, []));
const cap = (enabled = true, owner = principal) => ({ schema_version: 1, owner_context: { user_id: owner.id, tenant_id: owner.tenant_id, role: owner.role }, enabled, reason: enabled ? null : 'PILOT_DISABLED', quote_currency: 'USD', currencies: enabled ? [{ code: 'usdttrc20', label: 'USDT', network: 'TRC20', decimals: 6 }] : [], fee_paid_by_user: enabled ? false : null, policy_version: enabled ? 'synthetic-v1' : null, live_trading_enabled: false });
const projection = (state = 'not_started', owner = principal) => ({ schema_version: 1, owner_context: { user_id: owner.id, tenant_id: owner.tenant_id, role: owner.role }, order_id: orderId, program_id: 12, quote_amount_minor: '1999', quote_currency: 'USD', state, paid: state === 'paid', recorded_purchase: state === 'paid', review_required: state === 'manual_review', creation_attempted: state !== 'not_started', can_create: state === 'not_started', can_refresh: !['not_started', 'creation_uncertain'].includes(state), provider_status: state === 'paid' ? 'finished' : state === 'awaiting_payment' ? 'waiting' : state === 'processing' ? 'confirming' : null, payment: ['not_started', 'creation_uncertain'].includes(state) ? null : { provider: 'nowpayments', provider_payment_id: '123456789', pay_amount: '20.000000', pay_currency: 'usdttrc20', label: 'USDT', network: 'TRC20', decimals: 6, pay_address: address, memo: null, expires_at: '2030-01-01T00:00:00Z', actually_paid: state === 'paid' ? '20.000000' : null, outcome_amount: state === 'paid' ? '19.800000' : null, outcome_currency: state === 'paid' ? 'usdttrc20' : null, fee_paid_by_user: false }, reason: null, policy_version: 'synthetic-v1', updated_at: '2026-10-13T10:00:00Z', replayed: false });
const purchaseRow = () => ({ order_id: orderId, program_id: 12, program_name: 'Synthetic program', user_id: 2, tenant_id: 1, state: 'paid', paid: true, recorded_purchase: true, review_required: false, quote_amount_minor: '1999', quote_currency: 'USD', provider_payment_id: '123456789', pay_currency: 'usdttrc20', network: 'TRC20', actually_paid: '20.000000', outcome_amount: '19.800000', outcome_currency: 'usdttrc20', updated_at: '2026-10-13T10:00:00Z' });
const records = () => ({ ...purchaseRecordsFixture(2, 1, 'trader'), records: [purchaseRow()], pagination: { page: 1, per_page: 20, total: 1, pages: 1, has_next: false, has_prev: false } });
const catalog = (id = 12, programTerms = terms) => ({ id, tenant_id: 1, currency: 'USD', is_active: true, price: '19.99', ...programTerms, terms: programTerms, addons: [] });

for (const mutate of [x => x.owner_context.user_id++, x => x.owner_context.tenant_id++, x => x.owner_context.role = 'affiliate', x => x.enabled = 'true', x => x.live_trading_enabled = true, x => x.currencies[0].network = 'ERC20', x => x.fee_paid_by_user = true]) {
  test(`payment capability refuses mismatched or unapproved contract ${mutate.toString()}`, () => { const payload = cap(); mutate(payload); assert.throws(() => service.mapPaymentCapabilities(payload, principal), service.OrderPaymentContractError); });
}
test('payment mapper preserves separate quote, exact deposit, final outcome, null and independent currency', () => {
  const payload = projection('paid'); payload.payment.outcome_currency = 'usdt';
  const value = service.mapOrderPayment(payload, { quote: quote(), principal });
  assert.equal(value.amountMinor, '1999'); assert.equal(value.payment.payAmount, '20.000000'); assert.equal(value.payment.actuallyPaid, '20.000000'); assert.equal(value.payment.outcomeAmount, '19.800000'); assert.equal(value.payment.outcomeCurrency, 'usdt');
  assert.equal(service.mapOrderPayment(projection('awaiting_payment'), { quote: quote(), principal }).payment.actuallyPaid, null);
});
for (const mutate of [x => x.quote_amount_minor = '2000', x => x.order_id = '00000000-0000-4000-8000-000000000013', x => x.payment.actually_paid = '19.999999', x => x.payment.actually_paid = '20.000001', x => x.payment.pay_amount = 20, x => x.payment.outcome_amount = '0', x => x.provider_status = 'confirming', x => x.review_required = true, x => x.payment.network = 'ERC20', x => x.payment.decimals = 18, x => x.payment.provider_payment_id = 'attacker', x => x.can_create = true]) {
  test(`paid purchase refuses inconsistent evidence ${mutate.toString()}`, () => { const payload = projection('paid'); mutate(payload); assert.throws(() => service.mapOrderPayment(payload, { quote: quote(), principal }), service.OrderPaymentContractError); });
}
test('create payload contains only allowed asset, one key, bounded timeout and disables automatic auth replay', async () => {
  const calls = []; const client = { post: async (...args) => { calls.push(args); return { data: projection('awaiting_payment') }; } };
  await service.createOrderPayment({ principal, quote: quote(), payCurrency: 'usdttrc20', idempotencyKey: 'synthetic_payment_key_0001', client });
  assert.equal(calls.length, 1); assert.deepEqual(calls[0][1], { pay_currency: 'usdttrc20' }); assert.equal(calls[0][2]._skipAuthRefresh, true); assert.equal(calls[0][2].timeout, 25000);
  await assert.rejects(service.createOrderPayment({ principal, quote: quote(), payCurrency: 'btc', idempotencyKey: 'synthetic_payment_key_0001', client })); assert.equal(calls.length, 1);
});
test('saved order read validates program and both snapshot/current owner before exposing terms', async () => {
  const client = { get: async () => ({ data: quotePayload() }) };
  assert.equal((await service.readStoredPurchaseQuote({ orderId, programId: 12, principal, client })).order.id, orderId);
  await assert.rejects(service.readStoredPurchaseQuote({ orderId, programId: 13, principal, client }));
  await assert.rejects(service.readStoredPurchaseQuote({ orderId, programId: 12, principal: { ...principal, tenant_id: 2 }, client }));
});
test('collections enforce own owner and tenant, preserve absent source rather than financial zero, and reject duplicate rows', () => {
  assert.equal(service.mapPurchaseRecords(records(), principal).records[0].actuallyPaid, '20.000000');
  const wrong = records(); wrong.records[0].user_id = 3; assert.throws(() => service.mapPurchaseRecords(wrong, principal));
  const wrongBrand = records(); wrongBrand.records[0].tenant_id = 2; assert.throws(() => service.mapPurchaseRecords(wrongBrand, principal, { ownOnly: false }));
  const missing = purchaseRecordsFixture(2, 1, 'trader'); missing.availability = false; missing.source_unavailable = true; missing.reason = 'SCHEMA_UNAVAILABLE'; assert.equal(service.mapPurchaseRecords(missing, principal).available, false);
  const duplicate = records(); duplicate.records.push(purchaseRow()); duplicate.pagination.total = 2; assert.throws(() => service.mapPurchaseRecords(duplicate, principal));
});

const panelBuild = await compilePaymentHarness(new URL('../src/components/payments/OrderPaymentPanel.jsx', import.meta.url), { prefix: 'payment-panel-contract', overrides: policyOverride });
const recordsBuild = await compilePaymentHarness(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url), { prefix: 'payment-record-contract', overrides: policyOverride });
const checkoutBuild = await compilePaymentHarness(new URL('../src/pages/Checkout.jsx', import.meta.url), { prefix: 'payment-checkout-contract', overrides: policyOverride });
const Panel = panelBuild.module.default, Records = recordsBuild.module.default, Checkout = checkoutBuild.module.default;
const bootstrap = new JSDOM('<body></body>');
Object.defineProperty(globalThis, 'window', { configurable: true, writable: true, value: bootstrap.window }); Object.defineProperty(globalThis, 'document', { configurable: true, writable: true, value: bootstrap.window.document });
const { createRoot } = await import('react-dom/client'); delete globalThis.window; delete globalThis.document; bootstrap.window.close();
const Location = () => { const location = useLocation(); return React.createElement('output', { 'data-location': true }, location.pathname + location.search); };
function harness(entry = '/') {
  const dom = new JSDOM('<body><div id="root"></div></body>', { url: 'https://synthetic.invalid/' }), before = new Map();
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document, navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node, IS_REACT_ACT_ENVIRONMENT: true })) { before.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, { configurable: true, writable: true, value }); }
  const host = document.getElementById('root'), root = createRoot(host);
  return { host, async render(element) { await act(async () => root.render(React.createElement(MemoryRouter, { initialEntries: [entry] }, element))); }, async close() { await act(async () => root.unmount()); for (const [key, value] of before) { if (value) Object.defineProperty(globalThis, key, value); else delete globalThis[key]; } dom.window.close(); delete globalThis.__payment_client; delete globalThis.__payment_auth; } };
}
const click = async node => { assert.ok(node); await act(async () => node.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))); };
const button = (host, text) => [...host.querySelectorAll('button')].find(node => node.textContent.includes(text));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const router = () => React.createElement(React.Fragment, null, React.createElement(Location), React.createElement(Routes, null, React.createElement(Route, { path: '/programs/:programId/checkout', element: React.createElement(Checkout) }), React.createElement(Route, { path: '/login', element: React.createElement('h1', null, 'Synthetic login') })));

test('mount performs only two local reads, never creates payment, and explicit confirmation precedes one POST', async () => {
  const h = harness(), calls = [];
  const client = { get: async url => { calls.push(['GET', url]); return { data: url.includes('capabilities') ? cap() : projection() }; }, post: async (...args) => { calls.push(['POST', ...args]); return { data: projection('awaiting_payment') }; } };
  try {
    await h.render(React.createElement(Panel, { principal, quote: quote(), client })); assert.equal(calls.length, 2); assert.equal(calls.filter(x => x[0] === 'POST').length, 0);
    const create = button(h.host, 'Create payment details'); assert.equal(create.disabled, true);
    await click(h.host.querySelector('input[type="checkbox"]')); await click(create);
    assert.equal(calls.filter(x => x[0] === 'POST').length, 1); assert.match(h.host.textContent, /20\.000000/); assert.match(h.host.textContent, /TRC20/); assert.equal(button(h.host, 'Create payment details'), undefined);
    await click(button(h.host, 'Check saved order')); assert.equal(calls.filter(x => x[0] === 'POST').length, 1); assert.equal(button(h.host, 'Create payment details'), undefined, 'a local not-started read cannot erase this mount’s creation attempt');
  } finally { await h.close(); }
});
test('uncertain POST is not retried; saved-order reads can recover a valid receipt without another create', async () => {
  const h = harness(); let paid = false, posts = 0;
  const client = { get: async url => ({ data: url.includes('capabilities') ? cap() : projection(paid ? 'paid' : 'not_started') }), post: async () => { posts++; throw new Error('Synthetic timeout'); } };
  try { await h.render(React.createElement(Panel, { principal, quote: quote(), client })); await click(h.host.querySelector('input')); await click(button(h.host, 'Create payment details')); assert.equal(posts, 1); assert.match(h.host.textContent, /Do not pay twice/); assert.equal(button(h.host, 'Create payment details'), undefined); paid = true; await click(button(h.host, 'Check saved order')); assert.match(h.host.textContent, /Purchase recorded/); assert.equal(posts, 1); assert.equal(button(h.host, 'Copy exact amount').disabled, true); } finally { await h.close(); }
});
test('expired and manual-review payment details are references only and copy actions cannot instruct another deposit', async () => {
  for (const state of ['expired', 'manual_review', 'processing', 'paid']) {
    const h = harness(); const payload = projection(state);
    try { await h.render(React.createElement(Panel, { principal, quote: quote(), client: { get: async url => ({ data: url.includes('capabilities') ? cap(false) : payload }) } })); assert.equal(button(h.host, 'Copy exact amount').disabled, true); assert.match(h.host.textContent, /stored reference, not an instruction/); assert.equal(button(h.host, 'Create payment details'), undefined); } finally { await h.close(); }
  }
});
test('owner change immediately hides prior address and late response cannot return it', async () => {
  const h = harness(), held = deferred(); let owner = principal;
  const client = { get: url => url.includes('capabilities') ? Promise.resolve({ data: cap(true, owner) }) : held.promise };
  try { await h.render(React.createElement(Panel, { principal, quote: quote(), client })); owner = { ...principal, id: 3 }; const oldQuote = quote(); const nextQuote = { ...oldQuote, order: { ...oldQuote.order, userId: 3 } }; await h.render(React.createElement(Panel, { principal: owner, quote: nextQuote, client })); await act(async () => held.resolve({ data: projection('awaiting_payment') })); assert.equal(h.host.textContent.includes(address), false); assert.equal(button(h.host, 'Create payment details'), undefined); } finally { await h.close(); }
});
test('saved purchase records link to a canonical owned order and never imply live trading or a wallet balance', async () => {
  const h = harness(), calls = [];
  try { await h.render(React.createElement(Records, { principal, client: { get: async (...args) => { calls.push(args); return { data: records() }; } } })); assert.equal(calls.length, 1); assert.equal(calls[0][0], '/orders/purchases'); assert.equal(h.host.querySelector('a').getAttribute('href'), `/programs/12/checkout?order=${orderId}`); assert.match(h.host.textContent, /not a wallet balance/); assert.match(h.host.textContent, /19\.800000 usdttrc20/); assert.equal(button(h.host, 'Next purchase page').disabled, true); } finally { await h.close(); }
});
test('saved order restores its frozen quote even when its program is unavailable, with no quote or payment POST', async () => {
  const h = harness(`/programs/12/checkout?order=${orderId}&payment-requested=1&success=true`), calls = [];
  globalThis.__payment_auth = { user: principal, isAuthenticated: true, isLoading: false };
  globalThis.__payment_client = { get: async url => { calls.push(['GET', url]); if (url === '/programs/12') throw { response: { status: 404 } }; return { data: url.endsWith('/payment') ? projection('awaiting_payment') : url.includes('capabilities') ? cap() : quotePayload() }; }, post: async url => { calls.push(['POST', url]); throw new Error('Unexpected POST'); } };
  try { await h.render(router()); assert.match(h.host.textContent, /Current catalog is unavailable|current catalog is unavailable/); assert.match(h.host.textContent, /Immutable quote summary/); assert.match(h.host.textContent, /Awaiting your payment/); assert.equal(calls.filter(x => x[0] === 'POST').length, 0); assert.equal(h.host.querySelector('[data-state="paid"]'), null); await click(button(h.host, 'Reload saved quote')); assert.equal(calls.filter(x => x[0] === 'POST').length, 0); } finally { await h.close(); }
});
test('normal checkout requests one frozen quote, does not create payment automatically and focuses new payment heading', async () => {
  const h = harness('/programs/12/checkout'), calls = [];
  globalThis.__payment_auth = { user: principal, isAuthenticated: true, isLoading: false };
  globalThis.__payment_client = { get: async url => { calls.push(['GET', url]); return { data: url === '/programs/12' ? catalog() : url.includes('capabilities') ? cap(false) : projection() }; }, post: async url => { calls.push(['POST', url]); assert.equal(url, '/orders/'); return { data: quotePayload() }; } };
  try { await h.render(router()); await click(button(h.host, 'Request server quote')); assert.equal(calls.filter(x => x[0] === 'POST').length, 1); assert.equal(document.activeElement?.id, 'order-payment-title'); assert.match(h.host.textContent, /Quotes only\. Payments are not enabled/); assert.equal(h.host.querySelector('[aria-current="step"]').textContent.includes('Server quote'), true); } finally { await h.close(); }
});
test('direct Instant Funding checkout is Coming soon with no displayed price, quote request or payment creation', async () => {
  const h = harness('/programs/3711/checkout'), calls = [];
  globalThis.__payment_auth = { user: principal, isAuthenticated: true, isLoading: false };
  globalThis.__payment_client = {
    get: async (url) => { calls.push(['GET', url]); assert.equal(url, '/programs/3711'); return { data: catalog(3711, instantTerms) }; },
    post: async (url) => { calls.push(['POST', url]); throw new Error('Instant Funding must not post'); },
  };
  try {
    await h.render(router());
    assert.match(h.host.textContent, /Instant Funding/);
    assert.match(h.host.textContent, /Coming soon/);
    assert.match(h.host.textContent, /not available for purchase, quote requests or new payments/);
    assert.doesNotMatch(h.host.textContent, /USD 19\.99|Request server quote|Create payment details/);
    assert.equal(calls.filter(([method]) => method === 'POST').length, 0);
    assert.deepEqual(calls, [['GET', '/programs/3711']]);
  } finally { await h.close(); }
});
test('saved Instant Funding quote remains an immutable historical read with old values and no new payment provider request', async () => {
  const h = harness(`/programs/3711/checkout?order=${orderId}`), calls = [];
  globalThis.__payment_auth = { user: principal, isAuthenticated: true, isLoading: false };
  globalThis.__payment_client = {
    get: async (url) => {
      calls.push(['GET', url]);
      if (url === '/programs/3711') return { data: catalog(3711, instantTerms) };
      if (url.includes('/payment')) throw new Error('A historical Instant quote must not ask a provider for payment details');
      return { data: quotePayload({ programId: 3711, quoteTerms: instantTerms }) };
    },
    post: async (url) => { calls.push(['POST', url]); throw new Error('Historical Instant Funding must not post'); },
  };
  try {
    await h.render(router());
    await act(async () => { await Promise.resolve(); });
    assert.match(h.host.textContent, /Immutable quote summary/);
    assert.match(h.host.textContent, /Instant Funding historical record/);
    assert.match(h.host.textContent, /USD 19\.99/);
    assert.match(h.host.textContent, /No new payment is available for Instant Funding/);
    assert.match(h.host.textContent, /0%/);
    assert.equal(button(h.host, 'Create payment details'), undefined);
    assert.equal(calls.filter(([method]) => method === 'POST').length, 0);
    assert.equal(calls.some(([, url]) => url.includes('/payment')), false);
  } finally { await h.close(); }
});
test('guest login preserves the exact saved-order path rather than fabricating purchase status', async () => {
  const h = harness(`/programs/12/checkout?order=${orderId}`);
  globalThis.__payment_auth = { user: null, isAuthenticated: false, isLoading: false };
  globalThis.__payment_client = { get: async () => ({ data: catalog() }) };
  try { await h.render(router()); const location = h.host.querySelector('[data-location]').textContent; const url = new URL(location, 'https://synthetic.invalid'); assert.equal(url.pathname, '/login'); assert.equal(url.searchParams.get('redirect'), `/programs/12/checkout?order=${orderId}`); assert.equal(h.host.querySelector('[data-state="paid"]'), null); } finally { await h.close(); }
});
test('payment CSS reuses short finite motion and disables it for reduced motion; no perpetual/polling animation', () => {
  const css = fs.readFileSync(new URL('../src/components/payments/paymentFlow.css', import.meta.url), 'utf8'); assert.match(css, /prefers-reduced-motion:\s*reduce/); assert.doesNotMatch(css, /infinite|backdrop-filter|@import/);
  const panel = fs.readFileSync(new URL('../src/components/payments/OrderPaymentPanel.jsx', import.meta.url), 'utf8'); assert.doesNotMatch(panel, /setInterval|requestAnimationFrame/); assert.match(panel, /remaining <= 86400000/);
});
test.after(() => { panelBuild.cleanup(); recordsBuild.cleanup(); checkoutBuild.cleanup(); });
