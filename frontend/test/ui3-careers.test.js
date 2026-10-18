import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/pages/Careers.jsx', import.meta.url), 'utf8');

test('careers page keeps useful public content and only navigates to the supported contact page', () => {
  assert.match(source, /<h1[\s\S]*?Build thoughtful tools for traders\./);
  assert.match(source, /id="open-positions"/);
  assert.match(source, /Current openings and application details are not published on this page\./);
  assert.equal((source.match(/href="\/contact"/g) || []).length, 2);
  assert.doesNotMatch(source, /mailto:|onSubmit|setTimeout|setTimeout\s*\(/i);
});

test('careers page avoids unsupported recruiting promises, contact claims, and decorative claim lists', () => {
  for (const unsupported of [
    'Talented Team', 'Competitive Pay', 'Flexible Work', '200+ countries',
    'salary and benefits', 'work from anywhere', 'at the moment', 'always interested',
    'careers@marketedgepros.com', 'revolutionizing', 'Apply Now',
  ]) {
    assert.equal(source.toLowerCase().includes(unsupported.toLowerCase()), false, `unexpected claim: ${unsupported}`);
  }
  assert.match(source, /Current openings and application details are not published/);
});

test('careers layout retains navy/cyan styling and keyboard-visible link focus', () => {
  assert.match(source, /<Layout>/);
  assert.match(source, /mep-screen/);
  assert.match(source, /text-cyan-300/);
  assert.match(source, /focus-visible:ring-2 focus-visible:ring-cyan-300/);
  assert.match(source, /aria-labelledby="open-positions"/);
});
