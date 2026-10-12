import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../src/pages/ProgramsNew.jsx', import.meta.url), 'utf8');

test('programs page preserves the catalog module, configured catalog hook, and existing routes', () => {
  assert.match(source, /import useProgramCatalog from ["']\.\.\/hooks\/useProgramCatalog["']/);
  assert.match(source, /from ["']\.\.\/components\/programs\/CatalogUI["']/);
  assert.match(source, /CatalogCard/);
  assert.match(source, /const catalog = useProgramCatalog\(\)/);
  assert.match(source, /href="#program-comparison"/);
  assert.match(source, /<CatalogCard key=\{program\.id\} program=\{program\} \/>/);
  assert.match(source, /onClick=\{\(\) => setSelectedType\(type\)\}/);
});

test('quote copy conditions availability rather than promising a server quote', () => {
  assert.match(source, /Quote requests may not be available\./);
  assert.match(source, /If enabled, the server can return a quote for your selection\./);
  assert.doesNotMatch(source, /Your selection is priced and recorded by the server\./);
});

test('page keeps an explicit boundary around payment and account activation', () => {
  assert.match(source, /PaymentBoundary/);
  assert.match(source, /Payment and account activation are not enabled\./);
});

test('page retains restrained navy/cyan styling and semantic accessible controls', () => {
  assert.match(source, /text-cyan-300/);
  assert.match(source, /role="group"/);
  assert.match(source, /aria-label="Filter by program type"/);
  assert.match(source, /aria-pressed=\{activeType === type\}/);
  assert.match(source, /aria-hidden="true"/);
});
