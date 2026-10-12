import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';

const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');

test('admin insight routes preserve existing authentication, role and single layout boundaries', () => {
  for (const route of ['/admin', '/admin/dashboard', '/admin/analytics']) {
    const start = app.indexOf(`path="${route}"`);
    assert.ok(start >= 0, route);
    const source = app.slice(start, app.indexOf('/>', start) + 2);
    assert.match(source, /<ProtectedRoute>/);
    assert.match(source, /<RoleGuard allowedRoles=\{ADMIN_ROLES\}>/);
    assert.equal((source.match(/<AdminLayout>/g) || []).length, 1);
  }
});

test('admin record summaries have no floating chat overlay and retain normal support navigation', async () => {
  const source = app.slice(app.indexOf('function AccountChatWidget()'), app.indexOf('function App()'));
  const file = new URL(`../node_modules/.ui4-chat-boundary-${process.pid}.mjs`, import.meta.url);
  const input = `import React from 'react';
let path = '/';
const useLocation = () => ({ pathname: path });
const ChatWidget = () => React.createElement('div', { 'data-chat': 'true' });
${source}
export const setPath = next => { path = next; };
export default AccountChatWidget;`;
  try {
    const transformed = await transformWithEsbuild(input, 'chat-boundary.jsx', { loader: 'jsx', jsx: 'automatic' });
    writeFileSync(file, transformed.code);
    const widget = await import(file.href);
    for (const route of ['/admin', '/admin/dashboard', '/admin/analytics', '/admin/users',
      '/admin/programs', '/admin/challenges', '/admin/crm', '/admin/crm/100',
      '/admin/kyc-approval', '/admin/settings']) {
      widget.setPath(route);
      assert.equal(renderToStaticMarkup(React.createElement(widget.default)), '', route);
    }
    widget.setPath('/trader');
    assert.match(renderToStaticMarkup(React.createElement(widget.default)), /data-chat="true"/);
  } finally {
    rmSync(file, { force: true });
  }
  const layout = readFileSync(new URL('../src/components/admin/AdminLayout.jsx', import.meta.url), 'utf8');
  assert.match(layout, /to="\/support\/my-tickets"/);
});

test('administration shell replaces placeholder search with real support and labels navigation', () => {
  const layout = readFileSync(new URL('../src/components/admin/AdminLayout.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(layout, /Press Enter to search|isSearchOpen|search-dropdown|animate-pulse/);
  assert.match(layout, /to="\/support\/my-tickets"/);
  assert.match(layout, /aria-label="Open administration menu"/);
  assert.match(layout, /aria-expanded=\{isMobileMenuOpen\}/);
  assert.match(layout, /min-w-0 flex-1 overflow-y-auto/);
});
