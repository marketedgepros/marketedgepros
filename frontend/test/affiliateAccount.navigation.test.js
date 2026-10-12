import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const dashboardSource = fs.readFileSync(
  path.join(frontendDirectory, 'src', 'pages', 'affiliate', 'AffiliateDashboard.jsx'),
  'utf8',
);
const dashboardServiceSource = fs.readFileSync(
  path.join(frontendDirectory, 'src', 'services', 'affiliateViewService.js'),
  'utf8',
);
const payoutSource = fs.readFileSync(
  path.join(frontendDirectory, 'src', 'pages', 'affiliate', 'AffiliatePayout.jsx'),
  'utf8',
);

test('affiliate dashboard uses the account view service, current auth identity, and protected navigation targets', () => {
  assert.match(dashboardSource, /useAuthStore/);
  assert.match(dashboardSource, /loadAffiliateDashboard/);
  assert.match(dashboardSource, /affiliateViewError/);
  assert.match(dashboardSource, /loadGenerationRef/);
  assert.match(dashboardSource, /generation !== loadGenerationRef\.current/);

  for (const route of [
    '/affiliate/traders',
    '/affiliate/commissions',
    '/affiliate/reports',
    '/affiliate/payout',
    '/support/create-ticket',
  ]) {
    assert.ok(dashboardSource.includes(`to="${route}"`), `dashboard must link to ${route}`);
  }

  assert.match(dashboardSource, /totalCommission/);
  assert.match(dashboardSource, /pendingCommission/);
  assert.match(dashboardSource, /approvedCommission/);
  assert.match(dashboardSource, /paidCommission/);
  assert.match(dashboardSource, /const UNAVAILABLE = 'Unavailable'/);
  assert.doesNotMatch(dashboardSource, /<Layout[\s>]/);
  assert.doesNotMatch(dashboardSource, /api\.post|\/affiliate\/links/);
});

test('affiliate dashboard copies only safe server links with a single in-flight clipboard request', () => {
  assert.match(dashboardSource, /getSafeAffiliateReferralUrl/);
  assert.match(dashboardServiceSource, /url\.protocol !== 'https:'/);
  assert.match(dashboardServiceSource, /url\.hostname !== 'marketedgepros\.com'/);
  assert.match(dashboardSource, /copyInFlightRef\.current/);
  assert.match(dashboardSource, /navigator\.clipboard\?\.writeText/);
  assert.match(dashboardSource, /status: 'copied'/);
  assert.match(dashboardSource, /status: 'error'/);
});

test('affiliate payout remains a read-only status page with safe account navigation', () => {
  assert.match(payoutSource, /Payout execution is unavailable/);
  for (const route of [
    '/affiliate/dashboard',
    '/affiliate/commissions',
    '/support/create-ticket',
  ]) {
    assert.ok(payoutSource.includes(`to="${route}"`), `payout page must link to ${route}`);
  }

  assert.doesNotMatch(payoutSource, /<Layout[\s>]/);
  assert.doesNotMatch(payoutSource, /api\.get|api\.post|<form|\/affiliate\/balance|\/affiliate\/payouts\/request/);
});
