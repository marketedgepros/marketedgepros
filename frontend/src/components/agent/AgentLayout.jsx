import { Link, useLocation, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, Users, DollarSign, BarChart3, 
  User, LogOut, Menu, X, MessageSquare
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import useAuthStore from '../../store/authStore';
import NotificationBell from '../notifications/NotificationBell';

export default function AffiliateLayout({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const menuButtonRef = useRef(null);
  const closeButtonRef = useRef(null);
  const sidebarId = 'affiliate-navigation';

  const closeSidebar = (restoreFocus = false) => {
    setSidebarOpen(false);
    if (restoreFocus) menuButtonRef.current?.focus();
  };

  useEffect(() => {
    if (!sidebarOpen) return undefined;

    closeButtonRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeSidebar(true);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [sidebarOpen]);

  const navigation = [
    { name: 'Dashboard', href: '/affiliate/dashboard', icon: LayoutDashboard },
    { name: 'My Traders', href: '/affiliate/traders', icon: Users },
    { name: 'Commissions', href: '/affiliate/commissions', icon: DollarSign },
    { name: 'Reports', href: '/affiliate/reports', icon: BarChart3 },
    { name: 'Profile', href: '/profile', icon: User },
    { name: 'My Support Tickets', href: '/support/my-tickets', icon: MessageSquare },
  ];

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-40 lg:hidden"
          aria-hidden="true"
          onClick={() => closeSidebar(true)}
        />
      )}

      {/* Sidebar */}
      <aside
        id={sidebarId}
        aria-label="Affiliate navigation"
        className={`fixed top-0 left-0 z-50 h-full w-64 bg-slate-800/95 backdrop-blur-sm border-r border-white/10 transform transition-transform duration-200 ease-in-out lg:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center justify-between h-16 px-6 border-b border-white/10">
            <Link to="/affiliate/dashboard" onClick={() => setSidebarOpen(false)} className="flex min-w-0 items-center space-x-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-800">
              <div className="w-8 h-8 shrink-0 bg-gradient-to-r from-cyan-400 to-cyan-500 rounded-lg flex items-center justify-center" aria-hidden="true">
                <span className="text-white font-bold text-xl">M</span>
              </div>
              <span className="min-w-0 truncate text-white font-bold text-lg">MarketEdgePros</span>
            </Link>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={() => closeSidebar(true)}
              aria-label="Close navigation menu"
              className="lg:hidden rounded p-1 text-gray-400 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
            >
              <X className="w-6 h-6" aria-hidden="true" />
            </button>
          </div>

          {/* User Info */}
          <div className="px-6 py-4 border-b border-white/10">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 shrink-0 bg-gradient-to-r from-cyan-400 to-cyan-500 rounded-full flex items-center justify-center" aria-hidden="true">
                <span className="text-white font-semibold text-sm">
                  {user?.first_name?.charAt(0) || user?.name?.charAt(0) || 'A'}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">
                  {user?.first_name || user?.name || 'Affiliate'}
                </p>
                <p className="text-xs text-gray-400 truncate">{user?.email}</p>
              </div>
            </div>
            <div className="mt-3">
              <span className="inline-block px-3 py-1 text-xs font-medium bg-cyan-400/10 text-cyan-300 rounded-full border border-cyan-400/30">
                Affiliate
              </span>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto" aria-label="Affiliate navigation links">
            {navigation.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.href;
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  onClick={() => setSidebarOpen(false)}
                  aria-current={isActive ? 'page' : undefined}
                  className={`flex min-w-0 items-center gap-3 px-3 py-2.5 rounded-lg transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-800 ${
                    isActive
                      ? 'bg-cyan-400/10 text-white font-medium border border-cyan-400/30 shadow-lg shadow-cyan-400/10'
                      : 'text-gray-300 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <Icon className="w-5 h-5 shrink-0" aria-hidden="true" />
                  <span className="min-w-0 truncate">{item.name}</span>
                </Link>
              );
            })}
          </nav>

          {/* Logout */}
          <div className="p-4 border-t border-white/10">
            <button
              type="button"
              onClick={handleLogout}
              className="flex items-center gap-3 px-3 py-2.5 w-full rounded-lg text-gray-300 transition-all hover:bg-red-500/10 hover:text-red-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-800"
            >
              <LogOut className="w-5 h-5" aria-hidden="true" />
              Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="min-w-0 lg:pl-64">
        {/* One header and one notification consumer at every viewport width. */}
        <div className="sticky top-0 z-30 flex items-center justify-between lg:justify-end h-16 px-4 bg-slate-800/95 backdrop-blur-sm border-b border-white/10">
          <button
            ref={menuButtonRef}
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-controls={sidebarId}
            aria-expanded={sidebarOpen}
            aria-label="Open navigation menu"
            className="lg:hidden rounded p-1 text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
          >
            <Menu className="w-6 h-6" aria-hidden="true" />
          </button>
          <Link to="/affiliate/dashboard" className="lg:hidden flex min-w-0 items-center space-x-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-800">
            <div className="w-8 h-8 shrink-0 bg-gradient-to-r from-cyan-400 to-cyan-500 rounded-lg flex items-center justify-center" aria-hidden="true">
              <span className="text-white font-bold text-xl">M</span>
            </div>
            <span className="min-w-0 truncate text-white font-bold text-lg">MarketEdgePros</span>
          </Link>
          <NotificationBell />
        </div>

        {/* Page content */}
        <main className="min-w-0 min-h-screen bg-slate-900">{children}</main>
      </div>
    </div>
  );
}
