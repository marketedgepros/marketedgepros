import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('release notice remains truthful before and after controlled account activation', () => {
  const source = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(source, /Limited release — live trading and payouts are disabled\. Account access and purchase availability are controlled separately by the service\./);
  assert.doesNotMatch(source, /registration and email delivery are disabled/);
  assert.match(source, /VITE_DEMO_RELEASE === 'true'/);
  assert.match(source, /aria-label="Demo release status"/);
});
