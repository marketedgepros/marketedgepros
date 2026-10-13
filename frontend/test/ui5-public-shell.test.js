import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

async function compileModule(name, source) {
  const file = new URL(`../src/components/layout/${name}.jsx`, import.meta.url);
  const transformed = await transformWithEsbuild(source, file.pathname, {
    loader: 'jsx',
    jsx: 'automatic',
  });
  const target = new URL(
    `../node_modules/.cache-ui5-public-shell-${name}-${process.pid}-${Date.now()}.mjs`,
    import.meta.url,
  );

  fs.writeFileSync(target, transformed.code);
  try {
    return await import(target.href);
  } finally {
    fs.rmSync(target, { force: true });
  }
}

function renderWithRouter(Component, props = {}) {
  return renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(Component, props),
    ),
  );
}

async function loadNavbar(auth) {
  const file = new URL('../src/components/layout/LandingNavbar.jsx', import.meta.url);
  const source = fs
    .readFileSync(file, 'utf8')
    .replace(
      "import useAuthStore from '../../store/authStore';",
      `const useAuthStore = () => (${JSON.stringify(auth)});`,
    );
  return compileModule('LandingNavbar', source);
}

async function loadFooter() {
  const file = new URL('../src/components/layout/LandingFooter.jsx', import.meta.url);
  return compileModule('LandingFooter', fs.readFileSync(file, 'utf8'));
}

async function loadLayout() {
  const file = new URL('../src/components/layout/Layout.jsx', import.meta.url);
  const source = fs
    .readFileSync(file, 'utf8')
    .replace(
      "import LandingNavbar from './LandingNavbar';",
      "const LandingNavbar = () => <nav data-shell=\"navbar\" />;",
    )
    .replace(
      "import LandingFooter from './LandingFooter';",
      "const LandingFooter = () => <footer data-shell=\"footer\" />;",
    );
  return compileModule('Layout', source);
}

function findElement(node, matches) {
  if (!node || typeof node !== 'object') return null;
  if (matches(node)) return node;
  const children = node.props?.children;
  for (const child of React.Children.toArray(children)) {
    const found = findElement(child, matches);
    if (found) return found;
  }
  return null;
}

async function loadMobileMenuBehaviorHarness() {
  const file = new URL('../src/components/layout/LandingNavbar.jsx', import.meta.url);
  const harness = `import React from 'react';
let mobileMenuOpen = false;
let capturedEffect = null;
let focused = 0;
let removeCalls = 0;
const menuButton = { focus: () => { focused += 1; } };
globalThis.window = {
  addEventListener: (type, listener) => {
    if (type === 'keydown') globalThis.window.__ui5EscapeListener = listener;
  },
  removeEventListener: (type, listener) => {
    if (type === 'keydown' && globalThis.window.__ui5EscapeListener === listener) {
      delete globalThis.window.__ui5EscapeListener;
      removeCalls += 1;
    }
  },
};
const useState = () => [mobileMenuOpen, (next) => {
  mobileMenuOpen = typeof next === 'function' ? next(mobileMenuOpen) : next;
}];
const useRef = () => ({ current: menuButton });
const useEffect = (effect) => { capturedEffect = effect; };
export const __mobileMenuOpen = () => mobileMenuOpen;
export const __focused = () => focused;
export const __runEffect = () => capturedEffect?.();
export const __removeCalls = () => removeCalls;
`;
  const source = fs
    .readFileSync(file, 'utf8')
    .replace("import React, { useEffect, useRef, useState } from 'react';", harness)
    .replace(
      "import { Link, useNavigate } from 'react-router-dom';",
      "const Link = ({ children }) => children; const useNavigate = () => () => {};",
    )
    .replace(
      "import { Menu, X, LogOut } from 'lucide-react';",
      "const Menu = () => null; const X = () => null; const LogOut = () => null;",
    )
    .replace(
      "import useAuthStore from '../../store/authStore';",
      "const useAuthStore = () => ({ isAuthenticated: false, user: null, logout: async () => {} });",
    );
  return compileModule('LandingNavbarBehavior', source);
}

