import assert from "node:assert/strict";
import test from "node:test";
import { AxiosError } from "axios";
import api from "../src/services/api.js";
import {
  ADMIN_PAYMENT_RECORD_ENDPOINTS,
  createAdminPaymentRecordViewService,
} from "../src/services/adminPaymentRecordViewService.js";

const owner = { user_id: 3, tenant_id: 1 };

test("actual Axios interceptor returns admin-payment 401s without refresh POST or GET replay", async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, signal: config.signal, skip: config._skipAuthRefresh });
    throw new AxiosError("Synthetic unauthorized", "ERR_BAD_REQUEST", config, {}, {
      status: 401, data: { error: "Unauthorized" }, headers: {}, config,
    });
  };
  try {
    const service = createAdminPaymentRecordViewService();
    for (const [method, role, endpoint] of [
      ["loadPayments", "master", ADMIN_PAYMENT_RECORD_ENDPOINTS.payments],
      ["loadApprovalRequests", "supermaster", ADMIN_PAYMENT_RECORD_ENDPOINTS.approvalRequests],
    ]) {
      calls.length = 0;
      const controller = new AbortController();
      await assert.rejects(
        service[method]({ expectedOwner: owner, role, signal: controller.signal }),
        (error) => error.response?.status === 401,
      );
      assert.equal(calls.length, 1);
      assert.equal(calls[0].url, endpoint);
      assert.equal(calls[0].method, "get");
      assert.equal(calls[0].signal, controller.signal);
      assert.equal(calls[0].skip, true);

      controller.abort();
      await assert.rejects(
        service[method]({ expectedOwner: owner, role, signal: controller.signal }),
        (error) => error.name === "AbortError" || error.code === "ERR_CANCELED",
      );
      assert.equal(calls.length, 1, "an already aborted request must not enter Axios transport");
    }
  } finally {
    api.defaults.adapter = original;
  }
});

test("an abort racing a delayed admin-payment response is not normalized or retried", async () => {
  const original = api.defaults.adapter;
  const controller = new AbortController();
  let started;
  const ready = new Promise((resolve) => { started = resolve; });
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url);
    started();
    await held;
    return { data: {}, status: 200, statusText: "OK", headers: {}, config };
  };
  try {
    const pending = createAdminPaymentRecordViewService().loadPayments({
      expectedOwner: owner,
      role: "master",
      signal: controller.signal,
    });
    const checked = assert.rejects(pending, (error) => error.name === "AbortError" || error.code === "ERR_CANCELED");
    await ready;
    controller.abort();
    release();
    await checked;
    assert.deepEqual(calls, [ADMIN_PAYMENT_RECORD_ENDPOINTS.payments]);
  } finally {
    api.defaults.adapter = original;
  }
});
