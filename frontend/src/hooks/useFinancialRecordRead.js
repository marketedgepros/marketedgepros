import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  financialIdentityKey,
  financialPrincipalFromAuth,
  isFinancialRecordRequestCanceled,
} from "../services/financialRecordViewService.js";

/**
 * A financial read is published only for the exact authenticated principal and
 * query. Replacing a store user object with the same scalar principal does not
 * make another GET; an explicit refresh is the only revalidation action.
 */
export default function useFinancialRecordRead({
  isAuthenticated,
  userId,
  tenantId,
  role,
  queryKey,
  load,
}) {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const principal = useMemo(
    () =>
      financialPrincipalFromAuth(
        { id: userId, tenant_id: tenantId, role },
        isAuthenticated,
      ),
    [isAuthenticated, role, tenantId, userId],
  );
  const principalKey = useMemo(
    () =>
      financialIdentityKey({
        isAuthenticated,
        userId,
        tenantId,
        role,
      }),
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
    const generation = ++generationRef.current;
    const controller = new AbortController();
    inFlightRef.current = false;
    setState({ key: requestKey, value: null, loading: true, error: null });

    if (!principal) {
      setState({
        key: requestKey,
        value: null,
        loading: false,
        error:
          "Your account context is unavailable. Sign in again before viewing financial records.",
      });
      return () => {
        generationRef.current += 1;
        controller.abort();
      };
    }

    inFlightRef.current = true;
    Promise.resolve()
      .then(() => load(principal.owner, controller.signal))
      .then((value) => {
        if (controller.signal.aborted || generation !== generationRef.current)
          return;
        setState({ key: requestKey, value, loading: false, error: null });
      })
      .catch((error) => {
        if (
          controller.signal.aborted ||
          generation !== generationRef.current ||
          isFinancialRecordRequestCanceled(error)
        )
          return;
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
  }, [load, principal, requestKey]);

  // Effects run after render: route, page, filter, and principal changes hide all
  // previous rows immediately rather than allowing stale financial records to paint.
  const current =
    state.key === requestKey
      ? state
      : { key: requestKey, value: null, loading: true, error: null };
  const refresh = useCallback(() => {
    if (!inFlightRef.current) setRefreshVersion((version) => version + 1);
  }, []);

  return { ...current, principal, principalKey, requestKey, refresh };
}
