import api from "./api.js";
import { ADMIN_ROLES, ALL_ROLES } from "../constants/roles.js";

export const ADMIN_CLOSURE_USERS_ENDPOINTS = Object.freeze({
  users: "/admin/users",
  hierarchy: "/admin/users/hierarchy",
  user: (id) => `/admin/users/${id}`,
  fullDetails: (id) => `/admin/users/${id}/full-details`,
  resetPassword: (id) => `/admin/users/${id}/reset-password`,
});
export const ADMIN_CLOSURE_USERS_PAGE_SIZE = 20;
export const ADMIN_CLOSURE_USERS_PAGE_LIMIT = 10_000;
export const ADMIN_CLOSURE_USERS_PER_PAGE_LIMIT = 50;
export const ADMIN_CLOSURE_USERS_OFFSET_LIMIT = 10_000;
export const ADMIN_CLOSURE_USERS_ROLES = Object.freeze(["supermaster", "master", "affiliate", "trader", "guest"]);
export const ADMIN_CLOSURE_USERS_CREATABLE_ROLES = Object.freeze(["supermaster", "master", "affiliate", "trader"]);
export const ADMIN_CLOSURE_USERS_STATUSES = Object.freeze(["active", "inactive"]);
export const ADMIN_CLOSURE_USERS_KYC = Object.freeze(["not_submitted", "pending", "approved", "rejected", "incomplete", "verified", "unverified"]);
export const ADMIN_CLOSURE_USERS_CHALLENGE_STATUSES = Object.freeze(["pending", "active", "completed", "passed", "failed", "funded", "cancelled"]);
export const ADMIN_CLOSURE_USERS_PAYMENT_STATUSES = Object.freeze(["pending", "completed", "failed", "refunded"]);
export const ADMIN_CLOSURE_USERS_PAYMENT_TYPES = Object.freeze(["challenge_purchase", "withdrawal", "refund"]);

const ID_LIMIT = 2_147_483_647;
const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const CURRENCY = /^[A-Z]{3}$/;
const ISO_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?Z$/;
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class AdminClosureUsersContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "AdminClosureUsersContractError";
  }
}

const fail = (message) => { throw new AdminClosureUsersContractError(message); };
const requireRecord = (value, label) => {
  if (!isRecord(value)) fail(`${label} has an invalid shape.`);
  return value;
};
const requireArray = (value, label) => {
  if (!Array.isArray(value)) fail(`${label} has an invalid shape.`);
  return value;
};
const requireExactFields = (value, fields, label) => {
  const record = requireRecord(value, label);
  const keys = Object.keys(record);
  if (keys.length !== fields.length || fields.some((field) => !hasOwn(record, field))) {
    fail(`${label} contains unsupported fields.`);
  }
  return record;
};
const requirePositiveId = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > ID_LIMIT) fail(`${label} must be a positive bounded integer.`);
  return value;
};
const requireCount = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > ID_LIMIT) fail(`${label} must be a bounded non-negative integer.`);
  return value;
};
const requireStringOrNull = (value, label, maximum) => {
  if (value === null) return null;
  if (typeof value !== "string" || !value || value.length > maximum || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(value)) {
    fail(`${label} must be bounded text or null.`);
  }
  return value;
};
const requireEnumOrNull = (value, allowed, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || !allowed.includes(value)) fail(`${label} is unsupported.`);
  return value;
};
const requireBooleanOrNull = (value, label) => {
  if (value === null || typeof value === "boolean") return value;
  fail(`${label} must be boolean or null.`);
};
const isCalendarDate = (year, month, day) => {
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
};
const requireTimestampOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string") fail(`${label} must be an ISO UTC timestamp or null.`);
  const match = ISO_TIMESTAMP.exec(value);
  if (!match) fail(`${label} must be an ISO UTC timestamp or null.`);
  const [, year, month, day, hour, minute, second] = match.map(Number);
  if (!isCalendarDate(year, month, day) || hour > 23 || minute > 59 || second > 59 || !Number.isFinite(Date.parse(value))) {
    fail(`${label} must be a real ISO UTC timestamp or null.`);
  }
  return value;
};
const requireDecimalOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || !value || value.length > 128 || !DECIMAL.test(value)) {
    fail(`${label} must be an exact decimal string or null.`);
  }
  return value;
};
const requireCurrencyOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || !CURRENCY.test(value)) fail(`${label} must be an uppercase ISO currency or null.`);
  return value;
};

