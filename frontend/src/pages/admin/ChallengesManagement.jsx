import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle,
  ChevronRight,
  Database,
  Eye,
  Filter,
  RefreshCw,
  Search,
  ShieldAlert,
  TrendingUp,
  X,
} from 'lucide-react';
import useAuthStore from '../../store/authStore';
import {
  ADMIN_CLOSURE_CHALLENGE_PAGE_SIZE,
  adminClosureChallengesError,
  adminClosureChallengesPrincipalFromAuth,
  createAdminClosureChallengesService,
  isAdminClosureChallengeRequestCanceled,
} from '../../services/adminClosureChallengesService';
import { useDialogFocus } from '../../hooks/useDialogFocus.js';

const challengeService = createAdminClosureChallengesService();
const LEGACY_STATUSES = ['active', 'passed', 'failed', 'funded', 'pending'];

const displayText = (value) => (value === null || value === undefined || value === '' ? 'Unknown' : value);
const legacyDecimal = (value) => (value === null ? 'Unknown' : value);
const formatPhase = (challenge) => (
  challenge.currentPhase === null || challenge.totalPhases === null
    ? 'Unknown'
    : `${challenge.currentPhase} of ${challenge.totalPhases}`
);
const bindingCopy = (binding) => ({
  not_requested: 'Not requested for this read',
  single_unverified_legacy: 'One recorded legacy link',
  ambiguous: 'Ambiguous legacy links — no account selected',
  not_linked: 'No legacy link recorded',
}[binding] || 'Unknown binding');

export default function ChallengesManagement() {
  const { user, isAuthenticated, isLoading } = useAuthStore();
  const principal = useMemo(
    () => (isLoading ? null : adminClosureChallengesPrincipalFromAuth(user, isAuthenticated)),
    [isAuthenticated, isLoading, user],
  );
  return <ChallengesManagementContent principal={principal} authLoading={isLoading} />;
}

