import api from './api.js';

export const CHALLENGE_LIST_ENDPOINT = '/challenges/my-challenges';
export const MAX_CHALLENGE_PAGE = 1000;
export const MAX_CHALLENGE_PER_PAGE = 100;
export const DEFAULT_CHALLENGE_PER_PAGE = 20;
export const MAX_CHALLENGE_ID = 2147483647;

const DECIMAL_STRING = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;

const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isNullableString = (value) => value === null || typeof value === 'string';
const isNullableDecimalString = (value) => value === null
  || (typeof value === 'string' && value.length > 0 && value.length <= 128 && DECIMAL_STRING.test(value));
const isNullableNonNegativeInteger = (value) => value === null
  || (Number.isSafeInteger(value) && value >= 0);
const isNullableOwnerTenant = (value) => value === null
  || (Number.isSafeInteger(value) && value >= 1 && value <= MAX_CHALLENGE_ID);
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

const requireObject = (value, message) => {
  if (!isPlainObject(value)) throw new Error(message);
  return value;
};

const requireBoundedInteger = (value, label, maximum) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new Error(`${label} must be an integer between 1 and ${maximum}.`);
  }
  return value;
};

const requireNullableString = (value, label) => {
  if (!isNullableString(value)) throw new Error(`${label} must be a string or null.`);
  return value;
};

const requireNullableDecimal = (value, label) => {
  if (!isNullableDecimalString(value)) {
    throw new Error(`${label} must be an exact decimal string or null.`);
  }
  return value;
};

const requireNullableNonNegativeInteger = (value, label) => {
  if (!isNullableNonNegativeInteger(value)) {
    throw new Error(`${label} must be a non-negative integer or null.`);
  }
  return value;
};

const normaliseOwner = (value, label) => {
  const owner = requireObject(value, `${label} is missing.`);
  if (!hasOwn(owner, 'user_id') || !hasOwn(owner, 'tenant_id')) {
    throw new Error(`${label} is incomplete.`);
  }
  if (!isNullableOwnerTenant(owner.tenant_id)) {
    throw new Error(`${label} tenant ID must be a positive integer or null.`);
  }

  return {
    user_id: requireBoundedInteger(owner.user_id, `${label} user ID`, MAX_CHALLENGE_ID),
    tenant_id: owner.tenant_id,
  };
};

/**
 * Challenge views receive this local hint from the authenticated store. It is
 * deliberately typed: a missing tenant is explicitly null, never inferred
 * from a fallback brand or another profile field.
 */
export const normaliseExpectedOwner = (expectedOwner) => (
  normaliseOwner(expectedOwner, 'Expected owner')
);

const assertResponseOwner = (payload, expectedOwner, label) => {
  if (expectedOwner === undefined) return null;

  const ownerContext = normaliseOwner(payload.owner_context, `${label} owner context`);
  if (ownerContext.user_id !== expectedOwner.user_id
    || ownerContext.tenant_id !== expectedOwner.tenant_id) {
    throw new Error(`${label} owner context does not match the active account.`);
  }
  return ownerContext;
};

const throwIfAborted = (signal) => {
  if (!signal?.aborted) return;
  const error = new Error('Challenge request was cancelled.');
  error.name = 'AbortError';
  throw error;
};

/**
 * Legacy financial flags are never authorization evidence in this UI. A future
 * unfamiliar value therefore remains explicitly unverified instead of becoming
 * a verified payment, rule, balance, or provider assertion.
 */
const normaliseLegacyContext = (value, label) => {
  const context = requireObject(value, `${label} context is missing.`);
  if (typeof context.data_status !== 'string' || typeof context.provider_authenticated !== 'boolean') {
    throw new Error(`${label} verification context is invalid.`);
  }

  return {
    data_status: 'unverified_legacy',
    provider_authenticated: false,
  };
};

const normaliseProgram = (value) => {
  const program = requireObject(value, 'Challenge program is missing.');
  if (typeof program.name !== 'string' || program.name.length === 0) {
    throw new Error('Challenge program name is invalid.');
  }
  return {
    id: requireBoundedInteger(program.id, 'Program ID', MAX_CHALLENGE_ID),
    name: program.name,
  };
};

export const validateChallengeId = (challengeId) => (
  requireBoundedInteger(challengeId, 'Challenge ID', MAX_CHALLENGE_ID)
);

export const getChallengeProgressPath = (challengeId) => (
  `/challenges/${validateChallengeId(challengeId)}/progress`
);

/**
 * Preserve server decimal strings verbatim. In particular, zero is not treated
 * as absent and no client float calculation is permitted for legacy snapshots.
 */
export const recordedDecimalOrNull = (value) => (
  isNullableDecimalString(value) ? value : null
);

