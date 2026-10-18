import assert from 'node:assert/strict';
import test from 'node:test';

const { default: api } = await import('../src/services/api.js');
const { default: useAuthStore } = await import('../src/store/authStore.js');
const { default: useNotificationStore } = await import('../src/stores/notificationStore.js');
const {
  createDefaultNotificationPreferences,
  loadNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  saveNotificationPreferences,
} = await import('../src/services/notificationViewService.js');

const owner = { user_id: 1, tenant_id: 10 };
const otherOwner = { user_id: 2, tenant_id: 10 };
const notification = (overrides = {}) => ({
  id: 7,
  user_id: 1,
  type: 'system',
  title: 'Recorded update',
  message: 'An in-app event was recorded.',
  data: null,
  priority: 'normal',
  is_read: false,
  read_at: null,
  created_at: '2026-10-11T12:00:00Z',
  ...overrides,
});
const page = (overrides = {}) => ({
  owner_context: owner,
  notifications: [notification()],
  total: 1,
  page: 1,
  per_page: 20,
  pages: 1,
  ...overrides,
});
const axiosResponse = (config, data) => ({
  data, status: 200, statusText: 'OK', headers: {}, config, request: {},
});
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
};
const setActor = (role = 'trader') => useAuthStore.setState({
  user: { id: 1, tenant_id: 10, role }, isAuthenticated: true, isLoading: false,
});
const reset = () => {
  useNotificationStore.getState().reset();
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
};
const withAdapter = async (adapter, callback) => {
  const previous = api.defaults.adapter;
  api.defaults.adapter = adapter;
  try { return await callback(); } finally { api.defaults.adapter = previous; reset(); }
};

test('notification list rejects a spoofed owner_context and a row owned by another user', async () => {
  await assert.rejects(
    () => loadNotifications({ get: async () => ({ data: page({ owner_context: otherOwner }) }) }, { expectedOwner: owner }),
    /owner does not match/,
  );
  await assert.rejects(
    () => loadNotifications({ get: async () => ({ data: page({ notifications: [notification({ user_id: 2 })] }) }) }, { expectedOwner: owner }),
    /another account/,
  );
});

test('real Axios mutation rejects a forged action id and suppresses automatic 401 refresh retries', async () => {
  let calls = 0;
  await withAdapter(async (config) => {
    calls += 1;
    assert.equal(config._skipAuthRefresh, true);
    return axiosResponse(config, {
      owner_context: owner,
      notification: notification({ id: 8, is_read: true, read_at: '2026-10-11T12:01:00Z' }),
    });
  }, async () => {
    await assert.rejects(() => markNotificationRead(api, 7, { expectedOwner: owner }), /requested notification/);
    assert.equal(calls, 1);
  });
});

test('read-all requires its canonical message and changed-row count, never an unread-count lookalike', async () => {
  await assert.rejects(
    () => markAllNotificationsRead({ post: async () => ({ data: { owner_context: owner, message: 'All read', count: 3 } }) }, { expectedOwner: owner }),
    /changed rows/,
  );
  await assert.rejects(
    () => markAllNotificationsRead({ post: async () => ({ data: { owner_context: owner, message: 'Notifications marked as read', count: -1 } }) }, { expectedOwner: owner }),
    /changed rows/,
  );
});

test('preference save rejects persisted/id inconsistency and canonical payload mismatch', async () => {
  const draft = createDefaultNotificationPreferences();
  await assert.rejects(
    () => saveNotificationPreferences({ put: async () => ({ data: { owner_context: owner, preferences: { ...draft, id: null, persisted: true } } }) }, draft, { expectedOwner: owner }),
    /persistence state is inconsistent/,
  );
  await assert.rejects(
    () => saveNotificationPreferences({ put: async () => ({ data: {
      owner_context: owner,
      preferences: { ...draft, id: 9, persisted: true, email: { ...draft.email, payment: false } },
    } }) }, draft, { expectedOwner: owner }),
    /do not match/,
  );
});

