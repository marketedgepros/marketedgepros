import api from './api.js';
import { recordedTimestampOrNull } from './userDashboardViewService.js';
import {
  createAffiliateRecordViewService,
  mapAffiliateReferral as mapAffiliateReferralRecord,
  mapAffiliateCommission as mapAffiliateCommissionRecord,
} from './affiliateRecordViewService.js';

export const AFFILIATE_VIEW_ENDPOINTS = Object.freeze({
  referrals: '/affiliate/referrals',
  commissions: '/affiliate/commissions',
  dashboard: '/affiliate/dashboard',
});

const MAX_AFFILIATE_ID = 2147483647;
const MAX_LINKS = 50;
const MAX_RECENT_REFERRALS = 10;
const DECIMAL_STRING = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;

export class AffiliateViewContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AffiliateViewContractError';
  }
}

const requireRecord = (value, label) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new AffiliateViewContractError(`${label} had an unexpected response shape.`);
  }
  return value;
};

const requireList = (value, label) => {
  if (!Array.isArray(value)) {
    throw new AffiliateViewContractError(`${label} had an unexpected response shape.`);
  }
  return value;
};

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

const asNumberOrNull = (value) => {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
    return null;
  }
  if (typeof value === 'string' && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};
const asTextOrNull = (value) => (typeof value === 'string' && value.trim() ? value : null);

// Compatibility row mappers now enforce the dedicated PII-free record contract.
export const mapAffiliateReferral = (referral) => mapAffiliateReferralRecord(referral);
export const mapAffiliateCommission = (commission) => mapAffiliateCommissionRecord(commission);

const requireBoundedPositiveInteger = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_AFFILIATE_ID) {
    throw new AffiliateViewContractError(`${label} must be a positive bounded integer.`);
  }
  return value;
};

const requireBoundedCount = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > MAX_AFFILIATE_ID) {
    throw new AffiliateViewContractError(`${label} must be a non-negative bounded integer.`);
  }
  return value;
};

const requireNullableCount = (value, label) => (
  value === null ? null : requireBoundedCount(value, label)
);

const requireNullableExactDecimal = (value, label) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > 128 || !DECIMAL_STRING.test(value)) {
    throw new AffiliateViewContractError(`${label} must be an exact decimal string or null.`);
  }
  return value;
};

const requireNullableText = (value, label, maximum = 256) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > maximum) {
    throw new AffiliateViewContractError(`${label} must be a bounded string or null.`);
  }
  return value;
};

const requireAffiliateOwner = (value, label) => {
  const owner = requireRecord(value, label);
  if (!hasOwn(owner, 'user_id') || !hasOwn(owner, 'tenant_id')) {
    throw new AffiliateViewContractError(`${label} is incomplete.`);
  }

  return {
    user_id: requireBoundedPositiveInteger(owner.user_id, `${label} user ID`),
    // Affiliate dashboard records are tenant-scoped; a missing or inferred tenant is never safe.
    tenant_id: requireBoundedPositiveInteger(owner.tenant_id, `${label} tenant ID`),
  };
};

/**
 * The active account hint is deliberately typed and has no fallback to an email,
 * display name, or another tenant attribute. The server remains authoritative.
 */
export const normaliseAffiliateExpectedOwner = (expectedOwner) => (
  requireAffiliateOwner(expectedOwner, 'Expected affiliate owner')
);

const assertAffiliateOwner = (source, expectedOwner) => {
  const ownerContext = requireAffiliateOwner(source.owner_context, 'Affiliate dashboard owner context');
  if (expectedOwner && (
    ownerContext.user_id !== expectedOwner.user_id
    || ownerContext.tenant_id !== expectedOwner.tenant_id
  )) {
    throw new AffiliateViewContractError('Affiliate dashboard owner context does not match the active account.');
  }
  return ownerContext;
};

/**
 * Referral URLs are data, not navigation instructions. Accept only the one
 * canonical public referral shape that the dashboard is permitted to copy.
 */
