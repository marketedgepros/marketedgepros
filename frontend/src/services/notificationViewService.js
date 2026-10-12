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
const isNullableTimestamp = (value) => {
  if (value === null) return true;
  if (!isText(value) || value.length > 64) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/.exec(value);
  if (!match || !Number.isFinite(Date.parse(value))) return false;
  const [year, month, day, hour, minute, second] = match.slice(1).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]
    && hour <= 23 && minute <= 59 && second <= 59;
};

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
    if (!NOTIFICATION_TYPES.includes(type)) throw new TypeError('Notification type filter is invalid');
    params.type = type;
  }
  if (priority !== null) {
    if (!NOTIFICATION_PRIORITIES.includes(priority)) throw new TypeError('Notification priority filter is invalid');
    params.priority = priority;
  }
  if (isRead !== null && isRead !== undefined && isRead !== '') {
    if (isRead === true || isRead === 'true') params.is_read = 'true';
    else if (isRead === false || isRead === 'false') params.is_read = 'false';
    else throw new TypeError('Notification read filter is invalid');
  }
  return params;
};

/** Validate an owner supplied by a trusted UI/store principal, never by an API response. */
export const normalizeExpectedNotificationOwner = (value) => {
  if (!isRecord(value)
    || !isSafePositiveInteger(value.user_id)
    || !(value.tenant_id === null || isSafePositiveInteger(value.tenant_id))) {
    throw new TypeError('Notification owner is invalid');
  }
  return { user_id: value.user_id, tenant_id: value.tenant_id };
};

const expectedOwnerOrNull = (expectedOwner) => (
  expectedOwner === undefined ? null : normalizeExpectedNotificationOwner(expectedOwner)
);

const verifyOwnerContext = (payload, expectedOwner) => {
  const owner = expectedOwnerOrNull(expectedOwner);
  if (!owner) return null;
  const responseOwner = payload?.owner_context;
  if (!isRecord(responseOwner)
    || responseOwner.user_id !== owner.user_id
    || responseOwner.tenant_id !== owner.tenant_id) {
    throw new TypeError('Notification response owner does not match the active account');
  }
  return owner;
};

