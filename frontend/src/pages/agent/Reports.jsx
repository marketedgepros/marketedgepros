import { useEffect, useState } from 'react';
import { BarChart3, DollarSign, MousePointerClick, Users } from 'lucide-react';
import { affiliateViewError, loadAffiliateDashboard } from '../../services/affiliateViewService';

const formatCurrency = (value) => (
  Number.isFinite(value)
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
    : '—'
);

const formatNumber = (value) => (Number.isFinite(value) ? new Intl.NumberFormat('en-US').format(value) : '—');
const formatPercent = (value) => (Number.isFinite(value) ? `${value.toFixed(2)}%` : '—');
const formatDate = (value) => (value ? new Date(value).toLocaleDateString() : '—');

const statusClass = (status) => ({
  converted: 'bg-green-100 text-green-800',
  pending: 'bg-yellow-100 text-yellow-800',
  cancelled: 'bg-red-100 text-red-800',
}[status] || 'bg-slate-700/50 text-gray-100');

export default function Reports() {
  const [dashboard, setDashboard] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let isCurrent = true;

    const loadReport = async () => {
      try {
        setIsLoading(true);
        setLoadError(null);
        const data = await loadAffiliateDashboard();
        if (isCurrent) setDashboard(data);
      } catch (error) {
        if (isCurrent) {
          setDashboard(null);
          setLoadError(affiliateViewError(error));
        }
      } finally {
        if (isCurrent) setIsLoading(false);
      }
    };

    loadReport();
    return () => {
      isCurrent = false;
    };
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
          <p className="text-gray-300 mt-4">Loading account reporting...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900">
      <div className="bg-slate-800/50 border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-white">Reports &amp; Analytics</h1>
          <p className="text-gray-300 mt-2">Current aggregate activity for your affiliate account.</p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {loadError ? (
          <div role="alert" className="rounded-lg border border-red-500/50 bg-red-950/40 p-4 text-red-100">
            <p className="font-semibold">Reporting is unavailable</p>
            <p className="mt-1 text-sm">{loadError}</p>
          </div>
        ) : (
          <>
            <div className="mb-8">
              <h2 className="text-xl font-bold text-white mb-4">Current Account Overview</h2>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                <MetricCard label="Referral Clicks" value={formatNumber(dashboard?.stats.totalClicks)} icon={<MousePointerClick className="w-6 h-6 text-blue-600" />} />
                <MetricCard label="Conversions" value={formatNumber(dashboard?.stats.totalConversions)} icon={<Users className="w-6 h-6 text-green-600" />} />
                <MetricCard label="Conversion Rate" value={formatPercent(dashboard?.stats.conversionRate)} icon={<BarChart3 className="w-6 h-6 text-purple-600" />} />
                <MetricCard label="Tracked Commission" value={formatCurrency(dashboard?.stats.totalCommission)} icon={<DollarSign className="w-6 h-6 text-green-600" />} />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
              <div className="card">
                <p className="text-sm text-gray-300">Tracked Revenue</p>
                <p className="text-3xl font-bold text-white mt-2">{formatCurrency(dashboard?.stats.totalRevenue)}</p>
                <p className="mt-2 text-sm text-gray-400">Aggregate currently exposed for this account.</p>
              </div>
              <div className="card">
                <p className="text-sm text-gray-300">Pending Commission</p>
                <p className="text-3xl font-bold text-white mt-2">{formatCurrency(dashboard?.stats.pendingCommission)}</p>
                <p className="mt-2 text-sm text-gray-400">Approved: {formatCurrency(dashboard?.stats.approvedCommission)} · Paid: {formatCurrency(dashboard?.stats.paidCommission)}</p>
              </div>
            </div>

            <div className="mb-8 rounded-lg border border-white/10 bg-slate-800/50 p-4 text-gray-300">
              <p className="font-medium text-white">Unavailable in the current account API</p>
              <p className="mt-1 text-sm">Period comparisons, trader-performance rankings, and downloadable reports are not exposed for this account, so they are not shown here.</p>
            </div>

            <div>
              <h2 className="text-xl font-bold text-white mb-4">Recent Referral Activity</h2>
              <div className="bg-slate-800/50 rounded-lg shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-slate-900 border-b border-white/10">
                      <tr>
                        {['Referred Trader', 'Status', 'Clicked', 'Converted', 'Recorded Commission'].map((heading) => (
                          <th key={heading} className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">{heading}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="bg-slate-800/50 divide-y divide-white/10">
                      {dashboard?.recentReferrals.map((referral) => (
                        <tr key={referral.id} className="hover:bg-slate-900">
                          <td className="px-6 py-4 whitespace-nowrap">
                            <p className="text-sm font-medium text-white">{referral.name || '—'}</p>
                            <p className="text-sm text-gray-400">{referral.email || '—'}</p>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap"><span className={`px-2 py-1 rounded-full text-xs font-medium ${statusClass(referral.status)}`}>{referral.status || '—'}</span></td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{formatDate(referral.clickDate)}</td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{formatDate(referral.conversionDate)}</td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm font-bold text-white">{formatCurrency(referral.commissionAmount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {dashboard?.recentReferrals.length === 0 && <div className="text-center py-12 text-gray-300">No recent referral activity is available.</div>}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, icon }) {
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-300">{label}</p>
          <p className="text-2xl font-bold text-white mt-1">{value}</p>
        </div>
        <div className="w-12 h-12 bg-slate-900 rounded-lg flex items-center justify-center">{icon}</div>
      </div>
    </div>
  );
}
