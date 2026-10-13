import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';
import {
  AffiliateViewContractError,
  createAffiliateDashboardViewService,
  getSafeAffiliateReferralUrl,
  mapAffiliateDashboard,
} from '../src/services/affiliateViewService.js';

const owner = { user_id: 19, tenant_id: 6 };

const payload = (overrides = {}) => ({
  owner_context: owner,
  stats: {
    total_clicks: 23,
    total_conversions: 4,
    total_revenue: '100.00',
    total_commission: '12.50',
    pending_commission: '2.00',
    approved_commission: '3.50',
    paid_commission: '7.00',
    available_for_payout: null,
    payouts_enabled: false,
    commission_verification: 'unverified_legacy',
    currency: null,
  },
  links: [{
    id: 71,
    name: 'Campaign A',
    url: 'https://marketedgepros.com/?ref=AFFILIATE7',
    clicks: 23,
    conversions: 4,
  }],
  link_pagination: { total: 1, limit: 50, truncated: false },
  recent_referrals: [{
    id: 91,
    status: 'converted',
    click_date: '2026-10-12T09:00:00Z',
    commission_amount: '7.00',
    currency: null,
  }],
  ...overrides,
});

const serviceUrl = new URL('../src/services/affiliateViewService.js', import.meta.url).href;
const uiTarget = new URL('../node_modules/.cache-ui4-affiliate-dashboard.mjs', import.meta.url);
let dashboardUi;
try {
  const file = new URL('../src/pages/affiliate/AffiliateDashboard.jsx', import.meta.url);
  const source = fs.readFileSync(file, 'utf8')
    .replace(/import useAuthStore from [^;]+;/, 'const useAuthStore = () => null;')
    .replace(/['"]\.\.\/\.\.\/services\/affiliateViewService['"]/g, JSON.stringify(serviceUrl));
  fs.writeFileSync(uiTarget, (await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' })).code);
  dashboardUi = await import(uiTarget.href);
} finally {
  fs.rmSync(uiTarget, { force: true });
}

const render = (component, props) => renderToStaticMarkup(
  React.createElement(MemoryRouter, null, React.createElement(component, props)),
);

test('UI4 affiliate dashboard maps only strict owner-bound, bounded, PII-free legacy records', () => {
  const dashboard = mapAffiliateDashboard(payload(), { expectedOwner: owner });
  assert.deepEqual(dashboard.ownerContext, owner);
  assert.equal(dashboard.stats.totalCommission, '12.50');
  assert.equal(dashboard.stats.currency, null);
  assert.equal(dashboard.stats.availableForPayout, null);
  assert.equal(dashboard.stats.payoutsEnabled, false);
  assert.equal(dashboard.stats.commissionVerification, 'unverified_legacy');
  assert.deepEqual(dashboard.links[0], {
    id: 71,
    name: 'Campaign A',
    url: 'https://marketedgepros.com/?ref=AFFILIATE7',
    clicks: 23,
    conversions: 4,
  });
  assert.deepEqual(dashboard.recentReferrals[0], {
    id: 91,
    status: 'converted',
    clickDate: '2026-10-12T09:00:00Z',
    commissionAmount: '7.00',
    currency: null,
  });
  assert.equal('email' in dashboard.recentReferrals[0], false);
  assert.equal('referredUser' in dashboard.recentReferrals[0], false);

  assert.throws(
    () => mapAffiliateDashboard(payload({ owner_context: { user_id: 20, tenant_id: 6 } }), { expectedOwner: owner }),
    /owner context does not match/i,
  );
  assert.throws(() => mapAffiliateDashboard(payload({ owner_context: undefined })), AffiliateViewContractError);
  assert.throws(
    () => mapAffiliateDashboard(payload({ stats: { ...payload().stats, payouts_enabled: true } }), { expectedOwner: owner }),
    /verification flags/i,
  );
  assert.throws(
    () => mapAffiliateDashboard(payload({ stats: { ...payload().stats, total_commission: 12.5 } }), { expectedOwner: owner }),
    /exact decimal/i,
  );
  assert.throws(
    () => mapAffiliateDashboard(payload({ recent_referrals: [{ ...payload().recent_referrals[0], referred_user: { email: 'private@example.test' } }] }), { expectedOwner: owner }),
    /must not contain referred user/i,
  );
  assert.throws(
    () => mapAffiliateDashboard(payload({ link_pagination: { total: 2, limit: 50, truncated: false } }), { expectedOwner: owner }),
    /pagination/i,
  );
});

test('UI4 affiliate dashboard requires caller owner and preserves unknown counters and unavailable links', async () => {
  assert.throws(() => mapAffiliateDashboard(payload()), AffiliateViewContractError);
  let calls = 0;
  const service = createAffiliateDashboardViewService({ get: async () => { calls += 1; return { data: payload() }; } });
  await assert.rejects(service.getDashboard(), AffiliateViewContractError);
  assert.equal(calls, 0);
  const data = payload();
  data.stats.total_clicks = null;
  data.links[0].clicks = null;
  data.links[0].url = null;
  const view = mapAffiliateDashboard(data, { expectedOwner: owner });
  assert.equal(view.stats.totalClicks, null);
  assert.equal(view.links[0].clicks, null);
  assert.equal(view.links[0].url, null);
  const html = render(dashboardUi.AffiliateDashboardView, { dashboard: view, isLoading: false });
  assert.match(html, /shareable canonical link is unavailable/);
  assert.doesNotMatch(html, /aria-label="Copy referral link/);
  for (const invalid of ['2026-02-31T09:00:00Z', 'not-a-date', '2026-10-12T25:00:00']) {
    const malformed = payload();
    malformed.recent_referrals[0].click_date = invalid;
    assert.throws(() => mapAffiliateDashboard(malformed, { expectedOwner: owner }), /click date is invalid/);
  }
  const duplicate = payload();
  duplicate.recent_referrals.push({ ...duplicate.recent_referrals[0] });
  assert.throws(() => mapAffiliateDashboard(duplicate, { expectedOwner: owner }), /duplicate/);
});

test('UI4 affiliate URL gate accepts only canonical public root referral URLs', () => {
  assert.equal(getSafeAffiliateReferralUrl('https://marketedgepros.com/?ref=ABC123'), 'https://marketedgepros.com/?ref=ABC123');
  for (const unsafe of [
    'https://marketedgepros.com:443/?ref=ABC123',
    'https://user@marketedgepros.com/?ref=ABC123',
    'https://marketedgepros.com/campaign?ref=ABC123',
    'https://marketedgepros.com/?ref=ABC123#fragment',
    'https://marketedgepros.com/?ref=abc123',
    'https://marketedgepros.com/?ref=ABC123&next=/admin',
    'https://marketedgepros.com/?ref=ABC123 ',
  ]) {
    assert.equal(getSafeAffiliateReferralUrl(unsafe), null, unsafe);
  }
});

test('UI4 affiliate dashboard forwards AbortSignal and rejects a late aborted projection', async () => {
  let getConfig;
  const controller = new AbortController();
  const service = createAffiliateDashboardViewService({
    get: async (path, config) => {
      getConfig = { path, config };
      return { data: payload() };
    },
  });
  const dashboard = await service.getDashboard({ signal: controller.signal, expectedOwner: owner });
  assert.equal(dashboard.links.length, 1);
  assert.equal(getConfig.path, '/affiliate/dashboard');
  assert.equal(getConfig.config.signal, controller.signal);

  let release;
  const lateService = createAffiliateDashboardViewService({
    get: () => new Promise((resolve) => { release = resolve; }),
  });
  const lateController = new AbortController();
  const pending = lateService.getDashboard({ signal: lateController.signal, expectedOwner: owner });
  lateController.abort();
  release({ data: payload() });
  await assert.rejects(pending, { name: 'AbortError' });
});

test('real React SSR dashboard view uses exact uncategorized decimals and excludes personal referral information', () => {
  const dashboard = mapAffiliateDashboard(payload(), { expectedOwner: owner });
  const html = render(dashboardUi.AffiliateDashboardView, {
    dashboard,
    isLoading: false,
    loadError: null,
  });
  assert.match(html, /12\.50/);
  assert.match(html, /Currency unavailable/);
  assert.match(html, /Legacy API category: paid/);
  assert.match(html, /role="region"/);
  assert.match(html, /Showing the first|1 reported links/);
  assert.doesNotMatch(html, /\$|USD|Referred trader|private@example\.test|available to withdraw/i);
});

test('dashboard source keys all state by auth, identity, tenant, and role and invalidates stale GET/copy completions', () => {
  const source = fs.readFileSync(new URL('../src/pages/affiliate/AffiliateDashboard.jsx', import.meta.url), 'utf8');
  assert.match(source, /key=\{contextKey\}/);
  assert.match(source, /isAuthenticated === true/);
  assert.match(source, /tenantId/);
  assert.match(source, /role/);
  assert.match(source, /AbortController/);
  assert.match(source, /loadGenerationRef/);
  assert.match(source, /dashboardGenerationRef/);
  assert.match(source, /copyGenerationRef/);
  assert.match(source, /requestControllerRef\.current\?\.abort\(\)/);
  assert.match(source, /loadAffiliateDashboard\(\{ signal: controller\.signal, expectedOwner \}\)/);
  assert.doesNotMatch(source, /setInterval|setTimeout/);
});

test('affiliate next action uses only supplied safe links and keeps payout unavailable', () => {
  const dashboard = mapAffiliateDashboard(payload(), { expectedOwner: owner });
  const html = render(dashboardUi.AffiliateDashboardView, { dashboard, isLoading: false });
  assert.match(html, /mep-workspace-hero/);
  assert.match(html, /affiliate-next-action-heading/);
  assert.match(html, /href="\/#affiliate-links-heading"/);
  assert.match(html, /Review supplied links/);
  assert.match(html, /Payout availability: not enabled/);
  assert.match(html, /href="\/affiliate\/payout"/);
  assert.doesNotMatch(html, /Earn 15%|Withdraw now|Verified earnings/);
});

test('affiliate missing-link next action points to real records; loading/error do not invent next-step data', () => {
  const raw = payload();
  raw.links[0].url = null;
  const dashboard = mapAffiliateDashboard(raw, { expectedOwner: owner });
  const html = render(dashboardUi.AffiliateDashboardView, { dashboard, isLoading: false });
  assert.match(html, /No shareable canonical link was returned/);
  assert.match(html, /href="\/affiliate\/traders"/);
  assert.doesNotMatch(html, /Review supplied links/);
  for (const props of [{ isLoading: true }, { isLoading: false, loadError: 'Synthetic unavailable' }]) {
    const stateHtml = render(dashboardUi.AffiliateDashboardView, props);
    assert.doesNotMatch(stateHtml, /affiliate-next-action-heading/);
  }
});
