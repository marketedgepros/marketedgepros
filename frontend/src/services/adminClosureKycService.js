import api from './api.js';

export const ADMIN_CLOSURE_KYC_ENDPOINTS = Object.freeze({
  submissions: '/kyc/admin/submissions',
  submission: (userId) => `/kyc/admin/submissions/${userId}`,
  documentReview: (userId, documentType) => `/kyc/admin/submissions/${userId}/documents/${documentType}`,
  documentDownload: (userId, documentType) => `/kyc/documents/${userId}/${documentType}/download`,
});

export const ADMIN_CLOSURE_KYC_DOCUMENT_TYPES = new Set([
  'id_proof',
  'address_proof',
  'selfie',
  'bank_statement',
]);

const SUBMISSION_STATUSES = new Set(['pending', 'approved', 'rejected', 'not_submitted']);
const DOCUMENT_STATUSES = new Set(['pending', 'approved', 'rejected', 'not_uploaded']);
const REVIEW_STATUSES = new Set(['approved', 'rejected']);
const ADMIN_ROLES = new Set(['supermaster', 'master']);
const DOWNLOAD_PATH = /^\/api\/v1\/kyc\/documents\/([1-9]\d*)\/(id_proof|address_proof|selfie|bank_statement)\/download$/;
const INTEGER = /^[1-9]\d*$/;

const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isNonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0;

export const createAdminClosureKycAbortError = () => {
  const error = new Error('The KYC administration request was cancelled.');
  error.name = 'AbortError';
  return error;
};

export const isAdminClosureKycRequestCanceled = (error) => (
  error?.name === 'AbortError' || error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED'
);

const positiveId = (value) => {
  const text = value === undefined || value === null ? '' : String(value);
  return INTEGER.test(text) ? Number(text) : null;
};

const tenantIdFromUser = (user) => user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id;

/**
 * The route guard is not trusted as a principal proof. Each KYC operation derives
 * this complete, fixed scalar context from the current authenticated auth store.
 */
export const adminClosureKycPrincipalFromAuth = (user, isAuthenticated) => {
  const userId = positiveId(user?.id);
  const tenantId = positiveId(tenantIdFromUser(user));
  const role = typeof user?.role === 'string' ? user.role : null;
  if (isAuthenticated !== true || userId === null || tenantId === null || !ADMIN_ROLES.has(role)) {
    return null;
  }
  return Object.freeze({
    owner: Object.freeze({ user_id: userId, tenant_id: tenantId }),
    role,
  });
};

export const adminClosureKycIdentityKey = ({ user, isAuthenticated }) => {
  const userId = positiveId(user?.id);
  const tenantId = positiveId(tenantIdFromUser(user));
  const role = typeof user?.role === 'string' ? user.role : 'missing';
  return `auth:${isAuthenticated === true ? 'yes' : 'no'}|id:${userId ?? 'missing'}|tenant:${tenantId ?? 'missing'}|role:${role}`;
};

export const adminClosureKycAcknowledgement = (userId, documentType) => {
  const normalizedUserId = positiveId(userId);
  if (normalizedUserId === null || !ADMIN_CLOSURE_KYC_DOCUMENT_TYPES.has(documentType)) return null;
  return `REVIEW ${normalizedUserId} ${documentType}`;
};

const assertExpectedOwner = (owner) => {
  if (!isPlainObject(owner) || positiveId(owner.user_id) === null || positiveId(owner.tenant_id) === null) {
    throw new Error('The KYC administrator context is unavailable. Sign in again before continuing.');
  }
  return { user_id: positiveId(owner.user_id), tenant_id: positiveId(owner.tenant_id) };
};

const normalizeOwnerContext = (data, expectedOwner) => {
  if (!isPlainObject(data?.owner_context)) {
    throw new Error('The KYC response did not confirm the administrator context.');
  }
  const expected = assertExpectedOwner(expectedOwner);
  const received = {
    user_id: positiveId(data.owner_context.user_id),
    tenant_id: positiveId(data.owner_context.tenant_id),
  };
  if (received.user_id === null || received.tenant_id === null
    || received.user_id !== expected.user_id || received.tenant_id !== expected.tenant_id) {
    throw new Error('The KYC response belongs to a different administrator context.');
  }
  return Object.freeze(received);
};

