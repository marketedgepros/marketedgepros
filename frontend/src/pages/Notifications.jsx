import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, CheckCircle2, Circle, Loader, RefreshCw, Settings, Trash2 } from 'lucide-react';
import useAuthStore from '../store/authStore';
import useNotificationStore from '../stores/notificationStore';
import { notificationDestination } from '../services/notificationViewService';
import { formatDistanceToNow } from '../utils/dateUtils';
import useTabNavigation from '../hooks/useTabNavigation';

const getPriorityColor = (priority) => ({
  low: 'border-slate-500/70 bg-slate-700/70 text-slate-100',
  normal: 'border-cyan-400/40 bg-cyan-400/10 text-cyan-100',
  high: 'border-amber-400/50 bg-amber-400/10 text-amber-100',
  urgent: 'border-red-400/50 bg-red-500/10 text-red-100',
}[priority] || 'border-cyan-400/40 bg-cyan-400/10 text-cyan-100');

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
const tabIds = tabs.map((tab) => tab.value);

const actorIdentity = (state) => JSON.stringify([
  state.isAuthenticated,
  state.user?.id ?? null,
  state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
  state.user?.role ?? null,
]);

export default function Notifications() {
  const context = useAuthStore(actorIdentity);
  return <NotificationsView key={context} />;
}

