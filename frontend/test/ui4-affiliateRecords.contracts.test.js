import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';
import {
  AFFILIATE_RECORD_ENDPOINTS,
  AffiliateRecordContractError,
  buildAffiliateCommissionsCsv,
  buildAffiliateRecordParams,
  createAffiliateRecordViewService,
  downloadAffiliateCommissionsPage,
  normalizeAffiliateRecordResponse,
} from '../src/services/affiliateRecordViewService.js';
import { mapAffiliateCommissions, mapAffiliateReferrals } from '../src/services/affiliateRecordsViewService.js';

const owner = { user_id: 9, tenant_id: 7 };
const flags = { verification: 'unverified_legacy', payouts_enabled: false, available_for_payout: null, currency: null };
const referral = (patch = {}) => ({ id: 101, status: 'converted', click_date: '2026-10-12T10:00:00Z', conversion_date: null, purchase_amount: '100.00', commission_amount: '25.00', currency: null, ...patch });
const commission = (patch = {}) => ({ id: 201, amount: '25.00', type: 'referral', status: 'approved', created_at: '2026-10-12T10:00:00Z', approved_at: '2026-10-13T10:00:00Z', paid_at: null, currency: null, ...patch });
const response = (kind, rows, patch = {}) => ({
  owner_context: owner,
  ...flags,
  pagination: { page: 1, per_page: 20, total: rows.length, pages: rows.length ? 1 : 0 },
  filters: { status: null },
  [kind]: rows,
  ...patch,
});

const referralParams = buildAffiliateRecordParams('referrals');
const commissionParams = buildAffiliateRecordParams('commissions');

test('affiliate record maps require current owner, strict flags, exact decimal strings, typed dates and unique IDs', () => {
  const referrals = response('referrals', [referral()]);
  const commissions = response('commissions', [commission()]);
  const referralsView = normalizeAffiliateRecordResponse('referrals', referrals, { expectedOwner: owner, params: referralParams });
  const commissionsView = normalizeAffiliateRecordResponse('commissions', commissions, { expectedOwner: owner, params: commissionParams });
  assert.deepEqual(referralsView.referrals[0], { id: 101, status: 'converted', clickDate: '2026-10-12T10:00:00Z', conversionDate: null, purchaseAmount: '100.00', commissionAmount: '25.00', currency: null });
  assert.equal(commissionsView.commissions[0].amount, '25.00');
  assert.equal('description' in commissionsView.commissions[0], false);
  assert.equal('email' in referralsView.referrals[0], false);
  assert.deepEqual(mapAffiliateReferrals(referrals, { expectedOwner: owner, page: 1, perPage: 20, status: null }), referralsView);
  assert.deepEqual(mapAffiliateCommissions(commissions, { expectedOwner: owner, page: 1, perPage: 20, status: null }), commissionsView);

  for (const malformed of [
    response('referrals', [referral({ purchase_amount: 25 })]),
    response('referrals', [referral({ click_date: '2026-02-31T10:00:00Z' })]),
    response('referrals', [referral(), referral()]),
    response('referrals', [referral({ email: 'private@example.test' })]),
    response('referrals', [referral()], { currency: 'USD' }),
    response('referrals', [referral()], { owner_context: { user_id: 10, tenant_id: 7 } }),
  ]) {
    assert.throws(() => normalizeAffiliateRecordResponse('referrals', malformed, { expectedOwner: owner, params: referralParams }), AffiliateRecordContractError);
  }
  assert.throws(() => normalizeAffiliateRecordResponse('commissions', response('commissions', [commission({ amount: '1e3' })]), { expectedOwner: owner, params: commissionParams }), AffiliateRecordContractError);
});

