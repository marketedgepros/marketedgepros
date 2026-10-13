import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../src/pages/support/SupportHub.jsx', import.meta.url), 'utf8');

test('preserves articles API, published filter, article routes, ticket and FAQ navigation', () => {
  assert.match(source, /api\.get\('\/support\/articles', \{ signal: controller\.signal \}\)/);
  assert.match(source, /article\.status === 'published'/);
  assert.match(source, /`\/support\/\$\{article\.slug\}`/);
  assert.match(source, /link: '\/support\/create-ticket'/);
  assert.match(source, /link: '\/faq'/);
  assert.match(source, /<Layout>/);
  assert.match(source, /<SEO/);
});

test('separates API load error from empty search and removes unverified view/community claims', () => {
  assert.match(source, /const \[loadError, setLoadError\] = useState\(false\)/);
  assert.match(source, /setLoadError\(true\)/);
  assert.match(source, /Articles could not be loaded\. Please try again later\./);
  assert.match(source, /No articles match/);
  assert.doesNotMatch(source, /24\/7|Popular Articles|views\}|Join Discord Community|discord\.gg/);
});

test('search input has accessible name and visible keyboard focus treatment', () => {
  assert.match(source, /aria-label="Search help articles"/);
  assert.match(source, /focus:ring-2 focus:ring-cyan-500\/50 focus:border-cyan-400/);
});
