import { useState, useEffect } from 'react';
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
  Search,
  Bell,
  FileText,
  Mail,
  Award,
} from 'lucide-react';
import NotificationDropdown from '../notifications/NotificationDropdown';

export default function AdminLayout({ children }) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
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

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (isSearchOpen && !e.target.closest('.search-dropdown')) {
        setIsSearchOpen(false);
      }
      if (isNotificationsOpen && !e.target.closest('.notifications-dropdown')) {
        setIsNotificationsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isSearchOpen, isNotificationsOpen]);

  return (
    <div className="flex h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`
          fixed lg:static inset-y-0 left-0 z-40
          w-72 bg-slate-800/30 backdrop-blur-xl border-r border-white/10
          transform transition-transform duration-300 ease-in-out
          ${isMobileMenuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
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
            onClick={() => setIsMobileMenuOpen(false)}
            className="lg:hidden p-2 rounded-lg hover:bg-slate-700/50 transition-colors"
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
                    onClick={() => setIsMobileMenuOpen(false)}
                    className={`
                      group flex items-center gap-3 px-4 py-3 rounded-xl
                      transition-all duration-200 relative overflow-hidden
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
                    
                    <Icon className={`w-5 h-5 relative z-10 ${active ? 'animate-pulse' : ''}`} />
                    <span className="font-medium relative z-10">{item.title}</span>
                    {active && (
                      <ChevronRight className="w-4 h-4 ml-auto relative z-10 animate-pulse" />
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
            onClick={handleLogout}
            className="group flex items-center gap-3 px-4 py-3 rounded-xl text-gray-300 hover:bg-red-500/10 hover:text-red-400 transition-all duration-200 w-full border border-transparent hover:border-red-500/30"
          >
            <LogOut className="w-5 h-5 group-hover:animate-pulse" />
            <span className="font-medium">Logout</span>
          </button>
        </div>
      </aside>
      {/* Mobile Overlay */}
      {isMobileMenuOpen && (
        <div
          onClick={() => setIsMobileMenuOpen(false)}
          className="lg:hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-30"
        ></div>
      )}
      {/* Main Content */}
      <main className="flex-1 overflow-y-auto relative">
        {/* Top Bar */}
        <div className="sticky top-0 z-20 bg-slate-800/50 backdrop-blur-xl border-b border-white/10 px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => setIsMobileMenuOpen(true)}
                className="lg:hidden p-2 rounded-xl bg-slate-700/30 hover:bg-slate-700/50 transition-all duration-200"
              >
                <Menu className="w-5 h-5" />
              </button>
              <h2 className="text-2xl font-bold text-white">
                {menuItems.find(item => isActive(item.path))?.title || 'Dashboard'}
              </h2>
            </div>
            
            <div className="flex items-center gap-3">
              {/* Search */}
              <div className="relative search-dropdown">
                <button 
                  onClick={() => {
                    setIsSearchOpen(!isSearchOpen);
                    setIsNotificationsOpen(false);
                  }}
                  className="p-2 rounded-xl bg-slate-700/30 hover:bg-slate-700/50 text-gray-300 hover:text-white transition-all duration-200"
                >
                  <Search className="w-5 h-5" />
                </button>
                
                {/* Search Dropdown */}
                {isSearchOpen && (
                  <div className="absolute top-full right-0 mt-2 w-96 bg-slate-800/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl p-4 z-30">
                    <input
                      type="text"
                      placeholder="Search users, transactions, data..."
                      autoFocus
                      className="w-full px-4 py-3 bg-slate-900/50 border border-white/10 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                    />
                    <p className="text-sm text-gray-400 mt-3">Press Enter to search</p>
                  </div>
                )}
              </div>
              
              {/* Notifications */}
              <div className="relative notifications-dropdown">
                <button 
                  onClick={() => {
                    setIsNotificationsOpen(!isNotificationsOpen);
                    setIsSearchOpen(false);
                  }}
                  className="relative p-2 rounded-xl bg-slate-700/30 hover:bg-slate-700/50 text-gray-300 hover:text-white transition-all duration-200"
                >
                  <Bell className="w-5 h-5" />
                  <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>
                </button>
                
                {/* Notifications Dropdown */}
                {isNotificationsOpen && (
                  <div className="absolute top-full right-0 mt-2 w-96 bg-slate-800/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl overflow-hidden z-30">
                    <NotificationDropdown onClose={() => setIsNotificationsOpen(false)} />
                  </div>
                )}
              </div>
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
