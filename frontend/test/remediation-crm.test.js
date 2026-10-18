import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { transformWithEsbuild } from 'vite';

const crm = fs.readFileSync(new URL('../src/pages/admin/CRM.jsx', import.meta.url), 'utf8');
const leadDetails = fs.readFileSync(new URL('../src/pages/admin/LeadDetails.jsx', import.meta.url), 'utf8');

test('CRM:1 stages search input and only requests it through explicit apply/reset controls', () => {
  assert.match(crm, /const \[searchDraft, setSearchDraft\] = useState\(''\);/);
  assert.match(crm, /const applySearch = \(\) => \{\s+setPage\(1\);\s+setFilters\(\(current\) => \(\{ \.\.\.current, search: searchDraft \}\)\);/);
  assert.match(crm, /value=\{searchDraft\} onChange=\{\(event\) => setSearchDraft\(event\.target\.value\)\}/);
  assert.match(crm, /onClick=\{applySearch\}[^>]*>Apply search<\/button>/);
  assert.match(crm, /onClick=\{resetFilters\}[^>]*>Reset filters<\/button>/);
  assert.doesNotMatch(crm, /updateFilter\('search'/);
});

test('CRM:0 retries list and statistics independently while preserving their request ownership effects', () => {
  assert.match(crm, /const retryList = \(\) => setListRefreshVersion\(\(version\) => version \+ 1\);/);
  assert.match(crm, /const retryStats = \(\) => setStatsRefreshVersion\(\(version\) => version \+ 1\);/);
  assert.match(crm, /onClick=\{retryList\}[^>]*>Retry lead list<\/button>/);
  assert.match(crm, /onClick=\{retryStats\}[^>]*>Retry statistics<\/button>/);
  assert.match(crm, /\[filters, identity, listRefreshVersion, page, principalKey\]/);
  assert.match(crm, /\[identity, principalKey, statsRefreshVersion\]/);
  assert.match(crm, /expectedOwner: actor\.owner,\s+role: actor\.role,\s+signal: lease\.signal/);
});

test('CRM:3 uses a SPA Link to the real lead route instead of making a table row interactive', () => {
  assert.match(crm, /import \{ Link, useNavigate \} from 'react-router-dom';/);
  assert.match(crm, /<Link to=\{`\/admin\/crm\/\$\{lead\.id\}`\}[^>]*>\{displayName\(lead\)\}<\/Link>/);
  assert.doesNotMatch(crm, /<tr key=\{lead\.id\} tabIndex=\{0\} onClick=/);
});

test('CRM:2 attaches the shared dialog focus manager to the conditional Add lead dialog', () => {
  assert.match(crm, /import useDialogFocus from '\.\.\/\.\.\/hooks\/useDialogFocus';/);
  assert.match(crm, /const addLeadDialogRef = useDialogFocus\(\{ open: showAddModal, onClose: closeAddModal \}\);/);
  assert.match(crm, /<div ref=\{addLeadDialogRef\} role="dialog" aria-modal="true" aria-labelledby="add-lead-title"/);
  assert.match(crm, /First name<input data-autofocus required/);
  assert.match(crm, /onClick=\{closeAddModal\} aria-label="Close add lead dialog"/);
});

test('LeadDetails:0/1 applies shared focus behavior to both dialogs and scrolls long activity content internally', () => {
  assert.match(leadDetails, /import useDialogFocus from '\.\.\/\.\.\/hooks\/useDialogFocus';/);
  assert.match(leadDetails, /const editDialogRef = useDialogFocus\(\{ open: showEdit, onClose: closeEditDialog \}\);/);
  assert.match(leadDetails, /const activityDialogRef = useDialogFocus\(\{ open: showActivity, onClose: closeActivityDialog \}\);/);
  assert.match(leadDetails, /<div ref=\{editDialogRef\} role="dialog" aria-modal="true" aria-labelledby="edit-lead-title"/);
  assert.match(leadDetails, /<div ref=\{activityDialogRef\} role="dialog" aria-modal="true" aria-labelledby="activity-title" className="mep-panel max-h-\[90vh\][^"]*overflow-y-auto/);
  assert.match(leadDetails, /Status<select data-autofocus value=\{form\.status\}/);
  assert.match(leadDetails, /Activity date and time<input data-autofocus required type="datetime-local"/);
});

test('CRM fixes retain Decimal/NULL conversion and scoped mutation guards', () => {
  assert.match(crm, /const blankLead = \(\) => \(\{[^}]*budget: ''/);
  assert.match(crm, /createLead\(\{ expectedOwner: actor\.owner, role: actor\.role, payload: newLead, signal: lease\.signal \}\)/);
  assert.match(leadDetails, /budget: form\.budget === '' \? null : form\.budget/);
  assert.match(leadDetails, /expectedOwner: lease\.principal\.owner, role: lease\.principal\.role/);
  assert.match(leadDetails, /if \(!lease\.isCurrent\(\)\) return;/);
});

test('the remediated CRM JSX sources parse without a build or browser run', async () => {
  await Promise.all([
    transformWithEsbuild(crm, 'CRM.jsx', { loader: 'jsx', jsx: 'automatic' }),
    transformWithEsbuild(leadDetails, 'LeadDetails.jsx', { loader: 'jsx', jsx: 'automatic' }),
  ]);
});
