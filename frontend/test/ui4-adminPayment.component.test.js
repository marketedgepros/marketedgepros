import { compilePaymentHarness } from './paymentHarness.js';
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";

const serviceUrl = new URL("../src/services/adminPaymentRecordViewService.js", import.meta.url).href;
const uiFile = new URL("../src/components/admin/AdminPaymentRecordUI.jsx", import.meta.url);
const uiTarget = new URL(`../node_modules/.ui4-admin-payment-ui-${process.pid}.mjs`, import.meta.url);
const paymentsFile = new URL("../src/pages/admin/PaymentsManagementConnected.jsx", import.meta.url);
const approvalsFile = new URL("../src/pages/admin/PaymentApprovals.jsx", import.meta.url);
const paymentsTarget = new URL(`../node_modules/.ui4-admin-payments-page-${process.pid}.mjs`, import.meta.url);
const approvalsTarget = new URL(`../node_modules/.ui4-admin-approvals-page-${process.pid}.mjs`, import.meta.url);
const absolute = (path) => new URL(path, import.meta.url).href;
const policyModuleUrl = new URL('../src/services/programEvaluationPolicy.js', import.meta.url).href;
const policyOverride = {
  'services/programEvaluationPolicy.js': `export * from ${JSON.stringify(policyModuleUrl)};`,
};

