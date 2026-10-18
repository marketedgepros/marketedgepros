import { useEffect, useState } from 'react';
import { ArrowRight, BarChart3, BookOpen, FileText, RefreshCw, ShieldAlert, UserRound } from 'lucide-react';
import { Link } from 'react-router-dom';
import useAuthStore from '../../store/authStore';
import api, { profileAPI } from '../../services/api';
import AccountSetupGuide from '../../components/account/AccountSetupGuide';
import ProgramPurchaseRecords from '../../components/payments/ProgramPurchaseRecords';
import { createProfileApiTransport } from '../../services/profileViewService';
import { createAccountSetupViewService } from '../../services/accountSetupViewService';
import {
  isDashboardRequestCanceled,
  loadUserDashboard,
} from '../../services/userDashboardViewService';

// The guide receives the same configured same-origin clients as the rest of the
// account pages. Its service only exposes the two existing read endpoints.
const configuredAccountSetupService = createAccountSetupViewService({
  profileTransport: createProfileApiTransport(profileAPI),
  documentsClient: api,
});

const countLabel = (value) => new Intl.NumberFormat('en-US').format(value);

const positiveIntegerOrNull = (value) => (
  Number.isSafeInteger(value) && value > 0 ? value : null
);

const strictRoleOrNull = (value) => (
  typeof value === 'string' && value.trim() && value === value.trim() ? value : null
);

export const formatRecordedAmount = (value) => {
  if (typeof value !== 'string') return 'Unavailable';
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return 'Unavailable';
  const [, sign, whole, fraction] = match;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${sign}${grouped}${fraction === undefined ? '' : `.${fraction}`}`;
};

export const formatRecordedDate = (value) => (
  typeof value === 'string' ? value.slice(0, 10) : 'Unavailable'
);

const humanizeStatus = (value) => (
  typeof value === 'string' && value
    ? value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
    : 'Status unavailable'
);

function MetricCard({ label, value, description, icon: Icon }) {
  return (
    <article className="mep-interior-card min-w-0 rounded-2xl border border-white/10 bg-gradient-to-br from-slate-800/70 to-slate-900/90 p-5 shadow-lg shadow-slate-950/20 transition-colors hover:border-cyan-300/30 motion-reduce:transition-none">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-300">{label}</p>
          <p className="mt-2 break-words text-2xl font-semibold tracking-tight text-white">{value}</p>
          <p className="mt-2 text-xs leading-5 text-slate-400">{description}</p>
        </div>
        <span className="shrink-0 rounded-xl border border-cyan-300/15 bg-cyan-300/10 p-2.5 text-cyan-200">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
      </div>
    </article>
  );
}

function DashboardLink({ to, children, primary = false }) {
  return (
    <Link
      to={to}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 ${primary
        ? 'bg-cyan-300 text-slate-950 hover:bg-cyan-200'
        : 'border border-white/15 bg-slate-900/60 text-slate-100 hover:border-cyan-300/50 hover:text-cyan-100'}`}
    >
      {children}
    </Link>
  );
}

export function DashboardChallengeCards({ challenges }) {
  return <div className="space-y-3 p-4 md:hidden" aria-label="Latest recorded challenge cards">
    {challenges.map((challenge) => <article key={challenge.id} className="mep-interior-card mep-panel min-w-0 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <Link to={`/challenges/${challenge.id}`} className="min-w-0 break-words rounded font-semibold text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">{challenge.programName || 'Program name unavailable'}</Link>
        <span className="rounded-full border border-amber-300/25 bg-amber-300/10 px-2.5 py-1 text-xs text-amber-100">{humanizeStatus(challenge.status)}</span>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-400">Phase {challenge.phase === null ? 'unavailable' : challenge.phase}{challenge.totalPhases === null ? '' : ` of ${challenge.totalPhases}`} · {formatRecordedDate(challenge.createdAt)}</p>
      <dl className="mt-4 space-y-3 text-sm">
        <div><dt className="text-slate-400">Recorded balance</dt><dd className="mt-1 break-all font-mono tabular-nums text-slate-100">{formatRecordedAmount(challenge.currentBalance)}</dd><dd className="text-xs text-slate-400">Currency unavailable</dd></div>
        <div><dt className="text-slate-400">Recorded change</dt><dd className="mt-1 break-all font-mono tabular-nums text-slate-100">{formatRecordedAmount(challenge.profit)}</dd><dd className="text-xs text-slate-400">{humanizeStatus(challenge.profitDataStatus)}</dd></div>
        <div><dt className="text-slate-400">Progress</dt><dd className="mt-1 text-slate-300">Unavailable</dd><dd className="text-xs text-slate-400">{humanizeStatus(challenge.progressDataStatus)}</dd></div>
      </dl>
      <p className="mt-4 border-t border-white/10 pt-3 text-xs text-slate-400">{humanizeStatus(challenge.statusDataStatus)} · not a confirmation of live trading or funding.</p>
    </article>)}
  </div>;
}

