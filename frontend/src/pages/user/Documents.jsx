import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle, Download, FileText, Loader, Upload } from 'lucide-react';
import api from '../../services/api';
import useAuthStore from '../../store/authStore';
import {
  canDownloadKycDocument,
  createKycViewService,
  isKnownKycDocumentStatus,
  KycOperationGate,
  normaliseKycDocumentsResponse,
  validateKycUploadFile,
} from '../../services/kycViewService';

const kycViewService = createKycViewService(api);

const documentTypes = [
  {
    type: 'id_proof',
    label: 'ID Proof',
    description: 'Government-issued ID, such as a passport, driver license, or national ID.',
    required: true,
  },
  {
    type: 'address_proof',
    label: 'Address Proof',
    description: 'A document that records your address, such as a utility bill or bank statement.',
    required: true,
  },
  {
    type: 'selfie',
    label: 'Selfie with ID',
    description: 'A clear photo of you holding your ID.',
    required: true,
  },
  {
    type: 'bank_statement',
    label: 'Additional Bank Statement',
    description: 'An optional additional bank statement document.',
    required: false,
  },
];

const screenCopy = {
  documents: {
    heading: 'Documents & Verification',
    intro: 'Upload documents to your account record and review their recorded status.',
  },
  kyc: {
    heading: 'KYC Documents',
    intro: 'Submit the requested documents for identity verification.',
  },
};

const isRequestCancelled = (error, signal) => (
  signal?.aborted || error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError' || error?.name === 'AbortError'
);

const getErrorMessage = (error, fallback) => {
  const message = error?.response?.data?.error;
  return typeof message === 'string' && message.trim() ? message : fallback;
};

const toCurrentUserId = (value) => {
  const text = value === undefined || value === null ? '' : String(value);
  return /^[1-9]\d*$/.test(text) ? text : null;
};

const toContextValue = (value) => (
  value === undefined || value === null || String(value).trim() === '' ? 'missing' : String(value)
);

const buildPrincipalContext = (isAuthenticated, user) => {
  const id = toCurrentUserId(user?.id);
  const tenant = toContextValue(user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id);
  const role = toContextValue(user?.role);
  const authenticated = isAuthenticated === true;
  const ready = authenticated && id !== null && tenant !== 'missing' && role !== 'missing';
  const key =`auth:${authenticated ? 'yes' : 'no'}|id:${id ?? 'missing'}|tenant:${tenant}|role:${role}`;

  return {
    id,
    key,
    ready,
    unavailableMessage: !authenticated
      ? 'Document status is unavailable because the account session is not active.'
      : !id
        ? 'Document status is unavailable because the account identifier is missing.'
        : tenant === 'missing'
          ? 'Document status is unavailable because tenant membership is missing.'
          : role === 'missing'
            ? 'Document status is unavailable because the account role is missing.'
            : null,
  };
};

const getStatusColor = (status) => {
  switch (status) {
    case 'approved':
      return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100';
    case 'pending':
      return 'border-amber-400/30 bg-amber-400/10 text-amber-100';
    case 'rejected':
      return 'border-rose-400/50 bg-rose-950/60 text-rose-100';
    case 'not_uploaded':
      return 'border-slate-700 bg-slate-800 text-slate-200';
    default:
      return 'border-slate-700 bg-slate-800 text-slate-200';
  }
};

const formatRecordedUploadDate = (uploadedAt) => {
  if (uploadedAt === null || typeof uploadedAt !== 'string' || !uploadedAt.trim()) return null;
  const recordedAt = new Date(uploadedAt);
  return Number.isNaN(recordedAt.getTime()) ? 'Unavailable' : recordedAt.toLocaleDateString();
};

const formatRecordedStatus = (status) => {
  if (!isKnownKycDocumentStatus(status)) return 'Unavailable';
  return status.replaceAll('_', ' ');
};

const displayStatistic = (statistics, key) => (
  Number.isSafeInteger(statistics?.[key]) && statistics[key] >= 0 ? statistics[key] : '—'
);

