import api from "./api.js";
import { ADMIN_ROLES, ALL_ROLES } from "../constants/roles.js";

export const ADMIN_INSIGHT_ENDPOINTS = Object.freeze({
  dashboard: "/admin/dashboard/stats",
  analytics: "/analytics/comprehensive",
});
export const ADMIN_INSIGHT_REQUEST_TIMEOUT_MS = 5000;
export const ADMIN_INSIGHT_DAYS = Object.freeze([7, 30, 90, 180, 365]);
export const ADMIN_INSIGHT_KINDS = Object.freeze(["dashboard", "analytics"]);
export const ADMIN_INSIGHT_ROLE_CODES = Object.freeze(["supermaster", "master", "affiliate", "trader", "guest"]);
export const ADMIN_INSIGHT_KYC_CODES = Object.freeze([
  "not_submitted", "pending", "approved", "rejected", "incomplete", "verified", "unverified",
]);
export const ADMIN_INSIGHT_CHALLENGE_CODES = Object.freeze([
  "pending", "active", "completed", "passed", "failed", "funded", "cancelled",
]);
export const ADMIN_INSIGHT_PAYMENT_CODES = Object.freeze(["pending", "completed", "failed", "refunded"]);
export const ADMIN_INSIGHT_PAYMENT_TYPES = Object.freeze(["challenge_purchase", "withdrawal", "refund"]);

const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const CURRENCY = /^[A-Z]{3}$/;
const ISO_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
const CALENDAR_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class AdminInsightContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "AdminInsightContractError";
  }
}

const fail = (message) => {
  throw new AdminInsightContractError(message);
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
    fail(`${label} contains fields outside the canonical insight contract.`);
  }
  return record;
};
const requirePositiveId = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1) fail(`${label} must be a positive safe integer.`);
  return value;
};
const requireCount = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 0) fail(`${label} must be a non-negative safe integer.`);
  return value;
};
const isCalendarDate = (year, month, day) => {
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return day <= [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
};
const requireCalendarDay = (value, label) => {
  if (typeof value !== "string") fail(`${label} must be a UTC calendar day.`);
  const match = CALENDAR_DAY.exec(value);
  if (!match || !isCalendarDate(Number(match[1]), Number(match[2]), Number(match[3]))) {
    fail(`${label} must be a real UTC calendar day.`);
  }
  return value;
};
const requireTimestamp = (value, label) => {
  if (typeof value !== "string") fail(`${label} must be a complete ISO timestamp.`);
  const match = ISO_TIMESTAMP.exec(value);
  if (!match) fail(`${label} must be a complete ISO timestamp with a timezone.`);
  const [, rawYear, rawMonth, rawDay, rawHour, rawMinute, rawSecond, zone] = match;
  const year = Number(rawYear);
  const month = Number(rawMonth);
  const day = Number(rawDay);
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  const second = Number(rawSecond);
  if (!isCalendarDate(year, month, day) || hour > 23 || minute > 59 || second > 59) {
    fail(`${label} must contain a real calendar timestamp.`);
  }
  if (zone !== "Z") {
    const [zoneHour, zoneMinute] = zone.slice(1).split(":").map(Number);
    if (zoneHour > 23 || zoneMinute > 59) fail(`${label} has an invalid timezone.`);
  }
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) fail(`${label} is not a valid timestamp.`);
  // Date.parse truncates fractions to milliseconds; keep the remaining precision
  // for order/as_of comparisons while retaining milliseconds for UTC calendars.
  const fraction = /\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/.exec(value)?.[1] ?? "";
  const microseconds = BigInt(milliseconds) * 1000n + BigInt(fraction.padEnd(6, "0").slice(3));
  return { value, milliseconds, microseconds };
};
const requireTimestampOrNull = (value, label) => (value === null ? null : requireTimestamp(value, label));
const requireEnumOrNull = (value, values, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || !values.includes(value)) fail(`${label} is unsupported.`);
  return value;
};
const requireDecimalOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > 128 || !DECIMAL.test(value)) {
    fail(`${label} must be an exact decimal string or null.`);
  }
  return value;
};
const requireCurrencyOrNull = (value) => {
  if (value === null) return null;
  if (typeof value !== "string" || !CURRENCY.test(value)) {
    fail("Recorded payment currency must be an uppercase three-letter code or null.");
  }
  return value;
};

