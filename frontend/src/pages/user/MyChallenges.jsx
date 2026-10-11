import { useCallback, useEffect, useRef, useState } from 'react';
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

const challengeViewService = createChallengeViewService(api);

const isRequestCancelled = (error, signal) => (
  signal?.aborted || error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError'
);

const getErrorMessage = (error, fallback) => {
  const message = error?.response?.data?.error;
  return typeof message === 'string' && message.trim() ? message : fallback;
};

const displayRecordedValue = (value) => (value === null ? 'Unavailable' : value);
const displayRecordedStatus = (value) => (
  value === null || value === '' ? 'Unavailable' : value.replaceAll('_', ' ')
);

export default function MyChallenges() {
  const navigate = useNavigate();
  const [challenges, setChallenges] = useState(null);
  const [pagination, setPagination] = useState({
    page: 1,
    per_page: DEFAULT_CHALLENGE_PER_PAGE,
    total: 0,
    pages: 0,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const mountedRef = useRef(false);
  const controllerRef = useRef(null);
  const requestGateRef = useRef(new ChallengeViewRequestGate());
  const requestedPageRef = useRef(1);

  const loadChallenges = useCallback(async (page, { showLoading = true } = {}) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const request = requestGateRef.current.begin({ mode: 'list', page });

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
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    loadChallenges(1);

    return () => {
      mountedRef.current = false;
      requestGateRef.current.invalidate();
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [loadChallenges]);

  const goToPage = (page) => {
    if (isLoading || page < 1 || page > MAX_CHALLENGE_PAGE || (pagination.pages > 0 && page > pagination.pages)) return;
    loadChallenges(page);
  };

  const retry = () => loadChallenges(requestedPageRef.current);
  const currentPageCount = challenges?.length ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">My Challenges</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-300">
            Stored challenge records are shown for reference only. Status, payment, balance, and phase values are
            unverified legacy data and are not proof of payment, funding, rule approval, or live trading activity.
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/programs')}
          className="inline-flex items-center justify-center rounded-lg border border-cyan-500/60 px-4 py-2 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/10"
        >
          Browse Programs
        </button>
      </div>

      {isLoading && challenges === null && (
        <div className="flex min-h-[18rem] items-center justify-center rounded-xl border border-white/10 bg-slate-800/50">
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
              <h2 className="font-semibold">Challenges could not be loaded</h2>
              <p className="mt-1 text-sm text-red-200">{error}</p>
              <button
                type="button"
                onClick={retry}
                className="mt-4 inline-flex items-center gap-2 rounded-lg border border-red-300/60 px-3 py-2 text-sm font-medium hover:bg-red-900/30"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          </div>
        </div>
      )}

      {!isLoading && !error && challenges?.length === 0 && (
        <div className="rounded-xl border border-white/10 bg-slate-800/50 p-12 text-center">
          <h2 className="text-xl font-semibold text-white">
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
                className="rounded-xl border border-white/10 bg-slate-800/50 p-5 shadow-lg shadow-slate-950/10"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-semibold text-white">{challenge.program.name || 'Unnamed program'}</h2>
                    <p className="mt-1 text-xs font-medium uppercase tracking-wide text-cyan-300">Unverified legacy record</p>
                  </div>
                  <span className="rounded-full border border-slate-600 bg-slate-900/60 px-2.5 py-1 text-xs text-slate-200">
                    Recorded: {displayRecordedStatus(challenge.legacy_status)}
                  </span>
                </div>

                <dl className="mt-5 space-y-3 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Recorded payment status</dt>
                    <dd className="text-right font-medium text-slate-100">{displayRecordedStatus(challenge.legacy_payment_status)}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Recorded initial balance</dt>
                    <dd className="font-mono text-slate-100">{displayRecordedValue(challenge.initial_balance)}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Recorded current balance</dt>
                    <dd className="font-mono text-slate-100">{displayRecordedValue(challenge.current_balance)}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-400">Observed drawdown</dt>
                    <dd className="font-mono text-slate-100">{displayRecordedValue(challenge.max_drawdown_observed)}</dd>
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
                  className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg border border-cyan-500/60 px-4 py-2 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/10"
                >
                  View recorded details
                  <ArrowRight className="h-4 w-4" />
                </button>
              </article>
            ))}
          </div>

          <div className="flex flex-col gap-3 rounded-xl border border-white/10 bg-slate-800/30 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-slate-300">
              Page {pagination.page} of {pagination.pages} · {currentPageCount} record{currentPageCount === 1 ? '' : 's'} on this page · {pagination.total} total records
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => goToPage(pagination.page - 1)}
                disabled={isLoading || pagination.page <= 1}
                className="inline-flex items-center gap-1 rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-45"
              >
                <ChevronLeft className="h-4 w-4" /> Previous
              </button>
              <button
                type="button"
                onClick={() => goToPage(pagination.page + 1)}
                disabled={isLoading || pagination.pages === 0 || pagination.page >= pagination.pages || pagination.page >= MAX_CHALLENGE_PAGE}
                className="inline-flex items-center gap-1 rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-45"
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
