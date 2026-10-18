import api from './api.js';
import { recordedTimestampOrNull } from './userDashboardViewService.js';
import { recordedCsvCell } from './recordedTradingViewService.js';

export const AFFILIATE_RECORD_ENDPOINTS = Object.freeze({
  referrals: '/affiliate/referrals',
  commissions: '/affiliate/commissions',
});
export const AFFILIATE_RECORD_PAGE_LIMIT = 10000;
export const AFFILIATE_RECORD_PAGE_SIZE = 20;
export const AFFILIATE_RECORD_PER_PAGE_LIMIT = 50;
export const AFFILIATE_REFERRAL_STATUSES = Object.freeze(['pending', 'converted', 'cancelled']);
export const AFFILIATE_COMMISSION_STATUSES = Object.freeze(['pending', 'approved', 'paid', 'cancelled']);

const ID_LIMIT = 2147483647;
const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export class AffiliateRecordContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AffiliateRecordContractError';
  }
}

const fail = (message) => { throw new AffiliateRecordContractError(message); };
const requireRecord = (value, label) => {
  if (!isRecord(value)) fail(`${label} had an unexpected response shape.`);
  return value;
};
const requireArray = (value, label) => {
  if (!Array.isArray(value)) fail(`${label} had an unexpected response shape.`);
  return value;
};
const requireExactFields = (record, fields, label) => {
  const source = requireRecord(record, label);
  const actual = Object.keys(source);
  if (actual.length !== fields.length || fields.some((field) => !hasOwn(source, field))) {
    fail(`${label} contains fields outside the affiliate record contract.`);
  }
  return source;
};
const requirePositiveId = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > ID_LIMIT) {
    fail(`${label} must be a positive bounded integer.`);
  }
  return value;
};
const requireNonNegativeCount = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > ID_LIMIT) {
    fail(`${label} must be a non-negative bounded integer.`);
  }
  return value;
};
const requireExactDecimalOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > 128 || !DECIMAL.test(value)) {
    fail(`${label} must be an exact finite decimal string or null.`);
  }
  return value;
};
const requireTimestampOrNull = (value, label) => {
  if (value === null) return null;
  const timestamp = recordedTimestampOrNull(value);
  if (timestamp === null) fail(`${label} must be a complete ISO timestamp or null.`);
  return timestamp;
};
const requireStrictText = (value, label, maximum = 80) => {
  if (typeof value !== 'string' || !value || value !== value.trim() || value.length > maximum || /[\u0000-\u001F\u007F]/.test(value)) {
    fail(`${label} must be a bounded non-empty string.`);
  }
  return value;
};

/** Caller identity comes from the authenticated session, never from response data. */
export const normaliseAffiliateRecordExpectedOwner = (expectedOwner) => {
  const owner = requireExactFields(expectedOwner, ['user_id', 'tenant_id'], 'Expected affiliate owner');
  return {
    user_id: requirePositiveId(owner.user_id, 'Expected affiliate owner user ID'),
    tenant_id: requirePositiveId(owner.tenant_id, 'Expected affiliate owner tenant ID'),
  };
};

const requireAffiliateRole = (role) => {
  if (role !== 'affiliate') fail('Affiliate records require the affiliate role.');
  return role;
};

const requireOwnerContext = (value, expectedOwner) => {
  const owner = requireExactFields(value, ['user_id', 'tenant_id'], 'Affiliate record owner context');
  const normalized = {
    user_id: requirePositiveId(owner.user_id, 'Affiliate record owner user ID'),
    tenant_id: requirePositiveId(owner.tenant_id, 'Affiliate record owner tenant ID'),
  };
  if (normalized.user_id !== expectedOwner.user_id || normalized.tenant_id !== expectedOwner.tenant_id) {
    fail('Affiliate record owner context does not match the active account.');
  }
  return normalized;
};

const statusValuesFor = (kind) => {
  if (kind === 'referrals') return AFFILIATE_REFERRAL_STATUSES;
  if (kind === 'commissions') return AFFILIATE_COMMISSION_STATUSES;
  fail('Unsupported affiliate record type.');
};

