import { useState, useEffect, useRef } from 'react';
import { X, CheckCircle, XCircle, AlertCircle, Info } from 'lucide-react';
import { notificationService } from '../services/notifications';

export default function Notification() {
  const [notifications, setNotifications] = useState([]);
  const timeoutsRef = useRef(new Map());

  useEffect(() => {
    const unsubscribe = notificationService.subscribe((notification) => {
      setNotifications(prev => {
        const MAX_NOTIFICATIONS = 5;
        const newNotifications = [...prev, notification];
        return newNotifications.slice(-MAX_NOTIFICATIONS);
      });

      // Auto remove after duration
      const timeoutId = setTimeout(() => {
        removeNotification(notification.id);
      }, notification.duration);
      
      timeoutsRef.current.set(notification.id, timeoutId);
    });

    return () => {
      unsubscribe();
      // Clear all pending timeouts
      timeoutsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
      timeoutsRef.current.clear();
    };
  }, []);

  const removeNotification = (id) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
    // Clear the timeout if it exists
    const timeoutId = timeoutsRef.current.get(id);
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutsRef.current.delete(id);
    }
  };

  const getIcon = (type) => {
    switch (type) {
      case 'success':
        return <CheckCircle className="text-green-500" size={20} />;
      case 'error':
        return <XCircle className="text-red-500" size={20} />;
      case 'warning':
        return <AlertCircle className="text-yellow-500" size={20} />;
      case 'info':
      default:
        return <Info className="text-blue-500" size={20} />;
    }
  };

  const getBackgroundColor = (type) => {
    switch (type) {
      case 'success':
        return 'bg-green-50 border-green-200';
      case 'error':
        return 'bg-red-50 border-red-200';
      case 'warning':
        return 'bg-yellow-50 border-yellow-200';
      case 'info':
      default:
        return 'bg-blue-50 border-blue-200';
    }
  };

  if (notifications.length === 0) return null;

  return (
    <div className="fixed top-4 inset-x-4 sm:left-auto sm:w-96 z-50 space-y-2 pointer-events-none" aria-label="Notifications">
      {notifications.map((notification) => (
        <div
          key={notification.id}
          role={notification.type === 'error' ? 'alert' : 'status'}
          className={`flex min-w-0 items-center gap-3 px-4 py-3 rounded-lg border shadow-lg pointer-events-auto ${getBackgroundColor(notification.type)}`}
        >
          {getIcon(notification.type)}
          <p className="min-w-0 flex-1 break-words text-sm text-gray-800">{notification.message}</p>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => removeNotification(notification.id)}
            className="shrink-0 rounded-lg p-2 text-gray-500 hover:text-gray-700"
          >
            <X size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
