import api from './api.js';
import { mapOrderQuoteResponse, normalizeQuoteContext } from './orderQuoteViewService.js';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const CODE = /^[a-z][a-z0-9_]{0,31}$/;
const STATES = new Set(['not_started', 'awaiting_payment', 'creation_uncertain', 'processing', 'manual_review', 'paid', 'expired', 'failed', 'unavailable']);
const MAX_MINOR = 9999999999n;

export class OrderPaymentContractError extends Error {
  constructor(message) { super(message); this.name = 'OrderPaymentContractError'; }
}
const fail = () => { throw new OrderPaymentContractError('Payment information could not be verified. No payment is being assumed.'); };
const record = (value) => value && typeof value === 'object' && !Array.isArray(value) ? value : fail();
const bool = (value) => typeof value === 'boolean' ? value : fail();
const id = (value) => Number.isSafeInteger(value) && value > 0 && value <= 2147483647 ? value : fail();
const text = (value, limit = 256) => typeof value === 'string' && value.length > 0 && value.length <= limit && !/[\u0000-\u001f\u007f]/.test(value) ? value : fail();
const code = (value) => typeof value === 'string' && CODE.test(value) ? value : fail();
const nullableText = (value, limit) => value === null ? null : text(value, limit);
const role = (value) => value === 'user' ? 'trader' : text(value, 32);
const iso = (value) => value === null ? null : typeof value === 'string' && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value)) ? value : fail();
export const normalizePaymentOrderId = (value) => typeof value === 'string' && UUID.test(value) ? value : fail();
const minor = (value) => typeof value === 'string' && /^[1-9]\d{0,9}$/.test(value) && BigInt(value) <= MAX_MINOR ? value : fail();
const decimal = (value, { nullable = false, positive = false, decimals = 30 } = {}) => {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || value.length > 68 || !/^(?:0|[1-9]\d{0,35})(?:\.\d{1,30})?$/.test(value)) fail();
  const [whole, fraction = ''] = value.split('.');
  if (fraction.length > decimals || (positive && BigInt(whole + fraction) === 0n)) fail();
  return value;
};
const units = (value, decimals) => {
  const [whole, fraction = ''] = value.split('.');
  return BigInt(whole) * 10n ** BigInt(decimals) + BigInt(fraction.padEnd(decimals, '0') || '0');
};
const owner = (payload, principal) => {
  const context = record(payload.owner_context);
  const user = record(principal);
  if (id(context.user_id) !== id(user.id) || id(context.tenant_id) !== id(user.tenant_id) || role(context.role) !== role(user.role)) fail();
  return Object.freeze({ userId: context.user_id, tenantId: context.tenant_id, role: context.role });
};
const quoteIdentity = (quote, principal) => {
  const value = record(record(quote).order);
  const user = record(principal);
  if (id(value.userId) !== id(user.id) || id(value.tenantId) !== id(user.tenant_id)) fail();
  return { orderId: normalizePaymentOrderId(value.id), programId: id(quote.context.programId), amountMinor: minor(value.amountMinor) };
};
const schema = (payload) => {
  const value = record(payload);
  if (value.schema_version !== 1) fail();
  return value;
};
const currency = (value) => {
  const source = record(value);
  if (!Number.isSafeInteger(source.decimals) || source.decimals < 0 || source.decimals > 30) fail();
  return Object.freeze({ code: code(source.code), label: text(source.label, 100), network: text(source.network, 64), decimals: source.decimals });
};

export function mapPaymentCapabilities(payload, principal) {
  const source = schema(payload);
  const ownerContext = owner(source, principal);
  if (source.quote_currency !== 'USD' || source.live_trading_enabled !== false || !Array.isArray(source.currencies) || source.currencies.length > 32) fail();
  const currencies = source.currencies.map(currency);
  if (new Set(currencies.map((item) => item.code)).size !== currencies.length) fail();
  const enabled = bool(source.enabled);
  const feePaidByUser = source.fee_paid_by_user === null ? null : bool(source.fee_paid_by_user);
  const policyVersion = nullableText(source.policy_version, 128);
  if (enabled && (currencies.length !== 1 || currencies[0].code !== 'usdttrc20' || currencies[0].network !== 'TRC20' || currencies[0].decimals !== 6 || feePaidByUser !== false || policyVersion === null)) fail();
  return Object.freeze({ owner: ownerContext, enabled, reason: nullableText(source.reason, 128), currencies: Object.freeze(currencies), feePaidByUser, policyVersion });
}