/** Validate all transport options before a GET is attempted. */
export const buildAffiliateRecordParams = (kind, { page = 1, perPage = AFFILIATE_RECORD_PAGE_SIZE, status = null } = {}) => {
  const statuses = statusValuesFor(kind);
  if (!Number.isSafeInteger(page) || page < 1 || page > AFFILIATE_RECORD_PAGE_LIMIT) {
    fail(`Affiliate record page must be between 1 and ${AFFILIATE_RECORD_PAGE_LIMIT}.`);
  }
  if (!Number.isSafeInteger(perPage) || perPage < 1 || perPage > AFFILIATE_RECORD_PER_PAGE_LIMIT) {
    fail(`Affiliate record page size must be between 1 and ${AFFILIATE_RECORD_PER_PAGE_LIMIT}.`);
  }
  if (status !== null && !statuses.includes(status)) {
    fail('Affiliate record status filter is unsupported.');
  }
  return {
    page,
    per_page: perPage,
    ...(status === null ? {} : { status }),
  };
};

const normalizePagination = (value, params, rowCount) => {
  const pagination = requireExactFields(value, ['page', 'per_page', 'total', 'pages'], 'Affiliate record pagination');
  const page = pagination.page;
  const perPage = pagination.per_page;
  const total = requireNonNegativeCount(pagination.total, 'Affiliate record pagination total');
  const pages = requireNonNegativeCount(pagination.pages, 'Affiliate record pagination pages');
  if (page !== params.page || perPage !== params.per_page) {
    fail('Affiliate record pagination does not match the requested page.');
  }
  if (!Number.isSafeInteger(page) || page < 1 || page > AFFILIATE_RECORD_PAGE_LIMIT
      || !Number.isSafeInteger(perPage) || perPage < 1 || perPage > AFFILIATE_RECORD_PER_PAGE_LIMIT
      || pages !== Math.ceil(total / perPage)) {
    fail('Affiliate record pagination is mathematically inconsistent.');
  }
  const remaining = Math.max(0, total - ((page - 1) * perPage));
  const expectedRows = Math.min(perPage, remaining);
  if (rowCount !== expectedRows) {
    fail('Affiliate record page does not match its server pagination total.');
  }
  return { page, per_page: perPage, total, pages };
};

const normalizeFlags = (source) => {
  if (source.verification !== 'unverified_legacy' || source.payouts_enabled !== false
      || source.available_for_payout !== null || source.currency !== null) {
    fail('Affiliate record verification or payout boundary is invalid.');
  }
  return {
    verification: 'unverified_legacy',
    payoutsEnabled: false,
    availableForPayout: null,
    currency: null,
  };
};

const normalizeFilters = (value, expectedStatus, statuses) => {
  const filters = requireExactFields(value, ['status'], 'Affiliate record filters');
  if (filters.status !== null && !statuses.includes(filters.status)) {
    fail('Affiliate record filter response has an unsupported status.');
  }
  if (filters.status !== expectedStatus) fail('Affiliate record filter response does not echo the request.');
  return { status: filters.status };
};

export const mapAffiliateReferral = (row) => {
  const source = requireExactFields(row, [
    'id', 'status', 'click_date', 'conversion_date', 'purchase_amount', 'commission_amount', 'currency',
  ], 'Affiliate referral row');
  if (!AFFILIATE_REFERRAL_STATUSES.includes(source.status) || source.currency !== null) {
    fail('Affiliate referral row status or currency is invalid.');
  }
  return {
    id: requirePositiveId(source.id, 'Affiliate referral ID'),
    status: source.status,
    clickDate: requireTimestampOrNull(source.click_date, 'Affiliate referral click date'),
    conversionDate: requireTimestampOrNull(source.conversion_date, 'Affiliate referral conversion date'),
    purchaseAmount: requireExactDecimalOrNull(source.purchase_amount, 'Affiliate referral purchase amount'),
    commissionAmount: requireExactDecimalOrNull(source.commission_amount, 'Affiliate referral commission amount'),
    currency: null,
  };
};

export const mapAffiliateCommission = (row) => {
  const source = requireExactFields(row, [
    'id', 'amount', 'type', 'status', 'created_at', 'approved_at', 'paid_at', 'currency',
  ], 'Affiliate commission row');
  if (!AFFILIATE_COMMISSION_STATUSES.includes(source.status) || source.currency !== null) {
    fail('Affiliate commission row status or currency is invalid.');
  }
  return {
    id: requirePositiveId(source.id, 'Affiliate commission ID'),
    amount: requireExactDecimalOrNull(source.amount, 'Affiliate commission amount'),
    type: requireStrictText(source.type, 'Affiliate commission type'),
    status: source.status,
    createdAt: requireTimestampOrNull(source.created_at, 'Affiliate commission created date'),
    approvedAt: requireTimestampOrNull(source.approved_at, 'Affiliate commission approved date'),
    paidAt: requireTimestampOrNull(source.paid_at, 'Affiliate commission paid date'),
    currency: null,
  };
};

