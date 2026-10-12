import api from './api.js';

export const ADMIN_PROGRAMS_ENDPOINT = '/admin/programs';
const DECIMAL_RE = /^(?:0|[1-9]\d*)\.\d{2}$/;
const MAX_DESCRIPTION = 65536;
const MAX_RULES_BYTES = 65536;
const MAX_PAGE = 10000;
const MAX_PER_PAGE = 50;
const MAX_OFFSET = 10000;
const ADMIN_PROGRAM_ROLES = new Set(['supermaster', 'master']);

export class AdminProgramsContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AdminProgramsContractError';
  }
}

const contractError = (message) => {
  throw new AdminProgramsContractError(message);
};

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const positiveInteger = (value, label) => {
  if (!Number.isSafeInteger(value) || value <= 0) contractError(`${label} must be a positive integer`);
  return value;
};

const boundedText = (value, label, maximum, { nullable = false, ascii = false, allowEmpty = false } = {}) => {
  if (value === null && nullable) return null;
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0) || value.length > maximum) {
    contractError(`${label} is invalid`);
  }
  if (ascii && !/^[\x20-\x7e]*$/.test(value)) contractError(`${label} is invalid`);
  return value;
};

const canonicalDecimalOrNull = (value, label, { nullable = true, positive = false, percentage = false } = {}) => {
  if (value === null && nullable) return null;
  if (typeof value !== 'string' || !DECIMAL_RE.test(value)) {
    contractError(`${label} must be an exact decimal string`);
  }
  const [whole] = value.split('.');
  const isZero = /^0+$/.test(whole) && value.endsWith('.00');
  if (positive && isZero) contractError(`${label} must be positive`);
  if (percentage) {
    const wholeNumber = Number(whole);
    if (wholeNumber > 100 || (wholeNumber === 100 && value !== '100.00')) {
      contractError(`${label} is outside its stored bounds`);
    }
  }
  return value;
};

const validateJsonObject = (value, label) => {
  if (!isRecord(value)) contractError(`${label} must be an object`);
  let encoded;
  try {
    encoded = JSON.stringify(value);
  } catch {
    contractError(`${label} must be JSON`);
  }
  if (typeof encoded !== 'string' || new TextEncoder().encode(encoded).byteLength > MAX_RULES_BYTES) {
    contractError(`${label} exceeds the 64 KiB storage limit`);
  }
  return value;
};

/** Auth/id/tenant/role are independently derived from the client auth store, never a response. */
export const normalizeAdminProgramsExpectedOwner = (value) => {
  if (!isRecord(value)) contractError('authenticated owner is required');
  const owner = {
    userId: positiveInteger(value.userId, 'authenticated user id'),
    tenantId: positiveInteger(value.tenantId, 'authenticated tenant id'),
    role: boundedText(value.role, 'authenticated role', 50, { ascii: true }),
  };
  if (!ADMIN_PROGRAM_ROLES.has(owner.role)) contractError('authenticated role cannot manage programs');
  return owner;
};

export const adminProgramsIdentityKey = ({ isAuthenticated, userId, tenantId, role } = {}) => (
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null])
);

export const adminProgramsPrincipalFromAuth = (user, isAuthenticated) => {
  if (isAuthenticated !== true) return null;
  try {
    const owner = normalizeAdminProgramsExpectedOwner({
      userId: user?.id,
      tenantId: user?.tenant_id,
      role: user?.role,
    });
    return {
      owner,
      key: adminProgramsIdentityKey({ isAuthenticated, ...owner }),
    };
  } catch {
    return null;
  }
};

const normalizedOwner = (value, expectedOwner) => {
  if (!isRecord(value)) contractError('owner_context is required');
  const expected = normalizeAdminProgramsExpectedOwner(expectedOwner);
  const owner = {
    userId: positiveInteger(value.user_id, 'owner_context.user_id'),
    tenantId: positiveInteger(value.tenant_id, 'owner_context.tenant_id'),
    role: boundedText(value.role, 'owner_context.role', 50, { ascii: true }),
  };
  if (owner.userId !== expected.userId || owner.tenantId !== expected.tenantId || owner.role !== expected.role) {
    contractError('owner context does not match the authenticated principal');
  }
  return owner;
};

const timestampOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > 64 || !value.endsWith('Z')) {
    contractError(`${label} is invalid`);
  }
  return value;
};

