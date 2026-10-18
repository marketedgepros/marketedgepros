import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import { AxiosError } from "axios";
import api from "../src/services/api.js";
import {
  ADMIN_CLOSURE_SETTINGS_ENDPOINT,
  ADMIN_CLOSURE_SETTINGS_REQUEST_TIMEOUT_MS,
  AdminClosureSettingsContractError,
  createAdminClosureSettingsService,
  mapAdminClosureSettings,
} from "../src/services/adminClosureSettingsService.js";

const owner = { user_id: 1, tenant_id: 7, role: "supermaster" };
const payload = (patch = {}) => ({
  owner_context: { user_id: 1, tenant_id: 7 },
  scope: { kind: "tenant", tenant_id: 7 },
  tenant_settings: { name: "Recorded tenant", contact_email: null, contact_phone: "+10000000000" },
  capabilities: {
    tenant_contact: "persisted",
    global_system: "unavailable_no_persistence",
    payment_providers: "unavailable_no_persistence",
  },
  ...patch,
});
const axiosResponse = (config, data) => ({ data, status: 200, statusText: "OK", headers: {}, config, request: {} });

test("strict settings mapping accepts only owner-bound tenant acknowledgements and preserves nulls", () => {
  const view = mapAdminClosureSettings(payload(), { expectedOwner: owner });
  assert.equal(view.ownerContext.user_id, 1);
  assert.equal(view.scope.tenantId, 7);
  assert.equal(view.tenantSettings.contact_email, null);
  assert.equal(view.capabilities.globalSystem, "unavailable_no_persistence");
  [
    () => mapAdminClosureSettings(payload({ owner_context: { user_id: 2, tenant_id: 7 } }), { expectedOwner: owner }),
    () => mapAdminClosureSettings(payload({ scope: { kind: "global", tenant_id: 7 } }), { expectedOwner: owner }),
    () => mapAdminClosureSettings(payload({ tenant_settings: { ...payload().tenant_settings, injected: true } }), { expectedOwner: owner }),
    () => mapAdminClosureSettings(payload({ capabilities: { ...payload().capabilities, payment_providers: "configured" } }), { expectedOwner: owner }),
    () => mapAdminClosureSettings(payload(), { expectedOwner: { ...owner, role: "master" } }),
  ].forEach((mapper) => assert.throws(mapper, AdminClosureSettingsContractError));
});

test("save refuses malformed requests and mismatched acknowledgements before success", async () => {
  let calls = 0;
  const service = createAdminClosureSettingsService({
    put: async () => { calls += 1; return { data: payload({ tenant_settings: { ...payload().tenant_settings, name: "Different" } }) }; },
  });
  await assert.rejects(
    () => service.saveSettings({ expectedOwner: owner, draft: { name: "", contact_email: null, contact_phone: null } }),
    AdminClosureSettingsContractError,
  );
  assert.equal(calls, 0);
  await assert.rejects(
    () => service.saveSettings({ expectedOwner: owner, draft: payload().tenant_settings }),
    /does not match/,
  );
  assert.equal(calls, 1);
});

test("actual Axios settings GET and PUT carry AbortSignal, timeout, and skip refresh while returning persisted acknowledgement", async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, data: config.data, signal: config.signal, timeout: config.timeout, skip: config._skipAuthRefresh });
    return axiosResponse(config, payload());
  };
  try {
    const service = createAdminClosureSettingsService(api);
    const controller = new AbortController();
    const loaded = await service.loadSettings({ expectedOwner: owner, signal: controller.signal });
    const saved = await service.saveSettings({ expectedOwner: owner, draft: loaded.tenantSettings, signal: controller.signal });
    assert.equal(saved.tenantSettings.name, "Recorded tenant");
    assert.equal(calls.length, 2);
    assert.deepEqual(calls.map((call) => [call.url, call.method]), [
      [ADMIN_CLOSURE_SETTINGS_ENDPOINT, "get"],
      [ADMIN_CLOSURE_SETTINGS_ENDPOINT, "put"],
    ]);
    calls.forEach((call) => {
      assert.equal(call.signal, controller.signal);
      assert.equal(call.timeout, ADMIN_CLOSURE_SETTINGS_REQUEST_TIMEOUT_MS);
      assert.equal(call.skip, true);
    });
    assert.deepEqual(JSON.parse(calls[1].data), { tenant_settings: payload().tenant_settings });
    controller.abort();
    await assert.rejects(
      () => service.loadSettings({ expectedOwner: owner, signal: controller.signal }),
      (error) => error.name === "AbortError" || error.code === "ERR_CANCELED",
    );
    assert.equal(calls.length, 2, "an already aborted settings request must not reach Axios");
  } finally {
    api.defaults.adapter = original;
  }
});

test("actual Axios 401 settings request has no refresh POST and no replay", async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, skip: config._skipAuthRefresh });
    throw new AxiosError("Synthetic unauthorized", "ERR_BAD_REQUEST", config, {}, {
      status: 401, data: { error: "Unauthorized" }, headers: {}, config,
    });
  };
  try {
    const service = createAdminClosureSettingsService(api);
    await assert.rejects(() => service.loadSettings({ expectedOwner: owner }), (error) => error.response?.status === 401);
    assert.deepEqual(calls, [{ url: ADMIN_CLOSURE_SETTINGS_ENDPOINT, method: "get", skip: true }]);
  } finally {
    api.defaults.adapter = original;
  }
});

const pageFile = new URL("../src/pages/admin/Settings.jsx", import.meta.url);
const target = new URL(`../node_modules/.ui4-closure-settings-${process.pid}.mjs`, import.meta.url);
const absolute = (path) => new URL(path, import.meta.url).href;
let page;
try {
  let source = fs.readFileSync(pageFile, "utf8");
  [
    ["../../store/authStore.js", absolute("../src/store/authStore.js")],
    ["../../services/adminClosureSettingsService.js", absolute("../src/services/adminClosureSettingsService.js")],
    ["../../hooks/useAdminClosureSettings.js", absolute("../src/hooks/useAdminClosureSettings.js")],
  ].forEach(([from, to]) => { source = source.replaceAll(`"${from}"`, JSON.stringify(to)); });
  const transformed = await transformWithEsbuild(source, pageFile.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(target, transformed.code);
  page = await import(`${target.href}?test=${process.pid}`);
} finally {
  fs.rmSync(target, { force: true });
}

test("actual Settings UI is accessible, responsive, persisted-only, and explicit about unavailable configuration", () => {
  const read = {
    value: mapAdminClosureSettings(payload(), { expectedOwner: owner }),
    draft: payload().tenant_settings,
    loading: false,
    saving: false,
    dirty: true,
    error: null,
    actionError: null,
    acknowledgement: null,
    refresh: () => {},
    editDraft: () => {},
    saveDraft: async () => true,
  };
  const html = renderToStaticMarkup(React.createElement(page.AdminClosureSettingsContent, { read }));
  assert.match(html, /Tenant contact settings/);
  assert.match(html, /for="admin-closure-tenant-name"/);
  assert.match(html, /for="admin-closure-contact-email"/);
  assert.match(html, /for="admin-closure-contact-phone"/);
  assert.match(html, /Save tenant contact fields/);
  assert.match(html, /Global system settings/);
  assert.match(html, /Payment-provider configuration/);
  assert.match(html, /Missing capability: a persisted global-settings model/);
  assert.match(html, /Missing capability: an approved server-side provider-configuration persistence contract/);
  assert.match(html, /lg:grid-cols-2/);
  assert.doesNotMatch(html, /Stripe API Key|PayPal Client ID|Minimum Payout|type="password"/i);
});
