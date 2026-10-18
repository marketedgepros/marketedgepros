import assert from 'node:assert/strict';
import test from 'node:test';
import { AxiosError } from 'axios';
import api from '../src/services/api.js';
import {
  ADMIN_CLOSURE_KYC_ENDPOINTS,
  adminClosureKycAcknowledgement,
  adminClosureKycPrincipalFromAuth,
  createAdminClosureKycService,
  normalizeAdminClosureKycDetail,
  normalizeAdminClosureKycSubmissions,
} from '../src/services/adminClosureKycService.js';

const owner = { user_id: 2, tenant_id: 10 };
const submissionPayload = {
  owner_context: owner,
  review_scope: 'recorded_document_only',
  filters: { status: 'pending' },
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
  submissions: [{
    user_id: 3,
    kyc_status: 'pending',
    submitted_at: '2026-10-12T12:00:00',
    documents: { id_proof: 'pending', address_proof: 'not_uploaded', selfie: 'not_uploaded', bank_statement: 'not_uploaded' },
  }],
};
const detailPayload = {
  owner_context: owner,
  review_scope: 'recorded_document_only',
  user: { id: 3, display_name: 'Review Subject' },
  kyc_status: 'pending',
  submitted_at: '2026-10-12T12:00:00',
  documents: ['id_proof', 'address_proof', 'selfie', 'bank_statement'].map((type, index) => ({
    type,
    name: type.replaceAll('_', ' '),
    status: index === 0 ? 'pending' : 'not_uploaded',
    uploaded_at: index === 0 ? '2026-10-12T12:00:00' : null,
    notes: null,
    download_url: index === 0 ? '/api/v1/kyc/documents/3/id_proof/download' : null,
  })),
};

const downloadDom = () => {
  const events = [];
  const body = {
    appendChild(node) { node.parentNode = body; events.push('append'); },
    removeChild(node) { node.parentNode = null; events.push('remove'); },
  };
  return {
    events,
    document: { body, createElement() { return { style: {}, click() { events.push('click'); } }; } },
    URL: {
      createObjectURL(blob) { events.push(`create:${blob.size}`); return 'blob:kyc-admin'; },
      revokeObjectURL(value) { events.push(`revoke:${value}`); },
    },
  };
};

test('UI4 closure KYC principal requires authenticated exact admin id, tenant, and role', () => {
  assert.deepEqual(
    adminClosureKycPrincipalFromAuth({ id: 2, tenant_id: 10, role: 'master' }, true),
    { owner, role: 'master' },
  );
  for (const [user, authenticated] of [
    [{ id: 2, tenant_id: 10, role: 'trader' }, true],
    [{ id: 2, role: 'master' }, true],
    [{ id: 0, tenant_id: 10, role: 'master' }, true],
    [{ id: 2, tenant_id: 10, role: 'master' }, false],
  ]) {
    assert.equal(adminClosureKycPrincipalFromAuth(user, authenticated), null);
  }
  assert.equal(adminClosureKycAcknowledgement(3, 'id_proof'), 'REVIEW 3 id_proof');
  assert.equal(adminClosureKycAcknowledgement(0, 'id_proof'), null);
});

test('UI4 closure KYC normalizers retain minimal scoped data and reject owner, private-reference, and duplicate defects', () => {
  const list = normalizeAdminClosureKycSubmissions(submissionPayload, owner);
  assert.equal(list.submissions[0].userId, 3);
  assert.deepEqual(list.submissions[0].documents, submissionPayload.submissions[0].documents);
  const detail = normalizeAdminClosureKycDetail(detailPayload, owner);
  assert.equal(detail.user.displayName, 'Review Subject');
  assert.equal(detail.documents[0].downloadPath, '/api/v1/kyc/documents/3/id_proof/download');

  assert.throws(() => normalizeAdminClosureKycSubmissions({ ...submissionPayload, owner_context: { user_id: 9, tenant_id: 10 } }, owner), /different administrator/i);
  assert.throws(() => normalizeAdminClosureKycSubmissions({ ...submissionPayload, submissions: [submissionPayload.submissions[0], submissionPayload.submissions[0]] }, owner), /duplicate/i);
  assert.throws(() => normalizeAdminClosureKycDetail({
    ...detailPayload,
    documents: detailPayload.documents.map((document, index) => index === 0 ? { ...document, download_url: 'https://files.example/document.pdf' } : document),
  }, owner), /download route/i);
  const stripped = normalizeAdminClosureKycDetail({
    ...detailPayload,
    documents: detailPayload.documents.map((document, index) => index === 0 ? { ...document, email: 'extra@example.invalid' } : document),
  }, owner);
  assert.equal(Object.hasOwn(stripped.documents[0], 'email'), false);
});

