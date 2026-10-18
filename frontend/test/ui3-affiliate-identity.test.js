import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const source=fs.readFileSync(new URL('../src/pages/affiliate/AffiliateLanding.jsx',import.meta.url),'utf8');
test('registration owns a separate component instance for each authenticated user tenant and role',()=>{
 assert.match(source,/return <AffiliateLandingContent key=\{contextKey\} \/>/);
 const wrapper=source.slice(source.indexOf('export default function AffiliateLanding'));
 for(const key of ['authenticated','user?.id','user?.tenant_id','user?.tenantId','user?.tenant?.id','user?.role'])assert.ok(wrapper.includes(key),key);
 assert.match(source,/mountedRef.current = false/);
 assert.match(source,/!mountedRef.current \|\| identityRef.current !== requestIdentity/);
});
test('server-provided referral URL must not contain credentials',()=>{
 assert.match(source,/parsed.username \|\| parsed.password/);
 assert.match(source,/parsed.origin !== base/);
});
