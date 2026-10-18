import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  adminClosureKycIdentityKey,
  adminClosureKycPrincipalFromAuth,
  createAdminClosureKycService,
  isAdminClosureKycRequestCanceled,
} from '../services/adminClosureKycService.js';

const LIST_STATUS = 'pending';
const LIST_PER_PAGE = 20;

const lastKnownPage = (pagination) => Math.max(1, pagination?.pages ?? 1);

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
  const [pageState, setPageState] = useState(() => ({ principalKey, status: LIST_STATUS, page: 1 }));
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [listState, setListState] = useState({ key: null, value: null, loading: true, error: null });
  const [detailState, setDetailState] = useState({ key: null, value: null, loading: false, error: null });
  const serviceRef = useRef(service);
  const listGeneration = useRef(0);
  const detailGeneration = useRef(0);

  useEffect(() => { serviceRef.current = service; }, [service]);

  const page = pageState.principalKey === principalKey && pageState.status === LIST_STATUS
    ? pageState.page
    : 1;

  useEffect(() => {
    setPageState((current) => (
      current.principalKey === principalKey && current.status === LIST_STATUS
        ? current
        : { principalKey, status: LIST_STATUS, page: 1 }
    ));
    setSelectedUserId(null);
  }, [principalKey]);

  const listRequestKey = useMemo(
    () => JSON.stringify([principalKey, LIST_STATUS, page, LIST_PER_PAGE, refreshVersion]),
    [page, principalKey, refreshVersion],
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
      status: LIST_STATUS,
      page,
      perPage: LIST_PER_PAGE,
      signal: controller.signal,
    }).then((value) => {
      if (!controller.signal.aborted && generation === listGeneration.current) {
        const correctedPage = Math.min(value.pagination.page, lastKnownPage(value.pagination));
        if (correctedPage !== page) {
          setPageState((current) => (
            current.principalKey === principalKey && current.status === LIST_STATUS && current.page === page
              ? { ...current, page: correctedPage }
              : current
          ));
          return;
        }
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
  }, [listRequestKey, page, principal, principalKey]);

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

  const goToPage = useCallback((requestedPage) => {
    if (!Number.isSafeInteger(requestedPage)) return;
    const boundedPage = Math.min(Math.max(1, requestedPage), lastKnownPage(currentList.value?.pagination));
    setPageState({ principalKey, status: LIST_STATUS, page: boundedPage });
  }, [currentList.value?.pagination, principalKey]);

  const previousPage = useCallback(() => {
    goToPage(page - 1);
  }, [goToPage, page]);

  const nextPage = useCallback(() => {
    goToPage(page + 1);
  }, [goToPage, page]);

  const pagination = currentList.value?.pagination ?? null;
  const responsePage = pagination?.page ?? page;
  const responseLastPage = lastKnownPage(pagination);

  return {
    principal,
    principalKey,
    list: currentList,
    detail: currentDetail,
    selectedUserId: selectedIsCurrent ? selectedUserId : null,
    selectSubmission,
    refresh,
    previousPage,
    nextPage,
    canPreviousPage: !currentList.loading && responsePage > 1,
    canNextPage: !currentList.loading && responsePage < responseLastPage,
  };
}

export { useAdminClosureKyc };
