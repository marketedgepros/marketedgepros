import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, FileText, RefreshCw, UserRound } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  isAccountSetupRequestCanceled,
  normaliseAccountSetupOwner,
} from '../../services/accountSetupViewService.js';

const sourceState = (status, summary = null) => ({ status, summary });
const loadingSources = () => ({
  profile: sourceState('loading'),
  documents: sourceState('loading'),
});
const unavailableSources = () => ({
  profile: sourceState('unavailable'),
  documents: sourceState('unavailable'),
});

const pluralizedRecords = (count) => `${count} challenge record${count === 1 ? '' : 's'}`;

export function accountSetupNextAction({ profileSource, documentsSource, dashboardCount }) {
  if (profileSource.status === 'loading') {
    return { title: 'Checking your next step', detail: 'Waiting for the current profile record; no missing fields are inferred.', to: null };
  }
  if (profileSource.status !== 'ready' || !profileSource.summary) {
    return { title: 'Review profile availability', detail: 'The profile check is unavailable. Open Profile or retry its check below; this is not evidence of missing details.', to: '/profile' };
  }
  if (profileSource.summary.missingFields.length) {
    return { title: 'Review missing profile fields', detail: `Not recorded in the current response: ${profileSource.summary.missingFields.join(', ')}. This is not a profile-completion requirement.`, to: '/profile' };
  }
  if (documentsSource.status === 'loading') {
    return { title: 'Checking document records', detail: 'Waiting for the recorded upload states; no upload or verification is inferred.', to: null };
  }
  if (documentsSource.status !== 'ready' || !documentsSource.summary) {
    return { title: 'Review document availability', detail: 'The document check is unavailable. Open Documents or retry its check below.', to: '/documents' };
  }
  const documents = documentsSource.summary.documents;
  if (documents.some((row) => row.state === 'needs-attention' || row.state === 'not-recorded')) {
    return { title: 'Review document upload records', detail: 'The current response reports an upload not recorded or a rejected record. Review the details in Documents; this does not establish KYC eligibility.', to: '/documents' };
  }
  if (!documentsSource.summary.allRequestedRecordsPresent) {
    return { title: 'Review document status', detail: 'Some upload evidence is unavailable. Review the recorded status before treating an upload as present or missing.', to: '/documents' };
  }
  if (!Number.isSafeInteger(dashboardCount) || dashboardCount < 0) {
    return { title: 'Review challenge availability', detail: 'The challenge count is unavailable; no empty-account conclusion is made.', to: '/challenges' };
  }
  return dashboardCount > 0
    ? { title: 'Review your recorded challenges', detail: 'The listed profile fields and upload records are present. Inspect your challenge records next; this is not verification or account eligibility.', to: '/challenges' }
    : { title: 'Explore the current catalog', detail: 'The listed profile fields and upload records are present. No challenge records were returned; you can review programs, without starting payment or activation.', to: '/programs' };
}

function SourceStatus({ source, loadingText, unavailableText, retryLabel, onRetry, children }) {
  if (source.status === 'loading') {
    return <p className="mt-3 text-sm leading-6 text-slate-300" role="status" aria-live="polite">{loadingText}</p>;
  }

  if (source.status !== 'ready' || !source.summary) {
    return (
      <div className="mt-3 rounded-lg border border-rose-300/30 bg-rose-950/30 p-3 text-sm text-rose-100" role="alert">
        <p>{unavailableText}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 inline-flex items-center gap-2 rounded-md border border-rose-200/35 px-3 py-2 font-semibold text-rose-50 transition-colors hover:bg-rose-100/10 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-200"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {retryLabel}
          </button>
        )}
      </div>
    );
  }

  return children(source.summary);
}

function GuideAction({ icon: Icon, title, detail, to, actionLabel, children }) {
  return (
    <article data-setup-step={to} className="mep-interior-card min-w-0 rounded-xl border p-4">
      <div className="flex items-start gap-3">
        <span className="rounded-lg border border-cyan-300/15 bg-cyan-300/10 p-2 text-cyan-200">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-slate-100">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-slate-400">{detail}</p>
          {children}
          <Link to={to} className="mt-4 inline-flex items-center gap-2 rounded font-semibold text-cyan-200 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
            {actionLabel}<ArrowRight className="h-4 w-4 shrink-0" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </article>
  );
}

/**
 * Pure presentation for synthetic dashboard consumers. It does not construct a
 * client or request data; callers provide source states and callbacks explicitly.
 */
