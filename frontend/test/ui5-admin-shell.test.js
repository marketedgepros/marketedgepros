import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';

const layoutFile = new URL('../src/components/admin/AdminLayout.jsx', import.meta.url);
const temporaryFiles = [
  'hooks',
  'router',
  'auth',
  'icons',
  'bell',
  'layout',
].map((name) => new URL(`../node_modules/.ui5-admin-shell-${name}-${process.pid}.mjs`, import.meta.url));
const [hooksFile, routerFile, authFile, iconsFile, bellFile, moduleFile] = temporaryFiles;

function writeStub(file, source) {
  fs.writeFileSync(file, source);
}

function childElements(value) {
  if (Array.isArray(value)) return value.flatMap(childElements);
  if (!React.isValidElement(value)) return [];
  return [value, ...childElements(value.props.children)];
}

function findElement(tree, predicate) {
  return childElements(tree).find(predicate);
}

let shell;
let hooks;
try {
  writeStub(hooksFile, `
    let slots = [];
    let cursor = 0;
    let pendingEffects = [];
    export const __reset = () => { slots = []; cursor = 0; pendingEffects = []; };
    export const __beginRender = () => { cursor = 0; };
    export const __flushEffects = () => {
      const effects = pendingEffects;
      pendingEffects = [];
      for (const { index, callback } of effects) {
        const previous = slots[index]?.cleanup;
        if (typeof previous === 'function') previous();
        slots[index] = { ...slots[index], cleanup: callback() };
      }
    };
    export const useState = (initialValue) => {
      const index = cursor++;
      if (!Object.hasOwn(slots, index)) slots[index] = typeof initialValue === 'function' ? initialValue() : initialValue;
      return [slots[index], (nextValue) => {
        slots[index] = typeof nextValue === 'function' ? nextValue(slots[index]) : nextValue;
      }];
    };
    export const useRef = (initialValue) => {
      const index = cursor++;
      if (!Object.hasOwn(slots, index)) slots[index] = { current: initialValue };
      return slots[index];
    };
    export const useEffect = (callback, dependencies) => {
      const index = cursor++;
      const previous = slots[index];
      const changed = !previous || dependencies.length !== previous.dependencies.length || dependencies.some((value, dependencyIndex) => value !== previous.dependencies[dependencyIndex]);
      if (changed) {
        slots[index] = { dependencies, cleanup: previous?.cleanup };
        pendingEffects.push({ index, callback });
      }
    };
  `);
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
    export const LayoutDashboard = Icon;
    export const Users = Icon;
    export const CreditCard = Icon;
    export const DollarSign = Icon;
    export const CheckCircle = Icon;
    export const BarChart3 = Icon;
    export const Settings = Icon;
    export const LogOut = Icon;
    export const Menu = Icon;
    export const X = Icon;
    export const Shield = Icon;
    export const ChevronRight = Icon;
    export const LifeBuoy = Icon;
    export const Award = Icon;
  `);
  writeStub(bellFile, `import React from 'react'; export default function NotificationBell() { return React.createElement('button', { type: 'button', 'aria-label': 'Notifications' }); }`);

  const source = fs.readFileSync(layoutFile, 'utf8')
    .replace("from 'react';", `from ${JSON.stringify(hooksFile.href)};`)
    .replace("from 'react-router-dom';", `from ${JSON.stringify(routerFile.href)};`)
    .replace("from '../../store/authStore';", `from ${JSON.stringify(authFile.href)};`)
    .replace("from 'lucide-react';", `from ${JSON.stringify(iconsFile.href)};`)
    .replace("from '../notifications/NotificationBell';", `from ${JSON.stringify(bellFile.href)};`);
  const transformed = await transformWithEsbuild(source, layoutFile.pathname, { loader: 'jsx', jsx: 'automatic' });
  fs.writeFileSync(moduleFile, transformed.code);
  shell = await import(`${moduleFile.href}?ui5=${process.pid}`);
  hooks = await import(hooksFile.href);
} finally {
  fs.rmSync(moduleFile, { force: true });
  fs.rmSync(hooksFile, { force: true });
  fs.rmSync(routerFile, { force: true });
  fs.rmSync(authFile, { force: true });
  fs.rmSync(iconsFile, { force: true });
  fs.rmSync(bellFile, { force: true });
}

function renderShell() {
  hooks.__beginRender();
  return shell.default({ children: React.createElement('section', null, 'Admin content') });
}

test('UI5 admin shell renders named, associated mobile menu controls through React DOM', () => {
  hooks.__reset();
  hooks.__beginRender();
  const html = renderToStaticMarkup(React.createElement(shell.default, null, 'Admin content'));

  assert.match(html, /<aside[^>]*id="admin-navigation"[^>]*aria-label="Administration navigation"/);
  assert.match(html, /<button[^>]*type="button"[^>]*aria-label="Open administration menu"[^>]*aria-controls="admin-navigation"[^>]*aria-expanded="false"/);
  assert.match(html, /<button[^>]*type="button"[^>]*aria-label="Close administration menu"[^>]*aria-controls="admin-navigation"/);
  assert.match(html, /aria-label="My support tickets"/);
  assert.match(html, /focus-visible:ring-cyan-400/);
});

test('UI5 admin shell opens its mobile menu, returns focus from close, and handles Escape', () => {
  const originalDocument = globalThis.document;
  const originalWindow = globalThis.window;
  const frames = new Map();
  let nextFrame = 0;
  globalThis.window = {
    requestAnimationFrame(callback) { frames.set(++nextFrame, callback); return nextFrame; },
    cancelAnimationFrame(id) { frames.delete(id); },
  };
  const paint = () => { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback()); };
  const listeners = new Map();
  const documentStub = {
    addEventListener(type, listener) { listeners.set(type, listener); },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) listeners.delete(type);
    },
  };
  globalThis.document = documentStub;

  try {
    hooks.__reset();
    let tree = renderShell();
    hooks.__flushEffects();

    const openButton = findElement(tree, (element) => element.type === 'button' && element.props['aria-label'] === 'Open administration menu');
    const closeButton = findElement(tree, (element) => element.type === 'button' && element.props['aria-label'] === 'Close administration menu');
    assert.ok(openButton, 'the mobile-menu trigger is rendered');
    assert.ok(closeButton, 'the close control is rendered');
    assert.equal(openButton.props['aria-expanded'], false);

    const focusLog = [];
    openButton.ref.current = { focus: () => focusLog.push('open') };
    closeButton.ref.current = { focus: () => focusLog.push('close') };

    openButton.props.onClick();
    tree = renderShell();
    hooks.__flushEffects();
    assert.deepEqual(focusLog, [], 'focus must wait until the sidebar is visible');
    paint();
    assert.deepEqual(focusLog, [], 'first frame only schedules focus after paint');
    paint();

    const openMenuButton = findElement(tree, (element) => element.type === 'button' && element.props['aria-label'] === 'Open administration menu');
    const openedCloseButton = findElement(tree, (element) => element.type === 'button' && element.props['aria-label'] === 'Close administration menu');
    const openedSidebar = findElement(tree, (element) => element.type === 'aside');
    assert.equal(openMenuButton.props['aria-expanded'], true);
    assert.match(openedSidebar.props.className, /visible translate-x-0/);
    assert.deepEqual(focusLog, ['close']);
    assert.ok(listeners.has('keydown'), 'an open mobile menu listens for Escape');

    openedCloseButton.props.onClick();
    tree = renderShell();
    hooks.__flushEffects();

    let closedMenuButton = findElement(tree, (element) => element.type === 'button' && element.props['aria-label'] === 'Open administration menu');
    let closedSidebar = findElement(tree, (element) => element.type === 'aside');
    assert.equal(closedMenuButton.props['aria-expanded'], false);
    assert.match(closedSidebar.props.className, /invisible/);
    assert.deepEqual(focusLog, ['close', 'open']);
    assert.equal(listeners.has('keydown'), false);

    closedMenuButton.props.onClick();
    tree = renderShell();
    hooks.__flushEffects();
    paint();
    paint();
    assert.deepEqual(focusLog, ['close', 'open', 'close']);
    assert.ok(listeners.has('keydown'), 'the reopened menu listens for Escape');

    let prevented = false;
    listeners.get('keydown')({ key: 'Escape', preventDefault: () => { prevented = true; } });
    tree = renderShell();
    hooks.__flushEffects();

    closedMenuButton = findElement(tree, (element) => element.type === 'button' && element.props['aria-label'] === 'Open administration menu');
    closedSidebar = findElement(tree, (element) => element.type === 'aside');
    assert.equal(prevented, true);
    assert.equal(closedMenuButton.props['aria-expanded'], false);
    assert.match(closedSidebar.props.className, /invisible/);
    assert.deepEqual(focusLog, ['close', 'open', 'close', 'open']);
    assert.equal(listeners.has('keydown'), false);
    closedMenuButton.props.onClick();
    tree = renderShell();
    hooks.__flushEffects();
    assert.equal(frames.size, 1);
    findElement(tree, (element) => element.type === 'button' && element.props['aria-label'] === 'Close administration menu').props.onClick();
    tree = renderShell();
    hooks.__flushEffects();
    assert.equal(frames.size, 0, 'closing before paint cancels stale focus');
  } finally {
    globalThis.document = originalDocument;
    globalThis.window = originalWindow;
  }
});
