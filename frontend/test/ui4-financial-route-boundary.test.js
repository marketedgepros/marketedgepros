import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');

test('financial screens have no floating chat overlay and retain the existing route guards', () => {
  assert.match(app, /\['\/wallet', '\/trader\/withdrawals', '\/admin\/withdrawals'\]\.includes\(location\.pathname\)\) return null/);
  assert.match(app, /path="\/wallet"[\s\S]*?<ProtectedRoute userOnly=\{true\}>[\s\S]*?<UserLayout>[\s\S]*?<Wallet\s*\/>/);
  assert.match(app, /path="\/trader\/withdrawals"[\s\S]*?<RoleGuard allowedRoles=\{\['trader'\]\}>[\s\S]*?<UserLayout>[\s\S]*?<Withdrawals\s*\/>/);
  assert.match(app, /path="\/admin\/withdrawals"[\s\S]*?<RoleGuard allowedRoles=\{ADMIN_ROLES\}>[\s\S]*?<AdminLayout>[\s\S]*?<WithdrawalManagement\s*\/>/);
});
