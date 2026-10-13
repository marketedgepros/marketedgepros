import { AlertTriangle, ChevronLeft, ChevronRight, Download, RefreshCw, ShieldAlert } from 'lucide-react';
import { Link } from 'react-router-dom';
import { AFFILIATE_RECORD_PAGE_LIMIT } from '../../services/affiliateRecordViewService.js';

export const affiliateRecordPanel = 'mep-panel min-w-0 rounded-2xl border';
export const affiliateRecordButton = 'inline-flex items-center justify-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none';

export const affiliateRecordDisplay = (value) => value === null || value === undefined || value === '' ? 'Unavailable' : String(value);
export const affiliateRecordDate = (value) => typeof value === 'string' ? value.slice(0, 10) : 'Unavailable';

export function AffiliateRecordNavigation() {
  const links = [
    ['/affiliate/dashboard', 'Dashboard'],
    ['/affiliate/traders', 'Referrals'],
    ['/affiliate/commissions', 'Commissions'],
    ['/affiliate/reports', 'Reports'],
    ['/affiliate/payout', 'Payout status'],
    ['/support/create-ticket', 'Support'],
  ];
  return (
    <nav aria-label="Affiliate account navigation" className="flex flex-wrap gap-2">
      {links.map(([to, label]) => (
        <Link key={to} to={to} className="rounded-full border border-white/10 bg-slate-900/60 px-3 py-1.5 text-sm text-slate-200 transition hover:border-cyan-300/40 hover:text-cyan-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 motion-reduce:transition-none">
          {label}
        </Link>
      ))}
    </nav>
  );
}

export function AffiliateRecordHeader({ eyebrow, title, summary, onRefresh, refreshing = false, action = null }) {
  return (
    <>
      <section className="border-b border-cyan-300/10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-500/10 via-slate-950 to-slate-950">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">{eyebrow}</p>
          <div className="mt-3 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <h1 className="mep-heading text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">{summary}</p>
            </div>
            <AffiliateRecordNavigation />
          </div>
        </div>
      </section>
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 pt-5 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p role="status" className="flex min-w-0 items-start gap-2 text-sm leading-6 text-amber-100">
          <AlertTriangle className="mt-1 h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" />
          <span><strong>Unverified legacy records.</strong> Status labels do not prove payment, identity, payout eligibility, or account ownership.</span>
        </p>
        <div className="flex shrink-0 flex-wrap gap-2">
          {action}
          <button type="button" onClick={onRefresh} disabled={refreshing} aria-label="Refresh affiliate records" className={affiliateRecordButton}>
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            {refreshing ? 'Refreshing records' : 'Refresh records'}
          </button>
        </div>
      </div>
    </>
  );
}

export function AffiliateRecordBoundary() {
  return (
    <section className="flex gap-3 rounded-2xl border border-amber-300/25 bg-amber-950/20 p-4 text-sm leading-6 text-amber-100" aria-label="Affiliate record data status">
      <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
      <p><strong>Read-only legacy source.</strong> Currency is unavailable and no payout or balance may be inferred from these records. Displayed decimals remain exact API strings.</p>
    </section>
  );
}

export function AffiliateRecordReadState({ loading, error, onRetry }) {
  if (loading) {
    return (
      <section role="status" aria-live="polite" aria-busy="true" className={`${affiliateRecordPanel} flex min-h-56 items-center justify-center p-6`}>
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-cyan-300/20 border-t-cyan-300 motion-reduce:animate-none" aria-hidden="true" />
          <p className="mt-4 text-sm text-slate-300">Loading affiliate records…</p>
        </div>
      </section>
    );
  }
  if (error) {
    return (
      <section role="alert" aria-live="assertive" className="rounded-2xl border border-rose-300/30 bg-rose-950/30 p-5 text-rose-50">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-rose-200" aria-hidden="true" />
          <div className="min-w-0">
            <h2 className="mep-heading font-semibold">Affiliate records could not be verified</h2>
            <p className="mt-1 break-words text-sm leading-6 text-rose-100/85">{typeof error === 'string' ? error : 'No records are shown until a complete response matches your signed-in affiliate account.'}</p>
            <button type="button" onClick={onRetry} className={`${affiliateRecordButton} mt-4 border-rose-200/40 bg-rose-100/10 text-rose-50 hover:bg-rose-100/20`}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" />Retry records
            </button>
          </div>
        </div>
      </section>
    );
  }
  return null;
}

export function AffiliateExactAmount({ value, align = 'left' }) {
  return (
    <div className={`min-w-[8rem] ${align === 'right' ? 'text-right' : ''}`}>
      <p className="break-all font-mono text-sm font-semibold tabular-nums text-slate-100">{affiliateRecordDisplay(value)}</p>
      <p className="mt-1 text-xs text-slate-400">Currency unavailable</p>
    </div>
  );
}

export function AffiliateStatusPill({ status }) {
  const tone = {
    pending: 'border-amber-300/25 bg-amber-300/10 text-amber-100',
    converted: 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100',
    approved: 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100',
    paid: 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100',
    cancelled: 'border-rose-300/25 bg-rose-300/10 text-rose-100',
  }[status] || 'border-white/10 bg-white/5 text-slate-300';
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${tone}`}>{affiliateRecordDisplay(status)}</span>;
}

export function AffiliateRecordPagination({ pagination, onPage, disabled = false, loadingPage = null }) {
  if (!pagination) return null;
  if (pagination.pages === 0) {
    return <p className="px-1 text-sm text-slate-400" role="status">No server pages are available for this affiliate result.</p>;
  }
  const serverLast = Math.min(pagination.pages, AFFILIATE_RECORD_PAGE_LIMIT);
  const beyondTotal = pagination.page > pagination.pages && pagination.pages > 0;
  const previousDisabled = disabled || pagination.page <= 1;
  const nextDisabled = disabled || pagination.page >= pagination.pages || pagination.page >= AFFILIATE_RECORD_PAGE_LIMIT;
  return (
    <nav aria-label="Affiliate records pagination" aria-busy={loadingPage !== null ? 'true' : undefined} className={`${affiliateRecordPanel} flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between`}>
      <div className="min-w-0 text-sm text-slate-300">
        {loadingPage !== null
          ? <p className="text-cyan-100" role="status">Loading requested page {loadingPage}…</p>
          : <p>Page {pagination.page} · {pagination.total} server records · {pagination.pages} server pages</p>}
        {pagination.pages > AFFILIATE_RECORD_PAGE_LIMIT && <p className="mt-1 text-xs text-amber-100">Browsing is limited to {AFFILIATE_RECORD_PAGE_LIMIT} pages.</p>}
        {beyondTotal && <p className="mt-1 text-xs text-amber-100">This requested page is beyond the server total and is validly empty. Choose the last available page or first page.</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={affiliateRecordButton} disabled={previousDisabled} onClick={() => onPage(pagination.page - 1)}>
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />Previous page
        </button>
        <button type="button" className={affiliateRecordButton} disabled={nextDisabled} onClick={() => onPage(pagination.page + 1)}>
          Next page<ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
        {pagination.page !== 1 && <button type="button" className={affiliateRecordButton} disabled={disabled} onClick={() => onPage(1)}>First page</button>}
        {beyondTotal && serverLast >= 1 && <button type="button" className={affiliateRecordButton} disabled={disabled} onClick={() => onPage(serverLast)}>Last available page</button>}
      </div>
    </nav>
  );
}

export function AffiliateExportButton({ disabled, onClick }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className={affiliateRecordButton} aria-label="Export current verified commissions page">
      <Download className="h-4 w-4" aria-hidden="true" />Export current page
    </button>
  );
}
