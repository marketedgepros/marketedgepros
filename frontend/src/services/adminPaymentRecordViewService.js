import api from "./api.js";
import { ADMIN_ROLES, ALL_ROLES, ROLES } from "../constants/roles.js";
import { recordedTimestampOrNull } from "./userDashboardViewService.js";

export const ADMIN_PAYMENT_RECORD_ENDPOINTS = Object.freeze({
  payments: "/admin/payments",
  approvalRequests: "/payment-approvals/pending",
});
export const ADMIN_PAYMENT_PAGE_LIMIT = 10000;
export const ADMIN_PAYMENT_PER_PAGE_LIMIT = 50;
export const ADMIN_PAYMENT_PAGE_SIZE = 20;
export const ADMIN_PAYMENT_OFFSET_LIMIT = 10000;
export const ADMIN_PAYMENT_STATUSES = Object.freeze([
  "pending",
  "completed",
  "failed",
  "refunded",
]);
export const ADMIN_PAYMENT_PURPOSES = Object.freeze([
  "challenge_purchase",
  "withdrawal",
  "refund",
]);

const ID_LIMIT = 2147483647;
const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const CURRENCY = /^[A-Z]{3}$/;
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class AdminPaymentRecordContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "AdminPaymentRecordContractError";
  }
}

const fail = (message) => {
  throw new AdminPaymentRecordContractError(message);
};
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
  const actual = Object.keys(record);
  if (actual.length !== fields.length || fields.some((field) => !hasOwn(record, field))) {
    fail(`${label} contains fields outside the payment-record contract.`);
  }
  return record;
};
const requirePositiveId = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > ID_LIMIT) {
    fail(`${label} must be a positive bounded integer.`);
  }
  return value;
};
const requireNonNegativeCount = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > ID_LIMIT) {
    fail(`${label} must be a non-negative bounded integer.`);
  }
  return value;
};
const requireDecimalOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > 128 || !DECIMAL.test(value)) {
    fail(`${label} must be an exact decimal string or null.`);
  }
  return value;
};
const requireCalendarTimestampOrNull = (value, label) => {
  if (value === null) return null;
  const timestamp = recordedTimestampOrNull(value);
  if (timestamp === null) fail(`${label} must be a complete ISO calendar timestamp or null.`);
  return timestamp;
};
const requireTextOrNull = (value, label, maximum = 128) => {
  if (value === null) return null;
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > maximum ||
    /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(value)
  ) {
    fail(`${label} must be a bounded text value or null.`);
  }
  return value;
};
const requireEnumOrNull = (value, values, label) => {
  if (value === null) return null;
  if (!values.includes(value)) fail(`${label} is unsupported.`);
  return value;
};

/** The owner is independently sourced from the active auth store, never a server response. */
export const normaliseAdminPaymentExpectedOwner = (expectedOwner) => {
  const source = requireExactFields(
    expectedOwner,
    ["user_id", "tenant_id"],
    "Expected admin-payment owner",
  );
  return {
    user_id: requirePositiveId(source.user_id, "Expected admin-payment owner user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Expected admin-payment owner tenant ID"),
  };
};
export const normalizeAdminPaymentExpectedOwner = normaliseAdminPaymentExpectedOwner;

export const adminPaymentIdentityKey = ({ isAuthenticated, userId, tenantId, role }) =>
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null]);

/** No tenant aliases are accepted: user.tenant_id is the only client identity source. */
export const adminPaymentPrincipalFromAuth = (user, isAuthenticated) => {
  try {
    if (isAuthenticated !== true || !ALL_ROLES.includes(user?.role)) return null;
    const owner = normaliseAdminPaymentExpectedOwner({
      user_id: user?.id,
      tenant_id: user?.tenant_id,
    });
    return {
      owner,
      role: user.role,
      key: adminPaymentIdentityKey({
        isAuthenticated,
        userId: owner.user_id,
        tenantId: owner.tenant_id,
        role: user.role,
      }),
    };
  } catch {
    return null;
  }
};

