import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { AxiosError } from "axios";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import api from "../src/services/api.js";
import {
  ADMIN_CLOSURE_USERS_ENDPOINTS,
  AdminClosureUsersContractError,
  adminClosureUsersPrincipalFromAuth,
  createAdminClosureUsersService,
  normalizeAdminClosureUserDetails,
  normalizeAdminClosureUsersList,
} from "../src/services/adminClosureUsersService.js";

const owner = { user_id: 2, tenant_id: 1, role: "master" };
const listRow = (patch = {}) => ({
  id: 3, first_name: "Trader", last_name: "Three", email: "trader@example.invalid", role: "trader",
  is_active: true, kyc_status: "not_submitted", created_at: "2026-10-12T12:00:00Z", last_login_at: null,
  ...patch,
});
const listPayload = (patch = {}) => ({
  owner_context: { user_id: 2, tenant_id: 1 },
  users: [listRow()],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  filters: { role: null, status: null, search: null },
  ...patch,
});
const detailsPayload = (patch = {}) => ({
  owner_context: { user_id: 2, tenant_id: 1 }, record_verification: "unverified_legacy", settlement_enabled: false,
  user: {
    ...listRow(), phone: null, country_code: null, is_verified: true, two_factor_enabled: false,
    updated_at: "2026-10-12T12:00:00Z",
  },
  downline: { items: [], truncated: false },
  challenges: { items: [{ id: 11, program_name: "Program", status: "active", initial_balance: "1000.00", current_balance: "999.50", total_profit: "-0.50", created_at: "2026-10-12T12:00:00Z" }], truncated: false },
  payments: { items: [{ id: 12, amount: "0.00", currency: "EUR", status: "completed", payment_type: "challenge_purchase", created_at: "2026-10-12T12:00:00Z" }], truncated: false },
  ...patch,
});
const writePayload = (action) => ({ owner_context: { user_id: 2, tenant_id: 1 }, action, message: "Confirmed by server.", user: { id: 3, role: "trader", is_active: true } });

