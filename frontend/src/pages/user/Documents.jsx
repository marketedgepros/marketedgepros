import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle, Download, FileText, Loader, Upload } from 'lucide-react';
import api from '../../services/api';
import {
  canDownloadKycDocument,
  createKycViewService,
  KycOperationGate,
  isKycFullyVerified,
  normaliseKycDocumentsResponse,
  validateKycUploadFile,
} from '../../services/kycViewService';

const kycViewService = createKycViewService(api);

const documentTypes = [
  {
    type: 'id_proof',
    label: 'ID Proof',
    description: 'Government-issued ID (passport, driver license, or national ID)',
    required: true,
  },
  {
    type: 'address_proof',
    label: 'Address Proof',
    description: 'Utility bill or bank statement',
    required: true,
  },
  {
    type: 'selfie',
    label: 'Selfie with ID',
    description: 'A clear photo of you holding your ID',
    required: true,
  },
  {
    type: 'bank_statement',
    label: 'Bank Statement',
    description: 'Statement requested for withdrawal verification',
    required: false,
  },
];

const isRequestCancelled = (error, signal) => (
  signal?.aborted || error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError'
);

const getErrorMessage = (error, fallback) => {
  const message = error?.response?.data?.error;
  return typeof message === 'string' && message.trim() ? message : fallback;
};

const getStatusColor = (status) => {
  switch (status) {
    case 'approved':
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
    case 'pending':
      return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
    case 'rejected':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
    default:
      return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200';
  }
};

const formatStatus = (status) => {
  if (typeof status !== 'string' || !status) return 'Unavailable';
  return status.replaceAll('_', ' ');
};

const displayStatistic = (statistics, key) => (
  Number.isFinite(statistics?.[key]) ? statistics[key] : '—'
);

