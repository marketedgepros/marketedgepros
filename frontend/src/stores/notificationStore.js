import { create } from 'zustand';
import api from '../services/api.js';
import useAuthStore from '../store/authStore.js';
import {
  DEFAULT_PER_PAGE,
  MAX_PAGE,
  boundedNotificationPerPage,
  isNotificationRequestCanceled,
  loadNotificationPreferences,
  loadNotifications,
  loadUnreadNotificationCount,
  markAllNotificationsRead,
  markNotificationRead,
  removeNotification,
  saveNotificationPreferences,
} from '../services/notificationViewService.js';

let requestGeneration = 0;
let requestSequence = 0;
const activeRequests = new Map();
let activeMutation = null;

const initialFilters = () => ({ type: null, is_read: null, priority: null });
const initialState = (contextKey = null) => ({
  contextKey,
  notifications: [],
  dropdownNotifications: [],
  // null means unknown: a failed count must never visually become a real zero.
  unreadCount: null,
  preferences: null,
  loading: false,
  dropdownLoading: false,
  preferencesLoading: false,
  countLoading: false,
  error: null,
  dropdownError: null,
  preferencesError: null,
  countError: null,
  actionErrors: {},
  pendingAction: null,
  currentPage: 1,
  totalPages: 0,
  total: 0,
  perPage: DEFAULT_PER_PAGE,
  dropdownPage: 1,
  dropdownTotal: 0,
  dropdownPerPage: 10,
  filters: initialFilters(),
});

const apiErrorMessage = (error, fallback) => {
  const candidate = error?.response?.data?.error ?? error?.response?.data?.message ?? error?.message;
  return typeof candidate === 'string' && candidate.trim().length > 0 ? candidate.trim() : fallback;
};

const asPositiveInteger = (value) => {
  if (Number.isSafeInteger(value) && value > 0) return value;
  if (typeof value === 'string' && /^(?:[1-9]\d*)$/.test(value)) {
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) ? parsed : null;
  }
  return null;
};

const currentPrincipal = () => {
  const auth = useAuthStore.getState();
  const user = auth?.user;
  const userId = asPositiveInteger(user?.id);
  const rawTenant = user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id ?? null;
  const tenantId = rawTenant === null || rawTenant === undefined ? null : asPositiveInteger(rawTenant);
  const role = typeof user?.role === 'string' ? user.role : null;
  if (!auth?.isAuthenticated || !userId || (rawTenant !== null && rawTenant !== undefined && !tenantId)) return null;
  return {
    key: `number:${userId}|${tenantId === null ? 'null' : `number:${tenantId}`}|role:${role ?? 'none'}`,
    owner: { user_id: userId, tenant_id: tenantId },
  };
};

const abortActiveRequests = () => {
  activeRequests.forEach((request) => request.controller.abort());
  activeRequests.clear();
};

const requestIsCurrent = (scope, request, contextKey) => (
  activeRequests.get(scope)?.identity === request.identity
  && request.generation === requestGeneration
  && currentPrincipal()?.key === contextKey
);

const startRequest = (scope, contextKey) => {
  activeRequests.get(scope)?.controller.abort();
  const request = {
    controller: new AbortController(),
    identity: ++requestSequence,
    contextKey,
    generation: requestGeneration,
  };
  activeRequests.set(scope, request);
  return request;
};

const clearRequestIfCurrent = (scope, request) => {
  if (activeRequests.get(scope)?.identity === request.identity) activeRequests.delete(scope);
};

const isCurrentMutation = (mutation) => (
  mutation.generation === requestGeneration
  && currentPrincipal()?.key === mutation.contextKey
  && activeMutation?.identity === mutation.identity
);

const matchesPageFilters = (notification, filters) => (
  (!filters.type || notification.type === filters.type)
  && (!filters.priority || notification.priority === filters.priority)
  && (filters.is_read !== false || notification.is_read === false)
  && (filters.is_read !== true || notification.is_read === true)
);

const applyReadToLists = (state, notification) => {
  const pageContains = state.notifications.some((item) => item.id === notification.id);
  const removeFromPage = pageContains && !matchesPageFilters(notification, state.filters);
  return {
    notifications: removeFromPage
      ? state.notifications.filter((item) => item.id !== notification.id)
      : state.notifications.map((item) => (item.id === notification.id ? notification : item)),
    dropdownNotifications: state.dropdownNotifications.map((item) => (
      item.id === notification.id ? notification : item
    )),
    total: removeFromPage ? Math.max(0, state.total - 1) : state.total,
    totalPages: removeFromPage ? Math.min(MAX_PAGE, Math.ceil(Math.max(0, state.total - 1) / state.perPage)) : state.totalPages,
  };
};

