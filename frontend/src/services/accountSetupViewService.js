import { createProfileViewService } from './profileViewService.js';
import {
  getCanonicalKycDownloadPath,
  isKnownKycDocumentStatus,
  normaliseKycDocumentsResponse,
} from './kycViewService.js';

const REQUESTED_DOCUMENT_TYPES = Object.freeze([
  { type: 'id_proof', label: 'ID proof' },
  { type: 'address_proof', label: 'Address proof' },
  { type: 'selfie', label: 'Selfie with ID' },
]);

const PROFILE_FIELD_LABELS = Object.freeze([
  ['first_name', 'First name'],
  ['last_name', 'Last name'],
  ['email', 'Email address'],
  ['phone', 'Phone number'],
]);

const CANONICAL_DOCUMENT_ROUTE = /^\/api\/v1\/kyc\/documents\/([1-9]\d*)\/(id_proof|address_proof|selfie|bank_statement)\/download$/;

export class AccountSetupContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AccountSetupContractError';
  }
}

const abortError = () => {
  const error = new Error('Account setup request was cancelled.');
  error.name = 'AbortError';
  return error;
};

export const isAccountSetupRequestCanceled = (error) => (
  error?.name === 'AbortError' || error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED' || error?.__CANCEL__ === true
);

const isPositiveInteger = (value) => Number.isSafeInteger(value) && value > 0;

/** The guide accepts only the same strict authenticated context as the dashboard. */
export const normaliseAccountSetupOwner = (owner) => {
  if (!owner || !isPositiveInteger(owner.userId) || !isPositiveInteger(owner.tenantId)
    || typeof owner.role !== 'string' || !owner.role.trim() || owner.role !== owner.role.trim()) {
    throw new AccountSetupContractError('A complete authenticated account context is required.');
  }

  return Object.freeze({
    userId: owner.userId,
    tenantId: owner.tenantId,
    role: owner.role,
  });
};

const isRecordedText = (value) => typeof value === 'string' && value.trim().length > 0;

/**
 * Keep the guide view model deliberately free of profile values. It records only
 * which server fields were present, never names, email addresses, phones, or avatars.
 */
export const sanitiseProfileSetupSummary = (user, expectedOwner) => {
  const owner = normaliseAccountSetupOwner(expectedOwner);
  if (!user || typeof user !== 'object' || Array.isArray(user)
    || user.id !== owner.userId
    || user.tenant_id !== owner.tenantId
    || user.role !== owner.role) {
    throw new AccountSetupContractError('Profile data does not match the authenticated account context.');
  }

  const recordedFields = [];
  const missingFields = [];
  for (const [field, label] of PROFILE_FIELD_LABELS) {
    if (isRecordedText(user[field])) recordedFields.push(label);
    else missingFields.push(label);
  }

  return Object.freeze({
    recordedFields: Object.freeze(recordedFields),
    missingFields: Object.freeze(missingFields),
  });
};

const hasCanonicalDocumentRouteForOwner = (documentMetadata, expectedUserId) => {
  if (!isRecordedText(documentMetadata.url)) return false;

  try {
    getCanonicalKycDownloadPath(documentMetadata, expectedUserId);
    return true;
  } catch (error) {
    // A canonical-looking route for another owner is a cross-account response,
    // never an unavailable row. Do not keep or visit the route.
    if (CANONICAL_DOCUMENT_ROUTE.test(documentMetadata.url)) {
      throw new AccountSetupContractError('Document metadata does not match the authenticated account context.');
    }
    return false;
  }
};

/**
 * Convert the normalized Documents response into a non-sensitive setup summary.
 * The raw name, notes, URL, timestamp, unknown status, and overall KYC status are
 * intentionally discarded. An upload record needs all three pieces of evidence:
 * a recorded upload timestamp, a canonical same-owner API route, and a recognized
 * non-"not uploaded" document status.
 */
