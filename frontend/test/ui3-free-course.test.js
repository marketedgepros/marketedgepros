import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../src/pages/FreeCourse.jsx', import.meta.url), 'utf8');

test('free-course presents the topic outline and clearly limits availability claims', () => {
  assert.match(source, /Introductory trading topics/);
  assert.match(source, /Course access, delivery format and learning materials have not been confirmed/);
  assert.match(source, /Market fundamentals/);
  assert.match(source, /Technical analysis/);
  assert.match(source, /Risk and planning/);
});

test('free-course does not submit unsupported registration or claim email success', () => {
  assert.doesNotMatch(source, /api\.post|\/free-course\/register|<form\b|type="email"/);
  assert.doesNotMatch(source, /Get Instant Access|Check Your Email|We've sent you|Start Learning Now/);
  assert.doesNotMatch(source, /StructuredData|courseWorkload|Lifetime Access|Downloadable Resources|Video Lessons/);
});

test('free-course provides supported navigation with accessible focus treatment', () => {
  assert.match(source, /href="\/programs"/);
  assert.match(source, /href="\/contact"/);
  assert.match(source, /aria-label="Related information"/);
  assert.match(source, /focus-visible:outline/);
});