/** Independent auth identity. No tenant aliases or server-provided identity are accepted. */
export const normaliseAdminInsightExpectedOwner = (expectedOwner) => {
  const source = requireRecord(expectedOwner, "Expected admin-insight owner");
  const fields = Object.keys(source).sort();
  const validFields = fields.length === 2
    ? fields[0] === "tenant_id" && fields[1] === "user_id"
    : fields.length === 3 && fields[0] === "role" && fields[1] === "tenant_id" && fields[2] === "user_id";
  if (!validFields) fail("Expected admin-insight owner contains unsupported fields.");
  const owner = {
    user_id: requirePositiveId(source.user_id, "Expected admin-insight user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Expected admin-insight tenant ID"),
  };
  if (hasOwn(source, "role")) {
    if (typeof source.role !== "string" || !ALL_ROLES.includes(source.role)) {
      fail("Expected admin-insight role is unsupported.");
    }
    owner.role = source.role;
  }
  return owner;
};
export const normalizeAdminInsightExpectedOwner = normaliseAdminInsightExpectedOwner;

export const adminInsightIdentityKey = ({ isAuthenticated, userId, tenantId, role }) => (
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null])
);
export const adminInsightRequestKey = ({ isAuthenticated, userId, tenantId, role, kind, days }) => (
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null, kind ?? null, days ?? null])
);
export const adminInsightPrincipalFromAuth = (user, isAuthenticated) => {
  try {
    if (isAuthenticated !== true || !ADMIN_ROLES.includes(user?.role)) return null;
    const owner = normaliseAdminInsightExpectedOwner({
      user_id: user?.id,
      tenant_id: user?.tenant_id,
      role: user.role,
    });
    return {
      owner,
      role: owner.role,
      key: adminInsightIdentityKey({
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

export const normaliseAdminInsightDays = (days) => {
  if (!Number.isSafeInteger(days) || !ADMIN_INSIGHT_DAYS.includes(days)) {
    fail("Analytics days must be one of 7, 30, 90, 180, or 365.");
  }
  return days;
};
export const normalizeAdminInsightDays = normaliseAdminInsightDays;

const normalizeOwnerContext = (value, expectedOwner) => {
  const source = requireExactFields(value, ["user_id", "tenant_id"], "Admin-insight owner context");
  const owner = {
    user_id: requirePositiveId(source.user_id, "Admin-insight owner-context user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Admin-insight owner-context tenant ID"),
  };
  if (owner.user_id !== expectedOwner.user_id || owner.tenant_id !== expectedOwner.tenant_id) {
    fail("Admin-insight owner context does not match the active account.");
  }
  return owner;
};
const normalizeBoundary = (source) => {
  if (source.record_verification !== "unverified_legacy" || source.settlement_enabled !== false) {
    fail("Admin-insight verification or settlement boundary is invalid.");
  }
  return { recordVerification: "unverified_legacy", settlementEnabled: false };
};
const normalizeCounts = (value) => {
  const source = requireExactFields(value, ["users", "challenges", "payments"], "Admin-insight counts");
  return {
    users: requireCount(source.users, "Admin-insight user count"),
    challenges: requireCount(source.challenges, "Admin-insight challenge count"),
    payments: requireCount(source.payments, "Admin-insight payment count"),
  };
};
const normalizeDistribution = (value, label, codes, expectedTotal) => {
  const rows = requireArray(value, label).map((candidate, index) => {
    const source = requireExactFields(candidate, ["code", "count"], `${label} row ${index + 1}`);
    return {
      code: requireEnumOrNull(source.code, codes, `${label} code`),
      count: requireCount(source.count, `${label} count`),
    };
  });
  const seen = new Set();
  let sum = 0;
  rows.forEach((row) => {
    const codeKey = row.code === null ? "__unknown__" : row.code;
    if (seen.has(codeKey)) fail(`${label} contains duplicate codes.`);
    seen.add(codeKey);
    sum += row.count;
    if (!Number.isSafeInteger(sum)) fail(`${label} count sum is unsafe.`);
  });
  if (sum !== expectedTotal) fail(`${label} count sum does not equal its source count.`);
  return rows;
};
const normalizeDistributions = (value, counts) => {
  const source = requireExactFields(value, ["user_roles", "user_kyc", "challenge_status", "payment_status"], "Admin-insight distributions");
  return {
    userRoles: normalizeDistribution(source.user_roles, "User-role distribution", ADMIN_INSIGHT_ROLE_CODES, counts.users),
    userKyc: normalizeDistribution(source.user_kyc, "User-KYC distribution", ADMIN_INSIGHT_KYC_CODES, counts.users),
    challengeStatus: normalizeDistribution(source.challenge_status, "Challenge-status distribution", ADMIN_INSIGHT_CHALLENGE_CODES, counts.challenges),
    paymentStatus: normalizeDistribution(source.payment_status, "Payment-status distribution", ADMIN_INSIGHT_PAYMENT_CODES, counts.payments),
  };
};
const ensureNotAfterAsOf = (timestamp, asOf, label) => {
  if (timestamp !== null && timestamp.microseconds > asOf.microseconds) {
    fail(`${label} must not be after as_of.`);
  }
};
const normalizeRecentUser = (value, asOf) => {
  const source = requireExactFields(value, ["id", "role", "is_active", "kyc_status", "created_at"], "Recent user");
  if (source.is_active !== null && typeof source.is_active !== "boolean") {
    fail("Recent user active flag must be boolean or null.");
  }
  const timestamp = requireTimestampOrNull(source.created_at, "Recent user creation timestamp");
  ensureNotAfterAsOf(timestamp, asOf, "Recent user creation timestamp");
  return {
    id: requirePositiveId(source.id, "Recent user ID"),
    role: requireEnumOrNull(source.role, ADMIN_INSIGHT_ROLE_CODES, "Recent user role"),
    is_active: source.is_active,
    kyc_status: requireEnumOrNull(source.kyc_status, ADMIN_INSIGHT_KYC_CODES, "Recent user KYC status"),
    created_at: timestamp?.value ?? null,
    _sortTimestamp: timestamp?.microseconds ?? null,
  };
};
const normalizeRecentPayment = (value, asOf) => {
  const source = requireExactFields(value, ["id", "user_id", "amount", "currency", "payment_type", "status", "created_at"], "Recent payment");
  const timestamp = requireTimestampOrNull(source.created_at, "Recent payment creation timestamp");
  ensureNotAfterAsOf(timestamp, asOf, "Recent payment creation timestamp");
  return {
    id: requirePositiveId(source.id, "Recent payment ID"),
    user_id: requirePositiveId(source.user_id, "Recent payment user ID"),
    amount: requireDecimalOrNull(source.amount, "Recent payment amount"),
    currency: requireCurrencyOrNull(source.currency),
    payment_type: requireEnumOrNull(source.payment_type, ADMIN_INSIGHT_PAYMENT_TYPES, "Recent payment type"),
    status: requireEnumOrNull(source.status, ADMIN_INSIGHT_PAYMENT_CODES, "Recent payment status"),
    created_at: timestamp?.value ?? null,
    _sortTimestamp: timestamp?.microseconds ?? null,
  };
};
const ensureRecentOrder = (rows, label) => {
  const ids = new Set();
  rows.forEach((row, index) => {
    if (ids.has(row.id)) fail(`${label} contains duplicate identifiers.`);
    ids.add(row.id);
    if (index === 0) return;
    const before = rows[index - 1];
    const currentTimestamp = row._sortTimestamp;
    const beforeTimestamp = before._sortTimestamp;
    const outOfOrder = beforeTimestamp === null
      ? (currentTimestamp !== null || (currentTimestamp === null && before.id < row.id))
      : (currentTimestamp !== null && (beforeTimestamp < currentTimestamp || (beforeTimestamp === currentTimestamp && before.id < row.id)));
    if (outOfOrder) fail(`${label} must be ordered by created_at DESC NULLS LAST and ID DESC.`);
  });
};
const withoutSortMetadata = (row) => {
  const { _sortTimestamp, ...clean } = row;
  return clean;
};
const normalizeRecentRows = (value, count, asOf, kind) => {
  const users = requireArray(value.users, "Recent users").map((row) => normalizeRecentUser(row, asOf));
  const payments = requireArray(value.payments, "Recent payments").map((row) => normalizeRecentPayment(row, asOf));
  if (kind === "dashboard") {
    if (users.length !== Math.min(count.users, 5) || payments.length !== Math.min(count.payments, 5)) {
      fail("Dashboard recent-row cardinality does not match the source counts.");
    }
  } else if (users.length !== 0 || payments.length !== 0) {
    fail("Analytics must not contain recent rows.");
  }
  ensureRecentOrder(users, "Recent users");
  ensureRecentOrder(payments, "Recent payments");
  return { recentUsers: users.map(withoutSortMetadata), recentPayments: payments.map(withoutSortMetadata) };
};
const utcDay = (date) => date.toISOString().slice(0, 10);
const expectedDailyDates = (asOf, days) => {
  const asOfDate = new Date(asOf.milliseconds);
  const today = new Date(Date.UTC(asOfDate.getUTCFullYear(), asOfDate.getUTCMonth(), asOfDate.getUTCDate()));
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(today);
    date.setUTCDate(today.getUTCDate() - (days - 1 - index));
    return utcDay(date);
  });
};
const normalizeDailyActivity = (value, counts, asOf, days) => {
  const rows = requireArray(value, "Daily activity");
  if (days === null) {
    if (rows.length !== 0) fail("Dashboard daily activity must be empty.");
    return [];
  }
  const expectedDates = expectedDailyDates(asOf, days);
  if (rows.length !== days) fail("Analytics daily activity must contain every requested UTC day.");
  const totals = { users: 0, challenges: 0, payments: 0 };
  const normalized = rows.map((candidate, index) => {
    const source = requireExactFields(candidate, ["date", "users", "challenges", "payments"], `Daily activity row ${index + 1}`);
    const row = {
      date: requireCalendarDay(source.date, "Daily activity date"),
      users: requireCount(source.users, "Daily activity user count"),
      challenges: requireCount(source.challenges, "Daily activity challenge count"),
      payments: requireCount(source.payments, "Daily activity payment count"),
    };
    if (row.date !== expectedDates[index]) fail("Analytics daily dates are out of order or outside the requested UTC range.");
    for (const key of Object.keys(totals)) {
      totals[key] += row[key];
      if (!Number.isSafeInteger(totals[key])) fail("Analytics daily total is unsafe.");
    }
    return row;
  });
  for (const key of Object.keys(totals)) {
    if (totals[key] !== counts[key]) fail(`Analytics daily ${key} total does not equal its source count.`);
  }
  return normalized;
};

/**
 * Maps only the direct canonical HTTP response. It validates the independently held
 * principal, requested filter, boundaries, dates, cardinalities, and record shapes.
 */
export const mapAdminInsight = (payload, { expectedOwner, days } = {}) => {
  const owner = normaliseAdminInsightExpectedOwner(expectedOwner);
  const expectedDays = days === null ? null : normaliseAdminInsightDays(days);
  const kind = expectedDays === null ? "dashboard" : "analytics";
  const source = requireExactFields(payload, [
    "owner_context", "record_verification", "settlement_enabled", "as_of", "filters", "counts",
    "distributions", "recent_users", "recent_payments", "daily_activity",
  ], "Admin-insight response");
  const asOf = requireTimestamp(source.as_of, "Admin-insight as_of");
  if (!source.as_of.endsWith("Z")) fail("Admin-insight as_of must be UTC.");
  const filters = requireExactFields(source.filters, ["days"], "Admin-insight filters");
  if (filters.days !== expectedDays) fail("Admin-insight filters do not echo the requested days.");
  const counts = normalizeCounts(source.counts);
  const recents = normalizeRecentRows({ users: source.recent_users, payments: source.recent_payments }, counts, asOf, kind);
  return {
    kind,
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    ...normalizeBoundary(source),
    asOf: asOf.value,
    filters: { days: expectedDays },
    counts,
    distributions: normalizeDistributions(source.distributions, counts),
    ...recents,
    dailyActivity: normalizeDailyActivity(source.daily_activity, counts, asOf, expectedDays),
  };
};

const abortError = () => {
  const error = new Error("Admin-insight request was cancelled.");
  error.name = "AbortError";
  return error;
};
const throwIfAborted = (signal) => {
  if (signal?.aborted) throw abortError();
};
const normalizeRequest = ({ kind, expectedOwner, days } = {}) => {
  if (!ADMIN_INSIGHT_KINDS.includes(kind)) fail("Admin-insight kind must be dashboard or analytics.");
  const owner = normaliseAdminInsightExpectedOwner(expectedOwner);
  if (owner.role !== undefined && !ADMIN_ROLES.includes(owner.role)) {
    fail("Admin insights require an existing admin role.");
  }
  if (kind === "dashboard") {
    if (days !== undefined && days !== null) fail("Dashboard does not accept a days query.");
    return { kind, owner, days: null };
  }
  return { kind, owner, days: normaliseAdminInsightDays(days === undefined ? 30 : days) };
};

/** Injectable Axios-compatible one-shot reader. It neither polls nor retries. */
export const createAdminInsightViewService = (client = api) => ({
  loadAdminInsight: async (options = {}) => {
    const request = normalizeRequest(options);
    throwIfAborted(options.signal);
    const config = request.kind === "analytics"
      ? { params: { days: request.days }, signal: options.signal, timeout: ADMIN_INSIGHT_REQUEST_TIMEOUT_MS, _skipAuthRefresh: true }
      : { signal: options.signal, timeout: ADMIN_INSIGHT_REQUEST_TIMEOUT_MS, _skipAuthRefresh: true };
    const response = await client.get(ADMIN_INSIGHT_ENDPOINTS[request.kind], config);
    throwIfAborted(options.signal);
    return mapAdminInsight(response?.data, { expectedOwner: request.owner, days: request.days });
  },
});

const defaultAdminInsightViewService = createAdminInsightViewService();
export const loadAdminInsight = (options = {}) => defaultAdminInsightViewService.loadAdminInsight(options);
export const isAdminInsightRequestCanceled = (error) => (
  error?.name === "AbortError" || error?.code === "ERR_CANCELED"
);
export const adminInsightError = () => (
  "The service is unavailable or its response could not be validated. No count, status, date, amount, or empty result has been assumed."
);
