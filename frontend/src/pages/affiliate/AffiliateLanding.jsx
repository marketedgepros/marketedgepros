import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Layout from '../../components/layout/Layout';
import useAuthStore from '../../store/authStore';
import {
  affiliateProgramError,
  isAffiliateProgramInactiveError,
  loadAffiliateProgram,
  registerAffiliate,
} from '../../services/affiliateProgramViewService';
import { Link2, ShieldCheck, CircleHelp } from 'lucide-react';

function safeAffiliateUrl(link) {
  if (!link || typeof link !== 'object' || typeof link.url !== 'string') return null;
  try {
    const base = window.location.origin;
    const parsed = new URL(link.url, base);
    if (parsed.protocol !== 'https:' || parsed.origin !== base || link.url.startsWith('//')) return null;
    if (parsed.username || parsed.password) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

function AffiliateLandingContent() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const authLoading = useAuthStore((state) => state.isLoading);
  const userIdentity = isAuthenticated && user
    ? JSON.stringify([user.id, user.tenant_id ?? user.tenantId ?? user.tenant?.id ?? null, user.role])
    : null;
  const [program, setProgram] = useState(null);
  const [programState, setProgramState] = useState('loading');
  const [error, setError] = useState('');
  const [availabilityRequest, setAvailabilityRequest] = useState(0);
  const [success, setSuccess] = useState('');
  const [registeredUrl, setRegisteredUrl] = useState(null);
  const [registering, setRegistering] = useState(false);
  const mountedRef = useRef(false);
  const identityRef = useRef(userIdentity);
  const availabilityRequestRef = useRef(0);
  const registrationInFlightRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  useEffect(() => {
    identityRef.current = userIdentity;
    setSuccess('');
    setRegisteredUrl(null);
  }, [userIdentity]);
  useEffect(() => {
    const controller = new AbortController();
    const requestId = availabilityRequestRef.current + 1;
    const requestIdentity = userIdentity;
    availabilityRequestRef.current = requestId;
    const canPublishAvailability = () => (
      mountedRef.current
      && !controller.signal.aborted
      && identityRef.current === requestIdentity
      && availabilityRequestRef.current === requestId
    );

    const fetchProgramInfo = async () => {
      setProgram(null);
      setProgramState('loading');
      setError('');
      try {
        const nextProgram = await loadAffiliateProgram();
        if (!canPublishAvailability()) return;
        setProgram(nextProgram);
        setProgramState(nextProgram.isActive ? 'ready' : 'inactive');
      } catch (requestError) {
        if (!canPublishAvailability()) return;
        setProgram(null);
        if (isAffiliateProgramInactiveError(requestError)) setProgramState('inactive');
        else {
          setProgramState('error');
          setError(affiliateProgramError(requestError));
        }
      }
    };
    fetchProgramInfo();
    return () => { controller.abort(); };
  }, [availabilityRequest, userIdentity]);

  const retryAvailability = () => {
    if (programState !== 'error') return;
    setAvailabilityRequest((request) => request + 1);
  };

  const canRegister = programState === 'ready' && program?.isActive === true
    && !authLoading && !registering && (!success || user?.role === 'affiliate');
  const registrationLabel = registering ? 'Registering…'
    : programState === 'loading' ? 'Loading availability…'
      : programState === 'inactive' ? 'Registration unavailable'
        : programState === 'error' ? 'Program information unavailable'
          : authLoading ? 'Checking sign-in…'
            : isAuthenticated && user?.role === 'affiliate' ? 'Open affiliate dashboard'
              : success ? 'Registration received'
                : isAuthenticated && user ? 'Register interest' : 'Sign in to continue';

  const handleRegister = async () => {
    if (registrationInFlightRef.current || !canRegister) return;
    if (!isAuthenticated || !user) {
      navigate(`/login?redirect=${encodeURIComponent('/affiliate')}`);
      return;
    }
    if (user.role === 'affiliate') {
      navigate('/affiliate/dashboard');
      return;
    }
    if (success) return;
    const requestIdentity = userIdentity;
    registrationInFlightRef.current = true;
    setRegistering(true);
    setError('');
    setSuccess('');
    setRegisteredUrl(null);
    try {
      const registration = await registerAffiliate();
      if (!mountedRef.current || identityRef.current !== requestIdentity) return;
      setSuccess('Your link registration request was received. A registered link does not create a commission or confirm eligibility for a payout.');
      setRegisteredUrl(safeAffiliateUrl(registration.link));
    } catch (requestError) {
      if (!mountedRef.current || identityRef.current !== requestIdentity) return;
      setError(affiliateProgramError(requestError));
    } finally {
      registrationInFlightRef.current = false;
      if (mountedRef.current && identityRef.current === requestIdentity) setRegistering(false);
    }
  };

  const statusMessage = programState === 'loading' ? 'Checking whether affiliate registration is currently available…'
    : programState === 'inactive' ? 'Affiliate registration is not currently available.'
      : programState === 'error' ? 'Program availability could not be confirmed. Registration is unavailable.' : null;

  return (
    <Layout>
      <main className="mep-screen min-h-screen text-slate-100">
        <section className="relative overflow-hidden border-b border-cyan-400/15 px-4 pb-16 pt-28 sm:px-6 lg:px-8">
          <div aria-hidden="true" className="absolute -right-24 top-8 h-80 w-80 rounded-full bg-cyan-500/10 blur-3xl" />
          <div className="relative mx-auto max-w-5xl">
            <p className="mb-4 text-sm font-semibold uppercase tracking-[0.22em] text-cyan-300">MarketEdgePros · Affiliate</p>
            <h1 className="mep-heading max-w-3xl text-4xl font-bold tracking-tight sm:text-6xl">Affiliate information and registration</h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
              Find current availability and, when registration is available, submit a request for an affiliate link. Link registration is separate from commission creation and payout eligibility.
            </p>
            {error && <div role="alert" className="mt-6 rounded-xl border border-rose-400/30 bg-rose-950/40 p-4 text-rose-200">{error}</div>}
            {success && (
              <div role="status" className="mep-panel mt-6 rounded-xl border p-4 text-cyan-100">
                <p>{success}</p>
                {registeredUrl && <a className="mt-3 inline-block break-all underline decoration-cyan-400 underline-offset-4 focus:outline-none focus:ring-2 focus:ring-cyan-300" href={registeredUrl} target="_blank" rel="noreferrer">Open your affiliate link</a>}
                <Link to="/support/create-ticket" className="mt-3 block underline underline-offset-4 focus:outline-none focus:ring-2 focus:ring-cyan-300">Contact support about affiliate access</Link>
              </div>
            )}
            {statusMessage && <p id="affiliate-availability-status" role="status" className="mt-6 rounded-xl border border-slate-700 bg-slate-900/80 p-4 text-slate-300">{statusMessage}</p>}
            {programState === 'error' && (
              <button type="button" onClick={retryAvailability} aria-describedby="affiliate-availability-status"
                className="mt-4 rounded-md border border-cyan-400/40 px-4 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-400/10 focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:ring-offset-2 focus:ring-offset-slate-950">
                Retry availability check
              </button>
            )}
            <button type="button" onClick={handleRegister} disabled={!canRegister}
              className="mep-primary mt-8 px-6 py-3 font-semibold transition focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:ring-offset-2 focus:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
              {registrationLabel}
            </button>
            <p className="mt-3 max-w-xl text-sm text-slate-400">Program details and terms have not been independently verified here. Please contact support before relying on payable terms.</p>
          </div>
        </section>

        <section className="mx-auto grid max-w-5xl gap-5 px-4 py-14 sm:px-6 md:grid-cols-2 lg:px-8">
          <article className="mep-panel rounded-2xl border p-6">
            <ShieldCheck aria-hidden="true" className="mb-4 h-7 w-7 text-cyan-300" />
            <h2 className="mep-heading text-xl font-semibold">Availability and terms</h2>
            <p className="mt-3 leading-7 text-slate-300">The current program status is shown above when available. Configured rates, cookie duration, thresholds, and terms are not presented as approved payable business terms on this page.</p>
          </article>
          <article className="mep-panel rounded-2xl border p-6">
            <Link2 aria-hidden="true" className="mb-4 h-7 w-7 text-cyan-300" />
            <h2 className="mep-heading text-xl font-semibold">A link is not a commission</h2>
            <p className="mt-3 leading-7 text-slate-300">A link returned after registration may identify referrals. It does not itself create a commission, grant an affiliate role, or confirm payout eligibility.</p>
          </article>
          <article className="mep-panel rounded-2xl border p-6 md:col-span-2">
            <CircleHelp aria-hidden="true" className="mb-4 h-7 w-7 text-cyan-300" />
            <h2 className="mep-heading text-xl font-semibold">Need current program information?</h2>
            <p className="mt-3 leading-7 text-slate-300">Contact support to ask about availability and current program terms. Registration requires a signed-in account; affiliate dashboard access is limited to accounts already authorized for that role.</p>
            <Link to="/support" className="mt-4 inline-flex rounded-md text-cyan-300 underline underline-offset-4 focus:outline-none focus:ring-2 focus:ring-cyan-300">Visit support</Link>
          </article>
        </section>
      </main>
    </Layout>
  );
}

export default function AffiliateLanding() {
  const authenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  // Separate component instances own each context's request refs and pending state.
  // An in-flight request may finish, but its unmounted instance cannot publish a result.
  const contextKey = JSON.stringify([
    authenticated, user?.id ?? null,
    user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id ?? null,
    user?.role ?? null,
  ]);
  return <AffiliateLandingContent key={contextKey} />;
}
