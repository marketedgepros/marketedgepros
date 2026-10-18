import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = fs.readFileSync(new URL('../src/pages/Contact.jsx', import.meta.url), 'utf8');

function getContactOptions() {
  return [...source.matchAll(/href: '(\/[^']+)'/g)].map((match) => match[1]);
}

test('contact page clearly states that messages are not submitted and has no form-success simulation', () => {
  assert.match(source, /Direct message submission is not available on this page/);
  assert.match(source, /No message or personal details are submitted here/);
  assert.doesNotMatch(source, /<form|<input|<textarea|handleSubmit|setTimeout|fetch\(|axios|Message sent successfully|We'll get back to you/);
});

test('contact page links only to declared public information destinations', () => {
  assert.deepEqual(getContactOptions(), ['/support', '/faq', '/programs']);
  assert.match(source, /Browse support/);
  assert.match(source, /Read the FAQ/);
  assert.match(source, /View programs/);
});

test('contact page retains semantic landmarks, visible focus treatment and restrained navy/cyan design', () => {
  assert.match(source, /<main className=/);
  assert.match(source, /aria-labelledby="contact-title"/);
  assert.match(source, /aria-labelledby="options-title"/);
  assert.match(source, /focus-visible:ring-2 focus-visible:ring-cyan-300/);
  assert.match(source, /mep-screen/);
  assert.match(source, /text-cyan-300/);
  assert.match(source, /motion-reduce:transition-none/);
});

test('unverified contact channels and fabricated availability language are not presented', () => {
  for (const unsupported of ['info@marketedgepros.com', '+1 (555) 123-4567', '123 Trading Lane', 'anytime', 'team']) {
    assert.ok(!source.toLowerCase().includes(unsupported.toLowerCase()), `unexpected unverified contact claim: ${unsupported}`);
  }
});
