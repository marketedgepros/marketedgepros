import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { transformWithEsbuild } from "vite";
import {
  FINANCIAL_RECORD_ENDPOINTS,
  FinancialRecordContractError,
  buildFinancialRecordParams,
  createFinancialRecordViewService,
  financialPrincipalFromAuth,
  normalizeFinancialBalanceResponse,
  normalizeFinancialTransactionsResponse,
  normalizeFinancialWithdrawalsResponse,
} from "../src/services/financialRecordViewService.js";

const owner = { user_id: 9, tenant_id: 7 };
const flags = {
  owner_context: owner,
  balance_verification: "unverified_legacy",
  payouts_enabled: false,
  available_for_payout: null,
  currency: null,
};
const params = buildFinancialRecordParams();
const wallet = (patch = {}) => ({
  id: 31,
  user_id: 9,
  main_balance: "0.00",
  commission_balance: null,
  bonus_balance: "10.25",
  is_active: true,
  last_transaction_at: "2026-10-12T10:00:00Z",
  created_at: "2026-10-11T10:00:00Z",
  ...patch,
});
const balance = (patch = {}) => ({ ...flags, wallet: wallet(), ...patch });
const transaction = (patch = {}) => ({
  id: 101,
  wallet_id: 31,
  type: "credit",
  balance_type: "main",
  amount: "0.00",
  balance_before: null,
  balance_after: "0.00",
  created_at: "2026-10-12T10:00:00Z",
  ...patch,
});
const transactions = (rows = [transaction()], patch = {}) => ({
  ...flags,
  wallet_id: 31,
  transactions: rows,
  pagination: {
    page: 1,
    per_page: 20,
    total: rows.length,
    pages: rows.length ? 1 : 0,
  },
  filters: { balance_type: null },
  ...patch,
});
const withdrawal = (patch = {}) => ({
  id: 501,
  user_id: 9,
  amount: "25.00",
  fee: null,
  net_amount: null,
  payment_method: "bank_transfer",
  status: "pending",
  created_at: "2026-10-12T10:00:00Z",
  approved_at: null,
  processed_at: null,
  completed_at: null,
  ...patch,
});
const withdrawals = (rows = [withdrawal()], patch = {}) => ({
  ...flags,
  withdrawals: rows,
  pagination: {
    page: 1,
    per_page: 20,
    total: rows.length,
    pages: rows.length ? 1 : 0,
  },
  filters: { status: null },
  ...patch,
});

test("financial record responses require exact allowlists, actor ownership, exact decimals, and strict timestamps", () => {
  const balanceView = normalizeFinancialBalanceResponse(balance(), {
    expectedOwner: owner,
  });
  assert.equal(balanceView.wallet.main_balance, "0.00");
  assert.equal(balanceView.wallet.commission_balance, null);
  assert.equal(balanceView.currency, null);
  assert.equal(
    normalizeFinancialBalanceResponse(
      balance({ wallet: wallet({ is_active: null }) }),
      { expectedOwner: owner },
    ).wallet.is_active,
    null,
  );
  const transactionView = normalizeFinancialTransactionsResponse(
    transactions(),
    { expectedOwner: owner, params },
  );
  assert.equal(transactionView.transactions[0].amount, "0.00");
  assert.equal(transactionView.transactions[0].balance_before, null);
  const self = normalizeFinancialWithdrawalsResponse(withdrawals(), {
    expectedOwner: owner,
    params,
    isAdminScope: false,
  });
  assert.equal(self.withdrawals[0].user_id, 9);
  assert.equal("payment_details" in self.withdrawals[0], false);

  const invalid = [
    () =>
      normalizeFinancialBalanceResponse(
        balance({ wallet: wallet({ user_id: 10 }) }),
        { expectedOwner: owner },
      ),
    () =>
      normalizeFinancialBalanceResponse(balance({ currency: "USD" }), {
        expectedOwner: owner,
      }),
    () =>
      normalizeFinancialBalanceResponse(
        balance({ wallet: { ...wallet(), updated_at: null } }),
        { expectedOwner: owner },
      ),
    () =>
      normalizeFinancialTransactionsResponse(
        transactions([transaction({ wallet_id: 32 })]),
        { expectedOwner: owner, params },
      ),
    () =>
      normalizeFinancialTransactionsResponse(
        transactions([transaction({ amount: "1e3" })]),
        { expectedOwner: owner, params },
      ),
    () =>
      normalizeFinancialTransactionsResponse(
        transactions([transaction({ created_at: "2026-02-31T10:00:00Z" })]),
        { expectedOwner: owner, params },
      ),
    () =>
      normalizeFinancialTransactionsResponse(
        transactions([transaction(), transaction()], {
          pagination: { page: 1, per_page: 20, total: 2, pages: 1 },
        }),
        { expectedOwner: owner, params },
      ),
    () =>
      normalizeFinancialWithdrawalsResponse(
        withdrawals([withdrawal({ user_id: 10 })]),
        { expectedOwner: owner, params, isAdminScope: false },
      ),
    () =>
      normalizeFinancialWithdrawalsResponse(
        withdrawals([withdrawal({ payment_method: "bank account" })]),
        { expectedOwner: owner, params, isAdminScope: false },
      ),
  ];
  invalid.forEach((normalizer) =>
    assert.throws(normalizer, FinancialRecordContractError),
  );
});

