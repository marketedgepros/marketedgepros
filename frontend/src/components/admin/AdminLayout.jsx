import { useState, useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import useAuthStore from '../../store/authStore';
import {
  LayoutDashboard,
  Users,
  CreditCard,
  DollarSign,
  CheckCircle,
  BarChart3,
  Settings,
  LogOut,
  Menu,
  X,
  Shield,
  ChevronRight,
  LifeBuoy,
  Award,
} from 'lucide-react';
import NotificationBell from '../notifications/NotificationBell';

export default function AdminLayout({ children }) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const mobileMenuButtonRef = useRef(null);
  const closeMobileMenuButtonRef = useRef(null);
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();

  const menuItems = [
    { title: 'Dashboard', path: '/admin/dashboard', icon: LayoutDashboard },
    { title: 'Users', path: '/admin/users', icon: Users },
    { title: 'Programs', path: '/admin/programs', icon: BarChart3 },
    { title: 'Challenges', path: '/admin/challenges', icon: Award },
    { title: 'Payments', path: '/admin/payments', icon: CreditCard },
    { title: 'Withdrawals', path: '/admin/withdrawals', icon: DollarSign },
    { title: 'CRM', path: '/admin/crm', icon: Users },
    { title: 'KYC Approval', path: '/admin/kyc-approval', icon: CheckCircle },
    { title: 'Payment Approvals', path: '/admin/payment-approvals', icon: CheckCircle },
    { title: 'Analytics', path: '/admin/analytics', icon: BarChart3 },
    { title: 'Settings', path: '/admin/settings', icon: Settings },
  ];

  const isActive = (path) => {
    return location.pathname === path;
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const closeMobileMenu = () => {
    setIsMobileMenuOpen(false);
    mobileMenuButtonRef.current?.focus();
  };

  // A route change closes the navigation rather than leaving it over new content.
  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isMobileMenuOpen) return undefined;

    // The previous effect could run while the formerly invisible sidebar was
    // still hidden by the browser. Focus after its visibility has been painted.
    let paintedFocusFrame;
    const focusFrame = window.requestAnimationFrame(() => {
      paintedFocusFrame = window.requestAnimationFrame(() => closeMobileMenuButtonRef.current?.focus());
    });
    const handleEscape = (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closeMobileMenu();
    };
    document.addEventListener('keydown', handleEscape);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      if (paintedFocusFrame !== undefined) window.cancelAnimationFrame(paintedFocusFrame);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isMobileMenuOpen]);

  return (
    <div className="flex h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white overflow-hidden">
      {/* Sidebar */}
      <aside
        id="admin-navigation"
        aria-label="Administration navigation"
        className={`
          fixed lg:static inset-y-0 left-0 z-40
          w-72 bg-slate-800/30 backdrop-blur-xl border-r border-white/10
          transform transition-transform duration-200 ease-in-out motion-reduce:transition-none
          ${isMobileMenuOpen ? 'visible translate-x-0' : 'invisible lg:visible -translate-x-full lg:translate-x-0'}
          flex flex-col
        `}
      >
        {/* Logo & Close Button */}
        <div className="flex items-center justify-between p-6 border-b border-white/10">
          <Link to="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-teal-500 flex items-center justify-center shadow-lg shadow-cyan-500/30">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-cyan-400 to-teal-400 bg-clip-text text-transparent">
                Admin Panel
              </h1>
              <p className="text-xs text-gray-400">Management Console</p>
            </div>
          </Link>
          <button
            ref={closeMobileMenuButtonRef}
            type="button"
            onClick={closeMobileMenu}
            aria-label="Close administration menu"
            aria-controls="admin-navigation"
            className="lg:hidden p-2 rounded-lg hover:bg-slate-700/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        {/* User Info */}
        <div className="p-4 border-b border-white/10">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-500 to-teal-500 flex items-center justify-center text-white font-semibold">
              {user?.first_name?.[0]}{user?.last_name?.[0]}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-white truncate">{user?.first_name} {user?.last_name}</p>
              <p className="text-xs text-gray-400 truncate">{user?.email}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-gradient-to-r from-cyan-500/10 to-teal-500/10 text-cyan-400 rounded-lg border border-cyan-500/30">
              <Shield className="w-3 h-3" />
              Administrator
            </span>
          </div>
        </div>
        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto p-4 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
          <ul className="space-y-1.5">
            {menuItems.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.path);
              
              return (
                <li key={item.path}>
                  <Link
                    to={item.path}
                    onClick={closeMobileMenu}
                    aria-current={active ? 'page' : undefined}
                    className={`
                      group flex items-center gap-3 px-4 py-3 rounded-xl
                      transition-all duration-200 motion-reduce:transition-none relative overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400
                      ${
                        active
                          ? 'bg-gradient-to-r from-cyan-500 to-teal-500 text-white shadow-lg shadow-cyan-500/30'
                          : 'text-gray-300 hover:bg-slate-700/30 hover:text-white'
                      }
                    `}
                  >
                    {/* Hover Effect */}
                    {!active && (
                      <div className="absolute inset-0 bg-gradient-to-r from-cyan-500/10 to-teal-500/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
                    )}
                    
                    <Icon className="w-5 h-5 relative z-10" />
                    <span className="font-medium relative z-10">{item.title}</span>
                    {active && (
                      <ChevronRight className="w-4 h-4 ml-auto relative z-10" />
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        {/* Logout */}
        <div className="p-4 border-t border-white/10">
          <button
            type="button"
            onClick={handleLogout}
            className="group flex items-center gap-3 px-4 py-3 rounded-xl text-gray-300 hover:bg-red-500/10 hover:text-red-400 transition-all duration-200 w-full border border-transparent hover:border-red-500/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
          >
            <LogOut className="w-5 h-5" />
            <span className="font-medium">Logout</span>
          </button>
        </div>
      </aside>
      {/* Mobile Overlay */}
      {isMobileMenuOpen && (
        <div
          onClick={closeMobileMenu}
          className="lg:hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-30"
        ></div>
      )}
      {/* Main Content */}
      <main className="min-w-0 flex-1 overflow-y-auto relative">
        {/* Top Bar */}
        <div className="sticky top-0 z-20 bg-slate-800/50 backdrop-blur-xl border-b border-white/10 px-4 sm:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="min-w-0 flex items-center gap-2 sm:gap-4">
              <button
                ref={mobileMenuButtonRef}
                type="button"
                onClick={() => setIsMobileMenuOpen(true)}
                aria-label="Open administration menu"
                aria-controls="admin-navigation"
                aria-expanded={isMobileMenuOpen}
                className="lg:hidden p-2 rounded-xl bg-slate-700/30 hover:bg-slate-700/50 transition-all duration-200"
              >
                <Menu className="w-5 h-5" />
              </button>
              <h2 className="truncate text-base sm:text-2xl font-bold text-white">
                {menuItems.find(item => isActive(item.path))?.title || 'Dashboard'}
              </h2>
            </div>
            
            <div className="flex items-center gap-3">
              <Link to="/support/my-tickets" aria-label="My support tickets"
                className="p-2 rounded-xl text-gray-300 hover:bg-slate-700/50 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                <LifeBuoy className="h-5 w-5" aria-hidden="true" />
              </Link>
              
              {/* Notifications */}
              <NotificationBell />
            </div>
          </div>
        </div>
        {/* Page Content */}
        <div className="relative z-10">
          {children}
        </div>
      </main>
    </div>
  );
}
