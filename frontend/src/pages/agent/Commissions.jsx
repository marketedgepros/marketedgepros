import { useCallback, useEffect, useRef, useState } from 'react';
import useAuthStore from '../../store/authStore';
import {
  AFFILIATE_COMMISSION_STATUSES,
  AFFILIATE_RECORD_PAGE_SIZE,
  affiliateRecordError,
  downloadAffiliateCommissionsPage,
} from '../../services/affiliateRecordViewService.js';
import { useAffiliateRecordRead } from '../../hooks/useAffiliateAccountRead.js';
import {
  AffiliateExactAmount,
  AffiliateExportButton,
  AffiliateRecordBoundary,
  AffiliateRecordHeader,
  AffiliateRecordPagination,
  AffiliateRecordReadState,
  AffiliateStatusPill,
  affiliateRecordDate,
  affiliateRecordPanel,
} from '../../components/affiliate/AffiliateRecordUI.jsx';

const tenantSelector = (state) => state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null;

export function AffiliateCommissionsView({ view, pagination, loading, error, exportError, onRefresh, onPage, onStatus, onExport, requestedPage, selectedStatus }) {
  const commissions = view?.commissions ?? [];
  const status = view?.filters?.status ?? selectedStatus;
  const canExport = Boolean(view && !loading && !error);
  return (
    <div className="mep-screen min-h-screen text-white">
      <AffiliateRecordHeader
        eyebrow="Affiliate records"
        title="Commission activity"
        summary="A server-filtered, read-only page of legacy commission records for the signed-in affiliate account."
        onRefresh={onRefresh}
        refreshing={loading}
        action={<AffiliateExportButton disabled={!canExport} onClick={onExport} />}
      />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <AffiliateRecordBoundary />
        {exportError && (
          <section role="alert" className="mt-5 rounded-2xl border border-rose-300/30 bg-rose-950/30 p-4 text-sm text-rose-50">
            <p className="font-semibold">Current-page export could not be created</p>
            <p className="mt-1 break-words text-rose-100/85">{exportError}</p>
          </section>
        )}
        <section className={`${affiliateRecordPanel} mt-6 p-4 sm:p-5`} aria-labelledby="commission-filter-heading">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 id="commission-filter-heading" className="mep-heading font-semibold text-white">Server status filter</h2>
              <p className="mt-1 text-sm text-slate-400">Changing the status starts again at page one. Export contains only the current verified page.</p>
            </div>
            <label className="flex shrink-0 items-center gap-3 text-sm text-slate-200" htmlFor="commission-status">
              Status
              <select id="commission-status" value={status ?? 'all'} disabled={loading} onChange={(event) => onStatus(event.target.value)} className="rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 disabled:cursor-not-allowed disabled:opacity-60">
                <option value="all">All statuses</option>
                {AFFILIATE_COMMISSION_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
          </div>
        </section>

        <div className="mt-6"><AffiliateRecordReadState loading={loading} error={error ? affiliateRecordError(error) : null} onRetry={onRefresh} /></div>

        {!loading && !error && view && (
          <>
            <section className={`${affiliateRecordPanel} mt-6 overflow-hidden`} aria-labelledby="commission-records-heading">
              <div className="border-b border-white/10 px-5 py-4 sm:px-6">
                <h2 id="commission-records-heading" className="mep-heading text-xl font-semibold">Commission records</h2>
                <p className="mt-1 text-sm text-slate-400">Exact API strings are displayed without a currency, total, or payment inference.</p>
              </div>
              <div role="region" aria-label="Commission records table" tabIndex="0" className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-200">
                <table className="w-full min-w-[820px] text-left text-sm">
                  <caption className="sr-only">Commission records for the signed-in affiliate account</caption>
                  <thead className="bg-slate-950/50 text-xs uppercase tracking-[0.14em] text-slate-400">
                    <tr>
                      <th scope="col" className="px-5 py-3 font-medium sm:px-6">Record ID</th>
                      <th scope="col" className="px-5 py-3 font-medium">Legacy API type</th>
                      <th scope="col" className="px-5 py-3 font-medium">Legacy API status</th>
                      <th scope="col" className="px-5 py-3 font-medium">Created</th>
                      <th scope="col" className="px-5 py-3 font-medium">Approved</th>
                      <th scope="col" className="px-5 py-3 font-medium">Paid</th>
                      <th scope="col" className="px-5 py-3 text-right font-medium sm:px-6">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {commissions.map((commission) => (
                      <tr key={commission.id} className="align-top transition-colors hover:bg-white/[0.025] motion-reduce:transition-none">
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300 sm:px-6">#{commission.id}</td>
                        <td className="px-5 py-4 text-slate-300">{commission.type}</td>
                        <td className="px-5 py-4"><AffiliateStatusPill status={commission.status} /></td>
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300">{affiliateRecordDate(commission.createdAt)}</td>
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300">{affiliateRecordDate(commission.approvedAt)}</td>
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300">{affiliateRecordDate(commission.paidAt)}</td>
                        <td className="px-5 py-4 sm:px-6"><AffiliateExactAmount value={commission.amount} align="right" /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {commissions.length === 0 && <p className="px-5 py-10 text-center text-sm text-slate-400 sm:px-6">No commission records were returned for this server-filtered page.</p>}
            </section>
          </>
        )}
        {!error && pagination && <div className="mt-6"><AffiliateRecordPagination pagination={pagination} onPage={onPage} disabled={loading} loadingPage={loading ? requestedPage : null} /></div>}
      </main>
    </div>
  );
}

export default function Commissions() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const tenantId = useAuthStore(tenantSelector);
  const role = useAuthStore((state) => state.user?.role ?? null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState(null);
  const [exportError, setExportError] = useState(null);
  const [lastPagination, setLastPagination] = useState(null);
  const pendingPageRef = useRef(null);
  const read = useAffiliateRecordRead({
    kind: 'commissions',
    isAuthenticated,
    userId,
    tenantId,
    role,
    page,
    perPage: AFFILIATE_RECORD_PAGE_SIZE,
    status,
  });

  useEffect(() => {
    if (read.view?.pagination) setLastPagination({ principalKey: read.principalKey, pagination: read.view.pagination });
  }, [read.principalKey, read.view]);
  useEffect(() => {
    if (!read.loading) pendingPageRef.current = null;
  }, [read.loading]);

  const pagination = read.view?.pagination ?? (lastPagination?.principalKey === read.principalKey ? lastPagination.pagination : null);

  const changeStatus = (nextStatus) => {
    if (read.loading || pendingPageRef.current !== null) return;
    pendingPageRef.current = 'status';
    setExportError(null);
    setStatus(nextStatus === 'all' ? null : nextStatus);
    setPage(1);
  };
  const changePage = (nextPage) => {
    if (read.loading || pendingPageRef.current !== null || nextPage === page) return;
    pendingPageRef.current = nextPage;
    setExportError(null);
    setPage(nextPage);
  };
  const exportCurrentPage = useCallback(() => {
    setExportError(null);
    try {
      if (!read.view || read.loading || read.error) throw new Error('The current verified commissions page is not available for export.');
      downloadAffiliateCommissionsPage(read.view);
    } catch (error) {
      setExportError(error?.message || 'The current verified commissions page could not be exported.');
    }
  }, [read.error, read.loading, read.view]);

  return <AffiliateCommissionsView view={read.view} pagination={pagination} loading={read.loading} error={read.error} exportError={exportError} onRefresh={read.refresh} onPage={changePage} onStatus={changeStatus} onExport={exportCurrentPage} requestedPage={page} selectedStatus={status} />;
}
