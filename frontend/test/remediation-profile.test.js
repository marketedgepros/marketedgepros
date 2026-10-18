import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const profilePath = new URL('../src/pages/user/Profile.jsx', import.meta.url);

async function profileSource() {
  return readFile(profilePath, 'utf8');
}

test('Profile adopts the foundation roving tab contract with stable ids and paired panels', async () => {
  const source = await profileSource();

  assert.match(source, /import useTabNavigation from ['"]\.\.\/\.\.\/hooks\/useTabNavigation['"];/);
  assert.match(source, /const PROFILE_TAB_IDS = Object\.freeze\(\['personal', 'security'\]\);/);
  assert.match(source, /const getTabProps = useTabNavigation\(\{\s*ids: PROFILE_TAB_IDS,\s*activeId: activeTab,\s*onChange: setActiveTab,\s*\}\);/s);

  assert.match(source, /id="profile-personal-tab"\s+type="button"\s+aria-controls="profile-personal-panel"\s+\{\.\.\.getTabProps\('personal'\)\}/);
  assert.match(source, /id="profile-security-tab"\s+type="button"\s+aria-controls="profile-security-panel"\s+\{\.\.\.getTabProps\('security'\)\}/);
  assert.match(source, /<form id="profile-personal-panel" role="tabpanel" aria-labelledby="profile-personal-tab"/);
  assert.match(source, /<form id="profile-security-panel" role="tabpanel" aria-labelledby="profile-security-tab"/);
});

test('Profile routes avatar deletion through the dialog-focus contract without bypassing busy guards', async () => {
  const source = await profileSource();

  assert.match(source, /import useDialogFocus from ['"]\.\.\/\.\.\/hooks\/useDialogFocus['"];/);
  assert.match(source, /const closeDeleteAvatarDialog = useCallback\(\(\) => \{\s*if \(mutationOperationNames\.some\(\(name\) => flightsRef\.current\[name\]\)\) return;\s*setIsDeleteDialogOpen\(false\);\s*\}, \[\]\);/s);
  assert.match(source, /const deleteAvatarDialogRef = useDialogFocus\(\{\s*open: isDeleteDialogOpen,\s*onClose: closeDeleteAvatarDialog,\s*\}\);/s);
  assert.ok(
    source.indexOf('const deleteAvatarDialogRef = useDialogFocus') < source.lastIndexOf('return ('),
    'the hook is called unconditionally before conditional dialog rendering',
  );
  assert.match(source, /<section ref=\{deleteAvatarDialogRef\} role="dialog" aria-modal="true"/);
  assert.match(source, /<button type="button" data-autofocus onClick=\{closeDeleteAvatarDialog\} disabled=\{isMutationPending\}/);
});
