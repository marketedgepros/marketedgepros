import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, Calendar, ChevronLeft, ChevronRight, CircleAlert, Loader2, RefreshCw,
} from 'lucide-react';
import api from '../../services/api';
import {
  ChallengeViewRequestGate,
  createChallengeViewService,
  DEFAULT_CHALLENGE_PER_PAGE,
  MAX_CHALLENGE_PAGE,
} from '../../services/challengeViewService';
import useAuthStore from '../../store/authStore';
import { ROLES } from '../../constants/roles.js';

const challengeViewService = createChallengeViewService(api);

const isRequestCancelled = (error, signal) => (
  signal?.aborted || error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError'
);

const getErrorMessage = (_error, fallback) => fallback;

const displayRecordedValue = (value) => (value === null ? 'Unavailable' : value);
const displayRecordedStatus = (value) => (
  value === null || value === '' ? 'Unavailable' : value.replaceAll('_', ' ')
);

const isPositiveInteger = (value) => Number.isSafeInteger(value) && value >= 1;
const isNullableTenant = (value) => value === null || isPositiveInteger(value);
const identityPart = (value) => `${typeof value}:${String(value ?? null)}`;

/**
 * This screen intentionally reads only user.tenant_id. A missing tenant is an
 * explicit null owner value; a tenantId/tenant object fallback could display a
 * different brand's result under an ambiguous local session.
 */
export const challengePrincipalFromUser = (user, isAuthenticated) => {
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
    return { key, ready: false, unavailableMessage: 'Recorded challenges are unavailable because the account session is not active.' };
  }
  if (!isPositiveInteger(userId)) {
    return { key, ready: false, unavailableMessage: 'Recorded challenges are unavailable because the account identifier is invalid.' };
  }
  if (!isNullableTenant(tenantId)) {
    return { key, ready: false, unavailableMessage: 'Recorded challenges are unavailable because the tenant context is invalid.' };
  }
  if (![ROLES.TRADER, ROLES.AFFILIATE, ROLES.GUEST].includes(role)) {
    return { key, ready: false, unavailableMessage: 'Recorded challenges are unavailable for this account role.' };
  }

  return {
    key,
    ready: true,
    expectedOwner: { user_id: userId, tenant_id: tenantId },
  };
};

