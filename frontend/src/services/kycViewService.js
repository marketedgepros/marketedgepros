export const KYC_DOCUMENT_TYPES = new Set([
  'id_proof',
  'address_proof',
  'selfie',
  'bank_statement',
]);

export const KYC_DOCUMENT_STATUSES = new Set([
  'not_uploaded',
  'pending',
  'approved',
  'rejected',
]);

const KYC_STATISTIC_KEYS = ['total', 'uploaded', 'approved', 'pending', 'rejected'];

export const KYC_UPLOAD_EXTENSIONS = new Set(['pdf', 'jpg', 'jpeg', 'png']);
// KycDocumentService accepts at most 10 MiB. This is an early UX check only;
// the server remains authoritative for file content and authorization.
export const MAX_KYC_FILE_BYTES = 10 * 1024 * 1024;

const KYC_DOWNLOAD_ROUTE = /^\/api\/v1\/kyc\/documents\/([1-9]\d*)\/(id_proof|address_proof|selfie|bank_statement)\/download$/;

const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isNonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0;

const createAbortError = () => {
  const error = new Error('The KYC document request was cancelled.');
  error.name = 'AbortError';
  return error;
};

const normaliseExpectedUserId = (expectedUserId) => {
  if (expectedUserId === undefined || expectedUserId === null) return null;
  const value = String(expectedUserId);
  return /^[1-9]\d*$/.test(value) ? value : null;
};

const getDownloadRouteMetadata = (documentMetadata, expectedUserId) => {
  if (!isPlainObject(documentMetadata) || !KYC_DOCUMENT_TYPES.has(documentMetadata.type)) {
    throw new Error('The KYC document metadata is invalid.');
  }

  // The deployed list endpoint exposes `url`; `download_url` is accepted only
  // when supplied by a compatible endpoint. Neither can be a storage URL.
  const rawRoute = documentMetadata.download_url !== undefined
    ? documentMetadata.download_url
    : documentMetadata.url;

  if (!isNonEmptyString(rawRoute)) {
    throw new Error('This KYC document is not available for download.');
  }

  // The route must be a literal API-relative path. Query/hash components,
  // escaped values, backslashes, and absolute URLs cannot be canonical routes.
  if (rawRoute.includes('?') || rawRoute.includes('#') || rawRoute.includes('%') || rawRoute.includes('\\')) {
    throw new Error('The KYC download route is invalid.');
  }

  const match = KYC_DOWNLOAD_ROUTE.exec(rawRoute);
  if (!match || match[2] !== documentMetadata.type) {
    throw new Error('The KYC download route is invalid.');
  }

  const expectedId = normaliseExpectedUserId(expectedUserId);
  if (expectedUserId !== undefined && expectedUserId !== null && expectedId !== match[1]) {
    throw new Error('The KYC document does not belong to the current account.');
  }

  return { userId: match[1], documentType: match[2] };
};

/**
 * Returns the only API path permitted for document metadata supplied by the
 * KYC endpoint. The optional expected user id lets the screen reject a stale
 * or cross-account response before requesting it; the server remains the
 * authorization authority for every download.
 */
export const getCanonicalKycDownloadPath = (documentMetadata, expectedUserId) => {
  const { userId, documentType } = getDownloadRouteMetadata(documentMetadata, expectedUserId);
  return `/api/v1/kyc/documents/${userId}/${documentType}/download`;
};

export const canDownloadKycDocument = (documentMetadata, expectedUserId) => {
  try {
    getCanonicalKycDownloadPath(documentMetadata, expectedUserId);
    return true;
  } catch (error) {
    return false;
  }
};

export const isKycFullyVerified = (overallStatus) => overallStatus === 'approved';

export const isKnownKycDocumentStatus = (status) => KYC_DOCUMENT_STATUSES.has(status);

/**
 * Validates only what the client can reliably preflight. The backend remains
 * the authority for content inspection, tenant membership, and authorization.
 */
