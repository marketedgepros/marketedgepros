import { useEffect, useRef, useState } from 'react';
import { Bell } from 'lucide-react';
import useNotificationStore from '../../stores/notificationStore';
import NotificationDropdown from './NotificationDropdown';
import useAuthStore from '../../store/authStore';

const actorIdentity = (state) => JSON.stringify([
  state.isAuthenticated,
  state.user?.id ?? null,
  state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
  state.user?.role ?? null,
]);

export default function NotificationBell() {
  const context = useAuthStore(actorIdentity);
  return <NotificationBellView key={context} />;
}

function NotificationBellView() {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);
  const buttonRef = useRef(null);
  const unreadCount = useNotificationStore((state) => state.unreadCount);
  const countError = useNotificationStore((state) => state.countError);
  const fetchUnreadCount = useNotificationStore((state) => state.fetchUnreadCount);
  const knownUnreadCount = Number.isSafeInteger(unreadCount) && unreadCount >= 0 ? unreadCount : null;

  useEffect(() => { fetchUnreadCount(); }, [fetchUnreadCount]);
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target) && buttonRef.current && !buttonRef.current.contains(event.target)) setIsOpen(false);
    };
    const handleEscape = (event) => { if (event.key === 'Escape') setIsOpen(false); };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => { document.removeEventListener('mousedown', handleClickOutside); document.removeEventListener('keydown', handleEscape); };
  }, []);

  const handleClick = () => {
    const opening = !isOpen;
    setIsOpen(opening);
    if (opening) fetchUnreadCount();
  };

  return <div className="relative">
    <button ref={buttonRef} type="button" onClick={handleClick} aria-controls="notification-dropdown" aria-expanded={isOpen}
      className="relative rounded-lg p-2 text-slate-300 transition-colors hover:bg-cyan-300/10 hover:text-cyan-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300"
      aria-label={countError ? `Notifications: ${countError}` : 'Notifications'} title={countError || 'Notifications'}>
      <Bell className="h-6 w-6" aria-hidden="true" />
      {knownUnreadCount > 0 && <span className="absolute right-1 top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-cyan-400 px-1 text-xs font-bold text-slate-950">{knownUnreadCount > 99 ? '99+' : knownUnreadCount}</span>}
    </button>
    {isOpen && <div id="notification-dropdown" ref={dropdownRef} className="mep-panel absolute right-0 z-50 mt-2 max-h-[600px] w-96 max-w-[calc(100vw-2rem)] rounded-lg border shadow-xl"><NotificationDropdown onClose={() => setIsOpen(false)} /></div>}
  </div>;
}
