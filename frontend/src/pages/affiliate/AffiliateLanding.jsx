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
import { DollarSign, TrendingUp, Users, Award, Clock, CreditCard } from 'lucide-react';

const formatProgramNumber = (value) => String(value);

export default function AffiliateLanding() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const authLoading = useAuthStore((state) => state.isLoading);
  const userIdentity = isAuthenticated && user
    ? String(user.id ?? user.email ?? user.username ?? 'authenticated-user')
    : null;

  const [program, setProgram] = useState(null);
  const [programState, setProgramState] = useState('loading');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [registering, setRegistering] = useState(false);
  const mountedRef = useRef(false);
  const identityRef = useRef(userIdentity);
  const registrationInFlightRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    identityRef.current = userIdentity;
    setSuccess('');
  }, [userIdentity]);

  useEffect(() => {
    let cancelled = false;

    const fetchProgramInfo = async () => {
      setProgram(null);
      setProgramState('loading');
      setError('');

      try {
        const nextProgram = await loadAffiliateProgram();
        if (cancelled || !mountedRef.current) return;

        setProgram(nextProgram);
        setProgramState(nextProgram.isActive ? 'ready' : 'inactive');
      } catch (requestError) {
        if (cancelled || !mountedRef.current) return;

        setProgram(null);
        if (isAffiliateProgramInactiveError(requestError)) {
          setProgramState('inactive');
        } else {
          setProgramState('error');
          setError(affiliateProgramError(requestError));
        }
      }
    };

    fetchProgramInfo();
    return () => {
      cancelled = true;
    };
  }, []);

  const canRegister = (
    programState === 'ready'
    && program?.isActive === true
    && !authLoading
    && !registering
    && (!success || user?.role === 'affiliate')
  );

  const registrationLabel = (() => {
    if (registering) return 'Registering...';
    if (programState === 'loading') return 'Loading program...';
    if (programState === 'inactive') return 'Affiliate program unavailable';
    if (programState === 'error') return 'Program details unavailable';
    if (authLoading) return 'Checking sign-in...';
    if (isAuthenticated && user?.role === 'affiliate') return 'Open Affiliate Dashboard';
    if (success) return 'Affiliate link registered';
    return isAuthenticated && user ? 'Register an Affiliate Link' : 'Sign in to Join';
  })();

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

    try {
      const registration = await registerAffiliate();
      if (!mountedRef.current || identityRef.current !== requestIdentity) return;

      setSuccess(`${registration.message} A registered link does not change your account role. Affiliate dashboard access requires an authorized affiliate account.`);
    } catch (requestError) {
      if (!mountedRef.current || identityRef.current !== requestIdentity) return;
      setError(affiliateProgramError(requestError));
    } finally {
      registrationInFlightRef.current = false;
      if (mountedRef.current && identityRef.current === requestIdentity) {
        setRegistering(false);
      }
    }
  };

  const showProgramDetails = programState === 'ready' && program?.isActive === true;
  const statusMessage = programState === 'loading'
    ? 'Loading current affiliate program details...'
    : programState === 'inactive'
      ? 'The affiliate program is not active at this time.'
      : programState === 'error'
        ? 'Program details are currently unavailable. Registration is disabled.'
        : null;

  const programBenefits = [
    {
      icon: DollarSign,
      color: 'from-blue-500 to-purple-500',
      title: 'Commission Rate',
      description: showProgramDetails
        ? `Current program rate: ${formatProgramNumber(program.commissionRate)}%. Eligibility is subject to program terms.`
        : 'The current commission rate is shown only when active program details are available.',
    },
    {
      icon: TrendingUp,
      color: 'from-purple-500 to-pink-500',
      title: 'Affiliate Dashboard',
      description: 'Accounts authorized with the affiliate role can review activity in the affiliate dashboard.',
    },
    {
      icon: Award,
      color: 'from-pink-500 to-orange-500',
      title: 'Affiliate Link',
      description: 'After confirmed registration, the server provides an affiliate link for your account.',
    },
    {
      icon: Clock,
      color: 'from-orange-500 to-yellow-500',
      title: 'Cookie Duration',
      description: showProgramDetails
        ? `${formatProgramNumber(program.cookieDurationDays)}-day cookie duration, as configured for the active program.`
        : 'Cookie duration is shown only when active program details are available.',
    },
    {
      icon: CreditCard,
      color: 'from-yellow-500 to-green-500',
      title: 'Payout Threshold',
      description: showProgramDetails
        ? `Minimum payout: ${formatProgramNumber(program.minPayout)} (program-configured amount; review program terms for payout details).`
        : 'The minimum payout is shown only when active program details are available.',
    },
    {
      icon: Users,
      color: 'from-green-500 to-blue-500',
      title: 'Program Terms',
      description: 'Review the current program terms and conditions before participating.',
    },
  ];

  return (
    <Layout>
      <div className="min-h-screen bg-slate-900">
        <section className="relative pt-32 pb-20 overflow-hidden">
          <div className="absolute inset-0">
            <div className="absolute top-20 left-10 w-96 h-96 bg-blue-500/20 rounded-full blur-3xl" />
            <div className="absolute bottom-20 right-10 w-96 h-96 bg-purple-500/20 rounded-full blur-3xl" />
          </div>

          <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <div className="inline-block mb-4 px-4 py-2 bg-blue-500/10 border border-blue-500/30 rounded-full">
              <span className="text-blue-400 text-sm font-semibold">AFFILIATE PROGRAM</span>
            </div>

            <h1 className="text-5xl md:text-7xl font-bold mb-6">
              <span className="text-white">Join Our </span>
              <span className="bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">Affiliate</span>
              <br />
              <span className="bg-gradient-to-r from-purple-400 to-pink-500 bg-clip-text text-transparent">Program</span>
            </h1>

            <p className="text-xl text-gray-300 mb-8 max-w-3xl mx-auto">
              Share MarketEdgePros with your audience and apply to earn commissions for eligible referrals, subject to the program terms.
            </p>

            {error && (
              <div role="alert" className="mb-4 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 max-w-md mx-auto">
                {error}
              </div>
            )}

            {success && (
              <div role="status" className="mb-4 p-4 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 max-w-md mx-auto">
                {success}
                <Link to="/support/create-ticket" className="block mt-3 underline">Contact support about affiliate access</Link>
              </div>
            )}

            {statusMessage && (
              <div role="status" className="mb-4 p-4 bg-slate-800/70 border border-white/10 rounded-lg text-gray-300 max-w-md mx-auto">
                {statusMessage}
              </div>
            )}

            <button
              type="button"
              onClick={handleRegister}
              disabled={!canRegister}
              className="px-8 py-4 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg text-white font-bold text-lg hover:from-blue-600 hover:to-purple-700 transition transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none"
            >
              {registrationLabel}
            </button>

            {showProgramDetails ? (
              <div className="mt-16 p-8 bg-gradient-to-r from-blue-500/10 to-purple-500/10 backdrop-blur-sm border border-white/10 rounded-2xl">
                <div className="text-6xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent mb-2">
                  {formatProgramNumber(program.commissionRate)}%
                </div>
                <div className="text-2xl text-white mb-2">Current commission rate</div>
                <div className="text-gray-400">
                  Minimum payout: {formatProgramNumber(program.minPayout)} (program setting) • {formatProgramNumber(program.cookieDurationDays)}-day cookie duration
                </div>
              </div>
            ) : (
              <div className="mt-16 p-8 bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl text-gray-400">
                Current commission, payout, and cookie details will appear after an active program response is available.
              </div>
            )}
          </div>
        </section>

        <section className="py-20 relative">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-16">
              <h2 className="text-4xl font-bold text-white mb-4">Program Details</h2>
              <p className="text-gray-400 text-lg">Current participation information is confirmed by the affiliate program response.</p>
            </div>

            <div className="grid md:grid-cols-3 gap-8">
              {programBenefits.map(({ icon: Icon, color, title, description }) => (
                <div key={title} className="p-8 bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl hover:bg-white/10 transition group">
                  <div className={`w-12 h-12 bg-gradient-to-r ${color} rounded-lg flex items-center justify-center mb-4 group-hover:scale-110 transition`}>
                    <Icon className="w-6 h-6 text-white" />
                  </div>
                  <h3 className="text-xl font-bold text-white mb-3">{title}</h3>
                  <p className="text-gray-400">{description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="py-20 relative">
          <div className="absolute inset-0">
            <div className="absolute top-0 left-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl" />
          </div>

          <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-16">
              <h2 className="text-4xl font-bold text-white mb-4">How It Works</h2>
              <p className="text-gray-400 text-lg">A straightforward registration flow for the active program.</p>
            </div>

            <div className="grid md:grid-cols-4 gap-8">
              {[
                { num: 1, title: 'Sign In', desc: 'Sign in to your MarketEdgePros account.' },
                { num: 2, title: 'Register', desc: 'Submit affiliate registration while the program is active.' },
                { num: 3, title: 'Get Your Link', desc: 'After confirmed registration, receive your server-provided affiliate link.' },
                { num: 4, title: 'Share Responsibly', desc: 'Share your link in accordance with the current program terms.' },
              ].map((step) => (
                <div key={step.num} className="text-center">
                  <div className="w-16 h-16 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full flex items-center justify-center text-white text-2xl font-bold mx-auto mb-4">
                    {step.num}
                  </div>
                  <h3 className="text-xl font-bold text-white mb-2">{step.title}</h3>
                  <p className="text-gray-400 text-sm">{step.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="py-20 relative">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <div className="p-12 bg-gradient-to-r from-blue-500/10 to-purple-500/10 backdrop-blur-sm border border-white/10 rounded-2xl">
              <h2 className="text-4xl font-bold text-white mb-4">Ready to Apply?</h2>
              <p className="text-xl text-gray-300 mb-8">
                Sign in and register when the affiliate program is active.
              </p>
              <button
                type="button"
                onClick={handleRegister}
                disabled={!canRegister}
                className="px-8 py-4 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg text-white font-bold text-lg hover:from-blue-600 hover:to-purple-700 transition transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none"
              >
                {registrationLabel}
              </button>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}
