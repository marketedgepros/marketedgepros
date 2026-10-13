import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { transformWithEsbuild } from "vite";
import {
  AdminClosureSettingsContractError,
  createAdminClosureSettingsService,
  isAdminClosureSettingsContactEmail,
  mapAdminClosureSettings,
} from "../src/services/adminClosureSettingsService.js";

const owner = { user_id: 1, tenant_id: 7, role: "supermaster" };
const draft = (patch = {}) => ({
  name: "Recorded tenant",
  contact_email: null,
  contact_phone: "+10000000000",
  ...patch,
});
const acknowledgement = (tenantSettings, patch = {}) => ({
  owner_context: { user_id: owner.user_id, tenant_id: owner.tenant_id },
  scope: { kind: "tenant", tenant_id: owner.tenant_id },
  tenant_settings: tenantSettings,
  capabilities: {
    tenant_contact: "persisted",
    global_system: "unavailable_no_persistence",
    payment_providers: "unavailable_no_persistence",
  },
  ...patch,
});

const importSettingsPage = async () => {
  const pageFile = new URL("../src/pages/admin/Settings.jsx", import.meta.url);
  const target = new URL(`../node_modules/.remediation-settings-0-${process.pid}.mjs`, import.meta.url);
  const absolute = (path) => new URL(path, import.meta.url).href;
  try {
    let source = fs.readFileSync(pageFile, "utf8");
    [
      ["../../store/authStore.js", absolute("../src/store/authStore.js")],
      ["../../services/adminClosureSettingsService.js", absolute("../src/services/adminClosureSettingsService.js")],
      ["../../hooks/useAdminClosureSettings.js", absolute("../src/hooks/useAdminClosureSettings.js")],
    ].forEach(([from, to]) => { source = source.replaceAll(`\"${from}\"`, JSON.stringify(to)); });
    const transformed = await transformWithEsbuild(source, pageFile.pathname, { loader: "jsx", jsx: "automatic" });
    fs.writeFileSync(target, transformed.code);
    return await import(`${target.href}?test=${process.pid}`);
  } finally {
    fs.rmSync(target, { force: true });
  }
};

const SettingsPage = await importSettingsPage();

test("Settings:0 rejects invalid configured email before PUT and accepts a valid email or contract-permitted null", async () => {
  const calls = [];
  const service = createAdminClosureSettingsService({
    put: async (url, body, config) => {
      calls.push({ url, body, config });
      return { data: acknowledgement(body.tenant_settings) };
    },
  });

  assert.equal(isAdminClosureSettingsContactEmail(null), true);
  assert.equal(isAdminClosureSettingsContactEmail("operations+alerts@example.com"), true);
  assert.equal(isAdminClosureSettingsContactEmail("not-an-email"), false);

  await assert.rejects(
    () => service.saveSettings({ expectedOwner: owner, draft: draft({ contact_email: "not-an-email" }) }),
    AdminClosureSettingsContractError,
  );
  assert.equal(calls.length, 0, "invalid email must be rejected before transport");

  const validEmail = draft({ contact_email: "operations+alerts@example.com" });
  const savedEmail = await service.saveSettings({ expectedOwner: owner, draft: validEmail });
  assert.deepEqual(calls[0].body, { tenant_settings: validEmail });
  assert.deepEqual(savedEmail.tenantSettings, validEmail);

  const blankEmail = draft({ contact_email: null });
  const savedBlank = await service.saveSettings({ expectedOwner: owner, draft: blankEmail });
  assert.deepEqual(calls[1].body, { tenant_settings: blankEmail });
  assert.equal(savedBlank.tenantSettings.contact_email, null, "blank optional email remains the existing null contract value");
});

test("Settings:0 blocks non-supermaster transport and rejects acknowledgements for another owner", async () => {
  let calls = 0;
  const service = createAdminClosureSettingsService({
    put: async (_url, body) => {
      calls += 1;
      return {
        data: acknowledgement(body.tenant_settings, {
          owner_context: { user_id: 2, tenant_id: owner.tenant_id },
        }),
      };
    },
  });

  await assert.rejects(
    () => service.saveSettings({ expectedOwner: { ...owner, role: "master" }, draft: draft() }),
    /supermaster session before transport/,
  );
  assert.equal(calls, 0, "a browser role without supermaster authority cannot start PUT");

  await assert.rejects(
    () => service.saveSettings({ expectedOwner: owner, draft: draft() }),
    /owner context does not match/,
  );
  assert.equal(calls, 1, "a response for another owner is rejected after transport");
  assert.throws(
    () => mapAdminClosureSettings(acknowledgement(draft(), { scope: { kind: "tenant", tenant_id: 8 } }), { expectedOwner: owner }),
    AdminClosureSettingsContractError,
  );
});

test("Settings:0 gives client feedback and focuses contact email while allowing a valid submit", async () => {
  const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", { url: "http://localhost" });
  const previous = Object.fromEntries(
    ["window", "document", "navigator", "HTMLElement", "Event", "IS_REACT_ACT_ENVIRONMENT"]
      .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  [
    ["window", dom.window],
    ["document", dom.window.document],
    ["navigator", dom.window.navigator],
    ["HTMLElement", dom.window.HTMLElement],
    ["Event", dom.window.Event],
    ["IS_REACT_ACT_ENVIRONMENT", true],
  ].forEach(([key, value]) => {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  });

  const saveCalls = [];
  const read = (tenantSettings) => ({
    value: mapAdminClosureSettings(acknowledgement(draft()), { expectedOwner: owner }),
    draft: tenantSettings,
    loading: false,
    saving: false,
    dirty: true,
    error: null,
    actionError: null,
    acknowledgement: null,
    refresh: () => {},
    editDraft: () => {},
    saveDraft: async () => { saveCalls.push(tenantSettings); return true; },
  });
  const root = createRoot(document.getElementById("root"));

  try {
    const React = await import("react");
    await act(async () => {
      root.render(React.createElement(SettingsPage.AdminClosureSettingsContent, { read: read(draft({ contact_email: "not-an-email" })) }));
    });
    const form = document.querySelector("form");
    const email = document.getElementById("admin-closure-contact-email");
    await act(async () => {
      form.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
    });
    assert.equal(saveCalls.length, 0, "invalid client input must not call saveDraft");
    assert.equal(document.activeElement, email, "feedback returns focus to the configured email field");
    assert.match(document.getElementById("admin-closure-contact-email-error").textContent, /valid contact email/i);
    assert.equal(email.getAttribute("aria-invalid"), "true");

    const validTenant = draft({ contact_email: "operations@example.com" });
    await act(async () => {
      root.render(React.createElement(SettingsPage.AdminClosureSettingsContent, { read: read(validTenant) }));
    });
    await act(async () => {
      document.querySelector("form").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
    });
    assert.deepEqual(saveCalls, [validTenant], "a valid configured email reaches the existing save controller");
  } finally {
    await act(async () => { root.unmount(); });
    dom.window.close();
    for (const [key, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
});
