import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const pageUrl = new URL('../src/pages/support/CreateTicket.jsx', import.meta.url);
const serviceUrl = new URL('../src/services/supportTicketViewService.js', import.meta.url);
const appUrl = new URL('../src/App.jsx', import.meta.url);
const page = fs.readFileSync(pageUrl, 'utf8');
const service = fs.readFileSync(serviceUrl, 'utf8');
const app = fs.readFileSync(appUrl, 'utf8');

test('create-ticket copy avoids unsupported security assurance and states account association plainly', () => {
  assert.match(page, /Account identity is derived by the support service and is not sent from this form\./);
  assert.match(page, /Your request is associated with that account\./);
  assert.doesNotMatch(page, /derived by the secure support service/);
});

test('ticket submission sends the validated draft only and server derives account ownership', () => {
  assert.match(page, /createMySupportTicket\(draft, undefined, \{ signal: controller\.signal \}\)/);
  assert.match(page, /Do not send name or email: the authenticated backend derives ticket ownership\./);
  assert.match(service, /return \{\s*subject: boundedText\(draft\.subject[\s\S]*?description: boundedText\(draft\.description[\s\S]*?category,\s*priority,/);
  assert.match(service, /apiClient\.post\(\s*MY_SUPPORT_TICKETS_ENDPOINT,\s*validateTicketDraft\(draft\)/);
});

test('success presentation is response-backed and actions retain ticket navigation and reset behavior', () => {
  assert.match(page, /if \(isCurrentSubmit\(\)\) setCreatedTicket\(ticket\)/);
  assert.match(page, /You can review this request and any customer-visible replies from your ticket list\./);
  assert.match(page, /navigate\(`\/support\/ticket\/\$\{encodeURIComponent\(createdTicket\.ticketNumber\)\}`\)/);
  assert.match(page, /setCreatedTicket\(null\);\s*setDraft\(EMPTY_DRAFT\)/);
  assert.match(page, /Unable to create the ticket\. Your details were not submitted\./);
});

test('authenticated route, accessible labels, error status, and duplicate-submit guard remain present', () => {
  assert.match(app, /path="\/support\/create-ticket"[\s\S]{0,240}ProtectedRoute/);
  for (const field of ['ticket-account-name', 'ticket-account-email', 'ticket-subject', 'ticket-category', 'ticket-priority', 'ticket-description']) {
    assert.match(page, new RegExp(`htmlFor="${field}"`));
  }
  assert.match(page, /role="alert"/);
  assert.match(page, /if \(mutationInFlightRef\.current\) return/);
});
