import api from './api.js';

export const NOTIFICATIONS_ENDPOINT = '/notifications/';
export const UNREAD_COUNT_ENDPOINT = '/notifications/unread-count';
export const NOTIFICATION_PREFERENCES_ENDPOINT = '/notifications/preferences';
export const NOTIFICATION_TYPES = Object.freeze([
  'withdrawal', 'commission', 'kyc', 'payment', 'challenge', 'system',
]);
export const NOTIFICATION_PRIORITIES = Object.freeze(['low', 'normal', 'high', 'urgent']);
export const EMAIL_FREQUENCIES = Object.freeze(['instant', 'daily', 'weekly']);
export const DEFAULT_PER_PAGE = 20;
export const MAX_PER_PAGE = 100;
export const MAX_PAGE = 1000;

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isSafeNonNegativeInteger = (value) => Number.isSafeInteger(value) && value >= 0;
const isSafePositiveInteger = (value) => Number.isSafeInteger(value) && value > 0;
const isText = (value) => typeof value === 'string';
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

const defaultCategories = (systemValue) => ({
  withdrawal: true,
  commission: true,
  kyc: true,
  payment: true,
  challenge: true,
  system: systemValue,
});

/** A new preference record is deliberately not persisted until an explicit PUT. */
export const createDefaultNotificationPreferences = () => ({
  id: null,
  persisted: false,
  in_app: defaultCategories(true),
  email: defaultCategories(false),
  settings: {
    email_enabled: true,
    email_frequency: 'instant',
  },
});

export const isNotificationRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError'
);

export const boundedNotificationPage = (value) => (
  Number.isSafeInteger(value) ? Math.min(MAX_PAGE, Math.max(1, value)) : 1
);

export const boundedNotificationPerPage = (value) => (
  Number.isSafeInteger(value) ? Math.min(MAX_PER_PAGE, Math.max(1, value)) : DEFAULT_PER_PAGE
);

const normalizeFilterText = (value) => (
  typeof value === 'string' && value.trim().length > 0 ? value.trim() : null
);

/**
 * Returns only supported query values. In particular, null/undefined values are
 * omitted rather than becoming the literal strings "null" or "undefined".
 */
export const buildNotificationQuery = ({ page = 1, perPage = DEFAULT_PER_PAGE, filters = {} } = {}) => {
  const params = {
    page: boundedNotificationPage(page),
    per_page: boundedNotificationPerPage(perPage),
  };
  const input = isRecord(filters) ? filters : {};
  const type = normalizeFilterText(input.type);
  const priority = normalizeFilterText(input.priority);
  const isRead = input.is_read;

  if (type !== null) {
    if (!NOTIFICATION_TYPES.includes(type)) {
      throw new TypeError('Notification type filter is invalid');
    }
    params.type = type;
  }
  if (priority !== null) {
    if (!NOTIFICATION_PRIORITIES.includes(priority)) {
      throw new TypeError('Notification priority filter is invalid');
    }
    params.priority = priority;
  }
  if (isRead !== null && isRead !== undefined && isRead !== '') {
    if (isRead === true || isRead === 'true') {
      params.is_read = 'true';
    } else if (isRead === false || isRead === 'false') {
      params.is_read = 'false';
    } else {
      throw new TypeError('Notification read filter is invalid');
    }
  }

  return params;
};

export const normalizeNotification = (value) => {
  if (!isRecord(value)
    || !isSafePositiveInteger(value.id)
    || !isSafePositiveInteger(value.user_id)
    || !isText(value.type)
    || !NOTIFICATION_TYPES.includes(value.type)
    || !isText(value.title)
    || !isText(value.message)
    || !NOTIFICATION_PRIORITIES.includes(value.priority)
    || typeof value.is_read !== 'boolean'
    || !(value.read_at === null || isText(value.read_at))
    || !(value.created_at === null || isText(value.created_at))
    || !hasOwn(value, 'data')) {
    throw new TypeError('Notification response has an invalid notification');
  }

  return {
    id: value.id,
    user_id: value.user_id,
    type: value.type,
    title: value.title,
    message: value.message,
    data: value.data,
    priority: value.priority,
    is_read: value.is_read,
    read_at: value.read_at,
    created_at: value.created_at,
  };
};

export const normalizeNotificationPage = (payload) => {
  if (!isRecord(payload)
    || !Array.isArray(payload.notifications)
    || !isSafeNonNegativeInteger(payload.total)
    || !isSafePositiveInteger(payload.page)
    || payload.page > MAX_PAGE
    || !isSafePositiveInteger(payload.per_page)
    || payload.per_page > MAX_PER_PAGE
    || !isSafeNonNegativeInteger(payload.pages)) {
    throw new TypeError('Notification list response is unavailable');
  }
  if (payload.notifications.length > payload.per_page
    || payload.notifications.length > payload.total
    || payload.pages !== Math.ceil(payload.total / payload.per_page)) {
    throw new TypeError('Notification list pagination is invalid');
  }

  return {
    notifications: payload.notifications.map(normalizeNotification),
    total: payload.total,
    page: payload.page,
    per_page: payload.per_page,
    pages: payload.pages,
  };
};

export const normalizeUnreadCount = (payload) => {
  if (!isRecord(payload) || !isSafeNonNegativeInteger(payload.count)) {
    throw new TypeError('Unread notification count response is unavailable');
  }
  return payload.count;
};

