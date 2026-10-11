import { useEffect, useState } from 'react';
import { TrendingUp, DollarSign, Trophy, Clock } from 'lucide-react';
import StatsCard from '../../components/common/StatsCard';
import {
  isDashboardRequestCanceled,
  loadUserDashboard,
} from '../../services/userDashboardViewService';

const countLabel = (value) => (value === null ? '—' : String(value));

const formatRecordedAmount = (value) => {
  if (typeof value !== 'string') return 'Not recorded';
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return 'Not recorded';
  const [, sign, whole, fraction] = match;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${sign}$${grouped}${fraction === undefined ? '' : `.${fraction}`}`;
};

const formatRecordedDate = (value) => {
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) return 'Not recorded';
  return new Date(value).toLocaleDateString();
};

const statusClass = (status) => {
  switch (status?.toLowerCase()) {
    case 'active': return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200';
    case 'passed': return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
    case 'failed': return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
    case 'funded': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
    case 'pending': return 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200';
    default: return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200';
  }
};

const statusLabel = (status) => (typeof status === 'string' ? status.toUpperCase() : 'NOT RECORDED');

export default function UserDashboard() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dashboardData, setDashboardData] = useState(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const fetchDashboard = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await loadUserDashboard(undefined, { signal: controller.signal });
        if (!disposed) setDashboardData(data);
      } catch (requestError) {
        if (!disposed && !isDashboardRequestCanceled(requestError)) {
          setError('Unable to load your dashboard. Please try again.');
        }
      } finally {
        if (!disposed) setLoading(false);
      }
    };

    fetchDashboard();
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [requestVersion]);

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]" aria-label="Loading dashboard">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mb-4" role="alert">
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded dark:bg-red-950 dark:text-red-200">
          <span>{error}</span>
          <button
            type="button"
            className="ml-4 underline font-semibold"
            onClick={() => setRequestVersion((version) => version + 1)}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!dashboardData) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <p className="text-center text-gray-600 dark:text-gray-400 py-8">
          Dashboard data is not available yet.
        </p>
      </div>
    );
  }

  const { user, statistics, recentChallenges } = dashboardData;
  const { statusCounts } = statistics;
  const userStats = [
    {
      title: 'Active Challenges',
      value: countLabel(statusCounts.active),
      subtitle: 'Recorded status count',
      icon: Clock,
      color: 'primary',
    },
    {
      title: 'Total Profit',
      value: 'Unavailable',
      subtitle: 'Verified provenance unavailable',
      icon: DollarSign,
      color: 'success',
    },
    {
      title: 'Success Rate',
      value: statistics.successRate === null ? 'Unavailable' : `${statistics.successRate}%`,
      subtitle: `Recorded: ${countLabel(statusCounts.passed)} passed / ${countLabel(statusCounts.failed)} failed`,
      icon: TrendingUp,
      color: 'info',
    },
    {
      title: 'Funded Accounts',
      value: countLabel(statusCounts.funded),
      subtitle: 'Recorded status count',
      icon: Trophy,
      color: 'warning',
    },
  ];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          Welcome back, {user.firstName || 'Trader'}
        </h1>
        <p className="text-gray-600 dark:text-gray-400">Here&apos;s your trading overview</p>
      </div>

      <div className="mb-6 rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-900 dark:border-cyan-900 dark:bg-cyan-950 dark:text-cyan-100">
        Statuses and balances are <strong>locally recorded legacy data</strong>; provider verification is not available.
        Financial totals and targets remain unavailable rather than inferred.
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
        {userStats.map((stat) => <StatsCard key={stat.title} {...stat} />)}
      </div>

      <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">Recent Challenges</h2>

      {recentChallenges.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
          <p className="text-center text-gray-600 dark:text-gray-400 py-8">
            No recorded challenges are available yet.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {recentChallenges.map((challenge, index) => (
            <div key={`${challenge.id ?? 'record'}-${index}`} className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex justify-between items-center mb-4 gap-3">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  {challenge.programName || 'Program not recorded'}
                </h3>
                <span className={`px-3 py-1 text-xs font-semibold rounded-full ${statusClass(challenge.status)}`}>
                  {statusLabel(challenge.status)}
                </span>
              </div>

              <div className="mb-4 rounded bg-gray-50 dark:bg-gray-700 px-3 py-2">
                <div className="flex justify-between gap-4">
                  <span className="text-sm text-gray-600 dark:text-gray-300">Progress</span>
                  <span className="text-sm font-semibold text-gray-900 dark:text-white">Target unavailable</span>
                </div>
              </div>

              <p className="mb-4 text-xs text-gray-500 dark:text-gray-400">
                Balances and profit are recorded values, not provider-verified.
              </p>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Current Balance</p>
                  <p className="text-lg font-semibold text-cyan-700 dark:text-cyan-300">
                    {formatRecordedAmount(challenge.currentBalance)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Recorded Profit/Loss</p>
                  <p className={`text-lg font-semibold ${challenge.profit?.startsWith('-') ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
                    {formatRecordedAmount(challenge.profit)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Phase</p>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    {challenge.phase === null ? 'Not recorded' : `${challenge.phase}${challenge.totalPhases === null ? '' : ` of ${challenge.totalPhases}`}`}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Started</p>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">
                    {formatRecordedDate(challenge.createdAt)}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
