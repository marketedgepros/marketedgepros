import { useState, useEffect } from 'react';
import { DollarSign, Clock, CheckCircle, XCircle, Plus, AlertCircle } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { SkeletonDashboard } from '../../components/common/Skeleton';

export default function Withdrawals() {
  const toast = useToast();
  const [withdrawals, setWithdrawals] = useState([]);
  const [statistics, setStatistics] = useState({
    available_balance: 0,
    total_withdrawn: 0,
    pending_withdrawals: 0,
    completed_count: 0
  });
  const [isLoading, setIsLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [formData, setFormData] = useState({
    amount: '',
    method: 'bank_transfer',
    accountDetails: '',
  });

  useEffect(() => {
    loadWithdrawals();
  }, []);

  const loadWithdrawals = async () => {
    try {
      setIsLoading(true);
      setError(null);
      
      const response = await api.get('/api/v1/traders/withdrawals');
      
      if (response.data) {
        setWithdrawals(response.data.withdrawals || []);
        setStatistics(response.data.statistics || {
          available_balance: 0,
          total_withdrawn: 0,
          pending_withdrawals: 0,
          completed_count: 0
        });
      }
    } catch (error) {
      setError('Failed to load withdrawal data. Please try again.');
      toast.error('Failed to load withdrawal data');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    const amount = parseFloat(formData.amount);
    
    // Validation
    if (!amount || amount <= 0) {
      toast.error('Please enter a valid amount');
      return;
    }
    
    if (amount < 100) {
      toast.error('Minimum withdrawal amount is $100');
      return;
    }
    
    if (amount > statistics.available_balance) {
      toast.error(`Insufficient balance. Available: $${statistics.available_balance.toFixed(2)}`);
      return;
    }

    if (!formData.accountDetails || formData.accountDetails.trim() === '') {
      toast.error('Please provide account details');
      return;
    }

    try {
      setIsSubmitting(true);
      setError(null);
      
      await api.post('/api/v1/traders/withdrawals', {
        amount: amount,
        method: formData.method,
        account_details: formData.accountDetails
      });
      
      // Reload data
      await loadWithdrawals();
      
      // Reset form and close modal
      setShowModal(false);
      setFormData({ amount: '', method: 'bank_transfer', accountDetails: '' });
      
      toast.success('Withdrawal request submitted successfully!');
    } catch (error) {
      const errorMessage = error.response?.data?.error || 'Failed to submit withdrawal request. Please try again.';
      toast.error(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'processing':
      case 'approved':
        return 'bg-blue-100 text-blue-800';
      case 'pending':
        return 'bg-yellow-100 text-yellow-800';
      case 'rejected':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-slate-700/50 text-gray-100';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-green-600" />;
      case 'processing':
      case 'approved':
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-600" />;
      case 'rejected':
        return <XCircle className="w-5 h-5 text-red-600" />;
      default:
        return null;
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (isLoading) {
    return (
      <>
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
            <p className="text-gray-300 mt-4">Loading withdrawals...</p>
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
                <h1 className="text-3xl font-bold text-white">Withdrawals</h1>
                <p className="text-gray-300 mt-2">Request and track your payouts</p>
              </div>
              <button
                onClick={() => setShowModal(true)}
                className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-medium transition-colors duration-200 flex items-center gap-2"
              >
                <Plus className="w-5 h-5" />
                New Withdrawal
              </button>
            </div>
          </div>
        </div>

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Error Message */}
          {error && (
            <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-red-800 font-medium">Error</p>
                <p className="text-red-700 text-sm mt-1">{error}</p>
              </div>
            </div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div className="bg-slate-800/50 rounded-lg shadow-md p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-300">Available Balance</p>
                  <p className="text-2xl font-bold text-white mt-1">
                    ${statistics.available_balance?.toFixed(2) || '0.00'}
                  </p>
                </div>
                <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                  <DollarSign className="w-6 h-6 text-green-600" />
                </div>
              </div>
            </div>

            <div className="bg-slate-800/50 rounded-lg shadow-md p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-300">Total Withdrawn</p>
                  <p className="text-2xl font-bold text-white mt-1">
                    ${statistics.total_withdrawn?.toFixed(2) || '0.00'}
                  </p>
                </div>
                <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                  <CheckCircle className="w-6 h-6 text-blue-600" />
                </div>
              </div>
            </div>

            <div className="bg-slate-800/50 rounded-lg shadow-md p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-300">Pending</p>
                  <p className="text-2xl font-bold text-white mt-1">
                    ${statistics.pending_withdrawals?.toFixed(2) || '0.00'}
                  </p>
                </div>
                <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
                  <Clock className="w-6 h-6 text-yellow-600" />
                </div>
              </div>
            </div>

            <div className="bg-slate-800/50 rounded-lg shadow-md p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-300">Completed</p>
                  <p className="text-2xl font-bold text-white mt-1">
                    {statistics.completed_count || 0}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">Total requests</p>
                </div>
                <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                  <CheckCircle className="w-6 h-6 text-purple-600" />
                </div>
              </div>
            </div>
          </div>

          {/* Withdrawals Table */}
          <div className="bg-slate-800/50 rounded-lg shadow-md overflow-hidden">
            <div className="px-6 py-4 border-b border-white/10">
              <h2 className="text-lg font-semibold text-white">Withdrawal History</h2>
            </div>

            {withdrawals.length === 0 ? (
              <div className="p-12 text-center">
                <DollarSign className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                <p className="text-gray-300 font-medium">No withdrawals yet</p>
                <p className="text-sm text-gray-400 mt-2">Click "New Withdrawal" to request your first payout</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-slate-900">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                        Date
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                        Amount
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                        Method
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                        Processed
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                        Notes
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-slate-800/50 divide-y divide-gray-200">
                    {withdrawals.map((withdrawal) => (
                      <tr key={withdrawal.id} className="hover:bg-slate-900">
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-white">
                          {formatDate(withdrawal.requested_at)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-white">
                          ${withdrawal.amount?.toFixed(2)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                          {withdrawal.method?.replace('_', ' ').toUpperCase()}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(withdrawal.status)}`}>
                            {getStatusIcon(withdrawal.status)}
                            {withdrawal.status?.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                          {withdrawal.processed_at ? formatDate(withdrawal.processed_at) : '-'}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-300 max-w-xs truncate">
                          {withdrawal.notes || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Withdrawal Modal */}
        {showModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-slate-800/50 rounded-lg max-w-md w-full p-6">
              <h2 className="text-2xl font-bold text-white mb-4">Request Withdrawal</h2>
              
              <form onSubmit={handleSubmit}>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-200 mb-2">
                    Amount ($)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="100"
                    max={statistics.available_balance}
                    value={formData.amount}
                    onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                    className="w-full px-4 py-2 border border-white/20 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    placeholder="Enter amount"
                    required
                  />
                  <p className="text-xs text-gray-400 mt-1">
                    Available: ${statistics.available_balance?.toFixed(2)} | Minimum: $100
                  </p>
                </div>

                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-200 mb-2">
                    Withdrawal Method
                  </label>
                  <select
                    value={formData.method}
                    onChange={(e) => setFormData({ ...formData, method: e.target.value })}
                    className="w-full px-4 py-2 border border-white/20 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    required
                  >
                    <option value="bank_transfer">Bank Transfer</option>
                    <option value="paypal">PayPal</option>
                    <option value="wire">Wire Transfer</option>
                    <option value="crypto">Cryptocurrency</option>
                  </select>
                </div>

                <div className="mb-6">
                  <label className="block text-sm font-medium text-gray-200 mb-2">
                    Account Details
                  </label>
                  <textarea
                    value={formData.accountDetails}
                    onChange={(e) => setFormData({ ...formData, accountDetails: e.target.value })}
                    className="w-full px-4 py-2 border border-white/20 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    rows="3"
                    placeholder="Enter your account details (account number, PayPal email, wallet address, etc.)"
                    required
                  ></textarea>
                </div>

                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setShowModal(false);
                      setFormData({ amount: '', method: 'bank_transfer', accountDetails: '' });
                    }}
                    className="flex-1 px-4 py-2 border border-white/20 text-gray-200 rounded-lg hover:bg-slate-900 font-medium transition-colors duration-200"
                    disabled={isSubmitting}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? 'Submitting...' : 'Submit Request'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

