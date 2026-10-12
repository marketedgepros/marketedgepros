import assert from "node:assert/strict";
import test from "node:test";
import { AxiosError } from "axios";
import api from "../src/services/api.js";
import {
  ADMIN_CLOSURE_CRM_ENDPOINTS,
  AdminClosureCrmContractError,
  adminClosureCrmPrincipalFromAuth,
  buildAdminClosureCrmListParams,
  createAdminClosureCrmService,
  formatAdminClosureCrmBudget,
  normalizeAdminClosureCrmDetail,
  normalizeAdminClosureCrmList,
} from "../src/services/adminClosureCrmService.js";

const owner = { user_id: 9, tenant_id: 4 };
const lead = (patch = {}) => ({
  id: 22,
  first_name: "Ada",
  last_name: "Lead",
  email: "ada@example.invalid",
  phone: null,
  country_code: null,
  status: "new",
  source: "website",
  score: 50,
  assigned_to: 9,
  assigned_user: { id: 9, name: "Admin Owner" },
  interested_program_id: null,
  budget: "10.50",
  company: null,
  job_title: null,
  notes: null,
  tags: [],
  next_follow_up: null,
  converted_at: null,
  lost_reason: null,
  lost_at: null,
  created_at: "2026-10-12T10:00:00",
  updated_at: "2026-10-12T10:00:00",
  ...patch,
});
const list = (rows = [lead()], patch = {}) => ({
  owner_context: owner,
  leads: rows,
  pagination: { page: 1, per_page: 20, total: rows.length, pages: rows.length ? 1 : 0 },
  filters: { status: null, source: null, search: "" },
  ...patch,
});
const detail = (patch = {}) => ({ ...lead(), owner_context: owner, notes_count: 0, activity_count: 0, ...patch });

test("CRM contracts keep exact decimal strings, independently validate owner context, and bind detail ID", () => {
  const params = buildAdminClosureCrmListParams();
  const normalized = normalizeAdminClosureCrmList(list(), { expectedOwner: owner, params });
  assert.equal(normalized.leads[0].budget, "10.50");
  assert.equal(formatAdminClosureCrmBudget("10.50"), "10.50 (currency unavailable)");
  assert.equal(formatAdminClosureCrmBudget(null), "Not specified");
  assert.equal(normalized.ownerContext.user_id, 9);
  assert.equal(normalizeAdminClosureCrmDetail(detail(), { expectedOwner: owner, expectedLeadId: 22 }).lead.id, 22);

  for (const invalid of [
    () => normalizeAdminClosureCrmList(list([lead({ budget: 10.5 })]), { expectedOwner: owner, params }),
    () => normalizeAdminClosureCrmList(list([lead({ budget: "1e3" })]), { expectedOwner: owner, params }),
    () => normalizeAdminClosureCrmList(list([], { owner_context: { user_id: 10, tenant_id: 4 }, pagination: { page: 1, per_page: 20, total: 0, pages: 0 } }), { expectedOwner: owner, params }),
    () => normalizeAdminClosureCrmDetail(detail({ id: 23 }), { expectedOwner: owner, expectedLeadId: 22 }),
    () => normalizeAdminClosureCrmList(list([lead({ assigned_user: null })]), { expectedOwner: owner, params }),
  ]) assert.throws(invalid, AdminClosureCrmContractError);
});

test("CRM query validation happens before transport and principal needs auth/id/tenant/role", async () => {
  let calls = 0;
  const service = createAdminClosureCrmService({
    get: async () => { calls += 1; return { data: list([]) }; },
  });
  for (const options of [{ page: 0 }, { page: 502, perPage: 20 }, { status: "all" }, { source: "manual" }, { search: "x".repeat(101) }]) {
    await assert.rejects(() => service.loadLeads({ expectedOwner: owner, role: "master", ...options }));
  }
  assert.equal(calls, 0);
  assert.equal(adminClosureCrmPrincipalFromAuth({ id: 9, tenantId: 4, role: "master" }, true), null);
  assert.equal(adminClosureCrmPrincipalFromAuth({ id: 9, tenant_id: 4, role: "agent" }, true), null);
  const first = adminClosureCrmPrincipalFromAuth({ id: 9, tenant_id: 4, role: "master", first_name: "A" }, true);
  const second = adminClosureCrmPrincipalFromAuth({ id: 9, tenant_id: 4, role: "master", first_name: "B" }, true);
  assert.equal(first.key, second.key);
});