test('compiled public navbar renders named controls and preserves guest destinations', async () => {
  const { default: LandingNavbar } = await loadNavbar({
    isAuthenticated: false,
    user: null,
    logout: async () => {},
  });
  const html = renderWithRouter(LandingNavbar);

  assert.match(html, /<nav aria-label="Primary navigation"/);
  assert.match(html, /aria-label="Open navigation"/);
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /aria-controls="mobile-navigation"/);
  assert.match(html, /href="\/login"/);
  assert.match(html, /href="\/programs"/);
  assert.doesNotMatch(html, /id="mobile-navigation"/);
  assert.match(html, /min-h-11 min-w-11/);
  assert.match(html, /focus-visible:ring-cyan-300/);
});

test('compiled public navbar preserves authenticated actions without changing identity data', async () => {
  const { default: LandingNavbar } = await loadNavbar({
    isAuthenticated: true,
    user: { first_name: 'Ada' },
    logout: async () => {},
  });
  const html = renderWithRouter(LandingNavbar);

  assert.match(html, /href="\/dashboard"/);
  assert.match(html, />Ada</);
  assert.match(html, />Logout</);
  assert.doesNotMatch(html, />Login</);
});

test('compiled mobile menu toggles, closes on Escape and returns focus to its trigger', async () => {
  const navbar = await loadMobileMenuBehaviorHarness();
  const closedTree = navbar.default();
  const trigger = findElement(
    closedTree,
    (element) => element.type === 'button' && element.props?.['aria-controls'] === 'mobile-navigation',
  );

  assert.ok(trigger, 'the mobile menu trigger is rendered');
  assert.equal(trigger.props['aria-expanded'], false);
  trigger.props.onClick();
  assert.equal(navbar.__mobileMenuOpen(), true);

  const openTree = navbar.default();
  const menu = findElement(
    openTree,
    (element) => element.props?.id === 'mobile-navigation',
  );
  assert.equal(menu.props.role, 'region');
  assert.equal(menu.props['aria-label'], 'Mobile navigation');

  const cleanup = navbar.__runEffect();
  let prevented = false;
  window.__ui5EscapeListener({
    key: 'Escape',
    preventDefault: () => { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(navbar.__mobileMenuOpen(), false);
  assert.equal(navbar.__focused(), 1);
  cleanup();
  assert.equal(navbar.__removeCalls(), 1);
});

test('compiled footer renders accessible icon links, bounded wrapping and supported destinations', async () => {
  const { default: LandingFooter } = await loadFooter();
  const html = renderWithRouter(LandingFooter);

  for (const name of ['Facebook', 'Twitter', 'Instagram', 'LinkedIn', 'YouTube', 'Discord']) {
    assert.match(html, new RegExp(`aria-label="${name}"`));
  }
  assert.match(html, /target="_blank" rel="noopener noreferrer"/);
  assert.match(html, /flex flex-wrap gap-2/);
  assert.match(html, /flex flex-wrap items-center justify-center gap-x-6 gap-y-2/);
  assert.match(html, /href="\/contact"/);
  assert.doesNotMatch(html, /<form/);
  assert.match(html, /focus-visible:ring-cyan-300/);
});

test('compiled layout keeps the public chrome and lets content shrink below fixed-width children', async () => {
  const { default: Layout } = await loadLayout();
  const html = renderToStaticMarkup(
    React.createElement(Layout, null, React.createElement('section', null, 'Public content')),
  );

  assert.match(html, /data-shell="navbar"/);
  assert.match(html, /<main class="mep-page min-w-0 flex-grow pt-16">/);
  assert.match(html, /Public content/);
  assert.match(html, /data-shell="footer"/);
});
