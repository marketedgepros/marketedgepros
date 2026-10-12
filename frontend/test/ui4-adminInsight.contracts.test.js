import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import {
  ADMIN_INSIGHT_ENDPOINTS,
  AdminInsightContractError,
  adminInsightPrincipalFromAuth,
  createAdminInsightViewService,
  mapAdminInsight,
} from "../src/services/adminInsightViewService.js";

const owner = { user_id: 9, tenant_id: 7, role: "master" };
const asOf = "2026-10-12T13:00:00Z";
const distribution = (code, count) => [{ code, count }];
const base = (patch = {}) => ({
  owner_context: { user_id: 9, tenant_id: 7 },
  record_verification: "unverified_legacy",
  settlement_enabled: false,
  as_of: asOf,
  filters: { days: null },
  counts: { users: 2, challenges: 1, payments: 1 },
  distributions: {
    user_roles: distribution("master", 2),
    user_kyc: distribution(null, 2),
    challenge_status: distribution("active", 1),
    payment_status: distribution("pending", 1),
  },
  recent_users: [
    { id: 2, role: "master", is_active: true, kyc_status: null, created_at: "2026-10-12T12:00:00Z" },
    { id: 1, role: null, is_active: null, kyc_status: "unverified", created_at: null },
  ],
  recent_payments: [{ id: 3, user_id: 2, amount: "0.00", currency: "EUR", payment_type: "challenge_purchase", status: "pending", created_at: "2026-10-12T11:00:00Z" }],
  daily_activity: [],
  ...patch,
});
const analytics = (patch = {}) => base({
  filters: { days: 7 },
  recent_users: [],
  recent_payments: [],
  daily_activity: [
    { date: "2026-10-06", users: 0, challenges: 0, payments: 0 },
    { date: "2026-10-07", users: 0, challenges: 0, payments: 0 },
    { date: "2026-10-08", users: 0, challenges: 0, payments: 0 },
    { date: "2026-10-09", users: 0, challenges: 0, payments: 0 },
    { date: "2026-10-10", users: 1, challenges: 1, payments: 1 },
    { date: "2026-10-11", users: 0, challenges: 0, payments: 0 },
    { date: "2026-10-12", users: 1, challenges: 0, payments: 0 },
  ],
  ...patch,
});

test("maps the direct dashboard payload strictly while preserving unknown null fields and exact payment strings", () => {
  const view = mapAdminInsight(base(), { expectedOwner: owner, days: null });
  assert.equal(view.kind, "dashboard");
  assert.equal(view.ownerContext.user_id, 9);
  assert.equal(view.distributions.userKyc[0].code, null, "null is the intentional server unknown group");
  assert.equal(view.recentUsers[1].created_at, null);
  assert.equal(view.recentPayments[0].amount, "0.00");
  assert.equal(view.recentPayments[0].currency, "EUR");
  assert.deepEqual(view.dailyActivity, []);
  assert.throws(() => mapAdminInsight(base({ owner_context: { user_id: 10, tenant_id: 7 } }), { expectedOwner: owner, days: null }), AdminInsightContractError);
  assert.throws(() => mapAdminInsight(base({ record_verification: "verified" }), { expectedOwner: owner, days: null }), AdminInsightContractError);
  assert.throws(() => mapAdminInsight(base({ extra_private_data: true }), { expectedOwner: owner, days: null }), AdminInsightContractError);
});

test("rejects malformed, late, duplicate and unallowlisted record data without inventing zeros", () => {
  const invalid = [
    () => mapAdminInsight(base({ recent_users: [{ id: 2, role: "legacy", is_active: true, kyc_status: null, created_at: asOf }, base().recent_users[1]] }), { expectedOwner: owner, days: null }),
    () => mapAdminInsight(base({ recent_payments: [{ ...base().recent_payments[0], amount: 0 }] }), { expectedOwner: owner, days: null }),
    () => mapAdminInsight(base({ recent_payments: [{ ...base().recent_payments[0], created_at: "2026-10-12T13:00:01Z" }] }), { expectedOwner: owner, days: null }),
    () => mapAdminInsight(base({ distributions: { ...base().distributions, payment_status: [{ code: "pending", count: 1 }, { code: "pending", count: 0 }] } }), { expectedOwner: owner, days: null }),
    () => mapAdminInsight(base({ counts: { users: -1, challenges: 1, payments: 1 } }), { expectedOwner: owner, days: null }),
    () => mapAdminInsight(base({ recent_users: [{ ...base().recent_users[0], created_at: "2026-02-30T10:00:00Z" }, base().recent_users[1]] }), { expectedOwner: owner, days: null }),
  ];
  invalid.forEach((normalizer) => assert.throws(normalizer, AdminInsightContractError));
});

