import assert from "node:assert/strict";
import test from "node:test";
import { AxiosError } from "axios";
import api from "../src/services/api.js";
import { ADMIN_INSIGHT_ENDPOINTS, ADMIN_INSIGHT_REQUEST_TIMEOUT_MS, loadAdminInsight } from "../src/services/adminInsightViewService.js";

const owner = { user_id: 3, tenant_id: 1, role: "master" };

test("actual Axios interceptor returns admin-insight 401s without refresh POST or GET replay", async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, signal: config.signal, timeout: config.timeout, skip: config._skipAuthRefresh, params: config.params });
    throw new AxiosError("Synthetic unauthorized", "ERR_BAD_REQUEST", config, {}, { status: 401, data: { error: "Unauthorized" }, headers: {}, config });
  };
  try {
    for (const [kind, days, endpoint] of [["dashboard", null, ADMIN_INSIGHT_ENDPOINTS.dashboard], ["analytics", 30, ADMIN_INSIGHT_ENDPOINTS.analytics]]) {
      calls.length = 0;
      const controller = new AbortController();
      await assert.rejects(loadAdminInsight({ kind, expectedOwner: owner, days, signal: controller.signal }), (error) => error.response?.status === 401);
      assert.equal(calls.length, 1);
      assert.equal(calls[0].url, endpoint);
      assert.equal(calls[0].method, "get");
      assert.equal(calls[0].signal, controller.signal);
      assert.equal(calls[0].timeout, ADMIN_INSIGHT_REQUEST_TIMEOUT_MS);
      assert.equal(calls[0].skip, true);
      assert.deepEqual(calls[0].params, kind === "analytics" ? { days: 30 } : undefined);
      controller.abort();
      await assert.rejects(loadAdminInsight({ kind, expectedOwner: owner, days, signal: controller.signal }), (error) => error.name === "AbortError" || error.code === "ERR_CANCELED");
      assert.equal(calls.length, 1, "an already aborted request must not reach transport");
    }
  } finally { api.defaults.adapter = original; }
});

test("an abort racing a delayed insight response is not mapped or retried", async () => {
  const original = api.defaults.adapter;
  const controller = new AbortController();
  let started;
  const ready = new Promise((resolve) => { started = resolve; });
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const calls = [];
  api.defaults.adapter = async (config) => { calls.push(config.url); started(); await held; return { data: {}, status: 200, statusText: "OK", headers: {}, config }; };
  try {
    const pending = loadAdminInsight({ kind: "dashboard", expectedOwner: owner, days: null, signal: controller.signal });
    const checked = assert.rejects(pending, (error) => error.name === "AbortError" || error.code === "ERR_CANCELED");
    await ready;
    controller.abort();
    release();
    await checked;
    assert.deepEqual(calls, [ADMIN_INSIGHT_ENDPOINTS.dashboard]);
  } finally { api.defaults.adapter = original; }
});
