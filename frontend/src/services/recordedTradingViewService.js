import api from './api.js';

export const HISTORY_PATH = '/traders/history';
export const SCALING_SELF_PATH = '/scaling/my-progress';
export const SCALING_ADMIN_PATH = '/scaling/admin/all-users';
export const PAGE_LIMIT = 1000;
export const PAGE_SIZE = 20;
const ID_LIMIT = 2147483647;
const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const ADMIN_ROLES = new Set(['supermaster', 'master']);
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const requireObject = (value) => {
  if (!object(value)) throw new Error('Recorded response is incomplete.');
  return value;
};
const integer = (value, maximum = Number.MAX_SAFE_INTEGER, minimum = 0) => {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error('Recorded integer is invalid.');
  }
  return value;
};
const id = (value) => integer(value, ID_LIMIT, 1);
const nullableInteger = (value) => value === null ? null : integer(value);
const text = (value, maximum = 256) => {
  if (typeof value !== 'string' || value.length > maximum || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(value)) {
    throw new Error('Recorded text is invalid.');
  }
  return value;
};
const nullableText = (value, maximum) => value === null ? null : text(value, maximum);
export const recordedDecimal = (value) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length > 128 || !DECIMAL.test(value)) {
    throw new Error('Recorded value must be an exact decimal string or null.');
  }
  return value;
};
const timestamp = (value) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length > 64 || !/^\d{4}-\d\d-\d\dT/.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new Error('Recorded timestamp is invalid.');
  }
  return value;
};

export function recordedPrincipal(user) {
  try {
    const tenant = user?.tenant_id ?? null;
    if (tenant !== null) id(tenant);
    return { user_id: id(user?.id), tenant_id: tenant, role: text(user.role, 32) };
  } catch {
    return null;
  }
}
export const recordedIdentityKey = (principal) => JSON.stringify([
  principal?.user_id ?? null, principal?.tenant_id ?? null, principal?.role ?? null,
]);
export const isScalingAdmin = (principal) => ADMIN_ROLES.has(principal?.role);