export function ChallengesManagementContent({ principal, authLoading = false }) {
  const [challenges, setChallenges] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const listControllerRef = useRef(null);
  const detailControllerRef = useRef(null);
  const requestIdRef = useRef(0);
  const detailRequestIdRef = useRef(0);

  const clearDetail = useCallback(() => {
    detailControllerRef.current?.abort();
    detailRequestIdRef.current += 1;
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
  }, []);

  const fetchChallenges = useCallback(async () => {
    listControllerRef.current?.abort();
    const requestId = ++requestIdRef.current;
    clearDetail();
    setChallenges([]);
    setPagination(null);
    setError(null);

    if (!principal) {
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    listControllerRef.current = controller;
    setLoading(true);
    try {
      const result = await challengeService.list({
        expectedOwner: principal.owner,
        role: principal.role,
        page: currentPage,
        perPage: ADMIN_CLOSURE_CHALLENGE_PAGE_SIZE,
        status: statusFilter === 'all' ? null : statusFilter,
        includeMt5: true,
        signal: controller.signal,
      });
      if (controller.signal.aborted || requestId !== requestIdRef.current) return;
      setChallenges(result.challenges);
      setPagination(result.pagination);
    } catch (requestError) {
      if (controller.signal.aborted || requestId !== requestIdRef.current || isAdminClosureChallengeRequestCanceled(requestError)) return;
      setError(adminClosureChallengesError());
    } finally {
      if (!controller.signal.aborted && requestId === requestIdRef.current) setLoading(false);
    }
  }, [clearDetail, currentPage, principal, statusFilter]);

  useEffect(() => {
    fetchChallenges();
    return () => {
      listControllerRef.current?.abort();
      detailControllerRef.current?.abort();
      requestIdRef.current += 1;
      detailRequestIdRef.current += 1;
    };
  }, [fetchChallenges]);

  const openDetail = useCallback(async (challengeId) => {
    if (!principal) return;
    detailControllerRef.current?.abort();
    const requestId = ++detailRequestIdRef.current;
    const controller = new AbortController();
    detailControllerRef.current = controller;
    setSelectedId(challengeId);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const result = await challengeService.detail(challengeId, {
        expectedOwner: principal.owner,
        role: principal.role,
        includeMt5: true,
        signal: controller.signal,
      });
      if (controller.signal.aborted || requestId !== detailRequestIdRef.current) return;
      setDetail(result.challenge);
    } catch (requestError) {
      if (controller.signal.aborted || requestId !== detailRequestIdRef.current || isAdminClosureChallengeRequestCanceled(requestError)) return;
      setDetailError(adminClosureChallengesError());
    } finally {
      if (!controller.signal.aborted && requestId === detailRequestIdRef.current) setDetailLoading(false);
    }
  }, [principal]);

  const visibleChallenges = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) return challenges;
    return challenges.filter((challenge) => [
      String(challenge.id),
      challenge.user.name || '',
      challenge.user.email || '',
      challenge.program.name || '',
      challenge.legacyStatus || '',
      challenge.legacyPaymentStatus || '',
    ].some((label) => label.toLowerCase().includes(term)));
  }, [challenges, searchTerm]);

  const recordedCounts = useMemo(() => Object.fromEntries(
    ['active', 'passed', 'funded'].map((status) => [
      status,
      challenges.filter((challenge) => challenge.legacyStatus === status).length,
    ]),
  ), [challenges]);

  const totalPages = pagination?.pages ?? 0;
  const serverTotal = pagination?.total;
  const unavailableMessage = authLoading
    ? 'Checking the active administrator session…'
    : 'Challenge records are unavailable for this account identity or role.';

  return (
    <div className="min-h-full bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-4 sm:p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-8">
          <div className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h1 className="mep-heading mb-2 text-3xl font-bold text-white sm:text-4xl">Challenge snapshots</h1>
              <p className="max-w-3xl text-gray-400">
                Scoped recorded legacy data for administration. It is not provider-verified trading, funding, payment, or entitlement evidence.
              </p>
            </div>
            <button
              type="button"
              onClick={fetchChallenges}
              disabled={!principal || loading}
              className="mep-primary flex w-fit items-center gap-2 px-4 py-2 font-semibold transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
              Manual refresh
            </button>
          </div>

          <div className="mb-6 flex gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4" role="note">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
            <div className="text-sm text-amber-100">
              <p className="font-semibold">This view is marked as unverified legacy data; the response reports provider authentication as false.</p>
              <p className="mt-1 text-amber-100/80">Recorded balances stay exact strings or Unknown. No account creation, funding, reset, capital command, payment-derived entitlement, or status outcome can be performed here.</p>
            </div>
          </div>

          <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
            <StatCard label="Server total recorded rows" value={serverTotal === undefined ? '—' : serverTotal} icon={<TrendingUp className="h-8 w-8 text-cyan-400" />} />
            <StatCard label="Active label on this page" value={pagination ? recordedCounts.active : '—'} icon={<Database className="h-8 w-8 text-sky-400" />} />
            <StatCard label="Passed label on this page" value={pagination ? recordedCounts.passed : '—'} icon={<CheckCircle className="h-8 w-8 text-cyan-400" />} />
            <StatCard label="Funded label on this page" value={pagination ? recordedCounts.funded : '—'} icon={<Database className="h-8 w-8 text-violet-400" />} />
          </div>
          <p className="-mt-3 mb-6 text-xs text-gray-500">Page counts are recorded legacy status labels, not verified outcomes.</p>

          <div className="flex flex-col gap-4 md:flex-row">
            <label className="relative flex-1">
              <span className="sr-only">Search labels on this page</span>
              <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" aria-hidden="true" />
              <input
                type="search"
                placeholder="Search labels on this page (user, program, ID)…"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="w-full rounded-xl border border-slate-700/50 bg-slate-800/50 py-3 pl-12 pr-4 text-white placeholder-gray-400 transition-colors focus:border-cyan-500/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              />
            </label>
            <label className="flex items-center gap-2">
              <Filter className="h-5 w-5 text-gray-400" aria-hidden="true" />
              <span className="sr-only">Recorded status filter</span>
              <select
                value={statusFilter}
                disabled={!principal || loading}
                onChange={(event) => {
                  setStatusFilter(event.target.value);
                  setCurrentPage(1);
                }}
                className="rounded-xl border border-slate-700/50 bg-slate-800/50 px-4 py-3 text-white transition-colors focus:border-cyan-500/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <option value="all">All recorded labels</option>
                {LEGACY_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
          </div>
          <p className="mt-2 text-xs text-gray-500">The status filter is server-side. Search only filters labels already returned for this page.</p>
        </div>

        {!principal && (
          <div className="mep-panel mb-6 flex gap-3 rounded-xl border p-4 text-slate-200" role="status" aria-live="polite">
            <ShieldAlert className="h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
            <p>{unavailableMessage}</p>
          </div>
        )}
        {error && (
          <div className="mb-6 flex gap-3 rounded-xl border border-red-500/30 bg-red-500/20 p-4" role="alert">
            <AlertCircle className="h-5 w-5 shrink-0 text-red-400" aria-hidden="true" />
            <p className="text-red-100">{error}</p>
          </div>
        )}

        <div className="mep-panel overflow-hidden rounded-2xl border backdrop-blur-sm">
          <div className="overflow-x-auto">
            <table className="min-w-[1050px] w-full">
              <thead className="bg-slate-700/30">
                <tr>
                  {['ID', 'User', 'Program', 'Recorded phase / status', 'Recorded balances', 'Recorded legacy MT5 snapshot', 'Detail'].map((heading) => (
                    <th key={heading} scope="col" className="px-5 py-4 text-left text-sm font-semibold text-gray-400">{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan="7" className="px-6 py-12 text-center text-gray-400" role="status">Loading recorded legacy snapshots…</td></tr>
                ) : !principal ? (
                  <tr><td colSpan="7" className="px-6 py-12 text-center text-gray-400">No scoped administrator identity is available.</td></tr>
                ) : error ? (
                  <tr><td colSpan="7" className="px-6 py-12 text-center text-red-200">Recorded snapshots are unavailable. Use manual refresh to retry.</td></tr>
                ) : visibleChallenges.length === 0 ? (
                  <tr><td colSpan="7" className="px-6 py-12 text-center text-gray-400">No recorded snapshots match this page and local search.</td></tr>
                ) : visibleChallenges.map((challenge) => (
                  <tr key={challenge.id} className="align-top border-b border-slate-700/30 transition-colors hover:bg-slate-700/20">
                    <td className="px-5 py-4"><span className="font-mono text-cyan-300">#{challenge.id}</span></td>
                    <td className="max-w-56 break-words px-5 py-4"><div className="flex flex-col"><span className="font-medium text-white">{displayText(challenge.user.name)}</span><span className="text-sm text-gray-400">{displayText(challenge.user.email)}</span></div></td>
                    <td className="max-w-52 break-words px-5 py-4 text-gray-300">{displayText(challenge.program.name)}</td>
                    <td className="px-5 py-4"><div className="flex flex-col gap-1"><span className="text-gray-200">Phase: {formatPhase(challenge)}</span><span className="w-fit rounded border border-slate-600 bg-slate-700/60 px-2 py-0.5 text-xs text-gray-300">Recorded: {displayText(challenge.legacyStatus)}</span><span className="text-xs text-gray-500">Payment label: {displayText(challenge.legacyPaymentStatus)}</span></div></td>
                    <td className="px-5 py-4"><SnapshotBalances title="Challenge" balance={challenge.currentBalance} initialBalance={challenge.initialBalance} drawdown={challenge.maxDrawdownObserved} /></td>
                    <td className="px-5 py-4"><Mt5Snapshot challenge={challenge} /></td>
                    <td className="px-5 py-4"><button type="button" onClick={() => openDetail(challenge.id)} className="mep-primary inline-flex items-center gap-2 border border-cyan-500/40 px-3 py-2 text-sm font-semibold text-cyan-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"><Eye className="h-4 w-4" aria-hidden="true" />View detail<ChevronRight className="h-4 w-4" aria-hidden="true" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!loading && principal && pagination && (totalPages > 0 ? (
            <div className="flex flex-col gap-3 border-t border-slate-700/50 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-gray-400">Server page {pagination.page} of {totalPages}; {pagination.total} recorded rows in this scoped result.</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => setCurrentPage((page) => Math.max(1, page - 1))} disabled={loading || currentPage === 1} className="rounded-lg bg-slate-700/50 px-4 py-2 text-white transition-colors hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">Previous</button>
                <button type="button" onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))} disabled={loading || totalPages === 0 || currentPage >= totalPages} className="mep-primary px-4 py-2 transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 disabled:cursor-not-allowed disabled:opacity-50">Next</button>
              </div>
            </div>
          ) : <p className="border-t border-slate-700/50 px-6 py-4 text-sm text-gray-400" role="status">No server pages are available for this scoped result.</p>)}
        </div>
      </div>

      {selectedId !== null && (
        <ChallengeDetailPanel
          challenge={detail}
          loading={detailLoading}
          error={detailError}
          onClose={clearDetail}
          onRetry={() => openDetail(selectedId)}
          selectedId={selectedId}
        />
      )}
    </div>
  );
}