/** Auth/id/tenant/role are independently derived from the client auth store, never any response. */
export const normaliseAdminClosureUsersExpectedOwner = (expectedOwner) => {
  const source = requireExactFields(expectedOwner, ["user_id", "tenant_id", "role"], "Expected users owner");
  const owner = {
    user_id: requirePositiveId(source.user_id, "Expected users owner user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Expected users owner tenant ID"),
    role: requireEnumOrNull(source.role, ALL_ROLES, "Expected users owner role"),
  };
  if (owner.role === null || !ADMIN_ROLES.includes(owner.role)) fail("Users management requires an existing admin role.");
  return owner;
};
export const normalizeAdminClosureUsersExpectedOwner = normaliseAdminClosureUsersExpectedOwner;

export const adminClosureUsersIdentityKey = ({ isAuthenticated, userId, tenantId, role }) => (
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null])
);
export const adminClosureUsersPrincipalFromAuth = (user, isAuthenticated) => {
  try {
    if (isAuthenticated !== true) return null;
    const owner = normaliseAdminClosureUsersExpectedOwner({
      user_id: user?.id,
      tenant_id: user?.tenant_id,
      role: user?.role,
    });
    return {
      owner,
      key: adminClosureUsersIdentityKey({
        isAuthenticated,
        userId: owner.user_id,
        tenantId: owner.tenant_id,
        role: owner.role,
      }),
    };
  } catch {
    return null;
  }
};

export const buildAdminClosureUsersParams = ({ page = 1, perPage = ADMIN_CLOSURE_USERS_PAGE_SIZE, role = null, status = null, search = null } = {}) => {
  if (!Number.isSafeInteger(page) || page < 1 || page > ADMIN_CLOSURE_USERS_PAGE_LIMIT) fail("Users page is outside the supported range.");
  if (!Number.isSafeInteger(perPage) || perPage < 1 || perPage > ADMIN_CLOSURE_USERS_PER_PAGE_LIMIT) fail("Users page size is outside the supported range.");
  if ((page - 1) * perPage > ADMIN_CLOSURE_USERS_OFFSET_LIMIT) fail("Users offset is outside the supported range.");
  const normalRole = requireEnumOrNull(role, ADMIN_CLOSURE_USERS_ROLES, "Users role filter");
  const normalStatus = requireEnumOrNull(status, ADMIN_CLOSURE_USERS_STATUSES, "Users status filter");
  if (search !== null && (typeof search !== "string" || !search || search.length > 100 || /[\u0000-\u001F]/.test(search))) {
    fail("Users search filter is invalid.");
  }
  return {
    page,
    per_page: perPage,
    ...(normalRole === null ? {} : { role: normalRole }),
    ...(normalStatus === null ? {} : { status: normalStatus }),
    ...(search === null ? {} : { search }),
  };
};

const normalizeOwnerContext = (value, expectedOwner) => {
  const source = requireExactFields(value, ["user_id", "tenant_id"], "Users owner context");
  const owner = {
    user_id: requirePositiveId(source.user_id, "Users owner-context user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Users owner-context tenant ID"),
  };
  if (owner.user_id !== expectedOwner.user_id || owner.tenant_id !== expectedOwner.tenant_id) {
    fail("Users owner context does not match the active account.");
  }
  return owner;
};

