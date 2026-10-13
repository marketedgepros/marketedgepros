import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileCheck2,
  FileText,
  LoaderCircle,
  ShieldCheck,
  X,
  XCircle,
} from 'lucide-react';
import { useToast } from '../../contexts/ToastContext';
import useAuthStore from '../../store/authStore';
import useAdminClosureKyc from '../../hooks/useAdminClosureKyc.js';
import useDialogFocus from '../../hooks/useDialogFocus.js';
import {
  adminClosureKycAcknowledgement,
  createAdminClosureKycService,
  isAdminClosureKycRequestCanceled,
} from '../../services/adminClosureKycService.js';

const kycAdminService = createAdminClosureKycService();

const DOCUMENT_LABELS = {
  id_proof: 'ID proof',
  address_proof: 'Address proof',
  selfie: 'Selfie with ID',
  bank_statement: 'Bank statement',
};

const statusStyle = {
  pending: 'border-amber-400/40 bg-amber-400/10 text-amber-100',
  approved: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-100',
  rejected: 'border-rose-400/40 bg-rose-400/10 text-rose-100',
  not_uploaded: 'border-slate-600 bg-slate-800 text-slate-200',
};

const isKnownStatus = (value) => Object.prototype.hasOwnProperty.call(statusStyle, value);
const formatStatus = (value) => (isKnownStatus(value) ? value.replaceAll('_', ' ') : 'Unavailable');
const formatDate = (value) => {
  if (!value) return 'Not recorded';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'Recorded date unavailable' : parsed.toLocaleString();
};
const errorMessage = (error, fallback) => {
  const message = error?.response?.data?.error;
  return typeof message === 'string' && message.trim() ? message : fallback;
};

export function KycStatusPill({ value }) {
  return (
    <span className={`inline-flex max-w-full items-center rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${statusStyle[value] || 'border-slate-600 bg-slate-800 text-slate-200'}`}>
      {formatStatus(value)}
    </span>
  );
}

export function KycReviewNotice() {
  return (
    <section className="rounded-2xl border border-cyan-900/60 bg-cyan-950/30 p-4 text-sm text-slate-200" aria-label="Recorded document review scope">
      <div className="flex gap-3">
        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
        <p>
          This workspace records a manual review of submitted documents only. It does not verify a provider identity and does not change wallet, payout, trading, or MT5 eligibility.
        </p>
      </div>
    </section>
  );
}