export const getSafeAffiliateReferralUrl = (value) => {
  if (typeof value !== 'string' || !value || value.length > 256 || /[\u0000-\u001F\u007F\s]/.test(value)) {
    return null;
  }

  try {
    const url = new URL(value);
    const ref = url.searchParams.get('ref');
    const canonical = typeof ref === 'string' && /^[A-Z0-9]{1,50}$/.test(ref)
      ? `https://marketedgepros.com/?ref=${ref}`
      : null;

    if (
      url.protocol !== 'https:'
      || url.hostname !== 'marketedgepros.com'
      || url.host !== 'marketedgepros.com'
      || url.port !== ''
      || url.username
      || url.password
      || url.hash
      || url.pathname !== '/'
      || url.searchParams.getAll('ref').length !== 1
      || [...url.searchParams.keys()].some((key) => key !== 'ref')
      || !canonical
      || value !== canonical
    ) {
      return null;
    }

    return canonical;
  } catch {
    return null;
  }
};

const mapDashboardLink = (link) => {
  const source = requireRecord(link, 'Affiliate dashboard link');
  const url = getSafeAffiliateReferralUrl(source.url);
  if (source.url !== null && !url) {
    throw new AffiliateViewContractError('Affiliate dashboard link URL is not a canonical public referral URL.');
  }

  return {
    id: requireBoundedPositiveInteger(source.id, 'Affiliate dashboard link ID'),
    name: requireNullableText(source.name, 'Affiliate dashboard link name', 160),
    url,
    clicks: requireNullableCount(source.clicks, 'Affiliate dashboard link clicks'),
    conversions: requireNullableCount(source.conversions, 'Affiliate dashboard link conversions'),
  };
};

const mapDashboardReferral = (referral) => {
  const source = requireRecord(referral, 'Affiliate dashboard referral');
  if (source.referred_user !== undefined && source.referred_user !== null) {
    throw new AffiliateViewContractError('Affiliate dashboard referral must not contain referred user information.');
  }
  if (source.currency !== null) {
    throw new AffiliateViewContractError('Affiliate dashboard referral currency must be explicitly unavailable.');
  }
  if (source.click_date !== null && recordedTimestampOrNull(source.click_date) === null) {
    throw new AffiliateViewContractError('Affiliate dashboard referral click date is invalid.');
  }

  return {
    id: requireBoundedPositiveInteger(source.id, 'Affiliate dashboard referral ID'),
    status: requireNullableText(source.status, 'Affiliate dashboard referral status', 80),
    clickDate: requireNullableText(source.click_date, 'Affiliate dashboard referral click date', 128),
    commissionAmount: requireNullableExactDecimal(source.commission_amount, 'Affiliate dashboard referral commission amount'),
    currency: null,
  };
};

const mapDashboardStats = (stats) => {
  const source = requireRecord(stats, 'Affiliate dashboard statistics');
  if (
    source.currency !== null
    || source.commission_verification !== 'unverified_legacy'
    || source.payouts_enabled !== false
    || source.available_for_payout !== null
  ) {
    throw new AffiliateViewContractError('Affiliate dashboard verification flags are not the supported legacy read-only values.');
  }

  return {
    totalClicks: requireNullableCount(source.total_clicks, 'Affiliate dashboard total clicks'),
    totalConversions: requireNullableCount(source.total_conversions, 'Affiliate dashboard total conversions'),
    totalRevenue: requireNullableExactDecimal(source.total_revenue, 'Affiliate dashboard total revenue'),
    totalCommission: requireNullableExactDecimal(source.total_commission, 'Affiliate dashboard total commission'),
    pendingCommission: requireNullableExactDecimal(source.pending_commission, 'Affiliate dashboard pending commission'),
    approvedCommission: requireNullableExactDecimal(source.approved_commission, 'Affiliate dashboard approved commission'),
    paidCommission: requireNullableExactDecimal(source.paid_commission, 'Affiliate dashboard paid commission'),
    availableForPayout: null,
    payoutsEnabled: false,
    commissionVerification: 'unverified_legacy',
    currency: null,
  };
};

