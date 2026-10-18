import { useState, useEffect, useRef } from 'react';
import { useToast } from '../contexts/ToastContext';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import Layout from '../components/layout/Layout';
import { Mail, AlertCircle, CheckCircle, RefreshCw } from 'lucide-react';
import api from '../services/api';

const isValidEmail = (value) => (
  typeof value === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
);

export default function VerifyEmail() {
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const emailFromState = location.state?.email || new URLSearchParams(location.search).get('email') || '';
  const emailDeliveryStatus = location.state?.emailDeliveryStatus;

  const [email, setEmail] = useState(emailFromState);
  const [code, setCode] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const isMountedRef = useRef(false);
  const redirectTimerRef = useRef(null);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (resendCooldown > 0) {
      const timer = setTimeout(() => setResendCooldown(resendCooldown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [resendCooldown]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await api.post('/auth/verify-email', { email, code });
      if (!isMountedRef.current) return;
      setSuccess(true);
      redirectTimerRef.current = setTimeout(() => {
        if (!isMountedRef.current) return;
        navigate('/login', { state: { message: 'Email verified successfully! Please login.' } });
      }, 2000);
    } catch (err) {
      if (!isMountedRef.current) return;
      setError(err.response?.data?.error || 'Verification failed. Please check your code and try again.');
    } finally {
      if (isMountedRef.current) setIsLoading(false);
    }
  };

  const handleResend = async () => {
    if (resendCooldown > 0 || resending) return;
    if (!isValidEmail(email)) {
      setError('Enter a valid email address before requesting a new verification code.');
      return;
    }

    setError('');
    setResending(true);
    try {
      await api.post('/auth/resend-verification', { email });
      if (!isMountedRef.current) return;
      setResendCooldown(120);
      toast.warning('If the account is eligible, a verification email has been requested. If nothing arrives, try again later.');
    } catch {
      if (!isMountedRef.current) return;
      setError('Unable to process the request right now. Please try again.');
    } finally {
      if (isMountedRef.current) setResending(false);
    }
  };

  const handleCodeChange = (e) => {
    const value = e.target.value.replace(/\D/g, '');
    if (value.length <= 6) {
      setCode(value);
      setError('');
    }
  };

  const panelClass = 'w-full max-w-lg rounded-3xl border border-slate-200/80 bg-white p-7 shadow-[0_24px_70px_-36px_rgba(8,47,73,0.5)] sm:p-10';
  const inputClass = 'w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-900 outline-none transition focus-visible:border-cyan-600 focus-visible:ring-2 focus-visible:ring-cyan-600/30 motion-reduce:transition-none';

  if (success) {
    return (
      <Layout>
        <main className="mep-screen min-h-[calc(100vh-200px)] via-white to-cyan-50/70 px-4 py-12">
          <div className="mx-auto flex min-h-[50vh] max-w-3xl items-center justify-center">
            <section className={panelClass + ' text-center'} aria-labelledby="verified-title">
              <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-cyan-50 text-cyan-700 ring-1 ring-cyan-100">
                <CheckCircle className="h-8 w-8" aria-hidden="true" />
              </div>
              <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-cyan-700">Account verification</p>
              <h1 id="verified-title" className="mep-heading text-3xl font-bold tracking-tight text-slate-900">Email verified</h1>
              <p className="mt-3 text-slate-600">Your email has been successfully verified. Redirecting to login…</p>
              <div className="mx-auto mt-7 h-1.5 w-24 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                <div className="h-full w-2/3 animate-pulse rounded-full bg-cyan-600 motion-reduce:animate-none" />
              </div>
            </section>
          </div>
        </main>
      </Layout>
    );
  }

  return (
    <Layout>
      <main className="mep-screen min-h-[calc(100vh-200px)] via-white to-cyan-50/70 px-4 py-12 sm:py-16">
        <div className="mx-auto flex max-w-5xl justify-center">
          <section className={panelClass} aria-labelledby="verify-title">
            <header className="mb-8">
              <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-cyan-50 text-cyan-700 ring-1 ring-cyan-100">
                <Mail className="h-7 w-7" aria-hidden="true" />
              </div>
              <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-cyan-700">Account verification</p>
              <h1 id="verify-title" className="mep-heading text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">Verify your email</h1>
              {emailFromState ? (
                <p className="mt-3 leading-relaxed text-slate-600">Enter the 6-digit verification code for <span className="font-semibold text-slate-800">{email}</span>. If you need a new code, you can request one below.</p>
              ) : (
                <p className="mt-3 leading-relaxed text-slate-600">Enter your email address and the 6-digit verification code to continue. If you need a code, request one below.</p>
              )}
            </header>

            {emailDeliveryStatus === 'unavailable' && (
              <div className="mb-5 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-amber-950" role="status">
                Your account was created, but the verification email was not accepted for delivery. You can request another verification email below.
              </div>
            )}
            {error && (
              <div className="mb-6 flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4" role="alert">
                <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-700" aria-hidden="true" />
                <p className="text-sm text-rose-900">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              {!emailFromState && (
                <div>
                  <label htmlFor="verify-email" className="mb-2 block text-sm font-semibold text-slate-800">Email address</label>
                  <input id="verify-email" name="email" type="email" autoComplete="email" value={email} onChange={(e) => { setEmail(e.target.value); setError(''); }} placeholder="you@example.com" className={inputClass} required />
                </div>
              )}

              <div>
                <label htmlFor="verification-code" className="mb-2 block text-sm font-semibold text-slate-800">Verification code</label>
                <input id="verification-code" name="code" type="text" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={handleCodeChange} placeholder="000000" maxLength="6" className={inputClass + ' text-center text-2xl font-mono tracking-[0.35em]'} required />
                <p className="mt-2 text-sm text-slate-500">Enter the 6-digit code from your email.</p>
              </div>

              <button type="submit" disabled={isLoading || code.length !== 6} className="w-full rounded-xl bg-slate-900 px-4 py-3.5 font-semibold text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none">
                {isLoading ? 'Verifying…' : 'Verify email'}
              </button>
            </form>

            <div className="mt-7 border-t border-slate-100 pt-6 text-center">
              <button type="button" onClick={handleResend} disabled={resending || resendCooldown > 0 || !isValidEmail(email)} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 text-sm font-semibold text-cyan-800 transition hover:bg-cyan-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-600 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none" aria-live="polite">
                <RefreshCw className={'h-4 w-4 ' + (resending ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
                {resendCooldown > 0 ? `Resend code in ${resendCooldown}s` : resending ? 'Sending…' : 'Resend verification code'}
              </button>
              <p className="mt-3 text-sm text-slate-600"><Link to="/login" className="font-semibold text-cyan-800 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-600">Back to login</Link></p>
            </div>
          </section>
        </div>
      </main>
    </Layout>
  );
}
