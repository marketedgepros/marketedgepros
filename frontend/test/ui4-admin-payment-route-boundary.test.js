import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
test('administrative payment routes retain protected role and single layout boundaries', () => {
  for (const path of ['/admin/payments', '/admin/payment-approvals']) {
    const position = app.indexOf(`path="${path}"`);
    assert.ok(position > 0);
    const route = app.slice(position, app.indexOf('/>', position) + 2);
    assert.match(route, /ProtectedRoute/);
    assert.match(route, /RoleGuard allowedRoles=\{ADMIN_ROLES\}/);
    assert.match(route, /AdminLayout/);
  }
});
test('administrative payment records have no floating chat covering amounts', () => {
  const source = app.slice(app.indexOf('function AccountChatWidget'), app.indexOf('function App()'));
  assert.match(source, /\['\/admin\/payments', '\/admin\/payment-approvals'\]\.includes\(location\.pathname\)\) return null/);
});
