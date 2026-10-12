import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  adminClosureKycIdentityKey,
  adminClosureKycPrincipalFromAuth,
  createAdminClosureKycService,
  isAdminClosureKycRequestCanceled,
} from '../services/adminClosureKycService.js';

/**
 * Each request is tied to the exact authenticated id/tenant/role tuple. The hook
 * has no polling or retry loop; refresh is always a visible user action.
 */
export default function useAdminClosureKyc({ user, isAuthenticated, service = createAdminClosureKycService() }) {
  const principal = useMemo(
    () => adminClosureKycPrincipalFromAuth(user, isAuthenticated),
    [isAuthenticated, user?.id, user?.role, user?.tenant?.id, user?.tenant_id, user?.tenantId],
  );
  const principalKey = useMemo(
    () => adminClosureKycIdentityKey({ user, isAuthenticated }),
    [isAuthenticated, user?.id, user?.role, user?.tenant?.id, user?.tenant_id, user?.tenantId],
  );
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [listState, setListState] = useState({ key: null, value: null, loading: true, error: null });
  const [detailState, setDetailState] = useState({ key: null, value: null, loading: false, error: null });
  const serviceRef = useRef(service);
  const listGeneration = useRef(0);
  const detailGeneration = useRef(0);

  useEffect(() => { serviceRef.current = service; }, [service]);

  const listRequestKey = useMemo(
    () => JSON.stringify([principalKey, 'pending', 1, 20, refreshVersion]),
    [principalKey, refreshVersion],
  );

  useEffect(() => {
    const generation = ++listGeneration.current;
    const controller = new AbortController();
    setListState({ key: listRequestKey, value: null, loading: true, error: null });
    setSelectedUserId(null);
    setDetailState({ key: null, value: null, loading: false, error: null });

    if (!principal) {
      setListState({
        key: listRequestKey,
        value: null,
        loading: false,
        error: new Error('KYC records are unavailable because the authenticated administrator context is incomplete.'),
      });
      return () => {
        listGeneration.current += 1;
        controller.abort();
      };
    }

    serviceRef.current.loadSubmissions({
      expectedOwner: principal.owner,
      status: 'pending',
      page: 1,
      perPage: 20,
      signal: controller.signal,
    }).then((value) => {
      if (!controller.signal.aborted && generation === listGeneration.current) {
        setListState({ key: listRequestKey, value, loading: false, error: null });
      }
    }).catch((error) => {
      if (!controller.signal.aborted && generation === listGeneration.current && !isAdminClosureKycRequestCanceled(error)) {
        setListState({ key: listRequestKey, value: null, loading: false, error });
      }
    });

    return () => {
      listGeneration.current += 1;
      controller.abort();
    };
  }, [listRequestKey, principal]);

  const currentList = listState.key === listRequestKey
    ? listState
    : { key: listRequestKey, value: null, loading: true, error: null };
  const selectedIsCurrent = Boolean(
    selectedUserId && currentList.value?.submissions.some((submission) => submission.userId === selectedUserId),
  );
  const detailRequestKey = selectedIsCurrent
    ? JSON.stringify([principalKey, selectedUserId, refreshVersion])
    : null;

  useEffect(() => {
    const generation = ++detailGeneration.current;
    const controller = new AbortController();
    if (!detailRequestKey || !principal) {
      setDetailState({ key: detailRequestKey, value: null, loading: false, error: null });
      return () => {
        detailGeneration.current += 1;
        controller.abort();
      };
    }
    setDetailState({ key: detailRequestKey, value: null, loading: true, error: null });
    serviceRef.current.loadSubmission({
      expectedOwner: principal.owner,
      userId: selectedUserId,
      signal: controller.signal,
    }).then((value) => {
      if (!controller.signal.aborted && generation === detailGeneration.current) {
        setDetailState({ key: detailRequestKey, value, loading: false, error: null });
      }
    }).catch((error) => {
      if (!controller.signal.aborted && generation === detailGeneration.current && !isAdminClosureKycRequestCanceled(error)) {
        setDetailState({ key: detailRequestKey, value: null, loading: false, error });
      }
    });
    return () => {
      detailGeneration.current += 1;
      controller.abort();
    };
  }, [detailRequestKey, principal, selectedUserId]);

  const currentDetail = detailState.key === detailRequestKey
    ? detailState
    : { key: detailRequestKey, value: null, loading: Boolean(detailRequestKey), error: null };

  const selectSubmission = useCallback((userId) => {
    const normalized = Number(userId);
    if (!Number.isSafeInteger(normalized) || normalized < 1) return;
    if (!currentList.value?.submissions.some((submission) => submission.userId === normalized)) return;
    setSelectedUserId(normalized);
  }, [currentList.value]);

  const refresh = useCallback(() => {
    setRefreshVersion((version) => version + 1);
  }, []);

  return {
    principal,
    principalKey,
    list: currentList,
    detail: currentDetail,
    selectedUserId: selectedIsCurrent ? selectedUserId : null,
    selectSubmission,
    refresh,
  };
}

export { useAdminClosureKyc };