export function normalizeRecordedOwner(value, expectedOwner) {
  const owner = requireObject(value);
  const normalized = { user_id: id(owner.user_id), tenant_id: owner.tenant_id === null ? null : id(owner.tenant_id) };
  if (!expectedOwner || normalized.user_id !== expectedOwner.user_id || normalized.tenant_id !== expectedOwner.tenant_id) {
    throw new Error('Recorded response owner does not match the current account.');
  }
  return normalized;
}
function boundary(payload, expectedOwner, scaling = false) {
  requireObject(payload);
  if (payload.data_status !== 'unverified_legacy' || payload.provider_authenticated !== false || payload.currency !== null
    || (scaling && (payload.success !== true || payload.scaling_enabled !== false))) {
    throw new Error('Recorded response verification boundary is invalid.');
  }
  return { owner_context: normalizeRecordedOwner(payload.owner_context, expectedOwner), data_status: 'unverified_legacy', provider_authenticated: false, currency: null };
}
export function normalizeRecordedPagination(value, expectedPage, expectedPerPage) {
  const data = requireObject(value);
  const result = {
    page: integer(data.page, PAGE_LIMIT, 1),
    per_page: integer(data.per_page, 100, 1),
    total: integer(data.total), pages: integer(data.pages),
  };
  if (result.pages !== Math.ceil(result.total / result.per_page)
    || result.page !== expectedPage || result.per_page !== expectedPerPage) {
    throw new Error('Recorded pagination does not match the requested context.');
  }
  return result;
}
export function buildRecordedHistoryParams({ page = 1, per_page = PAGE_SIZE, symbol = '', type = 'all', period = 'all' } = {}) {
  if (typeof symbol !== 'string' || symbol.length > 20 || (symbol && !/^[A-Za-z0-9._-]+$/.test(symbol))) {
    throw new Error('Symbol must contain at most 20 letters, numbers, dots, underscores or hyphens.');
  }
  if (!['all', 'buy', 'sell'].includes(type) || !['all', 'today', 'week', 'month'].includes(period)) {
    throw new Error('Recorded history filter is invalid.');
  }
  return { page: integer(page, PAGE_LIMIT, 1), per_page: integer(per_page, 100, 1), symbol: symbol.toUpperCase(), type, period };
}
export function normalizeRecordedHistory(payload, expectedOwner, params) {
  const context = boundary(payload, expectedOwner);
  const pagination = normalizeRecordedPagination(payload.pagination, params.page, params.per_page);
  const filters = requireObject(payload.filters);
  if (filters.symbol !== params.symbol || filters.type !== params.type || filters.period !== params.period) {
    throw new Error('Recorded history filters do not match the request.');
  }
  if (!Array.isArray(payload.trades) || payload.trades.length > pagination.per_page || payload.trades.length > pagination.total) {
    throw new Error('Recorded trade list is invalid.');
  }
  const seen = new Set();
  const trades = payload.trades.map((row) => {
    requireObject(row);
    const rowId = id(row.id);
    if (seen.has(rowId)) throw new Error('Duplicate recorded trade.');
    seen.add(rowId);
    const trade = { id: rowId, challenge_id: id(row.challenge_id), symbol: text(row.symbol, 20), trade_type: text(row.trade_type, 10),
      status: nullableText(row.status, 20), open_time: timestamp(row.open_time), close_time: timestamp(row.close_time) };
    if (!trade.symbol || (params.type !== 'all' && trade.trade_type !== params.type)
      || (params.symbol && trade.symbol.toUpperCase() !== params.symbol)) {
      throw new Error('Recorded trade does not match the filter.');
    }
    for (const field of ['volume', 'open_price', 'close_price', 'profit', 'commission', 'swap']) trade[field] = recordedDecimal(row[field]);
    return trade;
  });
  const stats = requireObject(payload.statistics);
  const statistics = { total_trades: integer(stats.total_trades), winning_trades: nullableInteger(stats.winning_trades),
    losing_trades: nullableInteger(stats.losing_trades), total_profit: recordedDecimal(stats.total_profit) };
  if (statistics.total_trades !== pagination.total || (statistics.winning_trades !== null && statistics.winning_trades > pagination.total)
    || (statistics.losing_trades !== null && statistics.losing_trades > pagination.total)
    || (statistics.winning_trades !== null && statistics.losing_trades !== null
      && statistics.winning_trades + statistics.losing_trades > pagination.total)) {
    throw new Error('Recorded statistics are inconsistent.');
  }
  return { trades, pagination, filters: { ...filters }, statistics, ...context };
}
function normalizeScalingRow(row) {
  requireObject(row);
  const result = { user_id: id(row.user_id), status: nullableText(row.status, 20), last_scaled_at: timestamp(row.last_scaled_at),
    created_at: timestamp(row.created_at), current_tier: nullableInteger(row.current_tier), next_tier: nullableInteger(row.next_tier),
    times_scaled: nullableInteger(row.times_scaled) };
  for (const field of ['current_account_size', 'next_account_size', 'total_profit', 'target_profit', 'progress_percentage']) {
    result[field] = recordedDecimal(row[field]);
  }
  if (row.is_eligible_for_scaling !== false) throw new Error('Legacy eligibility is not scaling authorization.');
  return { ...result, is_eligible_for_scaling: false };
}
export function normalizeRecordedScaling(payload, expectedOwner, { admin = false, page = 1, per_page = PAGE_SIZE } = {}) {
  const context = boundary(payload, expectedOwner, true);
  if (!admin) {
    const data = payload.data === null ? null : normalizeScalingRow(payload.data);
    if (data && data.user_id !== context.owner_context.user_id) throw new Error('Scaling record belongs to another account.');
    return { data, ...context, scaling_enabled: false };
  }
  if (!Array.isArray(payload.data)) throw new Error('Recorded scaling list is incomplete.');
  const pagination = normalizeRecordedPagination(payload.pagination, page, per_page);
  if (payload.data.length > pagination.per_page || payload.data.length > pagination.total) throw new Error('Scaling list exceeds its page.');
  const seen = new Set();
  const data = payload.data.map((row) => {
    const record = { ...normalizeScalingRow(row), name: nullableText(row.name, 256), email: nullableText(row.email, 320) };
    if (seen.has(record.user_id)) throw new Error('Duplicate recorded scaling owner.');
    seen.add(record.user_id);
    return record;
  });
  return { data, pagination, ...context, scaling_enabled: false };
}
export function createRecordedTradingViewService(client = api) {
  return {
    async history({ expectedOwner, signal, ...filters }) {
      const params = buildRecordedHistoryParams(filters);
      const response = await client.get(HISTORY_PATH, { params, signal });
      return normalizeRecordedHistory(response?.data, expectedOwner, params);
    },
    async scaling({ expectedOwner, admin = false, page = 1, per_page = PAGE_SIZE, signal }) {
      const params = { page: integer(page, PAGE_LIMIT, 1), per_page: integer(per_page, 100, 1) };
      const response = await client.get(admin ? SCALING_ADMIN_PATH : SCALING_SELF_PATH, { ...(admin ? { params } : {}), signal });
      return normalizeRecordedScaling(response?.data, expectedOwner, { admin, ...params });
    },
  };
}

// Every cell is quoted. Dangerous spreadsheet prefixes are neutralized even after
// leading spaces/control/Unicode separators; this is a report, not executable input.
export function recordedCsvCell(value) {
  let cell = value === null || value === undefined ? '' : String(value);
  if (/^[\s\p{Cc}\p{Cf}\p{Z}\p{M}]*[=+\-@]/u.test(cell)) cell = `'${cell}`;
  return `"${cell.replaceAll('"', '""')}"`;
}
export function buildRecordedHistoryCsv(view) {
  if (!view || view.data_status !== 'unverified_legacy' || view.provider_authenticated !== false || !Array.isArray(view.trades)) {
    throw new Error('A validated recorded history page is required.');
  }
  const fields = ['id', 'challenge_id', 'symbol', 'trade_type', 'volume', 'open_price', 'close_price', 'open_time', 'close_time', 'profit', 'commission', 'swap', 'status'];
  return [fields.map(recordedCsvCell).join(','), ...view.trades.map((row) => fields.map((field) => recordedCsvCell(row[field])).join(','))].join('\r\n') + '\r\n';
}
export function downloadRecordedHistoryPage(view, environment = globalThis) {
  const csv = buildRecordedHistoryCsv(view);
  const anchor = environment.document.createElement('a');
  const url = environment.URL.createObjectURL(new environment.Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' }));
  try {
    anchor.href = url;
    anchor.download = `unverified-trading-history-page-${view.pagination.page}.csv`;
    environment.document.body.appendChild(anchor);
    anchor.click();
  } finally {
    try { anchor.remove(); }
    finally { environment.URL.revokeObjectURL(url); }
  }
}
