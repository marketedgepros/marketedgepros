import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { transformWithEsbuild } from 'vite';

const blogFile = new URL('../src/pages/Blog.jsx', import.meta.url);
const postFile = new URL('../src/pages/BlogPost.jsx', import.meta.url);
const blogSource = fs.readFileSync(blogFile, 'utf8');
const postSource = fs.readFileSync(postFile, 'utf8');

test('Blog cancels and versions page/category requests while keeping retry bound to the failed view', () => {
  assert.match(blogSource, /const postsRequestRef = useRef\(\{ controller: null, version: 0 \}\)/);
  assert.match(blogSource, /previousRequest\.controller\?\.abort\(\)/);
  assert.match(blogSource, /const controller = new AbortController\(\)/);
  assert.match(blogSource, /api\.get\('\/blog\/posts', \{ params, signal: controller\.signal \}\)/);
  assert.match(blogSource, /postsRequestRef\.current\.version === version[\s\S]*postsRequestRef\.current\.controller === controller/);
  assert.match(blogSource, /if \(controller\.signal\.aborted \|\| !isCurrentRequest\(\)\) return/);
  assert.match(blogSource, /if \(isCurrentRequest\(\)\) setLoading\(false\)/);
  assert.match(blogSource, /setRequestedPage\(1\)[\s\S]*fetchPosts\(1, category\)/);
  assert.match(blogSource, /setRequestedPage\(page\)[\s\S]*fetchPosts\(page, selectedCategory\)/);
  assert.match(blogSource, /fetchPosts\(requestedPage, selectedCategory\)/);
});

test('Blog labels search as current-page only and never claims a global no-match result', () => {
  assert.match(blogSource, /Search posts on this page/);
  assert.match(blogSource, /aria-describedby="blog-search-scope"/);
  assert.match(blogSource, /Search is limited to posts loaded on the current page\./);
  assert.match(blogSource, /No posts match your search on the currently loaded page\./);
  assert.doesNotMatch(blogSource, /Search all blog posts|No posts anywhere|global search/i);
});

test('BlogPost rejects stale slug and related-post responses and exposes retry for the same slug', () => {
  assert.match(postSource, /const postRequestRef = useRef\(\{ controller: null, version: 0 \}\)/);
  assert.match(postSource, /previousRequest\.controller\?\.abort\(\)/);
  assert.match(postSource, /api\.get\(`\/blog\/posts\/\$\{requestedSlug\}`, \{ signal: controller\.signal \}\)/);
  assert.match(postSource, /api\.get\('\/blog\/posts', \{[\s\S]*signal: controller\.signal/);
  assert.match(postSource, /postRequestRef\.current\.version === version[\s\S]*postRequestRef\.current\.controller === controller/);
  assert.match(postSource, /if \(!isCurrentRequest\(\)\) return/);
  assert.match(postSource, /if \(controller\.signal\.aborted \|\| !isCurrentRequest\(\)\) return/);
  assert.match(postSource, /activeRequest\.version \+= 1[\s\S]*activeRequest\.controller\?\.abort\(\)/);
  assert.match(postSource, /onClick=\{\(\) => fetchPost\(slug\)\}/);
});

test('BlogPost share windows are opener-safe and provide accessible blocked-popup feedback', () => {
  assert.match(postSource, /window\.open\(shareUrl, '_blank', 'noopener,noreferrer,width=600,height=400'\)/);
  assert.match(postSource, /if \(!popup\) \{[\s\S]*blocked the sharing window/);
  assert.match(postSource, /popup\.opener = null/);
  assert.match(postSource, /role="status" aria-live="polite"/);
  assert.match(postSource, /aria-label="Share on Facebook"/);
  assert.match(postSource, /aria-label="Share on X\/Twitter"/);
  assert.match(postSource, /aria-label="Share on LinkedIn"/);
});

test('the edited Blog components remain JSX-transformable', async () => {
  for (const file of [blogFile, postFile]) {
    const source = fs.readFileSync(file, 'utf8');
    const result = await transformWithEsbuild(source, file.pathname, { loader: 'jsx', jsx: 'automatic' });
    assert.match(result.code, /export default/);
  }
});
