import { useEffect, useMemo, useState } from 'react';
import { Filter, Search, Users } from 'lucide-react';
import { affiliateViewError, loadAffiliateReferrals } from '../../services/affiliateViewService';

const formatCurrency = (value) => (
  Number.isFinite(value)
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
    : '—'
);

const formatDate = (value) => (value ? new Date(value).toLocaleDateString() : '—');

const statusClass = (status) => ({
  converted: 'bg-green-100 text-green-800',
  pending: 'bg-yellow-100 text-yellow-800',
  cancelled: 'bg-red-100 text-red-800',
}[status] || 'bg-slate-700/50 text-gray-100');

export default function TradersManagement() {
  const [traders, setTraders] = useState([]);
  const [pagination, setPagination] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');

  useEffect(() => {
    let isCurrent = true;

    const loadTraders = async () => {
      try {
        setIsLoading(true);
        setLoadError(null);
        const data = await loadAffiliateReferrals();
        if (isCurrent) {
          setTraders(data.referrals);
          setPagination(data.pagination);
        }
      } catch (error) {
        if (isCurrent) {
          setTraders([]);
          setPagination({});
          setLoadError(affiliateViewError(error));
        }
      } finally {
        if (isCurrent) setIsLoading(false);
      }
    };

    loadTraders();
    return () => {
      isCurrent = false;
    };
  }, []);

  const statuses = useMemo(
    () => [...new Set(traders.map((trader) => trader.status).filter(Boolean))],
    [traders],
  );

  const filteredTraders = useMemo(() => traders.filter((trader) => {
    const query = searchTerm.trim().toLowerCase();
    const matchesSearch = !query
      || trader.name?.toLowerCase().includes(query)
      || trader.email?.toLowerCase().includes(query);
    const matchesFilter = filterStatus === 'all' || trader.status === filterStatus;
    return matchesSearch && matchesFilter;
  }), [filterStatus, searchTerm, traders]);

  const converted = traders.filter((trader) => trader.status === 'converted').length;
  const pending = traders.filter((trader) => trader.status === 'pending').length;
  const recordedCommissionValues = traders
    .map((trader) => trader.commissionAmount)
    .filter(Number.isFinite);
  const recordedCommission = recordedCommissionValues.length > 0
    ? recordedCommissionValues.reduce((total, amount) => total + amount, 0)
    : null;

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
          <p className="text-gray-300 mt-4">Loading referred traders...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900">
      <div className="bg-slate-800/50 border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-white">My Referred Traders</h1>
          <p className="text-gray-300 mt-2">Referral activity for your current affiliate account.</p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {loadError && (
          <div role="alert" className="mb-6 rounded-lg border border-red-500/50 bg-red-950/40 p-4 text-red-100">
            <p className="font-semibold">Unable to load referred traders</p>
            <p className="mt-1 text-sm">{loadError}</p>
          </div>
        )}

        {!loadError && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
              <div className="card">
                <p className="text-sm text-gray-300">Total Referrals</p>
                <p className="text-2xl font-bold text-white mt-1">{pagination.total ?? traders.length}</p>
              </div>
              <div className="card">
                <p className="text-sm text-gray-300">Converted in This Page</p>
                <p className="text-2xl font-bold text-green-600 mt-1">{converted}</p>
              </div>
              <div className="card">
                <p className="text-sm text-gray-300">Pending in This Page</p>
                <p className="text-2xl font-bold text-yellow-600 mt-1">{pending}</p>
              </div>
              <div className="card">
                <p className="text-sm text-gray-300">Recorded Commission in This Page</p>
                <p className="text-2xl font-bold text-white mt-1">{formatCurrency(recordedCommission)}</p>
              </div>
            </div>

            <div className="bg-slate-800/50 rounded-lg shadow-sm p-4 mb-6">
              <div className="flex flex-col sm:flex-row gap-4">
                <div className="flex-1 relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-5 h-5" />
                  <input
                    type="text"
                    placeholder="Search referred traders by name or email..."
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    className="input pl-10 w-full"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Filter className="w-5 h-5 text-gray-400" />
                  <select
                    value={filterStatus}
                    onChange={(event) => setFilterStatus(event.target.value)}
                    className="input"
                  >
                    <option value="all">All statuses</option>
                    {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="bg-slate-800/50 rounded-lg shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-slate-900 border-b border-white/10">
                    <tr>
                      {['Trader', 'Status', 'Clicked', 'Converted', 'Purchase', 'Commission'].map((heading) => (
                        <th key={heading} className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">{heading}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-slate-800/50 divide-y divide-white/10">
                    {filteredTraders.map((trader) => (
                      <tr key={trader.id} className="hover:bg-slate-900">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 bg-primary-100 rounded-full flex items-center justify-center">
                              <Users className="w-5 h-5 text-primary-600" />
                            </div>
                            <div>
                              <p className="font-medium text-white">{trader.name || '—'}</p>
                              <p className="text-sm text-gray-400">{trader.email || '—'}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap"><span className={`px-2 py-1 rounded-full text-xs font-medium ${statusClass(trader.status)}`}>{trader.status || '—'}</span></td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{formatDate(trader.clickDate)}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{formatDate(trader.conversionDate)}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-white">{formatCurrency(trader.purchaseAmount)}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-bold text-white">{formatCurrency(trader.commissionAmount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filteredTraders.length === 0 && <div className="text-center py-12 text-gray-300">No referred traders found.</div>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
