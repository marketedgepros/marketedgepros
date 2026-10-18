import api from './api.js';
import { ADMIN_ROLES } from '../constants/roles.js';

export const ADMIN_CLOSURE_CHALLENGE_ENDPOINTS = Object.freeze({
  list: '/challenges/admin/all',
  detail: (id) => `/challenges/admin/${id}`,
});
export const ADMIN_CLOSURE_CHALLENGE_PAGE_LIMIT = 1000;
export const ADMIN_CLOSURE_CHALLENGE_PER_PAGE_LIMIT = 100;
export const ADMIN_CLOSURE_CHALLENGE_OFFSET_LIMIT = 10000;
export const ADMIN_CLOSURE_CHALLENGE_PAGE_SIZE = 20;
export const ADMIN_CLOSURE_CHALLENGE_ID_LIMIT = 2147483647;
export const ADMIN_CLOSURE_MT5_BINDINGS = Object.freeze([
  'not_requested',
  'single_unverified_legacy',
  'ambiguous',
  'not_linked',
]);

const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/;
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export class AdminClosureChallengesContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AdminClosureChallengesContractError';
  }
}

const fail = (message) => { throw new AdminClosureChallengesContractError(message); };
const requireRecord = (value, label) => {
  if (!isRecord(value)) fail(`${label} has an invalid shape.`);
  return value;
};
const requireExactFields = (value, fields, label) => {
  const source = requireRecord(value, label);
  const actual = Object.keys(source);
  if (actual.length !== fields.length || fields.some((field) => !hasOwn(source, field))) {
    fail(`${label} contains fields outside the challenge contract.`);
  }
  return source;
};
const requirePositiveId = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > ADMIN_CLOSURE_CHALLENGE_ID_LIMIT) {
    fail(`${label} must be a positive bounded integer.`);
  }
  return value;
};
const requireNonNegativeIntegerOrNull = (value, label) => {
  if (value === null) return null;
  if (!Number.isSafeInteger(value) || value < 0) fail(`${label} must be a non-negative integer or null.`);
  return value;
};
const requireNonNegativeCount = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > Number.MAX_SAFE_INTEGER) {
    fail(`${label} must be a non-negative safe integer.`);
  }
  return value;
};
const requireTextOrNull = (value, label, maximum = 255) => {
  if (value === null) return null;
  if (typeof value !== 'string' || !value || value.length > maximum || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(value)) {
    fail(`${label} must be bounded text or null.`);
  }
  return value;
};
const requireText = (value, label, maximum = 255) => {
  const text = requireTextOrNull(value, label, maximum);
  if (text === null) fail(`${label} must be present.`);
  return text;
};
const requireDecimalOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== 'string' || !value || value.length > 128 || !DECIMAL.test(value)) {
    fail(`${label} must be an exact decimal string or null.`);
  }
  return value;
};
const requireTimestampOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length > 64 || !TIMESTAMP.test(value)) {
    fail(`${label} must be a complete ISO timestamp or null.`);
  }
  return value;
};

/** Active identity comes from the local authenticated store, never a response actor hint. */
export const normaliseAdminClosureChallengesExpectedOwner = (expectedOwner) => {
  const source = requireExactFields(expectedOwner, ['user_id', 'tenant_id'], 'Expected challenge owner');
  return {
    user_id: requirePositiveId(source.user_id, 'Expected challenge owner user ID'),
    tenant_id: requirePositiveId(source.tenant_id, 'Expected challenge owner tenant ID'),
  };
};
export const normalizeAdminClosureChallengesExpectedOwner = normaliseAdminClosureChallengesExpectedOwner;

export const adminClosureChallengesIdentityKey = ({ isAuthenticated, userId, tenantId, role }) => (
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null])
);

export const adminClosureChallengesPrincipalFromAuth = (user, isAuthenticated) => {
  try {
    if (isAuthenticated !== true || !ADMIN_ROLES.includes(user?.role)) return null;
    const owner = normaliseAdminClosureChallengesExpectedOwner({
      user_id: user?.id,
      tenant_id: user?.tenant_id,
    });
    return Object.freeze({
      owner: Object.freeze(owner),
      role: user.role,
      key: adminClosureChallengesIdentityKey({
        isAuthenticated,
        userId: owner.user_id,
        tenantId: owner.tenant_id,
        role: user.role,
      }),
    });
  } catch {
    return null;
  }
};

