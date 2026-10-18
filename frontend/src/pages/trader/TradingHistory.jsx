import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, RefreshCw, Search } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import useRecordedTradingRead from '../../hooks/useRecordedTradingRead';
import {
  buildRecordedHistoryParams, createRecordedTradingViewService, downloadRecordedHistoryPage,
  recordedIdentityKey, recordedPrincipal,
} from '../../services/recordedTradingViewService.js';
import {
  RecordedBoundary, RecordedMetric, RecordedPagination, RecordedReadState,
  recordedDisplay, tradingButton, tradingPanel,
} from '../../components/trading/RecordedTradingUI';

const service = createRecordedTradingViewService();
const defaults = { symbol: '', type: 'all', period: 'all' };
const inputClass = 'mt-2 w-full min-w-0 rounded-xl border border-white/15 bg-slate-950/60 px-3 py-2.5 text-sm text-white focus:border-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300/25';

function HistoryContent({ principal }) {
  const [draft, setDraft] = useState(defaults);
  const [filters, setFilters] = useState(defaults);
  const [page, setPage] = useState(1);
  const [filterError, setFilterError] = useState(null);
  const [exportError, setExportError] = useState(null);
  const scopeKey = recordedIdentityKey(principal);
  const params = buildRecordedHistoryParams({ ...filters, page });
  const key = JSON.stringify([scopeKey, params]);
  const load = useCallback((signal) => service.history({ ...params, expectedOwner: principal, signal }), [key]);
  const { value: view, loading, error, retry } = useRecordedTradingRead(key, load);
  const dirty = draft.symbol !== filters.symbol || draft.type !== filters.type || draft.period !== filters.period;
  const apply = (event) => {
    event.preventDefault();
    try {
      const normalized = buildRecordedHistoryParams(draft);
      const applied = { symbol: normalized.symbol, type: normalized.type, period: normalized.period };
      setDraft(applied); setFilters(applied); setPage(1); setFilterError(null); setExportError(null);
    } catch (requestError) {
      setFilterError(requestError.message);
    }
  };
  const exportPage = () => {
    if (!view || loading || error || dirty || !view.trades.length
      || recordedIdentityKey(recordedPrincipal(useAuthStore.getState().user)) !== scopeKey) return;
    try { downloadRecordedHistoryPage(view); setExportError(null); }
    catch { setExportError('The recorded page could not be exported. Please try again.'); }
  };
  return <div className="mx-auto max-w-7xl min-w-0 space-y-6 p-4 text-slate-100 sm:p-6 lg:p-8">
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Account records</p>
        <h1 className="mep-heading mt-2 text-3xl font-semibold tracking-tight text-white">Trading history</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">Review stored trade records, filter them on the server and export the current page. Recorded figures are not live trading evidence.</p></div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={tradingButton} onClick={retry} disabled={loading}><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh records</button>
        <button type="button" className={tradingButton} onClick={exportPage} disabled={loading || error || dirty || !view?.trades.length}>
          <Download className="h-4 w-4" aria-hidden="true" />Export current page</button>
      </div>
    </header>
    <RecordedBoundary />
    <form onSubmit={apply} className={tradingPanel} aria-label="Recorded trade filters">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="min-w-0 text-sm text-slate-300">Symbol
          <input className={inputClass} value={draft.symbol} maxLength={20} placeholder="For example EURUSD" onChange={(event) => setDraft({ ...draft, symbol: event.target.value })} />
        </label>
        <label className="text-sm text-slate-300">Recorded side
          <select className={inputClass} value={draft.type} onChange={(event) => setDraft({ ...draft, type: event.target.value })}>
            <option value="all">All recorded sides</option><option value="buy">Buy</option><option value="sell">Sell</option>
          </select>
        </label>
        <label className="text-sm text-slate-300">Close-time window
          <select className={inputClass} value={draft.period} onChange={(event) => setDraft({ ...draft, period: event.target.value })}>
            <option value="all">All recorded times</option><option value="today">Today — UTC cutoff</option>
            <option value="week">Last 7 days</option><option value="month">Last 30 days</option>
          </select>
        </label>
        <div className="flex items-end"><button type="submit" className={`${tradingButton} w-full`}><Search className="h-4 w-4" aria-hidden="true" />Apply filters</button></div>
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-400">The time windows use server UTC cutoffs against stored close times; source timezone is not verified. Filters apply when submitted. Export is disabled until changes are applied.</p>
      {dirty && <p className="mt-2 text-sm text-cyan-200" role="status">Filter changes have not been applied.</p>}
      {filterError && <p className="mt-3 text-sm text-red-200" role="alert">{filterError}</p>}
    </form>
    {exportError && <p className="rounded-xl border border-red-400/30 p-4 text-sm text-red-200" role="alert">{exportError}</p>}
    <RecordedReadState loading={loading} error={error} retry={retry} empty={view?.trades.length === 0}
      emptyTitle={view?.pagination.total > 0 ? 'No records on this page' : 'No recorded trades for these filters'} />
    {view && !loading && !error && <>
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <RecordedMetric label="Recorded rows in this filter" value={view.statistics.total_trades} />
        <RecordedMetric label="Rows with positive stored P/L" value={view.statistics.winning_trades} />
        <RecordedMetric label="Rows with negative stored P/L" value={view.statistics.losing_trades} />
        <RecordedMetric label="Stored P/L sum" value={view.statistics.total_profit} hint="Currency not recorded; incomplete P/L remains unavailable." />
      </dl>
      {view.trades.length > 0 && <section className="mep-panel min-w-0 overflow-hidden rounded-2xl border" aria-label="Recorded trades">
        <div className="flex flex-col gap-2 border-b border-white/10 p-5 sm:flex-row sm:justify-between">
          <h2 className="mep-heading font-semibold text-white">Current recorded page</h2><p className="text-xs text-slate-300">{view.trades.length} rows · currency unspecified · unverified legacy</p>
        </div>
        <div className="max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-cyan-300" role="region" aria-label="Scrollable recorded trade table" tabIndex={0}>
          <table className="w-full min-w-[900px] text-left text-sm">
            <caption className="sr-only">Stored trade values only. Open or incomplete trades can have unavailable close fields.</caption>
            <thead className="bg-slate-950/40 text-xs text-slate-300"><tr>
              {['Symbol / ID', 'Side / status', 'Volume', 'Open / close price', 'Stored P/L', 'Commission / swap', 'Recorded open / close time'].map((label) => <th key={label} scope="col" className="px-4 py-3 font-semibold">{label}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-white/10">{view.trades.map((trade) => <tr key={trade.id} className="hover:bg-white/[0.025]">
              <td className="px-4 py-4"><span className="font-semibold text-white">{trade.symbol}</span><span className="mt-1 block text-xs text-slate-400">Trade {trade.id} · Challenge {trade.challenge_id}</span></td>
              <td className="px-4 py-4"><span>{recordedDisplay(trade.trade_type)}</span><span className="mt-1 block text-xs text-slate-400">{recordedDisplay(trade.status)}</span></td>
              <td className="px-4 py-4 font-mono">{recordedDisplay(trade.volume)}</td>
              <td className="px-4 py-4 font-mono"><span>{recordedDisplay(trade.open_price)}</span><span className="mt-1 block text-slate-400">{recordedDisplay(trade.close_price)}</span></td>
              <td className="px-4 py-4 font-mono">{recordedDisplay(trade.profit)}</td>
              <td className="px-4 py-4 font-mono"><span>{recordedDisplay(trade.commission)}</span><span className="mt-1 block text-slate-400">{recordedDisplay(trade.swap)}</span></td>
              <td className="px-4 py-4 text-xs"><span>{recordedDisplay(trade.open_time)}</span><span className="mt-1 block text-slate-400">{recordedDisplay(trade.close_time)}</span></td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>}
      <RecordedPagination pagination={view.pagination} onPage={setPage} disabled={loading || dirty} />
    </>}
    <footer className="flex flex-wrap gap-4 text-sm"><Link className="text-cyan-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-cyan-300" to="/challenges">View recorded challenges</Link>
      <Link className="text-cyan-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-cyan-300" to="/support/my-tickets">My support tickets</Link></footer>
  </div>;
}
export default function TradingHistory() {
  const user = useAuthStore((state) => state.user);
  const principal = recordedPrincipal(user);
  if (!principal || principal.role !== 'trader' || principal.tenant_id === null) return <section className={`${tradingPanel} m-4`} role="status">
    <h1 className="mep-heading text-xl font-semibold text-white">Trading history unavailable</h1><p className="mt-2 text-sm text-slate-300">A signed-in trader account with a recorded brand is required.</p>
  </section>;
  return <HistoryContent key={recordedIdentityKey(principal)} principal={principal} />;
}