const normalizeListUser = (value) => {
  const source = requireExactFields(value, ["id", "first_name", "last_name", "email", "role", "is_active", "kyc_status", "created_at", "last_login_at"], "User list row");
  return {
    id: requirePositiveId(source.id, "User list ID"),
    first_name: requireStringOrNull(source.first_name, "User first name", 100),
    last_name: requireStringOrNull(source.last_name, "User last name", 100),
    email: requireStringOrNull(source.email, "User email", 255),
    role: requireEnumOrNull(source.role, ADMIN_CLOSURE_USERS_ROLES, "User role"),
    is_active: requireBooleanOrNull(source.is_active, "User active status"),
    kyc_status: requireEnumOrNull(source.kyc_status, ADMIN_CLOSURE_USERS_KYC, "User KYC status"),
    created_at: requireTimestampOrNull(source.created_at, "User creation timestamp"),
    last_login_at: requireTimestampOrNull(source.last_login_at, "User login timestamp"),
  };
};

const normalizeDetailUser = (value) => {
  const source = requireExactFields(value, ["id", "first_name", "last_name", "email", "phone", "country_code", "role", "is_active", "kyc_status", "is_verified", "two_factor_enabled", "created_at", "updated_at", "last_login_at"], "User detail");
  return {
    ...normalizeListUser({
      id: source.id, first_name: source.first_name, last_name: source.last_name, email: source.email,
      role: source.role, is_active: source.is_active, kyc_status: source.kyc_status,
      created_at: source.created_at, last_login_at: source.last_login_at,
    }),
    phone: requireStringOrNull(source.phone, "User phone", 20),
    country_code: requireStringOrNull(source.country_code, "User country code", 20),
    is_verified: requireBooleanOrNull(source.is_verified, "User verification status"),
    two_factor_enabled: requireBooleanOrNull(source.two_factor_enabled, "User two-factor status"),
    updated_at: requireTimestampOrNull(source.updated_at, "User update timestamp"),
  };
};

const normalizePagination = (value, params, received) => {
  const source = requireExactFields(value, ["page", "per_page", "total", "pages"], "Users pagination");
  const page = requireCount(source.page, "Users pagination page");
  const perPage = requireCount(source.per_page, "Users pagination page size");
  const total = requireCount(source.total, "Users pagination total");
  const pages = requireCount(source.pages, "Users pagination pages");
  if (page !== params.page || perPage !== params.per_page || page < 1 || perPage < 1) fail("Users pagination does not match the request.");
  if (pages !== Math.ceil(total / perPage)) fail("Users pagination is inconsistent.");
  const expectedRows = Math.min(perPage, Math.max(0, total - (page - 1) * perPage));
  if (received !== expectedRows) fail("Users page does not match the server total.");
  return { page, per_page: perPage, total, pages };
};

export const normalizeAdminClosureUsersList = (payload, { expectedOwner, params } = {}) => {
  const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
  const requested = buildAdminClosureUsersParams({
    page: params?.page,
    perPage: params?.per_page,
    role: hasOwn(params || {}, "role") ? params.role : null,
    status: hasOwn(params || {}, "status") ? params.status : null,
    search: hasOwn(params || {}, "search") ? params.search : null,
  });
  const source = requireExactFields(payload, ["owner_context", "users", "pagination", "filters"], "Users list response");
  const users = requireArray(source.users, "Users list").map(normalizeListUser);
  if (new Set(users.map((user) => user.id)).size !== users.length) fail("Users list contains duplicate IDs.");
  const filters = requireExactFields(source.filters, ["role", "status", "search"], "Users filters");
  const echoed = {
    role: requireEnumOrNull(filters.role, ADMIN_CLOSURE_USERS_ROLES, "Users echoed role"),
    status: requireEnumOrNull(filters.status, ADMIN_CLOSURE_USERS_STATUSES, "Users echoed status"),
    search: filters.search === null ? null : requireStringOrNull(filters.search, "Users echoed search", 100),
  };
  const expected = { role: requested.role ?? null, status: requested.status ?? null, search: requested.search ?? null };
  if (JSON.stringify(echoed) !== JSON.stringify(expected)) fail("Users filters do not echo the request.");
  if (echoed.role !== null && users.some((user) => user.role !== echoed.role)) fail("Users rows do not match the role filter.");
  if (echoed.status !== null && users.some((user) => (user.is_active ? "active" : "inactive") !== echoed.status)) fail("Users rows do not match the status filter.");
  return {
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    users,
    pagination: normalizePagination(source.pagination, requested, users.length),
    filters: echoed,
  };
};