const requireAdminRole = (role) => {
  if (!ADMIN_ROLES.includes(role)) fail('Challenge administration requires an existing admin role.');
  return role;
};
const requireOwnerContext = (value, expectedOwner) => {
  const source = requireExactFields(value, ['user_id', 'tenant_id'], 'Challenge owner context');
  const owner = {
    user_id: requirePositiveId(source.user_id, 'Challenge owner-context user ID'),
    tenant_id: requirePositiveId(source.tenant_id, 'Challenge owner-context tenant ID'),
  };
  if (owner.user_id !== expectedOwner.user_id || owner.tenant_id !== expectedOwner.tenant_id) {
    fail('Challenge owner context does not match the active account.');
  }
  return owner;
};
const requireLegacyBoundary = (source, label) => {
  if (source.data_status !== 'unverified_legacy' || source.provider_authenticated !== false) {
    fail(`${label} verification boundary is invalid.`);
  }
  return { dataStatus: 'unverified_legacy', providerAuthenticated: false };
};

export const validateAdminClosureChallengeId = (value) => requirePositiveId(value, 'Challenge ID');
export const adminClosureChallengeDetailPath = (value) => (
  ADMIN_CLOSURE_CHALLENGE_ENDPOINTS.detail(validateAdminClosureChallengeId(value))
);

const requirePagination = (page, perPage) => {
  if (!Number.isSafeInteger(page) || page < 1 || page > ADMIN_CLOSURE_CHALLENGE_PAGE_LIMIT) {
    fail(`Challenge page must be between 1 and ${ADMIN_CLOSURE_CHALLENGE_PAGE_LIMIT}.`);
  }
  if (!Number.isSafeInteger(perPage) || perPage < 1 || perPage > ADMIN_CLOSURE_CHALLENGE_PER_PAGE_LIMIT) {
    fail(`Challenge page size must be between 1 and ${ADMIN_CLOSURE_CHALLENGE_PER_PAGE_LIMIT}.`);
  }
  if ((page - 1) * perPage > ADMIN_CLOSURE_CHALLENGE_OFFSET_LIMIT) {
    fail(`Challenge offset must not exceed ${ADMIN_CLOSURE_CHALLENGE_OFFSET_LIMIT}.`);
  }
  return { page, per_page: perPage };
};

export const buildAdminClosureChallengeListParams = ({
  page = 1,
  perPage = ADMIN_CLOSURE_CHALLENGE_PAGE_SIZE,
  status = null,
  includeMt5 = true,
} = {}) => {
  const pagination = requirePagination(page, perPage);
  if (status !== null && status !== undefined && (typeof status !== 'string' || !status || status.length > 20 || !status.trim())) {
    fail('Challenge status filter is invalid.');
  }
  if (typeof includeMt5 !== 'boolean') fail('Challenge MT5 inclusion mode is invalid.');
  return {
    ...pagination,
    ...(status === null || status === undefined ? {} : { status }),
    include_mt5: includeMt5 ? 'true' : 'false',
  };
};

export const buildAdminClosureChallengeDetailParams = ({ includeMt5 = true } = {}) => {
  if (typeof includeMt5 !== 'boolean') fail('Challenge MT5 inclusion mode is invalid.');
  return { include_mt5: includeMt5 ? 'true' : 'false' };
};

const normalizeMt5 = (value, binding) => {
  if (binding !== 'single_unverified_legacy') {
    if (value !== null) fail('A non-single MT5 binding must not include an account.');
    return null;
  }
  const source = requireExactFields(value, [
    'login', 'server', 'group', 'status', 'balance', 'equity', 'margin', 'free_margin',
    'margin_level', 'updated_at', 'data_status', 'provider_authenticated',
  ], 'Recorded MT5 snapshot');
  const boundary = requireLegacyBoundary(source, 'Recorded MT5 snapshot');
  return {
    login: requireTextOrNull(source.login, 'Recorded MT5 login', 50),
    server: requireTextOrNull(source.server, 'Recorded MT5 server', 100),
    group: requireTextOrNull(source.group, 'Recorded MT5 group', 100),
    status: requireTextOrNull(source.status, 'Recorded MT5 status', 20),
    balance: requireDecimalOrNull(source.balance, 'Recorded MT5 balance'),
    equity: requireDecimalOrNull(source.equity, 'Recorded MT5 equity'),
    margin: requireDecimalOrNull(source.margin, 'Recorded MT5 margin'),
    freeMargin: requireDecimalOrNull(source.free_margin, 'Recorded MT5 free margin'),
    marginLevel: requireDecimalOrNull(source.margin_level, 'Recorded MT5 margin level'),
    updatedAt: requireTimestampOrNull(source.updated_at, 'Recorded MT5 update time'),
    ...boundary,
  };
};