export const normalizeAdminProgram = (value) => {
  if (!isRecord(value)) contractError('program is invalid');
  const program = {
    id: positiveInteger(value.id, 'program.id'),
    tenantId: positiveInteger(value.tenant_id, 'program.tenant_id'),
    name: boundedText(value.name, 'program.name', 255),
    type: boundedText(value.type, 'program.type', 50, { ascii: true }),
    description: boundedText(value.description, 'program.description', MAX_DESCRIPTION, { nullable: true }),
    accountSize: canonicalDecimalOrNull(value.account_size, 'program.account_size', { nullable: false, positive: true }),
    profitTarget: canonicalDecimalOrNull(value.profit_target, 'program.profit_target', { percentage: true }),
    maxDailyLoss: canonicalDecimalOrNull(value.max_daily_loss, 'program.max_daily_loss', { percentage: true }),
    maxTotalLoss: canonicalDecimalOrNull(value.max_total_loss, 'program.max_total_loss', { percentage: true }),
    price: canonicalDecimalOrNull(value.price, 'program.price', { nullable: false, positive: true }),
    profitSplit: canonicalDecimalOrNull(value.profit_split, 'program.profit_split', { percentage: true }),
    profitSplitPercentage: canonicalDecimalOrNull(value.profit_split_percentage, 'program.profit_split_percentage', { percentage: true }),
    minimumPayoutAmount: canonicalDecimalOrNull(value.minimum_payout_amount, 'program.minimum_payout_amount'),
    payoutMode: boundedText(value.payout_mode, 'program.payout_mode', 50, { nullable: true, ascii: true }),
    rules: validateJsonObject(value.rules, 'program.rules'),
    isActive: typeof value.is_active === 'boolean' ? value.is_active : contractError('program.is_active is invalid'),
    createdAt: timestampOrNull(value.created_at, 'program.created_at'),
    updatedAt: timestampOrNull(value.updated_at, 'program.updated_at'),
  };
  return program;
};

const pagination = (value) => {
  if (!isRecord(value)) contractError('pagination is required');
  const page = positiveInteger(value.page, 'pagination.page');
  const perPage = positiveInteger(value.per_page, 'pagination.per_page');
  const total = Number.isSafeInteger(value.total) && value.total >= 0
    ? value.total : contractError('pagination.total is invalid');
  const pages = Number.isSafeInteger(value.pages) && value.pages >= 0
    ? value.pages : contractError('pagination.pages is invalid');
  if (perPage > 50 || page > 10000 || pages !== (total === 0 ? 0 : Math.ceil(total / perPage))) {
    contractError('pagination is inconsistent');
  }
  return { page, perPage, total, pages };
};

export const normalizeProgramsList = (payload, { expectedOwner } = {}) => {
  if (!isRecord(payload) || !Array.isArray(payload.programs)) contractError('programs response is invalid');
  const owner = normalizedOwner(payload.owner_context, expectedOwner);
  const programs = payload.programs.map(normalizeAdminProgram);
  if (programs.length > 50 || new Set(programs.map((program) => program.id)).size !== programs.length) {
    contractError('program list is invalid');
  }
  if (owner.role !== 'supermaster' && programs.some((program) => program.tenantId !== owner.tenantId)) {
    contractError('program row is outside the authenticated tenant');
  }
  return { owner, programs, pagination: pagination(payload.pagination) };
};

const normalizeMutation = (payload, { expectedOwner, expectedProgramId = null } = {}) => {
  if (!isRecord(payload)) contractError('program mutation response is invalid');
  const owner = normalizedOwner(payload.owner_context, expectedOwner);
  const program = normalizeAdminProgram(payload.program);
  if (expectedProgramId !== null && program.id !== expectedProgramId) {
    contractError('program mutation response did not match the requested program');
  }
  if (owner.role !== 'supermaster' && program.tenantId !== owner.tenantId) {
    contractError('persisted program is outside the authenticated tenant');
  }
  return { owner, program };
};

const nullableInput = (value) => (typeof value === 'string' && value.trim() === '' ? null : value);

const decimalInput = (value, label, options = {}) => canonicalDecimalOrNull(nullableInput(value), label, options);

const requestPagination = (page, perPage) => {
  const requestedPage = positiveInteger(page, 'page');
  const requestedPerPage = positiveInteger(perPage, 'per_page');
  if (
    requestedPage > MAX_PAGE
    || requestedPerPage > MAX_PER_PAGE
    || (requestedPage - 1) * requestedPerPage > MAX_OFFSET
  ) {
    contractError('program pagination is outside supported bounds');
  }
  return { page: requestedPage, perPage: requestedPerPage };
};