const normalizeHierarchyNode = (value, seen, depth = 0) => {
  if (depth > 10) fail("Users hierarchy exceeds the supported depth.");
  const source = requireExactFields(value, ["id", "first_name", "last_name", "email", "role", "is_active", "kyc_status", "created_at", "last_login_at", "children"], "Users hierarchy node");
  const row = normalizeListUser({
    id: source.id, first_name: source.first_name, last_name: source.last_name, email: source.email,
    role: source.role, is_active: source.is_active, kyc_status: source.kyc_status,
    created_at: source.created_at, last_login_at: source.last_login_at,
  });
  if (seen.has(row.id)) fail("Users hierarchy contains a repeated ID.");
  seen.add(row.id);
  return { ...row, children: requireArray(source.children, "Users hierarchy children").map((child) => normalizeHierarchyNode(child, seen, depth + 1)) };
};

export const normalizeAdminClosureUsersHierarchy = (payload, { expectedOwner } = {}) => {
  const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
  const source = requireExactFields(payload, ["owner_context", "users", "total_users"], "Users hierarchy response");
  const seen = new Set();
  const users = requireArray(source.users, "Users hierarchy roots").map((item) => normalizeHierarchyNode(item, seen));
  const totalUsers = requireCount(source.total_users, "Users hierarchy total");
  if (totalUsers !== seen.size || totalUsers > 500) fail("Users hierarchy total is invalid.");
  return { ownerContext: normalizeOwnerContext(source.owner_context, owner), users, totalUsers };
};

export const normalizeAdminClosureUser = (payload, { expectedOwner } = {}) => {
  const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
  const source = requireExactFields(payload, ["owner_context", "user"], "User response");
  return { ownerContext: normalizeOwnerContext(source.owner_context, owner), user: normalizeDetailUser(source.user) };
};

const normalizeDownline = (value) => {
  const source = requireExactFields(value, ["items", "truncated"], "User downline");
  if (typeof source.truncated !== "boolean") fail("User downline truncation is invalid.");
  const items = requireArray(source.items, "User downline rows").map((row) => {
    const item = requireExactFields(row, ["id", "first_name", "last_name", "email", "role", "is_active", "created_at"], "User downline row");
    return {
      id: requirePositiveId(item.id, "User downline ID"),
      first_name: requireStringOrNull(item.first_name, "User downline first name", 100),
      last_name: requireStringOrNull(item.last_name, "User downline last name", 100),
      email: requireStringOrNull(item.email, "User downline email", 255),
      role: requireEnumOrNull(item.role, ADMIN_CLOSURE_USERS_ROLES, "User downline role"),
      is_active: requireBooleanOrNull(item.is_active, "User downline active status"),
      created_at: requireTimestampOrNull(item.created_at, "User downline creation timestamp"),
    };
  });
  if (items.length > 50 || new Set(items.map((item) => item.id)).size !== items.length) fail("User downline is invalid.");
  return { items, truncated: source.truncated };
};
const normalizeChallenges = (value) => {
  const source = requireExactFields(value, ["items", "truncated"], "User challenges");
  if (typeof source.truncated !== "boolean") fail("User challenges truncation is invalid.");
  const items = requireArray(source.items, "User challenge rows").map((row) => {
    const item = requireExactFields(row, ["id", "program_name", "status", "initial_balance", "current_balance", "total_profit", "created_at"], "User challenge row");
    return {
      id: requirePositiveId(item.id, "User challenge ID"),
      program_name: requireStringOrNull(item.program_name, "User challenge program", 255),
      status: requireEnumOrNull(item.status, ADMIN_CLOSURE_USERS_CHALLENGE_STATUSES, "User challenge status"),
      initial_balance: requireDecimalOrNull(item.initial_balance, "User challenge initial balance"),
      current_balance: requireDecimalOrNull(item.current_balance, "User challenge current balance"),
      total_profit: requireDecimalOrNull(item.total_profit, "User challenge total profit"),
      created_at: requireTimestampOrNull(item.created_at, "User challenge creation timestamp"),
    };
  });
  if (items.length > 50 || new Set(items.map((item) => item.id)).size !== items.length) fail("User challenges are invalid.");
  return { items, truncated: source.truncated };
};
const normalizePayments = (value) => {
  const source = requireExactFields(value, ["items", "truncated"], "User payments");
  if (typeof source.truncated !== "boolean") fail("User payments truncation is invalid.");
  const items = requireArray(source.items, "User payment rows").map((row) => {
    const item = requireExactFields(row, ["id", "amount", "currency", "status", "payment_type", "created_at"], "User payment row");
    return {
      id: requirePositiveId(item.id, "User payment ID"),
      amount: requireDecimalOrNull(item.amount, "User payment amount"),
      currency: requireCurrencyOrNull(item.currency, "User payment currency"),
      status: requireEnumOrNull(item.status, ADMIN_CLOSURE_USERS_PAYMENT_STATUSES, "User payment status"),
      payment_type: requireEnumOrNull(item.payment_type, ADMIN_CLOSURE_USERS_PAYMENT_TYPES, "User payment type"),
      created_at: requireTimestampOrNull(item.created_at, "User payment creation timestamp"),
    };
  });
  if (items.length > 50 || new Set(items.map((item) => item.id)).size !== items.length) fail("User payments are invalid.");
  return { items, truncated: source.truncated };
};

