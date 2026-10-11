import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ORDER_QUOTE_ENDPOINT,
  OrderQuoteContractError,
  OrderQuoteIdempotencyKeys,
  formatUsdFromMinorUnits,
  mapOrderQuoteResponse,
  requestOrderQuote,
} from '../src/services/orderQuoteViewService.js';

const quotePayload = ({
  programId = 12,
  addonIds = [4, 9],
  amountMinor = 12345,
  amount = '123.45',
  replayed = false,
} = {}) => ({
  order: {
    id: 'b4b9b6ae-f2e5-4da0-ae91-8af0ad4b0d45',
    program_id: programId,
    amount_minor: amountMinor,
    amount,
    currency: 'USD',
    state: 'quoted',
    paid: false,
    snapshot_hash: 'a'.repeat(64),
    snapshot: {
      schema: 1,
      kind: 'purchase_quote',
      program_id: programId,
      currency: 'USD',
      base_amount: '100.00',
      amount,
      entitlement: false,
      rounding: 'USD cents; ROUND_HALF_UP per add-on line',
      addons: addonIds.map((id, index) => ({
        id,
        name: `Add-on ${id}`,
        price_type: index % 2 === 0 ? 'fixed' : 'percentage',
        catalog_price: index % 2 === 0 ? '20.00' : '3.45',
        amount: index % 2 === 0 ? '20.00' : '3.45',
        benefits: { included: true },
      })),
    },
  },
  replayed,
});

test('POST /orders/ uses only canonical sorted context and records path, body, headers', async () => {
  const calls = [];
  const client = {
    post: async (path, body, config) => {
      calls.push({ path, body, headers: config.headers, hasSignal: config.signal instanceof AbortSignal });
      return { data: quotePayload() };
    },
  };

  const result = await requestOrderQuote({
    client,
    programId: 12,
    addonIds: [9, 4],
    idempotencyKey: 'quote_contract_request_0001',
  });

  assert.deepEqual(calls, [{
    path: ORDER_QUOTE_ENDPOINT,
    body: { program_id: 12, addon_ids: [4, 9] },
    headers: { 'Idempotency-Key': 'quote_contract_request_0001' },
    hasSignal: false,
  }]);
  assert.deepEqual(result.context, { programId: 12, addonIds: [4, 9], signature: '12:4,9' });
  assert.equal(result.order.amountMinor, '12345');
  assert.equal(result.order.snapshot.addons[1].priceType, 'percentage');
});

test('one unchanged selection reuses its idempotency key for a duplicate/ambiguous retry', async () => {
  let sequence = 0;
  const keys = new OrderQuoteIdempotencyKeys(() => `quote_duplicate_key_${++sequence}_123456`);
  const context = { programId: 12, addonIds: [9, 4] };
  const calls = [];
  const client = {
    post: async (path, body, config) => {
      calls.push({ path, body, idempotencyKey: config.headers['Idempotency-Key'] });
      return { data: quotePayload({ replayed: calls.length > 1 }) };
    },
  };

  const firstKey = keys.forContext(context);
  const first = await requestOrderQuote({ client, ...context, idempotencyKey: firstKey });
  const retryKey = keys.forContext({ programId: 12, addonIds: [4, 9] });
  const retry = await requestOrderQuote({ client, programId: 12, addonIds: [4, 9], idempotencyKey: retryKey });

  assert.equal(first.replayed, false);
  assert.equal(retry.replayed, true);
  assert.equal(firstKey, retryKey);
  assert.deepEqual(calls.map((call) => call.idempotencyKey), [firstKey, firstKey]);
  assert.deepEqual(calls.map((call) => call.path), [ORDER_QUOTE_ENDPOINT, ORDER_QUOTE_ENDPOINT]);

  keys.invalidate();
  assert.notEqual(keys.forContext(context), firstKey);
});

test('a response for changed program or add-on context is rejected before success can be shown', () => {
  assert.throws(
    () => mapOrderQuoteResponse(quotePayload({ programId: 12, addonIds: [4] }), { programId: 12, addonIds: [9] }),
    OrderQuoteContractError,
  );
  assert.throws(
    () => mapOrderQuoteResponse(quotePayload({ programId: 13, addonIds: [4] }), { programId: 12, addonIds: [4] }),
    /requested program/,
  );
});

test('request errors reject and do not produce a successful quote result', async () => {
  const client = {
    post: async () => {
      const error = new Error('network response was ambiguous');
      error.request = {};
      throw error;
    },
  };

  await assert.rejects(
    requestOrderQuote({
      client,
      programId: 12,
      addonIds: [],
      idempotencyKey: 'quote_network_retry_0001',
    }),
    /ambiguous/,
  );
});

test('minor-unit money formatting remains exact without floating point conversion', () => {
  assert.equal(formatUsdFromMinorUnits(1), 'USD 0.01');
  assert.equal(formatUsdFromMinorUnits('1000000001'), 'USD 10000000.01');
  const mapped = mapOrderQuoteResponse(
    quotePayload({ addonIds: [], amountMinor: '1000000001', amount: '10000000.01' }),
    { programId: 12, addonIds: [] },
  );
  assert.equal(mapped.order.amountMinor, '1000000001');
  assert.equal(mapped.order.amount, '10000000.01');
  assert.throws(
    () => mapOrderQuoteResponse(
      quotePayload({ addonIds: [], amountMinor: 12345, amount: '123.46' }),
      { programId: 12, addonIds: [] },
    ),
    /minor units/,
  );
});