const mapLinkPagination = (value, linkCount) => {
  const source = requireRecord(value, 'Affiliate dashboard link pagination');
  const total = requireBoundedCount(source.total, 'Affiliate dashboard total links');
  if (source.limit !== MAX_LINKS || typeof source.truncated !== 'boolean') {
    throw new AffiliateViewContractError('Affiliate dashboard link pagination must use its fixed bounded limit.');
  }
  if (total < linkCount || source.truncated !== (total > MAX_LINKS)) {
    throw new AffiliateViewContractError('Affiliate dashboard link pagination is inconsistent.');
  }
  if ((!source.truncated && total !== linkCount) || (source.truncated && linkCount !== MAX_LINKS)) {
    throw new AffiliateViewContractError('Affiliate dashboard links do not match their bounded pagination.');
  }

  return { total, limit: MAX_LINKS, truncated: source.truncated };
};

/**
 * Projects the tenant-bound, read-only /affiliate/dashboard response. Amounts
 * intentionally remain exact API decimal strings: neither a number conversion
 * nor a currency assumption is permitted in this view.
 */
export const mapAffiliateDashboard = (payload, options = {}) => {
  const source = requireRecord(payload, 'Affiliate dashboard');
  const stats = requireRecord(source.stats, 'Affiliate dashboard statistics');
  const expectedOwner = normaliseAffiliateExpectedOwner(options.expectedOwner);

  const ownerContext = assertAffiliateOwner(source, expectedOwner);
  const rawLinks = requireList(source.links, 'Affiliate dashboard links');
  const rawReferrals = requireList(source.recent_referrals, 'Affiliate dashboard referrals');
  if (rawLinks.length > MAX_LINKS || rawReferrals.length > MAX_RECENT_REFERRALS) {
    throw new AffiliateViewContractError('Affiliate dashboard list exceeds its supported bound.');
  }
  const links = rawLinks.map(mapDashboardLink);
  const recentReferrals = rawReferrals.map(mapDashboardReferral);
  if (new Set(links.map((row) => row.id)).size !== links.length
      || new Set(recentReferrals.map((row) => row.id)).size !== recentReferrals.length) {
    throw new AffiliateViewContractError('Affiliate dashboard contains duplicate record identifiers.');
  }

  return {
    ownerContext,
    stats: mapDashboardStats(stats),
    links,
    linkPagination: mapLinkPagination(source.link_pagination, links.length),
    recentReferrals,
  };
};

/** Legacy loader names remain exported but require a verified affiliate principal before GET. */
export async function loadAffiliateReferrals(options = {}) {
  const client = options.apiClient || api;
  return createAffiliateRecordViewService(client).referrals(options);
}

export async function loadAffiliateCommissions(options = {}) {
  const client = options.apiClient || api;
  return createAffiliateRecordViewService(client).commissions(options);
}

const throwIfAborted = (signal) => {
  if (!signal?.aborted) return;
  const error = new Error('Affiliate dashboard request was cancelled.');
  error.name = 'AbortError';
  throw error;
};

/** Allows focused contract tests to inject an Axios-compatible GET client. */
export const createAffiliateDashboardViewService = (client = api) => ({
  async getDashboard(options = {}) {
    const expectedOwner = normaliseAffiliateExpectedOwner(options.expectedOwner);
    throwIfAborted(options.signal);
    const response = await client.get(AFFILIATE_VIEW_ENDPOINTS.dashboard, { signal: options.signal });
    throwIfAborted(options.signal);
    return mapAffiliateDashboard(response.data, { expectedOwner });
  },
});

/**
 * The caller must provide the current owner independently from the response.
 * Signal and expectedOwner keep aborted and cross-account responses fail-closed.
 */
export async function loadAffiliateDashboard(options = {}) {
  const client = options?.apiClient || api;
  return createAffiliateDashboardViewService(client).getDashboard(options || {});
}

export const affiliateViewError = (error) => (
  error?.response?.data?.error
  || error?.response?.data?.message
  || error?.message
  || 'The account data could not be loaded. Please try again.'
);