export function MyChallengesContent({ principal }) {
  const navigate = useNavigate();
  const [challenges, setChallenges] = useState(null);
  const [pagination, setPagination] = useState({
    page: 1,
    per_page: DEFAULT_CHALLENGE_PER_PAGE,
    total: 0,
    pages: 0,
  });
  const [isLoading, setIsLoading] = useState(principal.ready);
  const [error, setError] = useState(null);
  const mountedRef = useRef(false);
  const controllerRef = useRef(null);
  const requestGateRef = useRef(new ChallengeViewRequestGate());
  const requestedPageRef = useRef(1);

  const loadChallenges = useCallback(async (page, { showLoading = true } = {}) => {
    if (!principal.ready) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const request = requestGateRef.current.begin({ mode: 'list', page, identity: principal.key });

    if (showLoading && mountedRef.current) setIsLoading(true);
    requestedPageRef.current = page;
    if (mountedRef.current) {
      setChallenges(null);
      setError(null);
    }

    try {
      const result = await challengeViewService.getMyChallenges({
        page,
        perPage: DEFAULT_CHALLENGE_PER_PAGE,
        signal: controller.signal,
        expectedOwner: principal.expectedOwner,
      });
      if (!mountedRef.current || controller.signal.aborted || !requestGateRef.current.isCurrent(request)) {
        return;
      }
      setChallenges(result.challenges);
      setPagination(result.pagination);
    } catch (requestError) {
      if (!mountedRef.current || isRequestCancelled(requestError, controller.signal)
        || !requestGateRef.current.isCurrent(request)) {
        return;
      }
      setChallenges(null);
      setError(getErrorMessage(requestError, 'Unable to load your recorded challenges. Please try again.'));
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
      void loadChallenges(1);
    } else {
      setChallenges(null);
      setError(null);
      setIsLoading(false);
    }

    return () => {
      mountedRef.current = false;
      requestGateRef.current.invalidate();
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [loadChallenges, principal.ready]);

  const goToPage = (page) => {
    if (isLoading || page < 1 || page > MAX_CHALLENGE_PAGE || (pagination.pages > 0 && page > pagination.pages)) return;
    loadChallenges(page);
  };

  const retry = () => loadChallenges(requestedPageRef.current);
  const currentPageCount = challenges?.length ?? 0;

  if (!principal.ready) {
    return (
      <section className="rounded-xl border border-amber-400/35 bg-amber-950/20 p-5 text-amber-50" role="status" aria-live="polite">
        <h1 className="mep-heading text-xl font-semibold">Recorded challenges unavailable</h1>
        <p className="mt-2 max-w-2xl break-words text-sm text-amber-100">{principal.unavailableMessage}</p>
      </section>
    );
  }

  return (
    <div className="mx-auto min-w-0 max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="mep-heading text-3xl font-bold text-white">My Challenges</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-300">
            Stored challenge records are shown for reference only. Status, payment, balance, and phase values are
            unverified legacy data and are not proof of payment, funding, rule approval, or live trading activity.
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/programs')}
          className="inline-flex items-center justify-center rounded-lg border border-cyan-500/60 px-4 py-2 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
        >
          Browse Programs
        </button>
      </div>

      {isLoading && challenges === null && (
        <div className="mep-panel flex min-h-[18rem] items-center justify-center rounded-xl border" role="status" aria-live="polite">
          <div className="text-center text-slate-300">
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-cyan-400" />
            <p className="mt-3">Loading recorded challenges…</p>
          </div>
        </div>
      )}

      {!isLoading && error && (
        <div className="rounded-xl border border-red-500/50 bg-red-950/30 p-5 text-red-100" role="alert">
          <div className="flex gap-3">
            <CircleAlert className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <h2 className="mep-heading font-semibold">Challenges could not be loaded</h2>
              <p className="mt-1 break-words text-sm text-red-200">{error}</p>
              <button
                type="button"
                onClick={retry}
                className="mt-4 inline-flex items-center gap-2 rounded-lg border border-red-300/60 px-3 py-2 text-sm font-medium hover:bg-red-900/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 focus-visible:ring-offset-2 focus-visible:ring-offset-red-950"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          </div>
        </div>
      )}

      {!isLoading && !error && challenges?.length === 0 && (
        <div className="mep-panel rounded-xl border p-12 text-center">
          <h2 className="mep-heading text-xl font-semibold text-white">
            {pagination.total > 0 ? 'No records on this page' : 'No recorded challenges'}
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-slate-300">
            {pagination.total > 0
              ? `There are ${pagination.total} recorded challenges, but this page is now empty. Return to the first page to reload the current result.`
              : 'No challenge records were returned. This does not confirm payment, funding, or provider account status.'}
          </p>
          {pagination.page > 1 && (
            <button
              type="button"
              onClick={() => goToPage(1)}
              className="mt-6 mr-3 rounded-lg border border-cyan-500/60 px-4 py-2 text-sm font-medium text-cyan-200 hover:bg-cyan-500/10"
            >
              Return to first page
            </button>
          )}
          <button
            type="button"
            onClick={() => navigate('/programs')}
            className="mt-6 rounded-lg border border-cyan-500/60 px-4 py-2 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/10"
          >
            Browse Programs
          </button>
        </div>
      )}

      {!isLoading && !error && challenges?.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
            {challenges.map((challenge) => (
              <article
                key={challenge.id}
                className="mep-panel rounded-xl border p-5 shadow-lg shadow-slate-950/10"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h2 className="mep-heading break-words text-lg font-semibold text-white">{challenge.program.name || 'Unnamed program'}</h2>
                    <p className="mt-1 text-xs font-medium uppercase tracking-wide text-cyan-300">Unverified legacy record</p>
                  </div>
                  <span className="max-w-[55%] break-words rounded-full border border-slate-600 bg-slate-900/60 px-2.5 py-1 text-right text-xs text-slate-200">
                    Recorded: {displayRecordedStatus(challenge.legacy_status)}
                  </span>
                </div>

                <dl className="mt-5 space-y-3 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Recorded payment status</dt>
                    <dd className="max-w-[58%] break-words text-right font-medium text-slate-100">{displayRecordedStatus(challenge.legacy_payment_status)}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Recorded initial balance</dt>
                    <dd className="max-w-[58%] break-words text-right font-mono text-slate-100">{displayRecordedValue(challenge.initial_balance)}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Recorded current balance</dt>
                    <dd className="max-w-[58%] break-words text-right font-mono text-slate-100">{displayRecordedValue(challenge.current_balance)}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Observed drawdown</dt>
                    <dd className="max-w-[58%] break-words text-right font-mono text-slate-100">{displayRecordedValue(challenge.max_drawdown_observed)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-4 border-t border-white/10 pt-3">
                    <dt className="flex items-center gap-2 text-slate-400"><Calendar className="h-4 w-4" /> Recorded phase</dt>
                    <dd className="text-slate-100">
                      {displayRecordedValue(challenge.current_phase)} / {displayRecordedValue(challenge.total_phases)}
                    </dd>
                  </div>
                </dl>

                <button
                  type="button"
                  onClick={() => navigate(`/challenges/${challenge.id}`)}
                  className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg border border-cyan-500/60 px-4 py-2 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
                >
                  View recorded details
                  <ArrowRight className="h-4 w-4" />
                </button>
              </article>
            ))}
          </div>

          <div className="mep-panel flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-slate-300">
              Page {pagination.page} of {pagination.pages} · {currentPageCount} record{currentPageCount === 1 ? '' : 's'} on this page · {pagination.total} total records
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => goToPage(pagination.page - 1)}
                disabled={isLoading || pagination.page <= 1}
                aria-label="Previous challenge page"
                className="inline-flex items-center gap-1 rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-45"
              >
                <ChevronLeft className="h-4 w-4" /> Previous
              </button>
              <button
                type="button"
                onClick={() => goToPage(pagination.page + 1)}
                disabled={isLoading || pagination.pages === 0 || pagination.page >= pagination.pages || pagination.page >= MAX_CHALLENGE_PAGE}
                aria-label="Next challenge page"
                className="inline-flex items-center gap-1 rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-45"
              >
                Next <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function MyChallenges() {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const principal = useMemo(
    () => challengePrincipalFromUser(user, isAuthenticated),
    [isAuthenticated, user?.id, user?.tenant_id, user?.role],
  );

  // The key makes stale state impossible to render during an identity handoff.
  return <MyChallengesContent key={principal.key} principal={principal} />;
}