export function AccountSetupGuideView({
  expanded,
  onToggle,
  onRefresh,
  onRetryProfile,
  onRetryDocuments,
  profileSource,
  documentsSource,
  dashboardCount,
}) {
  const safeDashboardCount = Number.isSafeInteger(dashboardCount) && dashboardCount >= 0 ? dashboardCount : null;
  const hasChallengeRecords = safeDashboardCount > 0;
  const isRefreshing = profileSource.status === 'loading' || documentsSource.status === 'loading';
  const nextAction = accountSetupNextAction({ profileSource, documentsSource, dashboardCount: safeDashboardCount });

  return (
    <section className="mep-panel mt-7 min-w-0 rounded-2xl border p-5 sm:p-6" aria-labelledby="getting-started-heading">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">Account setup records</p>
          <h2 id="getting-started-heading" className="mep-heading mt-2 text-xl font-semibold text-white">Review your account records</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">Server-derived record checks only. This guide does not determine profile completion, identity verification, or account eligibility.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-3 py-2 text-sm font-semibold text-slate-200 transition-colors hover:border-cyan-300 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            {isRefreshing ? 'Refreshing setup records' : 'Refresh setup records'}
          </button>
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls="account-starting-guide"
            className="rounded-lg border border-white/20 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-cyan-300 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            {expanded ? 'Hide getting-started guide' : 'Show getting-started guide'}
          </button>
        </div>
      </div>

      {expanded && (
        <div id="account-starting-guide" className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className="mep-workspace-hero mep-interior-card min-w-0 rounded-xl border p-4 sm:col-span-2" aria-labelledby="setup-next-action-heading">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Your next step</p>
            <h3 id="setup-next-action-heading" className="mep-heading mt-2 font-semibold text-slate-100">{nextAction.title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-300" role={nextAction.to ? undefined : 'status'}>{nextAction.detail}</p>
            {nextAction.to && <Link to={nextAction.to} className="mep-primary mt-3 inline-flex items-center gap-2 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">Open next step<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>}
          </div>
          <GuideAction icon={UserRound} title="Saved profile fields" detail="Review the name and contact fields returned by the current profile record." to="/profile" actionLabel="Review profile">
            <SourceStatus
              source={profileSource}
              loadingText="Checking saved profile fields…"
              unavailableText="Profile record is unavailable. Saved fields cannot be treated as missing."
              retryLabel="Retry profile check"
              onRetry={onRetryProfile}
            >
              {(summary) => (
                <div className="mt-3 text-sm leading-6 text-slate-300">
                  <p><span className="font-medium text-slate-100">Fields recorded:</span> {summary.recordedFields.length ? summary.recordedFields.join(', ') : 'None of the listed name and contact fields were returned.'}</p>
                  <p className="mt-1"><span className="font-medium text-slate-100">Fields not recorded:</span> {summary.missingFields.length ? summary.missingFields.join(', ') : 'No listed name or contact fields are absent from this response.'}</p>
                  <p className="mt-2 text-xs text-slate-400">This is a saved-field summary, not a profile-completion decision.</p>
                </div>
              )}
            </SourceStatus>
          </GuideAction>

          <GuideAction icon={FileText} title="Document upload records" detail="Review the three document types shown in Documents and their recorded upload state." to="/documents" actionLabel="Open Documents">
            <SourceStatus
              source={documentsSource}
              loadingText="Checking recorded document uploads…"
              unavailableText="Document records are unavailable. No document type is treated as missing or uploaded."
              retryLabel="Retry document check"
              onRetry={onRetryDocuments}
            >
              {(summary) => (
                <div className="mt-3 text-sm leading-6 text-slate-300">
                  <p className="text-xs text-slate-400">Document types shown in Documents: {summary.documentTypesShown}</p>
                  <ul className="mt-2 space-y-1" aria-label="Recorded document upload states">
                    {summary.documents.map((documentMetadata) => (
                      <li key={documentMetadata.type}>
                        <span className="font-medium text-slate-100">{documentMetadata.label}:</span>{' '}
                        {documentMetadata.state === 'recorded'
                          ? `Upload record present — recorded status: ${documentMetadata.status}.`
                          : documentMetadata.state === 'needs-attention'
                            ? 'Upload record needs attention — recorded status: rejected.'
                            : documentMetadata.state === 'not-recorded'
                              ? 'No upload recorded — the account service returned not uploaded.'
                            : 'Upload record unavailable.'}
                      </li>
                    ))}
                  </ul>
                  {summary.allRequestedRecordsPresent && (
                    <p className="mt-2">Upload records are present for all three document types shown in Documents.</p>
                  )}
                  <p className="mt-2 text-xs text-slate-400">File-upload records are distinct from identity verification or a KYC provider decision.</p>
                </div>
              )}
            </SourceStatus>
          </GuideAction>

          <GuideAction
            icon={ArrowRight}
            title={safeDashboardCount === null || hasChallengeRecords ? 'Review recorded challenges' : 'Explore current programs'}
            detail={safeDashboardCount === null ? 'The challenge count is unavailable. Open the challenge area to check its recorded status.' : hasChallengeRecords
              ? `${pluralizedRecords(safeDashboardCount)} appear in the existing account summary. Recorded status is not live activity.`
              : 'The existing account summary has no challenge records. You can review the current catalog.'}
            to={safeDashboardCount === null || hasChallengeRecords ? '/challenges' : '/programs'}
            actionLabel={safeDashboardCount === null || hasChallengeRecords ? 'Review challenges' : 'Explore programs'}
          />

          <GuideAction icon={AlertCircle} title="Capabilities and help" detail="MT5 and KYC-provider capabilities are unavailable from this account workspace. Payment availability is checked separately in an order checkout; a stored purchase does not activate trading or payouts." to="/support/create-ticket" actionLabel="Get help from Support">
            <p className="mt-3 text-xs leading-5 text-slate-400">Use Support for account questions; this guide does not enable payment, trading-platform, or provider actions.</p>
          </GuideAction>
        </div>
      )}
    </section>
  );
}

function AccountSetupGuideSession({ owner, dashboardCount, service }) {
  const [expanded, setExpanded] = useState(true);
  const validOwner = useMemo(() => {
    try {
      return normaliseAccountSetupOwner(owner);
    } catch {
      return null;
    }
  }, [owner?.userId, owner?.tenantId, owner?.role]);
  const [sources, setSources] = useState(() => (
    validOwner && service ? loadingSources() : unavailableSources()
  ));
  const mountedRef = useRef(false);
  const activeRequestsRef = useRef({ profile: null, documents: null });

  const cancelRequests = useCallback(() => {
    Object.values(activeRequestsRef.current).forEach((request) => request?.controller.abort());
    activeRequestsRef.current = { profile: null, documents: null };
  }, []);

  const loadSource = useCallback(async (source) => {
    if (!validOwner || !service || activeRequestsRef.current[source]) return false;
    const method = source === 'profile' ? 'loadProfile' : 'loadDocuments';
    if (typeof service[method] !== 'function') return false;

    const request = { id: Symbol(source), controller: new AbortController() };
    activeRequestsRef.current[source] = request;
    if (mountedRef.current) {
      setSources((previous) => ({ ...previous, [source]: sourceState('loading') }));
    }

    try {
      const summary = await service[method](validOwner, request.controller.signal);
      if (!mountedRef.current || request.controller.signal.aborted || activeRequestsRef.current[source]?.id !== request.id) {
        return false;
      }
      setSources((previous) => ({ ...previous, [source]: sourceState('ready', summary) }));
      return true;
    } catch (error) {
      if (!mountedRef.current || request.controller.signal.aborted
        || activeRequestsRef.current[source]?.id !== request.id
        || isAccountSetupRequestCanceled(error)) {
        return false;
      }
      // Errors stay unavailable; raw server messages and prior source data are not retained.
      setSources((previous) => ({ ...previous, [source]: sourceState('error') }));
      return false;
    } finally {
      if (activeRequestsRef.current[source]?.id === request.id) {
        activeRequestsRef.current[source] = null;
      }
    }
  }, [service, validOwner]);

  useEffect(() => {
    mountedRef.current = true;
    cancelRequests();
    if (!validOwner || !service) {
      setSources(unavailableSources());
      return () => {
        mountedRef.current = false;
        cancelRequests();
      };
    }

    setSources(loadingSources());
    void loadSource('profile');
    void loadSource('documents');
    return () => {
      mountedRef.current = false;
      cancelRequests();
    };
  }, [cancelRequests, loadSource, service, validOwner]);

  const refresh = useCallback(() => {
    void loadSource('profile');
    void loadSource('documents');
  }, [loadSource]);

  return (
    <AccountSetupGuideView
      expanded={expanded}
      onToggle={() => setExpanded((value) => !value)}
      onRefresh={refresh}
      onRetryProfile={() => { void loadSource('profile'); }}
      onRetryDocuments={() => { void loadSource('documents'); }}
      profileSource={sources.profile}
      documentsSource={sources.documents}
      dashboardCount={dashboardCount}
    />
  );
}

/**
 * A principal-keyed wrapper guarantees old source state is cleared and in-flight
 * reads are aborted whenever authentication identity, tenant, or role changes.
 */
export default function AccountSetupGuide({ owner, dashboardCount, service }) {
  const key = JSON.stringify([
    owner?.userId ?? null,
    owner?.tenantId ?? null,
    owner?.role ?? null,
  ]);
  return <AccountSetupGuideSession key={key} owner={owner} dashboardCount={dashboardCount} service={service} />;
}
