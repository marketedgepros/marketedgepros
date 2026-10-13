import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const notificationsPath = new URL('../src/pages/Notifications.jsx', import.meta.url);

async function source() {
  return readFile(notificationsPath, 'utf8');
}

test('Notifications:0 adopts foundation roving tabs with an associated selected tabpanel', async () => {
  const page = await source();

  assert.match(page, /import useTabNavigation from '\.\.\/hooks\/useTabNavigation';/);
  assert.match(page, /const tabIds = tabs\.map\(\(tab\) => tab\.value\);/);
  assert.match(page, /useTabNavigation\(\{ ids: tabIds, activeId: activeTab, onChange: setActiveTab \}\)/);
  assert.match(page, /id=\{`notifications-tab-\$\{tab\.value\}`\}/);
  assert.match(page, /aria-controls=\{`notifications-tabpanel-\$\{tab\.value\}`\} \{\.\.\.getTabProps\(tab\.value\)\}/);
  assert.match(page, /role="tabpanel" id=\{`notifications-tabpanel-\$\{activeTab\}`\}/);
  assert.match(page, /aria-labelledby=\{`notifications-tab-\$\{activeTab\}`\}/);
  assert.doesNotMatch(page, /setInterval\s*\(/, 'the notifications screen must not introduce polling');
});

test('Notifications:0 preserves identity-aware open and notification actions', async () => {
  const page = await source();

  assert.match(page, /const originalIdentity = identity;/);
  assert.match(page, /if \(!notification\.is_read && !\(await markAsRead\(notification\.id\)\)\) return;/);
  assert.match(page, /if \(actorIdentity\(current\) !== originalIdentity\) return;/);
  assert.match(page, /markAllAsRead\(\)/);
  assert.match(page, /deleteNotification\(notification\.id\)/);
  assert.match(page, /navigate\('\/settings\/notifications'\)/);
});
