import { useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import Layout from '../components/layout/Layout';
import { Lock, AlertCircle, CheckCircle, Eye, EyeOff, Mail } from 'lucide-react';
import api from "../services/api";



export default function ResetPassword() {
  const navigate = useNavigate();
  const location = useLocation();
  const emailFromState = location.state?.email || '';

  const [email, setEmail] = useState(emailFromState);
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  const handleCodeChange = (e) => {
    const value = e.target.value.replace(/\D/g, ''); // Only digits
    if (value.length <= 6) {
      setCode(value);
      setError('');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    // Validate passwords match
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    // Validate password strength
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters long');
      return;
    }

    if (!/[A-Z]/.test(newPassword)) {
      setError('Password must contain at least one uppercase letter');
      return;
    }

    if (!/[a-z]/.test(newPassword)) {
      setError('Password must contain at least one lowercase letter');
      return;
    }

    if (!/[0-9]/.test(newPassword)) {
      setError('Password must contain at least one number');
      return;
    }

    setIsLoading(true);

    try {
      await api.post('/auth/password/reset-with-code', {
        email,
        code,
        new_password: newPassword
      });

      setSuccess(true);
      
      // Redirect to login after 2 seconds
      setTimeout(() => {
        navigate('/login', { state: { message: 'Password reset successfully! Please login with your new password.' } });
      }, 2000);
    } catch (err) {
      setError(err.response?.data?.error || 'Password reset failed. Please check your code and try again.');
    } finally {
      setIsLoading(false);
    }
  };

  if (success) {
    return (
      <Layout>
        <div className="mep-screen min-h-[calc(100vh-200px)] flex items-center justify-center px-4 py-12">
          <div className="max-w-md w-full">
            <div role="status" aria-live="polite" className="mep-panel backdrop-blur-xl border rounded-2xl shadow-2xl p-8 text-center">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-green-500/20 to-emerald-500/20 rounded-full mb-4 border border-green-500/30">
                <CheckCircle className="w-8 h-8 text-green-400" aria-hidden="true" />
              </div>
              <h1 className="mep-heading text-2xl font-bold text-white mb-2">Password Reset Successfully!</h1>
              <p className="text-gray-400 mb-6">
                Your password has been updated. Redirecting to login...
              </p>
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-500 mx-auto"></div>
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
                <Lock className="w-8 h-8 text-white" aria-hidden="true" />
              </div>
              <h1 className="mep-heading text-3xl font-bold text-white">Reset Password</h1>
              <p className="text-gray-400 mt-2">Enter the code from your email and create a new password</p>
            </div>

            {error && (
              <div role="alert" className="mb-4 p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
                <p className="text-sm text-red-300">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label htmlFor="reset-password-email" className="block text-sm font-medium text-gray-300 mb-2">
                  Email Address
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" aria-hidden="true" />
                  <input
                    id="reset-password-email"
                    name="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                    className="w-full pl-10 pr-4 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-white placeholder-gray-500"
                    required
                  />
                </div>
              </div>

              <div>
                <label htmlFor="reset-password-code" className="block text-sm font-medium text-gray-300 mb-2">
                  6-Digit Reset Code
                </label>
                <input
                  id="reset-password-code"
                  name="code"
                  type="text"
                  value={code}
                  onChange={handleCodeChange}
                  placeholder="000000"
                  maxLength="6"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  className="w-full px-4 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-center text-2xl tracking-widest text-white placeholder-gray-500"
                  required
                />
              </div>

              <div>
                <label htmlFor="new-password" className="block text-sm font-medium text-gray-300 mb-2">
                  New Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" aria-hidden="true" />
                  <input
                    id="new-password"
                    name="newPassword"
                    type={showPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    className="w-full pl-10 pr-12 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-white placeholder-gray-500"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? 'Hide new password' : 'Show new password'}
                    aria-controls="new-password"
                    aria-pressed={showPassword}
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-300"
                  >
                    {showPassword ? <EyeOff className="w-5 h-5" aria-hidden="true" /> : <Eye className="w-5 h-5" aria-hidden="true" />}
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  Must be at least 8 characters with uppercase, lowercase, and number. A special character is recommended, not required.
                </p>
              </div>

              <div>
                <label htmlFor="confirm-new-password" className="block text-sm font-medium text-gray-300 mb-2">
                  Confirm New Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" aria-hidden="true" />
                  <input
                    id="confirm-new-password"
                    name="confirmPassword"
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    className="w-full pl-10 pr-12 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-white placeholder-gray-500"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    aria-label={showConfirmPassword ? 'Hide confirm new password' : 'Show confirm new password'}
                    aria-controls="confirm-new-password"
                    aria-pressed={showConfirmPassword}
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-300"
                  >
                    {showConfirmPassword ? <EyeOff className="w-5 h-5" aria-hidden="true" /> : <Eye className="w-5 h-5" aria-hidden="true" />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading || code.length !== 6}
                className="mep-primary w-full py-3 px-4 font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? 'Resetting Password...' : 'Reset Password'}
              </button>
            </form>

            <div className="mt-6 text-center">
              <p className="text-sm text-gray-400">
                Remember your password?{' '}
                <Link to="/login" className="text-cyan-400 hover:text-cyan-300 font-medium">
                  Sign in
                </Link>
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