export const validateKycUploadFile = (file) => {
  if (!file || typeof file.name !== 'string') {
    return { valid: false, error: 'Choose a PDF, JPG, JPEG, or PNG file.' };
  }

  const extension = file.name.includes('.')
    ? file.name.slice(file.name.lastIndexOf('.') + 1).toLowerCase()
    : '';
  if (!KYC_UPLOAD_EXTENSIONS.has(extension)) {
    return { valid: false, error: 'Please upload a PDF, JPG, JPEG, or PNG file.' };
  }

  if (!Number.isSafeInteger(file.size) || file.size <= 0) {
    return { valid: false, error: 'The selected file could not be validated.' };
  }

  if (file.size > MAX_KYC_FILE_BYTES) {
    return { valid: false, error: 'File size must be 10 MB or less.' };
  }

  return { valid: true };
};

const normaliseDocumentMetadata = (documentMetadata) => {
  if (!isPlainObject(documentMetadata)
    || !KYC_DOCUMENT_TYPES.has(documentMetadata.type)
    || !isNonEmptyString(documentMetadata.status)
    || !isNonEmptyString(documentMetadata.name)
    || !hasOwn(documentMetadata, 'uploaded_at')
    || !hasOwn(documentMetadata, 'notes')
    || !hasOwn(documentMetadata, 'url')) {
    throw new Error('The KYC document response was incomplete.');
  }

  if ((documentMetadata.uploaded_at !== null && !isNonEmptyString(documentMetadata.uploaded_at))
    || (documentMetadata.notes !== null && typeof documentMetadata.notes !== 'string')
    || (documentMetadata.url !== null && !isNonEmptyString(documentMetadata.url))) {
    throw new Error('The KYC document response contained invalid metadata.');
  }

  // `null` is a meaningful absence of a recorded upload timestamp. A nonempty
  // value must be a date that can be displayed safely; never pass Invalid Date
  // into the account screen or reinterpret it as `not_uploaded`.
  if (documentMetadata.uploaded_at !== null
    && !Number.isFinite(Date.parse(documentMetadata.uploaded_at))) {
    throw new Error('The KYC document response contained an invalid upload timestamp.');
  }

  // Return only the display/download contract. Do not retain arbitrary API
  // fields (which could contain unnecessary personal information) in view state.
  return {
    type: documentMetadata.type,
    name: documentMetadata.name,
    status: documentMetadata.status,
    uploaded_at: documentMetadata.uploaded_at,
    notes: documentMetadata.notes,
    url: documentMetadata.url,
  };
};

const normaliseStatistics = (statistics) => {
  if (statistics === undefined || statistics === null) return null;
  if (!isPlainObject(statistics)) {
    throw new Error('The KYC document statistics were invalid.');
  }

  const result = {};
  for (const key of KYC_STATISTIC_KEYS) {
    if (!hasOwn(statistics, key) || !Number.isSafeInteger(statistics[key]) || statistics[key] < 0) {
      throw new Error('The KYC document statistics were incomplete.');
    }
    result[key] = statistics[key];
  }
  return result;
};

/**
 * Checks the deployed GET shape without inventing records or zero counters.
 * An empty document list is explicit no-data; absent document types remain
 * unavailable in the screen rather than becoming uploadable `not_uploaded` rows.
 */
export const normaliseKycDocumentsResponse = (data) => {
  if (!isPlainObject(data) || !Array.isArray(data.documents) || !hasOwn(data, 'overall_status')) {
    throw new Error('The KYC document response was incomplete.');
  }

  if (data.overall_status !== null && !isNonEmptyString(data.overall_status)) {
    throw new Error('The KYC document response contained an invalid status.');
  }

  const documentTypes = new Set();
  const documents = data.documents.map((documentMetadata) => {
    const document = normaliseDocumentMetadata(documentMetadata);
    if (documentTypes.has(document.type)) {
      throw new Error('The KYC document response contained duplicate document types.');
    }
    documentTypes.add(document.type);
    return document;
  });

  return {
    documents,
    statistics: normaliseStatistics(data.statistics),
    overallStatus: data.overall_status,
  };
};

/**
 * A successful one-file POST must prove it recorded the same document type as
 * pending. The client never manufactures approved or submitted state.
 */
