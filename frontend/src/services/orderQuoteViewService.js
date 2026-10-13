import api from './api.js';

export const ORDER_QUOTE_ENDPOINT = '/orders/';
export const MAX_ORDER_ADDONS = 20;
const MAX_CATALOG_IDENTIFIER = 2147483647;
const MAX_AMOUNT_MINOR = '9999999999';
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9_-]{16,128}$/;
const MONEY_PATTERN = /^(0|[1-9]\d*)\.\d{2}$/;

export class OrderQuoteContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'OrderQuoteContractError';
  }
}

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const requireRecord = (value, label) => {
  if (!isRecord(value)) {
    throw new OrderQuoteContractError(`${label} had an unexpected response shape.`);
  }
  return value;
};

const requirePositiveIdentifier = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_CATALOG_IDENTIFIER) {
    throw new OrderQuoteContractError(`${label} must be a positive integer.`);
  }
  return value;
};

const compareDecimalStrings = (left, right) => {
  if (left.length !== right.length) return left.length - right.length;
  return left.localeCompare(right);
};

const normalizeMinorUnits = (value, label = 'Amount minor units') => {
  let minor;
  if (typeof value === 'number' && Number.isSafeInteger(value)) {
    minor = String(value);
  } else if (typeof value === 'string' && /^\d+$/.test(value)) {
    minor = value.replace(/^0+(?=\d)/, '');
  } else {
    throw new OrderQuoteContractError(`${label} must be an integer or decimal-digit string.`);
  }

  if (minor === '0' || compareDecimalStrings(minor, MAX_AMOUNT_MINOR) > 0) {
    throw new OrderQuoteContractError(`${label} is outside the supported quote range.`);
  }
  return minor;
};

const minorUnitsToDecimal = (minorUnits) => {
  const minor = normalizeMinorUnits(minorUnits);
  const padded = minor.padStart(3, '0');
  return `${padded.slice(0, -2)}.${padded.slice(-2)}`;
};

const requireMoneyText = (value, label) => {
  if (typeof value !== 'string' || !MONEY_PATTERN.test(value)) {
    throw new OrderQuoteContractError(`${label} must be an exact decimal string with two fraction digits.`);
  }
  return value;
};

const sameIds = (actual, expected) => (
  actual.length === expected.length && actual.every((value, index) => value === expected[index])
);

/**
 * Normalizes the only request-controlled quote fields. The result is safe to
 * send as JSON and makes the server's sorted-idempotency request canonical.
 */
export const normalizeQuoteContext = (programId, addonIds = []) => {
  const normalizedProgramId = requirePositiveIdentifier(programId, 'Program identifier');
  if (!Array.isArray(addonIds) || addonIds.length > MAX_ORDER_ADDONS) {
    throw new OrderQuoteContractError(`Add-on identifiers must be an array of at most ${MAX_ORDER_ADDONS} items.`);
  }

  const normalizedAddonIds = addonIds.map((value) => requirePositiveIdentifier(value, 'Add-on identifier'));
  const sortedAddonIds = [...normalizedAddonIds].sort((left, right) => left - right);
  if (new Set(sortedAddonIds).size !== sortedAddonIds.length) {
    throw new OrderQuoteContractError('Add-on identifiers must not contain duplicates.');
  }

  return Object.freeze({
    programId: normalizedProgramId,
    addonIds: Object.freeze(sortedAddonIds),
    signature: `${normalizedProgramId}:${sortedAddonIds.join(',')}`,
  });
};

/**
 * Formats server minor units without converting money to a floating-point
 * number. The backend currently configures immutable USD quotes only.
 */
export const formatUsdFromMinorUnits = (amountMinor) => `USD ${minorUnitsToDecimal(amountMinor)}`;

