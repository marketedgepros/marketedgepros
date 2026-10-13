import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
const src = new URL('../src/', import.meta.url);
const read = (name) => fs.readFileSync(new URL(name, src), 'utf8');
function target(from, relative) {
  const base = path.resolve(path.dirname(from), relative);
  return [base, `${base}.jsx`, `${base}.js`].find((file) => fs.existsSync(file) && fs.statSync(file).isFile());
}
function reachesDesign(file, visited = new Set()) {
  if (!file || visited.has(file)) return false;
  visited.add(file);
  const source = fs.readFileSync(file, 'utf8');
  if (/\bmep-(heading|panel|primary|screen|shell|page)\b/.test(source)) return true;
  const imports = [...source.matchAll(/(?:from\s+|import\()['"]([^'"]+)['"]/g)].map((m) => m[1]);
  return imports.filter((m) => m.startsWith('.')).some((m) => reachesDesign(target(file, m), visited));
}
test('every active Router lazy page reaches explicit shared design or its real forwarding component', () => {
  const app = read('App.jsx');
  const imports = [...app.matchAll(/const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\(['"]([^'"]+)['"]\)\)/g)];
  assert.ok(imports.length >= 60, 'full active lazy set, not a handful of samples');
  for (const [, name, spec] of imports) {
    const file = target(new URL('App.jsx', src).pathname, spec);
    if (name === 'RoleBasedDashboard') {
      assert.match(fs.readFileSync(file, 'utf8'), /<Navigate to=\{user \? accountHome\(user\) : '\/login'\} replace \/>/);
    } else assert.ok(reachesDesign(file), `${name} has no shared design or actual forwarding path`);
  }
});
test('shared surfaces are explicit, static, and retain visible focus and reduced motion', () => {
  const css = read('index.css');
  for (const token of ['mep-canvas', 'mep-surface', 'mep-border', 'mep-accent']) assert.match(css, new RegExp(`--${token}:`));
  for (const name of ['shell', 'chrome', 'page', 'heading', 'panel', 'primary', 'brand-mark', 'nav-item', 'cta']) assert.match(css, new RegExp(`\\.mep-${name}\\b`));
  assert.doesNotMatch(css, /overflow-x:\s*hidden|animation:[^;]*infinite/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /outline: 2px solid #22d3ee/);
  assert.match(css, /\.mep-nav-item\[aria-current="page"\]/);
  assert.match(css, /\.mep-primary:hover:not\(:disabled\)/);
});
test('all active public and account shells use shared surfaces without changing route or identity behavior', () => {
  for (const file of ['components/layout/Layout.jsx', 'components/trader/TraderLayout.jsx', 'components/agent/AgentLayout.jsx', 'components/admin/AdminLayout.jsx']) {
    const source = read(file);
    assert.match(source, /mep-shell/);
    assert.match(source, /mep-page/);
  }
  for (const file of ['components/trader/TraderLayout.jsx', 'components/agent/AgentLayout.jsx', 'components/admin/AdminLayout.jsx']) {
    const source = read(file);
    assert.match(source, /mep-chrome/);
    assert.match(source, /mep-nav-item/);
    assert.match(source, /aria-current/);
  }
  for (const file of ['components/layout/LandingNavbar.jsx', 'components/layout/LandingFooter.jsx']) {
    assert.match(read(file), /mep-brand-mark/);
    assert.match(read(file), /mep-cta/);
  }
  const layout = read('components/layout/UserLayout.jsx');
  assert.match(layout, /Fragment key=\{identityKey\}/);
  assert.match(layout, /role="status" aria-live="polite"/);
});
test('home reduced motion removes reveals and selection transitions while keeping content visible', () => {
  const home = read('pages/NewHomePage.jsx');
  assert.match(home, /data-visual-paused=\{ambient.reduced \? "true" : "false"\}/);
  const css = read('components/visual/homeMotion.css');
  for (const name of ['scroll-reveal', 'home-motion__panel', 'premium-switch-in', 'program-selector-card']) {
    assert.match(css, new RegExp(`\\.home-motion\\[data-visual-paused="true"\\] \\.${name}`));
  }
  assert.match(css, /animation: none !important;\s*transition: none !important;\s*opacity: 1 !important;\s*transform: none !important;/);
  assert.doesNotMatch(home, /\bfocus:/);
});

test('shared catalog, affiliate, financial, insight, payment and trading panels resolve to the same surface without status overrides', () => {
  const panels = [
    ['programs/CatalogUI.jsx', 'panelStyle'],
    ['affiliate/AffiliateRecordUI.jsx', 'affiliateRecordPanel'],
    ['financial/FinancialRecordUI.jsx', 'financialPanel'],
    ['admin/AdminInsightUI.jsx', 'adminInsightPanel'],
    ['admin/AdminPaymentRecordUI.jsx', 'adminPaymentPanel'],
    ['trading/RecordedTradingUI.jsx', 'tradingPanel'],
  ];
  for (const [file, variable] of panels) {
    const source = read(`components/${file}`);
    assert.match(source, new RegExp(`export const ${variable}\\s*=\\s*["']mep-panel `));
    assert.match(source, /(?:role="alert"|role=\{error \? "alert" : undefined\})/);
  }
  assert.match(read('components/programs/CatalogUI.jsx'), /export const primaryAction\s*=\s*"mep-primary /);
});
