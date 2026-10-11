import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle, Loader, RefreshCw, Settings, Trash2 } from 'lucide-react';
import useAuthStore from '../store/authStore';
import useNotificationStore from '../stores/notificationStore';
import { notificationDestination } from '../services/notificationViewService';
import { formatDistanceToNow } from '../utils/dateUtils';

const getNotificationIcon = (type) => ({
  withdrawal: '💰',
  commission: '💵',
  kyc: '🆔',
  system: '📢',
  payment: '💳',
  challenge: '🎯',
}[type] || '📬');

const getPriorityColor = (priority) => ({
  low: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200',
  normal: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  high: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  urgent: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
}[priority] || 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200');

const filterForTab = (tab) => {
  if (tab === 'unread') return { is_read: false };
  if (tab === 'all') return {};
  return { type: tab };
};

const tabs = [
  { label: 'All', value: 'all' },
  { label: 'Unread', value: 'unread' },
  { label: 'Withdrawals', value: 'withdrawal' },
  { label: 'Commissions', value: 'commission' },
  { label: 'KYC', value: 'kyc' },
  { label: 'Payments', value: 'payment' },
  { label: 'Challenges', value: 'challenge' },
  { label: 'System', value: 'system' },
];

export default function Notifications() {
  const context = useAuthStore((state) => JSON.stringify([
    state.isAuthenticated, state.user?.id ?? null,
    state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
  ]));
  return <NotificationsView key={context} />;
}

function NotificationsView() {
  const navigate = useNavigate();
  const role = useAuthStore((state) => state.user?.role);
  const [activeTab, setActiveTab] = useState('all');
  const notifications = useNotificationStore((state) => state.notifications);
  const loading = useNotificationStore((state) => state.loading);
  const error = useNotificationStore((state) => state.error);
  const currentPage = useNotificationStore((state) => state.currentPage);
  const totalPages = useNotificationStore((state) => state.totalPages);
  const total = useNotificationStore((state) => state.total);
  const fetchNotifications = useNotificationStore((state) => state.fetchNotifications);
  const markAsRead = useNotificationStore((state) => state.markAsRead);
  const markAllAsRead = useNotificationStore((state) => state.markAllAsRead);
  const deleteNotification = useNotificationStore((state) => state.deleteNotification);
  const filters = useMemo(() => filterForTab(activeTab), [activeTab]);

  useEffect(() => {
    fetchNotifications(1, filters);
  }, [fetchNotifications, filters]);

  const changePage = (page) => {
    if (page < 1 || page > totalPages || page > 1000) return;
    fetchNotifications(page, filters);
  };

  const handleNotificationClick = async (notification) => {
    if (!notification.is_read) {
      const marked = await markAsRead(notification.id);
      if (!marked) return;
    }
    navigate(notificationDestination(notification.type, role));
  };

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="mb-6 flex flex-wrap justify-between gap-3 items-center">
        <h1 className="text-3xl font-bold text-white">Notifications</h1>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => fetchNotifications(1, filters)}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 border border-white/20 text-white rounded-lg hover:bg-white/10 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => markAllAsRead()}
            disabled={notifications.length === 0 || loading}
            className="flex items-center gap-2 px-4 py-2 border border-white/20 text-white rounded-lg hover:bg-white/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <CheckCircle className="w-4 h-4" />
            Mark All Read
          </button>
          <button
            type="button"
            onClick={() => navigate('/settings/notifications')}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-purple-800 text-white rounded-lg hover:from-purple-700 hover:to-purple-900 transition-colors"
          >
            <Settings className="w-4 h-4" />
            Settings
          </button>
        </div>
      </div>

      <div className="mb-6 bg-slate-800/50 backdrop-blur-sm border border-white/10 rounded-lg p-1">
        <div className="flex gap-1 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              type="button"
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
                activeTab === tab.value
                  ? 'bg-gradient-to-r from-purple-600 to-purple-800 text-white'
                  : 'text-gray-300 hover:text-white hover:bg-white/5'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-slate-800/50 backdrop-blur-sm border border-white/10 rounded-lg" aria-live="polite">
        {error && (
          <div role="alert" className="m-4 rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-red-200">
            <p>{error}</p>
            <button
              type="button"
              onClick={() => fetchNotifications(1, filters)}
              className="mt-2 text-sm font-medium text-red-100 underline hover:text-white"
            >
              Try again
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex justify-center p-12">
            <Loader className="w-8 h-8 text-purple-500 animate-spin" />
          </div>
        ) : error ? null : notifications.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-400">No notifications found</p>
          </div>
        ) : (
          <>
            <div className="divide-y divide-white/5">
              {notifications.map((notification) => (
                <div
                  key={notification.id}
                  onClick={() => handleNotificationClick(notification)}
                  className={`flex items-start gap-4 p-4 cursor-pointer transition-colors ${
                    notification.is_read ? 'hover:bg-white/5' : 'bg-white/10 hover:bg-white/15'
                  }`}
                >
                  <div className="text-3xl flex-shrink-0 mt-1" aria-hidden="true">{getNotificationIcon(notification.type)}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h2 className={`text-base ${notification.is_read ? 'text-gray-300' : 'text-white font-semibold'}`}>
                        {notification.title}
                      </h2>
                      <span className={`px-2 py-0.5 text-xs font-medium rounded ${getPriorityColor(notification.priority)}`}>
                        {notification.priority}
                      </span>
                      {!notification.is_read && <div className="w-2.5 h-2.5 rounded-full bg-blue-500" />}
                    </div>
                    <p className="text-sm text-gray-400 mb-1">{notification.message}</p>
                    <p className="text-xs text-gray-500">
                      {notification.created_at ? formatDistanceToNow(new Date(notification.created_at), { addSuffix: true }) : 'Recently'}
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label={`Delete ${notification.title}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      deleteNotification(notification.id);
                    }}
                    className="flex-shrink-0 p-2 text-gray-400 hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              ))}
            </div>

            {totalPages > 1 && (
              <div className="flex flex-wrap items-center justify-center gap-3 p-4 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => changePage(currentPage - 1)}
                  disabled={currentPage <= 1 || loading}
                  className="px-4 py-2 border border-white/20 text-white rounded-lg hover:bg-white/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <span className="text-sm text-gray-300">
                  Page {currentPage} of {Math.min(totalPages, 1000)} {total > 0 ? `(${total} total)` : ''}
                </span>
                <button
                  type="button"
                  onClick={() => changePage(currentPage + 1)}
                  disabled={currentPage >= totalPages || currentPage >= 1000 || loading}
                  className="px-4 py-2 border border-white/20 text-white rounded-lg hover:bg-white/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
