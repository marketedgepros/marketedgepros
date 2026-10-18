import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';

const pageFile = new URL('../src/pages/admin/KYCApprovalConnected.jsx', import.meta.url);
const target = new URL(`../node_modules/.ui4-closure-kyc-page-${process.pid}.mjs`, import.meta.url);
const toastTarget = new URL(`../node_modules/.ui4-closure-kyc-toast-${process.pid}.mjs`, import.meta.url);
const src = (relative) => new URL(`../src/${relative}`, import.meta.url).href;

let page;
try {
  fs.writeFileSync(toastTarget, 'export const useToast = () => ({ success() {}, error() {} });\n');
  let source = fs.readFileSync(pageFile, 'utf8');
  for (const [from, to] of Object.entries({
    '../../contexts/ToastContext': toastTarget.href,
    '../../store/authStore': src('store/authStore.js'),
    '../../hooks/useAdminClosureKyc.js': src('hooks/useAdminClosureKyc.js'),
    '../../hooks/useDialogFocus.js': src('hooks/useDialogFocus.js'),
    '../../services/adminClosureKycService.js': src('services/adminClosureKycService.js'),
  })) {
    source = source.replaceAll(`'${from}'`, JSON.stringify(to));
  }
  const transformed = await transformWithEsbuild(source, pageFile.pathname, { loader: 'jsx', jsx: 'automatic' });
  fs.writeFileSync(target, transformed.code);
  page = await import(`${target.href}?ui4=${process.pid}`);
} finally {
  fs.rmSync(target, { force: true });
  fs.rmSync(toastTarget, { force: true });
}

const listValue = {
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  submissions: [{
    userId: 3,
    kycStatus: 'pending',
    submittedAt: '2026-10-12T12:00:00Z',
    documents: { id_proof: 'pending', address_proof: 'not_uploaded', selfie: 'not_uploaded', bank_statement: 'not_uploaded' },
  }],
};
const detailValue = {
  user: { id: 3, displayName: '<Review Subject>' },
  kycStatus: 'pending',
  submittedAt: '2026-10-12T12:00:00Z',
  documents: [
    { type: 'id_proof', name: 'ID proof', status: 'pending', uploadedAt: '2026-10-12T12:00:00Z', notes: null, downloadPath: '/api/v1/kyc/documents/3/id_proof/download' },
    { type: 'address_proof', name: 'Address proof', status: 'not_uploaded', uploadedAt: null, notes: null, downloadPath: null },
  ],
};

test('UI4 closure KYC SSR exposes separate loading, failure, empty, and scrollable scoped list states', () => {
  const loading = renderToStaticMarkup(React.createElement(page.KycSubmissionList, {
    list: { loading: true, value: null, error: null }, selectedUserId: null, onSelect: () => {}, disabled: false,
  }));
  assert.match(loading, /aria-busy="true"/);
  assert.match(loading, /Loading recorded pending submissions/);
  const failure = renderToStaticMarkup(React.createElement(page.KycSubmissionList, {
    list: { loading: false, value: null, error: new Error('synthetic failure') }, selectedUserId: null, onSelect: () => {}, disabled: false,
  }));
  assert.match(failure, /role="alert"/);
  assert.match(failure, /could not be loaded\. Try a manual refresh/);
  const empty = renderToStaticMarkup(React.createElement(page.KycSubmissionList, {
    list: { loading: false, value: { ...listValue, submissions: [] }, error: null }, selectedUserId: null, onSelect: () => {}, disabled: false,
  }));
  assert.match(empty, /No pending submissions are available to display/);
  assert.doesNotMatch(empty, /All KYC requests have been processed/);
  const populated = renderToStaticMarkup(React.createElement(page.KycSubmissionList, {
    list: { loading: false, value: listValue, error: null }, selectedUserId: 3, onSelect: () => {}, disabled: false,
  }));
  assert.match(populated, /overflow-x-auto/);
  assert.match(populated, /User #3/);
  assert.match(populated, /Viewing record/);
  assert.doesNotMatch(populated, /Email|Verification Rate|Success rate/);
});

test('UI4 closure KYC SSR renders private download, real document-review actions, neutral scope copy, and escaped subject data', () => {
  const scope = renderToStaticMarkup(React.createElement(page.KycReviewNotice));
  assert.match(scope, /manual review of submitted documents only/);
  assert.match(scope, /does not change wallet, payout, trading, or MT5 eligibility/);
  const detail = renderToStaticMarkup(React.createElement(page.KycSubmissionDetail, {
    detail: { loading: false, error: null, value: detailValue }, onDownload: () => {}, onReview: () => {}, disabled: false,
  }));
  assert.match(detail, /Download privately/);
  assert.match(detail, /Record approval/);
  assert.match(detail, /Record rejection/);
  assert.match(detail, /&lt;Review Subject&gt;/);
  assert.doesNotMatch(detail, />View</);
  assert.doesNotMatch(detail, /identity verification has been approved/i);
});

test('UI4 closure KYC SSR dialog requires the exact typed original-user/document acknowledgement and a rejection reason', () => {
  const document = detailValue.documents[0];
  const dialog = renderToStaticMarkup(React.createElement(page.KycDocumentReviewDialog, {
    review: { userId: 3, document, status: 'rejected', notes: '', acknowledgement: '' },
    onClose: () => {}, onChange: () => {}, onSubmit: () => {}, isSaving: false,
  }));
  assert.match(dialog, /role="dialog"/);
  assert.match(dialog, /REVIEW 3 id_proof/);
  assert.match(dialog, /Original subject:<\/strong> User #3/);
  assert.match(dialog, /Original document:<\/strong> ID proof/);
  assert.match(dialog, /required=""/);
  assert.match(dialog, /disabled=""[^>]*>Save recorded rejection/);
  assert.match(dialog, /not provider identity proof/);
});
