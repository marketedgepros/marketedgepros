import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createAffiliateRecordViewService,
  normaliseAffiliateRecordExpectedOwner,
  isAffiliateRecordRequestCanceled,
} from '../services/affiliateRecordViewService.js';
import { loadAffiliateDashboard } from '../services/affiliateViewService.js';

const tenantValue = (value) => value ?? null;

/** Keeps a session refresh with the same principal from becoming another GET. */
export const affiliatePrincipalKey = ({ isAuthenticated, userId, tenantId, role }) => JSON.stringify([
  isAuthenticated === true, userId ?? null, tenantValue(tenantId), role ?? null,
]);

const validOwner = ({ isAuthenticated, userId, tenantId, role }) => {
  if (isAuthenticated !== true || role !== 'affiliate') return null;
  try {
    return normaliseAffiliateRecordExpectedOwner({ user_id: userId, tenant_id: tenantId });
  } catch {
    return null;
  }
};

/**
 * One owner-bound read at a time. A key includes only scalar identity/query state,
 * never the mutable auth user object. Every cleanup both aborts and invalidates late work.
 */
export function useAffiliateAccountRead({
  isAuthenticated,
  userId,
  tenantId,
  role,
  queryKey,
  load,
}) {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const owner = useMemo(
    () => validOwner({ isAuthenticated, userId, tenantId, role }),
    [isAuthenticated, role, tenantId, userId],
  );
  const principalKey = useMemo(
    () => affiliatePrincipalKey({ isAuthenticated, userId, tenantId, role }),
    [isAuthenticated, role, tenantId, userId],
  );
  const requestKey = useMemo(
    () => JSON.stringify([principalKey, queryKey, refreshVersion]),
    [principalKey, queryKey, refreshVersion],
  );
  const [state, setState] = useState({ key: null, view: null, loading: true, error: null });
  const generationRef = useRef(0);
  const inFlightRef = useRef(false);

  useEffect(() => {
    const generation = ++generationRef.current;
    const controller = new AbortController();
    inFlightRef.current = false;
    setState({ key: requestKey, view: null, loading: true, error: null });

    // Role and independently validated owner are checked before invoking any transport.
    if (!owner) {
      setState({
        key: requestKey,
        view: null,
        loading: false,
        error: 'Your current affiliate account context could not be verified. Please sign in again.',
      });
      return () => {
        generationRef.current += 1;
        controller.abort();
      };
    }

    inFlightRef.current = true;
    Promise.resolve()
      .then(() => load(owner, controller.signal))
      .then((view) => {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setState({ key: requestKey, view, loading: false, error: null });
      })
      .catch((error) => {
        if (controller.signal.aborted || generation !== generationRef.current || isAffiliateRecordRequestCanceled(error)) return;
        setState({ key: requestKey, view: null, loading: false, error });
      })
      .finally(() => {
        if (generation === generationRef.current) inFlightRef.current = false;
      });

    return () => {
      generationRef.current += 1;
      inFlightRef.current = false;
      controller.abort();
    };
  }, [load, owner, requestKey]);

  // Effects run after render, so hide a previous page/identity/export immediately.
  const current = state.key === requestKey
    ? state
    : { key: requestKey, view: null, loading: true, error: null };
  const refresh = useCallback(() => {
    if (!inFlightRef.current) setRefreshVersion((version) => version + 1);
  }, []);

  return { ...current, principalKey, requestKey, refresh };
}

export function useAffiliateRecordRead({
  kind,
  isAuthenticated,
  userId,
  tenantId,
  role,
  page,
  perPage,
  status,
  apiClient,
}) {
  const queryKey = useMemo(() => JSON.stringify([kind, page, perPage, status]), [kind, page, perPage, status]);
  const load = useCallback((expectedOwner, signal) => (
    createAffiliateRecordViewService(apiClient)[kind]({
      expectedOwner,
      role,
      page,
      perPage,
      status,
      signal,
    })
  ), [apiClient, kind, page, perPage, role, status]);
  return useAffiliateAccountRead({
    isAuthenticated, userId, tenantId, role, queryKey, load,
  });
}

export function useAffiliateDashboardRead({
  isAuthenticated,
  userId,
  tenantId,
  role,
  apiClient,
}) {
  const load = useCallback((expectedOwner, signal) => loadAffiliateDashboard({
    apiClient,
    expectedOwner,
    signal,
  }), [apiClient]);
  return useAffiliateAccountRead({
    isAuthenticated,
    userId,
    tenantId,
    role,
    queryKey: 'affiliate-dashboard',
    load,
  });
}