export const normaliseChallenge = (value) => {
  const challenge = requireObject(value, 'Challenge record is invalid.');
  const context = normaliseLegacyContext(challenge, 'Challenge');

  return {
    id: validateChallengeId(challenge.id),
    user_id: requireBoundedInteger(challenge.user_id, 'Challenge user ID', MAX_CHALLENGE_ID),
    program: normaliseProgram(challenge.program),
    legacy_status: requireNullableString(challenge.legacy_status, 'Recorded status'),
    legacy_payment_status: requireNullableString(challenge.legacy_payment_status, 'Recorded payment status'),
    current_phase: requireNullableNonNegativeInteger(challenge.current_phase, 'Recorded current phase'),
    total_phases: requireNullableNonNegativeInteger(challenge.total_phases, 'Recorded total phases'),
    initial_balance: requireNullableDecimal(challenge.initial_balance, 'Initial balance'),
    current_balance: requireNullableDecimal(challenge.current_balance, 'Current balance'),
    max_drawdown_observed: requireNullableDecimal(challenge.max_drawdown_observed, 'Observed drawdown'),
    start_date: requireNullableString(challenge.start_date, 'Start date'),
    end_date: requireNullableString(challenge.end_date, 'End date'),
    passed_at: requireNullableString(challenge.passed_at, 'Passed date'),
    created_at: requireNullableString(challenge.created_at, 'Created date'),
    ...context,
  };
};

const normaliseProgress = (value) => {
  const progress = requireObject(value, 'Challenge progress is missing.');
  const context = normaliseLegacyContext(progress, 'Progress');

  return {
    initial_balance: requireNullableDecimal(progress.initial_balance, 'Progress initial balance'),
    current_balance: requireNullableDecimal(progress.current_balance, 'Progress current balance'),
    profit_loss: requireNullableDecimal(progress.profit_loss, 'Recorded profit/loss'),
    profit_target_percent: requireNullableDecimal(progress.profit_target_percent, 'Catalog profit target percent'),
    profit_target_amount: requireNullableDecimal(progress.profit_target_amount, 'Catalog profit target amount'),
    profit_progress_percent: requireNullableDecimal(progress.profit_progress_percent, 'Legacy estimated progress percent'),
    trading_days: requireNullableNonNegativeInteger(progress.trading_days, 'Trading days'),
    min_trading_days: requireNullableNonNegativeInteger(progress.min_trading_days, 'Minimum trading days'),
    ...context,
  };
};

const normaliseMt5Account = (value) => {
  if (value === null) return null;
  const account = requireObject(value, 'Stored MT5 metadata is invalid.');
  const context = normaliseLegacyContext(account, 'MT5 metadata');

  return {
    login: requireNullableString(account.login, 'MT5 login'),
    server: requireNullableString(account.server, 'MT5 server'),
    group: requireNullableString(account.group, 'MT5 group'),
    status: requireNullableString(account.status, 'MT5 status'),
    balance: requireNullableDecimal(account.balance, 'Stored MT5 balance'),
    equity: requireNullableDecimal(account.equity, 'Stored MT5 equity'),
    margin: requireNullableDecimal(account.margin, 'Stored MT5 margin'),
    free_margin: requireNullableDecimal(account.free_margin, 'Stored MT5 free margin'),
    margin_level: requireNullableDecimal(account.margin_level, 'Stored MT5 margin level'),
    updated_at: requireNullableString(account.updated_at, 'MT5 metadata update time'),
    ...context,
  };
};

const normalisePagination = (value) => {
  const pagination = requireObject(value, 'Challenge pagination is missing.');
  const page = requireBoundedInteger(pagination.page, 'Page', MAX_CHALLENGE_PAGE);
  const perPage = requireBoundedInteger(pagination.per_page, 'Per-page count', MAX_CHALLENGE_PER_PAGE);
  if (!Number.isSafeInteger(pagination.total) || pagination.total < 0
    || !Number.isSafeInteger(pagination.pages) || pagination.pages < 0) {
    throw new Error('Challenge pagination totals are invalid.');
  }
  if (pagination.pages !== Math.ceil(pagination.total / perPage)) {
    throw new Error('Challenge pagination context is inconsistent.');
  }

  return {
    page,
    per_page: perPage,
    total: pagination.total,
    pages: pagination.pages,
  };
};

