import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { ADMIN_PAYMENT_PAGE_LIMIT, ADMIN_PAYMENT_OFFSET_LIMIT } from "../../services/adminPaymentRecordViewService.js";

export const adminPaymentPanel = "mep-panel min-w-0 rounded-2xl border p-4 sm:p-6";
export const adminPaymentButton = "inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-400/40 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition-colors hover:bg-cyan-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-45";
const knownPurpose = {
  challenge_purchase: "Challenge purchase",
  withdrawal: "Withdrawal",
  refund: "Refund",
};

export const adminPaymentDisplay = (value, unavailable = "Unknown") => (
  value === null || value === undefined || value === "" ? unavailable : String(value)
);
export const adminPaymentPurpose = (value) => (
  value === null ? "Unknown" : (knownPurpose[value] || "Unknown")
);
export const adminApprovalType = (value) => (
  ({ cash: "Cash", free: "Free" })[value] || "Unknown"
);
export const adminPaymentCalendar = (value) => adminPaymentDisplay(value);

export function AdminPaymentBoundary() {
  return (
    <div className="flex gap-3 rounded-2xl border border-amber-300/25 bg-amber-950/20 p-4 text-sm leading-6 text-amber-100">
      <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
      <p>
        <strong>Recorded legacy data only.</strong> These records are unverified and settlement is disabled.
        Amounts, currency codes, and request references are displayed only as returned by the server; they
        do not establish payment completion, funds availability, or approval authority.
      </p>
    </div>
  );
}

export function AdminPaymentReadState({ loading, error, onRetry, empty, emptyTitle, emptyMessage }) {
  if (loading) {
    return (
      <div className={`${adminPaymentPanel} flex min-h-48 items-center justify-center`} role="status" aria-busy="true">
        <Loader2 className="mr-3 h-5 w-5 animate-spin motion-reduce:animate-none text-cyan-300" aria-hidden="true" />
        <p className="text-slate-200">Loading recorded legacy data…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border border-red-300/30 bg-red-950/25 p-5 text-red-100" role="alert">
        <h2 className="mep-heading flex items-center gap-2 font-semibold">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          Recorded data could not be loaded
        </h2>
        <p className="mt-2 text-sm leading-6">
          The service is unavailable or its response could not be validated. No payment value, settlement
          state, or empty result has been assumed.
        </p>
        <button type="button" onClick={onRetry} className={`${adminPaymentButton} mt-4`}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Refresh records
        </button>
      </div>
    );
  }
  if (empty) {
    return (
      <section className={`${adminPaymentPanel} py-10 text-center`} aria-labelledby="admin-payment-empty-title">
        <h2 id="admin-payment-empty-title" className="mep-heading text-lg font-semibold text-white">{emptyTitle}</h2>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-slate-300">
          {emptyMessage || "The server returned no records for this page. This is not a financial or settlement conclusion."}
        </p>
      </section>
    );
  }
  return null;
}

export function AdminPaymentExactAmount({ amount, currency, showCurrency = true }) {
  return (
    <span className="font-mono text-sm text-slate-100">
      {adminPaymentDisplay(amount)}
      {showCurrency && <span className="ml-1 text-slate-400">{adminPaymentDisplay(currency, "Currency unavailable")}</span>}
    </span>
  );
}

function RecordCell({ children, className = "" }) {
  return <td className={`max-w-56 break-words px-4 py-3 align-top text-sm text-slate-200 sm:px-5 ${className}`}>{children}</td>;
}

function CalendarCell({ value }) {
  if (value === null) return <span className="text-slate-400">Unknown</span>;
  return <time dateTime={value} className="break-all text-slate-300">{adminPaymentCalendar(value)}</time>;
}

function StatusPill({ children, pending = false }) {
  return (
    <span className={`inline-flex max-w-full break-words rounded-full border px-2.5 py-1 text-xs font-semibold ${
      pending
        ? "border-amber-300/30 bg-amber-300/10 text-amber-100"
        : "border-cyan-300/30 bg-cyan-300/10 text-cyan-100"
    }`}>
      {children}
    </span>
  );
}

