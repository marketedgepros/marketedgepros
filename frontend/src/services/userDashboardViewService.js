import api from './api.js';

export const USER_DASHBOARD_ENDPOINT = '/users/dashboard';

const COUNT_NAMES = ['total', 'pending', 'active', 'passed', 'failed', 'funded'];
const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const ISO_TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?$/;

export class UserDashboardContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'UserDashboardContractError';
  }
}

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOwn = (record, field) => Object.prototype.hasOwnProperty.call(record, field);

const contractError = (message) => {
  throw new UserDashboardContractError(`Dashboard response ${message}.`);
};

const requireRecord = (value, label) => {
  if (!isRecord(value)) contractError(`${label} is missing or invalid`);
  return value;
};

const requireList = (value, label) => {
  if (!Array.isArray(value)) contractError(`${label} is missing or invalid`);
  return value;
};

const requireField = (record, field, label) => {
  if (!hasOwn(record, field)) contractError(`${label}.${field} is missing`);
  return record[field];
};

const positiveInteger = (value) => (
  Number.isSafeInteger(value) && value > 0 ? value : null
);

const nonNegativeIntegerOrNull = (value) => (
  value === null || (Number.isSafeInteger(value) && value >= 0) ? value : null
);

const requirePositiveInteger = (record, field, label) => {
  const value = positiveInteger(requireField(record, field, label));
  if (value === null) contractError(`${label}.${field} must be a positive integer`);
  return value;
};

const requireNullableNonNegativeInteger = (record, field, label) => {
  const value = requireField(record, field, label);
  const normalized = nonNegativeIntegerOrNull(value);
  if (normalized === null && value !== null) {
    contractError(`${label}.${field} must be a non-negative integer or null`);
  }
  return normalized;
};

const requireStrictText = (value, label, { nullable = false } = {}) => {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || !value.trim() || value !== value.trim()) {
    contractError(`${label} must be a non-empty string${nullable ? ' or null' : ''}`);
  }
  return value;
};

const requireNullableText = (record, field, label) => (
  requireStrictText(requireField(record, field, label), `${label}.${field}`, { nullable: true })
);

const requireStatusText = (record, field, label) => (
  requireStrictText(requireField(record, field, label), `${label}.${field}`)
);

const isCalendarDate = (year, month, day) => {
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= monthDays[month - 1];
};

/** A date must be a real complete ISO calendar timestamp; Date.parse normalizes invalid dates. */
export const recordedTimestampOrNull = (value) => {
  if (value === null) return null;
  if (typeof value !== 'string') return null;

  const matched = ISO_TIMESTAMP_PATTERN.exec(value);
  if (!matched) return null;

  const [, rawYear, rawMonth, rawDay, rawHour, rawMinute, rawSecond, zone] = matched;
  const year = Number(rawYear);
  const month = Number(rawMonth);
  const day = Number(rawDay);
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  const second = Number(rawSecond);
  if (!isCalendarDate(year, month, day) || hour > 23 || minute > 59 || second > 59) return null;

  if (zone && zone !== 'Z') {
    const [zoneHour, zoneMinute] = zone.slice(1).split(':').map(Number);
    if (zoneHour > 23 || zoneMinute > 59) return null;
  }

  return value;
};

/**
 * Monetary values stay as decimal strings. They are never converted to JavaScript
 * numbers, and null remains distinct from a recorded zero.
 */
export const recordedDecimalOrNull = (value) => (
  typeof value === 'string' && DECIMAL_PATTERN.test(value) ? value : null
);

const requireRecordedDecimalOrNull = (record, field, label) => {
  const value = requireField(record, field, label);
  if (value === null) return null;
  const decimal = recordedDecimalOrNull(value);
  if (decimal === null) contractError(`${label}.${field} must be a decimal string or null`);
  return decimal;
};

const requireNullableTimestamp = (record, field, label) => {
  const value = requireField(record, field, label);
  const timestamp = recordedTimestampOrNull(value);
  if (timestamp === null && value !== null) {
    contractError(`${label}.${field} must be a valid ISO calendar timestamp or null`);
  }
  return timestamp;
};

