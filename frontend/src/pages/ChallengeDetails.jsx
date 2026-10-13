import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, Calendar, CircleAlert, Database, FileSearch, Loader2, MessageCircle, RefreshCw, ShieldAlert,
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
const failedOrRejectedStatuses = new Set(['failed', 'rejected']);
const detailTabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'account', label: 'Stored account data' },
];

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

const progressRows = (progress) => [
  ['Stored progress initial balance', progress.initial_balance],
  ['Stored progress current balance', progress.current_balance],
  ['Recorded profit/loss', progress.profit_loss],
  ['Recorded catalog profit target percent', progress.profit_target_percent],
  ['Recorded catalog target amount', progress.profit_target_amount],
  ['Stored legacy estimated progress percent', progress.profit_progress_percent],
  ['Stored trading days', progress.trading_days],
  ['Recorded catalog minimum trading days', progress.min_trading_days],
];

/**
 * Legacy statuses are display-only records. This maps only a small, known set to
 * a conservative next step; unfamiliar values intentionally receive generic copy
 * rather than becoming an uncontrolled call to action.
 */
export const challengeGuidanceForStatus = (legacyStatus) => {
  const normalizedStatus = typeof legacyStatus === 'string' ? legacyStatus.trim().toLowerCase() : '';

  if (!normalizedStatus) {
    return {
      kind: 'missing-status',
      title: 'Ask support to review the recorded context',
      description: 'This legacy record has no recorded status. Support can help review the stored context; no challenge, payment, or provider outcome is confirmed here.',
      includesProgram: false,
    };
  }

  if (failedOrRejectedStatuses.has(normalizedStatus)) {
    return {
      kind: 'review-record',
      title: 'Review the stored record with support',
      description: 'This legacy record needs review. Support can help clarify the stored context; this page does not offer a retry, purchase, trading, or provider action.',
      includesProgram: false,
    };
  }

  return {
    kind: 'review-program',
    title: 'Review the program and verify requirements with support',
    description: 'Review the current public program information, then ask support to verify which requirements apply to this recorded legacy record. No approval, funding, payment acceptance, or live account access is implied.',
    includesProgram: true,
  };
};

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

