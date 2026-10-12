import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  adminInsightPrincipalFromAuth,
  adminInsightRequestKey,
  isAdminInsightRequestCanceled,
} from "../services/adminInsightViewService.js";

/**
 * Reads one canonical insight view for the scalar session + kind + days key. A fresh
 * auth-store object for the same principal does not fetch again; manual refresh is
 * explicit, single-shot, and never a retry or polling loop.
 */
export default function useAdminInsightRead({
  isAuthenticated,
  userId,
  tenantId,
  role,
  kind,
  days,
  load,
}) {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const loadRef = useRef(load);
  const principal = useMemo(
    () => adminInsightPrincipalFromAuth({ id: userId, tenant_id: tenantId, role }, isAuthenticated),
    [isAuthenticated, role, tenantId, userId],
  );
  const baseKey = useMemo(
    () => adminInsightRequestKey({ isAuthenticated, userId, tenantId, role, kind, days }),
    [days, isAuthenticated, kind, role, tenantId, userId],
  );
  const requestKey = useMemo(
    () => JSON.stringify([baseKey, refreshVersion]),
    [baseKey, refreshVersion],
  );
  const [state, setState] = useState({ key: null, value: null, loading: true, error: null });
  const generationRef = useRef(0);
  const inFlightRef = useRef(false);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    const generation = ++generationRef.current;
    const controller = new AbortController();
    inFlightRef.current = false;
    setState({ key: requestKey, value: null, loading: true, error: null });

    if (!principal) {
      setState({
        key: requestKey,
        value: null,
        loading: false,
        error: "Your administrator account context is unavailable. Sign in again before viewing recorded insights.",
      });
      return () => {
        generationRef.current += 1;
        controller.abort();
      };
    }

    inFlightRef.current = true;
    Promise.resolve()
      .then(() => loadRef.current(principal.owner, controller.signal))
      .then((value) => {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setState({ key: requestKey, value, loading: false, error: null });
      })
      .catch((error) => {
        if (controller.signal.aborted || generation !== generationRef.current || isAdminInsightRequestCanceled(error)) {
          return;
        }
        setState({ key: requestKey, value: null, loading: false, error });
      })
      .finally(() => {
        if (generation === generationRef.current) inFlightRef.current = false;
      });

    return () => {
      generationRef.current += 1;
      inFlightRef.current = false;
      controller.abort();
    };
  }, [principal, requestKey]);

  // Effects happen after paint. A changed auth/session/filter key must never expose stale rows.
  const current = state.key === requestKey
    ? state
    : { key: requestKey, value: null, loading: true, error: null };
  const refresh = useCallback(() => {
    if (!inFlightRef.current) setRefreshVersion((version) => version + 1);
  }, []);

  return { ...current, principal, requestKey, refresh };
}

export { useAdminInsightRead };
