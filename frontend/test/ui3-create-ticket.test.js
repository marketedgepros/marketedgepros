import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const page = fs.readFileSync(new URL('../src/pages/support/CreateTicket.jsx', import.meta.url), 'utf8');
const service = fs.readFileSync(new URL('../src/services/supportTicketViewService.js', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');

test('create-ticket copy explains account association without unsupported security assurance', () => {
  assert.match(page, /Account identity is derived by the support service and is not sent from this form\./);
  assert.match(page, /The support service associates the request with that account\./);
  assert.doesNotMatch(page, /derived by the secure support service/);
});

test('ticket submission has an owner-verified response contract and never serializes identity fields', () => {
  assert.match(page, /createMySupportTicket\(draft, undefined, \{[\s\S]*?signal: controller\.signal,[\s\S]*?expectedOwner,[\s\S]*?\}\)/);
  assert.match(service, /const payload = validateTicketDraft\(draft\)/);
  assert.match(service, /\[MY_SUPPORT_TICKETS_ENDPOINT, payload, requestConfig\(signal, \{ mutation: true \}\)\]/);
  assert.match(service, /assertCreatedTicket\(/);
  assert.match(service, /_skipAuthRefresh: true/);
});

test('success UI is response-backed and uncertain failures do not claim no database write', () => {
  assert.match(page, /if \(isCurrentSubmit\(\)\) setCreatedTicket\(ticket\)/);
  assert.match(page, /customer-visible replies in your ticket list\./);
  assert.match(page, /navigate\(`\/support\/ticket\/\$\{encodeURIComponent\(createdTicket\.ticketNumber\)\}`\)/);
  assert.match(page, /setCreatedTicket\(null\); setDraft\(EMPTY_DRAFT\)/);
  assert.match(page, /We could not confirm whether the ticket was created\. Check My tickets before submitting again\./);
});

test('authenticated route, labels, alert, unavailable guard, and duplicate guard remain present', () => {
  assert.match(app, /path="\/support\/create-ticket"[\s\S]{0,240}ProtectedRoute/);
  for (const field of ['ticket-account-name', 'ticket-account-email', 'ticket-subject', 'ticket-category', 'ticket-priority', 'ticket-description']) {
    assert.match(page, new RegExp(`htmlFor="${field}"`));
  }
  assert.match(page, /role="alert"/);
  assert.match(page, /if \(!expectedOwner\) return/);
  assert.match(page, /if \(mutationInFlightRef\.current\) return/);
});