const Header = ({ heading, intro }) => (
  <header className="mb-7 border-b border-cyan-900/30 pb-6">
    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Account documents</p>
    <h1 className="mep-heading mt-2 text-3xl font-bold tracking-tight text-white">{heading}</h1>
    <p className="mt-2 max-w-3xl text-slate-300">{intro}</p>
  </header>
);

function DocumentsContent({ copy, principal }) {
  const [documents, setDocuments] = useState(null);
  const [statistics, setStatistics] = useState(null);
  const [overallStatus, setOverallStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(principal.ready);
  const [activeAction, setActiveAction] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [refreshError, setRefreshError] = useState(null);
  const [actionErrors, setActionErrors] = useState({});
  const operationGateRef = useRef(new KycOperationGate());
  const mountedRef = useRef(false);
  const activeControllersRef = useRef(new Set());
  const latestLoadRef = useRef(0);
  const hasSuccessfulLoadRef = useRef(false);

  const beginRequest = useCallback(() => {
    const controller = new AbortController();
    activeControllersRef.current.add(controller);
    return controller;
  }, []);

  const finishRequest = useCallback((controller) => {
    activeControllersRef.current.delete(controller);
  }, []);

  const loadDocuments = useCallback(async ({ showLoading = false } = {}) => {
    if (!principal.ready) return false;

    const controller = beginRequest();
    const requestId = latestLoadRef.current + 1;
    latestLoadRef.current = requestId;

    if (showLoading && mountedRef.current) setIsLoading(true);
    if (mountedRef.current) {
      setLoadError(null);
      setRefreshError(null);
    }

    try {
      const response = await kycViewService.getDocuments({ signal: controller.signal });
      const data = normaliseKycDocumentsResponse(response?.data);
      if (!mountedRef.current || controller.signal.aborted || requestId !== latestLoadRef.current) {
        return false;
      }

      setDocuments(data.documents);
      setStatistics(data.statistics);
      setOverallStatus(data.overallStatus);
      hasSuccessfulLoadRef.current = true;
      return true;
    } catch (requestError) {
      if (!mountedRef.current || isRequestCancelled(requestError, controller.signal)
        || requestId !== latestLoadRef.current) {
        return false;
      }

      const message = getErrorMessage(requestError, 'Failed to load recorded document status. Please try again.');
      if (hasSuccessfulLoadRef.current) {
        // Keep the last confirmed record visible, but make its freshness explicit.
        setRefreshError(message);
      } else {
        setLoadError(message);
      }
      return false;
    } finally {
      finishRequest(controller);
      if (showLoading && mountedRef.current && requestId === latestLoadRef.current) {
        setIsLoading(false);
      }
    }
  }, [beginRequest, finishRequest, principal.ready]);

  useEffect(() => {
    mountedRef.current = true;
    if (principal.ready) {
      void loadDocuments({ showLoading: true });
    } else {
      setDocuments(null);
      setStatistics(null);
      setOverallStatus(null);
      setLoadError(principal.unavailableMessage);
      setRefreshError(null);
      setIsLoading(false);
    }

    return () => {
      mountedRef.current = false;
      activeControllersRef.current.forEach((controller) => controller.abort());
      activeControllersRef.current.clear();
    };
  }, [loadDocuments, principal.ready, principal.unavailableMessage]);

  const setActionError = useCallback((type, message) => {
    setActionErrors((previous) => ({ ...previous, [type]: message }));
  }, []);

  const clearActionError = useCallback((type) => {
    setActionErrors((previous) => {
      if (!previous[type]) return previous;
      const next = { ...previous };
      delete next[type];
      return next;
    });
  }, []);

  const handleFileUpload = async (type, event) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    // The browser input is cleared promptly; file data is never persisted.
    input.value = '';
    if (!file || !principal.ready) return;

    const validation = validateKycUploadFile(file);
    if (!validation.valid) {
      setActionError(type, validation.error);
      return;
    }

    const operation = operationGateRef.current.begin(type, 'upload');
    if (!operation) return;

    const controller = beginRequest();
    setActiveAction(operation);
    clearActionError(type);

    try {
      // The service rejects a mismatched type or any response that does not
      // explicitly record this one-file submission as pending.
      await kycViewService.uploadDocument(type, file, { signal: controller.signal });
      if (!mountedRef.current || controller.signal.aborted) return;

      const refreshed = await loadDocuments();
      if (mountedRef.current && !controller.signal.aborted && !refreshed) {
        setRefreshError('The document was submitted, but its recorded status could not be refreshed. Retry the status check; do not resubmit it yet.');
      }
    } catch (requestError) {
      if (mountedRef.current && !isRequestCancelled(requestError, controller.signal)) {
        const responseWasUnconfirmed = requestError?.message === 'The KYC upload response did not confirm the submitted document.';
        setActionError(
          type,
          responseWasUnconfirmed
            ? 'The upload response could not confirm the document record. Refresh the status before trying again.'
            : getErrorMessage(requestError, 'Failed to upload this document. Please try again.'),
        );
      }
    } finally {
      finishRequest(controller);
      if (operationGateRef.current.finish(operation) && mountedRef.current) {
        setActiveAction(null);
      }
    }
  };

  const handleDownload = async (documentInfo) => {
    if (!principal.ready) return;

    const operation = operationGateRef.current.begin(documentInfo.type, 'download');
    if (!operation) return;

    const controller = beginRequest();
    setActiveAction(operation);
    clearActionError(documentInfo.type);

    try {
      await kycViewService.downloadDocument(documentInfo, {
        signal: controller.signal,
        expectedUserId: principal.id,
      });
    } catch (requestError) {
      if (mountedRef.current && !isRequestCancelled(requestError, controller.signal)) {
        setActionError(documentInfo.type, getErrorMessage(requestError, 'Failed to download this document. Please try again.'));
      }
    } finally {
      finishRequest(controller);
      if (operationGateRef.current.finish(operation) && mountedRef.current) {
        setActiveAction(null);
      }
    }
  };

  const getDocumentInfo = (type) => documents?.find((documentInfo) => documentInfo.type === type) ?? null;

  if (isLoading) {
    return (
      <main aria-busy="true">
        <Header {...copy} />
        <div className="mep-panel flex min-h-[300px] items-center justify-center rounded-2xl border" role="status" aria-label="Loading documents">
          <Loader className="h-8 w-8 animate-spin text-cyan-300" aria-hidden="true" />
          <span className="ml-3 text-sm font-medium text-slate-100">Loading recorded document status…</span>
        </div>
      </main>
    );
  }

  if (!documents) {
    return (
      <main>
        <Header {...copy} />
        <section className="rounded-2xl border border-rose-900 bg-rose-950/40 p-5 text-rose-100" role="alert">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <div>
              <h2 className="mep-heading font-semibold">Recorded document status unavailable</h2>
              <p className="mt-1 text-sm">{loadError || 'Recorded document status is unavailable.'}</p>
              {principal.ready && (
                <button
                  type="button"
                  onClick={() => { void loadDocuments({ showLoading: true }); }}
                  className="mt-4 rounded-lg border border-rose-400 bg-slate-900 px-4 py-2 text-sm font-semibold text-slate-100 transition-colors hover:bg-rose-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 motion-reduce:transition-none"
                >
                  Retry status check
                </button>
              )}
            </div>
          </div>
        </section>
      </main>
    );
  }

  const recordedOverallStatus = overallStatus === 'not_submitted' ? 'Not submitted' : formatRecordedStatus(overallStatus);
  const hasNoRecordedDocuments = documents.length === 0;

  return (
    <main>
      <Header {...copy} />
      {refreshError && (
        <section className="mb-5 rounded-2xl border border-amber-400/50 bg-amber-950/50 p-5 text-amber-50" role="alert" aria-labelledby="stale-document-status-heading">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <div>
              <h2 id="stale-document-status-heading" className="mep-heading font-semibold">The displayed document status may be out of date</h2>
              <p className="mt-1 text-sm">{refreshError}</p>
              <button
                type="button"
                onClick={() => { void loadDocuments({ showLoading: true }); }}
                className="mt-4 rounded-lg border border-amber-300/70 bg-slate-900 px-4 py-2 text-sm font-semibold text-amber-50 transition-colors hover:bg-amber-100 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 motion-reduce:transition-none"
              >
                Retry status check
              </button>
            </div>
          </div>
        </section>
      )}
      <button type="button" disabled={Boolean(activeAction)} onClick={() => { void loadDocuments({ showLoading: true }); }} className="mb-5 rounded-lg border border-cyan-500 px-4 py-2 text-sm font-semibold text-cyan-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 disabled:opacity-50">Refresh status</button>

      <section className="mep-panel mb-7 overflow-hidden rounded-2xl border shadow-sm" aria-labelledby="recorded-status-heading">
        <div className="border-b border-slate-700/70 px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="recorded-status-heading" className="mep-heading text-xl font-semibold text-white">Recorded document status</h2>
              <p className="mt-1 max-w-2xl text-sm text-slate-300">
                These statuses reflect document records returned by the account service. They are not live identity evidence.
              </p>
            </div>
            <span className={`inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1 text-sm font-semibold ${getStatusColor(overallStatus)}`}>
              {overallStatus === 'approved' && <CheckCircle className="h-4 w-4" aria-hidden="true" />}
              Recorded overall: {recordedOverallStatus}
            </span>
          </div>
        </div>
        <dl className="grid grid-cols-2 divide-x divide-y divide-slate-700/70 sm:grid-cols-4 sm:divide-y-0">
          <div className="p-4 sm:p-5">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Document types</dt>
            <dd className="mt-1 text-2xl font-bold text-white">{displayStatistic(statistics, 'total')}</dd>
          </div>
          <div className="p-4 sm:p-5">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Recorded approved</dt>
            <dd className="mt-1 text-2xl font-bold text-cyan-300">{displayStatistic(statistics, 'approved')}</dd>
          </div>
          <div className="p-4 sm:p-5">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Pending review</dt>
            <dd className="mt-1 text-2xl font-bold text-amber-300">{displayStatistic(statistics, 'pending')}</dd>
          </div>
          <div className="p-4 sm:p-5">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Recorded rejected</dt>
            <dd className="mt-1 text-2xl font-bold text-rose-300">{displayStatistic(statistics, 'rejected')}</dd>
          </div>
        </dl>
      </section>

      {hasNoRecordedDocuments ? (
        <section className="mep-panel rounded-2xl border p-5 text-slate-200" role="status" aria-labelledby="no-recorded-documents-heading">
          <h2 id="no-recorded-documents-heading" className="mep-heading font-semibold text-white">No recorded documents yet</h2>
          <p className="mt-1 text-sm">The account service returned an empty document record. Reload the status before submitting or downloading a document.</p>
        </section>
      ) : (
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        {documentTypes.map((documentType) => {
          const documentInfo = getDocumentInfo(documentType.type);
          const recordedStatus = documentInfo?.status ?? null;
          const recordedUploadDate = formatRecordedUploadDate(documentInfo?.uploaded_at);
          const knownStatus = isKnownKycDocumentStatus(recordedStatus);
          const canUpload = Boolean(documentInfo)
            && (recordedStatus === 'not_uploaded' || recordedStatus === 'rejected');
          const canDownload = Boolean(documentInfo)
            && canDownloadKycDocument(documentInfo, principal.id);
          const isUploading = activeAction?.type === documentType.type && activeAction.kind === 'upload';
          const isDownloading = activeAction?.type === documentType.type && activeAction.kind === 'download';
          const inputId =`kyc-file-${documentType.type}`;
          const helpId =`${inputId}-help`;

          return (
            <section key={documentType.type} className="mep-panel rounded-2xl border p-5 shadow-sm sm:p-6" aria-labelledby={`${inputId}-title`}>
              <div className="flex items-start gap-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cyan-950/60 text-cyan-200">
                  <FileText className="h-6 w-6" aria-hidden="true" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 id={`${inputId}-title`} className="text-lg font-semibold text-white">
                    {documentType.label}
                    {documentType.required && <span className="ml-1 text-rose-300" aria-label="required">*</span>}
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-slate-300">{documentType.description}</p>
                </div>
              </div>

              {!documentInfo ? (
                <div className="mep-panel mt-5 rounded-xl border p-4 text-sm text-slate-200" role="status">
                  <p className="font-medium">Recorded document status unavailable</p>
                  <p className="mt-1">Reload the status before uploading or downloading this document.</p>
                </div>
              ) : (
                <>
                  <div className="mep-panel mt-5 flex items-center justify-between gap-3 rounded-xl border p-3">
                    <div className="min-w-0">
                      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Recorded status</p>
                      <p className="truncate text-sm font-semibold text-slate-100">{documentInfo.name}</p>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${getStatusColor(recordedStatus)}`}>
                      {formatRecordedStatus(recordedStatus)}
                    </span>
                  </div>

                  {!knownStatus && (
                    <p className="mt-3 rounded-lg border border-slate-700 bg-slate-800 p-3 text-sm text-slate-200" role="status">
                      This recorded status is unavailable for actions. Reload the status before trying again.
                    </p>
                  )}

                  {knownStatus && recordedStatus !== 'not_uploaded' && (
                    <div className="mt-3 text-sm text-slate-300">
                      {recordedUploadDate && <p>Recorded upload date: {recordedUploadDate}</p>}
                      {documentInfo.notes && (
                        <p className={`mt-3 rounded-lg border p-3 ${recordedStatus === 'rejected'
                          ? 'border-rose-900 bg-rose-950/40 text-rose-100   '
                          : 'border-cyan-900 bg-cyan-950/40 text-slate-100   '}`}>
                          <strong>Recorded note:</strong> {documentInfo.notes}
                        </p>
                      )}
                    </div>
                  )}

                  {canDownload && (
                    <button
                      type="button"
                      onClick={() => { void handleDownload(documentInfo); }}
                      disabled={Boolean(activeAction)}
                      className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-cyan-700 px-4 py-2.5 text-sm font-semibold text-cyan-200 transition-colors hover:bg-cyan-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
                    >
                      {isDownloading ? <Loader className="h-5 w-5 animate-spin" aria-hidden="true" /> : <Download className="h-5 w-5" aria-hidden="true" />}
                      {isDownloading ? 'Preparing download…' : 'Download recorded document'}
                    </button>
                  )}

                  {canUpload && (
                    <div className="mt-4 rounded-xl border border-dashed border-cyan-400 bg-cyan-950/30 p-4">
                      <label htmlFor={inputId} className="block text-sm font-semibold text-slate-100">
                        {isUploading ? 'Uploading document…' : recordedStatus === 'rejected' ? 'Choose a replacement document' : 'Choose a document to upload'}
                      </label>
                      <p id={helpId} className="mt-1 text-xs leading-5 text-slate-300">
                        PDF, JPG, JPEG, or PNG. Maximum file size: 10 MB.
                      </p>
                      <input
                        id={inputId}
                        type="file"
                        accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                        aria-describedby={helpId}
                        onChange={(event) => { void handleFileUpload(documentType.type, event); }}
                        disabled={Boolean(activeAction)}
                        className="mt-3 block w-full cursor-pointer rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-cyan-200 hover:file:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                      />
                    </div>
                  )}
                </>
              )}

              {actionErrors[documentType.type] && (
                <p className="mt-4 rounded-lg border border-rose-900 bg-rose-950/40 p-3 text-sm text-rose-100" role="alert">
                  {actionErrors[documentType.type]}
                </p>
              )}
            </section>
          );
        })}
      </div>
      )}
    </main>
  );
}

/**
 * Shared documents screen for /documents, /trader/documents and /kyc. The
 * principal key intentionally remounts state and aborts in-flight work when
 * authentication, account id, tenant, or role changes.
 */
export default function Documents({ mode = 'documents', intro }) {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const principal = useMemo(() => buildPrincipalContext(isAuthenticated, user), [isAuthenticated, user]);
  const copy = {
    ...(screenCopy[mode] || screenCopy.documents),
    ...(typeof intro === 'string' && intro.trim() ? { intro } : {}),
  };

  return (
    <div className="mep-screen min-h-screen rounded-2xl p-4 text-slate-100 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-6xl">
        <DocumentsContent key={principal.key} copy={copy} principal={principal} />
      </div>
    </div>
  );
}
