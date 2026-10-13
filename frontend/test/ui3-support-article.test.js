import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/pages/support/Article.jsx', import.meta.url), 'utf8');

test('support article keeps the public article, sanitization and related-article navigation flow', () => {
  assert.match(source, /api\.get\(`\/support\/articles\/\$\{encodeURIComponent\(slug \|\| ''\)\}`, \{ signal: controller\.signal \}\)/);
  assert.match(source, /api\.get\('\/support\/articles'/);
  assert.match(source, /DOMPurify\.sanitize\(htmlContent\)/);
  assert.match(source, /ReactMarkdown/);
  assert.match(source, /to=\{`\/support\/\$\{related\.slug\}`\}/);
  assert.match(source, /to="\/support"/);
});

test('load failure copy does not assert a missing article or unsupported round-the-clock support', () => {
  assert.match(source, /Unable to Load Article/);
  assert.match(source, /We couldn't load this article\. Please try again or browse the Support Hub\./);
  assert.doesNotMatch(source, /Article Not Found|doesn't exist|24\/7/);
});

test('support CTA describes its actual destination and offers a non-promissory statement', () => {
  assert.match(source, /Contact us and we'll do our best to help\./);
  assert.match(source, /href="mailto:info@marketedgepros\.com"/);
  assert.match(source, /to="\/support"[\s\S]*?Browse Support Articles/);
  assert.doesNotMatch(source, /Browse FAQ/);
});

test('loading and error states expose assistive-technology status', () => {
  assert.match(source, /role="status" aria-live="polite"/);
  assert.match(source, /role="alert"/);
});
