import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle,
  Database,
  Filter,
  RefreshCw,
  Search,
  ShieldAlert,
  TrendingUp,
} from 'lucide-react';
import api from '../../services/api';
import { createAdminChallengeViewService } from '../../services/adminChallengeViewService';

const challengeViewService = createAdminChallengeViewService(api);
const PAGE_SIZE = 20;
const LEGACY_STATUSES = ['active', 'passed', 'failed', 'funded', 'pending'];

const displayText = (value) => (value === null || value === undefined || value === '' ? '—' : value);
const legacyDecimal = (value) => (value === null ? 'Unknown' : value);
const formatPhase = (challenge) => (
  challenge.currentPhase === null || challenge.totalPhases === null
    ? 'Unknown'
    : `${challenge.currentPhase} of ${challenge.totalPhases}`
);

const bindingCopy = (binding) => ({
  not_requested: 'Not requested for this read',
  single_unverified_legacy: 'One unverified legacy link',
  ambiguous: 'Ambiguous legacy links — no account selected',
  not_linked: 'No legacy link recorded',
}[binding] || 'Unknown binding');

export default function ChallengesManagement() {
  const [challenges, setChallenges] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const controllerRef = useRef(null);
  const requestIdRef = useRef(0);

  const fetchChallenges = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++requestIdRef.current;

    // Do not leave a prior page/filter visible while its replacement is loading.
    setLoading(true);
    setChallenges([]);
    setPagination(null);
    setError(null);

    try {
      const result = await challengeViewService.list({
        page: currentPage,
        perPage: PAGE_SIZE,
        status: statusFilter === 'all' ? undefined : statusFilter,
        includeMt5: true,
        signal: controller.signal,
      });
      if (controller.signal.aborted || requestId !== requestIdRef.current) return;
      setChallenges(result.challenges);
      setPagination(result.pagination);
    } catch (requestError) {
      if (controller.signal.aborted || requestId !== requestIdRef.current) return;
      setError(requestError?.message || 'The recorded challenge snapshots could not be loaded.');
    } finally {
      if (!controller.signal.aborted && requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [currentPage, statusFilter]);

  useEffect(() => {
    fetchChallenges();
    return () => controllerRef.current?.abort();
  }, [fetchChallenges]);

  const visibleChallenges = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) return challenges;
    return challenges.filter((challenge) => [
      String(challenge.id),
      challenge.user.name,
      challenge.user.email,
      challenge.program.name,
      challenge.legacyStatus,
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between mb-4">
            <div>
              <h1 className="text-4xl font-bold text-white mb-2">Challenge snapshots</h1>
              <p className="text-gray-400">
                Read-only legacy records in your server-authorized scope. They are not provider-verified trading outcomes.
              </p>
            </div>
            <button
              type="button"
              onClick={fetchChallenges}
              disabled={loading}
              className="flex w-fit items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-xl font-semibold hover:shadow-lg hover:shadow-cyan-500/50 disabled:opacity-60 disabled:cursor-not-allowed transition-all duration-300"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
              Manual refresh
            </button>
          </div>

          <div className="mb-6 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 flex gap-3">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
            <div className="text-sm text-amber-100">
              <p className="font-semibold">Unverified legacy data; provider authentication is false.</p>
              <p className="mt-1 text-amber-100/80">Balances are stored snapshot strings only. Unknown values remain unknown; no profit, eligibility, payment, or funding result is calculated here.</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <StatCard label="Server total recorded rows" value={serverTotal === undefined ? '—' : serverTotal} icon={<TrendingUp className="w-8 h-8 text-cyan-400" />} />
            <StatCard label="Active label on this page" value={pagination ? recordedCounts.active : '—'} icon={<Database className="w-8 h-8 text-sky-400" />} />
            <StatCard label="Passed label on this page" value={pagination ? recordedCounts.passed : '—'} icon={<CheckCircle className="w-8 h-8 text-cyan-400" />} />
            <StatCard label="Funded label on this page" value={pagination ? recordedCounts.funded : '—'} icon={<Database className="w-8 h-8 text-violet-400" />} />
          </div>
          <p className="-mt-3 mb-6 text-xs text-gray-500">Page counts are recorded legacy status labels, not verified outcomes.</p>

          <div className="flex flex-col md:flex-row gap-4">
            <label className="flex-1 relative">
              <span className="sr-only">Search labels on this page</span>
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 w-5 h-5" />
              <input
                type="search"
                placeholder="Search labels on this page (user, program, ID)..."
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="w-full pl-12 pr-4 py-3 bg-slate-800/50 border border-slate-700/50 rounded-xl text-white placeholder-gray-400 focus:outline-none focus:border-cyan-500/50 transition-colors"
              />
            </label>
            <label className="flex items-center gap-2">
              <Filter className="text-gray-400 w-5 h-5" />
              <span className="sr-only">Legacy status filter</span>
              <select
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value);
                  setCurrentPage(1);
                }}
                className="px-4 py-3 bg-slate-800/50 border border-slate-700/50 rounded-xl text-white focus:outline-none focus:border-cyan-500/50 transition-colors"
              >
                <option value="all">All recorded labels</option>
                {LEGACY_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
          </div>
          <p className="mt-2 text-xs text-gray-500">The status filter is server-side. Search only filters labels already returned for this page.</p>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-500/20 border border-red-500/30 rounded-xl flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-400" />
            <p className="text-red-200">{error}</p>
          </div>
        )}

        <div className="bg-slate-800/50 backdrop-blur-sm rounded-2xl border border-slate-700/50 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-700/30">
                <tr>
                  {['ID', 'User', 'Program', 'Recorded phase / status', 'Recorded balances', 'Recorded legacy MT5 snapshot', 'Created'].map((heading) => (
                    <th key={heading} className="px-5 py-4 text-left text-sm font-semibold text-gray-400">{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan="7" className="px-6 py-12 text-center text-gray-400">Loading recorded legacy snapshots…</td></tr>
                ) : error ? (
                  <tr><td colSpan="7" className="px-6 py-12 text-center text-red-200">Recorded snapshots are unavailable. Use manual refresh to retry.</td></tr>
                ) : visibleChallenges.length === 0 ? (
                  <tr><td colSpan="7" className="px-6 py-12 text-center text-gray-400">No recorded snapshots match this page and local search.</td></tr>
                ) : visibleChallenges.map((challenge) => (
                  <tr key={challenge.id} className="border-b border-slate-700/30 align-top hover:bg-slate-700/20 transition-colors">
                    <td className="px-5 py-4"><span className="text-cyan-300 font-mono">#{challenge.id}</span></td>
                    <td className="px-5 py-4"><div className="flex flex-col"><span className="text-white font-medium">{challenge.user.name}</span><span className="text-sm text-gray-400">{challenge.user.email}</span></div></td>
                    <td className="px-5 py-4 text-gray-300">{challenge.program.name}</td>
                    <td className="px-5 py-4"><div className="flex flex-col gap-1"><span className="text-gray-200">Phase: {formatPhase(challenge)}</span><span className="w-fit rounded border border-slate-600 bg-slate-700/60 px-2 py-0.5 text-xs text-gray-300">Recorded: {challenge.legacyStatus}</span><span className="text-xs text-gray-500">Payment label: {displayText(challenge.legacyPaymentStatus)}</span></div></td>
                    <td className="px-5 py-4"><SnapshotBalances title="Challenge" balance={challenge.currentBalance} initialBalance={challenge.initialBalance} drawdown={challenge.maxDrawdownObserved} /></td>
                    <td className="px-5 py-4"><Mt5Snapshot challenge={challenge} /></td>
                    <td className="px-5 py-4 text-sm text-gray-400 font-mono whitespace-nowrap">{displayText(challenge.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!loading && pagination && (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between px-6 py-4 border-t border-slate-700/50">
              <p className="text-gray-400 text-sm">Server page {pagination.page} of {totalPages}; {pagination.total} recorded rows in this scoped result.</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => setCurrentPage((page) => Math.max(1, page - 1))} disabled={currentPage === 1} className="px-4 py-2 bg-slate-700/50 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">Previous</button>
                <button type="button" onClick={() => setCurrentPage((page) => Math.min(1000, totalPages, page + 1))} disabled={totalPages === 0 || currentPage >= totalPages || currentPage >= 1000} className="px-4 py-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-lg hover:shadow-lg hover:shadow-cyan-500/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300">Next</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon }) {
  return <div className="bg-slate-800/50 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-4"><div className="flex items-center justify-between gap-3"><div><p className="text-gray-400 text-sm">{label}</p><p className="text-2xl font-bold text-white">{value}</p></div>{icon}</div></div>;
}

function SnapshotBalances({ title, balance, initialBalance, drawdown }) {
  return <div className="flex min-w-44 flex-col gap-1 text-sm"><span className="text-gray-500">{title} raw snapshots</span><span className="font-mono text-gray-100">Balance: {legacyDecimal(balance)}</span><span className="font-mono text-gray-400">Initial: {legacyDecimal(initialBalance)}</span><span className="font-mono text-gray-400">Max DD observed: {legacyDecimal(drawdown)}</span></div>;
}

function Mt5Snapshot({ challenge }) {
  if (challenge.mt5AccountBinding !== 'single_unverified_legacy') {
    return <div className="max-w-56 text-sm text-gray-500">{bindingCopy(challenge.mt5AccountBinding)}</div>;
  }
  const account = challenge.mt5Account;
  return <div className="flex min-w-48 flex-col gap-1 text-sm"><span className="text-cyan-300 font-mono">Login: {account.login}</span><span className="text-gray-400">{displayText(account.server)} · {displayText(account.group)}</span><span className="text-xs text-gray-500">Recorded MT5 label: {displayText(account.status)}</span><span className="font-mono text-gray-200">Balance: {legacyDecimal(account.balance)}</span><span className="font-mono text-gray-400">Equity: {legacyDecimal(account.equity)} · Margin: {legacyDecimal(account.margin)}</span><span className="text-xs text-amber-200/80">Unverified legacy snapshot; provider authentication false.</span></div>;
}