export function PaymentRecordsTable({ payments }) {
  return (
    <div className={`${adminPaymentPanel} p-0`}>
      <div className="max-w-full overflow-x-auto" tabIndex="0" aria-label="Recorded payment table; scroll horizontally for all columns">
        <table className="min-w-[940px] w-full border-collapse text-left">
          <caption className="sr-only">Recorded legacy payment records</caption>
          <thead className="border-b border-white/10 bg-slate-950/35 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Record ID</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">User ID</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Recorded amount</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Purpose</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Status</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Method</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {payments.map((payment) => (
              <tr key={payment.id} className="transition-colors hover:bg-cyan-300/[0.035]">
                <RecordCell className="font-mono text-cyan-100">{payment.id}</RecordCell>
                <RecordCell className="font-mono">{payment.user_id}</RecordCell>
                <RecordCell><AdminPaymentExactAmount amount={payment.amount} currency={payment.currency} /></RecordCell>
                <RecordCell><StatusPill>{adminPaymentPurpose(payment.payment_type)}</StatusPill></RecordCell>
                <RecordCell><StatusPill pending={payment.status === "pending"}>{adminPaymentDisplay(payment.status)}</StatusPill></RecordCell>
                <RecordCell>{adminPaymentDisplay(payment.payment_method)}</RecordCell>
                <RecordCell><CalendarCell value={payment.created_at} /></RecordCell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ApprovalRequestsTable({ requests }) {
  return (
    <div className={`${adminPaymentPanel} p-0`}>
      <div className="max-w-full overflow-x-auto" tabIndex="0" aria-label="Pending legacy approval-request table; scroll horizontally for all columns">
        <table className="min-w-[1120px] w-full border-collapse text-left">
          <caption className="sr-only">Pending legacy approval requests, read only</caption>
          <thead className="border-b border-white/10 bg-slate-950/35 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Request ID</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Requested by</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Requested for</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Challenge ID</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Payment ID</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Recorded amount</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Request type</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Status</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Created</th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">Reviewed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {requests.map((request) => (
              <tr key={request.id} className="transition-colors hover:bg-cyan-300/[0.035]">
                <RecordCell className="font-mono text-cyan-100">{request.id}</RecordCell>
                <RecordCell className="font-mono">{request.requested_by}</RecordCell>
                <RecordCell className="font-mono">{request.requested_for}</RecordCell>
                <RecordCell className="font-mono">{adminPaymentDisplay(request.challenge_id)}</RecordCell>
                <RecordCell className="font-mono">{adminPaymentDisplay(request.payment_id)}</RecordCell>
                <RecordCell><AdminPaymentExactAmount amount={request.amount} showCurrency={false} /></RecordCell>
                <RecordCell><StatusPill>{adminApprovalType(request.payment_type)}</StatusPill></RecordCell>
                <RecordCell><StatusPill pending>{request.status}</StatusPill></RecordCell>
                <RecordCell><CalendarCell value={request.created_at} /></RecordCell>
                <RecordCell><CalendarCell value={request.reviewed_at} /></RecordCell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AdminPaymentPagination({ pagination, onPage, disabled = false }) {
  if (!pagination) return null;
  if (pagination.pages === 0) {
    return <p className="px-1 text-sm text-slate-400" role="status">No recorded payment pages are available for this result.</p>;
  }
  const browseLimit = Math.min(ADMIN_PAYMENT_PAGE_LIMIT, Math.floor(ADMIN_PAYMENT_OFFSET_LIMIT / pagination.per_page) + 1);
  const maxPage = Math.min(pagination.pages, browseLimit);
  return (
    <nav aria-label="Recorded payment pagination" className={`${adminPaymentPanel} flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between`}>
      <p className="text-sm leading-6 text-slate-300">
        Page {pagination.page} of {pagination.pages} · {pagination.total} recorded {pagination.total === 1 ? "record" : "records"}
        {pagination.pages > browseLimit && <span className="block text-xs text-amber-200">Browsing is limited to {browseLimit} pages.</span>}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={adminPaymentButton} disabled={disabled || pagination.page <= 1} onClick={() => onPage(pagination.page - 1)}>
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          Previous page
        </button>
        <button type="button" className={adminPaymentButton} disabled={disabled || pagination.page >= maxPage} onClick={() => onPage(pagination.page + 1)}>
          Next page
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
        {pagination.page > 1 && (
          <button type="button" className={adminPaymentButton} disabled={disabled} onClick={() => onPage(1)}>
            First page
          </button>
        )}
      </div>
    </nav>
  );
}

export function ApprovalAccessRestricted() {
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Read-only record view</p>
        <h1 className="mep-heading mt-2 text-2xl font-bold text-white sm:text-3xl">Pending legacy payment requests</h1>
      </div>
      <div className="flex gap-3 rounded-2xl border border-amber-300/25 bg-amber-950/20 p-5 text-sm leading-6 text-amber-100" role="alert">
        <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
        <p>
          Pending approval requests are restricted to the platform root scope. This account cannot retrieve
          them, and no request was sent.
        </p>
      </div>
    </div>
  );
}
