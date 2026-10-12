import assert from "node:assert/strict";
import test from "node:test";
import {
  ADMIN_PAYMENT_RECORD_ENDPOINTS,
  AdminPaymentRecordContractError,
  adminPaymentPrincipalFromAuth,
  buildAdminPaymentParams,
  buildApprovalRequestParams,
  createAdminPaymentRecordViewService,
  normalizeAdminApprovalRequestsResponse,
  normalizeAdminPaymentsResponse,
} from "../src/services/adminPaymentRecordViewService.js";

const owner = { user_id: 9, tenant_id: 7 };
const flags = {
  owner_context: owner,
  record_verification: "unverified_legacy",
  settlement_enabled: false,
};
const payment = (patch = {}) => ({
  id: 31,
  user_id: 22,
  amount: "0.00",
  currency: "USD",
  payment_type: "challenge_purchase",
  payment_method: "bank_transfer",
  status: "pending",
  created_at: "2026-10-12T10:00:00Z",
  ...patch,
});
const payments = (rows = [payment()], patch = {}) => ({
  ...flags,
  payments: rows,
  pagination: { page: 1, per_page: 20, total: rows.length, pages: rows.length ? 1 : 0 },
  filters: { status: null, type: null },
  ...patch,
});
const approval = (patch = {}) => ({
  id: 41,
  requested_by: 8,
  requested_for: 22,
  challenge_id: null,
  payment_id: 31,
  amount: "0.00",
  payment_type: "cash",
  status: "pending",
  created_at: "2026-10-12T10:00:00Z",
  reviewed_at: null,
  ...patch,
});
const approvals = (rows = [approval()], patch = {}) => ({
  ...flags,
  requests: rows,
  pagination: { page: 1, per_page: 20, total: rows.length, pages: rows.length ? 1 : 0 },
  filters: { status: "pending" },
  ...patch,
});

const paymentParams = buildAdminPaymentParams();
const approvalParams = buildApprovalRequestParams();

test("payment and approval normalizers require exact scalar schemas while preserving an independently scoped actor", () => {
  const paymentView = normalizeAdminPaymentsResponse(payments(), { expectedOwner: owner, params: paymentParams });
  assert.equal(paymentView.ownerContext.user_id, 9);
  assert.equal(paymentView.payments[0].user_id, 22, "admin-scoped rows are not required to belong to the actor");
  assert.equal(paymentView.payments[0].amount, "0.00");
  assert.equal(paymentView.payments[0].currency, "USD");
  assert.equal(paymentView.settlementEnabled, false);

  const approvalView = normalizeAdminApprovalRequestsResponse(approvals(), { expectedOwner: owner, params: approvalParams });
  assert.equal(approvalView.requests[0].amount, "0.00");
  assert.equal("currency" in approvalView.requests[0], false);
  assert.equal(approvalView.filters.status, "pending");

  assert.equal(normalizeAdminApprovalRequestsResponse(approvals([approval({ payment_type: "free" })]), { expectedOwner: owner, params: approvalParams }).requests[0].payment_type, "free");
  const invalid = [
    () => normalizeAdminApprovalRequestsResponse(approvals([approval({ payment_type: "challenge_purchase" })]), { expectedOwner: owner, params: approvalParams }),
    () => normalizeAdminPaymentsResponse(payments({ owner_context: { user_id: 10, tenant_id: 7 } }), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminPaymentsResponse(payments([payment({ amount: 0 })]), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminPaymentsResponse(payments([payment({ amount: "1e3" })]), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminPaymentsResponse(payments([payment({ currency: "usd" })]), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminPaymentsResponse(payments([payment({ status: "legacy_paid" })]), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminPaymentsResponse(payments([payment({ created_at: "2026-02-30T10:00:00Z" })]), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminPaymentsResponse(payments([payment(), payment()]), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminPaymentsResponse(payments([payment({ transaction_id: "private" })]), { expectedOwner: owner, params: paymentParams }),
    () => normalizeAdminApprovalRequestsResponse(approvals([approval({ status: "approved" })]), { expectedOwner: owner, params: approvalParams }),
    () => normalizeAdminApprovalRequestsResponse(approvals([approval({ currency: null })]), { expectedOwner: owner, params: approvalParams }),
  ];
  invalid.forEach((normalizer) => assert.throws(normalizer, AdminPaymentRecordContractError));
});

test("query validation happens before transport and pagination validates a partial or beyond-total page exactly", async () => {
  let calls = 0;
  const service = createAdminPaymentRecordViewService({
    get: async () => {
      calls += 1;
      return { data: payments([]) };
    },
  });
  for (const options of [
    { page: 0 },
    { page: "1" },
    { page: 10001 },
    { perPage: 51 },
    { page: 502, perPage: 20 },
    { status: "all" },
    { type: "cash" },
  ]) {
    await assert.rejects(() => service.loadPayments({ expectedOwner: owner, role: "master", ...options }));
  }
  await assert.rejects(() => service.loadApprovalRequests({ expectedOwner: owner, role: "master" }));
  assert.equal(calls, 0);

  const beyondParams = buildAdminPaymentParams({ page: 2 });
  const beyond = payments([], { pagination: { page: 2, per_page: 20, total: 1, pages: 1 } });
  assert.equal(normalizeAdminPaymentsResponse(beyond, { expectedOwner: owner, params: beyondParams }).payments.length, 0);
  assert.throws(
    () => normalizeAdminPaymentsResponse(payments([], { pagination: { page: 1, per_page: 20, total: 1, pages: 1 } }), { expectedOwner: owner, params: paymentParams }),
    AdminPaymentRecordContractError,
  );
});

test("factory methods use only the two canonical GET endpoints with validated params, signal, and refresh bypass", async () => {
  const calls = [];
  const controller = new AbortController();
  const client = {
    get: async (path, config) => {
      calls.push({ path, config });
      return { data: path === ADMIN_PAYMENT_RECORD_ENDPOINTS.payments ? payments() : approvals() };
    },
  };
  const service = createAdminPaymentRecordViewService(client);
  await service.loadPayments({
    expectedOwner: owner,
    role: "master",
    page: 1,
    status: null,
    type: null,
    signal: controller.signal,
  });
  await service.loadApprovalRequests({ expectedOwner: owner, role: "supermaster", signal: controller.signal });
  assert.deepEqual(calls.map((call) => call.path), [
    ADMIN_PAYMENT_RECORD_ENDPOINTS.payments,
    ADMIN_PAYMENT_RECORD_ENDPOINTS.approvalRequests,
  ]);
  assert.deepEqual(calls[0].config.params, { page: 1, per_page: 20 });
  assert.deepEqual(calls[1].config.params, { page: 1, per_page: 20 });
  calls.forEach((call) => {
    assert.equal(call.config.signal, controller.signal);
    assert.equal(call.config._skipAuthRefresh, true);
  });
});

test("principal identity needs auth/id/tenant/role and rejects aliases while remaining stable across fresh user objects", () => {
  assert.equal(adminPaymentPrincipalFromAuth({ id: 9, tenantId: 7, role: "master" }, true), null);
  assert.equal(adminPaymentPrincipalFromAuth({ id: 9, tenant_id: 7, role: "admin" }, true), null);
  const first = adminPaymentPrincipalFromAuth({ id: 9, tenant_id: 7, role: "master", first_name: "First" }, true);
  const second = adminPaymentPrincipalFromAuth({ id: 9, tenant_id: 7, role: "master", first_name: "Second" }, true);
  assert.equal(first.key, second.key);
});
