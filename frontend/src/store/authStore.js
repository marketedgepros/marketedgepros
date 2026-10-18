import { create } from 'zustand';
import { authAPI } from '../services/api.js';

const INACTIVITY_TIMEOUT = 15 * 60 * 1000;
const TWO_FACTOR_CHALLENGE_TIMEOUT = 5 * 60 * 1000;
const ACTIVITY_EVENTS = ['mousedown', 'keydown', 'scroll', 'touchstart', 'click'];
const INVALID_AUTH_RESPONSE = 'Authentication response was invalid. Please sign in again.';
const STALE_AUTH_RESULT = Object.freeze({ stale: true });

// Auth requests can finish after the visitor has cancelled, logged out, or started over.
// Only the most recently begun auth operation is allowed to change session state or errors.
let authOperationGeneration = 0;

const beginAuthOperation = () => {
  authOperationGeneration += 1;
  return authOperationGeneration;
};

const isCurrentAuthOperation = (generation) => generation === authOperationGeneration;

export const isJsonObject = (value) => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
);

const isNonEmptyString = (value) => (
  typeof value === 'string' && value.trim().length > 0
);

const isValidUserId = (value) => (
  isNonEmptyString(value) || (typeof value === 'number' && Number.isFinite(value))
);

export const getAuthErrorMessage = (error, fallback) => {
  const data = error?.response?.data;
  if (isJsonObject(data)) {
    const message = data.error ?? data.message;
    if (isNonEmptyString(message)) {
      return message;
    }
  }

  return fallback;
};

export const isCompleteAuthSession = (data) => (
  isJsonObject(data)
  && isJsonObject(data.user)
  && isNonEmptyString(data.access_token)
  && isNonEmptyString(data.refresh_token)
  && isNonEmptyString(data.csrf_token)
);

const removeActivityListeners = (updateActivity) => {
  if (typeof document === 'undefined') return;
  ACTIVITY_EVENTS.forEach((event) => document.removeEventListener(event, updateActivity));
};

const addActivityListeners = (updateActivity) => {
  if (typeof document === 'undefined') return;
  ACTIVITY_EVENTS.forEach((event) => document.addEventListener(event, updateActivity));
};

const clearLegacySessionStorage = () => {
  localStorage.removeItem('user');
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('csrf_token');
};

const saveAuthenticatedSession = (data) => {
  if (!isCompleteAuthSession(data)) {
    throw new Error(INVALID_AUTH_RESPONSE);
  }

  // Legacy storage is retained for the current bearer-token compatibility path.
  // It must not be used as proof of an authenticated session (see init()).
  localStorage.setItem('user', JSON.stringify(data.user));
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  localStorage.setItem('csrf_token', data.csrf_token);
};

const savePendingCsrfToken = (data) => {
  localStorage.removeItem('csrf_token');
  if (isNonEmptyString(data.csrf_token)) {
    localStorage.setItem('csrf_token', data.csrf_token);
  }
};