const normalizedStatus = (value, allowed, label) => {
  if (value === null) return null;
  if (!allowed.has(value)) throw new Error(`The KYC ${label} was invalid.`);
  return value;
};

const normalizedTimestamp = (value, label) => {
  if (value === null) return null;
  if (!isNonEmptyString(value) || value.length > 64) throw new Error(`The KYC ${label} was invalid.`);
  return value;
};

const normalizedDocumentSummary = (value) => {
  if (!isPlainObject(value) || Object.keys(value).length !== ADMIN_CLOSURE_KYC_DOCUMENT_TYPES.size) {
    throw new Error('The KYC submission document summary was incomplete.');
  }
  const result = {};
  for (const type of ADMIN_CLOSURE_KYC_DOCUMENT_TYPES) {
    if (!hasOwn(value, type)) throw new Error('The KYC submission document summary was incomplete.');
    result[type] = normalizedStatus(value[type], DOCUMENT_STATUSES, 'document status');
  }
  return Object.freeze(result);
};

const normalizedPagination = (value) => {
  if (!isPlainObject(value)) throw new Error('The KYC submissions pagination was invalid.');
  const pagination = {};
  for (const key of ['page', 'per_page', 'total', 'pages']) {
    if (!Number.isSafeInteger(value[key]) || value[key] < 0 || ((key === 'page' || key === 'per_page') && value[key] < 1)) {
      throw new Error('The KYC submissions pagination was invalid.');
    }
    pagination[key] = value[key];
  }
  return Object.freeze(pagination);
};

const normalizedSubmission = (value) => {
  if (!isPlainObject(value) || positiveId(value.user_id) === null || !hasOwn(value, 'kyc_status')
    || !hasOwn(value, 'submitted_at') || !hasOwn(value, 'documents')) {
    throw new Error('The KYC submission response was incomplete.');
  }
  return Object.freeze({
    userId: positiveId(value.user_id),
    kycStatus: normalizedStatus(value.kyc_status, SUBMISSION_STATUSES, 'submission status'),
    submittedAt: normalizedTimestamp(value.submitted_at, 'submission timestamp'),
    documents: normalizedDocumentSummary(value.documents),
  });
};

export const normalizeAdminClosureKycSubmissions = (data, expectedOwner) => {
  if (!isPlainObject(data) || !Array.isArray(data.submissions) || !isPlainObject(data.filters)
    || typeof data.filters.status !== 'string' || !SUBMISSION_STATUSES.has(data.filters.status)
    || data.review_scope !== 'recorded_document_only') {
    throw new Error('The KYC submissions response was incomplete.');
  }
  const ownerContext = normalizeOwnerContext(data, expectedOwner);
  const seen = new Set();
  const submissions = data.submissions.map((entry) => {
    const submission = normalizedSubmission(entry);
    if (seen.has(submission.userId)) throw new Error('The KYC submissions response contained a duplicate subject.');
    seen.add(submission.userId);
    return submission;
  });
  return Object.freeze({
    ownerContext,
    reviewScope: data.review_scope,
    submissions: Object.freeze(submissions),
    pagination: normalizedPagination(data.pagination),
    filters: Object.freeze({ status: data.filters.status }),
  });
};

const canonicalDownloadPath = (value, userId, documentType) => {
  if (value === null) return null;
  if (!isNonEmptyString(value) || value.includes('?') || value.includes('#') || value.includes('%') || value.includes('\\')) {
    throw new Error('The KYC private download route was invalid.');
  }
  const match = DOWNLOAD_PATH.exec(value);
  if (!match || Number(match[1]) !== userId || match[2] !== documentType) {
    throw new Error('The KYC private download route was invalid.');
  }
  return `/api/v1/kyc/documents/${userId}/${documentType}/download`;
};

const normalizedDocumentDetail = (value, userId) => {
  if (!isPlainObject(value) || !ADMIN_CLOSURE_KYC_DOCUMENT_TYPES.has(value.type)
    || !isNonEmptyString(value.name) || !hasOwn(value, 'status') || !hasOwn(value, 'uploaded_at')
    || !hasOwn(value, 'notes') || !hasOwn(value, 'download_url')) {
    throw new Error('The KYC document detail was incomplete.');
  }
  if (value.notes !== null && (typeof value.notes !== 'string' || value.notes.length > 500)) {
    throw new Error('The KYC document review note was invalid.');
  }
  return Object.freeze({
    type: value.type,
    name: value.name,
    status: normalizedStatus(value.status, DOCUMENT_STATUSES, 'document status'),
    uploadedAt: normalizedTimestamp(value.uploaded_at, 'document timestamp'),
    notes: value.notes,
    downloadPath: canonicalDownloadPath(value.download_url, userId, value.type),
  });
};

