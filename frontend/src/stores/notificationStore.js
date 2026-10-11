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
const mutationFlights = new Map();

const initialFilters = () => ({ type: null, is_read: null, priority: null });

const initialState = (contextKey = null) => ({
  contextKey,
  notifications: [],
  dropdownNotifications: [],
  unreadCount: 0,
  preferences: null,
  loading: false,
  dropdownLoading: false,
  preferencesLoading: false,
  countLoading: false,
  error: null,
  dropdownError: null,
  preferencesError: null,
  countError: null,
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

const userContextKey = () => {
  const auth = useAuthStore.getState();
  const user = auth?.user;
  const userId = user?.id;
  if (!auth?.isAuthenticated || !(typeof userId === 'string' || Number.isSafeInteger(userId))) {
    return null;
  }
  const tenantId = user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id ?? null;
  const normalizedTenant = typeof tenantId === 'string' || Number.isSafeInteger(tenantId) ? tenantId : null;
  return `${typeof userId}:${userId}|${typeof normalizedTenant}:${normalizedTenant}`;
};

const cancelActiveRequests = () => {
  activeRequests.forEach((request) => request.controller.abort());
  activeRequests.clear();
};

const requestIsCurrent = (scope, identity, contextKey, generation) => {
  const active = activeRequests.get(scope);
  return active?.identity === identity
    && active?.contextKey === contextKey
    && generation === requestGeneration
    && contextKey === userContextKey();
};

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
  if (activeRequests.get(scope)?.identity === request.identity) {
    activeRequests.delete(scope);
  }
};

const isCurrentMutation = (contextKey, generation) => (
  generation === requestGeneration && contextKey === userContextKey()
);

const replaceInLists = (state, notification) => ({
  notifications: state.notifications.map((item) => (item.id === notification.id ? notification : item)),
  dropdownNotifications: state.dropdownNotifications.map((item) => (
    item.id === notification.id ? notification : item
  )),
});

const removeFromLists = (state, notificationId) => ({
  notifications: state.notifications.filter((item) => item.id !== notificationId),
  dropdownNotifications: state.dropdownNotifications.filter((item) => item.id !== notificationId),
  total: Math.max(0, state.total - (state.notifications.some((item) => item.id === notificationId) ? 1 : 0)),
  dropdownTotal: Math.max(
    0,
    state.dropdownTotal - (state.dropdownNotifications.some((item) => item.id === notificationId) ? 1 : 0),
  ),
});

const useNotificationStore = create((set, get) => {
  const resetForContext = (contextKey = null) => {
    requestGeneration += 1;
    cancelActiveRequests();
    mutationFlights.clear();
    set(initialState(contextKey));
  };

  const ensureContext = () => {
    const contextKey = userContextKey();
    if (!contextKey) {
      if (get().contextKey !== null) resetForContext(null);
      return null;
    }
    if (get().contextKey !== contextKey) resetForContext(contextKey);
    return contextKey;
  };

  const runMutation = (name, id, operation, errorField = 'error') => {
    const contextKey = ensureContext();
    if (!contextKey) return Promise.resolve(false);
    const generation = requestGeneration;
    const key = `${generation}:${contextKey}:${name}:${id ?? ''}`;
    const existing = mutationFlights.get(key);
    if (existing) return existing;

    const flight = (async () => {
      try {
        return await operation({ contextKey, generation });
      } catch (error) {
        if (isCurrentMutation(contextKey, generation)) {
          set({ [errorField]: apiErrorMessage(error, 'Notification action failed') });
        }
        return false;
      } finally {
        // A reset/new context must never allow an old completion to remove a new gate.
        if (mutationFlights.get(key) === flight) mutationFlights.delete(key);
      }
    })();
    mutationFlights.set(key, flight);
    return flight;
  };

  return {
    ...initialState(),

    /** The App auth lifecycle calls this synchronously on any user/tenant change. */
    reset: () => resetForContext(null),

    fetchNotifications: async (page = 1, filters = {}, options = {}) => {
      const contextKey = ensureContext();
      if (!contextKey) return false;
      const scope = options.scope === 'dropdown' ? 'dropdown' : 'page';
      const perPage = boundedNotificationPerPage(
        options.perPage ?? filters?.per_page ?? (scope === 'dropdown' ? 10 : get().perPage),
      );
      const effectiveFilters = {
        type: filters?.type ?? null,
        is_read: filters?.is_read ?? null,
        priority: filters?.priority ?? null,
      };
      const request = startRequest(scope, contextKey);
      const isPage = scope === 'page';

      set(isPage ? {
        notifications: [],
        loading: true,
        error: null,
        currentPage: 1,
        totalPages: 0,
        total: 0,
        perPage,
        filters: effectiveFilters,
      } : {
        dropdownNotifications: [],
        dropdownLoading: true,
        dropdownError: null,
        dropdownPage: 1,
        dropdownTotal: 0,
        dropdownPerPage: perPage,
      });

      try {
        const result = await loadNotifications(api, {
          page,
          perPage,
          filters: effectiveFilters,
          signal: request.controller.signal,
        });
        if (!requestIsCurrent(scope, request.identity, contextKey, request.generation)) return false;

        // A row can disappear after the user reached its old last page. Recover once to
        // page one rather than rendering a confusing dead page; no unbounded page list.
        if (result.notifications.length === 0 && result.total > 0 && result.page > 1) {
          clearRequestIfCurrent(scope, request);
          return get().fetchNotifications(1, effectiveFilters, { scope, perPage });
        }

        if (isPage) {
          set({
            notifications: result.notifications,
            loading: false,
            currentPage: result.page,
            totalPages: Math.min(MAX_PAGE, result.pages),
            total: result.total,
            perPage: result.per_page,
            filters: effectiveFilters,
          });
        } else {
          set({
            dropdownNotifications: result.notifications,
            dropdownLoading: false,
            dropdownPage: result.page,
            dropdownTotal: result.total,
            dropdownPerPage: result.per_page,
          });
        }
        return true;
      } catch (error) {
        if (!requestIsCurrent(scope, request.identity, contextKey, request.generation)) return false;
        if (isNotificationRequestCanceled(error)) {
          set(isPage ? { loading: false } : { dropdownLoading: false });
          return false;
        }
        const message = apiErrorMessage(error, 'Unable to load notifications');
        set(isPage ? {
          notifications: [],
          loading: false,
          error: message,
          currentPage: 1,
          totalPages: 0,
          total: 0,
        } : {
          dropdownNotifications: [],
          dropdownLoading: false,
          dropdownError: message,
          dropdownPage: 1,
          dropdownTotal: 0,
        });
        return false;
      } finally {
        clearRequestIfCurrent(scope, request);
      }
    },

    fetchUnreadCount: async () => {
      const contextKey = ensureContext();
      if (!contextKey) return false;
      const request = startRequest('count', contextKey);
      set({ unreadCount: 0, countLoading: true, countError: null });
      try {
        const count = await loadUnreadNotificationCount(api, { signal: request.controller.signal });
        if (!requestIsCurrent('count', request.identity, contextKey, request.generation)) return false;
        set({ unreadCount: count, countLoading: false });
        return true;
      } catch (error) {
        if (!requestIsCurrent('count', request.identity, contextKey, request.generation)) return false;
        if (isNotificationRequestCanceled(error)) {
          set({ countLoading: false });
          return false;
        }
        set({
          unreadCount: 0,
          countLoading: false,
          countError: apiErrorMessage(error, 'Unable to load unread notification count'),
        });
        return false;
      } finally {
        clearRequestIfCurrent('count', request);
      }
    },

    markAsRead: (notificationId) => runMutation('mark-read', notificationId, async ({ contextKey, generation }) => {
      set({ error: null });
      const notification = await markNotificationRead(api, notificationId);
      // The server's persisted entity, not a local optimistic assumption, controls the DOM.
      if (!notification.is_read) {
        throw new Error('Notification was not marked as read');
      }
      if (!isCurrentMutation(contextKey, generation)) return false;
      set((state) => replaceInLists(state, notification));
      // Count is authoritative and a repeat read cannot decrement it twice.
      await get().fetchUnreadCount();
      return isCurrentMutation(contextKey, generation);
    }),

    markAllAsRead: () => runMutation('mark-all-read', null, async ({ contextKey, generation }) => {
      set({ error: null });
      await markAllNotificationsRead(api);
      if (!isCurrentMutation(contextKey, generation)) return false;
      set((state) => ({
        notifications: state.notifications.map((item) => ({ ...item, is_read: true })),
        dropdownNotifications: state.dropdownNotifications.map((item) => ({ ...item, is_read: true })),
      }));
      await get().fetchUnreadCount();
      return isCurrentMutation(contextKey, generation);
    }),

    deleteNotification: (notificationId) => runMutation('delete', notificationId, async ({ contextKey, generation }) => {
      set({ error: null });
      const notification = await removeNotification(api, notificationId);
      if (!isCurrentMutation(contextKey, generation)) return false;
      set((state) => removeFromLists(state, notification.id));
      await get().fetchUnreadCount();
      return isCurrentMutation(contextKey, generation);
    }),

    fetchPreferences: async () => {
      const contextKey = ensureContext();
      if (!contextKey) return false;
      const request = startRequest('preferences', contextKey);
      set({ preferences: null, preferencesLoading: true, preferencesError: null });
      try {
        const preferences = await loadNotificationPreferences(api, { signal: request.controller.signal });
        if (!requestIsCurrent('preferences', request.identity, contextKey, request.generation)) return false;
        set({ preferences, preferencesLoading: false });
        return true;
      } catch (error) {
        if (!requestIsCurrent('preferences', request.identity, contextKey, request.generation)) return false;
        if (isNotificationRequestCanceled(error)) {
          set({ preferencesLoading: false });
          return false;
        }
        set({
          preferences: null,
          preferencesLoading: false,
          preferencesError: apiErrorMessage(error, 'Unable to load notification preferences'),
        });
        return false;
      } finally {
        clearRequestIfCurrent('preferences', request);
      }
    },

    updatePreferences: (preferences) => runMutation('save-preferences', null, async ({ contextKey, generation }) => {
      set({ preferencesError: null });
      const saved = await saveNotificationPreferences(api, preferences);
      if (!saved.persisted) throw new Error('Notification preferences were not persisted');
      if (!isCurrentMutation(contextKey, generation)) return false;
      set({ preferences: saved, preferencesError: null });
      return true;
    }, 'preferencesError'),
  };
});

export default useNotificationStore;
