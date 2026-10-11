import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Loader, Trash2 } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import useNotificationStore from '../../stores/notificationStore';
import { notificationDestination } from '../../services/notificationViewService';
import { formatDistanceToNow } from '../../utils/dateUtils';

const getNotificationIcon = (type) => {
  const icons = {
    withdrawal: '💰',
    commission: '💵',
    kyc: '🆔',
    system: '📢',
    payment: '💳',
    challenge: '🎯',
  };
  return icons[type] || '📬';
};

const getPriorityColor = (priority) => ({
  low: 'bg-gray-400',
  normal: 'bg-blue-500',
  high: 'bg-yellow-500',
  urgent: 'bg-red-500',
}[priority] || 'bg-blue-500');

export default function NotificationDropdown({ onClose }) {
  const navigate = useNavigate();
  const role = useAuthStore((state) => state.user?.role);
  const notifications = useNotificationStore((state) => state.dropdownNotifications);
  const loading = useNotificationStore((state) => state.dropdownLoading);
  const error = useNotificationStore((state) => state.dropdownError);
  const fetchNotifications = useNotificationStore((state) => state.fetchNotifications);
  const markAsRead = useNotificationStore((state) => state.markAsRead);
  const markAllAsRead = useNotificationStore((state) => state.markAllAsRead);
  const deleteNotification = useNotificationStore((state) => state.deleteNotification);

  useEffect(() => {
    fetchNotifications(1, {}, { scope: 'dropdown', perPage: 10 });
  }, [fetchNotifications]);

  const handleNotificationClick = async (notification) => {
    if (!notification.is_read) {
      const marked = await markAsRead(notification.id);
      if (!marked) return;
    }
    navigate(notificationDestination(notification.type, role));
    onClose?.();
  };

  const handleDelete = async (event, notificationId) => {
    event.stopPropagation();
    await deleteNotification(notificationId);
  };

  return (
    <div className="flex flex-col" aria-live="polite">
      <div className="flex justify-between items-center p-4 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Bell className="w-5 h-5 text-white" />
          <h3 className="text-lg font-semibold text-white">Notifications</h3>
        </div>
        {notifications.length > 0 && (
          <button
            type="button"
            onClick={() => markAllAsRead()}
            className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            Mark all read
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="m-3 rounded border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {loading ? (
        <div className="flex justify-center p-8">
          <Loader className="w-8 h-8 text-blue-500 animate-spin" />
        </div>
      ) : notifications.length === 0 ? (
        <div className="p-8 text-center">
          <p className="text-gray-400">No notifications</p>
        </div>
      ) : (
        <div className="max-h-96 overflow-y-auto">
          {notifications.map((notification) => (
            <div
              key={notification.id}
              onClick={() => handleNotificationClick(notification)}
              className={`flex items-start gap-3 p-4 border-b border-white/5 cursor-pointer transition-colors ${
                notification.is_read ? 'hover:bg-white/5' : 'bg-white/10 hover:bg-white/15'
              }`}
            >
              <div className="text-2xl flex-shrink-0" aria-hidden="true">
                {getNotificationIcon(notification.type)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <p className={`text-sm ${notification.is_read ? 'text-gray-300' : 'text-white font-semibold'}`}>
                    {notification.title}
                  </p>
                  {!notification.is_read && <div className={`w-2 h-2 rounded-full ${getPriorityColor(notification.priority)}`} />}
                </div>
                <p className="text-sm text-gray-400 mb-1 line-clamp-2">{notification.message}</p>
                <p className="text-xs text-gray-500">
                  {notification.created_at ? formatDistanceToNow(new Date(notification.created_at), { addSuffix: true }) : 'Recently'}
                </p>
              </div>
              <button
                type="button"
                aria-label={`Delete ${notification.title}`}
                onClick={(event) => handleDelete(event, notification.id)}
                className="flex-shrink-0 p-1 text-gray-400 hover:text-red-400 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {notifications.length > 0 && (
        <div className="p-2 border-t border-white/10">
          <button
            type="button"
            onClick={() => {
              navigate('/notifications');
              onClose?.();
            }}
            className="w-full py-2 text-sm text-blue-400 hover:text-blue-300 hover:bg-white/5 rounded transition-colors"
          >
            View All Notifications
          </button>
        </div>
      )}
    </div>
  );
}
