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

const dashboardOwner = { user_id: 7, tenant_id: 3 };

test('affiliate pages use only current-account API URLs and map their supported mock responses', async () => {
  const originalAdapter = api.defaults.adapter;
  const requests = [];
  api.defaults.adapter = async (config) => {
    const uri = api.getUri(config);
    requests.push({ method: config.method, uri });

    if (config.url === AFFILIATE_VIEW_ENDPOINTS.referrals) {
      return adapterResponse(config, {
        owner_context: dashboardOwner, verification: 'unverified_legacy', payouts_enabled: false, available_for_payout: null, currency: null,
        referrals: [{ id: 17, status: 'converted', purchase_amount: '150', commission_amount: '45', click_date: '2026-10-01T08:00:00Z', conversion_date: '2026-10-02T08:00:00Z', currency: null }],
        pagination: { page: 1, per_page: 20, total: 1, pages: 1 }, filters: { status: null },
      });
    }
    if (config.url === AFFILIATE_VIEW_ENDPOINTS.commissions) {
      return adapterResponse(config, {
        owner_context: dashboardOwner, verification: 'unverified_legacy', payouts_enabled: false, available_for_payout: null, currency: null,
        commissions: [{ id: 9, amount: '45', type: 'one_time', status: 'paid', created_at: '2026-10-02T08:00:00Z', approved_at: '2026-10-03T08:00:00Z', paid_at: '2026-10-04T08:00:00Z', currency: null }],
        pagination: { page: 1, per_page: 20, total: 1, pages: 1 }, filters: { status: null },
      });
    }
    if (config.url === AFFILIATE_VIEW_ENDPOINTS.dashboard) {
      return adapterResponse(config, {
        owner_context: dashboardOwner,
        stats: {
          total_clicks: 120,
          total_conversions: 8,
          total_revenue: '1200.00',
          total_commission: '360.00',
          pending_commission: '30.00',
          approved_commission: '90.00',
          paid_commission: '240.00',
          available_for_payout: null,
          payouts_enabled: false,
          commission_verification: 'unverified_legacy',
          currency: null,
        },
        links: [],
        link_pagination: { total: 0, limit: 50, truncated: false },
        recent_referrals: [],
      });
    }
    throw new Error(`Unexpected synthetic request: ${config.url}`);
  };

  try {
    const [referrals, commissions, dashboard] = await Promise.all([
      loadAffiliateReferrals({ expectedOwner: dashboardOwner, role: 'affiliate' }),
      loadAffiliateCommissions({ expectedOwner: dashboardOwner, role: 'affiliate' }),
      loadAffiliateDashboard({ expectedOwner: dashboardOwner }),
    ]);

    assert.deepEqual(requests, [
      { method: 'get', uri: '/api/v1/affiliate/referrals?page=1&per_page=20' },
      { method: 'get', uri: '/api/v1/affiliate/commissions?page=1&per_page=20' },
      { method: 'get', uri: '/api/v1/affiliate/dashboard' },
    ]);
    assert.deepEqual(referrals.referrals[0], {
      id: 17, status: 'converted', clickDate: '2026-10-01T08:00:00Z', conversionDate: '2026-10-02T08:00:00Z', purchaseAmount: '150', commissionAmount: '45', currency: null,
    });
    assert.deepEqual(commissions.commissions[0], {
      id: 9, amount: '45', type: 'one_time', status: 'paid', createdAt: '2026-10-02T08:00:00Z', approvedAt: '2026-10-03T08:00:00Z', paidAt: '2026-10-04T08:00:00Z', currency: null,
    });
    assert.deepEqual(dashboard.stats, {
      totalClicks: 120,
      totalConversions: 8,
      totalRevenue: '1200.00',
      totalCommission: '360.00',
      pendingCommission: '30.00',
      approvedCommission: '90.00',
      paidCommission: '240.00',
      availableForPayout: null,
      payoutsEnabled: false,
      commissionVerification: 'unverified_legacy',
      currency: null,
    });
    assert.deepEqual(dashboard.ownerContext, dashboardOwner);
  } finally {
    api.defaults.adapter = originalAdapter;
  }
});

test('affiliate dashboard contracts reject missing owner, malformed amounts, and unsupported flags', () => {
  assert.throws(
    () => mapAffiliateDashboard({ stats: null, links: [], recent_referrals: [] }),
    AffiliateViewContractError,
  );

  const dashboardPayload = {
    owner_context: dashboardOwner,
    stats: {
      total_clicks: 0,
      total_conversions: 0,
      total_revenue: null,
      total_commission: null,
      pending_commission: null,
      approved_commission: null,
      paid_commission: null,
      available_for_payout: null,
      payouts_enabled: false,
      commission_verification: 'unverified_legacy',
      currency: null,
    },
    links: [],
    link_pagination: { total: 0, limit: 50, truncated: false },
    recent_referrals: [],
  };

  assert.throws(() => mapAffiliateDashboard({ ...dashboardPayload, owner_context: undefined }), AffiliateViewContractError);
  assert.throws(() => mapAffiliateDashboard({
    ...dashboardPayload,
    stats: { ...dashboardPayload.stats, total_commission: 0 },
  }, { expectedOwner: dashboardOwner }), AffiliateViewContractError);
  assert.throws(() => mapAffiliateDashboard({
    ...dashboardPayload,
    stats: { ...dashboardPayload.stats, payouts_enabled: true },
  }, { expectedOwner: dashboardOwner }), AffiliateViewContractError);
});
