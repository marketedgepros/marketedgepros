import { useEffect, useMemo, useRef } from "react";

const keyFor = (principal) => principal?.key ?? null;

/**
 * A principal-scoped request boundary for CRM pages.
 *
 * A lease is valid only while its auth/id/tenant/role key is still current.  Changing
 * that key aborts every Axios-bound signal synchronously and the React effect cleanup
 * repeats the cancellation for the prior key.  Updating auth metadata for the same
 * key deliberately does not invalidate in-flight scoped work.
 */
export const createAdminClosureCrmIdentityBoundary = (initialPrincipal = null) => {
  let principal = initialPrincipal;
  let principalKey = keyFor(initialPrincipal);
  let generation = 0;
  const leases = new Set();

  const release = (lease, { abort = false } = {}) => {
    if (abort && !lease.controller.signal.aborted) lease.controller.abort();
    leases.delete(lease);
  };

  const cancelKey = (key) => {
    for (const lease of [...leases]) {
      if (lease.key === key) release(lease, { abort: true });
    }
  };

  const synchronize = (nextPrincipal) => {
    const nextKey = keyFor(nextPrincipal);
    if (nextKey === principalKey) {
      principal = nextPrincipal;
      return false;
    }
    const previousKey = principalKey;
    principal = nextPrincipal;
    principalKey = nextKey;
    generation += 1;
    cancelKey(previousKey);
    return true;
  };

  const start = () => {
    const controller = new AbortController();
    const lease = {
      key: principalKey,
      generation,
      principal,
      controller,
      signal: controller.signal,
      isCurrent: () => (
        !controller.signal.aborted
        && principalKey === lease.key
        && generation === lease.generation
      ),
      cancel: () => release(lease, { abort: true }),
      finish: () => release(lease),
    };
    leases.add(lease);
    return lease;
  };

  return {
    synchronize,
    start,
    cancelKey,
    cancelAll: () => {
      for (const lease of [...leases]) release(lease, { abort: true });
    },
  };
};

/**
 * Keeps CRM async work bound to the exact authenticated principal.  synchronize() is
 * deliberately called during render so a committed identity change invalidates stale
 * continuations before they can publish a state update, toast, or navigation.
 */
export default function useAdminClosureCrmIdentityGuard(principal) {
  const boundaryRef = useRef(null);
  if (boundaryRef.current === null) {
    boundaryRef.current = createAdminClosureCrmIdentityBoundary(principal);
  } else {
    boundaryRef.current.synchronize(principal);
  }

  const boundary = boundaryRef.current;
  const principalKey = keyFor(principal);

  useEffect(() => () => boundary.cancelKey(principalKey), [boundary, principalKey]);
  useEffect(() => () => boundary.cancelAll(), [boundary]);

  return useMemo(() => ({ start: boundary.start }), [boundary]);
}
