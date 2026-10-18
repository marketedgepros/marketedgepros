import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { publicSiteOrigin, publicPageUrl, isPrivatePage, buildPublicSchema, serializePublicSchema } from '../src/services/publicMetadataService.js';

test('public origin must be explicit HTTPS without credentials or path', () => {
  for (const value of [undefined, '', 'http://example.invalid', 'https://user:password@example.invalid', 'https://example.invalid/path', 'https://example.invalid/?x=1', 'https://example.invalid/#x']) assert.equal(publicSiteOrigin(value), null);
  assert.equal(publicSiteOrigin('https://example.invalid/'), 'https://example.invalid');
  assert.equal(publicPageUrl(null, '/programs'), null);
  assert.equal(publicPageUrl('https://example.invalid', '//foreign.invalid'), null);
  assert.equal(publicPageUrl('https://example.invalid', '/programs'), 'https://example.invalid/programs');
});

test('private routes are not promoted for public indexing', () => {
  for (const path of ['/admin', '/admin/crm/12', '/affiliate/commissions', '/affiliate/payout', '/trader/history', '/user/dashboard', '/profile', '/challenges/12', '/support/ticket/TST', '/login', '/settings/notifications']) assert.equal(isPrivatePage(path), true, path);
  for (const path of ['/', '/programs', '/affiliate', '/support', '/support/article', '/faq', '/how-it-works']) assert.equal(isPrivatePage(path), false, path);
});

test('organization and website schemas do not invent reviews or company facts', () => {
  for (const type of ['organization', 'website']) {
    const schema = buildPublicSchema(type);
    assert.equal(schema.name, 'MarketEdgePros');
    for (const key of ['url', 'logo', 'address', 'contactPoint', 'sameAs', 'foundingDate', 'potentialAction', 'aggregateRating', 'review', 'offers']) assert.equal(schema[key], undefined);
    assert.doesNotMatch(JSON.stringify(schema), /400,000|200K|90%|instant funding|fast payouts/);
  }
});

test('catalog-only product cannot manufacture free price or purchasable offer', () => {
  assert.equal(buildPublicSchema('product'), null);
  const product = buildPublicSchema('product', {name:'Synthetic program', price:'0', url:'/programs/12'});
  assert.equal(product.name, 'Synthetic program');
  assert.equal(product.offers, undefined);
  assert.equal(product.aggregateRating, undefined);
});

test('articles only use supplied valid dates and never imply current publication', () => {
  assert.equal(buildPublicSchema('article'), null);
  const withoutDates = buildPublicSchema('article', {title:'Synthetic article', datePublished:'invalid'});
  assert.equal(withoutDates.datePublished, undefined);
  assert.equal(withoutDates.dateModified, undefined);
  assert.equal(withoutDates.author, undefined);
  assert.equal(buildPublicSchema('article', {title:'Synthetic article',datePublished:'2026-10-12T00:00:00Z'}).datePublished, '2026-10-12T00:00:00Z');
});

test('FAQ and breadcrumbs require actual supplied content and safe own-origin URLs', () => {
  assert.equal(buildPublicSchema('faq'), null);
  assert.equal(buildPublicSchema('faq', {questions:[{}]}), null);
  const faq=buildPublicSchema('faq', {questions:[{question:'Question?',answer:'Answer.'}]});
  assert.equal(faq.mainEntity.length, 1);
  assert.equal(buildPublicSchema('breadcrumb', {items:[{name:'Home',url:'/'}]}), null);
  assert.equal(buildPublicSchema('breadcrumb', {items:[{name:'Unsafe',url:'https://foreign.invalid/'}]}, 'https://example.invalid'), null);
  const crumbs=buildPublicSchema('breadcrumb', {items:[{name:'Programs',url:'/programs'}]}, 'https://example.invalid');
  assert.equal(crumbs.itemListElement[0].item, 'https://example.invalid/programs');
});

test('schema serialization cannot terminate a script tag', () => {
  const data={headline:'</script><script>alert(1)</script> & \u2028'};
  const value=serializePublicSchema(data);
  assert.doesNotMatch(value, /<|>|&|\u2028/);
  assert.deepEqual(JSON.parse(value), data);
});

test('initial metadata and manifest contain no funding claims or missing icon paths', () => {
  const html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
  assert.doesNotMatch(html, /200,000|fast payouts|Competitive profit|XXX|FinancialService|aggregateRating|og-image\.jpg|twitter-image\.jpg|logo\.png/);
  const manifest=JSON.parse(fs.readFileSync(new URL('../public/manifest.json',import.meta.url),'utf8'));
  assert.doesNotMatch(manifest.description,/Get funded|200,000/);
  for(const icon of manifest.icons) assert.ok(fs.existsSync(new URL('../public'+icon.src,import.meta.url)));
});

test('floating chat is desktop-only so narrow-page copy remains unobscured', () => {
  const app=fs.readFileSync(new URL('../src/App.jsx',import.meta.url),'utf8');
  assert.match(app, /return <div className="hidden md:block"><ChatWidget \/><\/div>/);
});