const requireUnavailableFinancials = (statistics) => {
  if (requireField(statistics, 'total_profit', 'statistics') !== null) {
    contractError('statistics.total_profit must remain null without verified provenance');
  }
  if (requireField(statistics, 'total_spent', 'statistics') !== null) {
    contractError('statistics.total_spent must remain null without verified provenance');
  }
  return {
    totalProfit: null,
    totalProfitDataStatus: requireStatusText(statistics, 'total_profit_data_status', 'statistics'),
    totalSpent: null,
    totalSpentDataStatus: requireStatusText(statistics, 'total_spent_data_status', 'statistics'),
  };
};

const requireCounts = (statistics) => {
  const rawCounts = requireRecord(requireField(statistics, 'status_counts', 'statistics'), 'statistics.status_counts');
  return Object.fromEntries(COUNT_NAMES.map((name) => {
    const value = requireField(rawCounts, name, 'statistics.status_counts');
    if (!Number.isSafeInteger(value) || value < 0) {
      contractError(`statistics.status_counts.${name} must be a non-negative integer`);
    }
    return [name, value];
  }));
};

const requireSuccessRate = (statistics) => {
  const value = requireField(statistics, 'success_rate', 'statistics');
  if (value === null) return null;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 100) {
    contractError('statistics.success_rate must be a percentage or null');
  }
  return value;
};

const expectedOwnerValue = (expectedOwner, camelName, snakeName) => {
  const owner = requireRecord(expectedOwner, 'expected owner');
  const names = [camelName, snakeName].filter((name) => hasOwn(owner, name));
  if (names.length === 0) contractError(`expected owner.${camelName} is missing`);
  const values = names.map((name) => owner[name]);
  if (values.some((value) => value !== values[0])) {
    contractError(`expected owner.${camelName} is inconsistent`);
  }
  const value = positiveInteger(values[0]);
  if (value === null) contractError(`expected owner.${camelName} must be a positive integer`);
  return value;
};

/** Normalize a caller's JWT-derived identity without trusting response identity. */
export const normalizeExpectedOwner = (expectedOwner) => ({
  userId: expectedOwnerValue(expectedOwner, 'userId', 'user_id'),
  tenantId: expectedOwnerValue(expectedOwner, 'tenantId', 'tenant_id'),
});

const requireRole = (role, label) => {
  if (typeof role !== 'string' || !role.trim() || role !== role.trim()) {
    contractError(`${label} must be a non-empty role`);
  }
  return role;
};

const normalizeRecentChallenge = (source, owner) => {
  const row = requireRecord(source, 'recent challenge');
  const id = requirePositiveInteger(row, 'id', 'recent challenge');
  const userId = requirePositiveInteger(row, 'user_id', 'recent challenge');
  if (userId !== owner.userId) contractError('recent challenge.user_id does not match owner context');
  if (requireField(row, 'currency', 'recent challenge') !== null) {
    contractError('recent challenge.currency must be explicit null while currency is unknown');
  }
  if (requireField(row, 'progress', 'recent challenge') !== null) {
    contractError('recent challenge.progress must remain null without an approved rule source');
  }

  return {
    id,
    userId,
    programName: requireNullableText(row, 'program_name', 'recent challenge'),
    status: requireNullableText(row, 'status', 'recent challenge'),
    statusDataStatus: requireStatusText(row, 'status_data_status', 'recent challenge'),
    phase: requireNullableNonNegativeInteger(row, 'phase', 'recent challenge'),
    totalPhases: requireNullableNonNegativeInteger(row, 'total_phases', 'recent challenge'),
    initialBalance: requireRecordedDecimalOrNull(row, 'initial_balance', 'recent challenge'),
    currentBalance: requireRecordedDecimalOrNull(row, 'current_balance', 'recent challenge'),
    balanceDataQuality: requireStatusText(row, 'balance_data_quality', 'recent challenge'),
    profit: requireRecordedDecimalOrNull(row, 'profit', 'recent challenge'),
    profitDataStatus: requireStatusText(row, 'profit_data_status', 'recent challenge'),
    progress: null,
    progressDataStatus: requireStatusText(row, 'progress_data_status', 'recent challenge'),
    createdAt: requireNullableTimestamp(row, 'created_at', 'recent challenge'),
    currency: null,
  };
};

