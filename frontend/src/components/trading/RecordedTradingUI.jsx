import { CircleAlert, ChevronLeft, ChevronRight, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';
import { PAGE_LIMIT } from '../../services/recordedTradingViewService.js';

export const tradingButton = 'inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-400/40 px-4 py-2.5 text-sm font-semibold text-cyan-200 transition-colors hover:bg-cyan-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-40';
export const tradingPanel = 'mep-panel min-w-0 rounded-2xl border p-5 sm:p-6';
export const recordedDisplay = (value) => value === null || value === undefined || value === '' ? 'Unavailable' : String(value);

export function RecordedBoundary({ scaling = false }) {
  return <div className="flex gap-3 rounded-2xl border border-amber-400/25 bg-amber-950/20 p-4 text-sm text-amber-100">
    <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
    <p><strong>Recorded data only.</strong> These legacy records are not verified by a trading provider and do not establish payment, funding or withdrawal eligibility.
      {scaling ? ' Account scaling is unavailable until approved rules and verified trading evidence are connected.' : ' Currency and source timestamps are not independently verified.'}</p>
  </div>;
}
export function RecordedReadState({ loading, error, retry, empty, emptyTitle = 'No recorded data', emptyMessage }) {
  if (loading) return <div className={`${tradingPanel} flex min-h-48 items-center justify-center`} role="status" aria-busy="true">
    <Loader2 className="mr-3 h-5 w-5 animate-spin motion-reduce:animate-none text-cyan-300" aria-hidden="true" />
    <p className="text-slate-200">Loading recorded data…</p>
  </div>;
  if (error) return <div className="rounded-2xl border border-red-400/30 bg-red-950/20 p-5 text-red-100" role="alert">
    <h2 className="mep-heading flex items-center gap-2 font-semibold"><CircleAlert className="h-5 w-5" aria-hidden="true" />Recorded data could not be loaded</h2>
    <p className="mt-2 text-sm">The service is unavailable or its response could not be validated. No zero balance or empty result has been assumed.</p>
    <button type="button" onClick={retry} className={`${tradingButton} mt-4`}><RefreshCw className="h-4 w-4" aria-hidden="true" />Retry recorded data</button>
  </div>;
  if (empty) return <section className={`${tradingPanel} py-10 text-center`}>
    <h2 className="mep-heading text-lg font-semibold text-white">{emptyTitle}</h2>
    <p className="mx-auto mt-3 max-w-xl text-sm text-slate-300">{emptyMessage || 'The service returned no records for this view. This is not confirmation of provider activity or financial eligibility.'}</p>
  </section>;
  return null;
}
export function RecordedPagination({ pagination, onPage, disabled = false }) {
  if (!pagination) return null;
  return <nav aria-label="Recorded data pagination" className={`${tradingPanel} flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between`}>
    <div className="text-sm text-slate-300"><p>Page {pagination.page} · {pagination.pages} recorded pages · {pagination.total} records</p>
      {pagination.pages > PAGE_LIMIT && <p className="mt-1 text-xs">Browsing is limited to {PAGE_LIMIT} pages.</p>}</div>
    <div className="flex flex-wrap gap-2">
      <button type="button" className={tradingButton} disabled={disabled || pagination.page <= 1} onClick={() => onPage(pagination.page - 1)}>
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />Previous page</button>
      <button type="button" className={tradingButton} disabled={disabled || pagination.page >= pagination.pages || pagination.page >= PAGE_LIMIT} onClick={() => onPage(pagination.page + 1)}>
        Next page<ChevronRight className="h-4 w-4" aria-hidden="true" /></button>
      {pagination.page > 1 && <button type="button" className={tradingButton} disabled={disabled} onClick={() => onPage(1)}>First page</button>}
    </div>
  </nav>;
}
export function RecordedMetric({ label, value, hint }) {
  return <div className={tradingPanel}><dt className="text-sm text-slate-400">{label}</dt>
    <dd className="mt-2 break-all font-mono text-xl font-semibold text-white">{recordedDisplay(value)}</dd>
    {hint && <p className="mt-2 text-xs text-slate-400">{hint}</p>}</div>;
}
