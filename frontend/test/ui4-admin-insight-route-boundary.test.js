import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

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

test('admin record summaries have no floating chat overlay and retain normal support navigation', () => {
  const source = app.slice(app.indexOf('function AccountChatWidget()'), app.indexOf('function App()'));
  assert.match(source, /\['\/admin', '\/admin\/dashboard', '\/admin\/analytics'\]\.includes\(location\.pathname\)\) return null/);
  const layout = readFileSync(new URL('../src/components/admin/AdminLayout.jsx', import.meta.url), 'utf8');
  assert.match(layout, /support/);
});

test('administration shell replaces placeholder search with real support and labels navigation', () => {
  const layout = readFileSync(new URL('../src/components/admin/AdminLayout.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(layout, /Press Enter to search|isSearchOpen|search-dropdown|animate-pulse/);
  assert.match(layout, /to="\/support\/my-tickets"/);
  assert.match(layout, /aria-label="Open administration menu"/);
  assert.match(layout, /aria-expanded=\{isMobileMenuOpen\}/);
  assert.match(layout, /min-w-0 flex-1 overflow-y-auto/);
});