export function DashboardReadState({ state, onRetry }) {
  if (state === 'loading') {
    return (
      <section className="mep-panel flex min-h-72 items-center justify-center rounded-2xl border" role="status" aria-live="polite" aria-busy="true">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-cyan-300/20 border-t-cyan-300 motion-reduce:animate-none" aria-hidden="true" />
          <p className="mt-4 text-sm text-slate-300">Loading your recorded account data…</p>
        </div>
      </section>
    );
  }

  if (state === 'error') {
    return (
      <section className="rounded-2xl border border-rose-300/30 bg-rose-950/30 p-5 text-rose-50" role="alert" aria-live="assertive">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-rose-200" aria-hidden="true" />
          <div>
            <h2 className="mep-heading font-semibold">Your dashboard could not be verified</h2>
            <p className="mt-1 text-sm leading-6 text-rose-100/85">
              No account records are shown until a complete response matches your signed-in account.
            </p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-4 inline-flex items-center gap-2 rounded-lg border border-rose-200/40 bg-rose-100/10 px-3 py-2 text-sm font-semibold text-rose-50 transition hover:bg-rose-100/20 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-200 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Retry dashboard
            </button>
          </div>
        </div>
      </section>
    );
  }

  return null;
}

export function DashboardOverview({ dashboard, onRefresh, refreshing = false, accountSetupService, purchaseClient = api }) {
  const { user, statistics, recentChallenges } = dashboard;
  const { statusCounts } = statistics;
  const hasRecords = statusCounts.total > 0;
  const recordedRatio = statistics.successRate === null ? 'Unavailable' : `${statistics.successRate}%`;
  const metrics = [
    {
      label: 'Recorded challenges',
      value: countLabel(statusCounts.total),
      description: 'Count from locally recorded challenge statuses.',
      icon: BookOpen,
    },
    {
      label: 'Active records',
      value: countLabel(statusCounts.active),
      description: 'Recorded status only; provider activity is not verified.',
      icon: BarChart3,
    },
    {
      label: 'Recorded outcome ratio',
      value: recordedRatio,
      description: `Based only on ${countLabel(statusCounts.passed)} passed and ${countLabel(statusCounts.failed)} failed recorded statuses.`,
      icon: FileText,
    },
    {
      label: 'Funded records',
      value: countLabel(statusCounts.funded),
      description: 'A recorded status, not a verified funding confirmation.',
      icon: UserRound,
    },
  ];

  return (
    <>
      <section className="mep-workspace-hero border-b border-cyan-300/15 bg-[radial-gradient(ellipse_at_top_left,_var(--tw-gradient-stops))] from-cyan-500/15 via-slate-950 to-slate-950">
        <div className="mx-auto max-w-7xl px-4 py-9 sm:px-6 lg:px-8 lg:py-11">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">Account records</p>
          <div className="mt-3 grid items-start gap-6 lg:grid-cols-[1.4fr_0.8fr] lg:gap-10">
            <div className="min-w-0">
              <h1 className="mep-heading break-words text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                {user.firstName ? `${user.firstName}’s challenge overview` : 'Challenge overview'}
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                Review the latest locally recorded challenge statuses for this account. This page does not verify provider activity or financial outcomes.
              </p>
              <div className="mt-6 flex flex-wrap gap-2">
                <DashboardLink to={hasRecords ? '/challenges' : '/programs'} primary>{hasRecords ? 'All challenges' : 'Explore programs'} <ArrowRight className="h-4 w-4" aria-hidden="true" /></DashboardLink>
                <DashboardLink to="/profile">Profile</DashboardLink>
                <DashboardLink to="/support/my-tickets">Support</DashboardLink>
              </div>
            </div>
            <aside className="mep-interior-card mep-panel min-w-0 rounded-2xl border p-5 shadow-[0_20px_60px_rgba(2,6,23,0.35)]" aria-label="Account workspace summary">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Your recorded workspace</p>
              <p className="mt-3 text-4xl font-semibold tabular-nums text-white">{countLabel(statusCounts.total)} <span className="text-sm font-normal text-slate-400">challenge records</span></p>
              <p className="mt-3 text-sm leading-6 text-slate-400">{hasRecords ? 'Open a record to inspect its recorded status and available details.' : 'No challenge records in this account summary. Start by reviewing the current catalog.'}</p>
              <nav className="mt-4 flex flex-wrap gap-2 border-t border-white/10 pt-4" aria-label="Workspace resources">
                <DashboardLink to="/programs">Programs</DashboardLink>
                <DashboardLink to="/documents">Documents</DashboardLink>
                {!hasRecords && <DashboardLink to="/challenges">All challenges</DashboardLink>}
              </nav>
            </aside>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8 lg:py-9">
        <section className="rounded-2xl border border-amber-300/25 bg-amber-300/10 p-4 text-amber-50" aria-label="Recorded data status">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="font-semibold">Recorded legacy status — not provider verified</p>
              <p className="mt-1 text-sm leading-6 text-amber-100/85">
                Balances and recorded changes are displayed without an authoritative currency. Financial totals and progress remain unavailable rather than inferred.
              </p>
            </div>
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
              className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-amber-100/35 bg-slate-950/20 px-3 py-2 text-sm font-semibold text-amber-50 transition hover:bg-slate-950/35 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
              {refreshing ? 'Refreshing records' : 'Refresh records'}
            </button>
          </div>
        </section>

        <section className="mt-6" aria-label="Recorded challenge metrics">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {metrics.map((metric) => <MetricCard key={metric.label} {...metric} />)}
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-400">
            Financial totals: unavailable. No verified financial provenance was returned by this challenge-summary source.
          </p>
        </section>

        <AccountSetupGuide
          owner={{ userId: dashboard.owner.userId, tenantId: dashboard.owner.tenantId, role: user.role }}
          dashboardCount={statusCounts.total}
          service={accountSetupService}
        />

        <div className="mt-7">
          <ProgramPurchaseRecords principal={{ id: dashboard.owner.userId, tenant_id: dashboard.owner.tenantId, role: user.role }} client={purchaseClient} />
        </div>

        <section className="mep-interior-card mep-panel mt-7 overflow-hidden rounded-2xl border shadow-xl shadow-slate-950/20" aria-labelledby="latest-records-heading">
          <div className="flex flex-col gap-3 border-b border-white/10 px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div>
              <h2 id="latest-records-heading" className="mep-heading text-xl font-semibold tracking-tight text-white">Latest recorded challenges</h2>
              <p className="mt-1 text-sm leading-6 text-slate-400">Up to five most recent records returned for your account.</p>
            </div>
            <span className="text-sm font-medium text-cyan-200">{recentChallenges.length} of 5 records</span>
          </div>

          {recentChallenges.length === 0 ? (
            <div className="px-5 py-12 text-center sm:px-6">
              <p className="font-medium text-slate-200">No recent challenge records were returned for this account.</p>
              <p className="mt-2 text-sm text-slate-400">You can review available programs or contact support if you expected a record here.</p>
            </div>
          ) : (
            <>
            <DashboardChallengeCards challenges={recentChallenges} />
            <div className="hidden overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300 md:block" tabIndex="0" aria-label="Latest recorded challenges table">
              <table className="w-full min-w-[920px] text-left text-sm">
                <caption className="sr-only">Latest recorded challenges for the signed-in account</caption>
                <thead className="bg-slate-950/45 text-xs uppercase tracking-[0.14em] text-slate-400">
                  <tr>
                    <th scope="col" className="px-5 py-3 font-medium sm:px-6">Challenge</th>
                    <th scope="col" className="px-5 py-3 font-medium">Recorded status</th>
                    <th scope="col" className="px-5 py-3 font-medium">Recorded balance</th>
                    <th scope="col" className="px-5 py-3 font-medium">Recorded change</th>
                    <th scope="col" className="px-5 py-3 font-medium">Progress</th>
                    <th scope="col" className="px-5 py-3 font-medium sm:px-6">Started</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {recentChallenges.map((challenge) => (
                    <tr key={challenge.id} className="align-top transition-colors hover:bg-white/[0.025] motion-reduce:transition-none">
                      <td className="min-w-[190px] px-5 py-4 sm:px-6">
                        <Link to={`/challenges/${challenge.id}`} className="break-words font-semibold text-cyan-200 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900">
                          {challenge.programName || 'Program name unavailable'}
                        </Link>
                        <p className="mt-1 text-xs leading-5 text-slate-400">Phase {challenge.phase === null ? 'unavailable' : challenge.phase}{challenge.totalPhases === null ? '' : ` of ${challenge.totalPhases}`}</p>
                      </td>
                      <td className="px-5 py-4">
                        <span className="inline-flex rounded-full border border-amber-300/25 bg-amber-300/10 px-2.5 py-1 text-xs font-semibold text-amber-100">
                          {humanizeStatus(challenge.status)}
                        </span>
                        <p className="mt-1 max-w-[180px] break-words text-xs text-slate-400">{humanizeStatus(challenge.statusDataStatus)}</p>
                      </td>
                      <td className="px-5 py-4">
                        <p className="break-all font-mono text-sm font-semibold tabular-nums text-slate-100">{formatRecordedAmount(challenge.currentBalance)}</p>
                        <p className="mt-1 text-xs leading-5 text-slate-400">Currency unavailable</p>
                      </td>
                      <td className="px-5 py-4">
                        <p className="break-all font-mono text-sm font-semibold tabular-nums text-slate-100">{formatRecordedAmount(challenge.profit)}</p>
                        <p className="mt-1 max-w-[180px] break-words text-xs leading-5 text-slate-400">{humanizeStatus(challenge.profitDataStatus)}</p>
                      </td>
                      <td className="px-5 py-4 text-slate-300">
                        <p>Unavailable</p>
                        <p className="mt-1 max-w-[180px] break-words text-xs leading-5 text-slate-400">{humanizeStatus(challenge.progressDataStatus)}</p>
                      </td>
                      <td className="whitespace-nowrap px-5 py-4 font-mono text-sm tabular-nums text-slate-300 sm:px-6">{formatRecordedDate(challenge.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </>
          )}
        </section>
      </main>
    </>
  );
}

export function UserDashboardData({
  userId,
  tenantId,
  role,
  apiClient = api,
  accountSetupService = configuredAccountSetupService,
}) {
  const [dashboard, setDashboard] = useState(null);
  const [state, setState] = useState('loading');
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;

    setDashboard(null);
    setState('loading');
    loadUserDashboard(apiClient, {
      signal: controller.signal,
      expectedOwner: { userId, tenantId },
      role,
    }).then((nextDashboard) => {
      if (!current) return;
      setDashboard(nextDashboard);
      setState('ready');
    }).catch((error) => {
      if (!current || isDashboardRequestCanceled(error)) return;
      setDashboard(null);
      setState('error');
    });

    return () => {
      current = false;
      controller.abort();
    };
  }, [apiClient, refreshVersion, role, tenantId, userId]);

  const refresh = () => {
    if (state === 'loading') return;
    // Clear the ready state before scheduling the next one-shot request so a
    // second click cannot leave concurrent requests or stale account data.
    setDashboard(null);
    setState('loading');
    setRefreshVersion((version) => version + 1);
  };

  if (state !== 'ready' || !dashboard) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <DashboardReadState state={state} onRetry={refresh} />
      </div>
    );
  }

  return <DashboardOverview dashboard={dashboard} onRefresh={refresh} refreshing={false} accountSetupService={accountSetupService} purchaseClient={apiClient} />;
}

export default function UserDashboard() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const rawUserId = useAuthStore((state) => state.user?.id);
  const rawTenantId = useAuthStore((state) => state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id);
  const rawRole = useAuthStore((state) => state.user?.role);
  const userId = positiveIntegerOrNull(rawUserId);
  const tenantId = positiveIntegerOrNull(rawTenantId);
  const role = strictRoleOrNull(rawRole);
  const identityKey = JSON.stringify([isAuthenticated, userId, tenantId, role]);

  if (!isAuthenticated || userId === null || tenantId === null || role === null) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <section className="rounded-2xl border border-rose-300/30 bg-rose-950/30 p-5 text-rose-50" role="alert">
          <h1 className="mep-heading font-semibold">Your account context is unavailable</h1>
          <p className="mt-1 text-sm leading-6 text-rose-100/85">Sign in again before viewing account records.</p>
        </section>
      </div>
    );
  }

  // A new auth/id/tenant/role context unmounts the old request and its data immediately.
  return <UserDashboardData
    key={identityKey}
    userId={userId}
    tenantId={tenantId}
    role={role}
    apiClient={api}
    accountSetupService={configuredAccountSetupService}
  />;
}