const abortError = () => {
  const error = new Error('Program catalog request was cancelled.');
  error.name = 'AbortError';
  return error;
};

const throwIfAborted = (signal) => {
  if (signal?.aborted) throw abortError();
};

/** Build the exact backend allow-list; no tenant or provider fields can leave the UI. */
export const serializeProgramMutation = (draft, { forCreate = false } = {}) => {
  if (!isRecord(draft)) contractError('program draft is invalid');
  let rules;
  try {
    rules = typeof draft.rules === 'string' ? JSON.parse(draft.rules) : draft.rules;
  } catch {
    contractError('rules must be valid JSON');
  }
  return {
    name: boundedText(draft.name, 'name', 255),
    type: boundedText(draft.type, 'type', 50, { ascii: true }),
    description: boundedText(nullableInput(draft.description), 'description', MAX_DESCRIPTION, { nullable: true }),
    account_size: decimalInput(draft.accountSize, 'account_size', { nullable: false, positive: true }),
    profit_target: decimalInput(draft.profitTarget, 'profit_target', { percentage: true }),
    max_daily_loss: decimalInput(draft.maxDailyLoss, 'max_daily_loss', { percentage: true }),
    max_total_loss: decimalInput(draft.maxTotalLoss, 'max_total_loss', { percentage: true }),
    price: decimalInput(draft.price, 'price', { nullable: false, positive: true }),
    profit_split: decimalInput(draft.profitSplit, 'profit_split', { percentage: true }),
    profit_split_percentage: decimalInput(draft.profitSplitPercentage, 'profit_split_percentage', { percentage: true }),
    minimum_payout_amount: decimalInput(draft.minimumPayoutAmount, 'minimum_payout_amount'),
    payout_mode: boundedText(nullableInput(draft.payoutMode), 'payout_mode', 50, { nullable: true, ascii: true }),
    rules: validateJsonObject(rules, 'rules'),
    is_active: typeof draft.isActive === 'boolean' ? draft.isActive : contractError('is_active must be boolean'),
  };
};

export const isAdminProgramsRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError'
);

/** One caller-cancelable, no-refresh read; this service intentionally never polls. */
export const loadAdminPrograms = async (apiClient = api, {
  signal,
  expectedOwner,
  page = 1,
  perPage = 20,
} = {}) => {
  const owner = normalizeAdminProgramsExpectedOwner(expectedOwner);
  const requested = requestPagination(page, perPage);
  throwIfAborted(signal);
  const response = await apiClient.get(ADMIN_PROGRAMS_ENDPOINT, {
    params: { page: String(requested.page), per_page: String(requested.perPage) },
    signal,
    _skipAuthRefresh: true,
  });
  throwIfAborted(signal);
  return normalizeProgramsList(response?.data, { expectedOwner: owner });
};

/** Persist only a validated allow-list and return the server's actual saved row. */
export const saveAdminProgram = async (apiClient = api, {
  programId = null,
  draft,
  signal,
  expectedOwner,
} = {}) => {
  const owner = normalizeAdminProgramsExpectedOwner(expectedOwner);
  const body = serializeProgramMutation(draft, { forCreate: programId === null });
  const identifier = programId === null ? null : positiveInteger(programId, 'program id');
  const config = { signal, _skipAuthRefresh: true };
  throwIfAborted(signal);
  const response = identifier === null
    ? await apiClient.post(ADMIN_PROGRAMS_ENDPOINT, body, config)
    : await apiClient.put(`${ADMIN_PROGRAMS_ENDPOINT}/${identifier}`, body, config);
  throwIfAborted(signal);
  return normalizeMutation(response?.data, { expectedOwner: owner, expectedProgramId: identifier });
};

/** Delete only after the canonical endpoint confirms the persisted deletion. */
export const deleteAdminProgram = async (apiClient = api, {
  programId,
  signal,
  expectedOwner,
} = {}) => {
  const owner = normalizeAdminProgramsExpectedOwner(expectedOwner);
  const identifier = positiveInteger(programId, 'program id');
  throwIfAborted(signal);
  const response = await apiClient.delete(`${ADMIN_PROGRAMS_ENDPOINT}/${identifier}`, {
    signal,
    _skipAuthRefresh: true,
  });
  throwIfAborted(signal);
  if (!isRecord(response?.data)) contractError('program delete response is invalid');
  const responseOwner = normalizedOwner(response.data.owner_context, owner);
  if (response.data.deleted_program_id !== identifier) contractError('program delete response did not match the request');
  return { owner: responseOwner, deletedProgramId: identifier };
};