export default function Documents() {
  const [documents, setDocuments] = useState(null);
  const [statistics, setStatistics] = useState(null);
  const [overallStatus, setOverallStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [uploadingType, setUploadingType] = useState(null);
  const [downloadingType, setDownloadingType] = useState(null);
  const operationGateRef = useRef(new KycOperationGate());
  const [error, setError] = useState(null);
  const mountedRef = useRef(false);
  const activeControllersRef = useRef(new Set());
  const latestLoadRef = useRef(0);

  const beginRequest = useCallback(() => {
    const controller = new AbortController();
    activeControllersRef.current.add(controller);
    return controller;
  }, []);

  const finishRequest = useCallback((controller) => {
    activeControllersRef.current.delete(controller);
  }, []);

  const loadDocuments = useCallback(async ({ showLoading = false } = {}) => {
    const controller = beginRequest();
    const requestId = latestLoadRef.current + 1;
    latestLoadRef.current = requestId;

    if (showLoading && mountedRef.current) {
      setIsLoading(true);
    }
    if (mountedRef.current) {
      setError(null);
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
      return true;
    } catch (requestError) {
      if (!mountedRef.current || isRequestCancelled(requestError, controller.signal)
        || requestId !== latestLoadRef.current) {
        return false;
      }

      // Do not retain stale status data or turn missing values into zero after an error.
      setDocuments(null);
      setStatistics(null);
      setOverallStatus(null);
      setError(getErrorMessage(requestError, 'Failed to load documents. Please try again.'));
      return false;
    } finally {
      finishRequest(controller);
      if (showLoading && mountedRef.current && requestId === latestLoadRef.current) {
        setIsLoading(false);
      }
    }
  }, [beginRequest, finishRequest]);

  useEffect(() => {
    mountedRef.current = true;
    loadDocuments({ showLoading: true });

    return () => {
      mountedRef.current = false;
      activeControllersRef.current.forEach((controller) => controller.abort());
      activeControllersRef.current.clear();
    };
  }, [loadDocuments]);

  const handleFileUpload = async (type, event) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    // Release the browser input value promptly; files are not persisted by this page.
    input.value = '';
    if (!file) return;

    const validation = validateKycUploadFile(file);
    if (!validation.valid) {
      setError(validation.error);
      return;
    }

    const operation = operationGateRef.current.begin(type, 'upload');
    if (!operation) return;
    const controller = beginRequest();
    setUploadingType(type);
    setError(null);

    try {
      await kycViewService.uploadDocument(type, file, { signal: controller.signal });
      const refreshed = await loadDocuments();
      if (mountedRef.current && !controller.signal.aborted && !refreshed) {
        setError('Document submitted, but the current verification status could not be refreshed.');
      }
    } catch (requestError) {
      if (mountedRef.current && !isRequestCancelled(requestError, controller.signal)) {
        setError(getErrorMessage(requestError, 'Failed to upload document. Please try again.'));
      }
    } finally {
      finishRequest(controller);
      if (operationGateRef.current.finish(operation) && mountedRef.current) {
        setUploadingType(null);
      }
    }
  };

  const handleDownload = async (documentInfo) => {
    const operation = operationGateRef.current.begin(documentInfo.type, 'download');
    if (!operation) return;
    const controller = beginRequest();
    setDownloadingType(documentInfo.type);
    setError(null);

    try {
      await kycViewService.downloadDocument(documentInfo, { signal: controller.signal });
    } catch (requestError) {
      if (mountedRef.current && !isRequestCancelled(requestError, controller.signal)) {
        setError(getErrorMessage(requestError, 'Failed to download document. Please try again.'));
      }
    } finally {
      finishRequest(controller);
      if (operationGateRef.current.finish(operation) && mountedRef.current) {
        setDownloadingType(null);
      }
    }
  };

  const getDocumentInfo = (type) => documents?.find((documentInfo) => documentInfo.type === type);
  const isFullyVerified = isKycFullyVerified(overallStatus);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]" role="status" aria-label="Loading documents">
        <Loader className="w-8 h-8 text-purple-500 animate-spin" />
      </div>
    );
  }

  if (!documents) {
    return (
      <div>
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">Documents &amp; Verification</h1>
          <p className="text-gray-600 dark:text-gray-400">Upload your documents for account verification</p>
        </div>
        <div className="p-4 bg-red-100 dark:bg-red-900/20 border border-red-400 dark:border-red-800 text-red-700 dark:text-red-400 rounded-lg">
          <p>{error || 'Document status is unavailable.'}</p>
          <button
            type="button"
            onClick={() => loadDocuments({ showLoading: true })}
            className="mt-3 px-4 py-2 bg-white dark:bg-gray-800 border border-red-300 dark:border-red-700 rounded-lg text-sm font-medium"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">Documents &amp; Verification</h1>
        <p className="text-gray-600 dark:text-gray-400">Upload your documents for account verification</p>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-100 dark:bg-red-900/20 border border-red-400 dark:border-red-800 text-red-700 dark:text-red-400 rounded-lg">
          {error}
        </div>
      )}

      <div className="mb-6 bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Verification Status</h2>
          {isFullyVerified ? (
            <span className="inline-flex items-center gap-2 px-3 py-1 bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 rounded-full text-sm font-semibold">
              <CheckCircle className="w-4 h-4" />
              Fully Verified
            </span>
          ) : (
            <span className={`px-3 py-1 text-sm font-semibold rounded-full ${getStatusColor(overallStatus)}`}>
              Overall: {formatStatus(overallStatus)}
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Document Types</p>
            <p className="text-3xl font-bold text-gray-900 dark:text-white">{displayStatistic(statistics, 'total')}</p>
          </div>
          <div className="text-center p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Approved</p>
            <p className="text-3xl font-bold text-green-600 dark:text-green-400">{displayStatistic(statistics, 'approved')}</p>
          </div>
          <div className="text-center p-4 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Pending Review</p>
            <p className="text-3xl font-bold text-yellow-600 dark:text-yellow-400">{displayStatistic(statistics, 'pending')}</p>
          </div>
          <div className="text-center p-4 bg-red-50 dark:bg-red-900/20 rounded-lg">
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Rejected</p>
            <p className="text-3xl font-bold text-red-600 dark:text-red-400">{displayStatistic(statistics, 'rejected')}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {documentTypes.map((documentType) => {
          const documentInfo = getDocumentInfo(documentType.type);
          const status = documentInfo?.status || 'not_uploaded';
          const canDownload = documentInfo && canDownloadKycDocument(documentInfo);
          const canUpload = status === 'not_uploaded' || status === 'rejected';
          const isUploading = uploadingType === documentType.type;
          const isDownloading = downloadingType === documentType.type;

          return (
            <div key={documentType.type} className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-start gap-4 mb-4">
                <div className="w-12 h-12 bg-purple-100 dark:bg-purple-900/20 rounded-lg flex items-center justify-center flex-shrink-0">
                  <FileText className="w-6 h-6 text-purple-600 dark:text-purple-400" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    {documentType.label}
                    {documentType.required && <span className="text-red-500 ml-1">*</span>}
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{documentType.description}</p>
                </div>
              </div>

              {documentInfo && status !== 'not_uploaded' && (
                <div className="mb-3">
                  <div className="flex justify-between items-center p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white">{documentInfo.name || documentType.label}</p>
                      {documentInfo.uploaded_at && (
                        <p className="text-xs text-gray-600 dark:text-gray-400">
                          Uploaded: {new Date(documentInfo.uploaded_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>
                    <span className={`px-2 py-1 text-xs font-semibold rounded ${getStatusColor(status)}`}>
                      {formatStatus(status)}
                    </span>
                  </div>

                  {documentInfo.notes && (
                    <div className={`p-3 rounded-lg mt-3 ${
                      status === 'rejected'
                        ? 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'
                        : 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800'
                    }`}>
                      <p className={`text-sm ${
                        status === 'rejected'
                          ? 'text-red-800 dark:text-red-300'
                          : 'text-blue-800 dark:text-blue-300'
                      }`}>
                        <strong>Note:</strong> {documentInfo.notes}
                      </p>
                    </div>
                  )}

                  {canDownload && (
                    <button
                      type="button"
                      onClick={() => handleDownload(documentInfo)}
                      disabled={Boolean(uploadingType || downloadingType)}
                      className="mt-3 flex items-center justify-center gap-2 w-full px-4 py-2 border border-purple-600 text-purple-700 dark:text-purple-300 rounded-lg hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors disabled:opacity-50"
                    >
                      {isDownloading ? <Loader className="w-5 h-5 animate-spin" /> : <Download className="w-5 h-5" />}
                      {isDownloading ? 'Preparing download...' : 'Download Document'}
                    </button>
                  )}
                </div>
              )}

              {canUpload && (
                <label className={`flex items-center justify-center gap-2 w-full px-4 py-2 bg-gradient-to-r from-purple-600 to-purple-800 text-white rounded-lg hover:from-purple-700 hover:to-purple-900 transition-colors cursor-pointer ${
                  isUploading ? 'opacity-50 cursor-not-allowed' : ''
                }`}>
                  {isUploading ? (
                    <>
                      <Loader className="w-5 h-5 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="w-5 h-5" />
                      {status === 'rejected' ? 'Re-upload Document' : 'Upload Document'}
                    </>
                  )}
                  <input
                    type="file"
                    accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                    onChange={(event) => handleFileUpload(documentType.type, event)}
                    disabled={Boolean(uploadingType || downloadingType)}
                    className="hidden"
                  />
                </label>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
