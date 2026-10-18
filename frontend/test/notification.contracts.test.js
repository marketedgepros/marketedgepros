import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const { default: api } = await import('../src/services/api.js');
const { default: useAuthStore } = await import('../src/store/authStore.js');
const { default: useNotificationStore } = await import('../src/stores/notificationStore.js');
const {
  DEFAULT_PER_PAGE,
  NOTIFICATIONS_ENDPOINT,
  buildNotificationQuery,
  createNotificationViewService,
  createDefaultNotificationPreferences,
  loadNotificationPreferences,
  loadNotifications,
  notificationDestination,
} = await import('../src/services/notificationViewService.js');

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');

const notification = (overrides = {}) => ({
  id: 7,
  user_id: 1,
  type: 'kyc',
  title: 'Documents received',
  message: 'Your documents are being reviewed.',
  data: null,
  priority: 'normal',
  is_read: false,
  read_at: null,
  created_at: '2026-10-11T12:00:00Z',
  ...overrides,
});

const page = (overrides = {}) => ({
  owner_context: { user_id: 1, tenant_id: 10 },
  notifications: [notification()],
  total: 1,
  page: 1,
  per_page: 20,
  pages: 1,
  ...overrides,
});

const preferences = (overrides = {}) => ({
  ...createDefaultNotificationPreferences(),
  owner_context: { user_id: 1, tenant_id: 10 },
  ...overrides,
  in_app: { ...createDefaultNotificationPreferences().in_app, ...overrides.in_app },
  email: { ...createDefaultNotificationPreferences().email, ...overrides.email },
  settings: { ...createDefaultNotificationPreferences().settings, ...overrides.settings },
});

const axiosResponse = (config, data, status = 200) => ({
  data,
  status,
  statusText: 'OK',
  headers: {},
  config,
  request: {},
});

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

const contextKey = 'number:1|number:10|role:trader';

const setActor = (id = 1, tenantId = 10, role = 'trader') => {
  useAuthStore.setState({
    user: { id, tenant_id: tenantId, role },
    isAuthenticated: true,
    isLoading: false,
  });
};

const clearActor = () => {
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
};

const withAdapter = async (adapter, callback) => {
  const previousAdapter = api.defaults.adapter;
  api.defaults.adapter = adapter;
  try {
    return await callback();
  } finally {
    api.defaults.adapter = previousAdapter;
    useNotificationStore.getState().reset();
    clearActor();
  }
};

test('notification page uses one canonical Axios request, bounds values, and never serializes null filters', async () => {
  const calls = [];
  await withAdapter(async (config) => {
    calls.push(config);
    return axiosResponse(config, page({
      page: 5,
      per_page: 100,
      notifications: [notification({ priority: 'high' })],
    }));
  }, async () => {
    const view = await loadNotifications(api, {
      page: 5,
      perPage: 500,
      filters: { type: 'kyc', is_read: false, priority: 'high', ignored: null },
    });
    assert.equal(view.page, 5);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, 'get');
    assert.equal(calls[0].url, NOTIFICATIONS_ENDPOINT);
    assert.deepEqual(calls[0].params, {
      page: 5,
      per_page: 100,
      type: 'kyc',
      is_read: 'false',
      priority: 'high',
    });
    assert.equal(JSON.stringify(calls[0].params).includes('null'), false);
    assert.equal(calls[0].baseURL, '/api/v1');
  });

  assert.deepEqual(buildNotificationQuery({ filters: { type: null, is_read: null, priority: undefined } }), {
    page: 1,
    per_page: DEFAULT_PER_PAGE,
  });
  assert.throws(() => buildNotificationQuery({ filters: { type: 'unknown' } }), /type filter/);
});

test('notification service rejects malformed list data and has an offline injectable facade', async () => {
  const fakeApi = {
    get: async () => ({ data: { ...page(), notifications: [{ id: 'bad' }] } }),
  };
  await assert.rejects(() => loadNotifications(fakeApi), /invalid notification/);

  const calls = [];
  const offline = createNotificationViewService({
    get: async (url, config) => {
      calls.push([url, config]);
      return { data: page({ notifications: [notification({ is_read: true, read_at: '2026-10-11T12:01:00Z' })] }) };
    },
  });
  await offline.loadNotifications({ filters: { is_read: true } });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], NOTIFICATIONS_ENDPOINT);
  assert.equal(calls[0][1].params.is_read, 'true');
});

test('GET defaults remain explicitly unpersisted until an explicit preference save', async () => {
  const calls = [];
  await withAdapter(async (config) => {
    calls.push(config);
    return axiosResponse(config, preferences());
  }, async () => {
    const loaded = await loadNotificationPreferences(api);
    assert.equal(loaded.id, null);
    assert.equal(loaded.persisted, false);
    assert.equal(loaded.email.system, false);
    assert.equal(loaded.in_app.withdrawal, true);
  });
  assert.deepEqual(calls.map((call) => call.method), ['get']);
});

test('store clears prior rows and surfaces a deferred list failure', async () => {
  setActor();
  const failure = deferred();
  await withAdapter((config) => {
    if (config.url === NOTIFICATIONS_ENDPOINT) return failure.promise;
    throw new Error(`Unexpected request ${config.url}`);
  }, async () => {
    useNotificationStore.setState({
      contextKey,
      notifications: [notification()],
      loading: false,
      error: null,
      currentPage: 1,
      totalPages: 1,
      total: 1,
    });
    const pending = useNotificationStore.getState().fetchNotifications(1, { is_read: false });
    assert.deepEqual(useNotificationStore.getState().notifications, []);
    failure.reject(new Error('network unavailable'));
    assert.equal(await pending, false);
    const state = useNotificationStore.getState();
    assert.deepEqual(state.notifications, []);
    assert.match(state.error, /network unavailable/);
  });
});