const requirePaymentReadRole = (role) => {
  if (!ADMIN_ROLES.includes(role)) fail("Payment records require an existing admin role.");
  return role;
};
const requireApprovalReadRole = (role) => {
  if (role !== ROLES.SUPERMASTER) {
    fail("Pending approval requests require the declared supermaster role.");
  }
  return role;
};

const requirePaginationInput = (page, perPage) => {
  if (!Number.isSafeInteger(page) || page < 1 || page > ADMIN_PAYMENT_PAGE_LIMIT) {
    fail(`Payment-record page must be between 1 and ${ADMIN_PAYMENT_PAGE_LIMIT}.`);
  }
  if (!Number.isSafeInteger(perPage) || perPage < 1 || perPage > ADMIN_PAYMENT_PER_PAGE_LIMIT) {
    fail(`Payment-record page size must be between 1 and ${ADMIN_PAYMENT_PER_PAGE_LIMIT}.`);
  }
  if ((page - 1) * perPage > ADMIN_PAYMENT_OFFSET_LIMIT) {
    fail(`Payment-record offset must not exceed ${ADMIN_PAYMENT_OFFSET_LIMIT}.`);
  }
  return { page, per_page: perPage };
};

/** Validate all payment query values before transport; null filters are omitted. */
export const buildAdminPaymentParams = ({
  page = 1,
  perPage = ADMIN_PAYMENT_PAGE_SIZE,
  status = null,
  type = null,
} = {}) => {
  const pagination = requirePaginationInput(page, perPage);
  const normalizedStatus = requireEnumOrNull(status, ADMIN_PAYMENT_STATUSES, "Payment status filter");
  const normalizedType = requireEnumOrNull(type, ADMIN_PAYMENT_PURPOSES, "Payment purpose filter");
  return {
    ...pagination,
    ...(normalizedStatus === null ? {} : { status: normalizedStatus }),
    ...(normalizedType === null ? {} : { type: normalizedType }),
  };
};

/** Approval requests are always the server's pending-only read endpoint. */
export const buildApprovalRequestParams = ({
  page = 1,
  perPage = ADMIN_PAYMENT_PAGE_SIZE,
} = {}) => requirePaginationInput(page, perPage);

export const canRequestAdminPaymentPage = (page, perPage = ADMIN_PAYMENT_PAGE_SIZE) => {
  try {
    requirePaginationInput(page, perPage);
    return true;
  } catch {
    return false;
  }
};

const normalizeOwnerContext = (value, expectedOwner) => {
  const source = requireExactFields(value, ["user_id", "tenant_id"], "Admin-payment owner context");
  const owner = {
    user_id: requirePositiveId(source.user_id, "Admin-payment owner-context user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Admin-payment owner-context tenant ID"),
  };
  if (owner.user_id !== expectedOwner.user_id || owner.tenant_id !== expectedOwner.tenant_id) {
    fail("Admin-payment owner context does not match the active account.");
  }
  return owner;
};

const normalizeBoundary = (source) => {
  if (source.record_verification !== "unverified_legacy" || source.settlement_enabled !== false) {
    fail("Admin-payment verification or settlement boundary is invalid.");
  }
  return { recordVerification: "unverified_legacy", settlementEnabled: false };
};

const normalizePagination = (value, params, rowCount) => {
  const source = requireExactFields(value, ["page", "per_page", "total", "pages"], "Admin-payment pagination");
  const page = source.page;
  const perPage = source.per_page;
  const total = requireNonNegativeCount(source.total, "Admin-payment pagination total");
  const pages = requireNonNegativeCount(source.pages, "Admin-payment pagination pages");
  if (page !== params.page || perPage !== params.per_page) {
    fail("Admin-payment pagination does not match the requested page.");
  }
  requirePaginationInput(page, perPage);
  if (pages !== Math.ceil(total / perPage)) {
    fail("Admin-payment pagination is mathematically inconsistent.");
  }
  const expectedRows = Math.min(perPage, Math.max(0, total - (page - 1) * perPage));
  if (rowCount !== expectedRows) {
    fail("Admin-payment page does not match its server pagination total.");
  }
  return { page, per_page: perPage, total, pages };
};

