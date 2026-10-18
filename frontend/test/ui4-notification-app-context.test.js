import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';

test('App notification identity invalidation includes verified user, brand, and role', () => {
  const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  const identity = app.match(/const identity = \(state\) => JSON\.stringify\(\[([\s\S]*?)\]\);/);
  assert.ok(identity, 'the real App subscriber must define a principal identity');
  for (const field of ['state.isAuthenticated', 'state.user?.id', 'state.user?.tenant_id', 'state.user?.role']) {
    assert.ok(identity[1].includes(field), field);
  }
  assert.match(app, /identity\(state\) !== identity\(previous\).*useNotificationStore\.getState\(\)\.reset\(\)/);
});
