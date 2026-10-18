import assert from 'node:assert/strict';
import { File } from 'node:buffer';
import test from 'node:test';
import {
  canDownloadKycDocument,
  createKycViewService,
  getCanonicalKycDownloadPath,
  isKycFullyVerified,
  normaliseKycDocumentsResponse,
  validateKycUploadFile,
} from '../src/services/kycViewService.js';

const validDocument = {
  type: 'id_proof',
  download_url: '/api/v1/kyc/documents/41/id_proof/download',
};

const createDownloadDom = ({ throwOnClick = false } = {}) => {
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
  const document = {
    body,
    createElement(tagName) {
      assert.equal(tagName, 'a');
      return {
        style: {},
        click() {
          events.push('click');
          if (throwOnClick) throw new Error('synthetic click error');
        },
      };
    },
  };
  const URL = {
    createObjectURL(blob) {
      events.push(`create:${blob.size}`);
      return 'blob:synthetic-kyc-document';
    },
    revokeObjectURL(objectUrl) {
      events.push(`revoke:${objectUrl}`);
    },
  };
  return { document, URL, events };
};

test('KYC download metadata permits only the canonical API-relative owner route', () => {
  assert.equal(
    getCanonicalKycDownloadPath(validDocument),
    '/api/v1/kyc/documents/41/id_proof/download',
  );
  // The currently deployed endpoint exposes `url`; retain strict compatibility.
  assert.equal(
    getCanonicalKycDownloadPath({
      type: 'selfie',
      url: '/api/v1/kyc/documents/99/selfie/download',
    }),
    '/api/v1/kyc/documents/99/selfie/download',
  );

  for (const documentMetadata of [
    { type: 'id_proof', download_url: 'https://files.example.test/id.pdf' },
    { type: 'id_proof', download_url: '//files.example.test/id.pdf' },
    { type: 'id_proof', download_url: '/api/v1/kyc/documents/41/id_proof/download?token=secret' },
    { type: 'id_proof', download_url: '/api/v1/kyc/documents/41/id_proof/download#fragment' },
    { type: 'id_proof', download_url: '/api/v1/kyc/documents/41/%69d_proof/download' },
    { type: 'id_proof', download_url: '/api/v1/kyc/documents/41/address_proof/download' },
    { type: 'id_proof', download_url: '/api/v1/kyc/documents/41/id_proof/download/../download' },
    {
      type: 'id_proof',
      download_url: 'https://files.example.test/blocked.pdf',
      url: '/api/v1/kyc/documents/41/id_proof/download',
    },
  ]) {
    assert.throws(() => getCanonicalKycDownloadPath(documentMetadata), /invalid/i);
    assert.equal(canDownloadKycDocument(documentMetadata), false);
  }
});

test('KYC download uses the configured authenticated API client, blob response, and temporary DOM URL', async () => {
  const calls = [];
  const dom = createDownloadDom();
  const apiClient = {
    get: async (path, config) => {
      calls.push({ path, config });
      return { data: new Blob(['synthetic KYC file'], { type: 'application/pdf' }) };
    },
    post: async () => {
      throw new Error('not used');
    },
  };
  const service = createKycViewService(apiClient, dom);
  const controller = new AbortController();

  await service.downloadDocument(validDocument, { signal: controller.signal });

  assert.deepEqual(calls, [{
    path: '/kyc/documents/41/id_proof/download',
    config: { responseType: 'blob', signal: controller.signal },
  }]);
  assert.deepEqual(dom.events, [
    'create:18',
    'append',
    'click',
    'remove',
    'revoke:blob:synthetic-kyc-document',
  ]);
});

test('KYC download rejects arbitrary routes before any request and always cleans temporary URLs on DOM errors', async () => {
  let requestCount = 0;
  const rejectingService = createKycViewService({
    get: async () => {
      requestCount += 1;
      return { data: new Blob(['synthetic']) };
    },
    post: async () => {},
  }, createDownloadDom());

  await assert.rejects(
    () => rejectingService.downloadDocument({ type: 'id_proof', download_url: 'https://evil.example.test/document' }),
    /invalid/i,
  );
  assert.equal(requestCount, 0);

  const dom = createDownloadDom({ throwOnClick: true });
  const failingDomService = createKycViewService({
    get: async () => ({ data: new Blob(['synthetic']) }),
    post: async () => {},
  }, dom);
  await assert.rejects(() => failingDomService.downloadDocument(validDocument), /synthetic click error/);
  assert.deepEqual(dom.events, [
    'create:9',
    'append',
    'click',
    'remove',
    'revoke:blob:synthetic-kyc-document',
  ]);
});

