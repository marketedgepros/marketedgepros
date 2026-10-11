import api from './api.js';

export const USER_DASHBOARD_ENDPOINT = '/users/dashboard';

const COUNT_NAMES = ['total', 'pending', 'active', 'passed', 'failed', 'funded'];
const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const textOrNull = (value) => (
  typeof value === 'string' && value.trim().length > 0 ? value.trim() : null
);

const nonNegativeIntegerOrNull = (value) => (
  Number.isSafeInteger(value) && value >= 0 ? value : null
);

const percentageOrNull = (value) => (
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100
    ? value
    : null
);

/**
 * Balances are API strings on purpose: local legacy decimals must not be rounded
 * through JavaScript floating point before the UI displays them.
 */
export const recordedDecimalOrNull = (value) => {
  const recorded = textOrNull(value);
  return recorded && DECIMAL_PATTERN.test(recorded) ? recorded : null;
};

const emptyCounts = () => Object.fromEntries(COUNT_NAMES.map((name) => [name, null]));

const normalizeCounts = (value) => {
  const input = isRecord(value) ? value : {};
  return Object.fromEntries(
    COUNT_NAMES.map((name) => [name, nonNegativeIntegerOrNull(input[name])]),
  );
};

const normalizeRecentChallenge = (value) => {
  const row = isRecord(value) ? value : {};
  const initialBalance = recordedDecimalOrNull(row.initial_balance);
  const currentBalance = recordedDecimalOrNull(row.current_balance);
  const hasRecordedBalances = initialBalance !== null && currentBalance !== null;

  return {
    id: nonNegativeIntegerOrNull(row.id),
    programName: textOrNull(row.program_name),
    status: textOrNull(row.status),
    statusDataStatus: textOrNull(row.status_data_status),
    phase: nonNegativeIntegerOrNull(row.phase),
    totalPhases: nonNegativeIntegerOrNull(row.total_phases),
    initialBalance,
    currentBalance,
    balanceDataQuality: textOrNull(row.balance_data_quality),
    // A profit value without both recorded balances is not meaningful enough to show.
    profit: hasRecordedBalances ? recordedDecimalOrNull(row.profit) : null,
    profitDataStatus: textOrNull(row.profit_data_status),
    // The API deliberately has no approved target source. Ignore any unexpected value.
    progress: null,
    progressDataStatus: textOrNull(row.progress_data_status),
    createdAt: textOrNull(row.created_at),
  };
};

/**
 * Turn the dashboard response into a presentation-only view model. It accepts
 * only local recorded-status counts and intentionally exposes no numeric total
 * profit/spend value until a verified financial provenance contract exists.
 */
export const normalizeUserDashboard = (payload) => {
  if (!isRecord(payload)) {
    throw new TypeError('Dashboard response is unavailable');
  }

  const rawUser = isRecord(payload.user) ? payload.user : {};
  const rawStatistics = isRecord(payload.statistics) ? payload.statistics : {};
  const rawRecent = Array.isArray(payload.recent_challenges) ? payload.recent_challenges : [];
  const counts = normalizeCounts(rawStatistics.status_counts);

  return {
    user: {
      firstName: textOrNull(rawUser.first_name),
    },
    statistics: {
      statusCounts: counts || emptyCounts(),
      statusCountsDataStatus: textOrNull(rawStatistics.status_counts_data_status),
      successRate: percentageOrNull(rawStatistics.success_rate),
      successRateDataStatus: textOrNull(rawStatistics.success_rate_data_status),
      // These fields stay null even if a malformed or stale response sends a value.
      totalProfit: null,
      totalProfitDataStatus: textOrNull(rawStatistics.total_profit_data_status),
      totalSpent: null,
      totalSpentDataStatus: textOrNull(rawStatistics.total_spent_data_status),
      dataQuality: textOrNull(rawStatistics.data_quality),
    },
    recentChallenges: rawRecent
      .filter(isRecord)
      .map(normalizeRecentChallenge),
    dataQuality: isRecord(payload.data_quality) ? {
      challengeStatuses: textOrNull(payload.data_quality.challenge_statuses),
      tradingBalances: textOrNull(payload.data_quality.trading_balances),
      financialTotals: textOrNull(payload.data_quality.financial_totals),
      providerVerification: textOrNull(payload.data_quality.provider_verification),
    } : null,
  };
};

export const isDashboardRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError'
);

/** Perform one caller-cancelable dashboard request; this service never polls. */
export const loadUserDashboard = async (apiClient = api, { signal } = {}) => {
  const response = await apiClient.get(
    USER_DASHBOARD_ENDPOINT,
    signal ? { signal } : undefined,
  );
  return normalizeUserDashboard(response?.data);
};
