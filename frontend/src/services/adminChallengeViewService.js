export const ADMIN_CHALLENGE_VIEW_ENDPOINT = '/challenges/admin/all';
export const UNVERIFIED_LEGACY_DATA_STATUS = 'unverified_legacy';
export const MT5_ACCOUNT_BINDINGS = Object.freeze([
  'not_requested',
  'single_unverified_legacy',
  'ambiguous',
  'not_linked',
]);

const MAX_PAGE = 1000;
const MAX_PER_PAGE = 100;
const MAX_LEGACY_DECIMAL_LENGTH = 128;
const DECIMAL_STRING = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/;

export class AdminChallengeViewContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AdminChallengeViewContractError';
  }
}

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

const fail = (message) => {
  throw new AdminChallengeViewContractError(message);
};

const requireRecord = (value, label) => {
  if (!isRecord(value)) fail(`${label} had an unexpected response shape.`);
  return value;
};

const requireField = (source, key, label) => {
  if (!hasOwn(source, key)) fail(`${label} was missing ${key}.`);
  return source[key];
};

const requireSafeInteger = (value, label, { minimum = 0, maximum = Number.MAX_SAFE_INTEGER } = {}) => {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`${label} was invalid.`);
  }
  return value;
};

const requireNullableInteger = (value, label) => {
  if (value === null) return null;
  return requireSafeInteger(value, label, { minimum: 0 });
};

const requireText = (value, label, { nullable = false, maximum = 512 } = {}) => {
  if (value === null && nullable) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > maximum) {
    fail(`${label} was invalid.`);
  }
  return value;
};

const requireNullableLegacyDecimal = (value, label) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_LEGACY_DECIMAL_LENGTH
    || !DECIMAL_STRING.test(value)) {
    fail(`${label} was not an exact legacy decimal string.`);
  }
  return value;
};

const requireNullableTimestamp = (value, label) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length > 64 || !TIMESTAMP.test(value)) {
    fail(`${label} was not an ISO timestamp.`);
  }
  return value;
};

const requireLegacyMetadata = (source, label) => {
  if (requireField(source, 'data_status', label) !== UNVERIFIED_LEGACY_DATA_STATUS) {
    fail(`${label} was not marked as unverified legacy data.`);
  }
  if (requireField(source, 'provider_authenticated', label) !== false) {
    fail(`${label} incorrectly claimed provider authentication.`);
  }
};

const normalizeStatus = (status) => {
  if (status === undefined || status === null || status === '') return null;
  if (typeof status !== 'string' || status.length > 20 || status.trim().length === 0) {
    fail('The legacy status filter was invalid.');
  }
  return status;
};

export const normalizeAdminChallengeViewParams = ({
  page = 1,
  perPage = 20,
  status,
  includeMt5 = true,
} = {}) => {
  requireSafeInteger(page, 'The page', { minimum: 1, maximum: MAX_PAGE });
  requireSafeInteger(perPage, 'The page size', { minimum: 1, maximum: MAX_PER_PAGE });
  if (typeof includeMt5 !== 'boolean') fail('The MT5 inclusion mode was invalid.');

  return Object.freeze({
    page,
    perPage,
    status: normalizeStatus(status),
    includeMt5,
  });
};