/**
 * Turn the complete owner-scoped dashboard response into a view model. A missing
 * collection or ownership mismatch is a contract failure, never an empty state.
 */
export const normalizeUserDashboard = (payload, { expectedOwner, role } = {}) => {
  const source = requireRecord(payload, 'root');
  const expected = normalizeExpectedOwner(expectedOwner);
  const expectedRole = requireRole(role, 'expected role');
  const ownerContext = requireRecord(requireField(source, 'owner_context', 'root'), 'owner context');
  const owner = {
    userId: requirePositiveInteger(ownerContext, 'user_id', 'owner context'),
    tenantId: requirePositiveInteger(ownerContext, 'tenant_id', 'owner context'),
  };

  if (owner.userId !== expected.userId || owner.tenantId !== expected.tenantId) {
    contractError('owner context does not match the authenticated principal');
  }

  const rawUser = requireRecord(requireField(source, 'user', 'root'), 'user');
  const userId = requirePositiveInteger(rawUser, 'id', 'user');
  const tenantId = requirePositiveInteger(rawUser, 'tenant_id', 'user');
  const userRole = requireRole(requireField(rawUser, 'role', 'user'), 'user.role');
  if (userId !== owner.userId || tenantId !== owner.tenantId || userRole !== expectedRole) {
    contractError('user identity does not match the authenticated principal');
  }

  const statistics = requireRecord(requireField(source, 'statistics', 'root'), 'statistics');
  const rawRecent = requireList(requireField(source, 'recent_challenges', 'root'), 'recent challenges');
  if (rawRecent.length > 5) contractError('recent challenges exceeds its five-record bound');

  const seenChallengeIds = new Set();
  const recentChallenges = rawRecent.map((row) => {
    const challenge = normalizeRecentChallenge(row, owner);
    if (seenChallengeIds.has(challenge.id)) contractError('recent challenges contains a duplicate id');
    seenChallengeIds.add(challenge.id);
    return challenge;
  });

  const rawDataQuality = requireRecord(requireField(source, 'data_quality', 'root'), 'data quality');
  const financials = requireUnavailableFinancials(statistics);

  return {
    owner,
    user: {
      id: userId,
      tenantId,
      role: userRole,
      firstName: requireNullableText(rawUser, 'first_name', 'user'),
    },
    statistics: {
      statusCounts: requireCounts(statistics),
      statusCountsDataStatus: requireStatusText(statistics, 'status_counts_data_status', 'statistics'),
      successRate: requireSuccessRate(statistics),
      successRateDataStatus: requireStatusText(statistics, 'success_rate_data_status', 'statistics'),
      ...financials,
      dataQuality: requireStatusText(statistics, 'data_quality', 'statistics'),
    },
    recentChallenges,
    dataQuality: {
      challengeStatuses: requireStatusText(rawDataQuality, 'challenge_statuses', 'data quality'),
      tradingBalances: requireStatusText(rawDataQuality, 'trading_balances', 'data quality'),
      financialTotals: requireStatusText(rawDataQuality, 'financial_totals', 'data quality'),
      providerVerification: requireStatusText(rawDataQuality, 'provider_verification', 'data quality'),
    },
  };
};

export const isDashboardRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError'
);

/** Perform one caller-cancelable dashboard request; this service never polls. */
export const loadUserDashboard = async (apiClient = api, {
  signal,
  expectedOwner,
  role,
} = {}) => {
  const response = await apiClient.get(
    USER_DASHBOARD_ENDPOINT,
    signal ? { signal } : undefined,
  );
  return normalizeUserDashboard(response?.data, { expectedOwner, role });
};
