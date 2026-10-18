import assert from 'node:assert/strict';
import fs from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { transformWithEsbuild } from 'vite';
import { JSDOM } from 'jsdom';

import {
  canDownloadKycDocument,
  getCanonicalKycDownloadPath,
  normaliseKycDocumentsResponse,
} from '../src/services/kycViewService.js';

const documentFixture = (overrides = {}) => ({
  type: 'id_proof',
  name: 'Government ID',
  status: 'not_uploaded',
  uploaded_at: null,
  notes: null,
  url: null,
  ...overrides,
});

const responseFixture = (documents, overrides = {}) => ({
  documents,
  overall_status: null,
  statistics: null,
  ...overrides,
});

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const source = (relative) => path.join(frontendDirectory, 'src', relative);
const sourceUrl = (relative) => pathToFileURL(source(relative)).href;
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://documents.remediation.test/' });

Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });

const { createRoot } = await import('react-dom/client');
const accountAuthStub = `const useAuthStore = (selector) => {
  const state = globalThis.__remediationDocumentsStore;
  return typeof selector === 'function' ? selector(state) : state;
};`;

globalThis.__remediationKycHandlers = {
  get: () => Promise.reject(new Error('Synthetic Documents handler was not configured.')),
  post: () => Promise.reject(new Error('Synthetic Documents handler was not configured.')),
};
globalThis.__remediationDocumentsApi = {
  get: (...args) => globalThis.__remediationKycHandlers.get(...args),
  post: (...args) => globalThis.__remediationKycHandlers.post(...args),
};

async function compileDocuments() {
  const sourcePath = source('pages/user/Documents.jsx');
  const targetPath = path.join(frontendDirectory, 'node_modules', `.remediation-documents-${process.pid}.mjs`);
  const original = fs.readFileSync(sourcePath, 'utf8');
  const transformed = await transformWithEsbuild(original
    .replace("import api from '../../services/api';", 'const api = globalThis.__remediationDocumentsApi;')
    .replace("import useAuthStore from '../../store/authStore';", accountAuthStub)
    .replace("} from '../../services/kycViewService';", `} from ${JSON.stringify(sourceUrl('services/kycViewService.js'))};`), sourcePath, {
    loader: 'jsx',
    jsx: 'automatic',
  });

  fs.writeFileSync(targetPath, transformed.code);
  try {
    return await import(`${pathToFileURL(targetPath).href}?documents-remediation=${process.pid}`);
  } finally {
    fs.rmSync(targetPath, { force: true });
  }
}

const Documents = (await compileDocuments()).default;
const h = React.createElement;
const rows = () => [
  documentFixture(),
  documentFixture({ type: 'address_proof', name: 'Address proof' }),
  documentFixture({ type: 'selfie', name: 'Selfie with ID' }),
  documentFixture({ type: 'bank_statement', name: 'Bank statement' }),
];
const renderedResponse = (documents) => ({
  data: {
    documents,
    overall_status: 'pending',
    statistics: { total: documents.length, uploaded: 1, approved: 0, pending: 1, rejected: 0 },
  },
});

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderDocuments() {
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.getElementById('root'));
  await act(async () => {
    root.render(h(Documents));
  });
  await settle();
  return root;
}

async function clickButton(text) {
  const button = [...document.querySelectorAll('button')].find((node) => node.textContent.includes(text));
  assert.ok(button, `expected ${text} button`);
  await act(async () => {
    button.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  });
  await settle();
}

test('Documents remediation: an explicit empty response remains distinct from unavailable data', () => {
  assert.deepEqual(normaliseKycDocumentsResponse(responseFixture([])), {
    documents: [],
    statistics: null,
    overallStatus: null,
  });
});