test("admin scope is an explicit caller option while its owner context still identifies the actor", () => {
  const scoped = normalizeFinancialWithdrawalsResponse(
    withdrawals([withdrawal({ user_id: 21 })]),
    {
      expectedOwner: owner,
      params,
      isAdminScope: true,
    },
  );
  assert.equal(scoped.ownerContext.user_id, 9);
  assert.equal(scoped.withdrawals[0].user_id, 21);
  assert.throws(
    () =>
      normalizeFinancialWithdrawalsResponse(withdrawals(), {
        expectedOwner: owner,
        params,
      }),
    FinancialRecordContractError,
  );
});

test("financial query parameters are bounded before any transport and preserve a valid empty beyond-total page", async () => {
  let calls = 0;
  const service = createFinancialRecordViewService({
    get: async () => {
      calls += 1;
      return { data: transactions([]) };
    },
  });
  for (const options of [
    { page: 0 },
    { page: 10001 },
    { page: "1" },
    { perPage: 51 },
    { page: 502, perPage: 20 },
    { balanceType: "all" },
    { balanceType: "main", status: "pending" },
  ]) {
    await assert.rejects(() =>
      service.transactions({
        expectedOwner: owner,
        role: "trader",
        ...options,
      }),
    );
  }
  assert.equal(calls, 0);
  const beyondParams = buildFinancialRecordParams({ page: 2, perPage: 20 });
  const beyond = transactions([], {
    pagination: { page: 2, per_page: 20, total: 1, pages: 1 },
  });
  assert.equal(
    normalizeFinancialTransactionsResponse(beyond, {
      expectedOwner: owner,
      params: beyondParams,
    }).transactions.length,
    0,
  );
});

