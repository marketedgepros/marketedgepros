import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { transformWithEsbuild } from "vite";

const crmFile = new URL("../src/pages/admin/CRM.jsx", import.meta.url);
const detailFile = new URL("../src/pages/admin/LeadDetails.jsx", import.meta.url);
const moduleBase = new URL(`../node_modules/.ui4-closure-crm-${process.pid}`, import.meta.url);
const layoutStub = new URL(`../node_modules/.ui4-closure-crm-layout-${process.pid}.mjs`, import.meta.url);
const toastStub = new URL(`../node_modules/.ui4-closure-crm-toast-${process.pid}.mjs`, import.meta.url);
const authStub = new URL(`../node_modules/.ui4-closure-crm-auth-${process.pid}.mjs`, import.meta.url);
const crmService = new URL("../src/services/adminClosureCrmService.js", import.meta.url).href;
const identityGuard = new URL("../src/hooks/useAdminClosureCrmIdentityGuard.js", import.meta.url).href;
const dialogFocus = new URL("../src/hooks/useDialogFocus.js", import.meta.url).href;

fs.writeFileSync(layoutStub, 'import React from "react"; export default function AdminLayout({children}) { return React.createElement("main", {"data-admin-layout":"true"}, children); }');
fs.writeFileSync(toastStub, 'export const useToast = () => ({ success() {}, error() {}, warning() {} });');
fs.writeFileSync(authStub, 'const state = { user: null, isAuthenticated: false }; export default function useAuthStore(selector) { return selector(state); }');

const compile = async (file, suffix) => {
  let source = fs.readFileSync(file, "utf8")
    .replace(/['"]\.\.\/\.\.\/components\/admin\/AdminLayout['"]/g, JSON.stringify(layoutStub.href))
    .replace(/['"]\.\.\/\.\.\/contexts\/ToastContext['"]/g, JSON.stringify(toastStub.href))
    .replace(/['"]\.\.\/\.\.\/hooks\/useAdminClosureCrmIdentityGuard['"]/g, JSON.stringify(identityGuard))
    .replace(/['"]\.\.\/\.\.\/hooks\/useDialogFocus['"]/g, JSON.stringify(dialogFocus))
    .replace(/['"]\.\.\/\.\.\/store\/authStore['"]/g, JSON.stringify(authStub.href))
    .replace(/['"]\.\.\/\.\.\/services\/adminClosureCrmService['"]/g, JSON.stringify(crmService));
  const target = new URL(`../node_modules/.ui4-closure-crm-${suffix}-${process.pid}.mjs`, import.meta.url);
  const transformed = await transformWithEsbuild(source, file.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(target, transformed.code);
  return { target, module: await import(`${target.href}?test=${process.pid}`) };
};

let crmPage;
let detailPage;
let generated = [];
try {
  const crm = await compile(crmFile, "list");
  const detail = await compile(detailFile, "detail");
  crmPage = crm.module;
  detailPage = detail.module;
  generated = [crm.target, detail.target];
} finally {
  generated.forEach((target) => fs.rmSync(target, { force: true }));
  fs.rmSync(layoutStub, { force: true });
  fs.rmSync(toastStub, { force: true });
  fs.rmSync(authStub, { force: true });
}

const render = (element) => renderToStaticMarkup(element);

test("actual CRM page SSR keeps one admin layout and announces safe unresolved identity state", () => {
  const html = render(React.createElement(MemoryRouter, { initialEntries: ["/admin/crm"] }, React.createElement(crmPage.default)));
  assert.match(html, /data-admin-layout="true"/);
  assert.match(html, /CRM leads/);
  assert.match(html, /aria-label="Loading leads"/);
  assert.match(html, /aria-live="polite"/);
  assert.doesNotMatch(html, /funded|trader account/i);
});

test("actual LeadDetails uses exactly the route-provided shared layout and exposes a labelled loading state", () => {
  const RouteLayout = () => React.createElement("main", { "data-admin-layout": "true" }, React.createElement(detailPage.default));
  const html = render(React.createElement(MemoryRouter, { initialEntries: ["/admin/crm/22"] }, React.createElement(Routes, null, React.createElement(Route, { path: "/admin/crm/:id", element: React.createElement(RouteLayout) }))));
  assert.match(html, /data-admin-layout="true"/);
  assert.equal((html.match(/data-admin-layout="true"/g) ?? []).length, 1);
  assert.match(html, /role="status"/);
  assert.match(html, /aria-label="Loading lead"/);
  assert.doesNotMatch(html, /Convert to Customer|scheduled successfully/i);
});
