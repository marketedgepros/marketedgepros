const KYC_DOCUMENT_TYPES = new Set([
  'id_proof',
  'address_proof',
  'selfie',
  'bank_statement',
]);

export const KYC_UPLOAD_EXTENSIONS = new Set(['pdf', 'jpg', 'jpeg', 'png']);
// KycDocumentService reads and accepts at most 10 MiB. This is only an early UX
// check; the server remains authoritative for content inspection and validation.
export const MAX_KYC_FILE_BYTES = 10 * 1024 * 1024;

const KYC_DOWNLOAD_ROUTE = /^\/api\/v1\/kyc\/documents\/([1-9]\d*)\/(id_proof|address_proof|selfie|bank_statement)\/download$/;

const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const getDownloadRouteMetadata = (documentMetadata) => {
  if (!isPlainObject(documentMetadata) || !KYC_DOCUMENT_TYPES.has(documentMetadata.type)) {
    throw new Error('The KYC document metadata is invalid.');
  }

  // Current API responses expose `url`; `download_url` is accepted when supplied
  // by the endpoint. Never fall through from an invalid preferred route to another URL.
  const rawRoute = documentMetadata.download_url !== undefined
    ? documentMetadata.download_url
    : documentMetadata.url;

  if (typeof rawRoute !== 'string' || rawRoute.length === 0) {
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

  return { userId: match[1], documentType: match[2] };
};

/**
 * Returns the only route that may be requested for document metadata supplied by
 * the KYC endpoint. It intentionally does not accept caller-provided URLs.
 */
export const getCanonicalKycDownloadPath = (documentMetadata) => {
  const { userId, documentType } = getDownloadRouteMetadata(documentMetadata);
  return `/api/v1/kyc/documents/${userId}/${documentType}/download`;
};

export const canDownloadKycDocument = (documentMetadata) => {
  try {
    getCanonicalKycDownloadPath(documentMetadata);
    return true;
  } catch (error) {
    return false;
  }
};

export const isKycFullyVerified = (overallStatus) => overallStatus === 'approved';

/**
 * Validates only what the client can reliably preflight. The backend remains the
 * authority for content inspection and authorization.
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

/**
 * Keeps the page's response contract explicit: server data is held only in
 * component memory, and absent statistics never become a misleading zero.
 */
export const normaliseKycDocumentsResponse = (data) => {
  if (!isPlainObject(data) || !Array.isArray(data.documents) || typeof data.overall_status !== 'string') {
    throw new Error('The KYC document response was incomplete.');
  }

  return {
    documents: data.documents,
    statistics: isPlainObject(data.statistics) ? data.statistics : null,
    overallStatus: data.overall_status,
  };
};

const requireDownloadDom = (documentRef, urlRef) => {
  if (!documentRef?.body || typeof documentRef.createElement !== 'function'
    || typeof urlRef?.createObjectURL !== 'function' || typeof urlRef?.revokeObjectURL !== 'function') {
    throw new Error('Document downloads are unavailable in this browser.');
  }
};

/**
 * The Axios client is injected so tests exercise the same request and cleanup
 * logic without making a network request. The app supplies its configured
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

    uploadDocument: (documentType, file, { signal } = {}) => {
      if (!KYC_DOCUMENT_TYPES.has(documentType)) {
        throw new Error('The KYC document type is invalid.');
      }

      const validation = validateKycUploadFile(file);
      if (!validation.valid) {
        throw new Error(validation.error);
      }

      const formData = new FormData();
      formData.append('file', file);
      // Clear the configured client's JSON default. The browser supplies the boundary.
      return apiClient.post(`/kyc/documents/${documentType}/upload`, formData, {
        signal, headers: { 'Content-Type': undefined },
      });
    },

    downloadDocument: async (documentMetadata, { signal } = {}) => {
      // Axios appends even slash-prefixed paths to its /api/v1 baseURL.
      const downloadPath = getCanonicalKycDownloadPath(documentMetadata).slice('/api/v1'.length);
      const response = await apiClient.get(downloadPath, { responseType: 'blob', signal });
      if (!response?.data) {
        throw new Error('The KYC document download was empty.');
      }

      requireDownloadDom(documentRef, urlRef);
      const { userId, documentType } = getDownloadRouteMetadata(documentMetadata);
      const objectUrl = urlRef.createObjectURL(response.data);
      let anchor;

      try {
        anchor = documentRef.createElement('a');
        anchor.href = objectUrl;
        // Use only path-derived identifiers, never a raw storage filename or URL.
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

// Synchronous admission guard, shared by upload/download handlers. React state
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
