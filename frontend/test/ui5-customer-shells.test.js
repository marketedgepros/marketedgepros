import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const traderFile = new URL('../src/components/trader/TraderLayout.jsx', import.meta.url);
const affiliateFile = new URL('../src/components/agent/AgentLayout.jsx', import.meta.url);
const userLayoutFile = new URL('../src/components/layout/UserLayout.jsx', import.meta.url);
const cache = (name) => new URL(`../node_modules/.ui5-customer-shells-${name}-${process.pid}.mjs`, import.meta.url);
const traderAuthFixture = cache('trader-auth');
const affiliateAuthFixture = cache('affiliate-auth');
const loadingAuthFixture = cache('loading-auth');
const navigationFixture = cache('navigation');
const bellFixture = cache('bell');
const rolesFixture = cache('roles');
const dialogFocus = new URL('../src/hooks/useDialogFocus.js', import.meta.url).href;
const traderTarget = cache('trader-layout');
const affiliateTarget = cache('affiliate-layout');
const userLayoutTarget = cache('user-layout');

const writeAuthFixture = (target, user) => {
  fs.writeFileSync(target, `export default function useAuthStore() { return { user: ${JSON.stringify(user)}, logout: () => {} }; }\n`);
};

const compile = async (file, target, replacements) => {
  let source = fs.readFileSync(file, 'utf8');
  for (const [from, to] of replacements) source = source.replaceAll(from, JSON.stringify(to));
  const transformed = await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' });
  fs.writeFileSync(target, transformed.code);
  return import(`${target.href}?ui5=${process.pid}`);
};

let TraderLayout;
let AffiliateLayout;
let UserLayout;
try {
  writeAuthFixture(traderAuthFixture, { id: 21, role: 'trader', first_name: 'Taylor', email: 'taylor@example.test' });
  writeAuthFixture(affiliateAuthFixture, { id: 22, role: 'affiliate', first_name: 'Avery', email: 'avery@example.test' });
  writeAuthFixture(loadingAuthFixture, null);
  fs.writeFileSync(navigationFixture, "export const accountHome = (user) => user?.role === 'trader' ? '/trader' : '/';\n");
  fs.writeFileSync(bellFixture, "import React from 'react'; export default function NotificationBell() { return React.createElement('button', { type: 'button', 'aria-label': 'Notifications' }, 'Notifications'); }\n");
  fs.writeFileSync(rolesFixture, 'export const ADMIN_ROLES = [];\n');

  TraderLayout = (await compile(traderFile, traderTarget, [
    ["'../../store/authStore'", traderAuthFixture.href],
    ["'../notifications/NotificationBell'", bellFixture.href],
    ["'../../services/navigationService.js'", navigationFixture.href],
    ["'../../hooks/useDialogFocus.js'", dialogFocus],
  ])).default;
  AffiliateLayout = (await compile(affiliateFile, affiliateTarget, [
    ["'../../store/authStore'", affiliateAuthFixture.href],
    ["'../notifications/NotificationBell'", bellFixture.href],
    ["'../../hooks/useDialogFocus.js'", dialogFocus],
  ])).default;
  UserLayout = (await compile(userLayoutFile, userLayoutTarget, [
    ["'../../store/authStore'", loadingAuthFixture.href],
    ["'../../constants/roles'", rolesFixture.href],
  ])).default;
} finally {
  [traderTarget, affiliateTarget, userLayoutTarget, traderAuthFixture, affiliateAuthFixture, loadingAuthFixture, navigationFixture, bellFixture, rolesFixture]
    .forEach((target) => fs.rmSync(target, { force: true }));
}

const renderShell = (Component, route) => renderToStaticMarkup(
  React.createElement(
    MemoryRouter,
    { initialEntries: [route] },
    React.createElement(Component, null, React.createElement('section', null, 'Shell content')),
  ),
);

const requireRendered = (html, expected, message) => {
  assert.ok(html.includes(expected), `${message}: ${expected}`);
};

