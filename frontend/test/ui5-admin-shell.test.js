import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React, { act } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

// ReactDOM observes DOM support while loading; provide a disposable bootstrap
// so the real source hook and the test renderer share React's actual dispatcher.
const bootstrap = new JSDOM('<!doctype html><html><body></body></html>');
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrap.window, document: bootstrap.window.document, navigator: bootstrap.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
}
const { createRoot } = await import('react-dom/client');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const layoutFile = new URL('../src/components/admin/AdminLayout.jsx', import.meta.url);
const temporaryFiles = ['router', 'auth', 'icons', 'bell', 'layout']
  .map((name) => new URL(`../node_modules/.ui5-admin-shell-${name}-${process.pid}.mjs`, import.meta.url));
const [routerFile, authFile, iconsFile, bellFile, moduleFile] = temporaryFiles;
const dialogFocusUrl = new URL('../src/hooks/useDialogFocus.js', import.meta.url).href;

function writeStub(file, source) {
  fs.writeFileSync(file, source);
}

let shell;
try {
  writeStub(routerFile, `
    import React from 'react';
    let pathname = '/admin/dashboard';
    export const __setPathname = (nextPathname) => { pathname = nextPathname; };
    export const useLocation = () => ({ pathname });
    export const useNavigate = () => () => {};
    export const Link = ({ children, ...props }) => React.createElement('a', props, children);
  `);
  writeStub(authFile, `
    export default function useAuthStore() {
      return {
        user: { first_name: 'Admin', last_name: 'User', email: 'admin@example.test' },
        logout: async () => {},
      };
    }
  `);
  writeStub(iconsFile, `
    import React from 'react';
    const Icon = () => React.createElement('svg', { 'aria-hidden': true });
    export const LayoutDashboard = Icon; export const Users = Icon; export const CreditCard = Icon;
    export const DollarSign = Icon; export const CheckCircle = Icon; export const BarChart3 = Icon;
    export const Settings = Icon; export const LogOut = Icon; export const Menu = Icon; export const X = Icon;
    export const Shield = Icon; export const ChevronRight = Icon; export const LifeBuoy = Icon; export const Award = Icon;
  `);
  writeStub(bellFile, `import React from 'react'; export default function NotificationBell() { return React.createElement('button', { type: 'button', 'aria-label': 'Notifications' }); }`);

  const source = fs.readFileSync(layoutFile, 'utf8')
    .replace("from 'react-router-dom';", `from ${JSON.stringify(routerFile.href)};`)
    .replace("from '../../store/authStore';", `from ${JSON.stringify(authFile.href)};`)
    .replace("from 'lucide-react';", `from ${JSON.stringify(iconsFile.href)};`)
    .replace("from '../notifications/NotificationBell';", `from ${JSON.stringify(bellFile.href)};`)
    .replace("from '../../hooks/useDialogFocus.js';", `from ${JSON.stringify(dialogFocusUrl)};`);
  const transformed = await transformWithEsbuild(source, layoutFile.pathname, { loader: 'jsx', jsx: 'automatic' });
  fs.writeFileSync(moduleFile, transformed.code);
  shell = await import(`${moduleFile.href}?ui5=${process.pid}`);
} finally {
  temporaryFiles.forEach((file) => fs.rmSync(file, { force: true }));
}

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { pretendToBeVisual: true });
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'IS_REACT_ACT_ENVIRONMENT'];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement, Node: dom.window.Node, Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent, KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver, IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom,
    root,
    host: dom.window.document.getElementById('root'),
    async close() {
      await act(async () => { root.unmount(); });
      dom.window.close();
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
    },
  };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test('UI5 admin shell renders named, associated mobile menu controls through React DOM', () => {
  const html = renderToStaticMarkup(React.createElement(shell.default, null, 'Admin content'));
  assert.match(html, /<aside[^>]*id="admin-navigation"[^>]*aria-label="Administration navigation"/);
  assert.match(html, /<button[^>]*type="button"[^>]*aria-label="Open administration menu"[^>]*aria-controls="admin-navigation"[^>]*aria-expanded="false"/);
  assert.match(html, /<button[^>]*type="button"[^>]*aria-label="Close administration menu"[^>]*aria-controls="admin-navigation"/);
  assert.match(html, /aria-label="My support tickets"/);
  assert.match(html, /focus-visible:ring-cyan-400/);
});

test('UI5 admin shell opens its drawer with the real focus hook and Escape restores its trigger', async () => {
  const environment = installDom();
  try {
    await act(async () => { environment.root.render(React.createElement(shell.default, null, 'Admin content')); });
    const open = environment.host.querySelector('[aria-label="Open administration menu"]');
    assert.ok(open, 'the mobile-menu trigger is rendered');
    assert.equal(open.getAttribute('aria-expanded'), 'false');
    open.focus();

    await act(async () => { open.click(); });
    await settle();
    const close = environment.host.querySelector('[aria-label="Close administration menu"]');
    const sidebar = environment.host.querySelector('#admin-navigation');
    assert.equal(open.getAttribute('aria-expanded'), 'true');
    assert.equal(sidebar.getAttribute('role'), 'dialog');
    assert.equal(sidebar.getAttribute('aria-modal'), 'true');
    assert.match(sidebar.className, /visible translate-x-0/);
    assert.equal(environment.dom.window.document.activeElement, close, 'the real hook focuses the data-autofocus close control');
    assert.equal(environment.host.querySelector('main').getAttribute('aria-hidden'), 'true', 'open drawer isolates background content');

    await act(async () => {
      environment.dom.window.document.dispatchEvent(new environment.dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    });
    await settle();
    assert.equal(open.getAttribute('aria-expanded'), 'false');
    assert.match(sidebar.className, /invisible/);
    assert.equal(environment.dom.window.document.activeElement, open, 'Escape through the real hook returns focus to the trigger');
    assert.equal(environment.host.querySelector('main').getAttribute('aria-hidden'), null, 'closing restores background accessibility');
  } finally {
    await environment.close();
  }
});
