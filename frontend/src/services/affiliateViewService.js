import api from './api.js';

export const AFFILIATE_VIEW_ENDPOINTS = Object.freeze({
  referrals: '/affiliate/referrals',
  commissions: '/affiliate/commissions',
  dashboard: '/affiliate/dashboard',
});

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

const asNumberOrNull = (value) => {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
    return null;
  }
  if (typeof value === 'string' && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};
const asTextOrNull = (value) => (typeof value === 'string' && value.trim() ? value : null);

export const mapAffiliateReferral = (referral) => {
  const source = requireRecord(referral, 'Affiliate referral');
  const referredUser = source.referred_user === null || source.referred_user === undefined
    ? {}
    : requireRecord(source.referred_user, 'Affiliate referral user');

  return {
    id: source.id,
    name: asTextOrNull(referredUser.name),
    email: asTextOrNull(referredUser.email),
    status: asTextOrNull(source.status),
    clickDate: asTextOrNull(source.click_date),
    conversionDate: asTextOrNull(source.conversion_date),
    purchaseAmount: asNumberOrNull(source.purchase_amount),
    commissionAmount: asNumberOrNull(source.commission_amount),
  };
};

export const mapAffiliateCommission = (commission) => {
  const source = requireRecord(commission, 'Affiliate commission');

  return {
    id: source.id,
    amount: asNumberOrNull(source.amount),
    type: asTextOrNull(source.type),
    status: asTextOrNull(source.status),
    description: asTextOrNull(source.description),
    createdAt: asTextOrNull(source.created_at),
    approvedAt: asTextOrNull(source.approved_at),
    paidAt: asTextOrNull(source.paid_at),
  };
};

export const mapAffiliateDashboard = (payload) => {
  const source = requireRecord(payload, 'Affiliate dashboard');
  const stats = requireRecord(source.stats, 'Affiliate dashboard statistics');

  return {
    stats: {
      totalClicks: asNumberOrNull(stats.total_clicks),
      totalConversions: asNumberOrNull(stats.total_conversions),
      totalRevenue: asNumberOrNull(stats.total_revenue),
      totalCommission: asNumberOrNull(stats.total_commission),
      conversionRate: asNumberOrNull(stats.conversion_rate),
      pendingCommission: asNumberOrNull(stats.pending_commission),
      approvedCommission: asNumberOrNull(stats.approved_commission),
      paidCommission: asNumberOrNull(stats.paid_commission),
    },
    links: requireList(source.links, 'Affiliate dashboard links'),
    recentReferrals: requireList(source.recent_referrals, 'Affiliate dashboard referrals').map(mapAffiliateReferral),
  };
};

const paginationParams = ({ page = 1, perPage = 100, status } = {}) => ({
  page,
  per_page: perPage,
  ...(status ? { status } : {}),
});

export async function loadAffiliateReferrals(options) {
  const response = await api.get(AFFILIATE_VIEW_ENDPOINTS.referrals, {
    params: paginationParams(options),
  });
  const data = requireRecord(response.data, 'Affiliate referrals');

  return {
    referrals: requireList(data.referrals, 'Affiliate referrals list').map(mapAffiliateReferral),
    pagination: requireRecord(data.pagination, 'Affiliate referrals pagination'),
  };
}

export async function loadAffiliateCommissions(options) {
  const response = await api.get(AFFILIATE_VIEW_ENDPOINTS.commissions, {
    params: paginationParams(options),
  });
  const data = requireRecord(response.data, 'Affiliate commissions');

  return {
    commissions: requireList(data.commissions, 'Affiliate commissions list').map(mapAffiliateCommission),
    pagination: requireRecord(data.pagination, 'Affiliate commissions pagination'),
  };
}

export async function loadAffiliateDashboard() {
  const response = await api.get(AFFILIATE_VIEW_ENDPOINTS.dashboard);
  return mapAffiliateDashboard(response.data);
}

export const affiliateViewError = (error) => (
  error?.response?.data?.error
  || error?.response?.data?.message
  || error?.message
  || 'The account data could not be loaded. Please try again.'
);
