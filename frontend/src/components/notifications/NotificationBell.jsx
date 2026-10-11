import { useEffect, useRef, useState } from 'react';
import { Bell } from 'lucide-react';
import useNotificationStore from '../../stores/notificationStore';
import NotificationDropdown from './NotificationDropdown';
import useAuthStore from '../../store/authStore';

export default function NotificationBell() {
  const context = useAuthStore((state) => JSON.stringify([
    state.isAuthenticated, state.user?.id ?? null,
    state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
  ]));
  return <NotificationBellView key={context} />;
}

function NotificationBellView() {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);
  const buttonRef = useRef(null);
  const unreadCount = useNotificationStore((state) => state.unreadCount);
  const countError = useNotificationStore((state) => state.countError);
  const fetchUnreadCount = useNotificationStore((state) => state.fetchUnreadCount);

  // One initial request only. Updates are user-initiated; notification polling is not used.
  useEffect(() => {
    fetchUnreadCount();
  }, [fetchUnreadCount]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (
        dropdownRef.current
        && !dropdownRef.current.contains(event.target)
        && buttonRef.current
        && !buttonRef.current.contains(event.target)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleClick = () => {
    const opening = !isOpen;
    setIsOpen(opening);
    if (opening) fetchUnreadCount();
  };

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={handleClick}
        className="relative p-2 text-gray-300 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
        aria-label={countError ? `Notifications: ${countError}` : 'Notifications'}
        title={countError || 'Notifications'}
        aria-expanded={isOpen}
      >
        <Bell className="w-6 h-6" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 flex items-center justify-center min-w-[18px] h-[18px] px-1 text-xs font-bold text-white bg-red-500 rounded-full">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div
          ref={dropdownRef}
          className="absolute right-0 mt-2 w-96 max-w-[calc(100vw-2rem)] max-h-[600px] bg-slate-800 border border-white/10 rounded-lg shadow-xl z-50"
        >
          <NotificationDropdown onClose={() => setIsOpen(false)} />
        </div>
      )}
    </div>
  );
}