const normalizeCategories = (value, name) => {
  if (!isRecord(value)) {
    throw new TypeError(`${name} notification preferences are unavailable`);
  }

  return Object.fromEntries(NOTIFICATION_TYPES.map((type) => {
    if (typeof value[type] !== 'boolean') {
      throw new TypeError(`${name} notification preference is invalid`);
    }
    return [type, value[type]];
  }));
};

export const normalizeNotificationPreferences = (payload) => {
  if (!isRecord(payload)
    || !(payload.id === null || isSafePositiveInteger(payload.id))
    || typeof payload.persisted !== 'boolean'
    || !isRecord(payload.settings)
    || typeof payload.settings.email_enabled !== 'boolean'
    || !EMAIL_FREQUENCIES.includes(payload.settings.email_frequency)) {
    throw new TypeError('Notification preferences response is unavailable');
  }

  return {
    id: payload.id,
    persisted: payload.persisted,
    in_app: normalizeCategories(payload.in_app, 'In-app'),
    email: normalizeCategories(payload.email, 'Email'),
    settings: {
      email_enabled: payload.settings.email_enabled,
      email_frequency: payload.settings.email_frequency,
    },
  };
};

/** Validate and strip read-only preference metadata before an explicit save. */
export const notificationPreferencesPayload = (preferences) => {
  const normalized = normalizeNotificationPreferences(preferences);
  return {
    in_app: normalized.in_app,
    email: normalized.email,
    settings: normalized.settings,
  };
};

const requestConfig = (signal, extra = {}) => ({
  ...extra,
  ...(signal ? { signal } : {}),
});

export const loadNotifications = async (
  apiClient = api,
  { page = 1, perPage = DEFAULT_PER_PAGE, filters = {}, signal } = {},
) => {
  const response = await apiClient.get(
    NOTIFICATIONS_ENDPOINT,
    requestConfig(signal, { params: buildNotificationQuery({ page, perPage, filters }) }),
  );
  return normalizeNotificationPage(response?.data);
};

export const loadUnreadNotificationCount = async (apiClient = api, { signal } = {}) => {
  const response = await apiClient.get(UNREAD_COUNT_ENDPOINT, requestConfig(signal));
  return normalizeUnreadCount(response?.data);
};

export const markNotificationRead = async (apiClient = api, notificationId, { signal } = {}) => {
  if (!isSafePositiveInteger(notificationId)) {
    throw new TypeError('Notification id is invalid');
  }
  const response = await apiClient.post(
    `/notifications/${notificationId}/read`,
    undefined,
    requestConfig(signal),
  );
  if (!isRecord(response?.data)) {
    throw new TypeError('Mark read response is unavailable');
  }
  return normalizeNotification(response.data.notification);
};

export const markAllNotificationsRead = async (apiClient = api, { signal } = {}) => {
  const response = await apiClient.post('/notifications/read-all', undefined, requestConfig(signal));
  return normalizeUnreadCount(response?.data);
};

export const removeNotification = async (apiClient = api, notificationId, { signal } = {}) => {
  if (!isSafePositiveInteger(notificationId)) {
    throw new TypeError('Notification id is invalid');
  }
  const response = await apiClient.delete(`/notifications/${notificationId}`, requestConfig(signal));
  if (!isRecord(response?.data)) {
    throw new TypeError('Delete notification response is unavailable');
  }
  return normalizeNotification(response.data.notification);
};

export const loadNotificationPreferences = async (apiClient = api, { signal } = {}) => {
  const response = await apiClient.get(NOTIFICATION_PREFERENCES_ENDPOINT, requestConfig(signal));
  return normalizeNotificationPreferences(response?.data);
};

export const saveNotificationPreferences = async (apiClient = api, preferences, { signal } = {}) => {
  const response = await apiClient.put(
    NOTIFICATION_PREFERENCES_ENDPOINT,
    notificationPreferencesPayload(preferences),
    requestConfig(signal),
  );
  if (!isRecord(response?.data)) {
    throw new TypeError('Save notification preferences response is unavailable');
  }
  return normalizeNotificationPreferences(response.data.preferences);
};

/** Never send a user to a route outside their known role. */
export const notificationDestination = (notificationType, actorRole) => {
  switch (notificationType) {
    case 'withdrawal':
      return actorRole === 'trader' ? '/trader/withdrawals' : '/notifications';
    case 'kyc':
      return '/documents';
    case 'challenge':
      return actorRole === 'supermaster' || actorRole === 'master' ? '/notifications' : '/challenges';
    case 'commission':
      return actorRole === 'affiliate' || actorRole === 'agent'
        ? '/affiliate/commissions'
        : '/notifications';
    // There is no verified /orders route in the application, so payment notices stay here.
    case 'payment':
    case 'system':
    default:
      return '/notifications';
  }
};

/**
 * Injectable facade for offline/unit callers.  It does not configure a URL or
 * perform any browser work; callers may supply an Axios instance with a
 * synthetic adapter.
 */
export const createNotificationViewService = (apiClient) => ({
  loadNotifications: (options) => loadNotifications(apiClient, options),
  loadUnreadCount: (options) => loadUnreadNotificationCount(apiClient, options),
  markRead: (notificationId, options) => markNotificationRead(apiClient, notificationId, options),
  markAllRead: (options) => markAllNotificationsRead(apiClient, options),
  remove: (notificationId, options) => removeNotification(apiClient, notificationId, options),
  loadPreferences: (options) => loadNotificationPreferences(apiClient, options),
  savePreferences: (preferences, options) => saveNotificationPreferences(apiClient, preferences, options),
});
