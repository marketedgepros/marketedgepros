import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, Calendar, CircleAlert, Database, Loader2, RefreshCw, ShieldAlert,
} from 'lucide-react';
import api from '../services/api';
import {
  ChallengeViewRequestGate,
  createChallengeViewService,
  validateChallengeId,
} from '../services/challengeViewService';
import useAuthStore from '../store/authStore';
import { ROLES } from '../constants/roles.js';

const challengeViewService = createChallengeViewService(api);

const isRequestCancelled = (error, signal) => (
  signal?.aborted || error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError' || error?.name === 'AbortError'
);

const getErrorMessage = (_error, fallback) => fallback;

const routeChallengeId = (value) => {
  if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) {
    throw new Error('Challenge ID is invalid.');
  }
  return validateChallengeId(Number(value));
};

const displayRecordedValue = (value) => (value === null ? 'Unavailable' : value);
const displayRecordedStatus = (value) => (
  value === null || value === '' ? 'Unavailable' : value.replaceAll('_', ' ')
);

const isPositiveInteger = (value) => Number.isSafeInteger(value) && value >= 1;
const isNullableTenant = (value) => value === null || isPositiveInteger(value);
const identityPart = (value) => `${typeof value}:${String(value ?? null)}`;

export const challengeDetailPrincipalFromUser = (user, isAuthenticated) => {
  const userId = user?.id;
  const tenantId = user?.tenant_id ?? null;
  const role = typeof user?.role === 'string' ? user.role : null;
  const key = JSON.stringify([
    isAuthenticated === true,
    identityPart(userId),
    identityPart(tenantId),
    identityPart(role),
  ]);

  if (isAuthenticated !== true) {
    return { key, ready: false, unavailableMessage: 'Recorded challenge details are unavailable because the account session is not active.' };
  }
  if (!isPositiveInteger(userId)) {
    return { key, ready: false, unavailableMessage: 'Recorded challenge details are unavailable because the account identifier is invalid.' };
  }
  if (!isNullableTenant(tenantId)) {
    return { key, ready: false, unavailableMessage: 'Recorded challenge details are unavailable because the tenant context is invalid.' };
  }
  if (![ROLES.TRADER, ROLES.AFFILIATE, ROLES.GUEST].includes(role)) {
    return { key, ready: false, unavailableMessage: 'Recorded challenge details are unavailable for this account role.' };
  }

  return {
    key,
    ready: true,
    expectedOwner: { user_id: userId, tenant_id: tenantId },
  };
};

const metadataRows = (account) => [
  ['Login', account.login],
  ['Server', account.server],
  ['Group', account.group],
  ['Stored status', account.status],
  ['Stored balance', account.balance],
  ['Stored equity', account.equity],
  ['Stored margin', account.margin],
  ['Stored free margin', account.free_margin],
  ['Stored margin level', account.margin_level],
  ['Metadata updated', account.updated_at],
];

