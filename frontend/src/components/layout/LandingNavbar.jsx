import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Menu, X, LogOut } from 'lucide-react';
import useAuthStore from '../../store/authStore';

export default function LandingNavbar() {
  const [isOpen, setIsOpen] = useState(false);
  const menuButtonRef = useRef(null);
  const navigate = useNavigate();
  const { isAuthenticated, user, logout } = useAuthStore();

  const closeMobileMenu = () => setIsOpen(false);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setIsOpen(false);
      menuButtonRef.current?.focus();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const handleLogout = async () => {
    await logout();
    navigate('/');
  };

  const navLinks = [
    { name: 'How It Works', href: '/#how-it-works' },
    { name: 'Programs', to: '/programs' },
    // { name: 'Features', href: '/#features' }, // Removed - page doesn't exist
    { name: 'About', to: '/about' },
    { name: 'Blog', to: '/blog' },
    { name: 'Support', to: '/support' },
  ];

  return (
    <nav aria-label="Primary navigation" className="mep-chrome fixed top-0 left-0 right-0 z-50 backdrop-blur-xl border-b">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex min-w-0 items-center space-x-2 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
            <div className="mep-brand-mark text-lg" aria-hidden="true">M</div>
            <span className="truncate text-xl font-bold text-white">MarketEdgePros</span>
          </Link>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center space-x-8">
            {navLinks.map((link) => (
              link.to ? (
                <Link
                  key={link.name}
                  to={link.to}
                  className="rounded px-1 py-2 text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  {link.name}
                </Link>
              ) : (
                <a
                  key={link.name}
                  href={link.href}
                  className="rounded px-1 py-2 text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  {link.name}
                </a>
              )
            ))}
          </div>

          {/* CTA Buttons */}
          <div className="hidden md:flex items-center space-x-4">
            {isAuthenticated ? (
              <>
                <Link
                  to="/dashboard"
                  className="rounded px-1 py-2 text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  Dashboard
                </Link>
                <span className="text-gray-400">
                  {user?.first_name || 'User'}
                </span>
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2 px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-all border border-red-500/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  <LogOut size={16} />
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link
                  to="/login"
                  className="rounded px-1 py-2 text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  Login
                </Link>
                <Link
                  to="/programs"
                  className="mep-cta focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
                >
                  View programs
                </Link>
              </>
            )}
          </div>

          {/* Mobile menu button */}
          <button
            ref={menuButtonRef}
            type="button"
            onClick={() => setIsOpen((open) => !open)}
            aria-label={isOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={isOpen}
            aria-controls="mobile-navigation"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-gray-300 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 md:hidden"
          >
            {isOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>

        {/* Mobile Navigation */}
        {isOpen && (
          <div id="mobile-navigation" role="region" aria-label="Mobile navigation" className="md:hidden py-4 space-y-4">
            {navLinks.map((link) => (
              link.to ? (
                <Link
                  key={link.name}
                  to={link.to}
                  className="block rounded px-1 py-2 text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                  onClick={closeMobileMenu}
                >
                  {link.name}
                </Link>
              ) : (
                <a
                  key={link.name}
                  href={link.href}
                  className="block rounded px-1 py-2 text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                  onClick={closeMobileMenu}
                >
                  {link.name}
                </a>
              )
            ))}
            <div className="pt-4 border-t border-white/10 space-y-2">
              {isAuthenticated ? (
                <>
                  <Link
                    to="/dashboard"
                    className="block px-4 py-2 bg-gradient-to-r from-cyan-500 to-teal-500 rounded-lg text-center text-white font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
                    onClick={closeMobileMenu}
                  >
                    Dashboard
                  </Link>
                  <button
                    type="button"
                    onClick={() => { handleLogout(); closeMobileMenu(); }}
                    className="flex items-center justify-center gap-2 w-full px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-all border border-red-500/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                  >
                    <LogOut size={16} />
                    Logout
                  </button>
                </>
              ) : (
                <>
                  <Link
                    to="/login"
                    className="block rounded px-1 py-2 text-center text-gray-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                    onClick={closeMobileMenu}
                  >
                    Login
                  </Link>
                  <Link
                    to="/programs"
                    className="mep-cta w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
                    onClick={closeMobileMenu}
                  >
                    View programs
                  </Link>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}