test('UI4 closure KYC review sends exact typed acknowledgement, owner context, abort signal, and real persisted response', async () => {
  let call;
  const service = createAdminClosureKycService({
    get: async () => ({ data: detailPayload }),
    put: async (path, data, config) => {
      call = { path, data, config };
      return {
        data: {
          owner_context: owner,
          review_scope: 'recorded_document_only',
          user: { id: 3 },
          document: {
            type: 'id_proof', status: 'approved', notes: 'reviewed',
            uploaded_at: '2026-10-12T12:00:00', download_url: '/api/v1/kyc/documents/3/id_proof/download',
          },
          review_recorded: true,
        },
      };
    },
  });
  const controller = new AbortController();
  const result = await service.reviewDocument({
    expectedOwner: owner,
    userId: 3,
    documentType: 'id_proof',
    status: 'approved',
    notes: ' reviewed ',
    acknowledgement: 'REVIEW 3 id_proof',
    expectedUploadedAt: '2026-10-12T12:00:00',
    documentName: 'ID proof',
    signal: controller.signal,
  });
  assert.deepEqual(call, {
    path: ADMIN_CLOSURE_KYC_ENDPOINTS.documentReview(3, 'id_proof'),
    data: {
      status: 'approved', notes: 'reviewed', acknowledgement: 'REVIEW 3 id_proof',
      expected_uploaded_at: '2026-10-12T12:00:00',
    },
    config: { signal: controller.signal, _skipAuthRefresh: true },
  });
  assert.equal(result.reviewRecorded, true);
  assert.equal(result.document.status, 'approved');
  await assert.rejects(() => service.reviewDocument({
    expectedOwner: owner, userId: 3, documentType: 'id_proof', status: 'approved', notes: '',
    acknowledgement: 'REVIEW 9 id_proof', expectedUploadedAt: '2026-10-12T12:00:00', documentName: 'ID proof',
  }), /acknowledgement/i);
});

test('actual Axios admin KYC GET neither refreshes a 401 nor replays a sensitive request, and aborted work never enters transport', async () => {
  const original = api.defaults.adapter;
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, signal: config.signal, skip: config._skipAuthRefresh });
    throw new AxiosError('Synthetic unauthorized', 'ERR_BAD_REQUEST', config, {}, {
      status: 401, data: { error: 'Unauthorized' }, headers: {}, config,
    });
  };
  try {
    const service = createAdminClosureKycService(api);
    const controller = new AbortController();
    await assert.rejects(
      service.loadSubmissions({ expectedOwner: owner, signal: controller.signal }),
      (error) => error.response?.status === 401,
    );
    assert.deepEqual(calls, [{
      url: ADMIN_CLOSURE_KYC_ENDPOINTS.submissions, method: 'get', signal: controller.signal, skip: true,
    }]);
    controller.abort();
    await assert.rejects(
      service.loadSubmissions({ expectedOwner: owner, signal: controller.signal }),
      (error) => error.name === 'AbortError' || error.code === 'ERR_CANCELED',
    );
    assert.equal(calls.length, 1);
  } finally {
    api.defaults.adapter = original;
  }
});

test('UI4 closure KYC private download uses only the canonical authenticated blob route and cleans temporary DOM state', async () => {
  const dom = downloadDom();
  const calls = [];
  const service = createAdminClosureKycService({
    get: async (path, config) => {
      calls.push({ path, config });
      return { data: new Blob(['private synthetic document']) };
    },
    put: async () => ({ data: {} }),
  }, dom);
  const document = normalizeAdminClosureKycDetail(detailPayload, owner).documents[0];
  const controller = new AbortController();
  await service.downloadDocument({ expectedOwner: owner, userId: 3, document, signal: controller.signal });
  assert.deepEqual(calls, [{
    path: '/api/v1/kyc/documents/3/id_proof/download',
    config: { signal: controller.signal, _skipAuthRefresh: true, responseType: 'blob' },
  }]);
  assert.deepEqual(dom.events, ['create:26', 'append', 'click', 'remove', 'revoke:blob:kyc-admin']);
});