export const normaliseChallengeListResponse = (data, { expectedOwner } = {}) => {
  const payload = requireObject(data, 'Challenge list response is unavailable.');
  const owner = expectedOwner === undefined ? undefined : normaliseExpectedOwner(expectedOwner);
  const context = normaliseLegacyContext(payload, 'Challenge list');
  if (!Array.isArray(payload.challenges)) {
    throw new Error('Challenge list response is incomplete.');
  }

  const pagination = normalisePagination(payload.pagination);
  if (payload.challenges.length > pagination.per_page
    || (pagination.total === 0 && payload.challenges.length !== 0)) {
    throw new Error('Challenge list exceeds its pagination bounds.');
  }
  const challenges = payload.challenges.map(normaliseChallenge);
  const ids = new Set();
  for (const challenge of challenges) {
    if (ids.has(challenge.id)) throw new Error('Challenge list contains duplicate records.');
    ids.add(challenge.id);
  }
  const ownerContext = assertResponseOwner(payload, owner, 'Challenge list');
  if (owner !== undefined && challenges.some((challenge) => challenge.user_id !== owner.user_id)) {
    throw new Error('Challenge list contains a record from a different account.');
  }

  return {
    challenges,
    pagination,
    ...context,
    ...(ownerContext ? { owner_context: ownerContext } : {}),
  };
};

export const normaliseChallengeProgressResponse = (data, expectedChallengeId, { expectedOwner } = {}) => {
  const payload = requireObject(data, 'Challenge progress response is unavailable.');
  const owner = expectedOwner === undefined ? undefined : normaliseExpectedOwner(expectedOwner);
  const context = normaliseLegacyContext(payload, 'Challenge progress');
  const challenge = normaliseChallenge(payload.challenge);
  if (expectedChallengeId !== undefined && challenge.id !== validateChallengeId(expectedChallengeId)) {
    throw new Error('Challenge progress response does not match the requested challenge.');
  }
  const ownerContext = assertResponseOwner(payload, owner, 'Challenge progress');
  if (owner !== undefined && challenge.user_id !== owner.user_id) {
    throw new Error('Challenge progress contains a record from a different account.');
  }

  return {
    challenge,
    progress: normaliseProgress(payload.progress),
    mt5_account: normaliseMt5Account(payload.mt5_account),
    ...context,
    ...(ownerContext ? { owner_context: ownerContext } : {}),
  };
};

export const buildChallengeListParams = ({ page = 1, perPage = DEFAULT_CHALLENGE_PER_PAGE, status } = {}) => {
  const params = {
    page: requireBoundedInteger(page, 'Page', MAX_CHALLENGE_PAGE),
    per_page: requireBoundedInteger(perPage, 'Per-page count', MAX_CHALLENGE_PER_PAGE),
  };

  if (status !== undefined && status !== null) {
    if (typeof status !== 'string' || status.length === 0 || status.length > 20) {
      throw new Error('Status must be a non-empty string of 20 characters or fewer.');
    }
    params.status = status;
  }
  return params;
};

/**
 * A request token captures route/list context. Components discard a completion
 * unless it is still current, so an abort-resistant stale response cannot
 * overwrite a newer page, filter, or route ID.
 */
export class ChallengeViewRequestGate {
  constructor() {
    this.sequence = 0;
  }

  begin(context) {
    if (!isPlainObject(context)) throw new Error('Challenge request context is invalid.');
    const token = Object.freeze({ sequence: this.sequence + 1, context: Object.freeze({ ...context }) });
    this.sequence = token.sequence;
    return token;
  }

  isCurrent(token) {
    return Boolean(token) && token.sequence === this.sequence;
  }

  invalidate() {
    this.sequence += 1;
  }
}

/**
 * Axios is injected for testability. The default app client already has
 * baseURL /api/v1, so these intentionally use API-relative paths without a
 * duplicated /api/v1 prefix.
 */
export const createChallengeViewService = (apiClient = api) => {
  if (!apiClient || typeof apiClient.get !== 'function') {
    throw new Error('A configured API client is required for challenge views.');
  }

  return {
    async getMyChallenges(options = {}) {
      const { signal, expectedOwner } = options;
      const params = buildChallengeListParams(options);
      const owner = expectedOwner === undefined ? undefined : normaliseExpectedOwner(expectedOwner);
      throwIfAborted(signal);
      const response = await apiClient.get(CHALLENGE_LIST_ENDPOINT, {
        params,
        signal,
      });
      throwIfAborted(signal);
      const result = normaliseChallengeListResponse(response?.data, { expectedOwner: owner });
      if (result.pagination.page !== params.page || result.pagination.per_page !== params.per_page
        || (params.status && result.challenges.some((row) => row.legacy_status !== params.status))) {
        throw new Error('Challenge list response does not match the requested context.');
      }
      return result;
    },

    async getChallengeProgress(challengeId, { signal, expectedOwner } = {}) {
      const id = validateChallengeId(challengeId);
      const owner = expectedOwner === undefined ? undefined : normaliseExpectedOwner(expectedOwner);
      throwIfAborted(signal);
      const response = await apiClient.get(getChallengeProgressPath(id), { signal });
      throwIfAborted(signal);
      return normaliseChallengeProgressResponse(response?.data, id, { expectedOwner: owner });
    },
  };
};

const challengeViewService = createChallengeViewService(api);
export default challengeViewService;