export const normalizeAdminClosureUserDetails = (payload, { expectedOwner } = {}) => {
  const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
  const source = requireExactFields(payload, ["owner_context", "record_verification", "settlement_enabled", "user", "downline", "challenges", "payments"], "User details response");
  if (source.record_verification !== "unverified_legacy" || source.settlement_enabled !== false) {
    fail("User record boundary is invalid.");
  }
  return {
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    recordVerification: "unverified_legacy",
    settlementEnabled: false,
    user: normalizeDetailUser(source.user),
    downline: normalizeDownline(source.downline),
    challenges: normalizeChallenges(source.challenges),
    payments: normalizePayments(source.payments),
  };
};

const normalizeWriteResult = (payload, expectedOwner, expectedAction) => {
  const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
  const source = requireExactFields(payload, ["owner_context", "action", "message", "user"], "User account action response");
  if (source.action !== expectedAction || typeof source.message !== "string" || !source.message || source.message.length > 160) {
    fail("User account action acknowledgment is invalid.");
  }
  const user = requireExactFields(source.user, ["id", "role", "is_active"], "User account action result");
  return {
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    action: expectedAction,
    message: source.message,
    user: {
      id: requirePositiveId(user.id, "User account action user ID"),
      role: requireEnumOrNull(user.role, ADMIN_CLOSURE_USERS_ROLES, "User account action role"),
      is_active: requireBooleanOrNull(user.is_active, "User account action active status"),
    },
  };
};

const requiredText = (value, label, maximum) => {
  if (typeof value !== "string" || !value.trim() || value.trim().length > maximum || /[\u0000-\u001F]/.test(value)) fail(`${label} is invalid.`);
  return value.trim();
};
const optionalText = (value, label, maximum) => {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string" || value.trim().length > maximum || /[\u0000-\u001F]/.test(value)) fail(`${label} is invalid.`);
  return value.trim() || null;
};