const randomKeyPart = () => {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (typeof uuid === 'string' && uuid.length > 0) return uuid.replace(/[^A-Za-z0-9_-]/g, '');
  return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 14)}`;
};

export const createOrderQuoteIdempotencyKey = () => {
  const key = `quote_${randomKeyPart()}`;
  // The fallback keeps the backend-required lower bound even in old browsers.
  return key.length >= 16 ? key : `${key}_request`;
};

/**
 * Retains one key for one deliberate selection. Call invalidate() whenever a
 * user changes the program or add-on selection; network retries then reuse the
 * same key, while a later deliberate selection receives a fresh key.
 */
export class OrderQuoteIdempotencyKeys {
  constructor(createKey = createOrderQuoteIdempotencyKey) {
    this.createKey = createKey;
    this.current = null;
  }

  forContext(context) {
    const normalized = normalizeQuoteContext(context?.programId, context?.addonIds);
    if (!this.current || this.current.signature !== normalized.signature) {
      const key = this.createKey();
      if (typeof key !== 'string' || !IDEMPOTENCY_KEY_PATTERN.test(key)) {
        throw new OrderQuoteContractError('The generated quote idempotency key is invalid.');
      }
      this.current = { signature: normalized.signature, key };
    }
    return this.current.key;
  }

  invalidate() {
    this.current = null;
  }
}

const mapSnapshotAddon = (addon, expectedId) => {
  const source = requireRecord(addon, 'Quote snapshot add-on');
  const id = requirePositiveIdentifier(source.id, 'Quote snapshot add-on identifier');
  if (id !== expectedId) {
    throw new OrderQuoteContractError('Quote snapshot add-ons did not match the requested selection.');
  }
  if (typeof source.name !== 'string' || !source.name.trim()) {
    throw new OrderQuoteContractError('Quote snapshot add-on name was missing.');
  }
  if (source.price_type !== 'fixed' && source.price_type !== 'percentage') {
    throw new OrderQuoteContractError('Quote snapshot add-on price type was invalid.');
  }

  return Object.freeze({
    id,
    name: source.name,
    priceType: source.price_type,
    catalogPrice: requireMoneyText(source.catalog_price, 'Quote snapshot add-on catalog price'),
    amount: requireMoneyText(source.amount, 'Quote snapshot add-on amount'),
    benefits: source.benefits,
  });
};

/**
 * Maps and validates the POST /orders/ response against the request context.
 * It deliberately accepts no payment URL, wallet, provider, or entitlement.
 */
export const mapOrderQuoteResponse = (payload, context) => {
  const expected = normalizeQuoteContext(context?.programId, context?.addonIds);
  const source = requireRecord(payload, 'Order quote');
  const order = requireRecord(source.order, 'Order quote order');

  if (typeof order.id !== 'string' || !order.id.trim()) {
    throw new OrderQuoteContractError('Order quote identifier was missing.');
  }
  if (requirePositiveIdentifier(order.program_id, 'Order quote program identifier') !== expected.programId) {
    throw new OrderQuoteContractError('Order quote did not match the requested program.');
  }
  if (order.currency !== 'USD' || order.state !== 'quoted' || order.paid !== false) {
    throw new OrderQuoteContractError('Order quote was not an unpaid USD quoted order.');
  }
  if (typeof source.replayed !== 'boolean') {
    throw new OrderQuoteContractError('Order quote replay state was missing.');
  }
  if (typeof order.snapshot_hash !== 'string' || !/^[a-f0-9]{64}$/.test(order.snapshot_hash)) {
    throw new OrderQuoteContractError('Order quote snapshot hash was invalid.');
  }

  const amountMinor = normalizeMinorUnits(order.amount_minor, 'Order quote amount minor units');
  const amount = requireMoneyText(order.amount, 'Order quote amount');
  if (amount !== minorUnitsToDecimal(amountMinor)) {
    throw new OrderQuoteContractError('Order quote amount did not match its minor units.');
  }

  const snapshot = requireRecord(order.snapshot, 'Order quote snapshot');
  if (
    snapshot.schema !== 1
    || snapshot.kind !== 'purchase_quote'
    || requirePositiveIdentifier(snapshot.program_id, 'Quote snapshot program identifier') !== expected.programId
    || snapshot.currency !== 'USD'
    || requireMoneyText(snapshot.amount, 'Quote snapshot amount') !== amount
    || snapshot.entitlement !== false
  ) {
    throw new OrderQuoteContractError('Order quote snapshot did not match the immutable quote contract.');
  }

  if (!Array.isArray(snapshot.addons)) {
    throw new OrderQuoteContractError('Order quote snapshot add-ons were missing.');
  }
  const snapshotAddonIds = snapshot.addons.map((addon) => requirePositiveIdentifier(
    requireRecord(addon, 'Quote snapshot add-on').id,
    'Quote snapshot add-on identifier',
  )).sort((left, right) => left - right);
  if (!sameIds(snapshotAddonIds, expected.addonIds)) {
    throw new OrderQuoteContractError('Order quote snapshot add-ons did not match the requested selection.');
  }

  const snapshotAddons = snapshot.addons
    .slice()
    .sort((left, right) => left.id - right.id)
    .map((addon, index) => mapSnapshotAddon(addon, expected.addonIds[index]));

  return Object.freeze({
    context: expected,
    replayed: source.replayed,
    order: Object.freeze({
      id: order.id,
      userId: order.user_id,
      tenantId: order.tenant_id,
      amountMinor,
      amount,
      currency: order.currency,
      state: order.state,
      paid: order.paid,
      snapshotHash: order.snapshot_hash,
      snapshot: Object.freeze({
        userId: snapshot.user_id,
        tenantId: snapshot.tenant_id,
        baseAmount: requireMoneyText(snapshot.base_amount, 'Quote snapshot base amount'),
        amount: snapshot.amount,
        addons: Object.freeze(snapshotAddons),
        rounding: typeof snapshot.rounding === 'string' ? snapshot.rounding : null,
        terms: isRecord(snapshot.terms) ? JSON.parse(JSON.stringify(snapshot.terms)) : null,
      }),
    }),
  });
};

export async function requestOrderQuote({
  client = api,
  programId,
  addonIds = [],
  idempotencyKey,
  signal,
} = {}) {
  const context = normalizeQuoteContext(programId, addonIds);
  if (typeof idempotencyKey !== 'string' || !IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) {
    throw new OrderQuoteContractError('A 16-128 character quote idempotency key is required.');
  }
  if (!client || typeof client.post !== 'function') {
    throw new OrderQuoteContractError('A quote API client is required.');
  }

  const response = await client.post(
    ORDER_QUOTE_ENDPOINT,
    { program_id: context.programId, addon_ids: context.addonIds },
    { headers: { 'Idempotency-Key': idempotencyKey }, signal, timeout: 15000 },
  );
  return mapOrderQuoteResponse(response?.data, context);
}

export const orderQuoteErrorMessage = (error) => (
  error?.response?.data?.error
  || error?.response?.data?.message
  || (error?.request && !error?.response
    ? 'No quote response was received. The request may have reached the server; retry uses the same selection and idempotency key.'
    : error?.message)
  || 'The quote could not be requested. Retry uses the same selection and idempotency key.'
);
