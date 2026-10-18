import assert from 'node:assert/strict';
import { File } from 'node:buffer';
import test from 'node:test';
import {
  canDownloadKycDocument,
  createKycViewService,
  KycOperationGate,
  normaliseKycDocumentsResponse,
  normaliseKycUploadResponse,
} from '../src/services/kycViewService.js';

const documentTypes = ['id_proof', 'address_proof', 'selfie', 'bank_statement'];
const documentMetadata = (type, overrides = {}) => ({
  type,
  name: type.replaceAll('_', ' '),
  status: 'not_uploaded',
  uploaded_at: null,
  notes: null,
  url: null,
  ...overrides,
});

const responseWithDocuments = (documents = documentTypes.map((type) => documentMetadata(type))) => ({
  overall_status: 'not_submitted',
  statistics: { total: 4, uploaded: 0, approved: 0, pending: 0, rejected: 0 },
  documents,
});

const createDownloadDom = () => {
  const events = [];
  const body = {
    appendChild(node) {
      events.push('append');
      node.parentNode = body;
    },
    removeChild(node) {
      events.push('remove');
      node.parentNode = null;
    },
  };
  return {
    events,
    document: {
      body,
      createElement() {
        return { style: {}, click() { events.push('click'); } };
      },
    },
    URL: {
      createObjectURL() { events.push('create'); return 'blob:synthetic-kyc'; },
      revokeObjectURL() { events.push('revoke'); },
    },
  };
};

test('UI4 KYC mapper retains only complete backend-shaped records, accepts explicit no-data, and rejects unsafe shapes', () => {
  const mapped = normaliseKycDocumentsResponse(responseWithDocuments());
  assert.equal(mapped.documents.length, 4);
  assert.deepEqual(mapped.statistics, { total: 4, uploaded: 0, approved: 0, pending: 0, rejected: 0 });
  assert.equal(mapped.overallStatus, 'not_submitted');
  assert.deepEqual(normaliseKycDocumentsResponse({ documents: [], overall_status: null }), {
    documents: [], statistics: null, overallStatus: null,
  });

  assert.throws(
    () => normaliseKycDocumentsResponse(responseWithDocuments([
      documentMetadata('id_proof'), documentMetadata('id_proof'),
    ])),
    /duplicate/i,
  );
  assert.throws(
    () => normaliseKycDocumentsResponse(responseWithDocuments([
      { ...documentMetadata('id_proof'), notes: 7 },
    ])),
    /metadata/i,
  );
  assert.throws(
    () => normaliseKycDocumentsResponse({
      ...responseWithDocuments(),
      statistics: { total: 4, uploaded: 0, approved: -1, pending: 0, rejected: 0 },
    }),
    /statistics/i,
  );
  assert.throws(
    () => normaliseKycDocumentsResponse(responseWithDocuments([
      documentMetadata('id_proof'), { ...documentMetadata('address_proof'), status: null },
    ])),
    /incomplete/i,
  );
});

test('UI4 KYC upload accepts only the matching pending document response and never creates approved client state', async () => {
  const file = new File(['synthetic only'], 'identity.pdf', { type: 'application/pdf' });
  let postCall;
  const service = createKycViewService({
    get: async () => ({ data: {} }),
    post: async (path, formData, config) => {
      postCall = { path, formData, config };
      return {
        data: {
          document: {
            type: 'id_proof', name: 'ID Proof', status: 'pending', uploaded_at: '2026-10-12T08:00:00Z',
          },
        },
      };
    },
  });

  const accepted = await service.uploadDocument('id_proof', file);
  assert.deepEqual(accepted, {
    type: 'id_proof', name: 'ID Proof', status: 'pending', uploaded_at: '2026-10-12T08:00:00Z',
  });
  assert.equal(postCall.path, '/kyc/documents/id_proof/upload');
  assert.equal(postCall.formData.get('file').name, 'identity.pdf');
  assert.equal(postCall.config.headers['Content-Type'], undefined);
  assert.throws(
    () => normaliseKycUploadResponse({
      document: { type: 'id_proof', name: 'ID Proof', status: 'approved', uploaded_at: '2026-10-12T08:00:00Z' },
    }, 'id_proof'),
    /did not confirm/i,
  );
  assert.throws(
    () => normaliseKycUploadResponse({
      document: { type: 'selfie', name: 'Selfie with ID', status: 'pending', uploaded_at: '2026-10-12T08:00:00Z' },
    }, 'id_proof'),
    /did not confirm/i,
  );
});

test('UI4 KYC download is principal-bound and aborts after a late blob response before DOM side effects', async () => {
  const documentInfo = {
    type: 'id_proof',
    url: '/api/v1/kyc/documents/41/id_proof/download',
  };
  assert.equal(canDownloadKycDocument(documentInfo, '41'), true);
  assert.equal(canDownloadKycDocument(documentInfo, '42'), false);

  const dom = createDownloadDom();
  let releaseResponse;
  const service = createKycViewService({
    get: () => new Promise((resolve) => { releaseResponse = resolve; }),
    post: async () => ({ data: {} }),
  }, dom);
  const controller = new AbortController();
  const download = service.downloadDocument(documentInfo, {
    signal: controller.signal,
    expectedUserId: '41',
  });

  controller.abort();
  releaseResponse({ data: new Blob(['synthetic KYC document']) });
  await assert.rejects(download, { name: 'AbortError' });
  assert.deepEqual(dom.events, []);
});

test('UI4 KYC operation gate remains synchronous and stale completions cannot release a later action', () => {
  const gate = new KycOperationGate();
  const first = gate.begin('id_proof', 'upload');
  assert.ok(first);
  assert.equal(gate.begin('selfie', 'download'), null);
  assert.equal(gate.finish({ type: 'id_proof', kind: 'upload' }), false);
  assert.equal(gate.busy, true);
  assert.equal(gate.finish(first), true);

  const second = gate.begin('selfie', 'download');
  assert.ok(second);
  assert.equal(gate.finish(first), false);
  assert.equal(gate.busy, true);
  assert.equal(gate.finish(second), true);
  assert.equal(gate.busy, false);
});