export const buildAdminClosureUserCreate = (values = {}) => {
  const source = requireExactFields(values, ["email", "password", "first_name", "last_name", "phone", "country_code", "role"], "Create user input");
  const role = requireEnumOrNull(source.role, ADMIN_CLOSURE_USERS_CREATABLE_ROLES, "Create role");
  if (role === null) fail("Create role is required.");
  return {
    email: requiredText(source.email, "Create email", 255),
    password: requiredText(source.password, "Create password", 512),
    first_name: requiredText(source.first_name, "Create first name", 100),
    last_name: requiredText(source.last_name, "Create last name", 100),
    phone: optionalText(source.phone, "Create phone", 20),
    country_code: optionalText(source.country_code, "Create country code", 2),
    role,
  };
};
export const buildAdminClosureUserUpdate = (values = {}) => {
  const source = requireExactFields(values, ["first_name", "last_name", "phone", "country_code", "role", "is_active"], "Update user input");
  const role = requireEnumOrNull(source.role, ADMIN_CLOSURE_USERS_ROLES, "Update role");
  if (role === null || typeof source.is_active !== "boolean") fail("Update role or account status is invalid.");
  return {
    first_name: requiredText(source.first_name, "Update first name", 100),
    last_name: requiredText(source.last_name, "Update last name", 100),
    phone: optionalText(source.phone, "Update phone", 20),
    country_code: optionalText(source.country_code, "Update country code", 2),
    role,
    is_active: source.is_active,
  };
};
export const buildAdminClosurePasswordReset = (newPassword) => ({ new_password: requiredText(newPassword, "New password", 512) });

const abortError = () => {
  const error = new Error("User-management request was cancelled.");
  error.name = "AbortError";
  return error;
};
const throwIfAborted = (signal) => { if (signal?.aborted) throw abortError(); };
const requireTargetId = (value) => requirePositiveId(value, "User target ID");

/** Injectable one-shot transport. Every user route is canonical; no polling or 401 replay is allowed. */
export const createAdminClosureUsersService = (client = api) => ({
  loadUsers: async ({ expectedOwner, signal, ...options } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    const params = buildAdminClosureUsersParams(options);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_USERS_ENDPOINTS.users, { params, signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeAdminClosureUsersList(response?.data, { expectedOwner: owner, params });
  },
  loadHierarchy: async ({ expectedOwner, signal } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_USERS_ENDPOINTS.hierarchy, { signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeAdminClosureUsersHierarchy(response?.data, { expectedOwner: owner });
  },
  loadUser: async ({ expectedOwner, userId, signal } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    const id = requireTargetId(userId);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_USERS_ENDPOINTS.user(id), { signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeAdminClosureUser(response?.data, { expectedOwner: owner });
  },
  loadDetails: async ({ expectedOwner, userId, signal } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    const id = requireTargetId(userId);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_USERS_ENDPOINTS.fullDetails(id), { signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeAdminClosureUserDetails(response?.data, { expectedOwner: owner });
  },
  createUser: async ({ expectedOwner, values, signal } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    const body = buildAdminClosureUserCreate(values);
    throwIfAborted(signal);
    const response = await client.post(ADMIN_CLOSURE_USERS_ENDPOINTS.users, body, { signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeWriteResult(response?.data, owner, "created");
  },
  updateUser: async ({ expectedOwner, userId, values, signal } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    const id = requireTargetId(userId);
    const body = buildAdminClosureUserUpdate(values);
    throwIfAborted(signal);
    const response = await client.put(ADMIN_CLOSURE_USERS_ENDPOINTS.user(id), body, { signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeWriteResult(response?.data, owner, "updated");
  },
  deactivateUser: async ({ expectedOwner, userId, signal } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    const id = requireTargetId(userId);
    throwIfAborted(signal);
    const response = await client.delete(ADMIN_CLOSURE_USERS_ENDPOINTS.user(id), { signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeWriteResult(response?.data, owner, "deactivated");
  },
  resetPassword: async ({ expectedOwner, userId, newPassword, signal } = {}) => {
    const owner = normaliseAdminClosureUsersExpectedOwner(expectedOwner);
    const id = requireTargetId(userId);
    const body = buildAdminClosurePasswordReset(newPassword);
    throwIfAborted(signal);
    const response = await client.post(ADMIN_CLOSURE_USERS_ENDPOINTS.resetPassword(id), body, { signal, _skipAuthRefresh: true });
    throwIfAborted(signal);
    return normalizeWriteResult(response?.data, owner, "password_reset");
  },
});

export const isAdminClosureUsersRequestCanceled = (error) => error?.name === "AbortError" || error?.code === "ERR_CANCELED";
export const adminClosureUsersError = () => "The user-management service is unavailable or its response could not be validated. No user record or account action has been assumed.";
