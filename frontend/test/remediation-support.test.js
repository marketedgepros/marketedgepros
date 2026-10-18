import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { transformWithEsbuild } from 'vite';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const supportDirectory = path.join(frontendDirectory, 'src', 'pages', 'support');

const sourceFor = async (file) => readFile(path.join(supportDirectory, file), 'utf8');

async function assertJsxParses(file) {
  const source = await sourceFor(file);
  const result = await transformWithEsbuild(source, path.join(supportDirectory, file), {
    loader: 'jsx',
    jsx: 'automatic',
    sourcemap: false,
  });
  assert.ok(result.code.length > 0, `${file} transforms as JSX`);
  return source;
}

test('support remediation source parses as JSX without a build', async () => {
  await Promise.all([
    assertJsxParses('SupportHub.jsx'),
    assertJsxParses('Article.jsx'),
    assertJsxParses('TicketDetail.jsx'),
  ]);
});

test('SupportHub has an abortable explicit retry and distinguishes no-search from no-match', async () => {
  const source = await sourceFor('SupportHub.jsx');

  assert.match(source, /const loadArticles = useCallback\(async \(\) =>/);
  assert.match(source, /requestRef\.current\?\.abort\(\)/);
  assert.match(source, /api\.get\('\/support\/articles', \{ signal: controller\.signal \}\)/);
  assert.match(source, /requestSequenceRef\.current !== requestId \|\| controller\.signal\.aborted/);
  assert.match(source, /onClick=\{loadArticles\}/);
  assert.match(source, /No support articles are available right now\. Please check back later\./);
  assert.match(source, /No articles match “\{normalizedSearchTerm\}”\. Try another search\./);
  assert.match(source, /const hasSearchTerm = normalizedSearchTerm\.length > 0/);
});

test('Article fences every slug response, resets old view state, and offers an explicit retry and body empty state', async () => {
  const source = await sourceFor('Article.jsx');
  const firstArticleGuard = source.indexOf('if (!isCurrentRequest()) return;');
  const applyArticle = source.indexOf('setArticle(data);');
  const relatedGuard = source.indexOf('if (!isCurrentRequest()) return;', firstArticleGuard + 1);
  const applyRelated = source.indexOf('setRelatedArticles(candidates.filter');

  assert.match(source, /requestRef\.current\?\.abort\(\)/);
  assert.match(source, /requestSequenceRef\.current \+= 1/);
  assert.match(source, /api\.get\(`\/support\/articles\/\$\{encodeURIComponent\(slug \|\| ''\)\}`, \{ signal: controller\.signal \}\)/);
  assert.ok(firstArticleGuard !== -1 && firstArticleGuard < applyArticle, 'article state is applied only after its identity guard');
  assert.ok(relatedGuard !== -1 && relatedGuard < applyRelated, 'related state is applied only after its identity guard');
  assert.match(source, /setArticle\(null\);/);
  assert.match(source, /setContent\(''\);/);
  assert.match(source, /const currentError = error\?\.slug === slug \? error\.message : null/);
  assert.match(source, /const hasCurrentArticle = articleSlug === slug && article !== null/);
  assert.match(source, /const currentRelatedArticles = relatedArticlesSlug === slug \? relatedArticles : \[\]/);
  assert.match(source, /onClick=\{retryLoad\}/);
  assert.match(source, /This article does not have any content yet\./);
});

test('TicketDetail reports rating progress while retaining its one-write owner-guarded mutation path', async () => {
  const source = await sourceFor('TicketDetail.jsx');
  const ratingCalls = source.match(/rateMySupportTicket\(/g) || [];

  assert.match(source, /if \(!expectedOwner \|\| mutationInFlightRef\.current\) return;/);
  assert.match(source, /rateMySupportTicket\(ticket\.id, rating, undefined, \{ signal, expectedOwner \}\)/);
  assert.equal(ratingCalls.length, 1, 'the view issues a single explicit rating write; it has no automatic retry call');
  assert.match(source, /aria-busy=\{mutation === 'rating'\}/);
  assert.match(source, /role="status" aria-live="polite"[^>]*>Submitting your rating…<\/p>/);
  assert.match(source, /disabled=\{isMutating\}/);
});