test('bounded page/filter inputs fail before transport and an empty request beyond total remains valid', async () => {
  let calls = 0;
  const service = createAffiliateRecordViewService({ get: async () => { calls += 1; return { data: response('referrals', []) }; } });
  for (const options of [
    { expectedOwner: owner, role: 'affiliate', page: 0 },
    { expectedOwner: owner, role: 'affiliate', page: 10001 },
    { expectedOwner: owner, role: 'affiliate', perPage: 51 },
    { expectedOwner: owner, role: 'affiliate', status: 'all' },
    { expectedOwner: owner, role: 'trader' },
    { role: 'affiliate' },
  ]) await assert.rejects(() => service.referrals(options));
  assert.equal(calls, 0);

  const params = buildAffiliateRecordParams('referrals', { page: 2, perPage: 20, status: null });
  const beyond = response('referrals', [], { pagination: { page: 2, per_page: 20, total: 1, pages: 1 } });
  const view = normalizeAffiliateRecordResponse('referrals', beyond, { expectedOwner: owner, params });
  assert.equal(view.referrals.length, 0);
  assert.equal(view.pagination.page, 2);
});

test('injectable GET receives signal and rejects late aborted record response', async () => {
  let config;
  const controller = new AbortController();
  const service = createAffiliateRecordViewService({ get: async (path, nextConfig) => { config = { path, nextConfig }; return { data: response('commissions', [commission()]) }; } });
  await service.commissions({ expectedOwner: owner, role: 'affiliate', signal: controller.signal });
  assert.equal(config.path, AFFILIATE_RECORD_ENDPOINTS.commissions);
  assert.equal(config.nextConfig.signal, controller.signal);
  assert.deepEqual(config.nextConfig.params, { page: 1, per_page: 20 });

  let release;
  const delayed = createAffiliateRecordViewService({ get: () => new Promise((resolve) => { release = resolve; }) });
  const late = new AbortController();
  const pending = delayed.referrals({ expectedOwner: owner, role: 'affiliate', signal: late.signal });
  late.abort(); release({ data: response('referrals', [referral()]) });
  await assert.rejects(pending, { name: 'AbortError' });
});

test('commission CSV is limited to a validated current page, preserves exact strings and cleans DOM/blob on failure', () => {
  const view = normalizeAffiliateRecordResponse('commissions', response('commissions', [commission({ type: '\u200B=unsafe', status: 'pending' })]), { expectedOwner: owner, params: commissionParams });
  const csv = buildAffiliateCommissionsCsv(view);
  assert.match(csv, /unverified legacy; currency unavailable/i);
  assert.match(csv, /"'\u200B=unsafe"/);
  assert.match(csv, /"25\.00"/);
  assert.doesNotMatch(csv, /\$|USD|description/i);

  const calls = [];
  const anchor = { click() { calls.push('click'); throw new Error('synthetic click'); }, remove() { calls.push('remove'); } };
  const environment = {
    Blob: class { constructor(parts) { assert.equal(parts[0], '\uFEFF'); } },
    URL: { createObjectURL() { calls.push('url'); return 'blob:affiliate'; }, revokeObjectURL(value) { calls.push(value); } },
    document: { createElement() { return anchor; }, body: { appendChild() { calls.push('append'); } } },
  };
  assert.throws(() => downloadAffiliateCommissionsPage(view, environment), /synthetic click/);
  assert.deepEqual(calls, ['url', 'append', 'click', 'remove', 'blob:affiliate']);
});

