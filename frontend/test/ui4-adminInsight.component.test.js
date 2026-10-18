import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { transformWithEsbuild } from "vite";

const uiFile = new URL("../src/components/admin/AdminInsightUI.jsx", import.meta.url);
const dashboardFile = new URL("../src/pages/admin/AdminDashboardConnected.jsx", import.meta.url);
const analyticsFile = new URL("../src/pages/admin/AnalyticsDashboard.jsx", import.meta.url);
const uiTarget = new URL(`../node_modules/.ui4-admin-insight-ui-${process.pid}.mjs`, import.meta.url);
const dashboardTarget = new URL(`../node_modules/.ui4-admin-insight-dashboard-${process.pid}.mjs`, import.meta.url);
const analyticsTarget = new URL(`../node_modules/.ui4-admin-insight-analytics-${process.pid}.mjs`, import.meta.url);
const absolute = (path) => new URL(path, import.meta.url).href;
const compile = async (file, target, replacements = []) => {
  let source = fs.readFileSync(file, "utf8");
  replacements.forEach(([from, to]) => { source = source.replaceAll(`"${from}"`, JSON.stringify(to)); });
  const transformed = await transformWithEsbuild(source, file.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(target, transformed.code);
  return import(`${target.href}?test=${process.pid}`);
};
let ui; let dashboard; let analytics;
try {
  ui = await compile(uiFile, uiTarget);
  dashboard = await compile(dashboardFile, dashboardTarget, [
    ["../../components/admin/AdminInsightUI.jsx", uiTarget.href], ["../../store/authStore.js", absolute("../src/store/authStore.js")], ["../../services/adminInsightViewService.js", absolute("../src/services/adminInsightViewService.js")], ["../../hooks/useAdminInsightRead.js", absolute("../src/hooks/useAdminInsightRead.js")],
  ]);
  analytics = await compile(analyticsFile, analyticsTarget, [
    ["../../components/admin/AdminInsightUI.jsx", uiTarget.href], ["./AdminDashboardConnected.jsx", dashboardTarget.href], ["../../store/authStore.js", absolute("../src/store/authStore.js")], ["../../services/adminInsightViewService.js", absolute("../src/services/adminInsightViewService.js")], ["../../hooks/useAdminInsightRead.js", absolute("../src/hooks/useAdminInsightRead.js")],
  ]);
} finally { fs.rmSync(analyticsTarget, { force: true }); fs.rmSync(dashboardTarget, { force: true }); fs.rmSync(uiTarget, { force: true }); }
const render = (element) => renderToStaticMarkup(
  React.createElement(MemoryRouter, { initialEntries: ["/admin/dashboard"] }, element),
);
const insight = {
  asOf: "2026-10-12T13:00:00Z",
  counts: { users: 1, challenges: 1, payments: 1 },
  distributions: { userRoles: [{ code: "master", count: 1 }], userKyc: [{ code: null, count: 1 }], challengeStatus: [{ code: "active", count: 1 }], paymentStatus: [{ code: "pending", count: 1 }] },
  recentUsers: [{ id: 7, role: "master", is_active: true, kyc_status: null, created_at: null }],
  recentPayments: [{ id: 8, user_id: 7, amount: "0.00", currency: "EUR", payment_type: "challenge_purchase", status: "pending", created_at: null }],
  dailyActivity: [{ date: "2026-10-12", users: 1, challenges: 1, payments: 1 }],
};

test("actual React UI exposes accessible loading, failure, unknown/null, exact-string and overflow-safe record views", () => {
  const loading = render(React.createElement(ui.AdminInsightReadState, { loading: true }));
  assert.match(loading, /role="status"/); assert.match(loading, /aria-busy="true"/);
  const failure = render(React.createElement(ui.AdminInsightReadState, { error: new Error("bad"), onRetry: () => {} }));
  assert.match(failure, /role="alert"/); assert.match(failure, /Refresh records/);
  const users = render(React.createElement(ui.AdminInsightRecentUsersTable, { users: insight.recentUsers }));
  assert.match(users, /User ID/); assert.match(users, /Not recorded/); assert.match(users, /overflow-x-auto/); assert.doesNotMatch(users, /email|Name/i);
  const payments = render(React.createElement(ui.AdminInsightRecentPaymentsTable, { payments: insight.recentPayments }));
  assert.match(payments, /0\.00/); assert.match(payments, /EUR/); assert.doesNotMatch(payments, /\$|Revenue|Total amount/);
  const unknownCurrency = render(React.createElement(ui.AdminInsightRecentPaymentsTable, { payments: [{ ...insight.recentPayments[0], currency: null }] }));
  assert.match(unknownCurrency, /Currency unavailable/);
  const daily = render(React.createElement(ui.AdminInsightDailyTable, { rows: insight.dailyActivity }));
  assert.match(daily, /UTC day/); assert.match(daily, /Payments created/);
});

test("actual dashboard React content is counts-only, links only to real admin routes, and retains no user detail route or polling", () => {
  const html = render(React.createElement(dashboard.AdminDashboardInsightContent, { read: { value: insight, loading: false, error: null, refresh: () => {} } }));
  ["/admin/users", "/admin/challenges", "/admin/kyc-approval", "/admin/payments", "/admin/analytics", "/admin/dashboard"].forEach((href) => assert.match(html, new RegExp(`href="${href}"`)));
  assert.match(html, /Recorded platform overview/); assert.match(html, /0\.00/); assert.match(html, /EUR/);
  assert.doesNotMatch(html, /Revenue|Funding|Conversion|affiliate|\/admin\/users\/7|\$|Total Revenue/);
  assert.doesNotMatch(fs.readFileSync(dashboardFile, "utf8"), /setInterval|setTimeout|<main/);
});

test("actual analytics React content uses the accessible UTC-day selector and has no money, trend, ranking, or status-transition chart claims", () => {
  const html = render(React.createElement(analytics.AnalyticsDashboardInsightContent, { read: { value: insight, loading: false, error: null, refresh: () => {} }, days: 30, onDaysChange: () => {} }));
  assert.match(html, /for="admin-insight-days"/); assert.match(html, /Last 30 UTC calendar days/); assert.match(html, /Daily record creation/); assert.match(html, /UTC calendar day/);
  assert.doesNotMatch(html, /Revenue|Top Performing|Affiliate|Conversion|\$|trend/i);
  assert.doesNotMatch(fs.readFileSync(analyticsFile, "utf8"), /setInterval|setTimeout|<main/);
});

test("every named section references an existing unique heading ID", () => {
  const read = { value: insight, loading: false, error: null, refresh: () => {} };
  for (const html of [
    render(React.createElement(dashboard.AdminDashboardInsightContent, { read })),
    render(React.createElement(analytics.AnalyticsDashboardInsightContent, { read, days: 30, onDaysChange: () => {} })),
  ]) {
    const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
    assert.equal(new Set(ids).size, ids.length);
    for (const match of html.matchAll(/aria-labelledby="([^"]+)"/g)) {
      for (const id of match[1].split(/\s+/)) assert.ok(ids.includes(id), `Missing heading ${id}`);
    }
  }
});