export const normalizeAffiliateRecordResponse = (kind, payload, { expectedOwner, params } = {}) => {
  const statuses = statusValuesFor(kind);
  const requiredParams = buildAffiliateRecordParams(kind, {
    page: params?.page,
    perPage: params?.per_page,
    status: params && hasOwn(params, 'status') ? params.status : null,
  });
  const owner = normaliseAffiliateRecordExpectedOwner(expectedOwner);
  const listKey = kind === 'referrals' ? 'referrals' : 'commissions';
  const source = requireExactFields(payload, [
    'owner_context', 'verification', 'payouts_enabled', 'available_for_payout', 'currency', 'pagination', 'filters', listKey,
  ], `Affiliate ${kind} response`);
  const rawRows = requireArray(source[listKey], `Affiliate ${kind} rows`);
  const rows = rawRows.map(kind === 'referrals' ? mapAffiliateReferral : mapAffiliateCommission);
  const pagination = normalizePagination(source.pagination, requiredParams, rows.length);
  const uniqueIds = new Set(rows.map((row) => row.id));
  if (uniqueIds.size !== rows.length) fail('Affiliate record response contains duplicate record identifiers.');
  if (requiredParams.status && rows.some((row) => row.status !== requiredParams.status)) {
    fail('Affiliate record rows do not match the requested status filter.');
  }
  return {
    kind,
    ownerContext: requireOwnerContext(source.owner_context, owner),
    ...normalizeFlags(source),
    pagination,
    filters: normalizeFilters(source.filters, requiredParams.status ?? null, statuses),
    [listKey]: rows,
  };
};

const abortError = () => {
  const error = new Error('Affiliate record request was cancelled.');
  error.name = 'AbortError';
  return error;
};
const throwIfAborted = (signal) => {
  if (signal?.aborted) throw abortError();
};

/** Axios-compatible, injectable transport; input identity/role is checked before every GET. */
export const createAffiliateRecordViewService = (client = api) => {
  const load = async (kind, options = {}) => {
    const expectedOwner = normaliseAffiliateRecordExpectedOwner(options.expectedOwner);
    requireAffiliateRole(options.role);
    const params = buildAffiliateRecordParams(kind, options);
    throwIfAborted(options.signal);
    const response = await client.get(AFFILIATE_RECORD_ENDPOINTS[kind], { params, signal: options.signal });
    throwIfAborted(options.signal);
    return normalizeAffiliateRecordResponse(kind, response?.data, { expectedOwner, params });
  };
  return {
    referrals: (options = {}) => load('referrals', options),
    commissions: (options = {}) => load('commissions', options),
  };
};

export const affiliateRecordError = (error) => (
  error?.response?.data?.error
  || error?.response?.data?.message
  || error?.message
  || 'The affiliate records could not be loaded. Please try again.'
);
export const isAffiliateRecordRequestCanceled = (error) => error?.name === 'AbortError' || error?.code === 'ERR_CANCELED';

/** Use the existing hardened CSV cell encoder; it quotes every value and neutralizes Unicode formula prefixes. */
export const affiliateCommissionCsvCell = recordedCsvCell;

export const buildAffiliateCommissionsCsv = (view) => {
  if (!view || view.kind !== 'commissions' || view.verification !== 'unverified_legacy'
      || view.payoutsEnabled !== false || view.currency !== null || !Array.isArray(view.commissions)) {
    throw new AffiliateRecordContractError('A validated current commissions page is required for export.');
  }
  const fields = [
    ['Commission record ID', 'id'],
    ['Legacy API type', 'type'],
    ['Legacy API status', 'status'],
    ['Amount — unverified legacy; currency unavailable', 'amount'],
    ['Created at', 'createdAt'],
    ['Approved at', 'approvedAt'],
    ['Paid at', 'paidAt'],
  ];
  return [
    fields.map(([heading]) => affiliateCommissionCsvCell(heading)).join(','),
    ...view.commissions.map((row) => fields.map(([, field]) => affiliateCommissionCsvCell(row[field])).join(',')),
  ].join('\r\n') + '\r\n';
};

export const downloadAffiliateCommissionsPage = (view, environment = globalThis) => {
  const csv = buildAffiliateCommissionsCsv(view);
  let anchor = null;
  let url = null;
  try {
    anchor = environment.document.createElement('a');
    url = environment.URL.createObjectURL(new environment.Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' }));
    anchor.href = url;
    anchor.download = `unverified-affiliate-commissions-page-${view.pagination.page}.csv`;
    environment.document.body.appendChild(anchor);
    anchor.click();
  } finally {
    try { anchor?.remove(); }
    finally { if (url !== null) environment.URL.revokeObjectURL(url); }
  }
};