const mapMt5Account = (value) => {
  const source = requireRecord(value, 'MT5 account');
  requireLegacyMetadata(source, 'MT5 account');

  return Object.freeze({
    // Only non-secret snapshot metadata is admitted. No password, token, or encrypted field is read.
    login: requireText(requireField(source, 'login', 'MT5 account'), 'MT5 login', { maximum: 50 }),
    server: requireText(requireField(source, 'server', 'MT5 account'), 'MT5 server', { nullable: true, maximum: 100 }),
    group: requireText(requireField(source, 'group', 'MT5 account'), 'MT5 group', { nullable: true, maximum: 100 }),
    status: requireText(requireField(source, 'status', 'MT5 account'), 'MT5 status', { nullable: true, maximum: 20 }),
    balance: requireNullableLegacyDecimal(requireField(source, 'balance', 'MT5 account'), 'MT5 balance'),
    equity: requireNullableLegacyDecimal(requireField(source, 'equity', 'MT5 account'), 'MT5 equity'),
    margin: requireNullableLegacyDecimal(requireField(source, 'margin', 'MT5 account'), 'MT5 margin'),
    freeMargin: requireNullableLegacyDecimal(requireField(source, 'free_margin', 'MT5 account'), 'MT5 free margin'),
    marginLevel: requireNullableLegacyDecimal(requireField(source, 'margin_level', 'MT5 account'), 'MT5 margin level'),
    updatedAt: requireNullableTimestamp(requireField(source, 'updated_at', 'MT5 account'), 'MT5 updated_at'),
    dataStatus: UNVERIFIED_LEGACY_DATA_STATUS,
    providerAuthenticated: false,
  });
};

const mapChallenge = (value, expectedStatus, includeMt5) => {
  const source = requireRecord(value, 'Challenge');
  requireLegacyMetadata(source, 'Challenge');
  const program = requireRecord(requireField(source, 'program', 'Challenge'), 'Challenge program');
  const user = requireRecord(requireField(source, 'user', 'Challenge'), 'Challenge user');
  const binding = requireField(source, 'mt5_account_binding', 'Challenge');

  if (!MT5_ACCOUNT_BINDINGS.includes(binding)) fail('Challenge had an unknown MT5 account binding.');
  if (!includeMt5 && binding !== 'not_requested') fail('Challenge ignored the requested MT5 exclusion.');

  const mt5Source = requireField(source, 'mt5_account', 'Challenge');
  if (binding === 'single_unverified_legacy' && mt5Source === null) {
    fail('Challenge claimed one MT5 account without snapshot metadata.');
  }
  if (binding !== 'single_unverified_legacy' && mt5Source !== null) {
    fail('Challenge supplied an MT5 account for a non-single legacy binding.');
  }

  const legacyStatus = requireText(requireField(source, 'legacy_status', 'Challenge'), 'Challenge legacy status', { maximum: 20 });
  if (expectedStatus !== null && legacyStatus !== expectedStatus) {
    fail('Challenge did not match the requested legacy status filter.');
  }

  const userId = requireSafeInteger(requireField(source, 'user_id', 'Challenge'), 'Challenge user_id', { minimum: 1 });
  const nestedUserId = requireSafeInteger(requireField(user, 'id', 'Challenge user'), 'User id', { minimum: 1 });
  if (userId !== nestedUserId) fail('Challenge user metadata did not match the challenge owner.');

  return Object.freeze({
    id: requireSafeInteger(requireField(source, 'id', 'Challenge'), 'Challenge id', { minimum: 1 }),
    userId,
    program: Object.freeze({
      id: requireSafeInteger(requireField(program, 'id', 'Challenge program'), 'Program id', { minimum: 1 }),
      name: requireText(requireField(program, 'name', 'Challenge program'), 'Program name', { maximum: 255 }),
    }),
    user: Object.freeze({
      id: nestedUserId,
      name: requireText(requireField(user, 'name', 'Challenge user'), 'User name', { maximum: 512 }),
      email: requireText(requireField(user, 'email', 'Challenge user'), 'User email', { maximum: 255 }),
    }),
    legacyStatus,
    legacyPaymentStatus: requireText(
      requireField(source, 'legacy_payment_status', 'Challenge'),
      'Challenge legacy payment status',
      { nullable: true, maximum: 20 },
    ),
    currentPhase: requireNullableInteger(requireField(source, 'current_phase', 'Challenge'), 'Challenge current phase'),
    totalPhases: requireNullableInteger(requireField(source, 'total_phases', 'Challenge'), 'Challenge total phases'),
    initialBalance: requireNullableLegacyDecimal(requireField(source, 'initial_balance', 'Challenge'), 'Challenge initial balance'),
    currentBalance: requireNullableLegacyDecimal(requireField(source, 'current_balance', 'Challenge'), 'Challenge current balance'),
    maxDrawdownObserved: requireNullableLegacyDecimal(requireField(source, 'max_drawdown_observed', 'Challenge'), 'Challenge maximum drawdown'),
    startDate: requireNullableTimestamp(requireField(source, 'start_date', 'Challenge'), 'Challenge start date'),
    endDate: requireNullableTimestamp(requireField(source, 'end_date', 'Challenge'), 'Challenge end date'),
    passedAt: requireNullableTimestamp(requireField(source, 'passed_at', 'Challenge'), 'Challenge passed_at'),
    createdAt: requireNullableTimestamp(requireField(source, 'created_at', 'Challenge'), 'Challenge created_at'),
    dataStatus: UNVERIFIED_LEGACY_DATA_STATUS,
    providerAuthenticated: false,
    mt5AccountBinding: binding,
    mt5Account: mt5Source === null ? null : mapMt5Account(mt5Source),
  });
};