function NotificationsView() {
  const navigate = useNavigate();
  const role = useAuthStore((state) => state.user?.role);
  const identity = useAuthStore(actorIdentity);
  const [activeTab, setActiveTab] = useState('all');
  const notifications = useNotificationStore((state) => state.notifications);
  const loading = useNotificationStore((state) => state.loading);
  const error = useNotificationStore((state) => state.error);
  const actionErrors = useNotificationStore((state) => state.actionErrors);
  const pendingAction = useNotificationStore((state) => state.pendingAction);
  const currentPage = useNotificationStore((state) => state.currentPage);
  const totalPages = useNotificationStore((state) => state.totalPages);
  const total = useNotificationStore((state) => state.total);
  const fetchNotifications = useNotificationStore((state) => state.fetchNotifications);
  const markAsRead = useNotificationStore((state) => state.markAsRead);
  const markAllAsRead = useNotificationStore((state) => state.markAllAsRead);
  const deleteNotification = useNotificationStore((state) => state.deleteNotification);
  const filters = useMemo(() => filterForTab(activeTab), [activeTab]);
  const getTabProps = useTabNavigation({ ids: tabIds, activeId: activeTab, onChange: setActiveTab });
  const anyActionPending = pendingAction !== null;
  const actionError = Object.values(actionErrors).find(Boolean);

  useEffect(() => {
    fetchNotifications(1, filters);
  }, [fetchNotifications, filters]);

  const changePage = (page) => {
    if (page < 1 || page > totalPages || page > 1000) return;
    fetchNotifications(page, filters);
  };

  const handleNotificationOpen = async (notification) => {
    const originalIdentity = identity;
    if (!notification.is_read && !(await markAsRead(notification.id))) return;
    const current = useAuthStore.getState();
    if (actorIdentity(current) !== originalIdentity) return;
    navigate(notificationDestination(notification.type, role));
  };

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="mep-heading text-3xl font-bold text-white">Notifications</h1>
          <p className="mt-1 text-sm text-slate-300">Your recorded in-app notification history.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={() => fetchNotifications(1, filters)} disabled={loading || anyActionPending}
            className="flex items-center gap-2 rounded-lg border border-cyan-300/35 px-4 py-2 text-cyan-100 transition-colors hover:bg-cyan-300/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" /> Refresh
          </button>
          <button type="button" onClick={() => markAllAsRead()} disabled={notifications.length === 0 || loading || anyActionPending}
            className="flex items-center gap-2 rounded-lg border border-cyan-300/35 px-4 py-2 text-cyan-100 transition-colors hover:bg-cyan-300/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Mark all read
          </button>
          <button type="button" onClick={() => navigate('/settings/notifications')}
            className="mep-primary flex items-center gap-2 px-4 py-2 font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-100">
            <Settings className="h-4 w-4" aria-hidden="true" /> Settings
          </button>
        </div>
      </div>

      <div className="mep-panel mb-6 rounded-lg border p-1">
        <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Notification filters">
          {tabs.map((tab) => (
            <button type="button" key={tab.value} id={`notifications-tab-${tab.value}`}
              aria-controls={`notifications-tabpanel-${tab.value}`} {...getTabProps(tab.value)}
              className={`whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 ${
                activeTab === tab.value ? 'bg-cyan-400/20 text-cyan-100' : 'text-slate-300 hover:bg-white/5 hover:text-white'
              }`}>{tab.label}</button>
          ))}
        </div>
      </div>

      {actionError && <div role="alert" className="mb-4 rounded-lg border border-red-400/50 bg-red-500/10 p-4 text-red-100">{actionError}</div>}

      <div className="mep-panel rounded-lg border" role="tabpanel" id={`notifications-tabpanel-${activeTab}`}
        aria-labelledby={`notifications-tab-${activeTab}`} aria-live="polite">
        {error && (
          <div role="alert" className="m-4 rounded-lg border border-red-400/50 bg-red-500/10 p-4 text-red-100">
            <p className="break-words">{error}</p>
            <button type="button" onClick={() => fetchNotifications(1, filters)}
              className="mt-2 text-sm font-medium text-cyan-100 underline hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">Try again</button>
          </div>
        )}
        {loading ? <div className="flex justify-center p-12"><Loader className="h-8 w-8 animate-spin text-cyan-300" aria-label="Loading notifications" /></div>
          : error ? null : notifications.length === 0 ? <div className="p-12 text-center text-slate-300">No notifications found.</div>
            : <>
              <div className="divide-y divide-white/10">
                {notifications.map((notification) => {
                  const marking = pendingAction?.name === 'mark-read' && pendingAction.id === notification.id;
                  const deleting = pendingAction?.name === 'delete' && pendingAction.id === notification.id;
                  return (
                    <article key={notification.id} className={`flex flex-col gap-3 p-4 sm:flex-row sm:items-start ${notification.is_read ? 'hover:bg-white/5' : 'bg-cyan-300/5'}`}>
                      <button type="button" onClick={() => handleNotificationOpen(notification)} disabled={anyActionPending}
                        className="flex min-w-0 flex-1 items-start gap-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed">
                        <Bell className="mt-1 h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
                        <span className="min-w-0 flex-1">
                          <span className="mb-1 flex flex-wrap items-center gap-2">
                            <span className={`break-words text-base ${notification.is_read ? 'text-slate-200' : 'font-semibold text-white'}`}>{notification.title}</span>
                            <span className={`rounded border px-2 py-0.5 text-xs font-medium ${getPriorityColor(notification.priority)}`}>{notification.priority}</span>
                            {!notification.is_read && <Circle className="h-2.5 w-2.5 fill-cyan-300 text-cyan-300" aria-label="Unread" />}
                          </span>
                          <span className="block break-words text-sm text-slate-300">{notification.message}</span>
                          {notification.created_at && <time dateTime={notification.created_at} className="mt-1 block text-xs text-slate-400">{formatDistanceToNow(new Date(notification.created_at), { addSuffix: true })}</time>}
                        </span>
                      </button>
                      <div className="flex shrink-0 gap-2 self-end sm:self-start">
                        {!notification.is_read && <button type="button" onClick={() => markAsRead(notification.id)} disabled={anyActionPending}
                          className="rounded px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-300/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">{marking ? 'Marking…' : 'Mark read'}</button>}
                        <button type="button" aria-label={`Delete ${notification.title}`} onClick={() => deleteNotification(notification.id)} disabled={anyActionPending}
                          className="rounded p-2 text-slate-300 hover:bg-red-500/10 hover:text-red-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-300 disabled:cursor-not-allowed disabled:opacity-50">
                          {deleting ? <Loader className="h-5 w-5 animate-spin" aria-hidden="true" /> : <Trash2 className="h-5 w-5" aria-hidden="true" />}
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
              {totalPages > 1 && <div className="flex flex-wrap items-center justify-center gap-3 border-t border-white/10 p-4">
                <button type="button" onClick={() => changePage(currentPage - 1)} disabled={currentPage <= 1 || loading || anyActionPending}
                  className="rounded-lg border border-cyan-300/35 px-4 py-2 text-cyan-100 hover:bg-cyan-300/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">Previous</button>
                <span className="text-center text-sm text-slate-200">Page {currentPage} of {Math.min(totalPages, 1000)} {total > 0 ? `(${total} total)` : ''}</span>
                <button type="button" onClick={() => changePage(currentPage + 1)} disabled={currentPage >= totalPages || currentPage >= 1000 || loading || anyActionPending}
                  className="rounded-lg border border-cyan-300/35 px-4 py-2 text-cyan-100 hover:bg-cyan-300/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">Next</button>
              </div>}
            </>}
      </div>
    </div>
  );
}
