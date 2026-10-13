import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';
import { STANDARD_EVALUATION_POLICY as policy, STANDARD_RULES_FAQ, standardPolicyForTerms } from '../src/services/standardEvaluationPolicy.js';
import { PROGRAM_RULE_FAMILIES, programRulesPath } from '../src/services/programRuleFamilies.js';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'standard-evaluation-'));
const serviceUrl = pathToFileURL(path.join(frontend,'src/services/standardEvaluationPolicy.js')).href;
const familiesUrl = pathToFileURL(path.join(frontend,'src/services/programRuleFamilies.js')).href;
const viewUrl = pathToFileURL(path.join(frontend,'src/services/programCatalogViewService.js')).href;
let uiUrl, familyUrl;
async function compile(page) {
  const relative = page.includes('/') ? page : 'pages/'+page;
  let source = fs.readFileSync(path.join(frontend,'src',relative+'.jsx'),'utf8');
  source = source.replace(/import Layout from ['"][^'"]+['"];?/, 'const Layout = ({children}) => <main>{children}</main>;')
    .replace(/from ['"][^'"]+standardEvaluationPolicy\.js['"]/g,'from '+JSON.stringify(serviceUrl))
    .replace(/from ['"][^'"]+programRuleFamilies\.js['"]/g,'from '+JSON.stringify(familiesUrl))
    .replace(/from ['"][^'"]+programCatalogViewService(?:\.js)?['"]/g,'from '+JSON.stringify(viewUrl))
    .replace(/import useProgramCatalog from ['"][^'"]+['"];?/, 'const useProgramCatalog = () => ({ loading: false, error: "", data: [], retry() {} });')
    .replace(/from ['"][^'"]*CatalogUI['"]/g,'from '+JSON.stringify(uiUrl))
    .replace(/from ['"][^'"]+ProgramRuleFamily['"]/g,'from '+JSON.stringify(familyUrl));
  for (const dep of ['react','react-router-dom','lucide-react']) for (const quote of ["'", '"']) source = source.replaceAll(`from ${quote}${dep}${quote}`, `from ${JSON.stringify(pathToFileURL(require.resolve(dep)).href)}`);
  const {code}=await transformWithEsbuild(source,page+'.jsx',{loader:'jsx',jsx:'transform',format:'esm'});
  const file=path.join(dir,page.replaceAll('/','-')+'.mjs');fs.writeFileSync(file,code);return (await import(pathToFileURL(file).href)).default;
}
await compile('components/programs/CatalogUI');
uiUrl=pathToFileURL(path.join(dir,'components-programs-CatalogUI.mjs')).href;
const Family=await compile('components/programs/ProgramRuleFamily');
familyUrl=pathToFileURL(path.join(dir,'components-programs-ProgramRuleFamily.mjs')).href;
const Rules=await compile('TradingRules');
const Terms=await compile('TermsOfService');
const view=(Component)=>new JSDOM(renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/trading-rules']},React.createElement(Component)))).window.document;
const terms=()=>({type:'one_phase',profit_target:'10.00',max_daily_loss:'5.00',max_total_loss:'10.00',profit_split:'90.00',profit_split_percentage:'90.00',rules:{drawdown_type:'static',standard_evaluation_policy:{...policy}}});

test('standard model records only the approved single-stage percentages and explicitly missing operational decisions',()=>{
  assert.equal(policy.phases,1);assert.equal(policy.profit_target,'10.00');assert.equal(policy.max_daily_loss,'5.00');assert.equal(policy.max_total_loss,'10.00');assert.equal(policy.profit_split,'90.00');assert.equal(policy.operator_share,'10.00');assert.equal(policy.drawdown_type,'static');
  assert.equal(policy.daily_loss_amount_base,'initial_account_size');assert.equal(policy.daily_threshold_base,'day_start_closed_balance');assert.equal(policy.breach_comparison,'equity_less_than_or_equal_to_threshold');
  assert.equal(policy.evaluation_target_basis,'closed_profit_after_trading_costs');assert.equal(policy.evaluation_requires_closed_positions,true);
  for(const key of ['daily_reset_timezone','daily_reset_time','funded_account_type','minimum_trading_days','maximum_trading_days','eligible_profit_definition','payout_schedule'])assert.equal(policy[key],null,key+' not invented');
  assert.ok(Object.isFrozen(policy));assert.throws(()=>{policy.profit_split='80.00';},TypeError);
});

test('matching percentages alone do not assign a policy; explicit complete snapshot and all matching terms are required',()=>{
  const original=terms();delete original.rules.standard_evaluation_policy;assert.equal(standardPolicyForTerms(original).status,'unassigned');
  assert.equal(standardPolicyForTerms(null).status,'unassigned');
  const current=terms();const before=JSON.stringify(current);assert.equal(standardPolicyForTerms(current).status,'matched');assert.equal(JSON.stringify(current),before);
  for(const field of ['profit_target','max_daily_loss','max_total_loss','profit_split','profit_split_percentage']){const input=terms();input[field]=null;assert.equal(standardPolicyForTerms(input).status,'mismatch',field);}
  for(const type of ['two_phase','three_phase','instant_funding']){const input=terms();input.type=type;assert.equal(standardPolicyForTerms(input).status,'mismatch',type);}
  const input=terms();input.rules.drawdown_type='trailing';assert.equal(standardPolicyForTerms(input).status,'mismatch');
});

test('recorded old, incomplete, modified or extended policies are never silently relabelled as current',()=>{
  const legacy=terms();legacy.rules.standard_evaluation_policy.version='unknown-version';assert.equal(standardPolicyForTerms(legacy).status,'unsupported');
  for(const key of Object.keys(policy)){const input=terms();delete input.rules.standard_evaluation_policy[key];assert.notEqual(standardPolicyForTerms(input).status,'matched',key);}
  const altered=terms();altered.rules.standard_evaluation_policy.max_daily_loss='3.00';assert.equal(standardPolicyForTerms(altered).status,'mismatch');
  const added=terms();added.rules.standard_evaluation_policy.payout_days=14;assert.equal(standardPolicyForTerms(added).status,'mismatch');
  const pending=terms();pending.rules.standard_evaluation_policy.funded_account_type='real';assert.equal(standardPolicyForTerms(pending).status,'mismatch','a later funded policy needs its own version');
});

test('illustrative thresholds and profit split use exact integer arithmetic, not floats or live account data',()=>{
  const size=10000000n, budget=size*5n/100n;
  assert.equal(budget,500000n);assert.equal(size-budget,9500000n);assert.equal(10200000n-budget,9700000n);assert.equal(size*90n/100n,9000000n);
  const profit=100000n;assert.equal(profit*90n/100n,90000n);assert.equal(profit*10n/100n,10000n);assert.equal(profit*90n/100n+profit*10n/100n,profit);
  const doc=view(Rules), text=doc.body.textContent;
  for(const amount of ['USD 100,000','USD 5,000','USD 95,000','USD 97,000','USD 90,000','USD 1,000','USD 900','USD 100'])assert.ok(text.includes(amount),amount);
  assert.match(text,/Illustration only/);assert.match(text,/Do not subtract the same commission or swap twice/);
  assert.match(text,/Reaching the profit target does not erase an earlier breach/);
});

test('rules render shared values, pending rollout, real destinations, one main and accessible section targets',()=>{
  const doc=view(Rules);assert.equal(doc.querySelectorAll('main').length,1);assert.equal(doc.querySelectorAll('h1').length,1);
  const values=[...doc.querySelectorAll('[data-standard-model] dd')].map(n=>n.textContent);assert.deepEqual(values,['1','10%','5%','10%','90%','10%']);
  assert.match(doc.body.textContent,/Catalog rollout pending/);assert.match(doc.body.textContent,/An existing order keeps the terms recorded with it/);
  for(const el of doc.querySelectorAll('[aria-labelledby]'))assert.ok(doc.getElementById(el.getAttribute('aria-labelledby')));
  for(const to of ['/programs','/terms-of-service','/contact'])assert.ok(doc.querySelector(`a[href="${to}"]`));
  assert.ok(doc.getElementById('profit-share-heading'));
  assert.match(STANDARD_RULES_FAQ.trading,/10% profit target.*5% maximum daily loss.*10% fixed maximum total loss/);
  assert.match(STANDARD_RULES_FAQ.payout,/90% of eligible profit.*10% to the operator/);
});

test('terms remove false legal completion, company/email claims and refund exclusion while retaining the pending contractual status',()=>{
  const doc=view(Terms),text=doc.body.textContent;
  assert.match(text,/Contractual policy is not complete/);assert.match(text,/No registered company/);
  assert.match(text,/90% of eligible profit to the trader and 10% to the operator/);
  assert.match(text,/No automatic refund exclusion/);assert.match(text,/does not transfer ownership/);
  assert.equal(doc.querySelectorAll('main').length,1);assert.ok(doc.querySelector('a[href="/contact"]'));assert.ok(doc.querySelector('a[href="/trading-rules"]'));
  assert.equal(doc.querySelectorAll('a[href^="mailto:"]').length,0);
  assert.doesNotMatch(text,/up to 90%|non-refundable|constitute a legally binding agreement|governed by the laws of|registered in [A-Z]/);
});

test('no new payment, trading or catalog requests; program details retain actual catalog values and quote path',()=>{
  const service=fs.readFileSync(path.join(frontend,'src/services/standardEvaluationPolicy.js'),'utf8');
  assert.doesNotMatch(service,/fetch\(|axios|setInterval|localStorage|sessionStorage|Date\.now/);
  const details=fs.readFileSync(path.join(frontend,'src/pages/ProgramDetails.jsx'),'utf8');
  assert.match(details,/<ProgramRules terms=\{program\.terms\}/);assert.match(details,/<ConfiguredRules terms=\{program\.terms\}/);
  assert.match(details,/to=\{programRulesPath\(program\.terms\.type\)\}/);assert.match(details,/\/programs\/\$\{program\.id\}\/checkout/);
});

test('four immutable structural families have distinct real anchors and no invented percentages',()=>{
  assert.deepEqual(PROGRAM_RULE_FAMILIES.map(item=>item.type),['one_phase','two_phase','three_phase','instant_funding']);
  assert.deepEqual(PROGRAM_RULE_FAMILIES.map(item=>item.stages),[1,2,3,0]);
  const doc=view(Rules);
  for(const family of PROGRAM_RULE_FAMILIES){
    assert.ok(Object.isFrozen(family));assert.ok(doc.getElementById(family.anchor));
    assert.ok(doc.querySelector(`nav a[href="/trading-rules#${family.anchor}"]`));
    assert.equal(programRulesPath(family.type),'/trading-rules#'+family.anchor);
    assert.equal('profit_target' in family,false);
  }
  assert.equal(programRulesPath('unknown'),'/trading-rules');
  const ids=[...doc.querySelectorAll('[id]')].map(el=>el.id);assert.equal(new Set(ids).size,ids.length);
  assert.match(STANDARD_RULES_FAQ.trading,/One-phase, two-phase, three-phase and Instant Funding/);
});

test('family rendering uses only selected catalog terms, including null and stored rules; never assigns standard policy',()=>{
  const rows=PROGRAM_RULE_FAMILIES.map((family,index)=>({id:100+index,terms:{type:family.type,name:'Synthetic '+family.title,account_size:'25000.00',profit_target:index===0?null:'8.00',max_daily_loss:'3.00',max_total_loss:'6.00',profit_split:'80.00',rules:{drawdown_type:'trailing',ea_allowed:false,min_trading_days:null}}}));
  const before=JSON.stringify(rows);
  for(const family of PROGRAM_RULE_FAMILIES){
    const doc=new JSDOM(renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(Family,{family,programs:rows})))).window.document;
    const selected=rows.find(row=>row.terms.type===family.type);
    assert.equal(doc.querySelectorAll('option').length,1);assert.ok(doc.querySelector(`a[href="/programs/${selected.id}"]`));
    assert.equal(doc.querySelector('[data-family-program]').getAttribute('data-family-program'),String(selected.id));
    assert.match(doc.body.textContent,/Not specified/);assert.match(doc.body.textContent,/trailing/);assert.match(doc.body.textContent,/false/);
    assert.ok(doc.getElementById(family.anchor+'-additional'));
    if(family.stages>1)assert.match(doc.body.textContent,/Individual stage targets and transition criteria still require confirmation/);
  }
  assert.equal(JSON.stringify(rows),before);
});

test.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