test('KYC uploads validate backend-supported extensions and leave multipart boundaries to the browser', async () => {
  const syntheticPdf = new File(['not a real document'], 'synthetic.pdf', { type: 'application/pdf' });
  assert.deepEqual(validateKycUploadFile(syntheticPdf), { valid: true });
  assert.equal(validateKycUploadFile(new File(['x'], 'synthetic.gif')).valid, false);
  assert.equal(validateKycUploadFile({ name: 'too-large.png', size: 10 * 1024 * 1024 + 1 }).valid, false);

  let postCall;
  const service = createKycViewService({
    get: async () => ({ data: {} }),
    post: async (path, formData, config) => {
      postCall = { path, formData, config };
      return { data: { document: { type: 'id_proof', name: 'ID Proof', status: 'pending', uploaded_at: '2026-10-12T08:00:00' } } };
    },
  }, createDownloadDom());
  const controller = new AbortController();

  await service.uploadDocument('id_proof', syntheticPdf, { signal: controller.signal });

  assert.equal(postCall.path, '/kyc/documents/id_proof/upload');
  assert.equal(postCall.formData.get('file').name, 'synthetic.pdf');
  assert.deepEqual(postCall.config, { signal: controller.signal, headers: { 'Content-Type': undefined } });
  assert.equal(postCall.config.headers['Content-Type'], undefined);
});

test('KYC verification is based only on explicit overall_status and incomplete response data is not zero-filled', () => {
  assert.equal(isKycFullyVerified('approved'), true);
  assert.equal(isKycFullyVerified('pending'), false);
  assert.equal(isKycFullyVerified(undefined), false);

  const normalised = normaliseKycDocumentsResponse({
    documents: [],
    overall_status: 'pending',
  });
  assert.equal(normalised.statistics, null);
  assert.equal(normalised.overallStatus, 'pending');
  assert.throws(
    () => normaliseKycDocumentsResponse({ documents: [], statistics: { approved: 3 } }),
    /incomplete/i,
  );
});

test('KYC requests compose correctly with the real configured Axios client without network', async () => {
  const { default: api } = await import('../src/services/api.js');
  const previousAdapter = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push(config);
    return { status: 200, statusText: 'OK', headers: {}, config,
      data: config.method === 'get' ? new Blob(['synthetic']) : { document: { type: 'id_proof', name: 'ID Proof', status: 'pending', uploaded_at: '2026-10-12T08:00:00' } } };
  };
  try {
    const service = createKycViewService(api, createDownloadDom());
    await service.downloadDocument(validDocument);
    assert.equal(api.getUri(calls[0]), '/api/v1/kyc/documents/41/id_proof/download');
    assert.equal(calls[0].withCredentials, true);
    await service.uploadDocument('id_proof', new File(['synthetic'], 'synthetic.pdf'));
    assert.ok(calls[1].data instanceof FormData, 'JSON transform must not serialize the FormData');
    assert.notEqual(calls[1].headers.get('Content-Type'), 'application/json');
    for (const size of [0, NaN, Infinity, -1, 1.5]) {
      assert.equal(validateKycUploadFile({ name: 'synthetic.pdf', size }).valid, false);
    }
  } finally {
    api.defaults.adapter = previousAdapter;
  }
});

test('KYC operation gate blocks overlapping types and stale completions cannot release another operation', async () => {
  const { KycOperationGate } = await import('../src/services/kycViewService.js');
  const gate = new KycOperationGate();
  const first = gate.begin('id_proof', 'upload');
  assert.ok(first);
  assert.equal(gate.begin('address_proof', 'upload'), null);
  assert.equal(gate.begin('id_proof', 'upload'), null);
  assert.equal(gate.begin('selfie', 'download'), null);
  assert.equal(gate.finish({ type: 'id_proof', kind: 'upload' }), false);
  assert.equal(gate.busy, true);
  assert.equal(gate.finish(first), true);
  const second = gate.begin('address_proof', 'upload');
  assert.ok(second);
  assert.equal(gate.finish(first), false);
  assert.equal(gate.busy, true);
  assert.equal(gate.finish(second), true);
  assert.equal(gate.busy, false);
});
