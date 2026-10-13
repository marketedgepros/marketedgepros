import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Clipboard,
  Database,
  Link as LinkIcon,
  MousePointerClick,
  RefreshCw,
  Users,
} from 'lucide-react';
import useAuthStore from '../../store/authStore';
import {
  affiliateViewError,
  getSafeAffiliateReferralUrl,
  loadAffiliateDashboard,
  normaliseAffiliateExpectedOwner,
} from '../../services/affiliateViewService';

const UNAVAILABLE = 'Unavailable';

const tenantFromUser = (user) => (
  user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id ?? null
);

const formatCount = (value) => (
  Number.isSafeInteger(value) && value >= 0
    ? new Intl.NumberFormat('en-US').format(value)
    : UNAVAILABLE
);

const formatDate = (value) => {
  if (typeof value !== 'string' || !value) return UNAVAILABLE;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? UNAVAILABLE : date.toLocaleDateString();
};

const isAbortError = (error) => error?.name === 'AbortError' || error?.code === 'ERR_CANCELED';

/**
 * The outer key is intentional: an auth, user, tenant, or role transition
 * unmounts all read/copy state before a response from the prior account can
 * paint in the new account shell.
 */
export default function AffiliateDashboard() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const tenantId = tenantFromUser(user);
  const role = user?.role ?? null;
  const contextKey = useMemo(() => JSON.stringify([
    isAuthenticated === true,
    user?.id ?? null,
    tenantId,
    role,
  ]), [isAuthenticated, role, tenantId, user?.id]);

  const expectedOwner = useMemo(() => {
    if (isAuthenticated !== true || role !== 'affiliate') return null;
    try {
      return normaliseAffiliateExpectedOwner({ user_id: user?.id, tenant_id: tenantId });
    } catch {
      return null;
    }
  }, [isAuthenticated, role, tenantId, user?.id]);

  return (
    <AffiliateDashboardSession
      key={contextKey}
      expectedOwner={expectedOwner}
    />
  );
}

function AffiliateDashboardSession({ expectedOwner }) {
  const [dashboard, setDashboard] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [copyState, setCopyState] = useState({ url: null, status: 'idle', message: null });
  const loadGenerationRef = useRef(0);
  const dashboardGenerationRef = useRef(0);
  const copyGenerationRef = useRef(0);
  const copyInFlightRef = useRef(false);
  const loadInFlightRef = useRef(false);
  const requestControllerRef = useRef(null);
  const currentLinkUrlsRef = useRef(new Set());

  const clearCopyState = useCallback(() => {
    copyGenerationRef.current += 1;
    copyInFlightRef.current = false;
    setCopyState({ url: null, status: 'idle', message: null });
  }, []);

  const beginLoad = useCallback(() => {
    if (loadInFlightRef.current) return;

    const generation = ++loadGenerationRef.current;
    dashboardGenerationRef.current += 1;
    currentLinkUrlsRef.current = new Set();
    clearCopyState();
    setDashboard(null);
    setLoadError(null);

    if (!expectedOwner) {
      setIsLoading(false);
      setLoadError('Your current affiliate account context could not be verified. Please sign in again.');
      return;
    }

    const controller = new AbortController();
    requestControllerRef.current = controller;
    loadInFlightRef.current = true;
    setIsLoading(true);

    void loadAffiliateDashboard({ signal: controller.signal, expectedOwner })
      .then((nextDashboard) => {
        if (controller.signal.aborted || generation !== loadGenerationRef.current) return;
        currentLinkUrlsRef.current = new Set(nextDashboard.links.map((link) => link.url));
        setDashboard(nextDashboard);
      })
      .catch((error) => {
        if (controller.signal.aborted || generation !== loadGenerationRef.current || isAbortError(error)) return;
        setDashboard(null);
        setLoadError(affiliateViewError(error));
      })
      .finally(() => {
        if (generation !== loadGenerationRef.current) return;
        loadInFlightRef.current = false;
        if (requestControllerRef.current === controller) requestControllerRef.current = null;
        setIsLoading(false);
      });
  }, [clearCopyState, expectedOwner]);

  useEffect(() => {
    beginLoad();
    return () => {
      // Abort is necessary but not sufficient for adapters that resolve late, so
      // the generation and dataset counters invalidate completion and clipboard ACKs too.
      loadGenerationRef.current += 1;
      dashboardGenerationRef.current += 1;
      copyGenerationRef.current += 1;
      copyInFlightRef.current = false;
      loadInFlightRef.current = false;
      currentLinkUrlsRef.current = new Set();
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
    };
  }, [beginLoad]);

  const refreshDashboard = useCallback(() => {
    if (!loadInFlightRef.current) beginLoad();
  }, [beginLoad]);

  const copyReferralUrl = useCallback(async (candidateUrl) => {
    const shareUrl = getSafeAffiliateReferralUrl(candidateUrl);
    if (!shareUrl || copyInFlightRef.current || !currentLinkUrlsRef.current.has(shareUrl)) return;

    const copyGeneration = ++copyGenerationRef.current;
    const dashboardGeneration = dashboardGenerationRef.current;
    copyInFlightRef.current = true;
    setCopyState({ url: shareUrl, status: 'copying', message: null });

    const isCurrentCopyTarget = () => (
      copyGeneration === copyGenerationRef.current
      && dashboardGeneration === dashboardGenerationRef.current
      && currentLinkUrlsRef.current.has(shareUrl)
    );

    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        throw new Error('Clipboard access is unavailable.');
      }

      await navigator.clipboard.writeText(shareUrl);
      if (isCurrentCopyTarget()) {
        setCopyState({ url: shareUrl, status: 'copied', message: 'Referral link copied.' });
      }
    } catch {
      if (isCurrentCopyTarget()) {
        setCopyState({
          url: shareUrl,
          status: 'error',
          message: 'Copy failed. Please use the displayed canonical link if your browser permits it.',
        });
      }
    } finally {
      if (isCurrentCopyTarget()) copyInFlightRef.current = false;
    }
  }, []);

  return (
    <AffiliateDashboardView
      dashboard={dashboard}
      isLoading={isLoading}
      loadError={loadError}
      copyState={copyState}
      onCopy={copyReferralUrl}
      onRefresh={refreshDashboard}
    />
  );
}

