import { useEffect, useMemo, useState } from 'react';
import { CheckCircle, Clock, DollarSign, Download } from 'lucide-react';
import {
  affiliateViewError,
  loadAffiliateCommissions,
  loadAffiliateDashboard,
} from '../../services/affiliateViewService';

const formatCurrency = (value) => (
  Number.isFinite(value)
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
    : '—'
);

const formatDate = (value) => (value ? new Date(value).toLocaleDateString() : '—');

const statusClass = (status) => ({
  paid: 'bg-green-100 text-green-800',
  approved: 'bg-blue-100 text-blue-800',
  pending: 'bg-yellow-100 text-yellow-800',
  cancelled: 'bg-red-100 text-red-800',
}[status] || 'bg-slate-700/50 text-gray-100');

export default function Commissions() {
  const [commissions, setCommissions] = useState([]);
  const [pagination, setPagination] = useState({});
  const [stats, setStats] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [filterStatus, setFilterStatus] = useState('all');

  useEffect(() => {
    let isCurrent = true;

    const loadCommissions = async () => {
      try {
        setIsLoading(true);
        setLoadError(null);
        const [commissionData, dashboardData] = await Promise.all([
          loadAffiliateCommissions(),
          loadAffiliateDashboard(),
        ]);
        if (isCurrent) {
          setCommissions(commissionData.commissions);
          setPagination(commissionData.pagination);
          setStats(dashboardData.stats);
        }
      } catch (error) {
        if (isCurrent) {
          setCommissions([]);
          setPagination({});
          setStats(null);
          setLoadError(affiliateViewError(error));
        }
      } finally {
        if (isCurrent) setIsLoading(false);
      }
    };

    loadCommissions();
    return () => {
      isCurrent = false;
    };
  }, []);

  const statuses = useMemo(
    () => [...new Set(commissions.map((commission) => commission.status).filter(Boolean))],
    [commissions],
  );
  const filteredCommissions = useMemo(
    () => commissions.filter((commission) => filterStatus === 'all' || commission.status === filterStatus),
    [commissions, filterStatus],
  );

  const exportLoadedCommissions = () => {
    const headers = ['Date', 'Description', 'Type', 'Amount', 'Status', 'Paid Date'];
    const rows = filteredCommissions.map((commission) => [
      formatDate(commission.createdAt),
      commission.description || '',
      commission.type || '',
      Number.isFinite(commission.amount) ? commission.amount : '',
      commission.status || '',
      formatDate(commission.paidAt),
    ]);
    const csv = [headers, ...rows]
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `affiliate-commissions-${new Date().toISOString().split('T')[0]}.csv`;
    anchor.click();
    window.URL.revokeObjectURL(url);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
          <p className="text-gray-300 mt-4">Loading commissions...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900">
      <div className="bg-slate-800/50 border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">Commissions</h1>
              <p className="text-gray-300 mt-2">Commission records for your current affiliate account.</p>
            </div>
            {!loadError && (
              <button onClick={exportLoadedCommissions} className="btn btn-primary flex items-center gap-2">
                <Download className="w-5 h-5" />
                Export loaded records
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {loadError ? (
          <div role="alert" className="rounded-lg border border-red-500/50 bg-red-950/40 p-4 text-red-100">
            <p className="font-semibold">Unable to load commissions</p>
            <p className="mt-1 text-sm">{loadError}</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
              <StatCard label="Tracked Commissions" value={formatCurrency(stats?.totalCommission)} icon={<DollarSign className="w-6 h-6 text-green-600" />} />
              <StatCard label="Pending" value={formatCurrency(stats?.pendingCommission)} icon={<Clock className="w-6 h-6 text-yellow-600" />} />
              <StatCard label="Approved" value={formatCurrency(stats?.approvedCommission)} icon={<CheckCircle className="w-6 h-6 text-blue-600" />} />
              <StatCard label="Paid" value={formatCurrency(stats?.paidCommission)} icon={<CheckCircle className="w-6 h-6 text-green-600" />} />
            </div>

            <div className="bg-slate-800/50 rounded-lg shadow-sm p-4 mb-6 flex items-center gap-4">
              <label htmlFor="commission-status" className="text-sm text-gray-300">Status</label>
              <select id="commission-status" value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)} className="input">
                <option value="all">All statuses</option>
                {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
              {pagination.total > commissions.length && <p className="ml-auto text-sm text-gray-400">Showing {commissions.length} of {pagination.total} records.</p>}
            </div>

            <div className="bg-slate-800/50 rounded-lg shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-slate-900 border-b border-white/10">
                    <tr>
                      {['Date', 'Description', 'Type', 'Amount', 'Status', 'Paid Date'].map((heading) => (
                        <th key={heading} className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">{heading}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-slate-800/50 divide-y divide-white/10">
                    {filteredCommissions.map((commission) => (
                      <tr key={commission.id} className="hover:bg-slate-900">
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{formatDate(commission.createdAt)}</td>
                        <td className="px-6 py-4 text-sm text-white">{commission.description || '—'}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{commission.type || '—'}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-bold text-white">{formatCurrency(commission.amount)}</td>
                        <td className="px-6 py-4 whitespace-nowrap"><span className={`px-2 py-1 rounded-full text-xs font-medium ${statusClass(commission.status)}`}>{commission.status || '—'}</span></td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{formatDate(commission.paidAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filteredCommissions.length === 0 && <div className="text-center py-12 text-gray-300">No commissions found.</div>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, icon }) {
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