export function ChallengeDetailsContent({ id, principal }) {
  const navigate = useNavigate();
  const [view, setView] = useState(null);
  const [isLoading, setIsLoading] = useState(principal.ready);
  const [error, setError] = useState(null);
  const mountedRef = useRef(false);
  const controllerRef = useRef(null);
  const requestGateRef = useRef(new ChallengeViewRequestGate());

  const loadChallenge = useCallback(async (requestedId, { showLoading = true } = {}) => {
    if (!principal.ready) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const request = requestGateRef.current.begin({ mode: 'detail', id: requestedId, identity: principal.key });

    if (showLoading && mountedRef.current) setIsLoading(true);
    if (mountedRef.current) {
      setView(null);
      setError(null);
    }

    try {
      const challengeId = routeChallengeId(requestedId);
      const result = await challengeViewService.getChallengeProgress(challengeId, {
        signal: controller.signal,
        expectedOwner: principal.expectedOwner,
      });
      if (!mountedRef.current || controller.signal.aborted || !requestGateRef.current.isCurrent(request)) {
        return;
      }
      setView(result);
    } catch (requestError) {
      if (!mountedRef.current || isRequestCancelled(requestError, controller.signal)
        || !requestGateRef.current.isCurrent(request)) {
        return;
      }
      setView(null);
      setError(getErrorMessage(requestError, 'Unable to load this recorded challenge. Please try again.'));
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
      if (showLoading && mountedRef.current && requestGateRef.current.isCurrent(request)) {
        setIsLoading(false);
      }
    }
  }, [principal]);

  useEffect(() => {
    mountedRef.current = true;
    if (principal.ready) {
      void loadChallenge(id);
    } else {
      setView(null);
      setError(null);
      setIsLoading(false);
    }

    return () => {
      mountedRef.current = false;
      requestGateRef.current.invalidate();
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [id, loadChallenge, principal.ready]);

  const retry = () => loadChallenge(id);

  if (!principal.ready) {
    return (
      <section className="rounded-xl border border-amber-400/35 bg-amber-950/20 p-5 text-amber-50" role="status" aria-live="polite">
        <h1 className="text-xl font-semibold">Recorded challenge details unavailable</h1>
        <p className="mt-2 max-w-2xl break-words text-sm text-amber-100">{principal.unavailableMessage}</p>
      </section>
    );
  }

  if (isLoading || (view && String(view.challenge.id) !== id)) {
    return (
      <div className="flex min-h-[20rem] items-center justify-center rounded-xl border border-white/10 bg-slate-800/50" role="status" aria-live="polite">
        <div className="text-center text-slate-300">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-cyan-400" />
          <p className="mt-3">Loading recorded challenge details…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/50 bg-red-950/30 p-6 text-red-100" role="alert">
        <div className="flex gap-3">
          <CircleAlert className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <h1 className="font-semibold">Challenge details could not be loaded</h1>
              <p className="mt-1 break-words text-sm text-red-200">{error}</p>
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={retry}
                className="inline-flex items-center gap-2 rounded-lg border border-red-300/60 px-3 py-2 text-sm font-medium hover:bg-red-900/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 focus-visible:ring-offset-2 focus-visible:ring-offset-red-950"
              >
                <RefreshCw className="h-4 w-4" /> Retry
              </button>
              <button
                type="button"
                onClick={() => navigate('/challenges')}
                className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-3 py-2 text-sm font-medium text-slate-100 hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
              >
                <ArrowLeft className="h-4 w-4" /> Back to challenges
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!view) return null;

  const { challenge, progress, mt5_account: mt5Account } = view;

  return (
    <div className="mx-auto min-w-0 max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
      <button
        type="button"
        onClick={() => navigate('/challenges')}
        className="inline-flex items-center gap-2 rounded-md text-sm font-medium text-slate-300 transition-colors hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to challenges
      </button>

      <header className="rounded-xl border border-white/10 bg-slate-800/50 p-6">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Unverified legacy record</p>
            <h1 className="mt-2 break-words text-3xl font-bold text-white">{challenge.program.name || 'Unnamed program'}</h1>
            <p className="mt-2 text-sm text-slate-300">
              All values below are stored legacy metadata. This view does not verify payment, funding, challenge rules,
              trading evidence, or a live provider account.
            </p>
          </div>
          <div className="rounded-lg border border-slate-600 bg-slate-900/60 px-4 py-3 text-sm">
            <p className="text-slate-400">Recorded status</p>
            <p className="mt-1 break-words font-medium text-slate-100">{displayRecordedStatus(challenge.legacy_status)}</p>
          </div>
        </div>
      </header>

      <div className="rounded-xl border border-amber-400/35 bg-amber-950/20 p-4 text-sm text-amber-100">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
          <p>
            <strong>Verification unavailable.</strong> Recorded payment status is not payment proof, and legacy balance
            snapshots are not approved live progress. Approved challenge-rule progress is unavailable.
          </p>
        </div>
      </div>

      <section className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4" aria-label="Recorded challenge fields">
        <div className="rounded-xl border border-white/10 bg-slate-800/50 p-5">
          <p className="text-sm text-slate-400">Recorded initial balance</p>
          <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(challenge.initial_balance)}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-slate-800/50 p-5">
          <p className="text-sm text-slate-400">Recorded current balance</p>
          <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(challenge.current_balance)}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-slate-800/50 p-5">
          <p className="text-sm text-slate-400">Observed drawdown</p>
          <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(challenge.max_drawdown_observed)}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-slate-800/50 p-5">
          <p className="text-sm text-slate-400">Recorded profit/loss</p>
          <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(progress.profit_loss)}</p>
          <p className="mt-1 text-xs text-slate-400">Legacy estimated diagnostic, not approved live progress.</p>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <section className="rounded-xl border border-white/10 bg-slate-800/50 p-6 xl:col-span-2">
          <h2 className="text-lg font-semibold text-white">Recorded challenge metadata</h2>
          <dl className="mt-5 space-y-4 text-sm">
            <div className="flex justify-between gap-5 border-b border-white/10 pb-3">
              <dt className="text-slate-400">Recorded payment status</dt>
              <dd className="max-w-[60%] break-words text-right font-medium text-slate-100">{displayRecordedStatus(challenge.legacy_payment_status)}</dd>
            </div>
            <div className="flex justify-between gap-5 border-b border-white/10 pb-3">
              <dt className="text-slate-400">Recorded phase</dt>
              <dd className="text-right text-slate-100">
                {displayRecordedValue(challenge.current_phase)} / {displayRecordedValue(challenge.total_phases)}
              </dd>
            </div>
            <div className="flex justify-between gap-5 border-b border-white/10 pb-3">
              <dt className="flex items-center gap-2 text-slate-400"><Calendar className="h-4 w-4" /> Recorded start date</dt>
              <dd className="min-w-0 max-w-[60%] break-words text-right text-slate-100">{displayRecordedValue(challenge.start_date)}</dd>
            </div>
            <div className="flex justify-between gap-5 border-b border-white/10 pb-3">
              <dt className="text-slate-400">Recorded end date</dt>
              <dd className="min-w-0 max-w-[60%] break-words text-right text-slate-100">{displayRecordedValue(challenge.end_date)}</dd>
            </div>
            <div className="flex justify-between gap-5">
              <dt className="text-slate-400">Record created</dt>
              <dd className="min-w-0 max-w-[60%] break-words text-right text-slate-100">{displayRecordedValue(challenge.created_at)}</dd>
            </div>
          </dl>
        </section>

        <section className="rounded-xl border border-white/10 bg-slate-800/50 p-6 xl:col-span-3">
          <div className="flex items-start gap-3">
            <Database className="mt-0.5 h-5 w-5 text-cyan-300" />
            <div>
              <h2 className="text-lg font-semibold text-white">Stored MT5 metadata</h2>
              <p className="mt-1 text-sm text-slate-300">Stored metadata is unverified and does not authenticate or connect to a provider.</p>
            </div>
          </div>

          {mt5Account ? (
            <>
              <p className="mt-4 rounded-lg border border-amber-400/30 bg-amber-950/20 px-3 py-2 text-sm text-amber-100">
                Provider and branch verification are unavailable. The fields below are a stored legacy snapshot only.
              </p>
              <dl className="mt-5 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
                {metadataRows(mt5Account).map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-4 border-b border-white/10 py-2 text-sm">
                    <dt className="text-slate-400">{label}</dt>
                    <dd className="max-w-[60%] break-words text-right font-mono text-slate-100">{displayRecordedValue(value)}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <p className="mt-5 rounded-lg border border-white/10 bg-slate-900/40 p-4 text-sm text-slate-300">
              No owner-linked stored MT5 metadata was returned for this challenge. This view cannot verify provider or branch connection status.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

export default function ChallengeDetails() {
  const { id } = useParams();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const principal = useMemo(
    () => challengeDetailPrincipalFromUser(user, isAuthenticated),
    [isAuthenticated, user?.id, user?.tenant_id, user?.role],
  );
  const routeKey = `${principal.key}|route:${identityPart(id)}`;

  // Route ID is part of the identity projection, not only an effect dependency.
  return <ChallengeDetailsContent key={routeKey} id={id} principal={principal} />;
}