/** Exported for focused SSR rendering tests; it remains a strictly read-only view. */
export function AffiliateDashboardView({
  dashboard,
  isLoading,
  loadError,
  copyState = { url: null, status: 'idle', message: null },
  onCopy = () => {},
  onRefresh = () => {},
}) {
  const stats = dashboard?.stats;
  const safeLinks = useMemo(() => (
    (dashboard?.links || []).map((link) => ({ ...link, shareUrl: getSafeAffiliateReferralUrl(link.url) }))
  ), [dashboard]);

  return (
    <div className="bg-slate-950 text-white">
      <section className="mep-workspace-hero border-b">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">Affiliate account</p>
          <div className="mt-3 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
            <div className="min-w-0">
              <h1 className="mep-heading text-3xl font-bold tracking-tight sm:text-4xl">Performance overview</h1>
              <p className="mt-3 max-w-2xl text-slate-300">
                Read-only activity and legacy API categories reported for this affiliate account.
              </p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label="Affiliate account navigation">
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
        <div className="mb-6 flex flex-col gap-3 border-b border-white/10 pb-5 sm:flex-row sm:items-center sm:justify-between">
          <p role="status" className="flex min-w-0 items-center gap-2 text-sm text-amber-100">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" />
            <span>Source status: <strong className="font-semibold">unverified legacy API records</strong>; payout actions are disabled.</span>
          </p>
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            aria-label="Refresh affiliate dashboard data"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            {isLoading ? 'Refreshing data' : 'Refresh data'}
          </button>
        </div>

        {isLoading ? (
          <div role="status" aria-live="polite" aria-busy="true" className="mep-panel flex min-h-64 items-center justify-center rounded-2xl border">
            <div className="text-center">
              <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-cyan-300/20 border-t-cyan-300 motion-reduce:animate-none" aria-hidden="true" />
              <p className="mt-4 text-sm text-slate-300">Loading affiliate account data...</p>
            </div>
          </div>
        ) : loadError ? (
          <div role="alert" className="rounded-2xl border border-rose-400/30 bg-rose-950/30 p-5 text-rose-100">
            <p className="font-semibold">Affiliate dashboard is unavailable</p>
            <p className="mt-1 break-words text-sm text-rose-100/80">{loadError}</p>
            <Link to="/support/create-ticket" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200 transition hover:text-cyan-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 motion-reduce:transition-none">
              Contact support <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
        ) : dashboard ? (
          <>
            <section aria-labelledby="affiliate-next-action-heading" className="mep-panel mep-interior-card mb-6 grid gap-5 rounded-2xl border p-5 sm:p-6 lg:grid-cols-[1.3fr_1fr]">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">Your workspace, in order</p>
                <h2 id="affiliate-next-action-heading" className="mep-heading mt-2 text-xl font-semibold">Your next action</h2>
                <p className="mt-2 text-sm leading-6 text-slate-300">
                  {safeLinks.some((link) => link.shareUrl)
                    ? 'A canonical referral link was returned. Review your supplied links and their recorded activity below.'
                    : 'No shareable canonical link was returned. Review your referral records, or ask support about the account record.'}
                </p>
                <Link to={safeLinks.some((link) => link.shareUrl) ? '#affiliate-links-heading' : '/affiliate/traders'}
                  className="mep-primary mt-4 inline-flex items-center gap-2 px-4 py-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">
                  {safeLinks.some((link) => link.shareUrl) ? 'Review supplied links' : 'Review referral records'}
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </div>
              <div className="min-w-0 border-t border-white/10 pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
                <p className="text-sm font-semibold text-amber-100">Payout availability: not enabled</p>
                <p className="mt-2 text-sm leading-6 text-slate-400">Recorded commission labels do not establish payable money or approved affiliate terms.</p>
                <Link to="/affiliate/payout" className="mt-3 inline-flex rounded text-sm font-semibold text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">Review payout status</Link>
              </div>
            </section>
            <section aria-label="Reported affiliate metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Referral clicks" value={formatCount(stats.totalClicks)} icon={<MousePointerClick className="h-5 w-5" aria-hidden="true" />} />
              <MetricCard label="Conversions" value={formatCount(stats.totalConversions)} icon={<Users className="h-5 w-5" aria-hidden="true" />} />
              <MetricCard label="Reported revenue" value={<ExactAmount value={stats.totalRevenue} />} icon={<Database className="h-5 w-5" aria-hidden="true" />} />
              <MetricCard label="Reported commission total" value={<ExactAmount value={stats.totalCommission} />} icon={<AlertTriangle className="h-5 w-5" aria-hidden="true" />} />
            </section>

            <section aria-labelledby="legacy-commission-heading" className="mep-panel mt-6 rounded-2xl border border-amber-300/20 p-5 shadow-xl shadow-cyan-950/10 sm:p-6">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                <div className="min-w-0">
                  <h2 id="legacy-commission-heading" className="mep-heading text-xl font-semibold">Legacy API commission categories</h2>
                  <p className="mt-1 max-w-3xl text-sm text-slate-400">
                    Pending, approved, and paid are legacy API labels only. They are not paid, verified, available, or withdrawable money.
                  </p>
                </div>
                <span className="inline-flex shrink-0 items-center gap-2 rounded-full border border-amber-300/25 bg-amber-300/10 px-3 py-1.5 text-xs font-semibold text-amber-100">
                  Verification: unverified legacy
                </span>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <CommissionValue label="Legacy API category: pending" value={stats.pendingCommission} />
                <CommissionValue label="Legacy API category: approved" value={stats.approvedCommission} />
                <CommissionValue label="Legacy API category: paid" value={stats.paidCommission} />
              </div>
            </section>

            <section aria-labelledby="affiliate-links-heading" className="mep-panel mt-6 rounded-2xl border p-5 sm:p-6">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                <div className="min-w-0">
                  <h2 id="affiliate-links-heading" className="mep-heading scroll-mt-24 text-xl font-semibold">Server-provided referral links</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Only canonical public HTTPS links returned by the account API are available to copy.
                  </p>
                </div>
                {dashboard.linkPagination?.truncated ? (
                  <p className="max-w-sm text-sm text-amber-100">
                    Showing the first {dashboard.linkPagination.limit} of {formatCount(dashboard.linkPagination.total)} links. Additional links are not shown in this view.
                  </p>
                ) : (
                  <p className="text-sm text-slate-400">{formatCount(dashboard.linkPagination?.total)} reported links</p>
                )}
              </div>

              {safeLinks.length === 0 ? (
                <div className="mep-panel mt-5 rounded-xl border border-dashed px-4 py-8 text-center text-sm text-slate-400">
                  No referral links were returned for this account.
                </div>
              ) : (
                <div className="mt-5 space-y-3">
                  {safeLinks.map((link) => (
                    <article key={link.id} className="mep-panel rounded-xl border p-4">
                      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
                        <div className="min-w-0">
                          <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-white">
                            <LinkIcon className="h-4 w-4 shrink-0 text-cyan-300" aria-hidden="true" />
                            <span className="break-words">{link.name || 'Referral link'}</span>
                          </div>
                          <p className="mt-1 text-xs text-slate-400">
                            {formatCount(link.clicks)} clicks · {formatCount(link.conversions)} conversions
                          </p>
                        </div>
                        {link.shareUrl ? (
                          <button
                            type="button"
                            onClick={() => onCopy(link.shareUrl)}
                            disabled={copyState.status === 'copying'}
                            aria-label={`Copy referral link ${link.id}`}
                            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none"
                          >
                            {copyState.url === link.shareUrl && copyState.status === 'copied'
                              ? <Check className="h-4 w-4" aria-hidden="true" />
                              : <Clipboard className="h-4 w-4" aria-hidden="true" />}
                            {copyState.url === link.shareUrl && copyState.status === 'copying'
                              ? 'Copying link'
                              : copyState.url === link.shareUrl && copyState.status === 'copied'
                                ? 'Copied'
                                : 'Copy link'}
                          </button>
                        ) : (
                          <span className="text-sm text-slate-400">A shareable canonical link is unavailable.</span>
                        )}
                      </div>
                      {link.shareUrl && (
                        <input
                          aria-label={`Canonical referral link ${link.id}`}
                          className="mt-3 w-full rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-xs text-slate-300 outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
                          readOnly
                          value={link.shareUrl}
                        />
                      )}
                      {copyState.url === link.shareUrl && copyState.status === 'copied' && (
                        <p role="status" aria-live="polite" className="mt-2 text-sm text-cyan-100">{copyState.message}</p>
                      )}
                      {copyState.url === link.shareUrl && copyState.status === 'error' && (
                        <p role="alert" className="mt-2 text-sm text-rose-200">{copyState.message}</p>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section aria-labelledby="recent-referrals-heading" className="mep-panel mt-6 overflow-hidden rounded-2xl border">
              <div className="border-b border-white/10 px-5 py-4 sm:px-6">
                <h2 id="recent-referrals-heading" className="mep-heading text-xl font-semibold">Recent referral activity</h2>
                <p className="mt-1 text-sm text-slate-400">At most ten identifier-only activity records are supplied. No referred-user details are displayed.</p>
              </div>
              {dashboard.recentReferrals.length === 0 ? (
                <p className="px-5 py-10 text-center text-sm text-slate-400 sm:px-6">No recent referral activity was returned.</p>
              ) : (
                <div role="region" aria-label="Recent referral activity table" tabIndex="0" className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-200">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead className="bg-slate-950/50 text-xs uppercase tracking-wide text-slate-400">
                      <tr>
                        <th scope="col" className="px-5 py-3 font-medium sm:px-6">Record ID</th>
                        <th scope="col" className="px-5 py-3 font-medium">Legacy API status</th>
                        <th scope="col" className="px-5 py-3 font-medium">Click date</th>
                        <th scope="col" className="px-5 py-3 text-right font-medium sm:px-6">Reported commission</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {dashboard.recentReferrals.map((referral) => (
                        <tr key={referral.id}>
                          <td className="px-5 py-4 font-mono text-xs text-slate-300 sm:px-6">#{referral.id}</td>
                          <td className="px-5 py-4 text-slate-300">{referral.status || UNAVAILABLE}</td>
                          <td className="px-5 py-4 text-slate-300">{formatDate(referral.clickDate)}</td>
                          <td className="px-5 py-4 text-right sm:px-6"><ExactAmount value={referral.commissionAmount} align="right" /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        ) : (
          <div role="status" className="mep-panel rounded-2xl border p-8 text-center text-sm text-slate-400">
            Affiliate dashboard data is unavailable.
          </div>
        )}
      </main>
    </div>
  );
}

function DashboardNavLink({ to, label }) {
  return (
    <Link to={to} className="rounded-full border border-white/10 bg-slate-900/60 px-3 py-1.5 text-sm text-slate-200 transition hover:border-cyan-300/40 hover:text-cyan-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 motion-reduce:transition-none">
      {label}
    </Link>
  );
}

function ExactAmount({ value, align = 'left' }) {
  if (value === null || value === undefined) {
    return <span className="text-slate-400">{UNAVAILABLE}</span>;
  }

  return (
    <span className={`inline-flex flex-col ${align === 'right' ? 'items-end' : 'items-start'} tabular-nums`}>
      <span className="break-all font-semibold text-white">{value}</span>
      <span className="mt-0.5 text-xs font-normal text-slate-400">Currency unavailable</span>
    </span>
  );
}

function MetricCard({ label, value, icon }) {
  return (
    <div className="mep-panel mep-interior-card min-w-0 rounded-2xl border p-5 shadow-lg shadow-slate-950/20">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-slate-400">{label}</p>
          <div className="mt-2 break-all text-2xl font-bold tracking-tight text-white">{value}</div>
        </div>
        <div className="shrink-0 rounded-xl bg-cyan-300/10 p-2.5 text-cyan-300">{icon}</div>
      </div>
    </div>
  );
}

function CommissionValue({ label, value }) {
  return (
    <div className="mep-panel min-w-0 rounded-xl border p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <div className="mt-2"><ExactAmount value={value} /></div>
    </div>
  );
}
