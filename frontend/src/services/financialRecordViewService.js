import api from "./api.js";
import { ADMIN_ROLES, ALL_ROLES, ROLES } from "../constants/roles.js";
import { recordedTimestampOrNull } from "./userDashboardViewService.js";

export const FINANCIAL_RECORD_ENDPOINTS = Object.freeze({
  balance: "/wallet/balance",
  transactions: "/wallet/transactions",
  withdrawals: "/traders/withdrawals",
  adminWithdrawals: "/wallet/admin/withdrawals",
});
export const FINANCIAL_RECORD_PAGE_LIMIT = 10000;
export const FINANCIAL_RECORD_PER_PAGE_LIMIT = 50;
export const FINANCIAL_RECORD_PAGE_SIZE = 20;
export const FINANCIAL_RECORD_OFFSET_LIMIT = 10000;
export const FINANCIAL_BALANCE_TYPES = Object.freeze([
  "main",
  "commission",
  "bonus",
]);
export const FINANCIAL_WITHDRAWAL_STATUSES = Object.freeze([
  "pending",
  "approved",
  "processing",
  "completed",
  "rejected",
]);

const ID_LIMIT = 2147483647;
const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const CODE = /^[a-z][a-z0-9_-]{0,63}$/;
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

export class FinancialRecordContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "FinancialRecordContractError";
  }
}

export class FinancialWalletNotFoundError extends Error {
  constructor() {
    super("The wallet was not found in the unverified legacy source.");
    this.name = "FinancialWalletNotFoundError";
    this.code = "WALLET_NOT_FOUND";
  }
}

const fail = (message) => {
  throw new FinancialRecordContractError(message);
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
  if (
    actual.length !== fields.length ||
    fields.some((field) => !hasOwn(record, field))
  ) {
    fail(`${label} contains fields outside the financial record contract.`);
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
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 128 ||
    !DECIMAL.test(value)
  ) {
    fail(`${label} must be an exact finite decimal string or null.`);
  }
  return value;
};
const requireTimestampOrNull = (value, label) => {
  if (value === null) return null;
  const timestamp = recordedTimestampOrNull(value);
  if (timestamp === null)
    fail(`${label} must be a complete ISO timestamp or null.`);
  return timestamp;
};
const requireCodeOrNull = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || !CODE.test(value)) {
    fail(`${label} must be a bounded machine-readable code or null.`);
  }
  return value;
};
const requireCode = (value, label) => {
  const code = requireCodeOrNull(value, label);
  if (code === null) fail(`${label} must be a bounded machine-readable code.`);
  return code;
};
const requireBooleanOrNull = (value, label) => {
  if (value !== null && typeof value !== "boolean")
    fail(`${label} must be boolean or null.`);
  return value;
};

/** Caller identity is independently sourced from the authenticated store, never a response. */
export const normaliseFinancialExpectedOwner = (expectedOwner) => {
  const source = requireExactFields(
    expectedOwner,
    ["user_id", "tenant_id"],
    "Expected financial owner",
  );
  return {
    user_id: requirePositiveId(
      source.user_id,
      "Expected financial owner user ID",
    ),
    tenant_id: requirePositiveId(
      source.tenant_id,
      "Expected financial owner tenant ID",
    ),
  };
};
export const normalizeFinancialExpectedOwner = normaliseFinancialExpectedOwner;

export const financialIdentityKey = ({
  isAuthenticated,
  userId,
  tenantId,
  role,
}) =>
  JSON.stringify([
    isAuthenticated === true,
    userId ?? null,
    tenantId ?? null,
    role ?? null,
  ]);

