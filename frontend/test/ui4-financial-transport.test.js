import assert from 'node:assert/strict';
import test from 'node:test';
import { AxiosError } from 'axios';
import api from '../src/services/api.js';
import { createFinancialRecordViewService } from '../src/services/financialRecordViewService.js';

const owner = { user_id: 3, tenant_id: 1 };

test('actual Axios interceptor returns each financial 401 without auth POST, token rotation or GET replay', async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, signal: config.signal, skip: config._skipAuthRefresh });
    throw new AxiosError('Synthetic unauthorized', 'ERR_BAD_REQUEST', config, {}, {
      status: 401, data: { error: 'Unauthorized' }, headers: {}, config,
    });
  };
  try {
    const service = createFinancialRecordViewService();
    for (const [method, role, url] of [
      ['balance', 'trader', '/wallet/balance'],
      ['transactions', 'trader', '/wallet/transactions'],
      ['selfWithdrawals', 'trader', '/traders/withdrawals'],
      ['adminWithdrawals', 'master', '/wallet/admin/withdrawals'],
    ]) {
      calls.length = 0;
      const controller = new AbortController();
      await assert.rejects(service[method]({ expectedOwner: owner, role, signal: controller.signal }),
        (error) => error.response.status === 401);
      assert.equal(calls.length, 1);
      assert.equal(calls[0].url, url);
      assert.equal(calls[0].method, 'get');
      assert.equal(calls[0].signal, controller.signal);
      assert.equal(calls[0].skip, true);
      controller.abort();
      await assert.rejects(service[method]({ expectedOwner: owner, role, signal: controller.signal }),
        (error) => error.name === 'AbortError');
      assert.equal(calls.length, 1, 'already cancelled request never starts transport');
    }
  } finally {
    api.defaults.adapter = original;
  }
});

test('abort racing a rejected financial response never starts refresh or another GET', async () => {
  const original = api.defaults.adapter;
  const controller = new AbortController();
  let started;
  const ready = new Promise((resolve) => { started = resolve; });
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url); started(); await held;
    throw new AxiosError('Synthetic unauthorized', 'ERR_BAD_REQUEST', config, {}, {
      status: 401, data: {}, headers: {}, config,
    });
  };
  try {
    const pending = createFinancialRecordViewService().selfWithdrawals({
      expectedOwner: owner, role: 'trader', signal: controller.signal,
    });
    const checked = assert.rejects(pending, (error) => error.code === 'ERR_CANCELED' || error.name === 'AbortError');
    await ready; controller.abort(); release(); await checked;
    assert.deepEqual(calls, ['/traders/withdrawals']);
  } finally {
    api.defaults.adapter = original;
  }
});