test("CRM client uses canonical paths, signal, and no 401 refresh/replay for reads and writes", async () => {
  const calls = [];
  const controller = new AbortController();
  const client = {
    get: async (path, config) => { calls.push({ method: "get", path, config }); return { data: path === ADMIN_CLOSURE_CRM_ENDPOINTS.leads ? list() : detail() }; },
    patch: async (path, data, config) => { calls.push({ method: "patch", path, data, config }); return { data: { owner_context: owner, lead: lead({ status: "contacted" }) } }; },
  };
  const service = createAdminClosureCrmService(client);
  await service.loadLeads({ expectedOwner: owner, role: "master", signal: controller.signal });
  await service.updateLead({ expectedOwner: owner, role: "master", leadId: 22, signal: controller.signal, payload: { status: "contacted", expected_updated_at: "2026-10-12T10:00:00" } });
  assert.deepEqual(calls.map((call) => call.path), [ADMIN_CLOSURE_CRM_ENDPOINTS.leads, ADMIN_CLOSURE_CRM_ENDPOINTS.lead(22)]);
  calls.forEach((call) => {
    assert.equal(call.config.signal, controller.signal);
    assert.equal(call.config._skipAuthRefresh, true);
  });
  assert.deepEqual(calls[1].data, { status: "contacted", expected_updated_at: "2026-10-12T10:00:00" });

  const original = api.defaults.adapter;
  const transportCalls = [];
  api.defaults.adapter = async (config) => {
    transportCalls.push(config);
    throw new AxiosError("Synthetic 401", "ERR_BAD_REQUEST", config, {}, { status: 401, data: { error: "Unauthorized" }, headers: {}, config });
  };
  try {
    await assert.rejects(
      createAdminClosureCrmService().loadLeads({ expectedOwner: owner, role: "master", signal: new AbortController().signal }),
      (error) => error.response?.status === 401,
    );
    assert.equal(transportCalls.length, 1);
    assert.equal(transportCalls[0]._skipAuthRefresh, true);
  } finally {
    api.defaults.adapter = original;
  }
});

test("already-aborted CRM requests do not enter Axios-compatible transport", async () => {
  let calls = 0;
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    createAdminClosureCrmService({ get: async () => { calls += 1; return { data: list([]) }; } }).loadLeads({ expectedOwner: owner, role: "master", signal: controller.signal }),
    (error) => error.name === "AbortError",
  );
  assert.equal(calls, 0);
});

test("every CRM mutation forwards its AbortController signal to Axios and disables refresh replay", async () => {
  const calls = [];
  const controller = new AbortController();
  const note = { id: 31, lead_id: 22, content: "Scoped note", created_at: "2026-10-12T10:00:00", created_by: "Admin Owner" };
  const activity = {
    id: 41, lead_id: 22, activity_type: "follow_up", subject: null, description: "Scoped activity", outcome: null,
    scheduled_at: "2026-10-12T11:00:00", completed: false, completed_at: null, created_at: "2026-10-12T10:00:00",
    created_by: { id: 9, name: "Admin Owner" },
  };
  const client = {
    post: async (path, data, config) => {
      calls.push({ method: "post", path, data, config });
      if (path === ADMIN_CLOSURE_CRM_ENDPOINTS.leads) return { data: { owner_context: owner, lead: lead() } };
      if (path === ADMIN_CLOSURE_CRM_ENDPOINTS.notes(22)) return { data: { owner_context: owner, note } };
      if (path === ADMIN_CLOSURE_CRM_ENDPOINTS.activities(22)) return { data: { owner_context: owner, activity } };
      return { data: { owner_context: owner, lead: lead({ status: "converted" }) } };
    },
    patch: async (path, data, config) => {
      calls.push({ method: "patch", path, data, config });
      return { data: { owner_context: owner, lead: lead({ status: "contacted" }) } };
    },
    delete: async (path, config) => {
      calls.push({ method: "delete", path, config });
      return { data: { owner_context: owner, lead_id: 22 } };
    },
  };
  const service = createAdminClosureCrmService(client);
  const base = { expectedOwner: owner, role: "supermaster", leadId: 22, signal: controller.signal };

  await service.createLead({ expectedOwner: owner, role: "master", signal: controller.signal, payload: { first_name: "Ada", last_name: "Lead", email: "ada@example.invalid" } });
  await service.updateLead({ ...base, payload: { status: "contacted", expected_updated_at: "2026-10-12T10:00:00" } });
  await service.addNote({ ...base, content: "Scoped note" });
  await service.addActivity({ ...base, payload: { activity_type: "follow_up", description: "Scoped activity", scheduled_at: "2026-10-12T11:00:00" } });
  await service.markConverted(base);
  await service.deleteLead(base);

  assert.deepEqual(calls.map((call) => [call.method, call.path]), [
    ["post", ADMIN_CLOSURE_CRM_ENDPOINTS.leads],
    ["patch", ADMIN_CLOSURE_CRM_ENDPOINTS.lead(22)],
    ["post", ADMIN_CLOSURE_CRM_ENDPOINTS.notes(22)],
    ["post", ADMIN_CLOSURE_CRM_ENDPOINTS.activities(22)],
    ["post", ADMIN_CLOSURE_CRM_ENDPOINTS.convert(22)],
    ["delete", ADMIN_CLOSURE_CRM_ENDPOINTS.lead(22)],
  ]);
  calls.forEach((call) => {
    assert.equal(call.config.signal, controller.signal);
    assert.equal(call.config._skipAuthRefresh, true);
  });
});
