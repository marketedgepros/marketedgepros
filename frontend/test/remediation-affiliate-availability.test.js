import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const affiliateLandingPath = new URL('../src/pages/affiliate/AffiliateLanding.jsx', import.meta.url);
const appPath = new URL('../src/App.jsx', import.meta.url);
const [source, appSource] = await Promise.all([
  readFile(affiliateLandingPath, 'utf8'),
  readFile(appPath, 'utf8'),
]);

test('AffiliateLanding active route loads the owned component rather than a legacy counterpart', () => {
  assert.match(appSource, /const AffiliateLanding = lazy\(\(\) => import\('\.\/pages\/affiliate\/AffiliateLanding'\)\)/);
  assert.match(appSource, /path="\/affiliate" element=\{<AffiliateLanding \/>\}/);
});

test('AffiliateLanding offers an explicit availability retry only after availability cannot be confirmed', () => {
  assert.match(source, /const \[availabilityRequest, setAvailabilityRequest\] = useState\(0\)/);
  assert.match(source, /const retryAvailability = \(\) => \{[\s\S]*?programState !== 'error'[\s\S]*?setAvailabilityRequest\(\(request\) => request \+ 1\)/);
  assert.match(source, /programState === 'error' && \([\s\S]*?onClick=\{retryAvailability\}[\s\S]*?Retry availability check/);
  assert.match(source, /aria-describedby="affiliate-availability-status"/);
});

test('AffiliateLanding ignores stale availability responses after retry, identity change, or unmount', () => {
  assert.match(source, /const controller = new AbortController\(\)/);
  assert.match(source, /const requestId = availabilityRequestRef\.current \+ 1/);
  assert.match(source, /const requestIdentity = userIdentity/);
  assert.match(source, /!controller\.signal\.aborted/);
  assert.match(source, /identityRef\.current === requestIdentity/);
  assert.match(source, /availabilityRequestRef\.current === requestId/);
  assert.match(source, /return \(\) => \{ controller\.abort\(\); \};/);
  assert.match(source, /if \(!canPublishAvailability\(\)\) return;/);
});

test('availability retry remains fail-closed and does not create payout or policy claims', () => {
  assert.match(source, /programState === 'ready' && program\?\.isActive === true/);
  assert.match(source, /Program availability could not be confirmed\. Registration is unavailable\./);
  assert.match(source, /does not create a commission or confirm eligibility for a payout/);
  assert.doesNotMatch(source, /commissionRate|Minimum payout:|Cookie Duration/);
});