const normalizeCurrencyOrNull = (value) => {
  if (value === null) return null;
  if (typeof value !== "string" || !CURRENCY.test(value)) {
    fail("Recorded payment currency must be an uppercase three-letter code or null.");
  }
  return value;
};

const normalizePayment = (value) => {
  const source = requireExactFields(
    value,
    ["id", "user_id", "amount", "currency", "payment_type", "payment_method", "status", "created_at"],
    "Recorded payment",
  );
  return {
    id: requirePositiveId(source.id, "Recorded payment ID"),
    user_id: requirePositiveId(source.user_id, "Recorded payment user ID"),
    amount: requireDecimalOrNull(source.amount, "Recorded payment amount"),
    currency: normalizeCurrencyOrNull(source.currency),
    payment_type: requireEnumOrNull(source.payment_type, ADMIN_PAYMENT_PURPOSES, "Recorded payment purpose"),
    payment_method: requireTextOrNull(source.payment_method, "Recorded payment method"),
    status: requireEnumOrNull(source.status, ADMIN_PAYMENT_STATUSES, "Recorded payment status"),
    created_at: requireCalendarTimestampOrNull(source.created_at, "Recorded payment timestamp"),
  };
};

export const normalizeAdminPaymentsResponse = (payload, { expectedOwner, params } = {}) => {
  const owner = normaliseAdminPaymentExpectedOwner(expectedOwner);
  const requiredParams = buildAdminPaymentParams({
    page: params?.page,
    perPage: params?.per_page,
    status: hasOwn(params || {}, "status") ? params.status : null,
    type: hasOwn(params || {}, "type") ? params.type : null,
  });
  const source = requireExactFields(
    payload,
    ["owner_context", "record_verification", "settlement_enabled", "payments", "pagination", "filters"],
    "Admin payment-list response",
  );
  const payments = requireArray(source.payments, "Recorded payments").map(normalizePayment);
  const pagination = normalizePagination(source.pagination, requiredParams, payments.length);
  const identifiers = new Set(payments.map((payment) => payment.id));
  if (identifiers.size !== payments.length) fail("Recorded payments contain duplicate identifiers.");
  if (
    requiredParams.status !== undefined &&
    payments.some((payment) => payment.status !== requiredParams.status)
  ) {
    fail("Recorded payment rows do not match the requested status filter.");
  }
  if (
    requiredParams.type !== undefined &&
    payments.some((payment) => payment.payment_type !== requiredParams.type)
  ) {
    fail("Recorded payment rows do not match the requested purpose filter.");
  }
  const filters = requireExactFields(source.filters, ["status", "type"], "Admin payment filters");
  const status = requireEnumOrNull(filters.status, ADMIN_PAYMENT_STATUSES, "Admin payment response status filter");
  const type = requireEnumOrNull(filters.type, ADMIN_PAYMENT_PURPOSES, "Admin payment response purpose filter");
  if (status !== (requiredParams.status ?? null) || type !== (requiredParams.type ?? null)) {
    fail("Admin payment filters do not echo the request.");
  }
  return {
    kind: "payments",
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    ...normalizeBoundary(source),
    payments,
    pagination,
    filters: { status, type },
  };
};