export const normaliseKycUploadResponse = (data, expectedDocumentType) => {
  if (!KYC_DOCUMENT_TYPES.has(expectedDocumentType)
    || !isPlainObject(data)
    || !isPlainObject(data.document)) {
    throw new Error('The KYC upload response was incomplete.');
  }

  const document = data.document;
  if (document.type !== expectedDocumentType || document.status !== 'pending'
    || !isNonEmptyString(document.name) || !isNonEmptyString(document.uploaded_at)) {
    throw new Error('The KYC upload response did not confirm the submitted document.');
  }

  return {
    type: document.type,
    name: document.name,
    status: document.status,
    uploaded_at: document.uploaded_at,
  };
};

const requireDownloadDom = (documentRef, urlRef) => {
  if (!documentRef?.body || typeof documentRef.createElement !== 'function'
    || typeof urlRef?.createObjectURL !== 'function' || typeof urlRef?.revokeObjectURL !== 'function') {
    throw new Error('Document downloads are unavailable in this browser.');
  }
};

/**
 * The Axios client is injected so focused tests exercise the same request and
 * cleanup logic without network access. The application supplies its configured
 * same-origin client, which already carries cookie/Bearer authentication.
 */
export const createKycViewService = (apiClient, domHooks = {}) => {
  if (!apiClient || typeof apiClient.get !== 'function' || typeof apiClient.post !== 'function') {
    throw new Error('A configured API client is required for KYC requests.');
  }

  const documentRef = domHooks.document ?? (typeof document !== 'undefined' ? document : undefined);
  const urlRef = domHooks.URL ?? (typeof URL !== 'undefined' ? URL : undefined);

  return {
    getDocuments: ({ signal } = {}) => apiClient.get('/kyc/documents', { signal }),

    uploadDocument: async (documentType, file, { signal } = {}) => {
      if (!KYC_DOCUMENT_TYPES.has(documentType)) {
        throw new Error('The KYC document type is invalid.');
      }

      const validation = validateKycUploadFile(file);
      if (!validation.valid) {
        throw new Error(validation.error);
      }
      if (signal?.aborted) throw createAbortError();

      const formData = new FormData();
      formData.append('file', file);
      // Clear the configured client's JSON default. The browser supplies the boundary.
      const response = await apiClient.post(`/kyc/documents/${documentType}/upload`, formData, {
        signal, headers: { 'Content-Type': undefined },
      });
      if (signal?.aborted) throw createAbortError();
      return normaliseKycUploadResponse(response?.data, documentType);
    },

    downloadDocument: async (documentMetadata, { signal, expectedUserId } = {}) => {
      // Validate and capture route metadata before any network or DOM side effect.
      const { userId, documentType } = getDownloadRouteMetadata(documentMetadata, expectedUserId);
      const downloadPath = `/kyc/documents/${userId}/${documentType}/download`;
      if (signal?.aborted) throw createAbortError();

      const response = await apiClient.get(downloadPath, { responseType: 'blob', signal });
      // A mock or adapter can resolve after abort; never create a blob URL or
      // click a DOM element once this context has been cancelled.
      if (signal?.aborted) throw createAbortError();
      if (!response?.data) {
        throw new Error('The KYC document download was empty.');
      }

      requireDownloadDom(documentRef, urlRef);
      const objectUrl = urlRef.createObjectURL(response.data);
      let anchor;

      try {
        anchor = documentRef.createElement('a');
        anchor.href = objectUrl;
        // Use only principal-bound path identifiers, never a storage filename or URL.
        anchor.download = `kyc-document-${userId}-${documentType}`;
        anchor.style.display = 'none';
        documentRef.body.appendChild(anchor);
        anchor.click();
      } finally {
        if (anchor?.parentNode) {
          anchor.parentNode.removeChild(anchor);
        }
        urlRef.revokeObjectURL(objectUrl);
      }
    },
  };
};

// Synchronous admission guard shared by upload/download handlers. React state
// updates alone do not prevent two clicks before the next render.
export class KycOperationGate {
  constructor() { this.current = null; }
  begin(type, kind) {
    if (this.current || !KYC_DOCUMENT_TYPES.has(type) || !['upload', 'download'].includes(kind)) return null;
    const operation = Object.freeze({ type, kind });
    this.current = operation;
    return operation;
  }
  finish(operation) {
    if (!operation || this.current !== operation) return false;
    this.current = null;
    return true;
  }
  get busy() { return this.current !== null; }
}
