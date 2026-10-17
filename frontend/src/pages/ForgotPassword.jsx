import { useEffect, useRef, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import Layout from '../components/layout/Layout';
import { Mail, AlertCircle, CheckCircle, ArrowLeft } from 'lucide-react';
import api from "../services/api";



export default function ForgotPassword() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const isMountedRef = useRef(false);
  const redirectTimerRef = useRef(null);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
    };
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await api.post('/auth/password/reset-request', { email });
      if (!isMountedRef.current) return;
      setSuccess(true);
      
      // Navigate to reset password page after 2 seconds
      redirectTimerRef.current = setTimeout(() => {
        if (!isMountedRef.current) return;
        navigate('/reset-password', { state: { email } });
      }, 2000);
    } catch (err) {
      if (!isMountedRef.current) return;
      setError(err.response?.data?.error || 'Failed to send reset code. Please try again.');
    } finally {
      if (isMountedRef.current) setIsLoading(false);
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
              <h1 className="mep-heading text-2xl font-bold text-white mb-2">Check Your Email</h1>
              <p className="text-gray-400 mb-6">
                If an account exists for <strong className="text-cyan-400">{email}</strong>, a password reset email has been requested. If eligible, use the code on the next page. If nothing arrives, try again later.
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
            <Link 
              to="/login" 
              className="inline-flex items-center gap-2 text-gray-400 hover:text-cyan-400 transition-colors mb-6"
            >
              <ArrowLeft className="w-4 h-4" aria-hidden="true" />
              <span className="text-sm">Back to Login</span>
            </Link>

            <div className="text-center mb-8">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-cyan-500 to-teal-500 rounded-full mb-4 shadow-lg shadow-cyan-500/30">
                <Mail className="w-8 h-8 text-white" aria-hidden="true" />
              </div>
              <h1 className="mep-heading text-3xl font-bold text-white">Forgot Password?</h1>
              <p className="text-gray-400 mt-2">Enter your email to receive a reset code</p>
            </div>

            {error && (
              <div role="alert" className="mb-4 p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
                <p className="text-sm text-red-300">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label htmlFor="reset-email" className="block text-sm font-medium text-gray-300 mb-2">
                  Email Address
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" aria-hidden="true" />
                  <input
                    id="reset-email"
                    name="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full pl-10 pr-4 py-3 bg-slate-900/50 border border-white/10 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-transparent text-white placeholder-gray-500"
                    autoComplete="email"
                    required
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="mep-primary w-full py-3 px-4 font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? 'Sending Code...' : 'Send Reset Code'}
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
