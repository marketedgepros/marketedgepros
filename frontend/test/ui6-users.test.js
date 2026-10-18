import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { JSDOM } from "jsdom";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { Simulate } from "react-dom/test-utils";
import { transformWithEsbuild } from "vite";
import api from "../src/services/api.js";
import useAuthStore from "../src/store/authStore.js";

const here = import.meta.url;
const absolute = (relative) => new URL(relative, here).href;
const userPageFile = new URL("../src/pages/admin/UserManagementConnected.jsx", here);
const appFile = new URL("../src/App.jsx", here);
const roleGuardFile = new URL("../src/components/guards/RoleGuard.jsx", here);
const userPageTarget = new URL(`../node_modules/.ui6-users-page-${process.pid}.mjs`, here);
const appTarget = new URL(`../node_modules/.ui6-users-router-${process.pid}.mjs`, here);

async function compileUserPage() {
  let source = fs.readFileSync(userPageFile, "utf8");
  for (const [from, to] of [
    ["../../store/authStore.js", absolute("../src/store/authStore.js")],
    ["../../constants/roles.js", absolute("../src/constants/roles.js")],
    ["../../services/adminClosureUsersService.js", absolute("../src/services/adminClosureUsersService.js")],
    ["../../hooks/useAdminClosureUsers.js", absolute("../src/hooks/useAdminClosureUsers.js")],
    ["../../hooks/useDialogFocus.js", absolute("../src/hooks/useDialogFocus.js")],
  ]) source = source.replaceAll(`"${from}"`, JSON.stringify(to));
  const transformed = await transformWithEsbuild(source, userPageFile.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(userPageTarget, transformed.code);
  return import(`${userPageTarget.href}?ui6=${process.pid}`);
}

async function compileRouter() {
  const roleGuard = fs.readFileSync(roleGuardFile, "utf8")
    .replace("import { Navigate } from 'react-router-dom';", "")
    .replace("import useAuthStore from '../../store/authStore';", "")
    .replace("export default function RoleGuard", "function RoleGuard");
  let source = fs.readFileSync(appFile, "utf8")
    .replace("import useAuthStore from './store/authStore';", `import useAuthStore from ${JSON.stringify(absolute("../src/store/authStore.js"))};`)
    .replace("import Notification from './components/Notification';", "const Notification = () => null;")
    .replace("import RouteScrollManager from './components/RouteScrollManager.js';", `import RouteScrollManager from ${JSON.stringify(new URL('../src/components/RouteScrollManager.js', import.meta.url).href)};`)
    .replace("import ChatWidget from './components/ChatWidget';", "const ChatWidget = () => null;")
    .replace("import { ADMIN_ROLES } from './constants/roles';", `import { ADMIN_ROLES } from ${JSON.stringify(absolute("../src/constants/roles.js"))};`)
    .replace("import { postLoginDestination } from './services/navigationService.js';", `import { postLoginDestination } from ${JSON.stringify(absolute("../src/services/navigationService.js"))};`)
    .replace("import { ToastProvider } from './contexts/ToastContext';", "const ToastProvider = ({ children }) => children;")
    .replace("import useNotificationStore from './stores/notificationStore.js';", "const useNotificationStore = { getState: () => ({ reset: () => {} }) };")
    .replace("import RoleGuard from './components/guards/RoleGuard';", roleGuard);
  source = source.replace(/const (\w+) = lazy\(\(\) => import\(['"][^'"]+['"]\)\);/g, (_, name) => (
    name === "AdminLayout"
      ? "const AdminLayout = ({ children }) => <div data-page=\"AdminLayout\">{children}</div>;"
      : `const ${name} = () => <div data-page=\"${name}\">${name}</div>;`
  ));
  const transformed = await transformWithEsbuild(source, appFile.pathname, { loader: "jsx", jsx: "automatic" });
  fs.writeFileSync(appTarget, transformed.code);
  return import(`${appTarget.href}?ui6=${process.pid}`);
}

let usersPage;
let router;
try {
  usersPage = await compileUserPage();
  router = await compileRouter();
} finally {
  fs.rmSync(userPageTarget, { force: true });
  fs.rmSync(appTarget, { force: true });
}

const owner = { user_id: 2, tenant_id: 1, role: "master" };
const authUser = { id: 2, tenant_id: 1, role: "master", first_name: "Admin", last_name: "Owner", email: "admin@example.invalid" };
const stamp = "2026-10-12T12:00:00Z";

function installDom(path = "/admin/users") {
  const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", {
    url: `http://localhost${path}`,
    pretendToBeVisual: true,
  });
  const names = [
    "window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Node", "Element", "Event",
    "MouseEvent", "KeyboardEvent", "PopStateEvent", "MutationObserver", "getComputedStyle", "localStorage",
    "requestAnimationFrame", "cancelAnimationFrame", "IS_REACT_ACT_ENVIRONMENT",
  ];
  const prior = new Map(names.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const supplied = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Node: dom.window.Node,
    Element: dom.window.Element,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    PopStateEvent: dom.window.PopStateEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    localStorage: dom.window.localStorage,
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [name, value] of Object.entries(supplied)) Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  return {
    dom,
    root: dom.window.document.getElementById("root"),
    restore() {
      dom.window.close();
      for (const [name, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else delete globalThis[name];
      }
    },
  };
}

