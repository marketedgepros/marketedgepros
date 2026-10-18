import { useState } from 'react';
import useAuthStore from '../../store/authStore';
import { AFFILIATE_RECORD_PAGE_SIZE, AFFILIATE_REFERRAL_STATUSES, affiliateRecordError } from '../../services/affiliateRecordViewService.js';
import { useAffiliateRecordRead } from '../../hooks/useAffiliateAccountRead.js';
import {
  AffiliateExactAmount,
  AffiliateRecordBoundary,
  AffiliateRecordHeader,
  AffiliateRecordPagination,
  AffiliateRecordReadState,
  AffiliateStatusPill,
  affiliateRecordDate,
  affiliateRecordPanel,
} from '../../components/affiliate/AffiliateRecordUI.jsx';

const tenantSelector = (state) => state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null;

export function AffiliateReferralsView({ view, loading, error, onRefresh, onPage, onStatus }) {
  const referrals = view?.referrals ?? [];
  const status = view?.filters?.status ?? null;
  return (
    <div className="mep-screen min-h-screen text-white">
      <AffiliateRecordHeader
        eyebrow="Affiliate records"
        title="Referral activity"
        summary="Server-filtered referral activity for the signed-in affiliate account. Person-level information is intentionally not included."
        onRefresh={onRefresh}
        refreshing={loading}
      />
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <AffiliateRecordBoundary />
        <section className={`${affiliateRecordPanel} mt-6 p-4 sm:p-5`} aria-labelledby="referral-filter-heading">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 id="referral-filter-heading" className="mep-heading font-semibold text-white">Server status filter</h2>
              <p className="mt-1 text-sm text-slate-400">Changing the status starts again at page one; this read-only view has no local record search.</p>
            </div>
            <label className="flex shrink-0 items-center gap-3 text-sm text-slate-200" htmlFor="referral-status">
              Status
              <select id="referral-status" value={status ?? 'all'} onChange={(event) => onStatus(event.target.value)} className="rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200">
                <option value="all">All statuses</option>
                {AFFILIATE_REFERRAL_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
          </div>
        </section>

        <div className="mt-6"><AffiliateRecordReadState loading={loading} error={error ? affiliateRecordError(error) : null} onRetry={onRefresh} /></div>

        {!loading && !error && view && (
          <>
            <section className={`${affiliateRecordPanel} mt-6 overflow-hidden`} aria-labelledby="referral-records-heading">
              <div className="border-b border-white/10 px-5 py-4 sm:px-6">
                <h2 id="referral-records-heading" className="mep-heading text-xl font-semibold">Referral records</h2>
                <p className="mt-1 text-sm text-slate-400">Record IDs and exact API values only. Currency remains unavailable.</p>
              </div>
              <div role="region" aria-label="Referral records table" tabIndex="0" className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-200">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <caption className="sr-only">Referral records for the signed-in affiliate account</caption>
                  <thead className="bg-slate-950/50 text-xs uppercase tracking-[0.14em] text-slate-400">
                    <tr>
                      <th scope="col" className="px-5 py-3 font-medium sm:px-6">Record ID</th>
                      <th scope="col" className="px-5 py-3 font-medium">Legacy API status</th>
                      <th scope="col" className="px-5 py-3 font-medium">Click date</th>
                      <th scope="col" className="px-5 py-3 font-medium">Conversion date</th>
                      <th scope="col" className="px-5 py-3 text-right font-medium">Purchase amount</th>
                      <th scope="col" className="px-5 py-3 text-right font-medium sm:px-6">Reported commission</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {referrals.map((referral) => (
                      <tr key={referral.id} className="align-top transition-colors hover:bg-white/[0.025] motion-reduce:transition-none">
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300 sm:px-6">#{referral.id}</td>
                        <td className="px-5 py-4"><AffiliateStatusPill status={referral.status} /></td>
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300">{affiliateRecordDate(referral.clickDate)}</td>
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300">{affiliateRecordDate(referral.conversionDate)}</td>
                        <td className="px-5 py-4"><AffiliateExactAmount value={referral.purchaseAmount} align="right" /></td>
                        <td className="px-5 py-4 sm:px-6"><AffiliateExactAmount value={referral.commissionAmount} align="right" /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {referrals.length === 0 && <p className="px-5 py-10 text-center text-sm text-slate-400 sm:px-6">No referral records were returned for this server-filtered page.</p>}
            </section>
            <div className="mt-6"><AffiliateRecordPagination pagination={view.pagination} onPage={onPage} /></div>
          </>
        )}
      </div>
    </div>
  );
}

export default function TradersManagement() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const tenantId = useAuthStore(tenantSelector);
  const role = useAuthStore((state) => state.user?.role ?? null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState(null);
  const read = useAffiliateRecordRead({
    kind: 'referrals',
    isAuthenticated,
    userId,
    tenantId,
    role,
    page,
    perPage: AFFILIATE_RECORD_PAGE_SIZE,
    status,
  });

  const changeStatus = (nextStatus) => {
    setStatus(nextStatus === 'all' ? null : nextStatus);
    setPage(1);
  };
  return <AffiliateReferralsView view={read.view} loading={read.loading} error={read.error} onRefresh={read.refresh} onPage={setPage} onStatus={changeStatus} />;
}
