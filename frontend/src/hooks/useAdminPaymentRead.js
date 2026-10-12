import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  adminPaymentIdentityKey,
  adminPaymentPrincipalFromAuth,
  isAdminPaymentRecordRequestCanceled,
} from "../services/adminPaymentRecordViewService.js";

/**
 * Publishes a read only for the exact scalar principal and query. A new auth-store
 * user object for the same id/tenant/role does not create another GET. Refresh is
 * explicit; this hook has no retry loop or polling behavior.
 */
export default function useAdminPaymentRead({
  isAuthenticated,
  userId,
  tenantId,
  role,
  queryKey,
  load,
}) {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const loadRef = useRef(load);
  const principal = useMemo(
    () => adminPaymentPrincipalFromAuth({ id: userId, tenant_id: tenantId, role }, isAuthenticated),
    [isAuthenticated, role, tenantId, userId],
  );
  const principalKey = useMemo(
    () => adminPaymentIdentityKey({ isAuthenticated, userId, tenantId, role }),
    [isAuthenticated, role, tenantId, userId],
  );
  const requestKey = useMemo(
    () => JSON.stringify([principalKey, queryKey, refreshVersion]),
    [principalKey, queryKey, refreshVersion],
  );
  const [state, setState] = useState({
    key: null,
    value: null,
    loading: true,
    error: null,
  });
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
        error: "Your account context is unavailable. Sign in again before viewing payment records.",
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
        if (
          controller.signal.aborted ||
          generation !== generationRef.current ||
          isAdminPaymentRecordRequestCanceled(error)
        ) {
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

  // Effects run after paint; a different page/filter/principal must never expose old rows.
  const current = state.key === requestKey
    ? state
    : { key: requestKey, value: null, loading: true, error: null };
  const refresh = useCallback(() => {
    if (!inFlightRef.current) setRefreshVersion((version) => version + 1);
  }, []);

  return { ...current, principal, principalKey, requestKey, refresh };
}

export { useAdminPaymentRead };