test("injectable requests receive AbortSignal, use canonical endpoints once, and distinguish only canonical missing wallets", async () => {
  const calls = [];
  const controller = new AbortController();
  const client = {
    get: async (path, config) => {
      calls.push({ path, config });
      if (path === FINANCIAL_RECORD_ENDPOINTS.balance)
        return { data: balance() };
      return { data: transactions() };
    },
  };
  const view = await createFinancialRecordViewService(client).wallet({
    expectedOwner: owner,
    role: "trader",
    signal: controller.signal,
  });
  assert.equal(view.kind, "wallet");
  assert.equal(calls.length, 2);
  assert.equal(calls[0].config.signal, controller.signal);
  assert.equal(calls[1].config.signal, controller.signal);
  assert.deepEqual(
    calls.find((call) => call.path === FINANCIAL_RECORD_ENDPOINTS.transactions)
      .config.params,
    { page: 1, per_page: 20 },
  );

  const missing = createFinancialRecordViewService({
    get: async () => {
      const error = new Error("missing");
      error.response = {
        status: 404,
        data: {
          error: "Wallet not found",
          code: "WALLET_NOT_FOUND",
          reason: "unverified_legacy",
        },
      };
      throw error;
    },
  });
  assert.equal(
    (await missing.wallet({ expectedOwner: owner, role: "trader" })).kind,
    "wallet-missing",
  );
  const malformed = createFinancialRecordViewService({
    get: async () => {
      const error = new Error("missing");
      error.response = {
        status: 404,
        data: {
          error: "Wallet not found",
          code: "WALLET_NOT_FOUND",
          reason: "wrong",
        },
      };
      throw error;
    },
  });
  await assert.rejects(() =>
    malformed.wallet({ expectedOwner: owner, role: "trader" }),
  );
});

test("principal rejects tenant aliases and unknown roles while same scalar principal has a stable key", () => {
  assert.equal(
    financialPrincipalFromAuth({ id: 9, tenantId: 7, role: "trader" }, true),
    null,
  );
  assert.equal(
    financialPrincipalFromAuth({ id: 9, tenant_id: 7, role: "user" }, true),
    null,
  );
  const first = financialPrincipalFromAuth(
    { id: 9, tenant_id: 7, role: "trader" },
    true,
  );
  const second = financialPrincipalFromAuth(
    { id: 9, tenant_id: 7, role: "trader", first_name: "Changed" },
    true,
  );
  assert.equal(first.key, second.key);
});

const serviceUrl = new URL(
  "../src/services/financialRecordViewService.js",
  import.meta.url,
).href;
const uiTarget = new URL(
  "../node_modules/.cache-ui4-financial-ui.mjs",
  import.meta.url,
);
let ui;
try {
  const file = new URL(
    "../src/components/financial/FinancialRecordUI.jsx",
    import.meta.url,
  );
  const source = fs
    .readFileSync(file, "utf8")
    .replace(
      /['"]\.\.\/\.\.\/services\/financialRecordViewService\.js['"]/g,
      JSON.stringify(serviceUrl),
    );
  fs.writeFileSync(
    uiTarget,
    (
      await transformWithEsbuild(source, file.pathname, {
        loader: "jsx",
        jsx: "automatic",
      })
    ).code,
  );
  ui = await import(uiTarget.href);
} finally {
  fs.rmSync(uiTarget, { force: true });
}
const render = (element) =>
  renderToStaticMarkup(React.createElement(MemoryRouter, null, element));

test("actual React financial components expose accessible loading, error, missing, amount, and bounded table controls", () => {
  const loading = render(
    React.createElement(ui.FinancialReadState, { loading: true }),
  );
  assert.match(loading, /role="status"/);
  assert.match(loading, /aria-busy="true"/);
  const failed = render(
    React.createElement(ui.FinancialReadState, {
      error: true,
      onRetry: () => {},
    }),
  );
  assert.match(failed, /role="alert"/);
  assert.match(failed, /Retry records/);
  const missing = render(React.createElement(ui.WalletMissingState));
  assert.match(missing, /No legacy wallet record was found/);
  assert.doesNotMatch(missing, /0\.00|No wallet transactions/);
  const amount = render(
    React.createElement(ui.FinancialExactAmount, { value: "0.00" }),
  );
  assert.match(amount, /0\.00/);
  assert.match(amount, /Currency unavailable/);
  assert.doesNotMatch(amount, /\$/);
  const pager = render(
    React.createElement(ui.FinancialPagination, {
      pagination: { page: 501, per_page: 20, total: 10020, pages: 501 },
      onPage: () => {},
    }),
  );
  assert.match(pager, /Financial records pagination/);
  assert.match(pager, /disabled=""/);
});