function RecordedRows({ rows, className = '' }) {
  return (
    <dl className={className}>
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-5 border-b border-white/10 pb-3 last:border-b-0 last:pb-0">
          <dt className="min-w-0 text-slate-400">{label}</dt>
          <dd className="min-w-0 max-w-[60%] break-words text-right font-mono text-slate-100">{displayRecordedValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ChallengeDetailsContent({ id, principal }) {
  const navigate = useNavigate();
  const [view, setView] = useState(null);
  const [isLoading, setIsLoading] = useState(principal.ready);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const mountedRef = useRef(false);
  const controllerRef = useRef(null);
  const requestGateRef = useRef(new ChallengeViewRequestGate());
  const tabRefs = useRef([]);

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

  const handleTabKeyDown = (event, index) => {
    let nextIndex = null;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % detailTabs.length;
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + detailTabs.length) % detailTabs.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = detailTabs.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    setActiveTab(detailTabs[nextIndex].id);
    tabRefs.current[nextIndex]?.focus();
  };

  if (!principal.ready) {
    return (
      <section className="rounded-xl border border-amber-400/35 bg-amber-950/20 p-5 text-amber-50" role="status" aria-live="polite">
        <h1 className="mep-heading text-xl font-semibold">Recorded challenge details unavailable</h1>
        <p className="mt-2 max-w-2xl break-words text-sm text-amber-100">{principal.unavailableMessage}</p>
      </section>
    );
  }

  if (isLoading || (view && String(view.challenge.id) !== id)) {
    return (
      <div className="mep-panel flex min-h-[20rem] items-center justify-center rounded-xl border" role="status" aria-live="polite">
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
            <h1 className="mep-heading font-semibold">Challenge details could not be loaded</h1>
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
  const guidance = challengeGuidanceForStatus(challenge.legacy_status);
  const tabNamespace = `challenge-${id}`;

  return (
    <div className="mx-auto min-w-0 max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
      <Link
        to="/challenges"
        className="inline-flex items-center gap-2 rounded-md text-sm font-medium text-slate-300 transition-colors hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Back to challenges
      </Link>

      <header className="mep-workspace-hero rounded-xl border border-cyan-400/15 bg-slate-800/50 p-6">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Recorded legacy workspace</p>
            <h1 className="mep-heading mt-2 break-words text-3xl font-bold text-white">{challenge.program.name || 'Unnamed program'}</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-300">
              Stored information is available for review. It does not verify payment, funding, challenge rules, trading evidence, or a live provider account.
            </p>
          </div>
          <div className="mep-panel min-w-0 max-w-full shrink-0 rounded-lg border px-4 py-3 text-sm md:max-w-xs">
            <p className="text-slate-400">Recorded status</p>
            <p className="mt-1 break-words font-medium text-slate-100">{displayRecordedStatus(challenge.legacy_status)}</p>
          </div>
        </div>
      </header>

      <div className="rounded-xl border border-amber-400/35 bg-amber-950/20 p-4 text-sm text-amber-100">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
          <p>
            <strong>Verification unavailable.</strong> Recorded payment status is not payment proof, and stored balance or progress snapshots are not approved live progress. A legacy status, including a passed or funded status, is not approval.
          </p>
        </div>
      </div>

      <div className="border-b border-white/10">
        <div role="tablist" aria-label="Challenge detail sections" className="flex flex-wrap gap-2">
          {detailTabs.map((tab, index) => {
            const selected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                ref={(element) => { tabRefs.current[index] = element; }}
                id={`${tabNamespace}-${tab.id}-tab`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`${tabNamespace}-${tab.id}-panel`}
                tabIndex={selected ? 0 : -1}
                onClick={() => setActiveTab(tab.id)}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
                className={`rounded-t-lg border border-b-0 px-4 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 ${selected ? 'border-cyan-300/35 bg-cyan-400/10 text-cyan-100' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {activeTab === 'overview' && (
        <section
          id={`${tabNamespace}-overview-panel`}
          role="tabpanel"
          aria-labelledby={`${tabNamespace}-overview-tab`}
          tabIndex="0"
          className="mep-tab-panel space-y-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
        >
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
            <section className="mep-panel mep-interior-card rounded-xl border p-6 xl:col-span-3" aria-labelledby="recorded-requirements-heading" data-challenge-requirements="true">
              <div className="flex items-start gap-3">
                <FileSearch className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
                <div>
                  <h2 id="recorded-requirements-heading" className="mep-heading text-lg font-semibold text-white">Recorded requirement sources</h2>
                  <p className="mt-1 text-sm text-slate-300">
                    These are stored catalog values, shown verbatim as a record source. They are not approved challenge rules and are not used to calculate progress, eligibility, or a monetary target.
                  </p>
                </div>
              </div>
              <RecordedRows
                className="mt-5 space-y-4 text-sm"
                rows={[
                  ['Recorded catalog profit target percent', progress.profit_target_percent],
                  ['Recorded catalog minimum trading days', progress.min_trading_days],
                ]}
              />
            </section>

            <section className="mep-panel mep-interior-card rounded-xl border p-6 xl:col-span-2" aria-labelledby="next-action-heading" data-challenge-next-action={guidance.kind}>
              <div className="flex items-start gap-3">
                <MessageCircle className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">Safe next action</p>
                  <h2 id="next-action-heading" className="mep-heading mt-1 text-lg font-semibold text-white">{guidance.title}</h2>
                </div>
              </div>
              <p className="mt-3 text-sm leading-6 text-slate-300">{guidance.description}</p>
              <div className="mt-5 flex flex-wrap gap-3">
                {guidance.includesProgram && (
                  <Link
                    to={`/programs/${challenge.program.id}`}
                    className="inline-flex items-center rounded-lg border border-cyan-300/45 bg-cyan-400/10 px-3 py-2 text-sm font-medium text-cyan-100 transition-colors hover:bg-cyan-400/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
                  >
                    Review program
                  </Link>
                )}
                <Link
                  to="/support/my-tickets"
                  className="inline-flex items-center rounded-lg border border-white/20 px-3 py-2 text-sm font-medium text-slate-100 transition-colors hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
                >
                  Open support tickets
                </Link>
              </div>
            </section>
          </div>

          <section className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4" aria-label="Recorded challenge fields">
            <div className="mep-panel rounded-xl border p-5">
              <p className="text-sm text-slate-400">Recorded initial balance</p>
              <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(challenge.initial_balance)}</p>
            </div>
            <div className="mep-panel rounded-xl border p-5">
              <p className="text-sm text-slate-400">Recorded current balance</p>
              <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(challenge.current_balance)}</p>
            </div>
            <div className="mep-panel rounded-xl border p-5">
              <p className="text-sm text-slate-400">Observed drawdown</p>
              <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(challenge.max_drawdown_observed)}</p>
            </div>
            <div className="mep-panel rounded-xl border p-5">
              <p className="text-sm text-slate-400">Recorded profit/loss</p>
              <p className="mt-2 break-words font-mono text-xl font-semibold text-white">{displayRecordedValue(progress.profit_loss)}</p>
              <p className="mt-1 text-xs text-slate-400">Stored legacy diagnostic, not approved live progress.</p>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
            <section className="mep-panel mep-interior-card rounded-xl border p-6 xl:col-span-2">
              <h2 className="mep-heading text-lg font-semibold text-white">Recorded challenge metadata</h2>
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
                  <dt className="flex items-center gap-2 text-slate-400"><Calendar className="h-4 w-4" aria-hidden="true" /> Recorded start date</dt>
                  <dd className="min-w-0 max-w-[60%] break-words text-right text-slate-100">{displayRecordedValue(challenge.start_date)}</dd>
                </div>
                <div className="flex justify-between gap-5 border-b border-white/10 pb-3">
                  <dt className="text-slate-400">Recorded end date</dt>
                  <dd className="min-w-0 max-w-[60%] break-words text-right text-slate-100">{displayRecordedValue(challenge.end_date)}</dd>
                </div>
                <div className="flex justify-between gap-5 border-b border-white/10 pb-3">
                  <dt className="text-slate-400">Recorded pass timestamp</dt>
                  <dd className="min-w-0 max-w-[60%] break-words text-right text-slate-100">{displayRecordedValue(challenge.passed_at)}</dd>
                </div>
                <div className="flex justify-between gap-5">
                  <dt className="text-slate-400">Record created</dt>
                  <dd className="min-w-0 max-w-[60%] break-words text-right text-slate-100">{displayRecordedValue(challenge.created_at)}</dd>
                </div>
              </dl>
            </section>

            <section className="mep-panel mep-interior-card rounded-xl border p-6 xl:col-span-3">
              <h2 className="mep-heading text-lg font-semibold text-white">Stored legacy diagnostics</h2>
              <p className="mt-1 text-sm text-slate-300">All values are stored snapshots only. They are not recalculated or treated as approved rules, live progress, or eligibility.</p>
              <RecordedRows className="mt-5 grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-2" rows={progressRows(progress)} />
            </section>
          </div>
        </section>
      )}

      {activeTab === 'account' && (
        <section
          id={`${tabNamespace}-account-panel`}
          role="tabpanel"
          aria-labelledby={`${tabNamespace}-account-tab`}
          tabIndex="0"
          className="mep-tab-panel mep-panel mep-interior-card rounded-xl border p-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
        >
          <div className="flex items-start gap-3">
            <Database className="mt-0.5 h-5 w-5 text-cyan-300" aria-hidden="true" />
            <div>
              <h2 className="mep-heading text-lg font-semibold text-white">Stored MT5 metadata</h2>
              <p className="mt-1 text-sm text-slate-300">Stored metadata is unverified and does not authenticate or connect to a provider.</p>
            </div>
          </div>

          {mt5Account ? (
            <>
              <p className="mt-4 rounded-lg border border-amber-400/30 bg-amber-950/20 px-3 py-2 text-sm text-amber-100">
                Provider and branch verification are unavailable. The fields below are a stored legacy snapshot only.
              </p>
              <RecordedRows className="mt-5 grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-2" rows={metadataRows(mt5Account)} />
            </>
          ) : (
            <p className="mt-5 rounded-lg border border-white/10 bg-slate-900/40 p-4 text-sm text-slate-300">
              No owner-linked stored MT5 metadata was returned for this challenge. This view cannot verify provider or branch connection status.
            </p>
          )}
        </section>
      )}
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