/** No tenant aliases are accepted here: only the authenticated store's tenant_id is authoritative. */
export const financialPrincipalFromAuth = (user, isAuthenticated) => {
  try {
    if (isAuthenticated !== true || !ALL_ROLES.includes(user?.role))
      return null;
    const owner = normaliseFinancialExpectedOwner({
      user_id: user?.id,
      tenant_id: user?.tenant_id,
    });
    return {
      owner,
      role: user.role,
      key: financialIdentityKey({
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

const requireWalletRole = (role) => {
  if (!ALL_ROLES.includes(role) || ADMIN_ROLES.includes(role)) {
    fail("Wallet records require an authenticated non-admin role.");
  }
  return role;
};
const requireTraderRole = (role) => {
  if (role !== ROLES.TRADER)
    fail("Withdrawal records require the trader role.");
  return role;
};
const requireAdminRole = (role) => {
  if (!ADMIN_ROLES.includes(role))
    fail("Administrative withdrawal records require an existing admin role.");
  return role;
};

/** Validate every query option before a GET is attempted. */
export const buildFinancialRecordParams = ({
  page = 1,
  perPage = FINANCIAL_RECORD_PAGE_SIZE,
  balanceType = null,
  status = null,
} = {}) => {
  if (
    !Number.isSafeInteger(page) ||
    page < 1 ||
    page > FINANCIAL_RECORD_PAGE_LIMIT
  ) {
    fail(
      `Financial record page must be between 1 and ${FINANCIAL_RECORD_PAGE_LIMIT}.`,
    );
  }
  if (
    !Number.isSafeInteger(perPage) ||
    perPage < 1 ||
    perPage > FINANCIAL_RECORD_PER_PAGE_LIMIT
  ) {
    fail(
      `Financial record page size must be between 1 and ${FINANCIAL_RECORD_PER_PAGE_LIMIT}.`,
    );
  }
  if ((page - 1) * perPage > FINANCIAL_RECORD_OFFSET_LIMIT) {
    fail(
      `Financial record offset must not exceed ${FINANCIAL_RECORD_OFFSET_LIMIT}.`,
    );
  }
  if (balanceType !== null && !FINANCIAL_BALANCE_TYPES.includes(balanceType)) {
    fail("Financial record balance type filter is unsupported.");
  }
  if (status !== null && !FINANCIAL_WITHDRAWAL_STATUSES.includes(status)) {
    fail("Financial record status filter is unsupported.");
  }
  if (balanceType !== null && status !== null) {
    fail(
      "A financial record request may use only its endpoint-specific filter.",
    );
  }
  return {
    page,
    per_page: perPage,
    ...(balanceType === null ? {} : { balance_type: balanceType }),
    ...(status === null ? {} : { status }),
  };
};

export const canRequestFinancialPage = (
  page,
  perPage = FINANCIAL_RECORD_PAGE_SIZE,
) => {
  try {
    buildFinancialRecordParams({ page, perPage });
    return true;
  } catch {
    return false;
  }
};

const normalizeOwnerContext = (value, expectedOwner) => {
  const source = requireExactFields(
    value,
    ["user_id", "tenant_id"],
    "Financial record owner context",
  );
  const owner = {
    user_id: requirePositiveId(
      source.user_id,
      "Financial record owner user ID",
    ),
    tenant_id: requirePositiveId(
      source.tenant_id,
      "Financial record owner tenant ID",
    ),
  };
  if (
    owner.user_id !== expectedOwner.user_id ||
    owner.tenant_id !== expectedOwner.tenant_id
  ) {
    fail("Financial record owner context does not match the active account.");
  }
  return owner;
};

const normalizeBoundary = (source) => {
  if (
    source.balance_verification !== "unverified_legacy" ||
    source.payouts_enabled !== false ||
    source.available_for_payout !== null ||
    source.currency !== null
  ) {
    fail("Financial record verification or payout boundary is invalid.");
  }
  return {
    balanceVerification: "unverified_legacy",
    payoutsEnabled: false,
    availableForPayout: null,
    currency: null,
  };
};

const normalizePagination = (value, params, rowCount) => {
  const source = requireExactFields(
    value,
    ["page", "per_page", "total", "pages"],
    "Financial record pagination",
  );
  const page = source.page;
  const perPage = source.per_page;
  const total = requireNonNegativeCount(
    source.total,
    "Financial record pagination total",
  );
  const pages = requireNonNegativeCount(
    source.pages,
    "Financial record pagination pages",
  );
  if (page !== params.page || perPage !== params.per_page) {
    fail("Financial record pagination does not match the requested page.");
  }
  if (
    !Number.isSafeInteger(page) ||
    page < 1 ||
    page > FINANCIAL_RECORD_PAGE_LIMIT ||
    !Number.isSafeInteger(perPage) ||
    perPage < 1 ||
    perPage > FINANCIAL_RECORD_PER_PAGE_LIMIT ||
    (page - 1) * perPage > FINANCIAL_RECORD_OFFSET_LIMIT ||
    pages !== Math.ceil(total / perPage)
  ) {
    fail("Financial record pagination is mathematically inconsistent.");
  }
  const expectedRows = Math.min(
    perPage,
    Math.max(0, total - (page - 1) * perPage),
  );
  if (rowCount !== expectedRows) {
    fail("Financial record page does not match its server pagination total.");
  }
  return { page, per_page: perPage, total, pages };
};

const normalizeWallet = (value, expectedOwner) => {
  const source = requireExactFields(
    value,
    [
      "id",
      "user_id",
      "main_balance",
      "commission_balance",
      "bonus_balance",
      "is_active",
      "last_transaction_at",
      "created_at",
    ],
    "Wallet",
  );
  const userId = requirePositiveId(source.user_id, "Wallet user ID");
  if (userId !== expectedOwner.user_id)
    fail("Wallet user ID does not match the active account.");
  return {
    id: requirePositiveId(source.id, "Wallet ID"),
    user_id: userId,
    main_balance: requireDecimalOrNull(
      source.main_balance,
      "Wallet main balance",
    ),
    commission_balance: requireDecimalOrNull(
      source.commission_balance,
      "Wallet commission balance",
    ),
    bonus_balance: requireDecimalOrNull(
      source.bonus_balance,
      "Wallet bonus balance",
    ),
    is_active: requireBooleanOrNull(source.is_active, "Wallet active status"),
    last_transaction_at: requireTimestampOrNull(
      source.last_transaction_at,
      "Wallet last transaction timestamp",
    ),
    created_at: requireTimestampOrNull(
      source.created_at,
      "Wallet creation timestamp",
    ),
  };
};

export const normalizeFinancialBalanceResponse = (
  payload,
  { expectedOwner } = {},
) => {
  const owner = normaliseFinancialExpectedOwner(expectedOwner);
  const source = requireExactFields(
    payload,
    [
      "owner_context",
      "balance_verification",
      "payouts_enabled",
      "available_for_payout",
      "currency",
      "wallet",
    ],
    "Financial balance response",
  );
  return {
    kind: "balance",
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    ...normalizeBoundary(source),
    wallet: normalizeWallet(source.wallet, owner),
  };
};

const normalizeTransaction = (value, walletId) => {
  const source = requireExactFields(
    value,
    [
      "id",
      "wallet_id",
      "type",
      "balance_type",
      "amount",
      "balance_before",
      "balance_after",
      "created_at",
    ],
    "Wallet transaction",
  );
  const rowWalletId = requirePositiveId(
    source.wallet_id,
    "Wallet transaction wallet ID",
  );
  if (rowWalletId !== walletId)
    fail("Wallet transaction belongs to another wallet.");
  if (!FINANCIAL_BALANCE_TYPES.includes(source.balance_type)) {
    fail("Wallet transaction balance type is unsupported.");
  }
  return {
    id: requirePositiveId(source.id, "Wallet transaction ID"),
    wallet_id: rowWalletId,
    type: requireCode(source.type, "Wallet transaction type"),
    balance_type: source.balance_type,
    amount: requireDecimalOrNull(source.amount, "Wallet transaction amount"),
    balance_before: requireDecimalOrNull(
      source.balance_before,
      "Wallet transaction balance before",
    ),
    balance_after: requireDecimalOrNull(
      source.balance_after,
      "Wallet transaction balance after",
    ),
    created_at: requireTimestampOrNull(
      source.created_at,
      "Wallet transaction timestamp",
    ),
  };
};

export const normalizeFinancialTransactionsResponse = (
  payload,
  { expectedOwner, params } = {},
) => {
  const owner = normaliseFinancialExpectedOwner(expectedOwner);
  const requiredParams = buildFinancialRecordParams({
    page: params?.page,
    perPage: params?.per_page,
    balanceType: hasOwn(params || {}, "balance_type")
      ? params.balance_type
      : null,
  });
  const source = requireExactFields(
    payload,
    [
      "owner_context",
      "balance_verification",
      "payouts_enabled",
      "available_for_payout",
      "currency",
      "wallet_id",
      "transactions",
      "pagination",
      "filters",
    ],
    "Financial transactions response",
  );
  const walletId = requirePositiveId(
    source.wallet_id,
    "Financial transactions wallet ID",
  );
  const rawRows = requireArray(source.transactions, "Financial transactions");
  const transactions = rawRows.map((row) =>
    normalizeTransaction(row, walletId),
  );
  const pagination = normalizePagination(
    source.pagination,
    requiredParams,
    transactions.length,
  );
  const ids = new Set(transactions.map((row) => row.id));
  if (ids.size !== transactions.length)
    fail("Financial transactions contain duplicate identifiers.");
  if (
    requiredParams.balance_type !== undefined &&
    transactions.some((row) => row.balance_type !== requiredParams.balance_type)
  ) {
    fail("Financial transaction rows do not match the requested balance type.");
  }
  const filters = requireExactFields(
    source.filters,
    ["balance_type"],
    "Financial transaction filters",
  );
  if (
    filters.balance_type !== null &&
    !FINANCIAL_BALANCE_TYPES.includes(filters.balance_type)
  ) {
    fail(
      "Financial transaction response contains an unsupported balance type filter.",
    );
  }
  if (filters.balance_type !== (requiredParams.balance_type ?? null)) {
    fail("Financial transaction filters do not echo the request.");
  }
  return {
    kind: "transactions",
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    ...normalizeBoundary(source),
    wallet_id: walletId,
    transactions,
    pagination,
    filters: { balance_type: filters.balance_type },
  };
};

const normalizeWithdrawal = (value, expectedOwner, isAdminScope) => {
  const source = requireExactFields(
    value,
    [
      "id",
      "user_id",
      "amount",
      "fee",
      "net_amount",
      "payment_method",
      "status",
      "created_at",
      "approved_at",
      "processed_at",
      "completed_at",
    ],
    "Withdrawal record",
  );
  const userId = requirePositiveId(source.user_id, "Withdrawal user ID");
  if (!isAdminScope && userId !== expectedOwner.user_id) {
    fail("Withdrawal record belongs to another account.");
  }
  if (!FINANCIAL_WITHDRAWAL_STATUSES.includes(source.status)) {
    fail("Withdrawal status is unsupported.");
  }
  return {
    id: requirePositiveId(source.id, "Withdrawal ID"),
    user_id: userId,
    amount: requireDecimalOrNull(source.amount, "Withdrawal amount"),
    fee: requireDecimalOrNull(source.fee, "Withdrawal fee"),
    net_amount: requireDecimalOrNull(
      source.net_amount,
      "Withdrawal net amount",
    ),
    payment_method: requireCodeOrNull(
      source.payment_method,
      "Withdrawal payment method",
    ),
    status: source.status,
    created_at: requireTimestampOrNull(
      source.created_at,
      "Withdrawal creation timestamp",
    ),
    approved_at: requireTimestampOrNull(
      source.approved_at,
      "Withdrawal approval timestamp",
    ),
    processed_at: requireTimestampOrNull(
      source.processed_at,
      "Withdrawal processing timestamp",
    ),
    completed_at: requireTimestampOrNull(
      source.completed_at,
      "Withdrawal completion timestamp",
    ),
  };
};

export const normalizeFinancialWithdrawalsResponse = (
  payload,
  { expectedOwner, params, isAdminScope } = {},
) => {
  if (typeof isAdminScope !== "boolean")
    fail("Withdrawal scope must be specified by the caller.");
  const owner = normaliseFinancialExpectedOwner(expectedOwner);
  const requiredParams = buildFinancialRecordParams({
    page: params?.page,
    perPage: params?.per_page,
    status: hasOwn(params || {}, "status") ? params.status : null,
  });
  const source = requireExactFields(
    payload,
    [
      "owner_context",
      "balance_verification",
      "payouts_enabled",
      "available_for_payout",
      "currency",
      "withdrawals",
      "pagination",
      "filters",
    ],
    "Financial withdrawals response",
  );
  const rawRows = requireArray(source.withdrawals, "Financial withdrawals");
  const withdrawals = rawRows.map((row) =>
    normalizeWithdrawal(row, owner, isAdminScope),
  );
  const pagination = normalizePagination(
    source.pagination,
    requiredParams,
    withdrawals.length,
  );
  const ids = new Set(withdrawals.map((row) => row.id));
  if (ids.size !== withdrawals.length)
    fail("Financial withdrawals contain duplicate identifiers.");
  if (
    requiredParams.status !== undefined &&
    withdrawals.some((row) => row.status !== requiredParams.status)
  ) {
    fail("Financial withdrawal rows do not match the requested status.");
  }
  const filters = requireExactFields(
    source.filters,
    ["status"],
    "Financial withdrawal filters",
  );
  if (
    filters.status !== null &&
    !FINANCIAL_WITHDRAWAL_STATUSES.includes(filters.status)
  ) {
    fail(
      "Financial withdrawal response contains an unsupported status filter.",
    );
  }
  if (filters.status !== (requiredParams.status ?? null)) {
    fail("Financial withdrawal filters do not echo the request.");
  }
  return {
    kind: isAdminScope ? "admin-withdrawals" : "withdrawals",
    ownerContext: normalizeOwnerContext(source.owner_context, owner),
    ...normalizeBoundary(source),
    withdrawals,
    pagination,
    filters: { status: filters.status },
  };
};

const walletMissingFromError = (error) => {
  const data = error?.response?.data;
  if (error?.response?.status !== 404 || !isRecord(data)) return false;
  const allowed = ["error", "code", "reason"];
  const actual = Object.keys(data);
  return (
    actual.length === allowed.length &&
    allowed.every((field) => hasOwn(data, field)) &&
    data.code === "WALLET_NOT_FOUND" &&
    data.reason === "unverified_legacy" &&
    typeof data.error === "string" &&
    data.error.length > 0 &&
    data.error.length <= 160
  );
};

const abortError = () => {
  const error = new Error("Financial record request was cancelled.");
  error.name = "AbortError";
  return error;
};
const throwIfAborted = (signal) => {
  if (signal?.aborted) throw abortError();
};

/** Axios-compatible, injectable, one-shot GET service. It never polls or retries. */
export const createFinancialRecordViewService = (client = api) => {
  const loadBalance = async ({ expectedOwner, role, signal } = {}) => {
    const owner = normaliseFinancialExpectedOwner(expectedOwner);
    requireWalletRole(role);
    throwIfAborted(signal);
    try {
      const response = await client.get(FINANCIAL_RECORD_ENDPOINTS.balance, {
        signal,
        _skipAuthRefresh: true,
      });
      throwIfAborted(signal);
      return normalizeFinancialBalanceResponse(response?.data, {
        expectedOwner: owner,
      });
    } catch (error) {
      if (walletMissingFromError(error))
        throw new FinancialWalletNotFoundError();
      throw error;
    }
  };
  const loadTransactions = async ({
    expectedOwner,
    role,
    signal,
    ...options
  } = {}) => {
    const owner = normaliseFinancialExpectedOwner(expectedOwner);
    requireWalletRole(role);
    const params = buildFinancialRecordParams(options);
    throwIfAborted(signal);
    try {
      const response = await client.get(
        FINANCIAL_RECORD_ENDPOINTS.transactions,
        { params, signal, _skipAuthRefresh: true },
      );
      throwIfAborted(signal);
      return normalizeFinancialTransactionsResponse(response?.data, {
        expectedOwner: owner,
        params,
      });
    } catch (error) {
      if (walletMissingFromError(error))
        throw new FinancialWalletNotFoundError();
      throw error;
    }
  };
  const loadWithdrawals = async ({
    expectedOwner,
    role,
    signal,
    isAdminScope = false,
    ...options
  } = {}) => {
    const owner = normaliseFinancialExpectedOwner(expectedOwner);
    if (typeof isAdminScope !== "boolean")
      fail("Withdrawal scope must be specified by the caller.");
    if (isAdminScope) requireAdminRole(role);
    else requireTraderRole(role);
    const params = buildFinancialRecordParams(options);
    throwIfAborted(signal);
    const response = await client.get(
      isAdminScope
        ? FINANCIAL_RECORD_ENDPOINTS.adminWithdrawals
        : FINANCIAL_RECORD_ENDPOINTS.withdrawals,
      { params, signal, _skipAuthRefresh: true },
    );
    throwIfAborted(signal);
    return normalizeFinancialWithdrawalsResponse(response?.data, {
      expectedOwner: owner,
      params,
      isAdminScope,
    });
  };
  return {
    balance: loadBalance,
    transactions: loadTransactions,
    withdrawals: loadWithdrawals,
    selfWithdrawals: (options = {}) =>
      loadWithdrawals({ ...options, isAdminScope: false }),
    adminWithdrawals: (options = {}) =>
      loadWithdrawals({ ...options, isAdminScope: true }),
    async wallet(options = {}) {
      try {
        const [balance, transactions] = await Promise.all([
          loadBalance(options),
          loadTransactions(options),
        ]);
        if (transactions.wallet_id !== balance.wallet.id) {
          fail("Wallet transaction page does not match the active wallet.");
        }
        return { kind: "wallet", balance, transactions };
      } catch (error) {
        if (error instanceof FinancialWalletNotFoundError)
          return { kind: "wallet-missing" };
        throw error;
      }
    },
  };
};

export const isFinancialRecordRequestCanceled = (error) =>
  error?.name === "AbortError" || error?.code === "ERR_CANCELED";
export const financialRecordError = () =>
  "The service is unavailable or its response could not be validated. No balance, payment availability, or empty result has been assumed.";
