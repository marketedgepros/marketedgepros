import { useEffect, useState } from 'react';
import { Search, Filter, Download, Calendar, TrendingUp, TrendingDown } from 'lucide-react';
import api from '../../services/api';

export default function TradingHistory() {
  const [trades, setTrades] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState('all');
  const [filterPeriod, setFilterPeriod] = useState('all');

  useEffect(() => {
    loadTrades();
  }, []);

  const loadTrades = async () => {
    try {
      setIsLoading(true);
      const response = await api.get('/trader/trades');
      setTrades(response.data.trades || []);
    } catch (error) {
      setTrades([]);
    } finally {
      setIsLoading(false);
    }
  };

  const exportTrades = () => {
    const headers = ['Symbol', 'Type', 'Lots', 'Open Price', 'Close Price', 'Open Time', 'Close Time', 'Pips', 'Profit', 'Commission', 'Swap'];
    const rows = filteredTrades.map((trade) => [
      trade.symbol,
      trade.type,
      trade.lots,
      trade.openPrice,
      trade.closePrice,
      new Date(trade.openTime).toLocaleString(),
      new Date(trade.closeTime).toLocaleString(),
      trade.pips,
      trade.profit,
      trade.commission,
      trade.swap,
    ]);

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trading-history-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  const filteredTrades = trades.filter((trade) => {
    const matchesSearch = trade.symbol.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesType = filterType === 'all' || trade.type === filterType;
    
    let matchesPeriod = true;
    if (filterPeriod !== 'all') {
      const tradeDate = new Date(trade.closeTime);
      const now = new Date();
      
      if (filterPeriod === 'today') {
        matchesPeriod = tradeDate.toDateString() === now.toDateString();
      } else if (filterPeriod === 'this_week') {
        const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        matchesPeriod = tradeDate >= weekAgo;
      } else if (filterPeriod === 'this_month') {
        matchesPeriod = tradeDate.getMonth() === now.getMonth() && 
                       tradeDate.getFullYear() === now.getFullYear();
      }
    }
    
    return matchesSearch && matchesType && matchesPeriod;
  });

  const stats = {
    totalTrades: filteredTrades.length,
    winningTrades: filteredTrades.filter(t => t.profit > 0).length,
    losingTrades: filteredTrades.filter(t => t.profit < 0).length,
    totalProfit: filteredTrades.reduce((sum, t) => sum + t.profit, 0),
    totalPips: filteredTrades.reduce((sum, t) => sum + t.pips, 0),
  };

  if (isLoading) {
    return (
      <>
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
            <p className="text-gray-300 mt-4">Loading trading history...</p>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="min-h-screen bg-slate-900">
        {/* Header */}
        <div className="bg-slate-800/50 border-b border-white/10">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-white">Trading History</h1>
                <p className="text-gray-300 mt-2">View all your past trades</p>
              </div>
              <button
                onClick={exportTrades}
                className="btn btn-primary flex items-center gap-2"
              >
                <Download className="w-5 h-5" />
                Export
              </button>
            </div>
          </div>
        </div>

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
            <div className="card text-center">
              <p className="text-sm text-gray-300 mb-1">Total Trades</p>
              <p className="text-2xl font-bold text-white">{stats.totalTrades}</p>
            </div>
            <div className="card text-center">
              <p className="text-sm text-gray-300 mb-1">Winning</p>
              <p className="text-2xl font-bold text-green-600">{stats.winningTrades}</p>
            </div>
            <div className="card text-center">
              <p className="text-sm text-gray-300 mb-1">Losing</p>
              <p className="text-2xl font-bold text-red-600">{stats.losingTrades}</p>
            </div>
            <div className="card text-center">
              <p className="text-sm text-gray-300 mb-1">Total Profit</p>
              <p className={`text-2xl font-bold ${stats.totalProfit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {stats.totalProfit >= 0 ? '+' : ''}${stats.totalProfit.toFixed(2)}
              </p>
            </div>
            <div className="card text-center">
              <p className="text-sm text-gray-300 mb-1">Total Pips</p>
              <p className={`text-2xl font-bold ${stats.totalPips >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {stats.totalPips >= 0 ? '+' : ''}{stats.totalPips}
              </p>
            </div>
          </div>

          {/* Filters */}
          <div className="bg-slate-800/50 rounded-lg shadow-sm p-4 mb-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
                <input
                  type="text"
                  placeholder="Search by symbol..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="input pl-10 w-full"
                />
              </div>
              <div className="flex items-center gap-2">
                <Filter className="w-5 h-5 text-gray-400" />
                <select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                  className="input flex-1"
                >
                  <option value="all">All Types</option>
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <Calendar className="w-5 h-5 text-gray-400" />
                <select
                  value={filterPeriod}
                  onChange={(e) => setFilterPeriod(e.target.value)}
                  className="input flex-1"
                >
                  <option value="all">All Time</option>
                  <option value="today">Today</option>
                  <option value="this_week">This Week</option>
                  <option value="this_month">This Month</option>
                </select>
              </div>
            </div>
          </div>

          {/* Trades Table */}
          <div className="bg-slate-800/50 rounded-lg shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-900 border-b border-white/10">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Symbol</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Type</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Lots</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Open Price</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Close Price</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Open Time</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Close Time</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Pips</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">Profit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {filteredTrades.map((trade) => (
                    <tr key={trade.id} className="hover:bg-slate-900">
                      <td className="px-4 py-3 text-sm font-medium text-white">{trade.symbol}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {trade.type === 'buy' ? (
                            <TrendingUp className="w-4 h-4 text-green-600" />
                          ) : (
                            <TrendingDown className="w-4 h-4 text-red-600" />
                          )}
                          <span className={`px-2 py-1 rounded text-xs font-medium ${
                            trade.type === 'buy' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                          }`}>
                            {trade.type.toUpperCase()}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm text-white">{trade.lots}</td>
                      <td className="px-4 py-3 text-sm text-white">{trade.openPrice}</td>
                      <td className="px-4 py-3 text-sm text-white">{trade.closePrice}</td>
                      <td className="px-4 py-3 text-sm text-gray-300">
                        {new Date(trade.openTime).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-300">
                        {new Date(trade.closeTime).toLocaleString()}
                      </td>
                      <td className={`px-4 py-3 text-sm font-medium ${trade.pips >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {trade.pips >= 0 ? '+' : ''}{trade.pips}
                      </td>
                      <td className={`px-4 py-3 text-sm font-bold ${trade.profit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {trade.profit >= 0 ? '+' : ''}${trade.profit.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {filteredTrades.length === 0 && (
              <div className="text-center py-12">
                <p className="text-gray-300">No trades found</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