const normalizeChallenge = (value, { includeMt5 }) => {
  const source = requireExactFields(value, [
    'id', 'user_id', 'program', 'user', 'legacy_status', 'legacy_payment_status', 'current_phase',
    'total_phases', 'initial_balance', 'current_balance', 'max_drawdown_observed', 'start_date',
    'end_date', 'passed_at', 'created_at', 'data_status', 'provider_authenticated',
    'mt5_account_binding', 'mt5_account',
  ], 'Recorded challenge');
  const boundary = requireLegacyBoundary(source, 'Recorded challenge');
  const program = requireExactFields(source.program, ['id', 'name'], 'Recorded challenge program');
  const user = requireExactFields(source.user, ['id', 'name', 'email'], 'Recorded challenge user');
  const id = validateAdminClosureChallengeId(source.id);
  const userId = requirePositiveId(source.user_id, 'Recorded challenge user ID');
  if (requirePositiveId(user.id, 'Recorded user ID') !== userId) fail('Recorded challenge owner is incoherent.');
  const binding = source.mt5_account_binding;
  if (!ADMIN_CLOSURE_MT5_BINDINGS.includes(binding)) fail('Recorded challenge has an unknown MT5 binding.');
  if (!includeMt5 && binding !== 'not_requested') fail('Recorded challenge ignored requested MT5 exclusion.');
  return {
    id,
    userId,
    program: {
      id: requirePositiveId(program.id, 'Recorded program ID'),
      name: requireTextOrNull(program.name, 'Recorded program name'),
    },
    user: {
      id: userId,
      name: requireTextOrNull(user.name, 'Recorded user name', 512),
      email: requireTextOrNull(user.email, 'Recorded user email'),
    },
    legacyStatus: requireTextOrNull(source.legacy_status, 'Recorded challenge status', 20),
    legacyPaymentStatus: requireTextOrNull(source.legacy_payment_status, 'Recorded payment status', 20),
    currentPhase: requireNonNegativeIntegerOrNull(source.current_phase, 'Recorded current phase'),
    totalPhases: requireNonNegativeIntegerOrNull(source.total_phases, 'Recorded total phases'),
    initialBalance: requireDecimalOrNull(source.initial_balance, 'Recorded initial balance'),
    currentBalance: requireDecimalOrNull(source.current_balance, 'Recorded current balance'),
    maxDrawdownObserved: requireDecimalOrNull(source.max_drawdown_observed, 'Recorded maximum drawdown'),
    startDate: requireTimestampOrNull(source.start_date, 'Recorded start date'),
    endDate: requireTimestampOrNull(source.end_date, 'Recorded end date'),
    passedAt: requireTimestampOrNull(source.passed_at, 'Recorded passed date'),
    createdAt: requireTimestampOrNull(source.created_at, 'Recorded creation date'),
    mt5AccountBinding: binding,
    mt5Account: normalizeMt5(source.mt5_account, binding),
    ...boundary,
  };
};

const normalizePagination = (value, params, count) => {
  const source = requireExactFields(value, ['page', 'per_page', 'total', 'pages'], 'Challenge pagination');
  const total = requireNonNegativeCount(source.total, 'Challenge pagination total');
  const pages = requireNonNegativeCount(source.pages, 'Challenge pagination pages');
  if (source.page !== params.page || source.per_page !== params.per_page) {
    fail('Challenge pagination does not match the requested page.');
  }
  requirePagination(source.page, source.per_page);
  if (pages !== Math.ceil(total / source.per_page)) fail('Challenge pagination is mathematically inconsistent.');
  const expectedCount = Math.min(source.per_page, Math.max(0, total - (source.page - 1) * source.per_page));
  if (count !== expectedCount) fail('Challenge page does not match its server total.');
  return { page: source.page, perPage: source.per_page, total, pages };
};

