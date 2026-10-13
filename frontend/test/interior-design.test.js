import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const read = (file) => fs.readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8');

test('interior entrance and tab motion are one-shot, immediately readable and compositor opacity only', () => {
  const css = read('index.css');
  assert.match(css, /animation: mep-interior-arrive 180ms ease-out 1;/);
  assert.match(css, /\.mep-page \[role="tabpanel"\]/);
  const frames = css.split('@keyframes mep-interior-arrive')[1].split('/* Pointer-only')[0];
  assert.match(frames, /from \{ opacity: 0\.96; \}/);
  assert.match(frames, /to \{ opacity: 1; \}/);
  assert.doesNotMatch(frames, /transform|filter|height|width|display|visibility/);
  assert.doesNotMatch(css, /animation:[^;]*infinite|overflow-x:\s*hidden/);
});

test('interior cards use pointer-only response and reduce-motion explicitly disables entrance and transitions', () => {
  const css = read('index.css');
  assert.match(css, /@media \(hover: hover\) and \(pointer: fine\)/);
  assert.match(css, /\.mep-interior-card:focus-within/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.mep-tab-panel \{\s*animation: none;/);
  assert.match(css, /\.mep-page \[role="tab"\],[\s\S]*?\.mep-interior-card \{\s*transition: none;/);
  assert.match(css, /outline: 2px solid #22d3ee/);
});

test('existing page and identity wrappers reach shared interior motion without adding pathname remounts or requests', () => {
  for (const file of ['components/layout/Layout.jsx', 'components/trader/TraderLayout.jsx', 'components/agent/AgentLayout.jsx', 'components/admin/AdminLayout.jsx']) {
    const source = read(file);
    assert.match(source, /mep-page/);
    // The admin's two pre-existing cancellable focus frames are not an animation loop.
    assert.doesNotMatch(source, /key=\{location\.pathname\}|setInterval/);
  }
  assert.match(read('pages/user/Profile.jsx'), /role="tabpanel"/);
  const affiliate = read('pages/affiliate/AffiliateDashboard.jsx');
  assert.match(affiliate, /mep-workspace-hero/);
  assert.match(affiliate, /mep-interior-card/);
  assert.match(affiliate, /Source status:/);
});