export function mapOrderPayment(payload, { quote, principal }) {
  const source = schema(payload);
  const expected = quoteIdentity(quote, principal);
  const ownerContext = owner(source, principal);
  if (normalizePaymentOrderId(source.order_id) !== expected.orderId || id(source.program_id) !== expected.programId || minor(source.quote_amount_minor) !== expected.amountMinor || source.quote_currency !== 'USD' || !STATES.has(source.state)) fail();
  const paid = bool(source.paid), recordedPurchase = bool(source.recorded_purchase), reviewRequired = bool(source.review_required);
  const creationAttempted = bool(source.creation_attempted), canCreate = bool(source.can_create), canRefresh = bool(source.can_refresh);
  const providerStatus = source.provider_status === null ? null : code(source.provider_status);
  let payment = null;
  if (source.payment !== null) {
    const pay = record(source.payment);
    if (pay.provider !== 'nowpayments' || typeof pay.provider_payment_id !== 'string' || !/^[1-9]\d{0,127}$/.test(pay.provider_payment_id) || !Number.isSafeInteger(pay.decimals) || pay.decimals < 0 || pay.decimals > 30) fail();
    payment = Object.freeze({
      providerPaymentId: pay.provider_payment_id,
      payAmount: decimal(pay.pay_amount, { positive: true, decimals: pay.decimals }),
      payCurrency: code(pay.pay_currency), network: text(pay.network, 64), label: text(pay.label, 100), decimals: pay.decimals,
      address: text(pay.pay_address, 256), memo: nullableText(pay.memo, 128), expiresAt: iso(pay.expires_at),
      actuallyPaid: decimal(pay.actually_paid, { nullable: true, decimals: pay.decimals }),
      outcomeAmount: decimal(pay.outcome_amount, { nullable: true }), outcomeCurrency: pay.outcome_currency === null ? null : code(pay.outcome_currency),
      feePaidByUser: bool(pay.fee_paid_by_user),
    });
    if (!/^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(payment.address) || payment.payCurrency !== 'usdttrc20' || payment.network !== 'TRC20' || payment.decimals !== 6 || payment.feePaidByUser !== false || !creationAttempted) fail();
  }
  if ((canCreate && (creationAttempted || payment || paid || source.state !== 'not_started')) || (canRefresh && !payment) || (recordedPurchase !== paid)) fail();
  if (source.state === 'paid' && (!paid || reviewRequired || providerStatus !== 'finished' || !payment || payment.actuallyPaid === null || units(payment.actuallyPaid, payment.decimals) !== units(payment.payAmount, payment.decimals) || payment.outcomeAmount === null || units(payment.outcomeAmount, 30) <= 0n || !payment.outcomeCurrency)) fail();
  if (paid && source.state !== 'paid' && source.state !== 'manual_review') fail();
  return Object.freeze({
    owner: ownerContext, orderId: expected.orderId, programId: expected.programId, amountMinor: expected.amountMinor,
    state: source.state, paid, recordedPurchase, reviewRequired, creationAttempted, canCreate, canRefresh,
    providerStatus, payment, reason: nullableText(source.reason, 128), policyVersion: nullableText(source.policy_version, 128),
    updatedAt: iso(source.updated_at), replayed: bool(source.replayed),
  });
}

export const paymentCreationKey = () => {
  const value = globalThis.crypto?.randomUUID?.();
  if (typeof value !== 'string' || !UUID.test(value)) fail();
  return `payment_${value}`;
};
export async function getPaymentCapabilities({ principal, signal, client = api }) {
  return mapPaymentCapabilities((await client.get('/orders/payment-capabilities', { signal, timeout: 12000 })).data, principal);
}
export async function readOrderPayment({ quote, principal, signal, client = api }) {
  const { orderId } = quoteIdentity(quote, principal);
  return mapOrderPayment((await client.get(`/orders/${orderId}/payment`, { signal, timeout: 12000 })).data, { quote, principal });
}
export async function createOrderPayment({ quote, principal, payCurrency, idempotencyKey, signal, client = api }) {
  const { orderId } = quoteIdentity(quote, principal);
  code(payCurrency);
  if (payCurrency !== 'usdttrc20') fail();
  if (typeof idempotencyKey !== 'string' || !/^[A-Za-z0-9_-]{16,128}$/.test(idempotencyKey)) fail();
  const response = await client.post(`/orders/${orderId}/payments/nowpayments`, { pay_currency: payCurrency }, { headers: { 'Idempotency-Key': idempotencyKey }, signal, timeout: 25000, _skipAuthRefresh: true });
  return mapOrderPayment(response.data, { quote, principal });
}
export async function refreshOrderPayment({ quote, principal, signal, client = api }) {
  const { orderId } = quoteIdentity(quote, principal);
  return mapOrderPayment((await client.post(`/orders/${orderId}/payment/refresh`, {}, { signal, timeout: 25000, _skipAuthRefresh: true })).data, { quote, principal });
}
export async function readStoredPurchaseQuote({ orderId, programId, principal, signal, client = api }) {
  normalizePaymentOrderId(orderId);
  id(programId);
  const payload = record((await client.get(`/orders/${orderId}`, { signal, timeout: 12000 })).data);
  const source = record(payload.order), snapshot = record(source.snapshot);
  if (source.id !== orderId || !Array.isArray(snapshot.addons)) fail();
  const context = normalizeQuoteContext(programId, snapshot.addons.map((item) => id(record(item).id)));
  const quote = mapOrderQuoteResponse({ ...payload, replayed: true }, context);
  quoteIdentity(quote, principal);
  if (id(quote.order.snapshot.userId) !== id(principal.id) || id(quote.order.snapshot.tenantId) !== id(principal.tenant_id)) fail();
  return quote;
}

