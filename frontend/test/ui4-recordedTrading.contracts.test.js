import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildRecordedHistoryParams, normalizeRecordedHistory, normalizeRecordedScaling,
  recordedIdentityKey, recordedPrincipal, createRecordedTradingViewService,
  recordedCsvCell, buildRecordedHistoryCsv, downloadRecordedHistoryPage,
} from '../src/services/recordedTradingViewService.js';
import api, { tradersAPI } from '../src/services/api.js';

const owner = { user_id: 9, tenant_id: 7 };
const context = { owner_context: owner, data_status: 'unverified_legacy', provider_authenticated: false, currency: null };
const params = buildRecordedHistoryParams();
const trade = (overrides = {}) => ({ id: 1, challenge_id: 11, symbol: 'EURUSD', trade_type: 'buy', volume: '0.00',
  open_price: '1.12345', close_price: null, profit: null, commission: '0.00', swap: '-0.01', status: 'open',
  open_time: '2026-10-12T10:00:00', close_time: null, ...overrides });
const history = (overrides = {}) => ({ ...context, trades: [trade()], filters: { symbol: '', type: 'all', period: 'all' },
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  statistics: { total_trades: 1, winning_trades: null, losing_trades: null, total_profit: null }, ...overrides });
const scalingRow = (overrides = {}) => ({ user_id: 9, current_tier: 1, current_account_size: '10000.00', next_tier: null,
  next_account_size: null, total_profit: '0.00', target_profit: '800.00', progress_percentage: null, times_scaled: 0,
  last_scaled_at: null, created_at: '2026-10-12T10:00:00', status: 'active', is_eligible_for_scaling: false, ...overrides });
const scaling = (data = scalingRow()) => ({ ...context, success: true, scaling_enabled: false, data });