export const normalizeAdminClosureChallengeListResponse = (payload, { expectedOwner, params } = {}) => {
  const owner = normaliseAdminClosureChallengesExpectedOwner(expectedOwner);
  const required = buildAdminClosureChallengeListParams({
    page: params?.page,
    perPage: params?.per_page,
    status: hasOwn(params || {}, 'status') ? params.status : null,
    includeMt5: params?.include_mt5 === 'true',
  });
  const source = requireExactFields(payload, [
    'owner_context', 'data_status', 'provider_authenticated', 'filters', 'challenges', 'pagination',
  ], 'Admin challenge-list response');
  const boundary = requireLegacyBoundary(source, 'Admin challenge-list response');
  const filter = requireExactFields(source.filters, ['status', 'include_mt5'], 'Challenge filters');
  const status = filter.status === null ? null : requireText(filter.status, 'Challenge response status filter', 20);
  if (status !== (required.status ?? null) || filter.include_mt5 !== (required.include_mt5 === 'true')) {
    fail('Challenge filters do not echo the request.');
  }
  if (!Array.isArray(source.challenges)) fail('Recorded challenges must be an array.');
  const challenges = source.challenges.map((row) => normalizeChallenge(row, { includeMt5: filter.include_mt5 }));
  const ids = new Set(challenges.map((challenge) => challenge.id));
  if (ids.size !== challenges.length) fail('Recorded challenges contain duplicate identifiers.');
  if (status !== null && challenges.some((challenge) => challenge.legacyStatus !== status)) {
    fail('Recorded challenges do not match the requested status filter.');
  }
  const pagination = normalizePagination(source.pagination, required, challenges.length);
  return {
    kind: 'list',
    ownerContext: requireOwnerContext(source.owner_context, owner),
    ...boundary,
    filters: { status, includeMt5: filter.include_mt5 },
    challenges,
    pagination,
  };
};

export const normalizeAdminClosureChallengeDetailResponse = (payload, { expectedOwner, challengeId, params } = {}) => {
  const owner = normaliseAdminClosureChallengesExpectedOwner(expectedOwner);
  const id = validateAdminClosureChallengeId(challengeId);
  const required = buildAdminClosureChallengeDetailParams({ includeMt5: params?.include_mt5 === 'true' });
  const source = requireExactFields(payload, [
    'owner_context', 'data_status', 'provider_authenticated', 'filters', 'challenge',
  ], 'Admin challenge-detail response');
  const boundary = requireLegacyBoundary(source, 'Admin challenge-detail response');
  const filter = requireExactFields(source.filters, ['include_mt5'], 'Challenge detail filters');
  if (filter.include_mt5 !== (required.include_mt5 === 'true')) fail('Challenge detail filter does not echo the request.');
  const challenge = normalizeChallenge(source.challenge, { includeMt5: filter.include_mt5 });
  if (challenge.id !== id) fail('Challenge detail does not match the requested record.');
  return {
    kind: 'detail',
    ownerContext: requireOwnerContext(source.owner_context, owner),
    ...boundary,
    filters: { includeMt5: filter.include_mt5 },
    challenge,
  };
};

const abortError = () => {
  const error = new Error('Admin challenge request was cancelled.');
  error.name = 'AbortError';
  return error;
};
const throwIfAborted = (signal) => { if (signal?.aborted) throw abortError(); };

/** Injected Axios-compatible client; GET only, no polling, retries, or write replay. */
export const createAdminClosureChallengesService = (client = api) => {
  if (!client || typeof client.get !== 'function') {
    throw new Error('A configured API client with GET support is required for challenge administration.');
  }
  const list = async ({ expectedOwner, role, signal, ...options } = {}) => {
    const owner = normaliseAdminClosureChallengesExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const params = buildAdminClosureChallengeListParams(options);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_CHALLENGE_ENDPOINTS.list, {
      params,
      signal,
      _skipAuthRefresh: true,
    });
    throwIfAborted(signal);
    return normalizeAdminClosureChallengeListResponse(response?.data, { expectedOwner: owner, params });
  };
  const detail = async (challengeId, { expectedOwner, role, signal, includeMt5 = true } = {}) => {
    const owner = normaliseAdminClosureChallengesExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = validateAdminClosureChallengeId(challengeId);
    const params = buildAdminClosureChallengeDetailParams({ includeMt5 });
    throwIfAborted(signal);
    const response = await client.get(adminClosureChallengeDetailPath(id), {
      params,
      signal,
      _skipAuthRefresh: true,
    });
    throwIfAborted(signal);
    return normalizeAdminClosureChallengeDetailResponse(response?.data, {
      expectedOwner: owner,
      challengeId: id,
      params,
    });
  };
  return Object.freeze({ list, detail });
};

export const isAdminClosureChallengeRequestCanceled = (error) => (
  error?.name === 'AbortError' || error?.code === 'ERR_CANCELED'
);
export const adminClosureChallengesError = () => (
  'The scoped legacy challenge record could not be loaded or validated. No provider result, payment entitlement, or account action was assumed.'
);