const purchaseBuild = await compilePaymentHarness(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url), {
  prefix: 'ui4-adminPayment-payment',
  overrides: policyOverride,
});
const purchaseBuildUrl = purchaseBuild.targets.get(new URL('../src/components/payments/ProgramPurchaseRecords.jsx', import.meta.url).pathname);
test.after(() => purchaseBuild.cleanup());
const compilePage = async (file, target) => {
  let source = fs.readFileSync(file, "utf8")
    .replace('import ProgramPurchaseRecords from "../../components/payments/ProgramPurchaseRecords.jsx";', `import ProgramPurchaseRecords from ${JSON.stringify(purchaseBuildUrl)};`)
    .replace(/["']\.\.\/\.\.\/components\/admin\/AdminPaymentRecordUI\.jsx["']/g, JSON.stringify(uiTarget.href));
  for (const path of [
    "../../store/authStore.js",
    "../../services/adminPaymentRecordViewService.js",
    "../../hooks/useAdminPaymentRead.js",
    "../../constants/roles.js",
  ]) {
    source = source.replaceAll(`"${path}"`, JSON.stringify(absolute(`../src/${path.slice(6)}`)));
  }
  const transformed = await transformWithEsbuild(source, file.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(target, transformed.code);
  return import(`${target.href}?test=${process.pid}`);
};

let ui;
let paymentPage;
let approvalPage;
try {
  const uiSource = fs.readFileSync(uiFile, "utf8")
    .replace(/["']\.\.\/\.\.\/services\/adminPaymentRecordViewService\.js["']/g, JSON.stringify(serviceUrl));
  const transformedUi = await transformWithEsbuild(uiSource, uiFile.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(uiTarget, transformedUi.code);
  ui = await import(`${uiTarget.href}?test=${process.pid}`);
  paymentPage = await compilePage(paymentsFile, paymentsTarget);
  approvalPage = await compilePage(approvalsFile, approvalsTarget);
} finally {
  fs.rmSync(paymentsTarget, { force: true });
  fs.rmSync(approvalsTarget, { force: true });
  fs.rmSync(uiTarget, { force: true });
}

const render = (element) => renderToStaticMarkup(element);
const paymentView = {
  payments: [{
    id: 31,
    user_id: 22,
    amount: "0.00",
    currency: "USD",
    payment_type: "challenge_purchase",
    payment_method: "<method>",
    status: "pending",
    created_at: "2026-10-12T10:00:00Z",
  }],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
};
const approvalView = {
  requests: [{
    id: 41,
    requested_by: 8,
    requested_for: 22,
    challenge_id: null,
    payment_id: 31,
    amount: "0.00",
    payment_type: null,
    status: "pending",
    created_at: "2026-10-12T10:00:00Z",
    reviewed_at: null,
  }],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
};

test("actual shared UI exposes accessible loading, failure, unknown, exact-decimal and horizontally scrollable record states", () => {
  const loading = render(React.createElement(ui.AdminPaymentReadState, { loading: true }));
  assert.match(loading, /role="status"/);
  assert.match(loading, /aria-busy="true"/);
  const failure = render(React.createElement(ui.AdminPaymentReadState, { error: new Error("bad"), onRetry: () => {} }));
  assert.match(failure, /role="alert"/);
  assert.match(failure, /Refresh records/);
  const table = render(React.createElement(ui.PaymentRecordsTable, { payments: paymentView.payments }));
  assert.match(table, /Recorded legacy payment records/);
  assert.match(table, /0\.00/);
  assert.match(table, /USD/);
  assert.match(table, /&lt;method&gt;/);
  assert.match(table, /overflow-x-auto/);
  assert.doesNotMatch(table, /Transaction ID|\$/);
  const unknown = render(React.createElement(ui.AdminPaymentExactAmount, { amount: null, currency: null }));
  assert.match(unknown, /Unknown/);
  assert.match(unknown, /Currency unavailable/);
});

test("actual connected payments content uses Status then Purpose server filters and does not invent KPIs or aggregate currency", () => {
  const read = { value: paymentView, loading: false, error: null, refresh: () => {} };
  const html = render(React.createElement(paymentPage.PaymentsManagementContent, {
    read,
    status: null,
    type: null,
    onStatusChange: () => {},
    onTypeChange: () => {},
    onPage: () => {},
  }));
  assert.match(html, /<label for="payment-record-status"[^>]*>Status<\/label>[\s\S]*?<label for="payment-record-purpose"[^>]*>Purpose<\/label>/);
  assert.match(html, /Refresh records/);
  assert.match(html, /Recorded payment records/);
  assert.doesNotMatch(html, /Revenue|Average|Payout|Transaction ID|\$/);
});

test("actual approval content is pending-only read-only, while the master restriction is an alert with no request action", () => {
  const read = { value: approvalView, loading: false, error: null, refresh: () => {} };
  const html = render(React.createElement(approvalPage.PaymentApprovalsContent, { read, onPage: () => {} }));
  assert.match(html, /Server filter: pending only/);
  assert.match(html, /Pending legacy approval requests/);
  assert.match(html, /Request ID/);
  assert.match(html, /Unknown/);
  assert.doesNotMatch(html, />\s*(?:Approve|Reject|Create)\s*<\/button>/);
  assert.doesNotMatch(html, /role="dialog"/);
  const restricted = render(React.createElement(ui.ApprovalAccessRestricted));
  assert.match(restricted, /role="alert"/);
  assert.match(restricted, /no request was sent/i);
  assert.doesNotMatch(restricted, /<button/);
});

test("actual pagination is labelled and bounded at the client page limit", () => {
  const html = render(React.createElement(ui.AdminPaymentPagination, {
    pagination: { page: 10000, per_page: 1, total: 10001, pages: 10001 },
    onPage: () => {},
  }));
  assert.match(html, /Recorded payment pagination/);
  assert.match(html, /Browsing is limited to 10000 pages/);
  assert.match(html, /disabled=""/);
});

test('actual approval table preserves cash/free type labels rather than payment-purpose labels', () => {
  const rows = ['cash', 'free'].map((payment_type, index) => ({ ...approvalView.requests[0], id: 50 + index, payment_type }));
  const html = render(React.createElement(ui.ApprovalRequestsTable, { requests: rows }));
  assert.match(html, />Cash<\/span>/);
  assert.match(html, />Free<\/span>/);
  assert.doesNotMatch(html, /Challenge purchase/);
});

test('actual pagination stops before offset bound and empty pages retain return navigation', () => {
  const html = render(React.createElement(ui.AdminPaymentPagination, { pagination: { page: 501, per_page: 20, total: 12000, pages: 600 }, onPage: () => {} }));
  assert.match(html, /Browsing is limited to 501 pages/);
  assert.match(html, /disabled=""[^>]*>[\s\S]*?Next page/);
  for (const [component, value] of [
    [paymentPage.PaymentsManagementContent, { payments: [], pagination: { page: 2, per_page: 20, total: 1, pages: 1 } }],
    [approvalPage.PaymentApprovalsContent, { requests: [], pagination: { page: 2, per_page: 20, total: 1, pages: 1 } }],
  ]) {
    const empty = render(React.createElement(component, { read: { value, loading: false, error: null, refresh: () => {} }, status: null, type: null, onPage: () => {} }));
    assert.match(empty, /First page/);
    assert.match(empty, /Previous page/);
  }
});