export const normalizeNotification = (value, { expectedOwner } = {}) => {
  const owner = expectedOwnerOrNull(expectedOwner);
  if (!isRecord(value)
    || !isSafePositiveInteger(value.id)
    || !isSafePositiveInteger(value.user_id)
    || !isText(value.type)
    || !NOTIFICATION_TYPES.includes(value.type)
    || !isText(value.title)
    || !isText(value.message)
    || !NOTIFICATION_PRIORITIES.includes(value.priority)
    || typeof value.is_read !== 'boolean'
    || !isNullableTimestamp(value.read_at)
    || !isNullableTimestamp(value.created_at)
    || !hasOwn(value, 'data')) {
    throw new TypeError('Notification response has an invalid notification');
  }
  if (owner && value.user_id !== owner.user_id) {
    throw new TypeError('Notification response belongs to another account');
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

const matchesRequestedFilter = (notification, query) => (
  (!query.type || notification.type === query.type)
  && (!query.priority || notification.priority === query.priority)
  && (!hasOwn(query, 'is_read') || notification.is_read === (query.is_read === 'true'))
);

export const normalizeNotificationPage = (payload, { expectedOwner, query } = {}) => {
  const owner = verifyOwnerContext(payload, expectedOwner);
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
  if (query && (payload.page !== query.page || payload.per_page !== query.per_page)) {
    throw new TypeError('Notification list response does not match the request');
  }
  const notifications = payload.notifications.map((row) => normalizeNotification(row, { expectedOwner: owner || expectedOwner }));
  if (query && notifications.some((row) => !matchesRequestedFilter(row, query))) {
    throw new TypeError('Notification list response does not match the requested filters');
  }
  return {
    notifications,
    total: payload.total,
    page: payload.page,
    per_page: payload.per_page,
    pages: payload.pages,
  };
};

export const normalizeUnreadCount = (payload, { expectedOwner } = {}) => {
  verifyOwnerContext(payload, expectedOwner);
  if (!isRecord(payload) || !isSafeNonNegativeInteger(payload.count)) {
    throw new TypeError('Unread notification count response is unavailable');
  }
  return payload.count;
};

const normalizeCategories = (value, name) => {
  if (!isRecord(value)) throw new TypeError(`${name} notification preferences are unavailable`);
  return Object.fromEntries(NOTIFICATION_TYPES.map((type) => {
    if (typeof value[type] !== 'boolean') throw new TypeError(`${name} notification preference is invalid`);
    return [type, value[type]];
  }));
};

export const normalizeNotificationPreferences = (payload, { expectedOwner } = {}) => {
  verifyOwnerContext(payload, expectedOwner);
  if (!isRecord(payload)
    || !(payload.id === null || isSafePositiveInteger(payload.id))
    || typeof payload.persisted !== 'boolean'
    || !isRecord(payload.settings)
    || typeof payload.settings.email_enabled !== 'boolean'
    || !EMAIL_FREQUENCIES.includes(payload.settings.email_frequency)) {
    throw new TypeError('Notification preferences response is unavailable');
  }
  if ((payload.persisted && payload.id === null) || (!payload.persisted && payload.id !== null)) {
    throw new TypeError('Notification preference persistence state is inconsistent');
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

const samePreferencePayload = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const requestConfig = (signal, extra = {}) => ({ ...extra, ...(signal ? { signal } : {}) });
const mutationRequestConfig = (signal) => requestConfig(signal, { _skipAuthRefresh: true });

export const loadNotifications = async (
  apiClient = api,
  { page = 1, perPage = DEFAULT_PER_PAGE, filters = {}, signal, expectedOwner } = {},
) => {
  const query = buildNotificationQuery({ page, perPage, filters });
  const response = await apiClient.get(NOTIFICATIONS_ENDPOINT, requestConfig(signal, { params: query }));
  return normalizeNotificationPage(response?.data, { expectedOwner, query });
};

export const loadUnreadNotificationCount = async (apiClient = api, { signal, expectedOwner } = {}) => {
  const response = await apiClient.get(UNREAD_COUNT_ENDPOINT, requestConfig(signal));
  return normalizeUnreadCount(response?.data, { expectedOwner });
};

export const markNotificationRead = async (apiClient = api, notificationId, { signal, expectedOwner } = {}) => {
  if (!isSafePositiveInteger(notificationId)) throw new TypeError('Notification id is invalid');
  const response = await apiClient.post(`/notifications/${notificationId}/read`, undefined, mutationRequestConfig(signal));
  if (!isRecord(response?.data)) throw new TypeError('Mark read response is unavailable');
  verifyOwnerContext(response.data, expectedOwner);
  const notification = normalizeNotification(response.data.notification, { expectedOwner });
  if (notification.id !== notificationId || notification.is_read !== true) {
    throw new TypeError('Mark read response does not confirm the requested notification');
  }
  return notification;
};

export const markAllNotificationsRead = async (apiClient = api, { signal, expectedOwner } = {}) => {
  const response = await apiClient.post('/notifications/read-all', undefined, mutationRequestConfig(signal));
  if (!isRecord(response?.data)) throw new TypeError('Mark all read response is unavailable');
  verifyOwnerContext(response.data, expectedOwner);
  if (response.data.message !== 'Notifications marked as read' || !isSafeNonNegativeInteger(response.data.count)) {
    throw new TypeError('Mark all read response does not confirm changed rows');
  }
  return { count: response.data.count };
};

export const removeNotification = async (apiClient = api, notificationId, { signal, expectedOwner } = {}) => {
  if (!isSafePositiveInteger(notificationId)) throw new TypeError('Notification id is invalid');
  const response = await apiClient.delete(`/notifications/${notificationId}`, mutationRequestConfig(signal));
  if (!isRecord(response?.data)) throw new TypeError('Delete notification response is unavailable');
  verifyOwnerContext(response.data, expectedOwner);
  if (response.data.notification?.id !== notificationId || response.data.notification?.is_deleted !== true) {
    throw new TypeError('Delete response does not confirm the requested notification');
  }
  return normalizeNotification(response.data.notification, { expectedOwner });
};

export const loadNotificationPreferences = async (apiClient = api, { signal, expectedOwner } = {}) => {
  const response = await apiClient.get(NOTIFICATION_PREFERENCES_ENDPOINT, requestConfig(signal));
  return normalizeNotificationPreferences(response?.data, { expectedOwner });
};

export const saveNotificationPreferences = async (apiClient = api, preferences, { signal, expectedOwner } = {}) => {
  const submitted = notificationPreferencesPayload(preferences);
  const response = await apiClient.put(
    NOTIFICATION_PREFERENCES_ENDPOINT,
    submitted,
    mutationRequestConfig(signal),
  );
  if (!isRecord(response?.data)) throw new TypeError('Save notification preferences response is unavailable');
  verifyOwnerContext(response.data, expectedOwner);
  const saved = normalizeNotificationPreferences(response.data.preferences);
  if (!saved.persisted || saved.id === null || !samePreferencePayload(notificationPreferencesPayload(saved), submitted)) {
    throw new TypeError('Saved notification preferences do not match the submitted values');
  }
  return saved;
};

/** Return only destinations explicitly guarded for the actor role in App.jsx. */
export const notificationDestination = (notificationType, actorRole) => {
  switch (notificationType) {
    case 'withdrawal':
      return actorRole === 'trader' ? '/trader/withdrawals' : '/notifications';
    case 'kyc':
      return actorRole === 'trader' ? '/trader/documents' : '/notifications';
    case 'challenge':
      return actorRole === 'trader' ? '/challenges' : '/notifications';
    case 'commission':
      return actorRole === 'affiliate' ? '/affiliate/commissions' : '/notifications';
    case 'payment':
    case 'system':
    default:
      return '/notifications';
  }
};

/** Injectable facade for offline/unit callers. */
export const createNotificationViewService = (apiClient) => ({
  loadNotifications: (options) => loadNotifications(apiClient, options),
  loadUnreadCount: (options) => loadUnreadNotificationCount(apiClient, options),
  markRead: (notificationId, options) => markNotificationRead(apiClient, notificationId, options),
  markAllRead: (options) => markAllNotificationsRead(apiClient, options),
  remove: (notificationId, options) => removeNotification(apiClient, notificationId, options),
  loadPreferences: (options) => loadNotificationPreferences(apiClient, options),
  savePreferences: (preferences, options) => saveNotificationPreferences(apiClient, preferences, options),
});