const removeFromLists = (state, notificationId) => {
  const pageContains = state.notifications.some((item) => item.id === notificationId);
  const dropdownContains = state.dropdownNotifications.some((item) => item.id === notificationId);
  return {
    notifications: state.notifications.filter((item) => item.id !== notificationId),
    dropdownNotifications: state.dropdownNotifications.filter((item) => item.id !== notificationId),
    total: pageContains ? Math.max(0, state.total - 1) : state.total,
    totalPages: pageContains ? Math.min(MAX_PAGE, Math.ceil(Math.max(0, state.total - 1) / state.perPage)) : state.totalPages,
    dropdownTotal: dropdownContains ? Math.max(0, state.dropdownTotal - 1) : state.dropdownTotal,
  };
};

const useNotificationStore = create((set, get) => {
  const resetForContext = (contextKey = null) => {
    requestGeneration += 1;
    abortActiveRequests();
    activeMutation?.controller.abort();
    activeMutation = null;
    set(initialState(contextKey));
  };

  const ensureContext = () => {
    const principal = currentPrincipal();
    if (!principal) {
      if (get().contextKey !== null) resetForContext(null);
      return null;
    }
    if (get().contextKey !== principal.key) resetForContext(principal.key);
    return principal;
  };

  const cancelReadScopesForMutation = () => {
    abortActiveRequests();
    set({ loading: false, dropdownLoading: false, preferencesLoading: false, countLoading: false });
  };

  const runMutation = (name, id, operation, errorField = 'error') => {
    const principal = ensureContext();
    if (!principal) return Promise.resolve(false);
    const requestedKey = `${principal.key}:${name}:${id ?? ''}`;
    if (activeMutation) return activeMutation.key === requestedKey ? activeMutation.promise : Promise.resolve(false);

    cancelReadScopesForMutation();
    const mutation = {
      identity: ++requestSequence,
      key: requestedKey,
      name,
      id,
      contextKey: principal.key,
      owner: principal.owner,
      generation: requestGeneration,
      controller: new AbortController(),
      promise: null,
    };
    set((state) => ({
      pendingAction: { name, id },
      actionErrors: { ...state.actionErrors, [name]: null },
      ...(errorField === 'preferencesError' ? { preferencesError: null } : {}),
    }));

    const flight = (async () => {
      try {
        const result = await operation(mutation);
        return result === true && isCurrentMutation(mutation);
      } catch (error) {
        if (isCurrentMutation(mutation) && !isNotificationRequestCanceled(error)) {
          const message = apiErrorMessage(error, 'Notification action failed');
          set((state) => ({
            actionErrors: { ...state.actionErrors, [name]: message },
            ...(errorField === 'preferencesError' ? { preferencesError: message } : {}),
          }));
        }
        return false;
      } finally {
        if (activeMutation?.identity === mutation.identity) {
          activeMutation = null;
          if (get().pendingAction?.name === mutation.name && get().pendingAction?.id === mutation.id) {
            set({ pendingAction: null });
          }
        }
      }
    })();
    mutation.promise = flight;
    activeMutation = mutation;
    return flight;
  };

  return {
    ...initialState(),

    /** Called synchronously by App whenever auth, user, tenant, or role changes. */
    reset: () => resetForContext(null),

    fetchNotifications: async (page = 1, filters = {}, options = {}) => {
      const principal = ensureContext();
      if (!principal) return false;
      // Wait for at most the one active write. A GET begun during that write
      // could otherwise carry a pre-commit snapshot over its acknowledgement.
      const pending = activeMutation;
      if (pending) {
        await pending.promise;
        if (activeMutation || currentPrincipal()?.key !== principal.key) return false;
      }
      const scope = options.scope === 'dropdown' ? 'dropdown' : 'page';
      const perPage = boundedNotificationPerPage(
        options.perPage ?? filters?.per_page ?? (scope === 'dropdown' ? 10 : get().perPage),
      );
      const effectiveFilters = {
        type: filters?.type ?? null,
        is_read: filters?.is_read ?? null,
        priority: filters?.priority ?? null,
      };
      const request = startRequest(scope, principal.key);
      const isPage = scope === 'page';
      set(isPage ? {
        notifications: [], loading: true, error: null, currentPage: 1, totalPages: 0, total: 0, perPage, filters: effectiveFilters,
      } : {
        dropdownNotifications: [], dropdownLoading: true, dropdownError: null, dropdownPage: 1, dropdownTotal: 0, dropdownPerPage: perPage,
      });
      try {
        const result = await loadNotifications(api, {
          page, perPage, filters: effectiveFilters, signal: request.controller.signal, expectedOwner: principal.owner,
        });
        if (!requestIsCurrent(scope, request, principal.key)) return false;
        if (result.notifications.length === 0 && result.total > 0 && result.page > 1) {
          clearRequestIfCurrent(scope, request);
          return get().fetchNotifications(1, effectiveFilters, { scope, perPage });
        }
        if (isPage) {
          set({
            notifications: result.notifications, loading: false, currentPage: result.page,
            totalPages: Math.min(MAX_PAGE, result.pages), total: result.total,
            perPage: result.per_page, filters: effectiveFilters,
          });
        } else {
          set({
            dropdownNotifications: result.notifications, dropdownLoading: false,
            dropdownPage: result.page, dropdownTotal: result.total, dropdownPerPage: result.per_page,
          });
        }
        return true;
      } catch (error) {
        if (!requestIsCurrent(scope, request, principal.key)) return false;
        if (isNotificationRequestCanceled(error)) {
          set(isPage ? { loading: false } : { dropdownLoading: false });
          return false;
        }
        const message = apiErrorMessage(error, 'Unable to load notifications');
        set(isPage ? {
          notifications: [], loading: false, error: message, currentPage: 1, totalPages: 0, total: 0,
        } : {
          dropdownNotifications: [], dropdownLoading: false, dropdownError: message, dropdownPage: 1, dropdownTotal: 0,
        });
        return false;
      } finally {
        clearRequestIfCurrent(scope, request);
      }
    },

    fetchUnreadCount: async () => {
      const principal = ensureContext();
      if (!principal) return false;
      const request = startRequest('count', principal.key);
      set({ countLoading: true, countError: null });
      try {
        const count = await loadUnreadNotificationCount(api, { signal: request.controller.signal, expectedOwner: principal.owner });
        if (!requestIsCurrent('count', request, principal.key)) return false;
        set({ unreadCount: count, countLoading: false });
        return true;
      } catch (error) {
        if (!requestIsCurrent('count', request, principal.key)) return false;
        if (isNotificationRequestCanceled(error)) {
          set({ countLoading: false });
          return false;
        }
        set({ unreadCount: null, countLoading: false, countError: apiErrorMessage(error, 'Unable to load unread notification count') });
        return false;
      } finally {
        clearRequestIfCurrent('count', request);
      }
    },

    markAsRead: (notificationId) => runMutation('mark-read', notificationId, async (mutation) => {
      const notification = await markNotificationRead(api, notificationId, {
        signal: mutation.controller.signal, expectedOwner: mutation.owner,
      });
      if (!isCurrentMutation(mutation)) return false;
      cancelReadScopesForMutation();
      set((state) => applyReadToLists(state, notification));
      // A counter failure is reported independently; it never rolls back an accepted read.
      await get().fetchUnreadCount();
      return true;
    }),

    markAllAsRead: () => runMutation('mark-all-read', null, async (mutation) => {
      await markAllNotificationsRead(api, { signal: mutation.controller.signal, expectedOwner: mutation.owner });
      if (!isCurrentMutation(mutation)) return false;
      cancelReadScopesForMutation();
      set((state) => ({
        notifications: state.filters.is_read === false
          ? [] : state.notifications.map((item) => ({ ...item, is_read: true })),
        total: state.filters.is_read === false ? 0 : state.total,
        totalPages: state.filters.is_read === false ? 0 : state.totalPages,
        currentPage: state.filters.is_read === false ? 1 : state.currentPage,
        dropdownNotifications: state.dropdownNotifications.map((item) => ({ ...item, is_read: true })),
      }));
      await get().fetchUnreadCount();
      return true;
    }),

    deleteNotification: (notificationId) => runMutation('delete', notificationId, async (mutation) => {
      const notification = await removeNotification(api, notificationId, {
        signal: mutation.controller.signal, expectedOwner: mutation.owner,
      });
      if (!isCurrentMutation(mutation)) return false;
      cancelReadScopesForMutation();
      set((state) => removeFromLists(state, notification.id));
      await get().fetchUnreadCount();
      return true;
    }),

    fetchPreferences: async () => {
      const principal = ensureContext();
      if (!principal) return false;
      const pending = activeMutation;
      if (pending) {
        await pending.promise;
        if (activeMutation || currentPrincipal()?.key !== principal.key) return false;
      }
      const request = startRequest('preferences', principal.key);
      set({ preferences: null, preferencesLoading: true, preferencesError: null });
      try {
        const preferences = await loadNotificationPreferences(api, {
          signal: request.controller.signal, expectedOwner: principal.owner,
        });
        if (!requestIsCurrent('preferences', request, principal.key)) return false;
        set({ preferences, preferencesLoading: false });
        return true;
      } catch (error) {
        if (!requestIsCurrent('preferences', request, principal.key)) return false;
        if (isNotificationRequestCanceled(error)) {
          set({ preferencesLoading: false });
          return false;
        }
        set({ preferences: null, preferencesLoading: false, preferencesError: apiErrorMessage(error, 'Unable to load notification preferences') });
        return false;
      } finally {
        clearRequestIfCurrent('preferences', request);
      }
    },

    updatePreferences: (preferences) => runMutation('save-preferences', null, async (mutation) => {
      const saved = await saveNotificationPreferences(api, preferences, {
        signal: mutation.controller.signal, expectedOwner: mutation.owner,
      });
      if (!isCurrentMutation(mutation)) return false;
      cancelReadScopesForMutation();
      set({ preferences: saved, preferencesError: null });
      return true;
    }, 'preferencesError'),
  };
});

export default useNotificationStore;