const useAuthStore = create((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,
  lastActivity: Date.now(),
  inactivityTimer: null,
  pending2FA: null,
  twoFactorTimer: null,

  updateActivity: () => {
    const state = get();
    set({ lastActivity: Date.now() });

    if (state.inactivityTimer) {
      clearTimeout(state.inactivityTimer);
    }

    const timer = setTimeout(() => {
      const { isAuthenticated, logout } = get();
      if (isAuthenticated) {
        logout();
      }
    }, INACTIVITY_TIMEOUT);

    set({ inactivityTimer: timer });
  },

  clear2FAPending: (error = null) => {
    const state = get();
    if (state.twoFactorTimer) {
      clearTimeout(state.twoFactorTimer);
    }

    set({
      pending2FA: null,
      twoFactorTimer: null,
      ...(error ? { error } : {}),
    });
  },

  cancel2FA: () => {
    beginAuthOperation();
    get().clear2FAPending();
    set({ error: null });
  },

  start2FAPending: (userId, challengeToken) => {
    get().clear2FAPending();

    const timer = setTimeout(() => {
      const pending2FA = get().pending2FA;
      if (pending2FA?.challengeToken === challengeToken) {
        get().clear2FAPending('Your two-factor sign-in request expired. Please sign in again.');
      }
    }, TWO_FACTOR_CHALLENGE_TIMEOUT);

    set({
      pending2FA: { userId, challengeToken },
      twoFactorTimer: timer,
    });
  },

  clearAuthenticatedSession: () => {
    const state = get();
    if (state.inactivityTimer) {
      clearTimeout(state.inactivityTimer);
    }
    removeActivityListeners(state.updateActivity);
    clearLegacySessionStorage();
    set({
      user: null,
      isAuthenticated: false,
      inactivityTimer: null,
    });
  },

  activateAuthenticatedSession: (data) => {
    saveAuthenticatedSession(data);
    get().clear2FAPending();

    const state = get();
    if (state.inactivityTimer) {
      clearTimeout(state.inactivityTimer);
    }
    removeActivityListeners(state.updateActivity);
    set({
      user: data.user,
      isAuthenticated: true,
      isLoading: false,
      error: null,
      inactivityTimer: null,
    });
    get().updateActivity();
    addActivityListeners(get().updateActivity);
  },

  // A cached user profile is only a hint to make a request; it is never trusted as authentication.
  init: async () => {
    const generation = beginAuthOperation();
    set({ isLoading: true });
    const hasSessionHint = Boolean(
      localStorage.getItem('user')
      || localStorage.getItem('access_token')
      || localStorage.getItem('refresh_token')
    );

    if (!hasSessionHint) {
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      set({ user: null, isAuthenticated: false, isLoading: false });
      return;
    }

    try {
      const response = await authAPI.getCurrentUser();
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      const data = response?.data;
      if (!isJsonObject(data) || !isJsonObject(data.user)) {
        throw new Error(INVALID_AUTH_RESPONSE);
      }

      localStorage.setItem('user', JSON.stringify(data.user));
      const state = get();
      if (state.inactivityTimer) {
        clearTimeout(state.inactivityTimer);
      }
      removeActivityListeners(state.updateActivity);
      set({
        user: data.user,
        isAuthenticated: true,
        isLoading: false,
        error: null,
        inactivityTimer: null,
      });
      get().updateActivity();
      addActivityListeners(get().updateActivity);
    } catch (error) {
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      // Do not revive a session from localStorage when validation with the server fails.
      const state = get();
      if (state.inactivityTimer) {
        clearTimeout(state.inactivityTimer);
      }
      removeActivityListeners(state.updateActivity);
      set({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        inactivityTimer: null,
      });
    }
  },

  login: async (email, password) => {
    const generation = beginAuthOperation();
    get().clear2FAPending();
    set({ error: null, isLoading: false });

    try {
      const response = await authAPI.login({ email, password });
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      const data = response?.data;
      if (!isJsonObject(data)) {
        throw new Error(INVALID_AUTH_RESPONSE);
      }

      if (data.requires_2fa === true) {
        if (
          !isValidUserId(data.user_id)
          || !isNonEmptyString(data.challenge_token)
        ) {
          throw new Error(INVALID_AUTH_RESPONSE);
        }

        // A 2FA challenge is not an authenticated session. Remove any old bearer
        // credentials before retaining only the challenge in transient Zustand state.
        get().clearAuthenticatedSession();
        savePendingCsrfToken(data);
        get().start2FAPending(data.user_id, data.challenge_token);
        return {
          requires2FA: true,
          userId: data.user_id,
          challengeToken: data.challenge_token,
        };
      }

      get().activateAuthenticatedSession(data);
      return { success: true, user: data.user };
    } catch (error) {
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      get().clear2FAPending();
      const errorMessage = error.message === INVALID_AUTH_RESPONSE
        ? INVALID_AUTH_RESPONSE
        : getAuthErrorMessage(error, 'Login failed');
      set({ error: errorMessage });
      throw new Error(errorMessage);
    }
  },

  // Preserve the existing login2FA(userId, token) caller contract. The password-proof
  // challenge_token is supplied only from transient state and never from localStorage.
  login2FA: async (userId, token) => {
    const generation = beginAuthOperation();
    const pending2FA = get().pending2FA;
    if (!pending2FA || pending2FA.userId !== userId || !isNonEmptyString(pending2FA.challengeToken)) {
      const errorMessage = 'Your two-factor sign-in request has expired. Please sign in again.';
      get().clear2FAPending();
      set({ error: errorMessage });
      throw new Error(errorMessage);
    }

    try {
      set({ error: null });
      const response = await authAPI.login2FA({
        user_id: userId,
        token,
        challenge_token: pending2FA.challengeToken,
      });
      const data = response?.data;
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      get().activateAuthenticatedSession(data);
      return { success: true, user: data.user };
    } catch (error) {
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      get().clear2FAPending();
      const errorMessage = error.message === INVALID_AUTH_RESPONSE
        ? INVALID_AUTH_RESPONSE
        : getAuthErrorMessage(error, '2FA verification failed');
      set({ error: errorMessage });
      throw new Error(errorMessage);
    }
  },

  register: async (data) => {
    try {
      set({ error: null });
      const response = await authAPI.register(data);
      return response.data;
    } catch (error) {
      const errorMessage = getAuthErrorMessage(error, 'Registration failed');
      set({ error: errorMessage });
      throw new Error(errorMessage);
    }
  },

  logout: async () => {
    const generation = beginAuthOperation();
    try {
      await authAPI.logout();
    } catch (error) {
      // Local credentials are still cleared if the server is unavailable.
      if (isCurrentAuthOperation(generation)) {
        console.warn('[Auth] Logout request failed:', error.message);
      }
    } finally {
      if (!isCurrentAuthOperation(generation)) return STALE_AUTH_RESULT;
      get().clear2FAPending();
      get().clearAuthenticatedSession();
      set({ error: null, isLoading: false });
    }
  },

  updateUser: (userData) => {
    set({ user: userData });
  },

  clearError: () => {
    set({ error: null });
  },
}));

export default useAuthStore;