test('Documents remediation: null and unknown document values are never converted to not_uploaded', () => {
  const result = normaliseKycDocumentsResponse(responseFixture([
    documentFixture({ status: 'awaiting_external_review' }),
  ], { overall_status: 'awaiting_external_review' }));

  assert.equal(result.documents[0].status, 'awaiting_external_review');
  assert.equal(result.documents[0].uploaded_at, null);
  assert.equal(result.overallStatus, 'awaiting_external_review');
});

test('Documents remediation: an invalid nonempty timestamp is rejected before it can render Invalid Date', () => {
  assert.throws(
    () => normaliseKycDocumentsResponse(responseFixture([
      documentFixture({ status: 'pending', uploaded_at: 'not-a-recorded-date' }),
    ])),
    /invalid upload timestamp/,
  );

  const valid = normaliseKycDocumentsResponse(responseFixture([
    documentFixture({ status: 'pending', uploaded_at: '2026-10-13T10:30:00.000Z' }),
  ]));
  assert.equal(valid.documents[0].uploaded_at, '2026-10-13T10:30:00.000Z');
});

test('Documents remediation: the download owner guard rejects a cross-account route without a request', () => {
  const metadata = documentFixture({
    status: 'approved',
    url: '/api/v1/kyc/documents/42/id_proof/download',
  });

  assert.equal(canDownloadKycDocument(metadata, '41'), false);
  assert.throws(() => getCanonicalKycDownloadPath(metadata, '41'), /does not belong/);
  assert.equal(getCanonicalKycDownloadPath(metadata, '42'), '/api/v1/kyc/documents/42/id_proof/download');
});

test('Documents remediation: the screen exposes stale, retryable, and explicit empty states with safe date rendering', async () => {
  const source = await readFile(new URL('../src/pages/user/Documents.jsx', import.meta.url), 'utf8');

  assert.match(source, /const \[refreshError, setRefreshError\] = useState\(null\)/);
  assert.match(source, /hasSuccessfulLoadRef\.current/);
  assert.match(source, /The displayed document status may be out of date/);
  assert.match(source, /Retry status check/);
  assert.match(source, /No recorded documents yet/);
  assert.match(source, /const formatRecordedUploadDate/);
  assert.doesNotMatch(source, /new Date\(documentInfo\.uploaded_at\)\.toLocaleDateString\(\)/);
  assert.match(source, /border-rose-400\/50 bg-rose-950\/60 text-rose-100/);
});

test('Documents remediation: a failed refresh retains the last record, warns that it is stale, and offers a retry', async () => {
  globalThis.__remediationDocumentsStore = {
    isAuthenticated: true,
    user: { id: 41, tenant_id: 7, role: 'user' },
  };
  const responses = [renderedResponse(rows()), new Error('Synthetic refresh failure'), renderedResponse(rows())];
  let reads = 0;
  globalThis.__remediationKycHandlers.get = async () => {
    reads += 1;
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next;
  };

  const root = await renderDocuments();
  try {
    assert.match(document.body.textContent, /Government ID/);
    await clickButton('Refresh status');
    assert.equal(reads, 2);
    assert.match(document.body.textContent, /The displayed document status may be out of date/);
    assert.match(document.body.textContent, /Failed to load recorded document status\. Please try again\./);
    assert.match(document.body.textContent, /Government ID/, 'last confirmed document remains visible');

    await clickButton('Retry status check');
    assert.equal(reads, 3);
    assert.doesNotMatch(document.body.textContent, /The displayed document status may be out of date/);
  } finally {
    await act(async () => root.unmount());
  }
});

test('Documents remediation: an initial empty response is not presented as unavailable', async () => {
  globalThis.__remediationDocumentsStore = {
    isAuthenticated: true,
    user: { id: 41, tenant_id: 7, role: 'user' },
  };
  globalThis.__remediationKycHandlers.get = async () => renderedResponse([]);

  const root = await renderDocuments();
  try {
    assert.match(document.body.textContent, /No recorded documents yet/);
    assert.doesNotMatch(document.body.textContent, /^Recorded document status unavailable$/m);
  } finally {
    await act(async () => root.unmount());
  }
});
