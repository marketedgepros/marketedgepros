import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, CheckCircle2, Circle, Loader, Trash2 } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import useNotificationStore from '../../stores/notificationStore';
import { notificationDestination } from '../../services/notificationViewService';
import { formatDistanceToNow } from '../../utils/dateUtils';

const actorIdentity = (state) => JSON.stringify([
  state.isAuthenticated,
  state.user?.id ?? null,
  state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
  state.user?.role ?? null,
]);

export default function NotificationDropdown({ onClose }) {
  const navigate = useNavigate();
  const role = useAuthStore((state) => state.user?.role);
  const identity = useAuthStore(actorIdentity);
  const notifications = useNotificationStore((state) => state.dropdownNotifications);
  const loading = useNotificationStore((state) => state.dropdownLoading);
  const error = useNotificationStore((state) => state.dropdownError);
  const actionErrors = useNotificationStore((state) => state.actionErrors);
  const pendingAction = useNotificationStore((state) => state.pendingAction);
  const fetchNotifications = useNotificationStore((state) => state.fetchNotifications);
  const markAsRead = useNotificationStore((state) => state.markAsRead);
  const markAllAsRead = useNotificationStore((state) => state.markAllAsRead);
  const deleteNotification = useNotificationStore((state) => state.deleteNotification);
  const anyActionPending = pendingAction !== null;

  useEffect(() => { fetchNotifications(1, {}, { scope: 'dropdown', perPage: 10 }); }, [fetchNotifications]);

  const handleNotificationOpen = async (notification) => {
    const originalIdentity = identity;
    if (!notification.is_read && !(await markAsRead(notification.id))) return;
    if (actorIdentity(useAuthStore.getState()) !== originalIdentity) return;
    navigate(notificationDestination(notification.type, role));
    onClose?.();
  };

  const actionError = Object.values(actionErrors).find(Boolean);
  return <div className="flex flex-col" aria-live="polite">
    <div className="flex items-center justify-between gap-3 border-b border-white/10 p-4"><div className="flex items-center gap-2"><Bell className="h-5 w-5 text-cyan-300" aria-hidden="true" /><h3 className="text-lg font-semibold text-white">Notifications</h3></div>
      {notifications.length > 0 && <button type="button" onClick={() => markAllAsRead()} disabled={anyActionPending} className="flex shrink-0 items-center gap-1 text-sm text-cyan-100 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />Mark all read</button>}</div>
    {(error || actionError) && <p role="alert" className="m-3 break-words rounded border border-red-400/50 bg-red-500/10 px-3 py-2 text-sm text-red-100">{actionError || error}</p>}
    {loading ? <div className="flex justify-center p-8"><Loader className="h-8 w-8 animate-spin text-cyan-300" aria-label="Loading notifications" /></div>
      : notifications.length === 0 ? <div className="p-8 text-center text-slate-300">No notifications.</div>
        : <div className="max-h-96 overflow-y-auto">{notifications.map((notification) => {
          const marking = pendingAction?.name === 'mark-read' && pendingAction.id === notification.id;
          const deleting = pendingAction?.name === 'delete' && pendingAction.id === notification.id;
          return <article key={notification.id} className={`flex gap-2 border-b border-white/10 p-3 ${notification.is_read ? 'hover:bg-white/5' : 'bg-cyan-300/5'}`}>
            <button type="button" onClick={() => handleNotificationOpen(notification)} disabled={anyActionPending} className="flex min-w-0 flex-1 items-start gap-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed"><Bell className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" aria-hidden="true" /><span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><span className={`break-words text-sm ${notification.is_read ? 'text-slate-200' : 'font-semibold text-white'}`}>{notification.title}</span>{!notification.is_read && <Circle className="h-2 w-2 fill-cyan-300 text-cyan-300" aria-label="Unread" />}</span><span className="mt-1 block break-words text-sm text-slate-300">{notification.message}</span>{notification.created_at && <time dateTime={notification.created_at} className="mt-1 block text-xs text-slate-400">{formatDistanceToNow(new Date(notification.created_at), { addSuffix: true })}</time>}</span></button>
            <div className="flex shrink-0 flex-col gap-1">{!notification.is_read && <button type="button" onClick={() => markAsRead(notification.id)} disabled={anyActionPending} className="rounded px-2 py-1 text-xs text-cyan-100 hover:bg-cyan-300/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">{marking ? 'Marking…' : 'Read'}</button>}<button type="button" aria-label={`Delete ${notification.title}`} onClick={() => deleteNotification(notification.id)} disabled={anyActionPending} className="rounded p-1 text-slate-300 hover:bg-red-500/10 hover:text-red-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-300 disabled:cursor-not-allowed disabled:opacity-50">{deleting ? <Loader className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Trash2 className="h-4 w-4" aria-hidden="true" />}</button></div>
          </article>;
        })}</div>}
    {notifications.length > 0 && <div className="border-t border-white/10 p-2"><button type="button" onClick={() => { navigate('/notifications'); onClose?.(); }} className="w-full rounded py-2 text-sm text-cyan-100 hover:bg-cyan-300/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">View all notifications</button></div>}
  </div>;
}
