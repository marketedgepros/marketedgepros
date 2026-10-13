import useAuthStore from '../../store/authStore';
import { affiliateViewError } from '../../services/affiliateViewService.js';
import { useAffiliateDashboardRead } from '../../hooks/useAffiliateAccountRead.js';
import {
  AffiliateExactAmount,
  AffiliateRecordBoundary,
  AffiliateRecordHeader,
  AffiliateRecordReadState,
  AffiliateStatusPill,
  affiliateRecordDate,
  affiliateRecordDisplay,
  affiliateRecordPanel,
} from '../../components/affiliate/AffiliateRecordUI.jsx';

const tenantSelector = (state) => state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null;
const count = (value) => Number.isSafeInteger(value) && value >= 0 ? new Intl.NumberFormat('en-US').format(value) : 'Unavailable';

function ReportMetric({ label, value, amount = false }) {
  return (
    <article className={`${affiliateRecordPanel} p-5`}>
      <p className="text-sm text-slate-400">{label}</p>
      {amount ? <div className="mt-2"><AffiliateExactAmount value={value} /></div> : <p className="mt-2 break-all text-2xl font-semibold tabular-nums text-white">{value}</p>}
    </article>
  );
}

export function AffiliateReportsView({ dashboard, loading, error, onRefresh }) {
  const stats = dashboard?.stats;
  const referrals = dashboard?.recentReferrals ?? [];
  return (
    <div className="mep-screen min-h-screen text-white">
      <AffiliateRecordHeader
        eyebrow="Affiliate reporting"
        title="Account reporting"
        summary="Current aggregate records and a bounded recent-activity list from the affiliate dashboard for this signed-in account."
        onRefresh={onRefresh}
        refreshing={loading}
      />
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <AffiliateRecordBoundary />
        <div className="mt-6"><AffiliateRecordReadState loading={loading} error={error ? affiliateViewError(error) : null} onRetry={onRefresh} /></div>

        {!loading && !error && dashboard && (
          <>
            <section aria-labelledby="report-overview-heading" className="mt-6">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h2 id="report-overview-heading" className="mep-heading text-xl font-semibold">Dashboard record overview</h2>
                  <p className="mt-1 text-sm text-slate-400">Only fields returned by the existing dashboard are shown; no rate or period comparison is inferred.</p>
                </div>
                <p className="text-sm text-amber-100">Verification: unverified legacy</p>
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <ReportMetric label="Referral clicks" value={count(stats.totalClicks)} />
                <ReportMetric label="Conversions" value={count(stats.totalConversions)} />
                <ReportMetric label="Reported revenue" value={stats.totalRevenue} amount />
                <ReportMetric label="Reported commission total" value={stats.totalCommission} amount />
              </div>
            </section>

            <section aria-labelledby="report-categories-heading" className={`${affiliateRecordPanel} mt-6 p-5 sm:p-6`}>
              <h2 id="report-categories-heading" className="mep-heading text-xl font-semibold">Legacy API commission categories</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">Pending, approved, and paid are legacy labels only. They do not confirm payment, availability, or a payout entitlement.</p>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <div className="mep-panel rounded-xl border p-4"><p className="text-sm text-slate-400">Pending</p><div className="mt-2"><AffiliateExactAmount value={stats.pendingCommission} /></div></div>
                <div className="mep-panel rounded-xl border p-4"><p className="text-sm text-slate-400">Approved</p><div className="mt-2"><AffiliateExactAmount value={stats.approvedCommission} /></div></div>
                <div className="mep-panel rounded-xl border p-4"><p className="text-sm text-slate-400">Paid</p><div className="mt-2"><AffiliateExactAmount value={stats.paidCommission} /></div></div>
              </div>
            </section>

            <section className={`${affiliateRecordPanel} mt-6 overflow-hidden`} aria-labelledby="report-recent-heading">
              <div className="border-b border-white/10 px-5 py-4 sm:px-6">
                <h2 id="report-recent-heading" className="mep-heading text-xl font-semibold">Recent referral activity</h2>
                <p className="mt-1 text-sm text-slate-400">At most ten identifier-only records are supplied by the dashboard. No person-level information is shown.</p>
              </div>
              <div role="region" aria-label="Recent referral activity table" tabIndex="0" className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-200">
                <table className="w-full min-w-[620px] text-left text-sm">
                  <caption className="sr-only">Recent referral activity for the signed-in affiliate account</caption>
                  <thead className="bg-slate-950/50 text-xs uppercase tracking-[0.14em] text-slate-400">
                    <tr>
                      <th scope="col" className="px-5 py-3 font-medium sm:px-6">Record ID</th>
                      <th scope="col" className="px-5 py-3 font-medium">Legacy API status</th>
                      <th scope="col" className="px-5 py-3 font-medium">Click date</th>
                      <th scope="col" className="px-5 py-3 text-right font-medium sm:px-6">Reported commission</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {referrals.map((referral) => (
                      <tr key={referral.id} className="align-top transition-colors hover:bg-white/[0.025] motion-reduce:transition-none">
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300 sm:px-6">#{referral.id}</td>
                        <td className="px-5 py-4"><AffiliateStatusPill status={referral.status} /></td>
                        <td className="px-5 py-4 font-mono text-xs tabular-nums text-slate-300">{affiliateRecordDate(referral.clickDate)}</td>
                        <td className="px-5 py-4 sm:px-6"><AffiliateExactAmount value={referral.commissionAmount} align="right" /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {referrals.length === 0 && <p className="px-5 py-10 text-center text-sm text-slate-400 sm:px-6">No recent referral activity was returned by the dashboard.</p>}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

export default function Reports() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const tenantId = useAuthStore(tenantSelector);
  const role = useAuthStore((state) => state.user?.role ?? null);
  const read = useAffiliateDashboardRead({ isAuthenticated, userId, tenantId, role });
  return <AffiliateReportsView dashboard={read.view} loading={read.loading} error={read.error} onRefresh={read.refresh} />;
}