test('a mutation aborts stale page reads and a role change prevents a late mutation from becoming success', async () => {
  setActor('trader');
  const staleList = deferred();
  const lateRead = deferred();
  let countCalls = 0;
  await withAdapter((config) => {
    if (config.url === '/notifications/') return staleList.promise;
    if (config.url === '/notifications/7/read') return lateRead.promise;
    if (config.url === '/notifications/unread-count') {
      countCalls += 1;
      return Promise.resolve(axiosResponse(config, { owner_context: owner, count: 0 }));
    }
    throw new Error(`Unexpected request ${config.url}`);
  }, async () => {
    const pendingList = useNotificationStore.getState().fetchNotifications();
    const pendingRead = useNotificationStore.getState().markAsRead(7);
    staleList.resolve(axiosResponse({ url: '/notifications/' }, page()));
    assert.equal(await pendingList, false, 'the read response cannot overwrite a later mutation scope');

    setActor('affiliate');
    lateRead.resolve(axiosResponse({ url: '/notifications/7/read' }, {
      owner_context: owner,
      notification: notification({ is_read: true, read_at: '2026-10-11T12:01:00Z' }),
    }));
    assert.equal(await pendingRead, false, 'a role switch invalidates a late action result');
    assert.equal(countCalls, 0, 'no stale action may begin a counter refresh');
    assert.equal(useNotificationStore.getState().pendingAction, null);
  });
});

test('a GET requested during a pending write is issued once only after its acknowledgement', async () => {
  setActor();
  const saved = deferred();
  let reads = 0;
  let putConfig;
  const draft = createDefaultNotificationPreferences();
  const receipt = { ...draft, id: 3, persisted: true };
  await withAdapter((config) => {
    if (config.method === 'put') { putConfig = config; return saved.promise; }
    if (config.url === '/notifications/preferences') {
      reads += 1;
      return Promise.resolve(axiosResponse(config, { ...receipt, owner_context: owner }));
    }
    throw new Error(`Unexpected request ${config.url}`);
  }, async () => {
    const write = useNotificationStore.getState().updatePreferences(draft);
    const read = useNotificationStore.getState().fetchPreferences();
    await Promise.resolve();
    assert.equal(reads, 0, 'do not capture an old server snapshot during the pending write');
    saved.resolve(axiosResponse(putConfig, { owner_context: owner, preferences: receipt }));
    assert.equal(await write, true);
    assert.equal(await read, true);
    assert.equal(reads, 1, 'the deferred read is bounded to one post-ack request');
    assert.equal(useNotificationStore.getState().preferences.id, 3);
    assert.equal(useNotificationStore.getState().pendingAction, null);
  });
});

test('both page and dropdown loaders reject malformed timestamps before relative-time rendering', async () => {
  for (const field of ['created_at', 'read_at']) {
    await assert.rejects(() => loadNotifications({ get: async () => ({ data: page({
      notifications: [notification({ [field]: 'not-a-date' })],
    }) }) }, { expectedOwner: owner }), /invalid notification/);
  }
  for (const scope of ['page', 'dropdown']) {
    setActor();
    await withAdapter(async (config) => axiosResponse(config, page({
      per_page: scope === 'dropdown' ? 10 : 20,
      notifications: [notification({ created_at: 'not-a-date' })],
    })), async () => {
      assert.equal(await useNotificationStore.getState().fetchNotifications(1, {}, { scope }), false);
      const state = useNotificationStore.getState();
      assert.equal((scope === 'dropdown' ? state.dropdownNotifications : state.notifications).length, 0);
      assert.ok(scope === 'dropdown' ? state.dropdownError : state.error);
    });
  }
});

test('notification timestamps reject calendar overflow without inventing normalized dates', async () => {
  for (const field of ['created_at', 'read_at']) {
    for (const value of ['2026-02-29T12:00:00Z', '2026-04-31T12:00:00Z', '2026-10-11T24:00:00Z']) {
      await assert.rejects(() => loadNotifications({ get: async () => ({ data: page({
        notifications: [notification({ [field]: value })],
      }) }) }, { expectedOwner: owner }), /invalid notification/);
    }
  }
  const view = await loadNotifications({ get: async () => ({ data: page({
    notifications: [notification({ created_at: '2024-02-29T12:00:00Z' })],
  }) }) }, { expectedOwner: owner });
  assert.equal(view.notifications[0].created_at, '2024-02-29T12:00:00Z');
});
