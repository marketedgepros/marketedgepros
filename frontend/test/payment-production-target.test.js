import assert from 'node:assert/strict';
import test from 'node:test';
import buildConfig from '../vite.config.js';
import { compilePaymentHarness, purchaseRecordsFixture } from './paymentHarness.js';

const compiled = await compilePaymentHarness(new URL('../src/services/orderPaymentViewService.js', import.meta.url), {
  prefix: 'payment-production-target', target: buildConfig.build.target,
});
const service = compiled.module;
const principal = { id: 2, tenant_id: 1, role: 'trader' };
const orderId = '00000000-0000-4000-8000-000000000012';
const quote = { order: { id: orderId, userId: 2, tenantId: 1, amountMinor: '1999' }, context: { programId: 12 } };
const payload = () => ({ schema_version: 1, owner_context: { user_id: 2, tenant_id: 1, role: 'trader' }, order_id: orderId, program_id: 12, quote_amount_minor: '1999', quote_currency: 'USD', state: 'paid', paid: true, recorded_purchase: true, review_required: false, creation_attempted: true, can_create: false, can_refresh: true, provider_status: 'finished', payment: { provider: 'nowpayments', provider_payment_id: '123456789', pay_amount: '20.123456', pay_currency: 'usdttrc20', network: 'TRC20', label: 'USDT (TRC20)', decimals: 6, pay_address: 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb', memo: null, expires_at: null, actually_paid: '20.123456', outcome_amount: '19.123456789012345678901234567890', outcome_currency: 'usdttrc20', fee_paid_by_user: false }, reason: null, policy_version: 'synthetic-v1', updated_at: '2026-10-18T10:00:00.123456Z', replayed: false });

// Source-only tests did not catch esbuild lowering BigInt exponentiation to
// Math.pow under the real ES2015 deployment target. Run the mapper after that
// exact target transform, with six-digit deposits and a thirty-digit outcome.
test('production-target mapper confirms exact paid evidence without Number coercion', () => {
  const mapped = service.mapOrderPayment(payload(), { quote, principal });
  assert.equal(mapped.state, 'paid');
  assert.equal(mapped.payment.actuallyPaid, '20.123456');
  assert.equal(mapped.payment.outcomeAmount, '19.123456789012345678901234567890');
});

test('production-target customer and administrator collections accept verified receipts', () => {
  const data = { ...purchaseRecordsFixture(2, 1, 'trader'), records: [{ order_id: orderId, program_id: 12, program_name: 'Synthetic program', user_id: 2, tenant_id: 1, state: 'paid', paid: true, recorded_purchase: true, review_required: false, quote_amount_minor: '1999', quote_currency: 'USD', provider_payment_id: '123456789', pay_currency: 'usdttrc20', network: 'TRC20', actually_paid: '20.123456', outcome_amount: '19.123456789012345678901234567890', outcome_currency: 'usdttrc20', updated_at: '2026-10-18T10:00:00.123456Z' }], pagination: { page: 1, per_page: 20, total: 1, pages: 1, has_next: false, has_prev: false } };
  assert.equal(service.mapPurchaseRecords(data, principal).records[0].paid, true);
  data.owner_context = { user_id: 1, tenant_id: 1, role: 'super_admin' };
  assert.equal(service.mapPurchaseRecords(data, { id: 1, tenant_id: 1, role: 'super_admin' }, { ownOnly: false }).records[0].paid, true);
});

for (const [label, mutate] of [
  ['partial', value => { value.payment.actually_paid = '20.123455'; }],
  ['extra', value => { value.payment.actually_paid = '20.123457'; }],
  ['unapproved precision', value => { value.payment.actually_paid = '20.1234561'; }],
  ['numeric float', value => { value.payment.actually_paid = 20.123456; }],
  ['zero outcome', value => { value.payment.outcome_amount = '0'; }],
  ['wrong owner', value => { value.owner_context.user_id = 3; }],
  ['wrong network', value => { value.payment.network = 'ERC20'; }],
  ['not final', value => { value.provider_status = 'sending'; }],
]) {
  test(`production-target mapper still refuses ${label} evidence`, () => {
    const value = payload(); mutate(value);
    assert.throws(() => service.mapOrderPayment(value, { quote, principal }), service.OrderPaymentContractError);
  });
}

test.after(() => compiled.cleanup());
