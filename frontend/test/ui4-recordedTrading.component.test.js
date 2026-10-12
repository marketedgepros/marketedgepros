import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const service = new URL('../src/services/recordedTradingViewService.js', import.meta.url).href;
const uiTarget = new URL('../node_modules/.cache-ui4-recorded-ui.mjs', import.meta.url);
const scalingTarget = new URL('../node_modules/.cache-ui4-recorded-scaling.mjs', import.meta.url);
let ui, scaling;
try {
  const file = new URL('../src/components/trading/RecordedTradingUI.jsx', import.meta.url);
  const source = fs.readFileSync(file, 'utf8').replace(/['"]\.\.\/\.\.\/services\/recordedTradingViewService\.js['"]/g, JSON.stringify(service));
  fs.writeFileSync(uiTarget, (await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' })).code);
  ui = await import(uiTarget.href);
  const scalingFile = new URL('../src/pages/ScalingProgress.jsx', import.meta.url);
  let scalingSource = fs.readFileSync(scalingFile, 'utf8')
    .replace(/import UserLayout from [^;]+;/, 'const UserLayout = ({ children }) => <main>{children}</main>;')
    .replace(/import useAuthStore from [^;]+;/, 'const useAuthStore = () => null;')
    .replace(/import useRecordedTradingRead from [^;]+;/, 'const useRecordedTradingRead = () => ({loading: true});')
    .replace(/['"]\.\.\/services\/recordedTradingViewService\.js['"]/g, JSON.stringify(service))
    .replace(/['"]\.\.\/components\/trading\/RecordedTradingUI['"]/g, JSON.stringify(uiTarget.href));
  fs.writeFileSync(scalingTarget, (await transformWithEsbuild(scalingSource, scalingFile.pathname, { loader: 'jsx', jsx: 'automatic' })).code);
  scaling = await import(scalingTarget.href);
} finally {
  fs.rmSync(uiTarget, { force: true }); fs.rmSync(scalingTarget, { force: true });
}
const render = (Component, props) => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Component, props)));

test('real read-state component distinguishes loading, failed response and successful empty without zero balance', () => {
  const loading = render(ui.RecordedReadState, { loading: true });
  assert.match(loading, /role="status"/); assert.match(loading, /aria-busy="true"/);
  const failed = render(ui.RecordedReadState, { error: true, retry: () => {} });
  assert.match(failed, /role="alert"/); assert.match(failed, /Retry recorded data/);
  assert.doesNotMatch(failed, /No recorded data|\$0|No trades found/);
  const empty = render(ui.RecordedReadState, { empty: true });
  assert.match(empty, /No recorded data/); assert.doesNotMatch(empty, /Retry recorded data|role="alert"/);
});
test('real boundary and Scaling details explicitly refuse live eligibility, preserve zero and unavailable values', () => {
  const html = render(scaling.RecordedScalingDetail, { data: { current_tier: 1, current_account_size: '10000.00', total_profit: '0.00',
    times_scaled: 0, status: 'active', next_tier: null, next_account_size: null, target_profit: '800.00', progress_percentage: null,
    last_scaled_at: null, created_at: null } });
  assert.match(html, /0\.00/); assert.match(html, /Unavailable/); assert.match(html, /not an approved scaling plan/);
  assert.doesNotMatch(html, /\$|Scale Up Now|Congratulations|eligible to scale/);
  const boundary = render(ui.RecordedBoundary, { scaling: true });
  assert.match(boundary, /Account scaling is unavailable/); assert.doesNotMatch(boundary, /<button/);
});
test('actual pagination remains bounded and all controls are buttons, including last-page limitation', () => {
  const html = render(ui.RecordedPagination, { pagination: { page: 1000, per_page: 20, total: 20020, pages: 1001 }, onPage: () => {} });
  assert.match(html, /Browsing is limited to 1000 pages/); assert.match(html, /First page/);
  assert.match(html, /disabled=""/); assert.match(html, /aria-label="Recorded data pagination"/);
});
test('actual metric displays NULL separately from measured zero and escapes stored text', () => {
  assert.match(render(ui.RecordedMetric, { label: 'Recorded', value: null }), /Unavailable/);
  assert.match(render(ui.RecordedMetric, { label: 'Recorded', value: '0.00' }), /0\.00/);
  assert.match(render(ui.RecordedMetric, { label: 'Recorded', value: '<script>x</script>' }), /&lt;script&gt;/);
});