const uiServiceUrl = new URL('../src/services/affiliateRecordViewService.js', import.meta.url).href;
const uiTarget = new URL('../node_modules/.cache-ui4-affiliate-records-ui.mjs', import.meta.url);
let ui;
try {
  const file = new URL('../src/components/affiliate/AffiliateRecordUI.jsx', import.meta.url);
  const source = fs.readFileSync(file, 'utf8').replace(/['"]\.\.\/\.\.\/services\/affiliateRecordViewService\.js['"]/g, JSON.stringify(uiServiceUrl));
  fs.writeFileSync(uiTarget, (await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' })).code);
  ui = await import(uiTarget.href);
} finally { fs.rmSync(uiTarget, { force: true }); }

const render = (element) => renderToStaticMarkup(React.createElement(MemoryRouter, null, element));

test('actual React SSR shared UI exposes status, select-safe controls, bounded pagination and unavailable currency without PII', () => {
  const loading = render(React.createElement(ui.AffiliateRecordReadState, { loading: true }));
  assert.match(loading, /role="status"/); assert.match(loading, /aria-busy="true"/);
  const error = render(React.createElement(ui.AffiliateRecordReadState, { error: 'bad', onRetry: () => {} }));
  assert.match(error, /role="alert"/); assert.match(error, /Retry records/);
  const pager = render(React.createElement(ui.AffiliateRecordPagination, { pagination: { page: 10000, per_page: 20, total: 200020, pages: 10001 }, onPage: () => {} }));
  assert.match(pager, /Browsing is limited to 10000 pages/); assert.match(pager, /aria-label="Affiliate records pagination"/);
  const amount = render(React.createElement(ui.AffiliateExactAmount, { value: '0.00' }));
  assert.match(amount, /0\.00/); assert.match(amount, /Currency unavailable/); assert.doesNotMatch(amount, /\$/);
});

test('in-range short server pages fail closed while exact last and beyond-total pages remain valid', () => {
  const options = { expectedOwner: owner, params: buildAffiliateRecordParams('referrals', { page: 1, perPage: 2 }) };
  const short = response('referrals', [referral()], { pagination: { page: 1, per_page: 2, total: 3, pages: 2 } });
  assert.throws(() => normalizeAffiliateRecordResponse('referrals', short, options), /pagination total/);
  const last = response('referrals', [referral()], { pagination: { page: 2, per_page: 2, total: 3, pages: 2 } });
  assert.equal(normalizeAffiliateRecordResponse('referrals', last, { expectedOwner: owner, params: buildAffiliateRecordParams('referrals', { page: 2, perPage: 2 }) }).referrals.length, 1);
  const beyond = response('referrals', [], { pagination: { page: 3, per_page: 2, total: 3, pages: 2 } });
  assert.equal(normalizeAffiliateRecordResponse('referrals', beyond, { expectedOwner: owner, params: buildAffiliateRecordParams('referrals', { page: 3, perPage: 2 }) }).referrals.length, 0);
});

test('complete-payload compatibility maps infer omitted filters but never replace explicit caller filters', () => {
  const referrals = response('referrals', [referral({ status: 'pending' })], { filters: { status: 'pending' } });
  const commissions = response('commissions', [commission({ status: 'approved' })], { filters: { status: 'approved' } });
  assert.equal(mapAffiliateReferrals(referrals, { expectedOwner: owner }).filters.status, 'pending');
  assert.equal(mapAffiliateCommissions(commissions, { expectedOwner: owner }).filters.status, 'approved');
  for (const [payload, mapper] of [[referrals, mapAffiliateReferrals], [commissions, mapAffiliateCommissions]]) {
    assert.throws(() => mapper(payload, { expectedOwner: owner, status: null }), /echo the request/);
  }
});

test('affiliate record routes keep a support destination without a floating chat over record amounts', () => {
  const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(app, /\['\/affiliate\/traders', '\/affiliate\/commissions', '\/affiliate\/reports'\]\.includes\(location\.pathname\)\) return null/);
  const navigation = render(React.createElement(ui.AffiliateRecordNavigation));
  assert.match(navigation, /href="\/support\/create-ticket"/);
});

test('an echoed status filter cannot authorize rows with a different status', () => {
  const forged = response('commissions', [commission({ status: 'paid' })], { filters: { status: 'approved' } });
  assert.throws(() => normalizeAffiliateRecordResponse('commissions', forged, { expectedOwner: owner, params: buildAffiliateRecordParams('commissions', { status: 'approved' }) }), /requested status filter/);
});
