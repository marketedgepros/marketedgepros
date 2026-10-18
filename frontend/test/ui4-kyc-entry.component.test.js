import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';

const documentsFile = new URL('../src/pages/user/Documents.jsx', import.meta.url);
const kycFile = new URL('../src/pages/KYC.jsx', import.meta.url);
const documentsTarget = new URL(`../src/pages/user/.ui4-kyc-documents-${process.pid}.mjs`, import.meta.url);
const kycTarget = new URL(`../src/pages/.ui4-kyc-entry-${process.pid}.mjs`, import.meta.url);

const documentsSource = fs.readFileSync(documentsFile, 'utf8')
  .replace("from '../../services/api';", "from '../../services/api.js';")
  .replace("from '../../store/authStore';", "from '../../store/authStore.js';")
  .replace("from '../../services/kycViewService';", "from '../../services/kycViewService.js';");
const kycSource = fs.readFileSync(kycFile, 'utf8')
  .replace("from './user/Documents';", `from './user/${documentsTarget.pathname.split('/').pop()}';`);

const [compiledDocuments, compiledKyc] = await Promise.all([
  transformWithEsbuild(documentsSource, documentsFile.pathname, { loader: 'jsx', jsx: 'automatic' }),
  transformWithEsbuild(kycSource, kycFile.pathname, { loader: 'jsx', jsx: 'automatic' }),
]);

let KycEntry;
try {
  fs.writeFileSync(documentsTarget, compiledDocuments.code);
  fs.writeFileSync(kycTarget, compiledKyc.code);
  KycEntry = (await import(`${kycTarget.href}?ui4=${process.pid}`)).default;
} finally {
  fs.rmSync(kycTarget, { force: true });
  fs.rmSync(documentsTarget, { force: true });
}

test('UI4 /kyc SSR renders the shared canonical document entry instead of redirecting or restoring unsupported fields', () => {
  const html = renderToStaticMarkup(React.createElement(KycEntry));
  assert.match(html, /KYC Documents/);
  assert.match(html, /Submit the requested documents for identity verification/);
  assert.match(html, /Recorded document status unavailable/);
  assert.doesNotMatch(kycSource, /uploadsAPI|kycAPI|document_number|postal_code|proof_of_address|navigate\(/);
});

test('UI4 shared documents source keeps visible file controls and neutral optional bank statement copy', () => {
  assert.match(documentsSource, /Additional Bank Statement/);
  assert.match(documentsSource, /optional additional bank statement document/i);
  assert.match(documentsSource, /type="file"/);
  assert.doesNotMatch(documentsSource, /withdrawal verification/i);
  assert.doesNotMatch(documentsSource, /className="hidden"/);
  assert.match(documentsSource, /focus-visible:ring-2/);
});
