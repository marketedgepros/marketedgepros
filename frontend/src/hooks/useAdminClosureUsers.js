import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  adminClosureUsersIdentityKey,
  adminClosureUsersPrincipalFromAuth,
  isAdminClosureUsersRequestCanceled,
} from "../services/adminClosureUsersService.js";

/**
 * Publishes a users read only for the exact auth/id/tenant/role/query tuple.
 * It has no polling, retry, refresh replay, or retention of a previous principal's data.
 */
export default function useAdminClosureUsersRead({
  isAuthenticated,
  userId,
  tenantId,
  role,
  queryKey,
  load,
}) {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const loadRef = useRef(load);
  const generationRef = useRef(0);
  const inFlightRef = useRef(false);
  const principal = useMemo(
    () => adminClosureUsersPrincipalFromAuth({ id: userId, tenant_id: tenantId, role }, isAuthenticated),
    [isAuthenticated, role, tenantId, userId],
  );
  const principalKey = useMemo(
    () => adminClosureUsersIdentityKey({ isAuthenticated, userId, tenantId, role }),
    [isAuthenticated, role, tenantId, userId],
  );
  const requestKey = useMemo(
    () => JSON.stringify([principalKey, queryKey, refreshVersion]),
    [principalKey, queryKey, refreshVersion],
  );
  const [state, setState] = useState({ key: null, value: null, loading: true, error: null });

  useEffect(() => { loadRef.current = load; }, [load]);

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
        error: "Your admin account context is unavailable. Sign in again before viewing user records.",
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
        if (controller.signal.aborted || generation !== generationRef.current || isAdminClosureUsersRequestCanceled(error)) return;
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

  const current = state.key === requestKey ? state : { key: requestKey, value: null, loading: true, error: null };
  const refresh = useCallback(() => {
    if (!inFlightRef.current) setRefreshVersion((version) => version + 1);
  }, []);
  return { ...current, principal, principalKey, requestKey, refresh };
}

export { useAdminClosureUsersRead };