const delay = () => new Promise((resolve) => setTimeout(resolve, 0));
async function waitFor(check, label) {
  let lastError;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const value = check();
      if (value) return value;
    } catch (error) { lastError = error; }
    await act(async () => { await delay(); });
  }
  throw lastError || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, "click target exists");
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}
async function submit(form) {
  assert.ok(form, "form exists");
  await act(async () => {
    form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}
async function inputValue(element, value) {
  assert.ok(element, "input exists");
  const prototype = element.tagName === "SELECT" ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  descriptor.set.call(element, value);
  await act(async () => {
    Simulate.change(element, { target: { value } });
    await Promise.resolve();
  });
}
function button(text, occurrence = 0) {
  const matches = [...document.querySelectorAll("button")].filter((element) => element.textContent.replace(/\s+/g, " ").trim() === text);
  return matches[occurrence];
}
function dialog() { return document.querySelector('[role="dialog"]'); }
function visibleText() { return document.body.textContent.replace(/\s+/g, " "); }
function row(id = 3) {
  return {
    id,
    first_name: id === 3 ? "Trader" : "User",
    last_name: id === 3 ? "Three" : String(id),
    email: `user${id}@example.invalid`,
    role: "trader",
    is_active: true,
    kyc_status: "not_submitted",
    created_at: stamp,
    last_login_at: null,
  };
}
function listPayload(params, empty = false) {
  const page = params.page;
  const total = empty ? 0 : 45;
  const received = empty ? 0 : (page === 3 ? 5 : 20);
  return {
    owner_context: { user_id: 2, tenant_id: 1 },
    users: Array.from({ length: received }, (_, index) => row(3 + ((page - 1) * 20) + index)),
    pagination: { page, per_page: params.per_page, total, pages: empty ? 0 : 3 },
    filters: { role: params.role ?? null, status: params.status ?? null, search: params.search ?? null },
  };
}
function hierarchyPayload() {
  return {
    owner_context: { user_id: 2, tenant_id: 1 },
    users: [{ ...row(3), children: [] }],
    total_users: 1,
  };
}
function detailsPayload() {
  return {
    owner_context: { user_id: 2, tenant_id: 1 },
    record_verification: "unverified_legacy",
    settlement_enabled: false,
    user: { ...row(3), phone: null, country_code: null, is_verified: true, two_factor_enabled: false, updated_at: stamp },
    downline: { items: [], truncated: false },
    challenges: { items: [], truncated: false },
    payments: { items: [], truncated: false },
  };
}
function response(config, data) {
  return { data, status: 200, statusText: "OK", headers: {}, config, request: {} };
}
function setAuth(state) {
  useAuthStore.setState({
    user: state.user,
    isAuthenticated: state.isAuthenticated,
    isLoading: false,
    error: null,
    init: async () => {},
  });
}

// This executes the current route expression plus the current ProtectedRoute/RoleGuard code;
// only leaf lazy pages are inert probes so no unrelated domains are loaded.
test("users route runs guest, forbidden, permitted, refresh, and back/forward outcomes through BrowserRouter", { concurrency: false }, async () => {
  const originalAuth = useAuthStore.getState();
  const environment = installDom("/admin/users");
  let root;
  async function mount(path, state) {
    window.history.replaceState({}, "", path);
    setAuth(state);
    root = createRoot(environment.root);
    await act(async () => { root.render(React.createElement(router.default)); });
  }
  async function unmount() {
    if (root) await act(async () => { root.unmount(); });
    root = undefined;
  }
  try {
    await mount("/admin/users", { user: null, isAuthenticated: false });
    await waitFor(() => document.querySelector('[data-page="Login"]'), "guest redirect to login");
    assert.equal(window.location.pathname, "/login");
    assert.equal(window.location.search, "?redirect=%2Fadmin%2Fusers");
    await unmount();

    await mount("/admin/users", { user: { ...authUser, role: "trader" }, isAuthenticated: true });
    await waitFor(() => visibleText().includes("Access Denied"), "forbidden role view");
    assert.equal(document.querySelector('[data-page="UserManagement"]'), null);
    await unmount();

    await mount("/admin/dashboard", { user: authUser, isAuthenticated: true });
    await waitFor(() => document.querySelector('[data-page="AdminDashboard"]'), "admin dashboard probe");
    window.history.pushState({}, "", "/admin/users");
    window.dispatchEvent(new window.PopStateEvent("popstate"));
    await waitFor(() => document.querySelector('[data-page="UserManagement"]'), "permitted user route");
    window.history.back();
    await waitFor(() => document.querySelector('[data-page="AdminDashboard"]'), "back to dashboard");
    window.history.forward();
    await waitFor(() => document.querySelector('[data-page="UserManagement"]'), "forward to users");
    await unmount();

    await mount("/admin/users", { user: authUser, isAuthenticated: true });
    await waitFor(() => document.querySelector('[data-page="UserManagement"]'), "refresh remount of permitted route");
  } finally {
    await unmount();
    useAuthStore.setState(originalAuth, true);
    environment.restore();
  }
});

test("mounted users UI binds controls to owner-validated synthetic reads and acknowledged writes", { concurrency: false }, async () => {
  const originalAuth = useAuthStore.getState();
  const originalAdapter = api.defaults.adapter;
  const environment = installDom();
  const calls = [];
  let releaseFirstRead;
  const firstRead = new Promise((resolve) => { releaseFirstRead = resolve; });
  let firstListRequest = true;
  let emptyNextList = false;
  const createModes = ["bad_ack", "bad_owner", "success"];
  const writeBodies = [];
  window.confirm = () => true;
  api.defaults.adapter = async (config) => {
    const method = String(config.method || "get").toLowerCase();
    calls.push({ method, url: config.url, params: config.params, data: config.data, signal: config.signal, skip: config._skipAuthRefresh });
    assert.equal(config._skipAuthRefresh, true, "user request suppresses auth-refresh replay");
    assert.ok(config.signal instanceof AbortSignal, "user request has a concrete abort signal");
    assert.equal(config.signal.aborted, false, "current user request is not already aborted");
    if (method === "get" && config.url === "/admin/users") {
      if (firstListRequest) {
        firstListRequest = false;
        await firstRead;
        throw new Error("Synthetic list failure");
      }
      const payload = listPayload(config.params, emptyNextList);
      emptyNextList = false;
      return response(config, payload);
    }
    if (method === "get" && config.url === "/admin/users/hierarchy") return response(config, hierarchyPayload());
    if (method === "get" && config.url === "/admin/users/3/full-details") return response(config, detailsPayload());

    const body = typeof config.data === "string" ? JSON.parse(config.data) : config.data;
    writeBodies.push({ method, url: config.url, body });
    let action;
    if (method === "post" && config.url === "/admin/users") {
      assert.deepEqual(body, {
        email: "new@example.invalid", password: "StrongValue42!", first_name: "New", last_name: "User", phone: null, country_code: null, role: "trader",
      });
      const mode = createModes.shift();
      action = mode === "bad_ack" ? "updated" : "created";
      return response(config, {
        owner_context: mode === "bad_owner" ? { user_id: 9, tenant_id: 1 } : { user_id: 2, tenant_id: 1 },
        action,
        message: "Confirmed created.",
        user: { id: 3, role: "trader", is_active: true },
      });
    }
    if (method === "put" && config.url === "/admin/users/3") {
      assert.deepEqual(body, { first_name: "Updated", last_name: "Three", phone: null, country_code: null, role: "trader", is_active: true });
      action = "updated";
    } else if (method === "delete" && config.url === "/admin/users/3") {
      assert.equal(body, undefined);
      action = "deactivated";
    } else if (method === "post" && config.url === "/admin/users/3/reset-password") {
      assert.deepEqual(body, { new_password: "NextValue42!" });
      action = "password_reset";
    } else {
      throw new Error(`Unexpected synthetic request ${method} ${config.url}`);
    }
    return response(config, {
      owner_context: { user_id: owner.user_id, tenant_id: owner.tenant_id },
      action,
      message: `Confirmed ${action}.`,
      user: { id: 3, role: "trader", is_active: action === "deactivated" ? false : true },
    });
  };
  setAuth({ user: authUser, isAuthenticated: true });
  const root = createRoot(environment.root);
  try {
    await act(async () => { root.render(React.createElement(usersPage.default)); });
    await waitFor(() => document.querySelector('[aria-busy="true"]'), "initial loading state");
    releaseFirstRead();
    await waitFor(() => document.querySelector('[role="alert"]') && button("Retry"), "failure with retry");
    const readsBeforeRetry = calls.filter((call) => call.method === "get" && call.url === "/admin/users").length;
    await click(button("Retry"));
    await waitFor(() => visibleText().includes("Showing 20 records"), "retried list");
    assert.equal(calls.filter((call) => call.method === "get" && call.url === "/admin/users").length, readsBeforeRetry + 1);

    emptyNextList = true;
    await click(button("Refresh"));
    await waitFor(() => visibleText().includes("No user records"), "empty list state");
    await click(button("Refresh"));
    await waitFor(() => visibleText().includes("Showing 20 records"), "refresh recovery");

    await click(button("Next"));
    await waitFor(() => visibleText().includes("Page 2 of 3"), "next page");
    await click(button("Previous"));
    await waitFor(() => visibleText().includes("Page 1 of 3"), "previous page");
    const listPages = calls.filter((call) => call.method === "get" && call.url === "/admin/users").map((call) => call.params.page);
    assert.ok(listPages.includes(2), "Next bound page 2 into the read request");
    assert.ok(listPages.filter((page) => page === 1).length >= 3, "Retry/refresh/Previous bound page 1 reads");

    await click(button("Hierarchy"));
    await waitFor(() => visibleText().includes("Scoped hierarchy"), "hierarchy switch");
    const hierarchyNode = [...document.querySelectorAll("button")].find((element) => element.textContent.includes("Trader Three"));
    await click(hierarchyNode);
    await waitFor(() => dialog() && visibleText().includes("User details"), "tree view details");
    await click(document.querySelector('button[aria-label="Close dialog"]'));
    await waitFor(() => !dialog(), "tree detail close");
    await click(button("Table"));
    await waitFor(() => visibleText().includes("User filters"), "table switch");

    await click(button("Add user"));
    await waitFor(() => dialog() && visibleText().includes("Add user"), "create dialog");
    await click(document.querySelector('button[aria-label="Close dialog"]'));
    await waitFor(() => !dialog(), "header close");
    await click(button("Add user"));
    await waitFor(() => dialog(), "reopened create dialog");
    const createForm = dialog().querySelector("form");
    const createInputs = createForm.querySelectorAll("input");
    await inputValue(createInputs[0], "New");
    await inputValue(createInputs[1], "User");
    await inputValue(createInputs[2], "new@example.invalid");
    await inputValue(createInputs[3], "StrongValue42!");
    await inputValue(createForm.querySelector("select"), "trader");
    await submit(createForm);
    await waitFor(() => visibleText().includes("The account action was not confirmed by the server."), "rejected mismatched acknowledgement");
    assert.ok(dialog(), "bad acknowledgement cannot close the dialog");
    assert.doesNotMatch(visibleText(), /Confirmed created\./, "bad acknowledgement has no success notice");
    await submit(createForm);
    await waitFor(() => visibleText().includes("The account action was not confirmed by the server."), "rejected mismatched owner");
    assert.ok(dialog(), "bad owner cannot close the dialog");
    await submit(createForm);
    await waitFor(() => !dialog() && visibleText().includes("Confirmed created."), "acknowledged create");

    await click(button("View"));
    await waitFor(() => dialog() && visibleText().includes("User details"), "row view details");
    await click(button("Edit account"));
    await waitFor(() => dialog() && visibleText().includes("Edit account"), "detail edit action");
    await click(button("Cancel"));
    await waitFor(() => !dialog(), "edit cancel");

    await click(button("Edit"));
    await waitFor(() => dialog() && visibleText().includes("Edit account"), "row edit action");
    const editForm = dialog().querySelector("form");
    await inputValue(editForm.querySelector("input"), "Updated");
    await submit(editForm);
    await waitFor(() => !dialog() && visibleText().includes("Confirmed updated."), "acknowledged update");

    await click(button("View"));
    await waitFor(() => dialog() && visibleText().includes("User details"), "details for password reset");
    await click(button("Reset password"));
    await waitFor(() => dialog() && visibleText().includes("Reset password"), "detail reset action");
    await click(button("Cancel"));
    await waitFor(() => !dialog(), "password reset cancel");
    await click(button("View"));
    await waitFor(() => dialog() && visibleText().includes("User details"), "reopened details for password reset");
    await click(button("Reset password"));
    await waitFor(() => dialog() && visibleText().includes("Reset password"), "reopened reset dialog");
    const resetForm = dialog().querySelector("form");
    await inputValue(resetForm.querySelector("input[type=\"password\"]"), "NextValue42!");
    await submit(resetForm);
    await waitFor(() => !dialog() && visibleText().includes("Confirmed password_reset."), "acknowledged reset");

    await click(button("Deactivate"));
    await waitFor(() => visibleText().includes("Confirmed deactivated."), "acknowledged deactivate");
    assert.deepEqual(writeBodies.map((item) => [item.method, item.url]), [
      ["post", "/admin/users"], ["post", "/admin/users"], ["post", "/admin/users"],
      ["put", "/admin/users/3"], ["post", "/admin/users/3/reset-password"], ["delete", "/admin/users/3"],
    ]);
  } finally {
    await act(async () => { root.unmount(); });
    api.defaults.adapter = originalAdapter;
    useAuthStore.setState(originalAuth, true);
    environment.restore();
  }
});