export const sanitiseDocumentSetupSummary = (data, expectedOwner) => {
  const owner = normaliseAccountSetupOwner(expectedOwner);
  const normalized = normaliseKycDocumentsResponse(data);
  // Reject foreign canonical metadata even for an optional row we do not summarize.
  for (const documentMetadata of normalized.documents) {
    hasCanonicalDocumentRouteForOwner(documentMetadata, owner.userId);
  }
  const byType = new Map(normalized.documents.map((documentMetadata) => [documentMetadata.type, documentMetadata]));
  const documents = REQUESTED_DOCUMENT_TYPES.map(({ type, label }) => {
    const documentMetadata = byType.get(type);
    if (!documentMetadata) {
      return Object.freeze({ type, label, state: 'unavailable', status: null });
    }

    const hasCanonicalOwnerRoute = hasCanonicalDocumentRouteForOwner(documentMetadata, owner.userId);
    if (documentMetadata.status === 'not_uploaded'
      && documentMetadata.uploaded_at === null && documentMetadata.url === null) {
      // An explicit authenticated endpoint result, not an invented empty row.
      return Object.freeze({ type, label, state: 'not-recorded', status: 'not_uploaded' });
    }
    const hasRecordedUpload = isRecordedText(documentMetadata.uploaded_at)
      && hasCanonicalOwnerRoute
      && isKnownKycDocumentStatus(documentMetadata.status)
      && documentMetadata.status !== 'not_uploaded';

    if (!hasRecordedUpload) {
      return Object.freeze({ type, label, state: 'unavailable', status: null });
    }

    return Object.freeze({
      type,
      label,
      state: documentMetadata.status === 'rejected' ? 'needs-attention' : 'recorded',
      // Known status values are product-safe metadata; no raw notes or provider claim is retained.
      status: documentMetadata.status,
    });
  });

  const recordedCount = documents.filter((documentMetadata) => (
    documentMetadata.state === 'recorded' || documentMetadata.state === 'needs-attention'
  )).length;
  return Object.freeze({
    documentTypesShown: REQUESTED_DOCUMENT_TYPES.length,
    documents: Object.freeze(documents),
    recordedCount,
    allRequestedRecordsPresent: recordedCount === REQUESTED_DOCUMENT_TYPES.length,
    hasRejectedRecord: documents.some((documentMetadata) => documentMetadata.state === 'needs-attention'),
  });
};

const call = (method, args, unavailableMessage) => {
  if (typeof method !== 'function') {
    return Promise.reject(new AccountSetupContractError(unavailableMessage));
  }
  try {
    return Promise.resolve(method(...args));
  } catch (error) {
    return Promise.reject(error);
  }
};

// Race request cancellation with adapters that ignore AbortSignal so stale responses
// cannot reach the sanitizers or component state.
const observeAbort = (promise, signal) => {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
  });
};

/**
 * The caller injects existing transports. This service performs no writes and only
 * GETs the established /profile and /kyc/documents endpoints once per caller action.
 */
export const createAccountSetupViewService = ({ profileTransport, documentsClient } = {}) => {
  const profileService = createProfileViewService(profileTransport);

  return Object.freeze({
    loadProfile: async (expectedOwner, signal) => {
      const owner = normaliseAccountSetupOwner(expectedOwner);
      const { user } = await profileService.getProfile({
        id: owner.userId,
        tenantId: owner.tenantId,
      }, signal);
      // createProfileViewService establishes strict id and tenant identity. Role is
      // explicitly checked here because it is a separate account-context boundary.
      return sanitiseProfileSetupSummary(user, owner);
    },

    loadDocuments: async (expectedOwner, signal) => {
      const owner = normaliseAccountSetupOwner(expectedOwner);
      const response = await observeAbort(
        call(
          documentsClient?.get,
          ['/kyc/documents', { signal }],
          'Document status transport is unavailable.',
        ),
        signal,
      );
      if (signal?.aborted) throw abortError();
      return sanitiseDocumentSetupSummary(response?.data, owner);
    },
  });
};

export { REQUESTED_DOCUMENT_TYPES };