export const mapAdminChallengeViewResponse = (payload, request = {}) => {
  const normalizedRequest = normalizeAdminChallengeViewParams(request);
  const source = requireRecord(payload, 'Admin challenge view');
  requireLegacyMetadata(source, 'Admin challenge view');

  const sourceChallenges = requireField(source, 'challenges', 'Admin challenge view');
  if (!Array.isArray(sourceChallenges)) fail('Admin challenge view challenges had an unexpected response shape.');

  const pagination = requireRecord(requireField(source, 'pagination', 'Admin challenge view'), 'Admin challenge pagination');
  const page = requireSafeInteger(requireField(pagination, 'page', 'Admin challenge pagination'), 'Response page', { minimum: 1, maximum: MAX_PAGE });
  const perPage = requireSafeInteger(requireField(pagination, 'per_page', 'Admin challenge pagination'), 'Response page size', { minimum: 1, maximum: MAX_PER_PAGE });
  const total = requireSafeInteger(requireField(pagination, 'total', 'Admin challenge pagination'), 'Response total', { minimum: 0 });
  const pages = requireSafeInteger(requireField(pagination, 'pages', 'Admin challenge pagination'), 'Response pages', { minimum: 0 });

  if (page !== normalizedRequest.page || perPage !== normalizedRequest.perPage) {
    fail('Admin challenge pagination did not match the requested page.');
  }
  if (pages !== Math.ceil(total / perPage)) fail('Admin challenge pagination was inconsistent.');
  if (sourceChallenges.length > perPage || (total === 0 && sourceChallenges.length !== 0)) {
    fail('Admin challenge results did not match the pagination metadata.');
  }

  const challenges = sourceChallenges.map((challenge) => mapChallenge(
    challenge,
    normalizedRequest.status,
    normalizedRequest.includeMt5,
  ));
  const uniqueIds = new Set(challenges.map((challenge) => challenge.id));
  if (uniqueIds.size !== challenges.length) fail('Admin challenge results contained duplicate challenge ids.');

  return Object.freeze({
    challenges: Object.freeze(challenges),
    pagination: Object.freeze({ page, perPage, total, pages }),
    dataStatus: UNVERIFIED_LEGACY_DATA_STATUS,
    providerAuthenticated: false,
  });
};

/**
 * The configured same-origin client is injected so all callers and tests use the
 * same read-only request path. This service exposes no mutation operation.
 */
export const createAdminChallengeViewService = (apiClient) => {
  if (!apiClient || typeof apiClient.get !== 'function') {
    throw new Error('A configured API client with GET support is required for challenge views.');
  }

  return Object.freeze({
    async list(options = {}) {
      const { signal, ...requestOptions } = options;
      const request = normalizeAdminChallengeViewParams(requestOptions);
      const params = {
        page: request.page,
        per_page: request.perPage,
        include_mt5: request.includeMt5 ? 'true' : 'false',
        ...(request.status === null ? {} : { status: request.status }),
      };
      const response = await apiClient.get(ADMIN_CHALLENGE_VIEW_ENDPOINT, { params, signal });
      return mapAdminChallengeViewResponse(response?.data, request);
    },
  });
};
