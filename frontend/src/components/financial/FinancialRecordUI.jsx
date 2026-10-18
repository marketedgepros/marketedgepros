import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Loader2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import {
  canRequestFinancialPage,
  FINANCIAL_RECORD_PAGE_LIMIT,
} from "../../services/financialRecordViewService.js";

export const financialPanel =
  "mep-panel min-w-0 rounded-2xl border";
export const financialButton =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none";
export const financialDisplay = (value) =>
  value === null || value === undefined || value === ""
    ? "Unavailable"
    : String(value);
export const financialDate = (value) =>
  typeof value === "string" ? value.slice(0, 10) : "Unavailable";

export function FinancialRecordBoundary() {
  return (
    <section
      className="flex gap-3 rounded-2xl border border-amber-300/25 bg-amber-950/20 p-4 text-sm leading-6 text-amber-100"
      aria-label="Financial record source status"
    >
      <ShieldAlert
        className="mt-0.5 h-5 w-5 shrink-0 text-amber-300"
        aria-hidden="true"
      />
      <p>
        <strong>Read-only unverified legacy records.</strong> Currency is
        unavailable. These records do not establish a balance available for
        trading, payment, payout, or withdrawal eligibility.
      </p>
    </section>
  );
}

export function FinancialReadState({
  loading,
  error,
  onRetry,
  recordLabel = "financial records",
}) {
  if (loading) {
    return (
      <section
        role="status"
        aria-live="polite"
        aria-busy="true"
        className={`${financialPanel} flex min-h-56 items-center justify-center p-6`}
      >
        <div className="text-center">
          <Loader2
            className="mx-auto h-9 w-9 animate-spin text-cyan-200 motion-reduce:animate-none"
            aria-hidden="true"
          />
          <p className="mt-4 text-sm text-slate-300">Loading {recordLabel}…</p>
        </div>
      </section>
    );
  }
  if (error) {
    return (
      <section
        role="alert"
        aria-live="assertive"
        className="rounded-2xl border border-rose-300/30 bg-rose-950/30 p-5 text-rose-50"
      >
        <div className="flex items-start gap-3">
          <CircleAlert
            className="mt-0.5 h-5 w-5 shrink-0 text-rose-200"
            aria-hidden="true"
          />
          <div className="min-w-0">
            <h2 className="mep-heading font-semibold">
              Financial records could not be verified
            </h2>
            <p className="mt-1 break-words text-sm leading-6 text-rose-100/85">
              {typeof error === "string"
                ? error
                : "The service is unavailable or its response could not be validated. No financial value has been inferred."}
            </p>
            <button
              type="button"
              onClick={onRetry}
              className={`${financialButton} mt-4 border-rose-200/40 bg-rose-100/10 text-rose-50 hover:bg-rose-100/20`}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Retry records
            </button>
          </div>
        </div>
      </section>
    );
  }
  return null;
}

export function WalletMissingState() {
  return (
    <section
      role="status"
      aria-live="polite"
      className="rounded-2xl border border-amber-300/30 bg-amber-950/25 p-6 text-amber-50"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle
          className="mt-0.5 h-5 w-5 shrink-0 text-amber-200"
          aria-hidden="true"
        />
        <div className="min-w-0">
          <h2 className="mep-heading font-semibold">No legacy wallet record was found</h2>
          <p className="mt-1 text-sm leading-6 text-amber-100/85">
            The service returned the canonical missing-wallet response. This is
            not a zero balance, an empty transaction history, or a financial
            eligibility decision.
          </p>
        </div>
      </div>
    </section>
  );
}

export function FinancialExactAmount({
  value,
  align = "left",
  label = "Recorded amount",
}) {
  return (
    <div className={`min-w-[8rem] ${align === "right" ? "text-right" : ""}`}>
      <p
        aria-label={label}
        className="break-all font-mono text-sm font-semibold tabular-nums text-slate-100"
      >
        {financialDisplay(value)}
      </p>
      <p className="mt-1 text-xs text-slate-400">Currency unavailable</p>
    </div>
  );
}

export function FinancialStatusPill({ status }) {
  const tone =
    {
      pending: "border-amber-300/25 bg-amber-300/10 text-amber-100",
      approved: "border-cyan-300/25 bg-cyan-300/10 text-cyan-100",
      processing: "border-violet-300/25 bg-violet-300/10 text-violet-100",
      completed: "border-emerald-300/25 bg-emerald-300/10 text-emerald-100",
      rejected: "border-rose-300/25 bg-rose-300/10 text-rose-100",
    }[status] || "border-white/10 bg-white/5 text-slate-300";
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${tone}`}
    >
      {financialDisplay(status)}
    </span>
  );
}

export function FinancialPagination({
  pagination,
  onPage,
  disabled = false,
  label = "Financial records pagination",
}) {
  if (!pagination) return null;
  const nextPage = pagination.page + 1;
  const serverLast = Math.min(pagination.pages, FINANCIAL_RECORD_PAGE_LIMIT);
  const beyondTotal =
    pagination.page > pagination.pages && pagination.pages > 0;
  const previousDisabled =
    disabled ||
    pagination.page <= 1 ||
    !canRequestFinancialPage(pagination.page - 1, pagination.per_page);
  const nextDisabled =
    disabled ||
    pagination.page >= pagination.pages ||
    !canRequestFinancialPage(nextPage, pagination.per_page);
  return (
    <nav
      aria-label={label}
      className={`${financialPanel} flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between`}
    >
      <div className="min-w-0 text-sm text-slate-300">
        <p>
          Page {pagination.page} · {pagination.total} server records ·{" "}
          {pagination.pages} server pages
        </p>
        {pagination.pages > FINANCIAL_RECORD_PAGE_LIMIT && (
          <p className="mt-1 text-xs text-amber-100">
            Browsing is limited to {FINANCIAL_RECORD_PAGE_LIMIT} pages.
          </p>
        )}
        {beyondTotal && (
          <p className="mt-1 text-xs text-amber-100">
            This requested page is beyond the server total and is validly empty.
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={financialButton}
          disabled={previousDisabled}
          onClick={() => onPage(pagination.page - 1)}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          Previous page
        </button>
        <button
          type="button"
          className={financialButton}
          disabled={nextDisabled}
          onClick={() => onPage(nextPage)}
        >
          Next page
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
        {pagination.page !== 1 && (
          <button
            type="button"
            className={financialButton}
            disabled={
              disabled || !canRequestFinancialPage(1, pagination.per_page)
            }
            onClick={() => onPage(1)}
          >
            First page
          </button>
        )}
        {beyondTotal &&
          serverLast >= 1 &&
          canRequestFinancialPage(serverLast, pagination.per_page) && (
            <button
              type="button"
              className={financialButton}
              disabled={disabled}
              onClick={() => onPage(serverLast)}
            >
              Last available page
            </button>
          )}
      </div>
    </nav>
  );
}