test('reset invalidates a late list response and a late mark-read mutation response', async () => {
  setActor();
  const listResponse = deferred();
  const markResponse = deferred();
  let countCalls = 0;
  await withAdapter((config) => {
    if (config.url === NOTIFICATIONS_ENDPOINT) return listResponse.promise;
    if (config.url === '/notifications/7/read') return markResponse.promise;
    if (config.url === '/notifications/unread-count') {
      countCalls += 1;
      return Promise.resolve(axiosResponse(config, { count: 0, owner_context: { user_id: 1, tenant_id: 10 } }));
    }
    throw new Error(`Unexpected request ${config.url}`);
  }, async () => {
    const pendingList = useNotificationStore.getState().fetchNotifications();
    useNotificationStore.getState().reset();
    listResponse.resolve(axiosResponse({ url: NOTIFICATIONS_ENDPOINT }, page()));
    assert.equal(await pendingList, false);
    assert.deepEqual(useNotificationStore.getState().notifications, []);

    // Re-establish the verified principal context, then invalidate it before the mutation returns.
    useNotificationStore.setState({ contextKey, notifications: [notification()], unreadCount: 1 });
    const pendingMark = useNotificationStore.getState().markAsRead(7);
    useNotificationStore.getState().reset();
    markResponse.resolve(axiosResponse({ url: '/notifications/7/read' }, {
      owner_context: { user_id: 1, tenant_id: 10 },
      notification: notification({ is_read: true, read_at: '2026-10-11T12:01:00Z' }),
    }));
    assert.equal(await pendingMark, false);
    assert.deepEqual(useNotificationStore.getState().notifications, []);
    assert.equal(useNotificationStore.getState().unreadCount, null);
    assert.equal(countCalls, 0, 'a stale mutation must not begin a count refresh');
  });
});

test('repeat mark-read shares one mutation flight and refreshes the authoritative count without double decrementing', async () => {
  setActor();
  let markCalls = 0;
  let countCalls = 0;
  const markResponse = deferred();
  await withAdapter((config) => {
    if (config.url === '/notifications/7/read') {
      markCalls += 1;
      return markResponse.promise;
    }
    if (config.url === '/notifications/unread-count') {
      countCalls += 1;
      return Promise.resolve(axiosResponse(config, { count: 0, owner_context: { user_id: 1, tenant_id: 10 } }));
    }
    throw new Error(`Unexpected request ${config.url}`);
  }, async () => {
    useNotificationStore.setState({
      contextKey,
      notifications: [notification()],
      dropdownNotifications: [notification()],
      unreadCount: 1,
      error: null,
    });
    const first = useNotificationStore.getState().markAsRead(7);
    const repeat = useNotificationStore.getState().markAsRead(7);
    assert.equal(first, repeat, 'same user/action/id must share the in-flight request');
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(markCalls, 1);
    markResponse.resolve(axiosResponse({ url: '/notifications/7/read' }, {
      owner_context: { user_id: 1, tenant_id: 10 },
      notification: notification({ is_read: true, read_at: '2026-10-11T12:01:00Z' }),
    }));
    assert.equal(await first, true);
    assert.equal(markCalls, 1);
    assert.equal(countCalls, 1);
    assert.equal(useNotificationStore.getState().unreadCount, 0);
    assert.equal(useNotificationStore.getState().notifications[0].is_read, true);

    // A later repeat reads the persisted value and still obtains the server count; it never
    // applies a local decrement based merely on a successful POST.
    const third = await useNotificationStore.getState().markAsRead(7);
    assert.equal(third, true);
    assert.equal(useNotificationStore.getState().unreadCount, 0);
    assert.equal(markCalls, 2);
    assert.equal(countCalls, 2);
  });
});

test('notification destinations enforce canonical role-safe navigation and sources contain no polling loop', () => {
  assert.equal(notificationDestination('withdrawal', 'trader'), '/trader/withdrawals');
  assert.equal(notificationDestination('withdrawal', 'affiliate'), '/notifications');
  assert.equal(notificationDestination('kyc', 'trader'), '/trader/documents');
  assert.equal(notificationDestination('kyc', 'master'), '/notifications');
  assert.equal(notificationDestination('challenge', 'trader'), '/challenges');
  assert.equal(notificationDestination('challenge', 'master'), '/notifications');
  assert.equal(notificationDestination('commission', 'affiliate'), '/affiliate/commissions');
  assert.equal(notificationDestination('commission', 'trader'), '/notifications');
  assert.equal(notificationDestination('payment', 'trader'), '/notifications');

  for (const relativePath of [
    'src/components/notifications/NotificationBell.jsx',
    'src/components/notifications/NotificationDropdown.jsx',
    'src/pages/Notifications.jsx',
    'src/stores/notificationStore.js',
  ]) {
    const source = fs.readFileSync(path.join(frontendDirectory, relativePath), 'utf8');
    assert.doesNotMatch(source, /setInterval\s*\(/, `${relativePath} must not poll`);
  }
  assert.doesNotMatch(
    fs.readFileSync(path.join(frontendDirectory, 'src/pages/Notifications.jsx'), 'utf8'),
    /Array\.from\(\{\s*length:\s*totalPages/, 
  );
});
