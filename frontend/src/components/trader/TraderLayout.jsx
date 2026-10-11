import { Link, useLocation, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, TrendingUp, DollarSign, FileText, 
  User, LogOut, Menu, X, Wallet, MessageSquare
} from 'lucide-react';
import { useState } from 'react';
import useAuthStore from '../../store/authStore';
import NotificationBell from '../notifications/NotificationBell';

export default function TraderLayout({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const navigation = [
    { name: 'Dashboard', href: '/trader', icon: LayoutDashboard },
    { name: 'Wallet', href: '/wallet', icon: Wallet },
    { name: 'Trading History', href: '/trader/history', icon: TrendingUp },
    { name: 'Withdrawals', href: '/trader/withdrawals', icon: DollarSign },
    { name: 'Documents', href: '/trader/documents', icon: FileText },
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
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed top-0 left-0 z-50 h-full w-64 bg-slate-800/95 backdrop-blur-sm border-r border-white/10 transform transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center justify-between h-16 px-6 border-b border-white/10">
            <Link to="/trader" className="flex items-center space-x-2">
              <div className="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-500 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-xl">M</span>
              </div>
              <span className="text-white font-bold text-lg">MarketEdgePros</span>
            </Link>
            <button
              onClick={() => setSidebarOpen(false)}
              className="lg:hidden text-gray-400 hover:text-white transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
          </div>

          {/* User Info */}
          <div className="px-6 py-4 border-b border-white/10">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full flex items-center justify-center">
                <span className="text-white font-semibold text-sm">
                  {user?.first_name?.charAt(0) || user?.name?.charAt(0) || 'T'}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">
                  {user?.first_name || user?.name || 'Trader'}
                </p>
                <p className="text-xs text-gray-400 truncate">{user?.email}</p>
              </div>
            </div>
            <div className="mt-3">
              <span className="inline-block px-3 py-1 text-xs font-medium bg-gradient-to-r from-blue-600/20 to-purple-600/20 text-blue-400 rounded-full border border-blue-500/30">
                Trader
              </span>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto">
            {navigation.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.href;
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-blue-600/20 to-purple-600/20 text-white font-medium border border-blue-500/30 shadow-lg shadow-blue-500/10'
                      : 'text-gray-300 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                  {item.name}
                </Link>
              );
            })}
          </nav>

          {/* Logout */}
          <div className="p-4 border-t border-white/10">
            <button
              onClick={handleLogout}
              className="flex items-center gap-3 px-3 py-2.5 w-full text-gray-300 hover:bg-red-500/10 hover:text-red-400 rounded-lg transition-all"
            >
              <LogOut className="w-5 h-5" />
              Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="lg:pl-64">
        {/* One header and one notification consumer at every viewport width. */}
        <div className="sticky top-0 z-30 flex items-center justify-between lg:justify-end h-16 px-4 bg-slate-800/95 backdrop-blur-sm border-b border-white/10">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden text-gray-300 hover:text-white transition-colors"
          >
            <Menu className="w-6 h-6" />
          </button>
          <Link to="/trader" className="lg:hidden flex items-center space-x-2">
            <div className="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-500 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-xl">M</span>
            </div>
            <span className="text-white font-bold text-lg">MarketEdgePros</span>
          </Link>
          <NotificationBell />
        </div>

        {/* Page content */}
        <main className="min-h-screen bg-slate-900">{children}</main>
      </div>
    </div>
  );
}