test('מעטפות הסוחר והאפיליאט המרונדרות חושפות בקרי תפריט נגישים, נתיב פעיל ותוכן מצומצם', () => {
  const shells = [
    { Component: TraderLayout, route: '/trader', sidebar: 'trader-navigation', navLabel: 'Account navigation', activeHref: '/trader' },
    { Component: AffiliateLayout, route: '/affiliate/dashboard', sidebar: 'affiliate-navigation', navLabel: 'Affiliate navigation', activeHref: '/affiliate/dashboard' },
  ];

  for (const shell of shells) {
    const html = renderShell(shell.Component, shell.route);
    requireRendered(html, `id="${shell.sidebar}"`, 'ה־sidebar הפעיל מקבל מזהה לבקר המובייל');
    requireRendered(html, `aria-label="${shell.navLabel}"`, 'ל־sidebar יש שם נגיש');
    requireRendered(html, `aria-controls="${shell.sidebar}"`, 'לחצן פתיחת התפריט מצביע על ה־sidebar');
    requireRendered(html, 'aria-expanded="false"', 'מצב התפריט הראשוני מפורש');
    requireRendered(html, 'aria-label="Open navigation menu"', 'לחצן אייקון הפתיחה מתויג');
    requireRendered(html, 'aria-label="Close navigation menu"', 'לחצן אייקון הסגירה מתויג');
    requireRendered(html, `href="${shell.activeHref}"`, 'לנתיב הפעיל יש יעד אמיתי');
    requireRendered(html, 'aria-current="page"', 'הקישור של הנתיב הפעיל מסומן לקורא מסך');
    requireRendered(html, 'focus-visible:ring-cyan-400', 'פעולות המעטפת מציגות focus נראה');
    requireRendered(html, 'min-w-0', 'מכלי המעטפת וטקסט ארוך יכולים להצטמצם במובייל');
    requireRendered(html, 'truncate', 'שם המותג ופריטי ניווט ארוכים אינם מרחיבים את המעטפת');
    requireRendered(html, 'bg-cyan-400/10', 'הדגשת מצב פעיל משתמשת במבטא cyan המאושר');
  }
});

test('מעטפת המשתמש האמיתית מציגה מצב טעינה חי ונגיש בלי תלות בתפקיד', () => {
  const html = renderToStaticMarkup(React.createElement(UserLayout, null, React.createElement('section', null, 'Hidden while loading')));
  requireRendered(html, 'role="status"', 'מצב הטעינה מודיע את עצמו');
  requireRendered(html, 'aria-live="polite"', 'הודעת הטעינה אינה קוטעת הודעה קיימת');
  requireRendered(html, 'aria-hidden="true"', 'הספינר הדקורטיבי אינו נקרא פעמיים');
  requireRendered(html, 'border-cyan-400', 'מצב הטעינה תואם למבטא cyan');
  assert.ok(!html.includes('Hidden while loading'), 'תוכן מוגן אינו נרנדר לפני שיש זהות');
});

test('מימוש התפריט הפעיל מאמץ useDialogFocus אמיתי ומבודד את התוכן מאחורי drawer פתוח', () => {
  for (const file of [traderFile, affiliateFile]) {
    const source = fs.readFileSync(file, 'utf8');
    assert.match(source, /useDialogFocus\(\{ open: sidebarOpen, onClose: closeSidebar \}\)/, `${file.pathname} משתמש ב-hook המשותף האמיתי ל־Escape, trap והחזרת focus`);
    assert.match(source, /role=\{sidebarOpen \? 'dialog' : undefined\}/, `${file.pathname} מסמן drawer פתוח כדיאלוג`);
    assert.match(source, /data-autofocus/, `${file.pathname} מספק יעד focus התחלתי בטוח`);
    assert.match(source, /aria-hidden=\{sidebarOpen \? true : undefined\}/, `${file.pathname} מבודד את התוכן שמאחורי drawer פתוח`);
  }
});
