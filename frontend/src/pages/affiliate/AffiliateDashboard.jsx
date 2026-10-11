import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  Check,
  Clipboard,
  DollarSign,
  Link as LinkIcon,
  MousePointerClick,
  Users,
} from 'lucide-react';
import useAuthStore from '../../store/authStore';
import {
  affiliateViewError,
  loadAffiliateDashboard,
} from '../../services/affiliateViewService';

const UNAVAILABLE = 'Unavailable';

const formatNumber = (value) => (
  Number.isFinite(value) ? new Intl.NumberFormat('en-US').format(value) : UNAVAILABLE
);

const formatCurrency = (value) => (
  Number.isFinite(value)
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
    : UNAVAILABLE
);

const formatPercent = (value) => (Number.isFinite(value) ? `${value.toFixed(2)}%` : UNAVAILABLE);

const formatDate = (value) => {
  if (!value) return UNAVAILABLE;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? UNAVAILABLE : date.toLocaleDateString();
};

// The API's AffiliateLink serializer returns the public `url` field. Do not copy
// arbitrary data or credential-bearing URLs from an unexpected response payload.
const getSafeServerReferralUrl = (value) => {
  if (typeof value !== 'string' || !value.trim()) return null;

  try {
    const url = new URL(value);
    if (
      url.protocol !== 'https:'
      || url.hostname !== 'marketedgepros.com'
      || url.username
      || url.password
      || url.hash
      || url.searchParams.getAll('ref').length !== 1
      || [...url.searchParams.keys()].some((key) => key !== 'ref')
      || !/^[A-Z0-9]{1,50}$/.test(url.searchParams.get('ref'))
    ) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
};

export default function AffiliateDashboard() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userIdentifier = useAuthStore((state) => state.user?.id ?? state.user?.email ?? null);
  const affiliateIdentity = isAuthenticated && userIdentifier !== null
    ? String(userIdentifier)
    : null;

  const [dashboard, setDashboard] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [copyState, setCopyState] = useState({ url: null, status: 'idle', message: null });
  const loadGenerationRef = useRef(0);
  const copyGenerationRef = useRef(0);
  const copyInFlightRef = useRef(false);

  useEffect(() => {
    const generation = ++loadGenerationRef.current;
    let isCurrent = true;

    setDashboard(null);
    setLoadError(null);

    if (!affiliateIdentity) {
      setIsLoading(false);
      setLoadError('Your current affiliate account identity is unavailable. Please sign in again.');
      return () => {
        isCurrent = false;
      };
    }

    const loadDashboard = async () => {
      setIsLoading(true);
      try {
        const nextDashboard = await loadAffiliateDashboard();
        if (isCurrent && generation === loadGenerationRef.current) {
          setDashboard(nextDashboard);
        }
      } catch (error) {
        if (isCurrent && generation === loadGenerationRef.current) {
          setDashboard(null);
          setLoadError(affiliateViewError(error));
        }
      } finally {
        if (isCurrent && generation === loadGenerationRef.current) {
          setIsLoading(false);
        }
      }
    };

    loadDashboard();
    return () => {
      isCurrent = false;
    };
  }, [affiliateIdentity]);

  useEffect(() => () => {
    copyGenerationRef.current += 1;
    copyInFlightRef.current = false;
  }, []);

  const verifiedLinks = useMemo(() => (
    (dashboard?.links || []).map((link, index) => ({
      ...link,
      key: link?.id ?? `server-link-${index}`,
      shareUrl: getSafeServerReferralUrl(link?.url),
    }))
  ), [dashboard]);

  const copyReferralUrl = async (shareUrl) => {
    if (!shareUrl || copyInFlightRef.current) return;

    const requestGeneration = ++copyGenerationRef.current;
    copyInFlightRef.current = true;
    setCopyState({ url: shareUrl, status: 'copying', message: null });

    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        throw new Error('Clipboard access is unavailable.');
      }

      await navigator.clipboard.writeText(shareUrl);
      if (requestGeneration === copyGenerationRef.current) {
        setCopyState({ url: shareUrl, status: 'copied', message: null });
      }
    } catch {
      if (requestGeneration === copyGenerationRef.current) {
        setCopyState({
          url: shareUrl,
          status: 'error',
          message: 'Copy failed. Please select the server-provided link and copy it manually.',
        });
      }
    } finally {
      if (requestGeneration === copyGenerationRef.current) {
        copyInFlightRef.current = false;
      }
    }
  };

  const stats = dashboard?.stats;

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <section className="border-b border-cyan-400/10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-500/10 via-slate-950 to-slate-950">
        <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">Affiliate account</p>
          <div className="mt-3 flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
            <div>
              <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Performance overview</h1>
              <p className="mt-3 max-w-2xl text-slate-300">
                View the activity and commission records currently reported for your affiliate account.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <DashboardNavLink to="/affiliate/traders" label="My traders" />
              <DashboardNavLink to="/affiliate/commissions" label="Commissions" />
              <DashboardNavLink to="/affiliate/reports" label="Reports" />
              <DashboardNavLink to="/affiliate/payout" label="Payout status" />
              <DashboardNavLink to="/support/create-ticket" label="Support" />
            </div>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {isLoading ? (
          <div className="flex min-h-64 items-center justify-center rounded-2xl border border-white/10 bg-slate-900/60">
            <div className="text-center">
              <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-cyan-300/20 border-t-cyan-300" />
              <p className="mt-4 text-sm text-slate-300">Loading affiliate account data...</p>
            </div>
          </div>
        ) : loadError ? (
          <div role="alert" className="rounded-2xl border border-rose-400/30 bg-rose-950/30 p-5 text-rose-100">
            <p className="font-semibold">Affiliate dashboard is unavailable</p>
            <p className="mt-1 text-sm text-rose-100/80">{loadError}</p>
            <Link to="/support/create-ticket" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200 hover:text-cyan-100">
              Contact support <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        ) : (
          <>
            <section aria-label="Reported affiliate metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Referral clicks" value={formatNumber(stats?.totalClicks)} icon={<MousePointerClick className="h-5 w-5" />} />
              <MetricCard label="Conversions" value={formatNumber(stats?.totalConversions)} icon={<Users className="h-5 w-5" />} />
              <MetricCard label="Tracked commission" value={formatCurrency(stats?.totalCommission)} icon={<DollarSign className="h-5 w-5" />} />
              <MetricCard label="Conversion rate" value={formatPercent(stats?.conversionRate)} icon={<BarChart3 className="h-5 w-5" />} />
            </section>

            <section className="mt-6 rounded-2xl border border-cyan-400/15 bg-slate-900/70 p-5 shadow-xl shadow-cyan-950/10 sm:p-6">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                <div>
                  <h2 className="text-xl font-semibold">Recorded commission status</h2>
                  <p className="mt-1 text-sm text-slate-400">These are reported commission categories, not verified withdrawable amounts.</p>
                </div>
                <Link to="/affiliate/payout" className="inline-flex items-center gap-2 text-sm font-semibold text-cyan-300 hover:text-cyan-200">
                  View payout status <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <CommissionValue label="Pending" value={formatCurrency(stats?.pendingCommission)} tone="text-amber-200" />
                <CommissionValue label="Approved" value={formatCurrency(stats?.approvedCommission)} tone="text-cyan-200" />
                <CommissionValue label="Paid" value={formatCurrency(stats?.paidCommission)} tone="text-emerald-200" />
              </div>
            </section>

            <section className="mt-6 rounded-2xl border border-white/10 bg-slate-900/70 p-5 sm:p-6">
              <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
                <div>
                  <h2 className="text-xl font-semibold">Server-provided referral links</h2>
                  <p className="mt-1 text-sm text-slate-400">Only public HTTPS referral links returned by the account API can be copied here.</p>
                </div>
                <span className="text-sm text-slate-400">Link management is deferred while affiliate plan support is completed.</span>
              </div>

              {verifiedLinks.length === 0 ? (
                <div className="mt-5 rounded-xl border border-dashed border-white/10 bg-slate-950/40 px-4 py-8 text-center text-sm text-slate-400">
                  No referral links were returned for this account.
                </div>
              ) : (
                <div className="mt-5 space-y-3">
                  {verifiedLinks.map((link) => (
                    <article key={link.key} className="rounded-xl border border-white/10 bg-slate-950/45 p-4">
                      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm font-semibold text-white">
                            <LinkIcon className="h-4 w-4 text-cyan-300" />
                            {link.name || 'Referral link'}
                          </div>
                          <p className="mt-1 text-xs text-slate-400">
                            {formatNumber(link.clicks)} clicks · {formatNumber(link.conversions)} conversions
                          </p>
                        </div>
                        {link.shareUrl ? (
                          <button
                            type="button"
                            onClick={() => copyReferralUrl(link.shareUrl)}
                            disabled={copyState.status === 'copying'}
                            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {copyState.url === link.shareUrl && copyState.status === 'copied' ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}
                            {copyState.url === link.shareUrl && copyState.status === 'copying'
                              ? 'Copying...'
                              : copyState.url === link.shareUrl && copyState.status === 'copied'
                                ? 'Copied'
                                : 'Copy link'}
                          </button>
                        ) : (
                          <span className="text-sm text-slate-400">A shareable server link is unavailable.</span>
                        )}
                      </div>
                      {link.shareUrl && (
                        <input
                          aria-label={`${link.name || 'Referral'} link`}
                          className="mt-3 w-full rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-xs text-slate-300 outline-none"
                          readOnly
                          value={link.shareUrl}
                        />
                      )}
                      {copyState.url === link.shareUrl && copyState.status === 'error' && (
                        <p role="status" className="mt-2 text-sm text-rose-200">{copyState.message}</p>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section className="mt-6 overflow-hidden rounded-2xl border border-white/10 bg-slate-900/70">
              <div className="border-b border-white/10 px-5 py-4 sm:px-6">
                <h2 className="text-xl font-semibold">Recent referral activity</h2>
                <p className="mt-1 text-sm text-slate-400">The latest activity currently supplied by the affiliate account API.</p>
              </div>
              {(dashboard?.recentReferrals || []).length === 0 ? (
                <p className="px-5 py-10 text-center text-sm text-slate-400 sm:px-6">No recent referral activity was returned.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead className="bg-slate-950/50 text-xs uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="px-5 py-3 font-medium sm:px-6">Referred trader</th>
                        <th className="px-5 py-3 font-medium">Status</th>
                        <th className="px-5 py-3 font-medium">Click date</th>
                        <th className="px-5 py-3 text-right font-medium sm:px-6">Recorded commission</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {dashboard.recentReferrals.map((referral) => (
                        <tr key={referral.id}>
                          <td className="px-5 py-4 sm:px-6">
                            <p className="font-medium text-white">{referral.name || UNAVAILABLE}</p>
                            <p className="mt-0.5 text-xs text-slate-400">{referral.email || UNAVAILABLE}</p>
                          </td>
                          <td className="px-5 py-4 text-slate-300">{referral.status || UNAVAILABLE}</td>
                          <td className="px-5 py-4 text-slate-300">{formatDate(referral.clickDate)}</td>
                          <td className="px-5 py-4 text-right font-semibold text-white sm:px-6">{formatCurrency(referral.commissionAmount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function DashboardNavLink({ to, label }) {
  return (
    <Link to={to} className="rounded-full border border-white/10 bg-slate-900/60 px-3 py-1.5 text-sm text-slate-200 transition hover:border-cyan-300/40 hover:text-cyan-200">
      {label}
    </Link>
  );
}

function MetricCard({ label, value, icon }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/70 p-5 shadow-lg shadow-slate-950/20">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-slate-400">{label}</p>
          <p className="mt-2 text-2xl font-bold tracking-tight text-white">{value}</p>
        </div>
        <div className="rounded-xl bg-cyan-300/10 p-2.5 text-cyan-300">{icon}</div>
      </div>
    </div>
  );
}

function CommissionValue({ label, value, tone }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-950/45 p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${tone}`}>{value}</p>
    </div>
  );
}