test("analytics requires every ordered UTC day, range parity, totals, and an empty recent section", () => {
  const view = mapAdminInsight(analytics(), { expectedOwner: owner, days: 7 });
  assert.equal(view.kind, "analytics");
  assert.equal(view.dailyActivity.length, 7);
  assert.equal(view.dailyActivity[0].date, "2026-10-06");
  assert.equal(view.dailyActivity[6].date, "2026-10-12");
  const invalid = [
    () => mapAdminInsight(analytics({ daily_activity: analytics().daily_activity.slice(1) }), { expectedOwner: owner, days: 7 }),
    () => mapAdminInsight(analytics({ daily_activity: analytics().daily_activity.map((row, index) => index === 4 ? { ...row, date: "2026-10-13" } : row) }), { expectedOwner: owner, days: 7 }),
    () => mapAdminInsight(analytics({ daily_activity: analytics().daily_activity.map((row, index) => index === 6 ? { ...row, users: 2 } : row) }), { expectedOwner: owner, days: 7 }),
    () => mapAdminInsight(analytics({ recent_users: [{ id: 1, role: null, is_active: null, kyc_status: null, created_at: null }] }), { expectedOwner: owner, days: 7 }),
    () => mapAdminInsight(analytics({ filters: { days: 30 } }), { expectedOwner: owner, days: 7 }),
  ];
  invalid.forEach((normalizer) => assert.throws(normalizer, AdminInsightContractError));
});

test("the one-shot service validates request input before transport and sends only canonical endpoints", async () => {
  let calls = 0;
  const service = createAdminInsightViewService({ get: async (path, config) => { calls += 1; return { data: path === ADMIN_INSIGHT_ENDPOINTS.dashboard ? base() : analytics() }; } });
  await assert.rejects(() => service.loadAdminInsight({ kind: "dashboard", expectedOwner: owner, days: 7 }));
  await assert.rejects(() => service.loadAdminInsight({ kind: "analytics", expectedOwner: owner, days: 8 }));
  assert.equal(calls, 0);
  const controller = new AbortController();
  await service.loadAdminInsight({ kind: "dashboard", expectedOwner: owner, days: null, signal: controller.signal });
  await service.loadAdminInsight({ kind: "analytics", expectedOwner: owner, days: 7, signal: controller.signal });
  assert.equal(calls, 2);
  const principalA = adminInsightPrincipalFromAuth({ id: 9, tenant_id: 7, role: "master", first_name: "A" }, true);
  const principalB = adminInsightPrincipalFromAuth({ id: 9, tenant_id: 7, role: "master", first_name: "B" }, true);
  assert.equal(principalA.key, principalB.key, "an auth-store object refresh for the same principal must not change the request key");
  assert.equal(adminInsightPrincipalFromAuth({ id: 9, tenantId: 7, role: "master" }, true), null);
  assert.doesNotMatch(fs.readFileSync(new URL("../src/pages/admin/AdminDashboardConnected.jsx", import.meta.url), "utf8"), /setInterval|setTimeout/);
  assert.doesNotMatch(fs.readFileSync(new URL("../src/pages/admin/AnalyticsDashboard.jsx", import.meta.url), "utf8"), /setInterval|setTimeout/);
});

test("microsecond ordering and as_of comparisons preserve PostgreSQL precision without leaking BigInt", () => {
  const payload = base();
  payload.recent_users = [
    { ...payload.recent_users[0], id: 1, created_at: "2026-10-12T12:00:00.000100Z" },
    { ...payload.recent_users[0], id: 2, created_at: "2026-10-12T12:00:00Z" },
  ];
  const view = mapAdminInsight(payload, { expectedOwner: owner, days: null });
  assert.deepEqual(view.recentUsers.map((row) => row.id), [1, 2]);
  assert.doesNotThrow(() => JSON.stringify(view));
  const reversed = { ...payload, recent_users: [...payload.recent_users].reverse() };
  assert.throws(() => mapAdminInsight(reversed, { expectedOwner: owner, days: null }), AdminInsightContractError);
  const future = base({ recent_payments: [{ ...base().recent_payments[0], created_at: "2026-10-12T13:00:00.000100Z" }] });
  assert.throws(() => mapAdminInsight(future, { expectedOwner: owner, days: null }), AdminInsightContractError);
});
