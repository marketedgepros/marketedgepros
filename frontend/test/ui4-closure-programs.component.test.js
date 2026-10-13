import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';
import { normalizeAdminProgram } from '../src/services/adminClosureProgramsService.js';

const pageFile = new URL('../src/pages/admin/ProgramsManagement.jsx', import.meta.url);
const target = new URL(`../node_modules/.ui4-closure-programs-page-${process.pid}.mjs`, import.meta.url);
const authStub = new URL(`../node_modules/.ui4-closure-programs-auth-${process.pid}.mjs`, import.meta.url);
const service = new URL('../src/services/adminClosureProgramsService.js', import.meta.url).href;
const dialogFocus = new URL('../src/hooks/useDialogFocus.js', import.meta.url).href;

let page;
try {
  fs.writeFileSync(authStub, 'const state = { user: null, isAuthenticated: false, isLoading: false }; export default function useAuthStore(selector) { return selector(state); }\n');
  const source = fs.readFileSync(pageFile, 'utf8')
    .replace("'../../store/authStore.js'", JSON.stringify(authStub.href))
    .replace("'../../hooks/useDialogFocus.js'", JSON.stringify(dialogFocus))
    .replace("'../../services/adminClosureProgramsService.js'", JSON.stringify(service));
  const transformed = await transformWithEsbuild(source, pageFile.pathname, { loader: 'jsx', jsx: 'automatic' });
  fs.writeFileSync(target, transformed.code);
  page = await import(`${target.href}?ui4=${process.pid}`);
} finally {
  fs.rmSync(target, { force: true });
  fs.rmSync(authStub, { force: true });
}

const record = () => normalizeAdminProgram({
  id: 19,
  tenant_id: 7,
  name: 'Recorded Evaluation',
  type: 'stored_legacy_type',
  description: null,
  account_size: '10000.00',
  profit_target: null,
  max_daily_loss: '0.00',
  max_total_loss: null,
  price: '199.99',
  profit_split: null,
  profit_split_percentage: '0.00',
  minimum_payout_amount: null,
  payout_mode: null,
  rules: { legacy: { exact: '0.00', missing: null } },
  is_active: false,
  created_at: null,
  updated_at: '2026-10-12T12:00:00Z',
});

test('UI4 programs page SSR is safe before a verified principal and exposes scoped loading without program rows', () => {
  const html = renderToStaticMarkup(React.createElement(page.default));
  assert.match(html, /Programs management/);
  assert.match(html, /role="status"/);
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /Loading the persisted program catalog/);
  assert.match(html, /disabled=""[^>]*>.*Create program/s);
  assert.doesNotMatch(html, /Persisted program catalog/);
  assert.doesNotMatch(html, /Tenant 7/);
});

test('UI4 programs component draft retains canonical decimals, represents persisted nulls as editable blanks, and blocks stale generations', () => {
  const draft = page.programDraft(record());
  assert.deepEqual(draft, {
    name: 'Recorded Evaluation',
    type: 'stored_legacy_type',
    description: '',
    accountSize: '10000.00',
    profitTarget: '',
    maxDailyLoss: '0.00',
    maxTotalLoss: '',
    price: '199.99',
    profitSplit: '',
    profitSplitPercentage: '0.00',
    minimumPayoutAmount: '',
    payoutMode: '',
    rules: '{\n  "legacy": {\n    "exact": "0.00",\n    "missing": null\n  }\n}',
    isActive: false,
  });
  const controller = new AbortController();
  assert.equal(page.isCurrentProgramsOperation(3, 3, controller.signal), true);
  assert.equal(page.isCurrentProgramsOperation(3, 4, controller.signal), false);
  controller.abort();
  assert.equal(page.isCurrentProgramsOperation(3, 3, controller.signal), false);
});