export const normalizeAdminClosureKycDetail = (data, expectedOwner) => {
  if (!isPlainObject(data) || data.review_scope !== 'recorded_document_only' || !isPlainObject(data.user)
    || positiveId(data.user.id) === null || !isNonEmptyString(data.user.display_name)
    || !hasOwn(data, 'kyc_status') || !hasOwn(data, 'submitted_at') || !Array.isArray(data.documents)) {
    throw new Error('The KYC submission detail was incomplete.');
  }
  const ownerContext = normalizeOwnerContext(data, expectedOwner);
  const userId = positiveId(data.user.id);
  const seen = new Set();
  const documents = data.documents.map((document) => {
    const normalized = normalizedDocumentDetail(document, userId);
    if (seen.has(normalized.type)) throw new Error('The KYC submission detail contained duplicate documents.');
    seen.add(normalized.type);
    return normalized;
  });
  if (documents.length !== ADMIN_CLOSURE_KYC_DOCUMENT_TYPES.size) {
    throw new Error('The KYC submission detail was incomplete.');
  }
  return Object.freeze({
    ownerContext,
    reviewScope: data.review_scope,
    user: Object.freeze({ id: userId, displayName: data.user.display_name }),
    kycStatus: normalizedStatus(data.kyc_status, SUBMISSION_STATUSES, 'submission status'),
    submittedAt: normalizedTimestamp(data.submitted_at, 'submission timestamp'),
    documents: Object.freeze(documents),
  });
};

const normalizedReviewResult = (data, expectedOwner, requested) => {
  if (!isPlainObject(data) || data.review_scope !== 'recorded_document_only' || data.review_recorded !== true
    || !isPlainObject(data.user) || positiveId(data.user.id) !== requested.userId
    || !isPlainObject(data.document) || data.document.type !== requested.documentType
    || data.document.status !== requested.status || !hasOwn(data.document, 'notes')
    || !hasOwn(data.document, 'uploaded_at') || !hasOwn(data.document, 'download_url')) {
    throw new Error('The KYC document review response did not confirm the original document.');
  }
  const ownerContext = normalizeOwnerContext(data, expectedOwner);
  const document = normalizedDocumentDetail({
    ...data.document,
    name: requested.documentName,
  }, requested.userId);
  if (document.uploadedAt !== requested.expectedUploadedAt || document.notes !== requested.notes) {
    throw new Error('The KYC document review response did not confirm the original document.');
  }
  return Object.freeze({ ownerContext, document, userId: requested.userId, reviewRecorded: true });
};

const requestConfig = (signal, extra = {}) => ({ signal, _skipAuthRefresh: true, ...extra });

const assertNotAborted = (signal) => {
  if (signal?.aborted) throw createAdminClosureKycAbortError();
};

const requireReviewRequest = ({ userId, documentType, status, notes, acknowledgement, expectedUploadedAt, documentName }) => {
  const normalizedUserId = positiveId(userId);
  const expectedAcknowledgement = adminClosureKycAcknowledgement(normalizedUserId, documentType);
  if (normalizedUserId === null || !ADMIN_CLOSURE_KYC_DOCUMENT_TYPES.has(documentType)
    || !REVIEW_STATUSES.has(status) || acknowledgement !== expectedAcknowledgement
    || !isNonEmptyString(expectedUploadedAt) || expectedUploadedAt.length > 64
    || !isNonEmptyString(documentName) || typeof notes !== 'string' || notes.length > 500
    || (status === 'rejected' && !notes.trim())) {
    throw new Error('Confirm the original user and document with the required acknowledgement before saving the review.');
  }
  return Object.freeze({
    userId: normalizedUserId,
    documentType,
    status,
    notes: notes.trim() || null,
    acknowledgement,
    expectedUploadedAt,
    documentName,
  });
};

const requireDownloadDom = (documentRef, urlRef) => {
  if (!documentRef?.body || typeof documentRef.createElement !== 'function'
    || typeof urlRef?.createObjectURL !== 'function' || typeof urlRef?.revokeObjectURL !== 'function') {
    throw new Error('Private document downloads are unavailable in this browser.');
  }
};

