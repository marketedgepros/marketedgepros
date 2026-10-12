import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  adminClosureSettingsIdentityKey,
  adminClosureSettingsPrincipalFromAuth,
  isAdminClosureSettingsRequestCanceled,
  normaliseAdminClosureTenantDraft,
} from "../services/adminClosureSettingsService.js";

const sameDraft = (left, right) => (
  left?.name === right?.name
  && left?.contact_email === right?.contact_email
  && left?.contact_phone === right?.contact_phone
);

const emptyState = (key) => ({
  key,
  value: null,
  draft: null,
  loading: true,
  saving: false,
  error: null,
  actionError: null,
  acknowledgement: null,
});

/**
 * A one-shot tenant-settings controller. Every auth/id/tenant/role change clears
 * stale data, aborts transport through Axios, and invalidates a late write result.
 */
export default function useAdminClosureSettings({
  isAuthenticated,
  userId,
  tenantId,
  role,
  load,
  save,
}) {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const loadRef = useRef(load);
  const saveRef = useRef(save);
  const generationRef = useRef(0);
  const readInFlightRef = useRef(false);
  const writeControllerRef = useRef(null);
  const principal = useMemo(
    () => adminClosureSettingsPrincipalFromAuth({ id: userId, tenant_id: tenantId, role }, isAuthenticated),
    [isAuthenticated, role, tenantId, userId],
  );
  const identityKey = useMemo(
    () => adminClosureSettingsIdentityKey({ isAuthenticated, userId, tenantId, role }),
    [isAuthenticated, role, tenantId, userId],
  );
  const requestKey = useMemo(
    () => JSON.stringify([identityKey, refreshVersion]),
    [identityKey, refreshVersion],
  );
  const [state, setState] = useState(() => emptyState(requestKey));

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    saveRef.current = save;
  }, [save]);

  useEffect(() => {
    const generation = ++generationRef.current;
    const controller = new AbortController();
    writeControllerRef.current?.abort();
    writeControllerRef.current = null;
    readInFlightRef.current = false;
    setState(emptyState(requestKey));

    if (!principal) {
      setState({
        ...emptyState(requestKey),
        loading: false,
        error: "Tenant settings require a signed-in supermaster session. The server separately verifies the configured platform root.",
      });
      return () => {
        generationRef.current += 1;
        controller.abort();
      };
    }

    readInFlightRef.current = true;
    Promise.resolve()
      .then(() => loadRef.current(principal.owner, controller.signal))
      .then((value) => {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setState({
          key: requestKey,
          value,
          draft: value.tenantSettings,
          loading: false,
          saving: false,
          error: null,
          actionError: null,
          acknowledgement: null,
        });
      })
      .catch((error) => {
        if (controller.signal.aborted || generation !== generationRef.current || isAdminClosureSettingsRequestCanceled(error)) {
          return;
        }
        setState({
          ...emptyState(requestKey),
          loading: false,
          error,
        });
      })
      .finally(() => {
        if (generation === generationRef.current) readInFlightRef.current = false;
      });

    return () => {
      generationRef.current += 1;
      readInFlightRef.current = false;
      controller.abort();
      writeControllerRef.current?.abort();
      writeControllerRef.current = null;
    };
  }, [principal, requestKey]);

  // Effects happen after paint. Never expose an earlier principal's value in that gap.
  const current = state.key === requestKey ? state : emptyState(requestKey);
  const dirty = Boolean(current.value && current.draft && !sameDraft(current.value.tenantSettings, current.draft));

  const editDraft = useCallback((updater) => {
    setState((previous) => {
      if (previous.key !== requestKey || previous.loading || previous.saving || !previous.draft) return previous;
      const candidate = typeof updater === "function" ? updater(previous.draft) : updater;
      try {
        return {
          ...previous,
          draft: normaliseAdminClosureTenantDraft(candidate),
          actionError: null,
          acknowledgement: null,
        };
      } catch (error) {
        return { ...previous, actionError: error, acknowledgement: null };
      }
    });
  }, [requestKey]);

  const refresh = useCallback(() => {
    if (!readInFlightRef.current && !writeControllerRef.current) {
      setRefreshVersion((version) => version + 1);
    }
  }, []);

  const saveDraft = useCallback(async () => {
    if (!principal || !current.value || !current.draft || current.loading || current.saving || !dirty) return false;
    const generation = generationRef.current;
    const draft = current.draft;
    const controller = new AbortController();
    writeControllerRef.current?.abort();
    writeControllerRef.current = controller;
    setState((previous) => (
      previous.key === requestKey
        ? { ...previous, saving: true, actionError: null, acknowledgement: null }
        : previous
    ));

    try {
      const acknowledgement = await saveRef.current(principal.owner, draft, controller.signal);
      if (controller.signal.aborted || generation !== generationRef.current) return false;
      setState((previous) => (
        previous.key === requestKey
          ? {
            ...previous,
            value: acknowledgement,
            draft: acknowledgement.tenantSettings,
            saving: false,
            actionError: null,
            acknowledgement: "Saved from the server persistence acknowledgement.",
          }
          : previous
      ));
      return true;
    } catch (error) {
      if (controller.signal.aborted || generation !== generationRef.current || isAdminClosureSettingsRequestCanceled(error)) {
        return false;
      }
      setState((previous) => (
        previous.key === requestKey
          ? { ...previous, saving: false, actionError: error, acknowledgement: null }
          : previous
      ));
      return false;
    } finally {
      if (writeControllerRef.current === controller) writeControllerRef.current = null;
    }
  }, [current.draft, current.loading, current.saving, current.value, dirty, principal, requestKey]);

  return {
    ...current,
    principal,
    dirty,
    editDraft,
    refresh,
    saveDraft,
  };
}

export { useAdminClosureSettings };
