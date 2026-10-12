import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { accountHome, postLoginDestination, programCheckoutPath } from '../src/services/navigationService.js';

const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
const routePaths = [...app.matchAll(/<Route\s+path="([^"]+)"/g)].map((entry) => entry[1]);

test('active router has exactly one declaration per URL', () => {
  assert.equal(routePaths.length, new Set(routePaths).size);
  assert.equal(routePaths.filter((value) => value === '/affiliate').length, 1);
  for (const value of ['/affiliate/dashboard', '/affiliate/payout', '/user/dashboard']) {
    assert.ok(routePaths.includes(value), value);
  }
});

test('authenticated account homes exist and never return the dispatcher itself', () => {
  for (const role of ['affiliate', 'user', 'trader', 'supermaster', 'master']) {
    const path = accountHome({ role });
    assert.ok(routePaths.includes(path), path);
    assert.notEqual(path, '/dashboard');
  }
  assert.equal(accountHome(null), '/');
  assert.equal(accountHome({ role: 'unsupported' }), '/');
});

test('affiliate public landing and private dashboard/payout have separate guards', () => {
  assert.match(app, /path="\/affiliate" element=\{<AffiliateLanding\s*\/>\}/);
  assert.match(app, /path="\/affiliate\/dashboard"[\s\S]{0,500}<ProtectedRoute>[\s\S]{0,100}<RoleGuard allowedRoles=\{\['affiliate'\]\}>[\s\S]{0,100}<AffiliateDashboard\s*\/>/);
  assert.match(app, /path="\/affiliate\/payout" element=\{<ProtectedRoute><RoleGuard allowedRoles=\{\['affiliate'\]\}><UserLayout><AffiliatePayout\s*\/>/);
});

test('canonical checkout IDs reject ambiguous input and resolve to existing template', () => {
  assert.equal(programCheckoutPath(17), '/programs/17/checkout');
  assert.ok(routePaths.includes('/programs/:programId/checkout'));
  for (const id of [null, 0, -1, '01', 'abc', '../admin', '1/2', '1e2', 1.5, '12345678901']) {
    assert.throws(() => programCheckoutPath(id), /Invalid program/);
  }
  const lightning = fs.readFileSync(new URL('../src/pages/LightningChallenge.jsx', import.meta.url), 'utf8');
  assert.match(lightning, /<CatalogPreview[^>]+type="lightning"/);
  const preview = fs.readFileSync(new URL('../src/components/programs/CatalogPreview.jsx', import.meta.url), 'utf8');
  assert.match(preview, /CatalogCard/);
  const card = fs.readFileSync(new URL('../src/components/programs/CatalogUI.jsx', import.meta.url), 'utf8');
  assert.match(card, /to=\{`\/programs\/\$\{program.id\}`\}/);
  assert.doesNotMatch(lightning, /navigate\(`\/checkout/);
});

test('login and 2FA share the same destination and preserve valid local workflow', () => {
  assert.equal(postLoginDestination({ role: 'user' }, '?redirect=%2Fprograms%2F17%2Fcheckout'), '/programs/17/checkout');
  assert.equal(postLoginDestination({ role: 'user' }, '?redirect=%2Fsupport%2Fmy-tickets'), '/support/my-tickets');
  assert.equal(postLoginDestination({ role: 'affiliate' }, '?redirect=%2Faffiliate%2Freports'), '/affiliate/reports');
  const login = fs.readFileSync(new URL('../src/pages/Login.jsx', import.meta.url), 'utf8');
  assert.equal([...login.matchAll(/postLoginDestination\(result.user, location.search\)/g)].length, 2);
});

test('untrusted destinations cannot redirect outside site, to auth loops or private roles', () => {
  const user = { role: 'user' };
  for (const path of ['https://evil.test', '//evil.test', '/\\evil.test', '/login', '/register', '/auth/login', '/missing', '/admin', '/affiliate/dashboard', '/trader', '/%2f%2fevil.test', '/faq\n', '/faq%0a', '/affiliate/dashboard/']) {
    assert.equal(postLoginDestination(user, `?redirect=${encodeURIComponent(path)}`), '/user/dashboard', path);
  }
  assert.equal(postLoginDestination({ role: 'affiliate' }, '?redirect=/admin/settings'), '/affiliate/dashboard');
});

test('active affiliate sidebar points to dashboard, while footer keeps public landing', () => {
  const menu = fs.readFileSync(new URL('../src/components/agent/AgentLayout.jsx', import.meta.url), 'utf8');
  assert.match(menu, /name: 'Dashboard', href: '\/affiliate\/dashboard'/);
  assert.doesNotMatch(menu, /to="\/affiliate"/);
  const footer = fs.readFileSync(new URL('../src/components/layout/LandingFooter.jsx', import.meta.url), 'utf8');
  assert.match(footer, /to: '\/affiliate'/);
});

test('router owns layouts for account menu destinations; identity changes remount content', () => {
  for (const page of ['pages/user/Profile.jsx', 'pages/trader/TradingHistory.jsx', 'pages/trader/Withdrawals.jsx']) {
    const source = fs.readFileSync(new URL(`../src/${page}`, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /<(?:UserLayout|TraderLayout)[\s>]/, page);
  }
  const layout = fs.readFileSync(new URL('../src/components/layout/UserLayout.jsx', import.meta.url), 'utf8');
  assert.match(layout, /<Fragment key=\{identityKey\}>\{children\}<\/Fragment>/);
});

test('affiliate link registration does not invent an affiliate role or navigate unauthorized user', () => {
  const landing = fs.readFileSync(new URL('../src/pages/affiliate/AffiliateLanding.jsx', import.meta.url), 'utf8');
  assert.match(landing, /if \(user.role === 'affiliate'\) \{\s*navigate\('\/affiliate\/dashboard'\)/);
  const registrationBlock = landing.match(/const registration = await registerAffiliate\(\);[\s\S]*?catch \(requestError\)/)[0];
  assert.doesNotMatch(registrationBlock, /navigate\(|updateUser\(|role:\s*['"]affiliate/);
  assert.match(registrationBlock, /does not create a commission or confirm eligibility for a payout/);
});