/** Injected client/DOM inputs make the real Axios transport testable without network access. */
export const createAdminClosureKycService = (apiClient = api, domHooks = {}) => {
  if (!apiClient || typeof apiClient.get !== 'function' || typeof apiClient.put !== 'function') {
    throw new Error('A configured API client is required for KYC administration.');
  }
  const documentRef = domHooks.document ?? (typeof document !== 'undefined' ? document : undefined);
  const urlRef = domHooks.URL ?? (typeof URL !== 'undefined' ? URL : undefined);

  return Object.freeze({
    async loadSubmissions({ expectedOwner, status = 'pending', page = 1, perPage = 20, signal } = {}) {
      assertNotAborted(signal);
      assertExpectedOwner(expectedOwner);
      if (!SUBMISSION_STATUSES.has(status) || !Number.isSafeInteger(page) || page < 1
        || !Number.isSafeInteger(perPage) || perPage < 1 || perPage > 50) {
        throw new Error('The KYC submissions query was invalid.');
      }
      const response = await apiClient.get(ADMIN_CLOSURE_KYC_ENDPOINTS.submissions, requestConfig(signal, {
        params: { status, page, per_page: perPage },
      }));
      assertNotAborted(signal);
      return normalizeAdminClosureKycSubmissions(response?.data, expectedOwner);
    },

    async loadSubmission({ expectedOwner, userId, signal } = {}) {
      assertNotAborted(signal);
      assertExpectedOwner(expectedOwner);
      const normalizedUserId = positiveId(userId);
      if (normalizedUserId === null) throw new Error('The KYC submission identifier was invalid.');
      const response = await apiClient.get(
        ADMIN_CLOSURE_KYC_ENDPOINTS.submission(normalizedUserId),
        requestConfig(signal),
      );
      assertNotAborted(signal);
      const detail = normalizeAdminClosureKycDetail(response?.data, expectedOwner);
      if (detail.user.id !== normalizedUserId) {
        throw new Error('The KYC submission response did not confirm the selected user.');
      }
      return detail;
    },

    async reviewDocument({ expectedOwner, userId, documentType, status, notes, acknowledgement, expectedUploadedAt, documentName, signal } = {}) {
      assertNotAborted(signal);
      assertExpectedOwner(expectedOwner);
      const requested = requireReviewRequest({
        userId, documentType, status, notes, acknowledgement, expectedUploadedAt, documentName,
      });
      const response = await apiClient.put(
        ADMIN_CLOSURE_KYC_ENDPOINTS.documentReview(requested.userId, requested.documentType),
        {
          status: requested.status,
          notes: requested.notes,
          acknowledgement: requested.acknowledgement,
          expected_uploaded_at: requested.expectedUploadedAt,
        },
        requestConfig(signal),
      );
      assertNotAborted(signal);
      return normalizedReviewResult(response?.data, expectedOwner, requested);
    },

    async downloadDocument({ expectedOwner, userId, document, signal } = {}) {
      assertNotAborted(signal);
      assertExpectedOwner(expectedOwner);
      const normalizedUserId = positiveId(userId);
      if (normalizedUserId === null || !isPlainObject(document) || !ADMIN_CLOSURE_KYC_DOCUMENT_TYPES.has(document.type)) {
        throw new Error('The KYC document selection was invalid.');
      }
      const downloadPath = canonicalDownloadPath(document.downloadPath, normalizedUserId, document.type);
      if (!downloadPath) throw new Error('This KYC document is unavailable for private download.');
      const response = await apiClient.get(downloadPath, requestConfig(signal, { responseType: 'blob' }));
      assertNotAborted(signal);
      if (!response?.data) throw new Error('The KYC document download was empty.');
      requireDownloadDom(documentRef, urlRef);
      const objectUrl = urlRef.createObjectURL(response.data);
      let anchor;
      try {
        anchor = documentRef.createElement('a');
        anchor.href = objectUrl;
        anchor.download = `kyc-document-${normalizedUserId}-${document.type}`;
        anchor.style.display = 'none';
        documentRef.body.appendChild(anchor);
        anchor.click();
      } finally {
        if (anchor?.parentNode) anchor.parentNode.removeChild(anchor);
        urlRef.revokeObjectURL(objectUrl);
      }
    },
  });
};

export default createAdminClosureKycService;