test('recorded history preserves exact native volume and NULL, not invented lots, pips or currency', () => {
  const view = normalizeRecordedHistory(history(), owner, params);
  assert.equal(view.trades[0].volume, '0.00'); assert.equal(view.trades[0].profit, null);
  assert.equal(view.trades[0].swap, '-0.01'); assert.equal(view.currency, null);
  assert.equal('lots' in view.trades[0], false); assert.equal('pips' in view.trades[0], false);
  for (const value of [0, NaN, Infinity, '1e3', 'NaN', '01.00', undefined]) {
    assert.throws(() => normalizeRecordedHistory(history({ trades: [trade({ profit: value })] }), owner, params));
  }
});
test('history refuses wrong identity, tenant, flags, totals, duplicate rows and mismatched filters', () => {
  for (const patch of [{ owner_context: { ...owner, user_id: 10 } }, { owner_context: { ...owner, tenant_id: 8 } },
    { owner_context: null }, { provider_authenticated: true }, { currency: 'USD' }, { data_status: 'verified' },
    { statistics: { total_trades: 0, winning_trades: 0, losing_trades: 0, total_profit: '0.00' } },
    { trades: [trade(), trade()], pagination: { page: 1, per_page: 20, total: 2, pages: 1 } },
    { filters: { symbol: 'GBP', type: 'all', period: 'all' } }, { pagination: { page: 2, per_page: 20, total: 1, pages: 1 } }]) {
    assert.throws(() => normalizeRecordedHistory(history(patch), owner, params));
  }
  assert.throws(() => normalizeRecordedHistory(history({ trades: [trade({ trade_type: 'sell' })], filters: { symbol: '', type: 'buy', period: 'all' } }), owner, buildRecordedHistoryParams({ type: 'buy' })));
});
test('history pagination and filter input are typed and bounded before transport', async () => {
  let calls = 0;
  const service = createRecordedTradingViewService({ get: async () => { calls++; return { data: history() }; } });
  for (const input of [{ page: 0 }, { page: 1001 }, { page: '1' }, { per_page: 101 }, { type: 'BUY' }, { period: 'this_month' },
    { symbol: 'x'.repeat(21) }, { symbol: '%' }, { symbol: 'EUR\nUSD' }, { symbol: ['EUR'] }]) {
    await assert.rejects(() => service.history({ expectedOwner: owner, ...input }));
  }
  assert.equal(calls, 0);
  assert.equal(buildRecordedHistoryParams({ symbol: 'eur_usd.a' }).symbol, 'EUR_USD.A');
});
test('real Axios history paths and AbortSignal are preserved with one API prefix', async () => {
  const previous = api.defaults.adapter; const calls = []; const controller = new AbortController();
  api.defaults.adapter = async (config) => { calls.push(config); return { config, status: 200, statusText: 'OK', headers: {}, data: history() }; };
  try {
    await createRecordedTradingViewService(api).history({ expectedOwner: owner, signal: controller.signal });
    await tradersAPI.getTradingHistory({ page: 1 }, { signal: controller.signal });
    assert.equal(calls.length, 2); assert.equal(calls[0].url, '/traders/history');
    assert.equal(calls[0].signal, controller.signal); assert.equal(calls[1].signal, controller.signal);
    assert.match(api.getUri(calls[0]), /^\/api\/v1\/traders\/history\?/); assert.equal(calls[0].withCredentials, true);
  } finally { api.defaults.adapter = previous; }
});
test('Scaling is read-only, NULL plan is not error, own row and eligibility are validated', () => {
  const view = normalizeRecordedScaling(scaling(), owner);
  assert.equal(view.data.total_profit, '0.00'); assert.equal(view.data.times_scaled, 0);
  assert.equal(view.data.next_account_size, null); assert.equal(view.scaling_enabled, false);
  assert.equal(normalizeRecordedScaling(scaling(null), owner).data, null);
  for (const patch of [{ scaling_enabled: true }, { success: 'true' }, { data: scalingRow({ user_id: 10 }) },
    { data: scalingRow({ is_eligible_for_scaling: true }) }, { data: {} }, { data: scalingRow({ total_profit: 0 }) }]) {
    assert.throws(() => normalizeRecordedScaling({ ...scaling(), ...patch }, owner));
  }
});
test('Scaling admin pages remain scoped to caller and reject duplicate owners or page mismatch', () => {
  const payload = { ...scaling(), data: [{ ...scalingRow(), name: 'Synthetic', email: 'trader@synthetic.invalid' }], pagination: { page: 1, per_page: 20, total: 1, pages: 1 } };
  assert.equal(normalizeRecordedScaling(payload, owner, { admin: true }).data.length, 1);
  assert.throws(() => normalizeRecordedScaling(payload, owner, { admin: true, page: 2 }));
  assert.throws(() => normalizeRecordedScaling({ ...payload, data: [...payload.data, ...payload.data], pagination: { page: 1, per_page: 20, total: 2, pages: 1 } }, owner, { admin: true }));
});
test('principal identity keys distinguish same-user brand/role switches and missing identity', () => {
  assert.equal(recordedPrincipal({ id: '9', tenant_id: 7, role: 'trader' }), null);
  const principal = recordedPrincipal({ id: 9, tenant_id: 7, role: 'trader' });
  assert.notEqual(recordedIdentityKey(principal), recordedIdentityKey({ ...principal, tenant_id: 8 }));
  assert.notEqual(recordedIdentityKey(principal), recordedIdentityKey({ ...principal, role: 'affiliate' }));
});
test('CSV escapes separators, quotes, newlines, control and Unicode formula prefixes', () => {
  assert.equal(recordedCsvCell('a,"b"\nc'), '"a,""b""\nc"');
  for (const value of ['=HYPERLINK(1)', '\t+1', '\r-1', '@SUM(1)', '\uFEFF=1', '\u200B=1', ' \u202E+1']) {
    assert.match(recordedCsvCell(value), /^"'/);
  }
  assert.equal(recordedCsvCell(null), '""');
  const csv = buildRecordedHistoryCsv(normalizeRecordedHistory(history(), owner, params));
  assert.match(csv, /"volume"/); assert.doesNotMatch(csv, /"pips"|"lots"|"USD"|\$/);
  assert.match(csv, /"0\.00"/); assert.equal(csv.endsWith('\r\n'), true);
});
test('CSV downloads current page and releases URL/DOM even when click fails', () => {
  const view = normalizeRecordedHistory(history(), owner, params); const calls = [];
  const anchor = { click() { calls.push('click'); throw new Error('synthetic click'); }, remove() { calls.push('remove'); } };
  const environment = { Blob: class { constructor(parts) { assert.equal(parts[0], '\uFEFF'); } },
    URL: { createObjectURL() { calls.push('url'); return 'blob:synthetic'; }, revokeObjectURL(url) { calls.push(url); } },
    document: { createElement() { return anchor; }, body: { appendChild() { calls.push('append'); } } } };
  assert.throws(() => downloadRecordedHistoryPage(view, environment), /synthetic click/);
  assert.deepEqual(calls, ['url', 'append', 'click', 'remove', 'blob:synthetic']);
  assert.equal(anchor.download, 'unverified-trading-history-page-1.csv');
});

test('UI4 review regression: C0/C1/Unicode formatting and separator formula prefixes are neutralized', () => {
  for (const prefix of ['\u0000', '\u0001', '\u001B', '\u007F', '\u0080', '\u0085', '\u009F', '\u00AD', '\u034F', '\u061C', '\u200E', '\u2028', '\u2066', '\uFEFF']) {
    for (const operator of ['=', '+', '-', '@']) assert.match(recordedCsvCell(prefix + operator + '1'), /^"'/);
  }
  // C1 is a real allowed legacy status path, not only a helper-only input.
  const view = normalizeRecordedHistory(history({ trades: [trade({ status: '\u0085=1' })] }), owner, params);
  assert.match(buildRecordedHistoryCsv(view), /"'\u0085=1"/);
});
test('UI4 review regression: symbol equality matches backend, not a prefix/substring match', () => {
  const request = buildRecordedHistoryParams({ symbol: 'EURUSD' });
  const response = history({ trades: [trade({ symbol: 'EURUSD2' })], filters: { symbol: 'EURUSD', type: 'all', period: 'all' } });
  assert.throws(() => normalizeRecordedHistory(response, owner, request), /does not match the filter/);
  assert.equal(normalizeRecordedHistory({ ...response, trades: [trade({ symbol: 'eurusd' })] }, owner, request).trades[0].symbol, 'eurusd');
});
