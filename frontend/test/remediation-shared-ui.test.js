import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const sourceRoot = new URL('../src/', import.meta.url);
const readSource = (path) => readFile(new URL(path, sourceRoot), 'utf8');

test('shared shells use the dialog focus contract and isolate the mobile background', async () => {
  const shellPaths = [
    'components/trader/TraderLayout.jsx',
    'components/agent/AgentLayout.jsx',
    'components/admin/AdminLayout.jsx',
  ];

  for (const path of shellPaths) {
    const source = await readSource(path);
    assert.match(source, /useDialogFocus\(\{ open: (?:sidebarOpen|isMobileMenuOpen), onClose:/, `${path} adopts the focus hook`);
    assert.match(source, /data-autofocus/, `${path} supplies an initial drawer target`);
    assert.match(source, /aria-hidden=\{(?:sidebarOpen|isMobileMenuOpen) \? true : undefined\}/, `${path} hides the background from assistive technology`);
    assert.match(source, /inert=\{(?:sidebarOpen|isMobileMenuOpen) \? '' : undefined\}/, `${path} makes the background inactive`);
  }
});

test('admin dialogs, detail retry, SPA links, and dashboard aliases retain their contracts', async () => {
  const [users, challenges, dashboard, insight, layout] = await Promise.all([
    readSource('pages/admin/UserManagementConnected.jsx'),
    readSource('pages/admin/ChallengesManagement.jsx'),
    readSource('pages/admin/AdminDashboardConnected.jsx'),
    readSource('components/admin/AdminInsightUI.jsx'),
    readSource('components/admin/AdminLayout.jsx'),
  ]);

  assert.match(users, /const dialogRef = useDialogFocus\(\{ open: true, onClose \}\)/);
  assert.match(challenges, /const dialogRef = useDialogFocus\(\{ open: true, onClose \}\)/);
  assert.match(challenges, /onRetry=\{\(\) => openDetail\(selectedId\)\}/);
  assert.match(challenges, /expectedOwner: principal\.owner/);
  assert.match(dashboard, /<Link key=\{href\} to=\{href\}/);
  assert.match(insight, /<Link key=\{card\.key\} to=\{card\.href\}/);
  assert.match(layout, /path === '\/admin\/dashboard' && location\.pathname === '\/admin'/);
  assert.match(dashboard, /location\.pathname === "\/admin" \? "\/admin\/dashboard" : location\.pathname/);
});

test('pagination stays accurate at zero pages and commissions retain controls during a guarded load', async () => {
  const [payments, affiliateUi, commissions, users, challenges] = await Promise.all([
    readSource('components/admin/AdminPaymentRecordUI.jsx'),
    readSource('components/affiliate/AffiliateRecordUI.jsx'),
    readSource('pages/agent/Commissions.jsx'),
    readSource('pages/admin/UserManagementConnected.jsx'),
    readSource('pages/admin/ChallengesManagement.jsx'),
  ]);

  assert.match(payments, /if \(pagination\.pages === 0\)/);
  assert.match(affiliateUi, /if \(pagination\.pages === 0\)/);
  assert.match(users, /No server pages are available for these filters\./);
  assert.match(challenges, /No server pages are available for this scoped result\./);
  assert.match(commissions, /pagination=\{pagination\} onPage=\{onPage\} disabled=\{loading\}/);
  assert.match(commissions, /if \(read\.loading \|\| pendingPageRef\.current !== null \|\| nextPage === page\) return;/);
  assert.match(commissions, /lastPagination\?\.principalKey === read\.principalKey/);
  assert.match(affiliateUi, /Loading requested page \{loadingPage\}/);
});

test('the three audited nested-main pages use the shell landmark and internal links remain SPA links', async () => {
  const [faq, rules, traders, footer] = await Promise.all([
    readSource('pages/FAQ.jsx'),
    readSource('pages/TradingRules.jsx'),
    readSource('pages/agent/TradersManagement.jsx'),
    readSource('components/layout/LandingFooter.jsx'),
  ]);

  for (const [path, source] of [['FAQ', faq], ['TradingRules', rules], ['TradersManagement', traders]]) {
    assert.doesNotMatch(source, /<main\b/, `${path} does not add a nested main landmark`);
  }
  assert.match(faq, /<Link to="\/programs"/);
  assert.match(rules, /<Link to="\/programs"/);
  assert.match(footer, /Information and help/);
  assert.match(footer, /View contact options/);
  assert.match(footer, /message submission are unavailable/);
});
