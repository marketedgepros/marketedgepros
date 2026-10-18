import { useEffect, useRef, useState } from 'react';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import { postLoginDestination } from '../services/navigationService.js';
import Layout from '../components/layout/Layout';
import useAuthStore from '../store/authStore';
import { LogIn, Mail, Lock, AlertCircle } from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    login,
    login2FA,
    pending2FA,
    cancel2FA,
    error,
    clearError,
  } = useAuthStore();

  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });

  const [requires2FA, setRequires2FA] = useState(false);
  const [userId, setUserId] = useState(null);
  const [twoFactorToken, setTwoFactorToken] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const mountedRef = useRef(false);
  const attemptRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      attemptRef.current += 1;
      // A password-proof challenge must not survive leaving this route.
      cancel2FA();
    };
  }, [cancel2FA]);

  const isCurrentAttempt = (attempt) => mountedRef.current && attempt === attemptRef.current;

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
    clearError();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const attempt = attemptRef.current + 1;
    attemptRef.current = attempt;
    setIsLoading(true);

    try {
      const result = await login(formData.email, formData.password);
      if (!isCurrentAttempt(attempt) || result?.stale) return;

      if (result.requires2FA) {
        setRequires2FA(true);
        setUserId(result.userId);
      } else {
        navigate(postLoginDestination(result.user, location.search), { replace: true });
      }
    } catch {
      // authStore owns login errors; its state is rendered below.
      if (!isCurrentAttempt(attempt)) return;
    } finally {
      if (isCurrentAttempt(attempt)) setIsLoading(false);
    }
  };

  const handle2FASubmit = async (e) => {
    e.preventDefault();
    const attempt = attemptRef.current + 1;
    attemptRef.current = attempt;
    setIsLoading(true);

    try {
      const result = await login2FA(userId, twoFactorToken);
      if (!isCurrentAttempt(attempt) || result?.stale) return;
      navigate(postLoginDestination(result.user, location.search), { replace: true });
    } catch (err) {
      // Verification failures deliberately invalidate the single-use pending challenge.
      if (!isCurrentAttempt(attempt)) return;
      setRequires2FA(false);
      setUserId(null);
      setTwoFactorToken('');
    } finally {
      if (isCurrentAttempt(attempt)) setIsLoading(false);
    }
  };

  if (requires2FA && pending2FA) {
    return (
      <Layout>
        <div className="mep-screen min-h-[calc(100vh-200px)] flex items-center justify-center px-4 py-12">
          <div className="max-w-md w-full">
            <div className="mep-panel backdrop-blur-xl border rounded-2xl shadow-2xl p-8">
              <div className="text-center mb-8">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-cyan-500/20 to-teal-500/20 rounded-full mb-4 border border-cyan-500/30">
                  <Lock className="w-8 h-8 text-cyan-400" aria-hidden="true" />
                </div>
                <h1 className="mep-heading text-2xl font-bold text-white">Two-Factor Authentication</h1>
                <label htmlFor="two-factor-code" className="block text-gray-400 mt-2">
                  Enter the 6-digit code from your authenticator app
                </label>
              </div>

              {error && (
                <div role="alert" className="mb-4 p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
                  <p className="text-sm text-red-300">{error}</p>
                </div>
              )}

              <form onSubmit={handle2FASubmit} className="space-y-6">
                <div>
                  <input
                    id="two-factor-code"
                    type="text"
                    value={twoFactorToken}
                    onChange={(e) => {
                      setTwoFactorToken(e.target.value.replace(/\D/g, ''));
                      clearError();
                    }}
                    placeholder="000000"
                    maxLength="6"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]{6}"
                    className="w-full px-4 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-center text-2xl tracking-widest text-white placeholder-gray-500"
                    required
                    autoFocus
                  />
                </div>

                <button
                  type="submit"
                  disabled={isLoading || twoFactorToken.length !== 6}
                  className="mep-primary w-full py-3 px-4 font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isLoading ? 'Verifying...' : 'Verify'}
                </button>

                <button
                  type="button"
                  onClick={() => {
                    attemptRef.current += 1;
                    cancel2FA();
                    setIsLoading(false);
                    setRequires2FA(false);
                    setUserId(null);
                    setTwoFactorToken('');
                    clearError();
                  }}
                  className="w-full bg-slate-700/50 text-gray-300 py-3 px-4 rounded-lg font-semibold hover:bg-slate-700 transition-colors border border-white/10"
                >
                  Back to Login
                </button>
              </form>
            </div>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="mep-screen min-h-[calc(100vh-200px)] flex items-center justify-center px-4 py-12">
        <div className="max-w-md w-full">
          {/* Decorative Background Elements */}
          <div className="absolute inset-0 overflow-hidden pointer-events-none">
            <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl"></div>
            <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-teal-500/10 rounded-full blur-3xl"></div>
          </div>

          <div className="mep-panel relative backdrop-blur-xl border rounded-2xl shadow-2xl p-8">
            <div className="text-center mb-8">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-cyan-500 to-teal-500 rounded-full mb-4 shadow-lg shadow-cyan-500/30">
                <LogIn className="w-8 h-8 text-white" aria-hidden="true" />
              </div>
              <h1 className="mep-heading text-3xl font-bold text-white">Welcome Back</h1>
              <p className="text-gray-400 mt-2">Sign in to your MarketEdgePros account</p>
            </div>

            {error && (
              <div role="alert" className="mb-4 p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
                <p className="text-sm text-red-300">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label htmlFor="login-email" className="block text-sm font-medium text-gray-300 mb-2">
                  Email Address
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" aria-hidden="true" />
                  <input
                    id="login-email"
                    type="email"
                    name="email"
                    value={formData.email}
                    onChange={handleChange}
                    placeholder="you@example.com"
                    autoComplete="email"
                    className="w-full pl-10 pr-4 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-white placeholder-gray-500"
                    required
                  />
                </div>
              </div>

              <div>
                <label htmlFor="login-password" className="block text-sm font-medium text-gray-300 mb-2">
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" aria-hidden="true" />
                  <input
                    id="login-password"
                    type="password"
                    name="password"
                    value={formData.password}
                    onChange={handleChange}
                    placeholder="••••••••"
                    autoComplete="current-password"
                    className="w-full pl-10 pr-4 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-white placeholder-gray-500"
                    required
                  />
                </div>
              </div>

              <div className="flex justify-end">
                <Link to="/forgot-password" className="text-sm text-cyan-400 hover:text-cyan-300 font-medium">
                  Forgot password?
                </Link>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="mep-primary w-full py-3 px-4 font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? 'Signing in...' : 'Sign In'}
              </button>
            </form>

            <div className="mt-6 text-center">
              <p className="text-sm text-gray-400">
                Don't have an account?{' '}
                <Link to="/register" className="text-cyan-400 hover:text-cyan-300 font-medium">
                  Sign up
                </Link>
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
