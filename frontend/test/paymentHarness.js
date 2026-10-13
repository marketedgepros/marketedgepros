import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { transformWithEsbuild } from 'vite';
const require = createRequire(import.meta.url);
const sourceRoot = new URL('../src/', import.meta.url).pathname;
const packageUrl = (specifier) => /^(?:node:|file:)/.test(specifier) ? specifier : pathToFileURL(require.resolve(specifier)).href;
export async function compilePaymentHarness(entry, { prefix = 'payment-ui', overrides = {} } = {}) {
  const targets = new Map(), files = [];
  const apiMock = `const api = { get: (...args) => { if (!globalThis.__payment_client) return Promise.reject(new Error('Synthetic payment transport is not configured')); return globalThis.__payment_client.get(...args); }, post: (...args) => { if (!globalThis.__payment_client) return Promise.reject(new Error('Synthetic payment transport is not configured')); return globalThis.__payment_client.post(...args); } }; export const profileAPI = { get: config => api.get('/profile', config) }; export default api;`;
  const authMock = `const useAuthStore = selector => selector ? selector(globalThis.__payment_auth || {}) : (globalThis.__payment_auth || {}); export default useAuthStore;`;
  const defaults = { 'services/api.js': apiMock, 'store/authStore.js': authMock };
  async function compile(file) {
    file = path.resolve(file);
    if (targets.has(file)) return targets.get(file);
    const digest = createHash('sha256').update(file).digest('hex').slice(0, 12);
    const target = new URL(`../node_modules/.${prefix}-${process.pid}-${digest}.mjs`, import.meta.url);
    targets.set(file, target.href); files.push(target);
    const relative = path.relative(sourceRoot, file);
    let text = overrides[relative] ?? defaults[relative] ?? fs.readFileSync(file, 'utf8');
    text = text.replace(/^import\s+['"][^'"\n]+\.css['"];?\s*$/gm, '');
    const imports = [...text.matchAll(/\b(?:from\s*|import\s*)['"]([^'"\n]+)['"]/g)];
    for (const match of imports) {
      const specifier = match[1]; let href;
      if (specifier.startsWith('.')) {
        const base = path.resolve(path.dirname(file), specifier);
        const dependency = [base, `${base}.js`, `${base}.jsx`, path.join(base, 'index.js')].find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
        if (!dependency || !dependency.startsWith(sourceRoot)) throw new Error(`Invalid synthetic import: ${specifier}`);
        href = await compile(dependency);
      } else href = packageUrl(specifier);
      text = text.replace(match[0], match[0].replace(new RegExp(`(['"])${specifier.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\1$`), JSON.stringify(href)));
    }
    const transformed = await transformWithEsbuild(text, file, { loader: file.endsWith('.jsx') ? 'jsx' : 'js', jsx: 'automatic' });
    const code = transformed.code.replace(/\bfrom\s*['"](react\/jsx-runtime)['"]/g, `from ${JSON.stringify(packageUrl('react/jsx-runtime'))}`);
    fs.writeFileSync(target, code);
    return target.href;
  }
  try {
    const url = await compile(entry instanceof URL ? entry.pathname : entry);
    return { module: await import(url), targets, cleanup() { for (const target of files) fs.rmSync(target, { force: true }); } };
  } catch (error) { for (const target of files) fs.rmSync(target, { force: true }); throw error; }
}
export const purchaseRecordsFixture = (userId = 1, tenantId = 10, role = 'user') => ({ schema_version: 1, owner_context: { user_id: userId, tenant_id: tenantId, role }, availability: true, source_unavailable: false, reason: null, records: [], pagination: { page: 1, per_page: 20, total: 0, pages: 0, has_next: false, has_prev: false } });