export function paymentErrorMessage(error, { creating = false } = {}) {
  if (creating) return 'The creation response could not be verified. Do not pay twice. Check this saved order before trying anything else.';
  if (error instanceof OrderPaymentContractError) return error.message;
  if ([401, 403, 404].includes(error?.response?.status)) return 'Payment information is unavailable for this account. No other account’s records are shown.';
  if (error?.response?.status === 429) return 'Please wait before checking again. No additional payment has been created.';
  return 'Payment information is temporarily unavailable. Check the saved order; no replacement payment has been created.';
}

const pageInteger = (value, { zero = false, max = 2147483647 } = {}) => Number.isSafeInteger(value) && value >= (zero ? 0 : 1) && value <= max ? value : fail();
export function mapPurchaseRecords(payload, principal, { ownOnly = true } = {}) {
  const source = schema(payload);
  const ownerContext = owner(source, principal);
  const available = bool(source.availability), sourceUnavailable = bool(source.source_unavailable);
  if (available === sourceUnavailable || !Array.isArray(source.records) || source.records.length > 50) fail();
  const page = record(source.pagination);
  const pagination = Object.freeze({
    page: pageInteger(page.page, { max: 10000 }), perPage: pageInteger(page.per_page, { max: 50 }), total: pageInteger(page.total, { zero: true }),
    pages: pageInteger(page.pages, { zero: true }), hasNext: bool(page.has_next), hasPrev: bool(page.has_prev),
  });
  if (pagination.pages !== Math.ceil(pagination.total / pagination.perPage) || pagination.hasNext !== (pagination.page < pagination.pages) || pagination.hasPrev !== (pagination.page > 1) || source.records.length > pagination.perPage || (!available && (source.records.length || pagination.total))) fail();
  const rows = source.records.map((item) => {
    const row = record(item);
    const userId = id(row.user_id), tenantId = id(row.tenant_id);
    if (tenantId !== ownerContext.tenantId || (ownOnly && userId !== ownerContext.userId) || !STATES.has(row.state) || row.quote_currency !== 'USD') fail();
    const paid = bool(row.paid), recordedPurchase = bool(row.recorded_purchase), reviewRequired = bool(row.review_required);
    const providerPaymentId = row.provider_payment_id === null ? null : text(row.provider_payment_id, 128);
    if (providerPaymentId !== null && !/^[1-9]\d{0,127}$/.test(providerPaymentId)) fail();
    const mapped = Object.freeze({
      orderId: normalizePaymentOrderId(row.order_id), programId: id(row.program_id), programName: nullableText(row.program_name, 256), userId, tenantId,
      state: row.state, paid, recordedPurchase, reviewRequired, amountMinor: minor(row.quote_amount_minor), providerPaymentId,
      payCurrency: row.pay_currency === null ? null : code(row.pay_currency), network: nullableText(row.network, 64),
      actuallyPaid: decimal(row.actually_paid, { nullable: true }), outcomeAmount: decimal(row.outcome_amount, { nullable: true }),
      outcomeCurrency: row.outcome_currency === null ? null : code(row.outcome_currency), updatedAt: iso(row.updated_at),
    });
    if (paid !== recordedPurchase || (mapped.state === 'paid' && (!paid || reviewRequired || !providerPaymentId || mapped.actuallyPaid === null || units(mapped.actuallyPaid, 30) <= 0n || mapped.outcomeAmount === null || units(mapped.outcomeAmount, 30) <= 0n || !mapped.outcomeCurrency))) fail();
    return mapped;
  });
  if (new Set(rows.map((item) => item.orderId)).size !== rows.length) fail();
  return Object.freeze({ owner: ownerContext, available, sourceUnavailable, reason: nullableText(source.reason, 128), records: Object.freeze(rows), pagination });
}
export async function readPurchaseRecords({ principal, ownOnly = true, page = 1, perPage = 20, signal, client = api }) {
  pageInteger(page, { max: 10000 }); pageInteger(perPage, { max: 50 });
  if ((page - 1) * perPage > 10000) fail();
  const endpoint = ownOnly ? '/orders/purchases' : '/orders/payment-records';
  const response = await client.get(endpoint, { params: { page, per_page: perPage }, signal, timeout: 12000 });
  return mapPurchaseRecords(response.data, principal, { ownOnly });
}