const normalizeApprovalRequest = (value) => {
  const source = requireExactFields(
    value,
    [
      "id",
      "requested_by",
      "requested_for",
      "challenge_id",
      "payment_id",
      "amount",
      "payment_type",
      "status",
      "created_at",
      "reviewed_at",
    ],
    "Pending legacy approval request",
  );
  if (source.status !== "pending") fail("Pending legacy approval status must be pending.");
  const nullableId = (candidate, label) => (
    candidate === null ? null : requirePositiveId(candidate, label)
  );
  return {
    id: requirePositiveId(source.id, "Pending legacy approval request ID"),
    requested_by: requirePositiveId(source.requested_by, "Pending legacy approval requester ID"),
    requested_for: requirePositiveId(source.requested_for, "Pending legacy approval recipient ID"),
    challenge_id: nullableId(source.challenge_id, "Pending legacy approval challenge ID"),
    payment_id: nullableId(source.payment_id, "Pending legacy approval payment ID"),
    amount: requireDecimalOrNull(source.amount, "Pending legacy approval amount"),
    payment_type: requireEnumOrNull(source.payment_type, ["cash", "free"], "Pending legacy approval type"),
    status: "pending",
    created_at: requireCalendarTimestampOrNull(source.created_at, "Pending legacy approval creation timestamp"),
    reviewed_at: requireCalendarTimestampOrNull(source.reviewed_at, "Pending legacy approval review timestamp"),
  };
};

export const normalizeApprovalRequestsResponse = (payload, { expectedOwner, params } = {}) => {
  const owner = normaliseAdminPaymentExpectedOwner(expectedOwner);
  const requiredParams = buildApprovalRequestParams({
    page: params?.page,
    perPage: params?.per_page,
  });
  const source = requireExactFields(
    payload,
    ["owner_context", "record_verification", "settlement_enabled", "requests", "pagination", "filters"],
    "Pending approval-request response",
  );
  const requests = requireArray(source.requests, "Pending legacy approval requests").map(normalizeApprovalRequest);
  const pagination = normalizePagination(source.pagination, requiredParams, requests.length);
  const identifiers = new Set(requests.map((request) => request.id));
  if (identifiers.size !== requests.length) fail("Pending legacy approval requests contain duplicate identifiers.");
  const filters = requireExactFields(source.filters, ["status"], "Pending approval-request filters");
  if (filters.status !== "pending") fail("Pending approval-request filter must remain pending.");
  if (requests.some((request) => request.status !== filters.status)) {
    fail("Pending legacy approval rows do not match the pending filter.");
  }
  return {
    kind: "approval-requests",
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    ...normalizeBoundary(source),
    requests,
    pagination,
    filters: { status: "pending" },
  };
};
export const normalizeAdminApprovalRequestsResponse = normalizeApprovalRequestsResponse;

const abortError = () => {
  const error = new Error("Admin-payment record request was cancelled.");
  error.name = "AbortError";
  return error;
};
const throwIfAborted = (signal) => {
  if (signal?.aborted) throw abortError();
};

/** Injectable Axios-compatible, one-shot GET factory. It never polls or retries. */
export const createAdminPaymentRecordViewService = (client = api) => {
  const loadPayments = async ({ expectedOwner, role, signal, ...options } = {}) => {
    const owner = normaliseAdminPaymentExpectedOwner(expectedOwner);
    requirePaymentReadRole(role);
    const params = buildAdminPaymentParams(options);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_PAYMENT_RECORD_ENDPOINTS.payments, {
      params,
      signal,
      _skipAuthRefresh: true,
    });
    throwIfAborted(signal);
    return normalizeAdminPaymentsResponse(response?.data, { expectedOwner: owner, params });
  };
  const loadApprovalRequests = async ({ expectedOwner, role, signal, ...options } = {}) => {
    const owner = normaliseAdminPaymentExpectedOwner(expectedOwner);
    requireApprovalReadRole(role);
    const params = buildApprovalRequestParams(options);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_PAYMENT_RECORD_ENDPOINTS.approvalRequests, {
      params,
      signal,
      _skipAuthRefresh: true,
    });
    throwIfAborted(signal);
    return normalizeApprovalRequestsResponse(response?.data, { expectedOwner: owner, params });
  };
  return { loadPayments, loadApprovalRequests };
};

export const isAdminPaymentRecordRequestCanceled = (error) =>
  error?.name === "AbortError" || error?.code === "ERR_CANCELED";
export const adminPaymentRecordError = () =>
  "The service is unavailable or its response could not be validated. No payment value, settlement state, or empty result has been assumed.";