function StatCard({ label, value, icon }) {
  return <div className="mep-panel rounded-2xl border p-4 backdrop-blur-sm"><div className="flex items-center justify-between gap-3"><div><p className="text-sm text-gray-400">{label}</p><p className="text-2xl font-bold text-white">{value}</p></div>{icon}</div></div>;
}

function SnapshotBalances({ title, balance, initialBalance, drawdown }) {
  return <div className="flex min-w-44 flex-col gap-1 text-sm"><span className="text-gray-500">{title} raw snapshots</span><span className="font-mono text-gray-100">Balance: {legacyDecimal(balance)}</span><span className="font-mono text-gray-400">Initial: {legacyDecimal(initialBalance)}</span><span className="font-mono text-gray-400">Max DD observed: {legacyDecimal(drawdown)}</span></div>;
}

function Mt5Snapshot({ challenge }) {
  if (challenge.mt5AccountBinding !== 'single_unverified_legacy') {
    return <div className="max-w-56 text-sm text-gray-500">{bindingCopy(challenge.mt5AccountBinding)}</div>;
  }
  const account = challenge.mt5Account;
  return <div className="flex min-w-48 flex-col gap-1 text-sm"><span className="font-mono text-cyan-300">Login: {displayText(account.login)}</span><span className="text-gray-400">{displayText(account.server)} · {displayText(account.group)}</span><span className="text-xs text-gray-500">Recorded MT5 label: {displayText(account.status)}</span><span className="font-mono text-gray-200">Balance: {legacyDecimal(account.balance)}</span><span className="font-mono text-gray-400">Equity: {legacyDecimal(account.equity)} · Margin: {legacyDecimal(account.margin)}</span><span className="text-xs text-amber-200/80">Unverified legacy snapshot; provider authentication false.</span></div>;
}

