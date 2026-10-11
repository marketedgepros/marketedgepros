import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const appPath = path.join(frontendDirectory, 'src', 'App.jsx');
const appSource = fs.readFileSync(appPath, 'utf8');

function resolveModule(fromPath, specifier) {
  const candidate = path.resolve(path.dirname(fromPath), specifier);
  const candidates = [
    candidate,
    `${candidate}.js`,
    `${candidate}.jsx`,
    path.join(candidate, 'index.js'),
    path.join(candidate, 'index.jsx'),
  ];

  return candidates.find((filePath) => fs.existsSync(filePath));
}

test('App lazy-route component inventory resolves to tracked source modules', () => {
  const imports = [...appSource.matchAll(/const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\(['"]([^'"]+)['"]\)\)/g)];

  assert.ok(imports.length > 0, 'App must declare lazy route components');
  for (const [, componentName, specifier] of imports) {
    assert.ok(
      resolveModule(appPath, specifier),
      `${componentName} must resolve from ${specifier}`,
    );
  }
});

test('affiliate management routes use canonical agent pages and keep their role guards', () => {
  for (const componentName of ['TradersManagement', 'Commissions', 'Reports']) {
    assert.match(
      appSource,
      new RegExp(`const\\s+${componentName}\\s*=\\s*lazy\\(\\(\\)\\s*=>\\s*import\\(['"]\\.\\/pages\\/agent\\/${componentName}['"]\\)\\)`),
    );
  }
  assert.match(
    appSource,
    /path="\/affiliate\/traders"[\s\S]{0,500}allowedRoles=\{\['affiliate'\]\}/,
  );
  for (const componentName of ['TradersManagement', 'Commissions', 'Reports']) {
    assert.match(
      fs.readFileSync(path.join(frontendDirectory, 'src', 'pages', 'agent', `${componentName}.jsx`), 'utf8'),
      new RegExp(`export default function ${componentName}\\(\\)`),
    );
  }
});

test('frontend build script remains a Vite production build smoke command', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(frontendDirectory, 'package.json'), 'utf8'));
  assert.equal(packageJson.scripts.build, 'vite build');
});

test('challenge routes use single router-owned layouts and the administrative route retains role guards', () => {
  const adminRoute = appSource.match(/<Route\s+path="\/admin\/challenges"[\s\S]*?<\/Route>|<Route\s+path="\/admin\/challenges"[\s\S]*?\n\s*\/>/);
  assert.ok(adminRoute, 'administration challenge page must be wired into App');
  assert.match(adminRoute[0], /<ProtectedRoute>/);
  assert.match(adminRoute[0], /<RoleGuard allowedRoles=\{ADMIN_ROLES\}>/);
  assert.match(adminRoute[0], /<AdminLayout>[\s\S]*<ChallengesManagement\s*\/>/);
  const menu = fs.readFileSync(path.join(frontendDirectory, 'src/components/admin/AdminLayout.jsx'), 'utf8');
  assert.match(menu, /path: '\/admin\/challenges'/);
  for (const page of ['pages/user/MyChallenges.jsx', 'pages/ChallengeDetails.jsx']) {
    const source = fs.readFileSync(path.join(frontendDirectory, 'src', page), 'utf8');
    assert.doesNotMatch(source, /<UserLayout|<Layout[\s>]/);
  }
});

test('support account views are protected without making public help articles private', () => {
  for (const [route, component] of [
    ['/support/create-ticket', 'CreateTicket'],
    ['/support/my-tickets', 'MyTickets'],
    ['/support/ticket/:ticketNumber', 'TicketDetail'],
  ]) {
    assert.ok(appSource.includes(`path="${route}" element={<ProtectedRoute><${component} /></ProtectedRoute>}`));
  }
  assert.ok(appSource.includes('path="/support" element={<SupportHub />}'));
  assert.ok(appSource.includes('path="/support/:slug" element={<Article />}'));
});

test('notification views have one router-owned layout and one bell in each active layout', () => {
  for (const page of ['pages/Notifications.jsx', 'pages/settings/NotificationSettings.jsx']) {
    const source = fs.readFileSync(path.join(frontendDirectory, 'src', page), 'utf8');
    assert.doesNotMatch(source, /<UserLayout[\s>]/);
  }
  for (const layout of ['admin/AdminLayout.jsx', 'trader/TraderLayout.jsx', 'agent/AgentLayout.jsx']) {
    const source = fs.readFileSync(path.join(frontendDirectory, 'src/components', layout), 'utf8');
    assert.equal([...source.matchAll(/<NotificationBell\s*\/>/g)].length, 1, layout);
    assert.doesNotMatch(source, /<NotificationDropdown[\s>]/);
  }
  assert.match(appSource, /useAuthStore\.subscribe/);
  assert.match(appSource, /useNotificationStore\.getState\(\)\.reset\(\)/);
});