export function KycSubmissionList({
  list,
  selectedUserId,
  onSelect,
  onPreviousPage,
  onNextPage,
  canPreviousPage,
  canNextPage,
  disabled,
}) {
  if (list.loading) {
    return (
      <section className="mep-panel rounded-2xl border p-8" aria-busy="true" aria-label="Loading pending KYC submissions">
        <div className="flex items-center gap-3 text-slate-200" role="status">
          <LoaderCircle className="h-5 w-5 animate-spin text-cyan-300" aria-hidden="true" />
          Loading recorded pending submissions…
        </div>
      </section>
    );
  }
  if (list.error) {
    return (
      <section className="rounded-2xl border border-rose-900 bg-rose-950/40 p-5 text-rose-100" role="alert">
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <div>
            <h2 className="mep-heading font-semibold">Pending submissions unavailable</h2>
            <p className="mt-1 text-sm">{errorMessage(list.error, 'The recorded KYC submissions could not be loaded. Try a manual refresh.')}</p>
          </div>
        </div>
      </section>
    );
  }
  if (!list.value?.submissions.length) {
    return (
      <section className="mep-panel rounded-2xl border p-8 text-center text-slate-300">
        <FileCheck2 className="mx-auto h-12 w-12 text-cyan-300/70" aria-hidden="true" />
        <h2 className="mep-heading mt-3 text-lg font-semibold text-white">No pending KYC submissions</h2>
        <p className="mt-2 text-sm">No pending submissions are available to display.</p>
      </section>
    );
  }
  return (
    <section className="mep-panel overflow-hidden rounded-2xl border shadow-sm" aria-labelledby="kyc-submissions-heading">
      <div className="border-b border-slate-700 px-5 py-4 sm:px-6">
        <h2 id="kyc-submissions-heading" className="mep-heading text-lg font-semibold text-white">Pending recorded submissions</h2>
        <p className="mt-1 text-sm text-slate-300">{list.value.pagination.total} pending record{list.value.pagination.total === 1 ? '' : 's'} in this scoped result.</p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[720px] w-full text-left">
          <thead className="bg-slate-950/80 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th scope="col" className="px-5 py-3 font-semibold">Subject</th>
              <th scope="col" className="px-5 py-3 font-semibold">Submitted</th>
              <th scope="col" className="px-5 py-3 font-semibold">Document records</th>
              <th scope="col" className="px-5 py-3 font-semibold">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {list.value.submissions.map((submission) => (
              <tr key={submission.userId} className={selectedUserId === submission.userId ? 'bg-cyan-950/30' : 'hover:bg-slate-800/70'}>
                <td className="px-5 py-4 align-top">
                  <p className="font-semibold text-white">User #{submission.userId}</p>
                  <p className="mt-1 text-xs text-slate-400">Recorded status: {formatStatus(submission.kycStatus)}</p>
                </td>
                <td className="px-5 py-4 align-top text-sm text-slate-300">{formatDate(submission.submittedAt)}</td>
                <td className="px-5 py-4 align-top">
                  <div className="flex max-w-md flex-wrap gap-1.5">
                    {Object.entries(submission.documents).map(([type, status]) => (
                      <span key={type} className="inline-flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-200">
                        {DOCUMENT_LABELS[type]}: <span className="capitalize text-slate-100">{formatStatus(status)}</span>
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-5 py-4 align-top">
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onSelect(submission.userId)}
                    className="rounded-lg border border-cyan-500/70 bg-cyan-950/40 px-3 py-2 text-sm font-semibold text-cyan-100 transition-colors hover:bg-cyan-900/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {selectedUserId === submission.userId ? 'Viewing record' : 'Review documents'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {list.value.pagination.pages > 1 && (
        <nav className="flex flex-col gap-3 border-t border-slate-700 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6" aria-label="Pending KYC submission pages">
          <p className="text-sm text-slate-300" aria-live="polite">Page {list.value.pagination.page} of {list.value.pagination.pages}</p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={disabled || !canPreviousPage}
              onClick={onPreviousPage}
              className="rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-100 hover:border-cyan-300 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous page
            </button>
            <button
              type="button"
              disabled={disabled || !canNextPage}
              onClick={onNextPage}
              className="rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-100 hover:border-cyan-300 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next page
            </button>
          </div>
        </nav>
      )}
    </section>
  );
}

export function KycSubmissionDetail({ detail, onDownload, onReview, disabled }) {
  if (detail.loading) {
    return (
      <section className="mep-panel rounded-2xl border p-6" aria-busy="true">
        <div className="flex items-center gap-3 text-slate-200" role="status">
          <LoaderCircle className="h-5 w-5 animate-spin text-cyan-300" aria-hidden="true" />
          Loading selected document record…
        </div>
      </section>
    );
  }
  if (detail.error) {
    return (
      <section className="rounded-2xl border border-rose-900 bg-rose-950/40 p-5 text-rose-100" role="alert">
        <h2 className="mep-heading font-semibold">Selected submission unavailable</h2>
        <p className="mt-1 text-sm">{errorMessage(detail.error, 'The selected document record could not be loaded. Return to the pending list and select it again.')}</p>
      </section>
    );
  }
  if (!detail.value) {
    return (
      <section className="mep-panel rounded-2xl border border-dashed p-6 text-sm text-slate-300" role="status">
        Select a pending submission to view its recorded documents. No document data is retained until a scoped detail response is returned.
      </section>
    );
  }
  const { user, documents, kycStatus, submittedAt } = detail.value;
  return (
    <section className="mep-panel rounded-2xl border shadow-sm" aria-labelledby="kyc-detail-heading">
      <div className="border-b border-slate-700 px-5 py-5 sm:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Selected recorded submission</p>
            <h2 id="kyc-detail-heading" className="mep-heading mt-1 break-words text-xl font-semibold text-white">{user.displayName} <span className="text-slate-400">· User #{user.id}</span></h2>
            <p className="mt-1 text-sm text-slate-300">Submitted: {formatDate(submittedAt)}</p>
          </div>
          <KycStatusPill value={kycStatus} />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 p-5 sm:p-6 lg:grid-cols-2">
        {documents.map((document) => {
          const canReview = document.status === 'pending' && Boolean(document.uploadedAt && document.downloadPath);
          return (
            <article key={document.type} className="mep-panel flex min-w-0 flex-col rounded-xl border p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <FileText className="h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
                    <h3 className="break-words font-semibold text-white">{document.name}</h3>
                  </div>
                  <p className="mt-2 text-xs text-slate-400">Recorded upload: {formatDate(document.uploadedAt)}</p>
                </div>
                <KycStatusPill value={document.status} />
              </div>
              {document.notes && <p className="mt-3 break-words rounded-lg border border-slate-700 bg-slate-800 p-3 text-sm text-slate-200"><strong>Recorded note:</strong> {document.notes}</p>}
              {!isKnownStatus(document.status) && <p className="mt-3 rounded-lg border border-slate-700 bg-slate-800 p-3 text-sm text-slate-200">This record has an unavailable status and cannot be acted on.</p>}
              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                {document.downloadPath && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onDownload(document)}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg border border-cyan-600 px-3 py-2 text-sm font-semibold text-cyan-200 hover:bg-cyan-950/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Download className="h-4 w-4" aria-hidden="true" /> Download privately
                  </button>
                )}
                {canReview && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onReview(document, 'approved')}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Record approval
                  </button>
                )}
                {canReview && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onReview(document, 'rejected')}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-rose-700 px-3 py-2 text-sm font-semibold text-white hover:bg-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <XCircle className="h-4 w-4" aria-hidden="true" /> Record rejection
                  </button>
                )}
              </div>
              {document.status === 'pending' && !canReview && <p className="mt-3 text-sm text-amber-200">This pending record cannot be reviewed until a current private document and upload timestamp are returned.</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function KycDocumentReviewDialog({ review, onClose, onChange, onSubmit, isSaving }) {
  const closeDialog = () => {
    if (!isSaving) onClose();
  };
  const dialogRef = useDialogFocus({ open: Boolean(review), onClose: closeDialog });
  if (!review) return null;
  const acknowledgement = adminClosureKycAcknowledgement(review.userId, review.document.type);
  const needsReason = review.status === 'rejected';
  const canSave = acknowledgement !== null
    && review.acknowledgement === acknowledgement
    && (!needsReason || review.notes.trim().length > 0)
    && !isSaving;
  return (
    <div className="fixed inset-0 z-50 flex items-end bg-slate-950/80 p-4 sm:items-center sm:justify-center" role="presentation">
      <section ref={dialogRef} className="mep-panel max-h-[calc(100vh-2rem)] w-full max-w-xl overflow-y-auto rounded-2xl border p-5 shadow-2xl sm:p-6" role="dialog" aria-modal="true" aria-labelledby="kyc-review-dialog-title">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Manual recorded review</p>
            <h2 id="kyc-review-dialog-title" className="mep-heading mt-1 text-xl font-semibold text-white">{review.status === 'approved' ? 'Record document approval' : 'Record document rejection'}</h2>
          </div>
          <button type="button" disabled={isSaving} onClick={closeDialog} className="rounded-md p-1 text-slate-300 hover:bg-slate-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50" aria-label="Close recorded document review dialog">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="mt-5 rounded-xl border border-cyan-900/60 bg-cyan-950/30 p-4 text-sm text-slate-100">
          <p><strong>Original subject:</strong> User #{review.userId}</p>
          <p className="mt-1"><strong>Original document:</strong> {review.document.name}</p>
          <p className="mt-1"><strong>Recorded upload:</strong> {formatDate(review.document.uploadedAt)}</p>
        </div>
        <p className="mt-4 text-sm leading-6 text-slate-300">This saves a document-review record only. It is not provider identity proof and it does not change account eligibility.</p>
        <label htmlFor="kyc-review-note" className="mt-5 block text-sm font-semibold text-slate-100">{needsReason ? 'Recorded rejection reason' : 'Recorded review note (optional)'}</label>
        <textarea
          id="kyc-review-note"
          value={review.notes}
          onChange={(event) => onChange({ notes: event.target.value })}
          maxLength={500}
          required={needsReason}
          disabled={isSaving}
          data-autofocus="true"
          className="mt-2 min-h-24 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none focus:ring-2 focus:ring-cyan-400/40 disabled:opacity-50"
          placeholder={needsReason ? 'Explain why this document record was rejected' : 'Optional recorded note'}
        />
        <label htmlFor="kyc-review-acknowledgement" className="mt-5 block text-sm font-semibold text-slate-100">Type the acknowledgement to confirm this original user and document</label>
        <p id="kyc-review-acknowledgement-help" className="mt-1 break-all rounded-lg border border-slate-700 bg-slate-950 p-3 font-mono text-xs text-cyan-200">{acknowledgement}</p>
        <input
          id="kyc-review-acknowledgement"
          value={review.acknowledgement}
          onChange={(event) => onChange({ acknowledgement: event.target.value })}
          aria-describedby="kyc-review-acknowledgement-help"
          autoComplete="off"
          spellCheck="false"
          disabled={isSaving}
          className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 font-mono text-sm text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none focus:ring-2 focus:ring-cyan-400/40 disabled:opacity-50"
          placeholder="Type the exact acknowledgement"
        />
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button type="button" disabled={isSaving} onClick={closeDialog} className="rounded-lg border border-slate-600 px-4 py-2.5 text-sm font-semibold text-slate-100 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">Cancel</button>
          <button type="button" disabled={!canSave} onClick={onSubmit} className={`rounded-lg px-4 py-2.5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50 ${review.status === 'approved' ? 'bg-emerald-700 hover:bg-emerald-600 focus-visible:ring-emerald-300' : 'bg-rose-700 hover:bg-rose-600 focus-visible:ring-rose-300'}`}>
            {isSaving ? 'Saving recorded review…' : review.status === 'approved' ? 'Save recorded approval' : 'Save recorded rejection'}
          </button>
        </div>
      </section>
    </div>
  );
}

export function KYCApprovalContent({ user, isAuthenticated, service = kycAdminService }) {
  const toast = useToast();
  const read = useAdminClosureKyc({ user, isAuthenticated, service });
  const [review, setReview] = useState(null);
  const [activeAction, setActiveAction] = useState(null);
  const [outcome, setOutcome] = useState(null);
  const mountedRef = useRef(false);
  const actionControllerRef = useRef(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      actionControllerRef.current?.abort();
      actionControllerRef.current = null;
    };
  }, []);

  const openReview = (document, status) => {
    const detail = read.detail.value;
    if (activeAction || !read.principal || !detail || document.status !== 'pending' || !document.uploadedAt || !document.downloadPath) return;
    setOutcome(null);
    setReview({ userId: detail.user.id, document, status, notes: '', acknowledgement: '' });
  };

  const downloadDocument = async (document) => {
    const detail = read.detail.value;
    if (activeAction || !read.principal || !detail || document.downloadPath === null) return;
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setActiveAction({ kind: 'download', type: document.type });
    try {
      await service.downloadDocument({
        expectedOwner: read.principal.owner,
        userId: detail.user.id,
        document,
        signal: controller.signal,
      });
    } catch (error) {
      if (mountedRef.current && !isAdminClosureKycRequestCanceled(error)) {
        toast.error(errorMessage(error, 'The private document download could not be prepared.'));
      }
    } finally {
      if (actionControllerRef.current === controller) actionControllerRef.current = null;
      if (mountedRef.current && !controller.signal.aborted) setActiveAction(null);
    }
  };

  const saveReview = async () => {
    const detail = read.detail.value;
    if (!review || activeAction || !read.principal || !detail || detail.user.id !== review.userId) return;
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setActiveAction({ kind: 'review', type: review.document.type });
    try {
      const result = await service.reviewDocument({
        expectedOwner: read.principal.owner,
        userId: review.userId,
        documentType: review.document.type,
        status: review.status,
        notes: review.notes,
        acknowledgement: review.acknowledgement,
        expectedUploadedAt: review.document.uploadedAt,
        documentName: review.document.name,
        signal: controller.signal,
      });
      if (mountedRef.current && !controller.signal.aborted) {
        setReview(null);
        setOutcome({
          userId: result.userId,
          document: result.document.name,
          status: result.document.status,
        });
        toast.success(`Recorded ${result.document.status} review saved for User #${result.userId}.`);
        read.refresh();
      }
    } catch (error) {
      if (mountedRef.current && !isAdminClosureKycRequestCanceled(error)) {
        toast.error(errorMessage(error, 'The recorded document review could not be saved.'));
      }
    } finally {
      if (actionControllerRef.current === controller) actionControllerRef.current = null;
      if (mountedRef.current && !controller.signal.aborted) setActiveAction(null);
    }
  };

  const disabled = Boolean(activeAction);
  return (
    <main className="space-y-6 text-slate-100">
      <header className="border-b border-cyan-900/50 pb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Administration · recorded review</p>
        <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="mep-heading text-3xl font-bold tracking-tight text-white">KYC document review</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Review pending document records within your tenant and hierarchy scope. Private files are downloaded through the authenticated document route.</p>
          </div>
          <button type="button" disabled={disabled || read.list.loading} onClick={read.refresh} className="inline-flex w-fit items-center gap-2 rounded-lg border border-cyan-500 px-4 py-2.5 text-sm font-semibold text-cyan-200 hover:bg-cyan-950/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
            <LoaderCircle className={`h-4 w-4 ${read.list.loading ? 'animate-spin' : ''}`} aria-hidden="true" /> Refresh records
          </button>
        </div>
      </header>
      <KycReviewNotice />
      {outcome && <section className="rounded-xl border border-emerald-500/40 bg-emerald-950/40 p-4 text-sm text-emerald-100" role="status">Confirmed saved response: User #{outcome.userId}, {outcome.document}, recorded as {formatStatus(outcome.status)}.</section>}
      <KycSubmissionList
        list={read.list}
        selectedUserId={read.selectedUserId}
        onSelect={read.selectSubmission}
        onPreviousPage={read.previousPage}
        onNextPage={read.nextPage}
        canPreviousPage={read.canPreviousPage}
        canNextPage={read.canNextPage}
        disabled={disabled}
      />
      <KycSubmissionDetail detail={read.detail} onDownload={downloadDocument} onReview={openReview} disabled={disabled} />
      <KycDocumentReviewDialog
        review={review}
        isSaving={activeAction?.kind === 'review'}
        onClose={() => { if (!activeAction) setReview(null); }}
        onChange={(change) => setReview((current) => (current ? { ...current, ...change } : current))}
        onSubmit={() => { void saveReview(); }}
      />
    </main>
  );
}

export default function KYCApproval() {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const identityKey = useMemo(
    () => `${isAuthenticated === true ? 'yes' : 'no'}:${user?.id ?? 'missing'}:${user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id ?? 'missing'}:${user?.role ?? 'missing'}`,
    [isAuthenticated, user?.id, user?.role, user?.tenant?.id, user?.tenant_id, user?.tenantId],
  );
  return <KYCApprovalContent key={identityKey} user={user} isAuthenticated={isAuthenticated} />;
}