function ChallengeDetailPanel({ challenge, loading, error, onClose, onRetry, selectedId }) {
  const dialogRef = useDialogFocus({ open: true, onClose });
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/70 p-0 backdrop-blur-sm" role="presentation">
      <section ref={dialogRef} className="h-full w-full max-w-2xl overflow-y-auto border-l border-slate-700 bg-slate-900 p-5 shadow-2xl sm:p-7" role="dialog" aria-modal="true" aria-labelledby="challenge-detail-title">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div><p className="text-sm font-semibold uppercase tracking-wide text-cyan-300">Recorded snapshot</p><h2 id="challenge-detail-title" className="mep-heading mt-1 text-2xl font-bold text-white">Challenge #{selectedId} detail</h2></div>
          <button type="button" onClick={onClose} data-autofocus className="rounded-lg p-2 text-slate-300 transition-colors hover:bg-slate-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300" aria-label="Close challenge detail"><X className="h-5 w-5" aria-hidden="true" /></button>
        </div>
        <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100"><strong>Read-only boundary.</strong> This detail does not establish a provider account, a funded result, a payment entitlement, or an evaluative outcome.</div>
        {loading && <p className="rounded-xl border border-slate-700 bg-slate-800/60 p-5 text-gray-300" role="status">Loading the current scoped recorded snapshot…</p>}
        {error && <div className="rounded-xl border border-red-500/30 bg-red-500/20 p-5 text-red-100" role="alert"><p>{error}</p><button type="button" onClick={onRetry} className="mt-4 rounded-lg border border-red-200/40 px-3 py-2 text-sm font-semibold text-red-50 transition-colors hover:bg-red-100/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"><RefreshCw className="mr-2 inline h-4 w-4" aria-hidden="true" />Retry detail</button></div>}
        {challenge && (
          <div className="space-y-5">
            <DetailGroup title="Owner and program"><DetailRow label="Recorded user" value={`${displayText(challenge.user.name)} · ${displayText(challenge.user.email)}`} /><DetailRow label="Program" value={displayText(challenge.program.name)} /><DetailRow label="Recorded status" value={displayText(challenge.legacyStatus)} /><DetailRow label="Recorded payment label" value={displayText(challenge.legacyPaymentStatus)} /></DetailGroup>
            <DetailGroup title="Recorded challenge values"><DetailRow label="Phase" value={formatPhase(challenge)} mono /><DetailRow label="Initial balance" value={legacyDecimal(challenge.initialBalance)} mono /><DetailRow label="Current balance" value={legacyDecimal(challenge.currentBalance)} mono /><DetailRow label="Maximum drawdown observed" value={legacyDecimal(challenge.maxDrawdownObserved)} mono /><DetailRow label="Created" value={displayText(challenge.createdAt)} mono /><DetailRow label="Started" value={displayText(challenge.startDate)} mono /><DetailRow label="Passed" value={displayText(challenge.passedAt)} mono /></DetailGroup>
            <DetailGroup title="Recorded MT5 metadata"><DetailRow label="Binding" value={bindingCopy(challenge.mt5AccountBinding)} />{challenge.mt5Account && <><DetailRow label="Login" value={displayText(challenge.mt5Account.login)} mono /><DetailRow label="Server / group" value={`${displayText(challenge.mt5Account.server)} · ${displayText(challenge.mt5Account.group)}`} /><DetailRow label="Balance / equity" value={`${legacyDecimal(challenge.mt5Account.balance)} · ${legacyDecimal(challenge.mt5Account.equity)}`} mono /><DetailRow label="Snapshot updated" value={displayText(challenge.mt5Account.updatedAt)} mono /></>}</DetailGroup>
            <DetailGroup title="Supported actions"><p className="text-sm leading-6 text-slate-300">This screen supports scoped refresh, filter, pagination, and recorded-detail reads. Provider or settlement commands remain unavailable because there is no authoritative operation behind these legacy records.</p></DetailGroup>
          </div>
        )}
      </section>
    </div>
  );
}

function DetailGroup({ title, children }) {
  return <section className="mep-panel rounded-xl border p-4"><h3 className="mb-3 font-semibold text-cyan-200">{title}</h3><dl className="space-y-3">{children}</dl></section>;
}
function DetailRow({ label, value, mono = false }) {
  return <div className="grid gap-1 sm:grid-cols-[11rem_1fr]"><dt className="text-sm text-slate-400">{label}</dt><dd className={`break-words text-sm text-slate-100 ${mono ? 'font-mono' : ''}`}>{value}</dd></div>;
}
