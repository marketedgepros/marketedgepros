import assert from 'node:assert/strict';
import test from 'node:test';

const { default: api } = await import('../src/services/api.js');
const {
  AFFILIATE_VIEW_ENDPOINTS,
  AffiliateViewContractError,
  loadAffiliateCommissions,
  loadAffiliateDashboard,
  loadAffiliateReferrals,
  mapAffiliateDashboard,
} = await import('../src/services/affiliateViewService.js');

function adapterResponse(config, data) {
  return {
    data,
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
    request: {},
  };
}

test('affiliate pages use only current-account API URLs and map their supported mock responses', async () => {
  const originalAdapter = api.defaults.adapter;
  const requests = [];
  api.defaults.adapter = async (config) => {
    const uri = api.getUri(config);
    requests.push({ method: config.method, uri });

    if (config.url === AFFILIATE_VIEW_ENDPOINTS.referrals) {
      return adapterResponse(config, {
        referrals: [{
          id: 17,
          referred_user: { id: 44, name: 'Dana Trader', email: 'dana@example.test' },
          status: 'converted',
          purchase_amount: 150,
          commission_amount: 45,
          click_date: '2026-10-01T08:00:00Z',
          conversion_date: '2026-10-02T08:00:00Z',
        }],
        pagination: { page: 1, per_page: 100, total: 1, pages: 1 },
      });
    }
    if (config.url === AFFILIATE_VIEW_ENDPOINTS.commissions) {
      return adapterResponse(config, {
        commissions: [{
          id: 9,
          amount: 45,
          type: 'one_time',
          status: 'paid',
          description: 'Referral conversion',
          created_at: '2026-10-02T08:00:00Z',
          approved_at: '2026-10-03T08:00:00Z',
          paid_at: '2026-10-04T08:00:00Z',
        }],
        pagination: { page: 1, per_page: 100, total: 1, pages: 1 },
      });
    }
    if (config.url === AFFILIATE_VIEW_ENDPOINTS.dashboard) {
      return adapterResponse(config, {
        stats: {
          total_clicks: 120,
          total_conversions: 8,
          total_revenue: 1200,
          total_commission: 360,
          conversion_rate: 6.67,
          pending_commission: 30,
          approved_commission: 90,
          paid_commission: 240,
        },
        links: [],
        recent_referrals: [],
      });
    }
    throw new Error(`Unexpected synthetic request: ${config.url}`);
  };

  try {
    const [referrals, commissions, dashboard] = await Promise.all([
      loadAffiliateReferrals(),
      loadAffiliateCommissions(),
      loadAffiliateDashboard(),
    ]);

    assert.deepEqual(requests, [
      { method: 'get', uri: '/api/v1/affiliate/referrals?page=1&per_page=100' },
      { method: 'get', uri: '/api/v1/affiliate/commissions?page=1&per_page=100' },
      { method: 'get', uri: '/api/v1/affiliate/dashboard' },
    ]);
    assert.deepEqual(referrals.referrals[0], {
      id: 17,
      name: 'Dana Trader',
      email: 'dana@example.test',
      status: 'converted',
      clickDate: '2026-10-01T08:00:00Z',
      conversionDate: '2026-10-02T08:00:00Z',
      purchaseAmount: 150,
      commissionAmount: 45,
    });
    assert.deepEqual(commissions.commissions[0], {
      id: 9,
      amount: 45,
      type: 'one_time',
      status: 'paid',
      description: 'Referral conversion',
      createdAt: '2026-10-02T08:00:00Z',
      approvedAt: '2026-10-03T08:00:00Z',
      paidAt: '2026-10-04T08:00:00Z',
    });
    assert.deepEqual(dashboard.stats, {
      totalClicks: 120,
      totalConversions: 8,
      totalRevenue: 1200,
      totalCommission: 360,
      conversionRate: 6.67,
      pendingCommission: 30,
      approvedCommission: 90,
      paidCommission: 240,
    });
  } finally {
    api.defaults.adapter = originalAdapter;
  }
});

test('affiliate view contracts reject malformed payloads and preserve unavailable scalar values', () => {
  assert.throws(
    () => mapAffiliateDashboard({ stats: null, links: [], recent_referrals: [] }),
    AffiliateViewContractError,
  );

  const dashboard = mapAffiliateDashboard({
    stats: {
      total_clicks: null,
      total_conversions: '',
      total_revenue: undefined,
      total_commission: false,
      conversion_rate: 0,
      pending_commission: null,
      approved_commission: '',
      paid_commission: undefined,
    },
    links: [],
    recent_referrals: [],
  });

  assert.equal(dashboard.stats.totalClicks, null);
  assert.equal(dashboard.stats.totalConversions, null);
  assert.equal(dashboard.stats.totalRevenue, null);
  assert.equal(dashboard.stats.totalCommission, null);
  assert.equal(dashboard.stats.conversionRate, 0);
  assert.equal(dashboard.stats.pendingCommission, null);
  assert.equal(dashboard.stats.approvedCommission, null);
  assert.equal(dashboard.stats.paidCommission, null);
});