const pageFile = new URL("../src/pages/admin/UserManagementConnected.jsx", import.meta.url);
const pageTarget = new URL(`../node_modules/.ui4-closure-users-${process.pid}.mjs`, import.meta.url);
let page;
try {
  let source = fs.readFileSync(pageFile, "utf8");
  const absolute = (relative) => new URL(relative, import.meta.url).href;
  for (const [from, to] of [
    ["../../store/authStore.js", absolute("../src/store/authStore.js")],
    ["../../constants/roles.js", absolute("../src/constants/roles.js")],
    ["../../services/adminClosureUsersService.js", absolute("../src/services/adminClosureUsersService.js")],
    ["../../hooks/useAdminClosureUsers.js", absolute("../src/hooks/useAdminClosureUsers.js")],
    ["../../hooks/useDialogFocus.js", absolute("../src/hooks/useDialogFocus.js")],
  ]) source = source.replaceAll(`"${from}"`, JSON.stringify(to));
  const transformed = await transformWithEsbuild(source, pageFile.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(pageTarget, transformed.code);
  page = await import(`${pageTarget.href}?test=${process.pid}`);
} finally { fs.rmSync(pageTarget, { force: true }); }

test("users list and details normalizers preserve exact decimals/nulls and reject owner or private-field drift", () => {
  const listed = normalizeAdminClosureUsersList(listPayload(), { expectedOwner: owner, params: { page: 1, per_page: 20 } });
  assert.equal(listed.ownerContext.user_id, 2);
  assert.equal(listed.users[0].last_login_at, null);
  const details = normalizeAdminClosureUserDetails(detailsPayload(), { expectedOwner: owner });
  assert.equal(details.challenges.items[0].initial_balance, "1000.00");
  assert.equal(details.challenges.items[0].total_profit, "-0.50");
  assert.equal(details.payments.items[0].amount, "0.00");
  assert.equal(details.payments.items[0].currency, "EUR");
  for (const mutate of [
    () => normalizeAdminClosureUsersList(listPayload({ owner_context: { user_id: 9, tenant_id: 1 } }), { expectedOwner: owner, params: { page: 1, per_page: 20 } }),
    () => normalizeAdminClosureUsersList(listPayload({ users: [listRow({ password_hash: "no" })] }), { expectedOwner: owner, params: { page: 1, per_page: 20 } }),
    () => normalizeAdminClosureUserDetails(detailsPayload({ payments: { items: [{ ...detailsPayload().payments.items[0], amount: 0 }], truncated: false } }), { expectedOwner: owner }),
    () => normalizeAdminClosureUserDetails(detailsPayload({ payments: { items: [{ ...detailsPayload().payments.items[0], transaction_id: "private" }], truncated: false } }), { expectedOwner: owner }),
  ]) assert.throws(mutate, AdminClosureUsersContractError);
});

test("one-shot service validates before transport and sends canonical read/write endpoints with signal and refresh bypass", async () => {
  const calls = [];
  const client = {
    get: async (path, config) => { calls.push({ method: "get", path, config }); return { data: path === ADMIN_CLOSURE_USERS_ENDPOINTS.users ? listPayload() : detailsPayload() }; },
    post: async (path, body, config) => { calls.push({ method: "post", path, body, config }); return { data: writePayload(path.includes("reset-password") ? "password_reset" : "created") }; },
    put: async (path, body, config) => { calls.push({ method: "put", path, body, config }); return { data: writePayload("updated") }; },
    delete: async (path, config) => { calls.push({ method: "delete", path, config }); return { data: writePayload("deactivated") }; },
  };
  const controller = new AbortController();
  const service = createAdminClosureUsersService(client);
  await service.loadUsers({ expectedOwner: owner, page: 1, signal: controller.signal });
  await service.loadDetails({ expectedOwner: owner, userId: 3, signal: controller.signal });
  await service.createUser({ expectedOwner: owner, values: { first_name: "New", last_name: "User", email: "new@example.invalid", password: "StrongValue42!", phone: null, country_code: null, role: "trader" }, signal: controller.signal });
  await service.updateUser({ expectedOwner: owner, userId: 3, values: { first_name: "Trader", last_name: "Three", phone: null, country_code: null, role: "trader", is_active: true }, signal: controller.signal });
  await service.deactivateUser({ expectedOwner: owner, userId: 3, signal: controller.signal });
  await service.resetPassword({ expectedOwner: owner, userId: 3, newPassword: "NextValue42!", signal: controller.signal });
  assert.deepEqual(calls.map((call) => call.path), ["/admin/users", "/admin/users/3/full-details", "/admin/users", "/admin/users/3", "/admin/users/3", "/admin/users/3/reset-password"]);
  calls.forEach((call) => { assert.equal(call.config.signal, controller.signal); assert.equal(call.config._skipAuthRefresh, true); });
  const before = calls.length;
  await assert.rejects(() => service.loadUsers({ expectedOwner: owner, page: 0 }));
  await assert.rejects(() => service.createUser({ expectedOwner: owner, values: { first_name: "A" } }));
  assert.equal(calls.length, before);
  assert.equal(adminClosureUsersPrincipalFromAuth({ id: 2, tenant_id: 1, role: "master" }, true)?.key, adminClosureUsersPrincipalFromAuth({ id: 2, tenant_id: 1, role: "master", first_name: "Fresh" }, true)?.key);
});

test("actual Axios requests never replay a users 401 and an already aborted read never enters transport", async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, skip: config._skipAuthRefresh, signal: config.signal });
    throw new AxiosError("Synthetic unauthorized", "ERR_BAD_REQUEST", config, {}, { status: 401, data: { error: "Unauthorized" }, headers: {}, config });
  };
  try {
    const service = createAdminClosureUsersService();
    const controller = new AbortController();
    await assert.rejects(() => service.loadUsers({ expectedOwner: owner, signal: controller.signal }), (error) => error.response?.status === 401);
    assert.deepEqual(calls.map((call) => [call.url, call.method, call.skip]), [["/admin/users", "get", true]]);
    controller.abort();
    await assert.rejects(() => service.loadDetails({ expectedOwner: owner, userId: 3, signal: controller.signal }), (error) => error.name === "AbortError" || error.code === "ERR_CANCELED");
    assert.equal(calls.length, 1);
  } finally { api.defaults.adapter = original; }
});

test("actual users React content has accessible states, scoped page labels, no dollar inference, and scroll-safe table", () => {
  const read = { value: { users: [listRow()], pagination: { page: 1, per_page: 20, total: 1, pages: 1 } }, loading: false, error: null, refresh: () => {} };
  const html = renderToStaticMarkup(React.createElement(page.AdminClosureUsersContent, {
    read, viewMode: "table", filters: { role: null, status: null, search: "" }, onFilter: () => {}, onPage: () => {}, onViewMode: () => {}, onView: () => {}, onEdit: () => {}, onDeactivate: () => {}, onCreate: () => {}, canCreate: true, canEdit: true,
  }));
  assert.match(html, /User management/);
  assert.match(html, /On this page only/);
  assert.match(html, /overflow-x-auto/);
  assert.match(html, /Server-scoped users/);
  assert.doesNotMatch(html, /\$|Delete User|Active affiliates/);
  const loading = renderToStaticMarkup(React.createElement(page.AdminClosureUsersContent, {
    read: { value: null, loading: true, error: null, refresh: () => {} }, viewMode: "table", filters: { role: null, status: null, search: "" }, onFilter: () => {}, onPage: () => {}, onViewMode: () => {}, onView: () => {}, onEdit: () => {}, onDeactivate: () => {}, onCreate: () => {}, canCreate: false, canEdit: false,
  }));
  assert.match(loading, /role="status"/);
  assert.match(loading, /aria-busy="true"/);
  assert.doesNotMatch(fs.readFileSync(pageFile, "utf8"), /setInterval|setTimeout/);
});
