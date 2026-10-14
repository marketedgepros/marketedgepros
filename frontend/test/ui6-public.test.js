import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { MemoryRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

// React DOM must be imported only after a DOM is available so controlled input
// handlers use the same host configuration as the mounted source components.
const bootstrapDom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://ui6.bootstrap.test/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrapDom.window, document: bootstrapDom.window.document, navigator: bootstrapDom.window.navigator })) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
}
const { createRoot } = await import('react-dom/client');
const helmetModule = await import('react-helmet-async');
const HelmetProvider = (helmetModule.default ?? helmetModule).HelmetProvider;
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrapDom.window.close();

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = (...parts) => path.join(frontend, 'src', ...parts);
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ui6-public-dom-'));
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const dependencies = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
  ['react-helmet-async', dependencyUrl('react-helmet-async')],
]);
let serial = 0;

function externalize(code) {
  for (const name of ['standardEvaluationPolicy', 'programRuleFamilies', 'programEvaluationPolicy']) code = code.replace(new RegExp(`from ['"][^'"]+${name}\\.js['"]`, 'g'), 'from '+JSON.stringify(pathToFileURL(source('services', name+'.js')).href));
  for (const [specifier, url] of dependencies) {
    code = code.replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
    code = code.replaceAll(`from \"${specifier}\"`, `from ${JSON.stringify(url)}`);
  }
  return code;
}
function writeModule(name, code) {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, externalize(code));
  return pathToFileURL(target).href;
}
async function bounded(promise, label) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Timed out importing ${label}`)), 5000); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}
async function compile(relative, name, mutate = (value) => value) {
  const file = source(...relative.split('/'));
  const original = mutate(fs.readFileSync(file, 'utf8'));
  const transformed = await transformWithEsbuild(externalize(original), file, { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  const target = path.join(tempDir, `${name}-${serial += 1}.mjs`);
  fs.writeFileSync(target, externalize(transformed.code));
  return bounded(import(`${pathToFileURL(target).href}?ui6-public=${serial}`), name);
}

const layoutStub = writeModule('layout.mjs', `
  import React from ${JSON.stringify(dependencies.get('react'))};
  export default function Layout({ children }) { return React.createElement('div', { 'data-ui6-layout': 'public' }, children); }
`);
const noOpStub = writeModule('noop.mjs', `import React from ${JSON.stringify(dependencies.get('react'))}; export default function NoOp() { return null; }`);
const apiStub = writeModule('api.mjs', `export default { get: (...args) => globalThis.__ui6PublicApi.get(...args) };`);
const catalogHookStub = writeModule('catalog-hook.mjs', `export default function useProgramCatalog() { return globalThis.__ui6Catalog; }`);
const comingSoonSource = fs.readFileSync(source('components', 'programs', 'ComingSoonProgram.jsx'), 'utf8');
const comingSoonCode = await transformWithEsbuild(externalize(comingSoonSource), 'ComingSoonProgram.jsx', { loader: 'jsx', jsx: 'automatic', format: 'esm' });
const comingSoonUrl = writeModule('coming-soon-program.mjs', externalize(comingSoonCode.code));
const catalogUiStub = writeModule('catalog-ui.mjs', `
  import React from ${JSON.stringify(dependencies.get('react'))};
  export const primaryAction = 'ui6-primary-action';
  export const secondaryAction = 'ui6-secondary-action';
  export const CatalogCard = ({ program }) => React.createElement('article', { 'data-catalog-card': program.id }, program.name);
  export const CatalogState = ({ loading, error, empty }) => React.createElement('p', { 'data-catalog-state': loading ? 'loading' : error ? 'error' : empty ? 'empty' : 'ready' }, loading ? 'Catalog loading' : error ? 'Catalog unavailable' : 'Catalog empty');
  export const PaymentBoundary = () => React.createElement('p', { 'data-payment-boundary': 'true' }, 'Payments unavailable');
  export const ProgramRules = () => React.createElement('dl', { 'data-program-rules': 'true' });
`);

const replaceLayout = (text) => text.replace(/import Layout from ['"][^'"]+\/components\/layout\/Layout['"];?/, `import Layout from ${JSON.stringify(layoutStub)};`);
const withoutHomepageVisuals = (text) => text
  .replace(/import useScrollReveal from ['"][^'"]+useScrollReveal['"];?\s*/, "const useScrollReveal = () => ({ ref: null, state: 'visible', className: '' });\n")
  .replace(/import ['"][^'"]+homeMotion\.css['"];?\s*/, '');
const replaceApi = (text) => text.replace(/import api from ['"][^'"]+\/services\/api['"];?/, `import api from ${JSON.stringify(apiStub)};`);
const withoutSeo = (text) => text.replace(/import SEO from ['"][^'"]+\/components\/SEO['"];?/, `import SEO from ${JSON.stringify(noOpStub)};`);
const withoutArticleLibraries = (text) => text
  .replace(/import \{ Helmet \} from ['"]react-helmet-async['"];?/, 'const Helmet = ({ children }) => children;')
  .replace(/import ReactMarkdown from ['"]react-markdown['"];?/, 'const ReactMarkdown = ({ children }) => <div>{children}</div>;')
  .replace(/import DOMPurify from ['"]isomorphic-dompurify['"];?/, 'const DOMPurify = { sanitize: (value) => value };');

await compile('components/programs/ProgramSelector.jsx', 'program-selector', (text) => text
  .replace(/import ['"][^'"]+\.css['"];/, '')
  .replace(/import \{ ProgramRules, primaryAction \} from ['"]\.\/CatalogUI['"];?/, `import { ProgramRules, primaryAction } from ${JSON.stringify(catalogUiStub)};`)
  .replace(/import ComingSoonProgram from ['"]\.\/ComingSoonProgram['"];?/, `import ComingSoonProgram from ${JSON.stringify(comingSoonUrl)};`)
  .replace(/from ['"]\.\.\/\.\.\/services\/programCatalogViewService['"]/, `from ${JSON.stringify(pathToFileURL(source('services', 'programCatalogViewService.js')).href)}`));
const programSelectorUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('program-selector-')))).href;

const revealUrl = writeModule('premium-reveal.mjs', externalize(fs.readFileSync(source('hooks', 'useScrollReveal.js'), 'utf8')));
const ambientUrl = writeModule('premium-ambient.mjs', externalize(fs.readFileSync(source('hooks', 'useAmbientMotion.js'), 'utf8').replace("'./useScrollReveal'", JSON.stringify(revealUrl))));
const showcaseSource = fs.readFileSync(source('components', 'visual', 'PlatformShowcase.jsx'), 'utf8');
const showcaseCode = await transformWithEsbuild(externalize(showcaseSource), 'PlatformShowcase.jsx', { loader: 'jsx', jsx: 'automatic', format: 'esm' });
const showcaseUrl = writeModule('premium-showcase.mjs', externalize(showcaseCode.code));
await compile('components/programs/CatalogUI.jsx', 'rules-catalog-ui', (text) => text
  .replace(/import Layout from ['"][^'"]+['"];/, 'const Layout = ({ children }) => <main>{children}</main>;')
  .replace(/import ComingSoonProgram from ['"]\.\/ComingSoonProgram['"];?/, `import ComingSoonProgram from ${JSON.stringify(comingSoonUrl)};`)
  .replace(/from ['"][^'"]+programCatalogViewService['"]/, `from ${JSON.stringify(pathToFileURL(source('services', 'programCatalogViewService.js')).href)}`));
const rulesUiUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('rules-catalog-ui-')))).href;
await compile('components/programs/ProgramRuleFamily.jsx', 'rule-family', (text) => text
  .replace(/from ['"][^'"]+programCatalogViewService\.js['"]/, `from ${JSON.stringify(pathToFileURL(source('services', 'programCatalogViewService.js')).href)}`)
  .replace(/import ComingSoonProgram from ['"]\.\/ComingSoonProgram['"];?/, `import ComingSoonProgram from ${JSON.stringify(comingSoonUrl)};`)
  .replace(/from ['"]\.\/CatalogUI['"]/, `from ${JSON.stringify(rulesUiUrl)}`));
const ruleFamilyUrl = pathToFileURL(path.join(tempDir, fs.readdirSync(tempDir).find((name) => name.startsWith('rule-family-')))).href;
const pages = {
  Home: (await compile('pages/NewHomePage.jsx', 'home', (text) => withoutHomepageVisuals(replaceLayout(text)
    .replace(/import SchemaMarkup from ['"][^'"]+SchemaMarkup['"];?/, `import SchemaMarkup from ${JSON.stringify(noOpStub)};`)
    .replace(/import CatalogPreview from ['"][^'"]+CatalogPreview['"];?/, `import CatalogPreview from ${JSON.stringify(noOpStub)};`)
    .replace(/import useAmbientMotion from ['"][^'"]+useAmbientMotion['"];?/, `import useAmbientMotion from ${JSON.stringify(ambientUrl)};`)
    .replace(/import PlatformShowcase from ['"][^'"]+PlatformShowcase['"];?/, `import PlatformShowcase from ${JSON.stringify(showcaseUrl)};`)))).default,
  About: (await compile('pages/AboutUs.jsx', 'about', replaceLayout)).default,
  How: (await compile('pages/HowItWorks.jsx', 'how', replaceLayout)).default,
  FAQ: (await compile('pages/FAQ.jsx', 'faq', (text) => replaceLayout(text).replace(/import StructuredData from ['"][^'"]+StructuredData['"];?/, `import StructuredData from ${JSON.stringify(noOpStub)};`))).default,
  Contact: (await compile('pages/Contact.jsx', 'contact', replaceLayout)).default,
  FreeCourse: (await compile('pages/FreeCourse.jsx', 'free-course', (text) => withoutSeo(replaceLayout(text)))).default,
  SupportHub: (await compile('pages/support/SupportHub.jsx', 'support-hub', (text) => replaceApi(withoutSeo(replaceLayout(text))))).default,
  Article: (await compile('pages/support/Article.jsx', 'support-article', (text) => replaceApi(withoutArticleLibraries(replaceLayout(text))))).default,
  Blog: (await compile('pages/Blog.jsx', 'blog', (text) => replaceApi(replaceLayout(text)))).default,
  BlogPost: (await compile('pages/BlogPost.jsx', 'blog-post', (text) => replaceApi(withoutSeo(withoutArticleLibraries(replaceLayout(text)))))).default,
  Terms: (await compile('pages/TermsOfService.jsx', 'terms', replaceLayout)).default,
  Privacy: (await compile('pages/PrivacyPolicy.jsx', 'privacy', replaceLayout)).default,
  Risk: (await compile('pages/RiskDisclosure.jsx', 'risk', replaceLayout)).default,
  TradingRules: (await compile('pages/TradingRules.jsx', 'trading-rules', (text) => replaceLayout(text)
    .replace(/import useProgramCatalog from ['"][^'"]+['"];?/, 'const useProgramCatalog = () => ({ loading: false, error: "", data: [], retry() {} });')
    .replace(/from ['"][^'"]+ProgramRuleFamily['"]/, `from ${JSON.stringify(ruleFamilyUrl)}`)
    .replace(/from ['"][^'"]+CatalogUI['"]/, `from ${JSON.stringify(rulesUiUrl)}`))).default,
  Refund: (await compile('pages/RefundPolicy.jsx', 'refund', replaceLayout)).default,
  Cookie: (await compile('pages/CookiePolicy.jsx', 'cookie', (text) => replaceLayout(text).replace(/import AnalyticsStatus from ['"][^'"]+AnalyticsStatus['"];?/, `import AnalyticsStatus from ${JSON.stringify(noOpStub)};`))).default,
  Careers: (await compile('pages/Careers.jsx', 'careers', replaceLayout)).default,
  CatalogPreview: (await compile('components/programs/CatalogPreview.jsx', 'catalog-preview', (text) => text
    .replace(/import useProgramCatalog from ['"][^'"]+useProgramCatalog['"];?/, `import useProgramCatalog from ${JSON.stringify(catalogHookStub)};`)
    .replace(/import ProgramSelector from ['"]\.\/ProgramSelector['"];?/, `import ProgramSelector from ${JSON.stringify(programSelectorUrl)};`)
    .replace(/import\s+\{[^}]+\}\s+from ['"]\.\/CatalogUI['"];?/, `import { CatalogCard, CatalogState, PaymentBoundary, secondaryAction } from ${JSON.stringify(catalogUiStub)};`))).default,
  SEO: (await compile('components/SEO.jsx', 'seo', (text) => text
    .replace("import { Helmet } from 'react-helmet-async';", `import HelmetPackage from ${JSON.stringify(dependencyUrl('react-helmet-async'))}; const { Helmet } = HelmetPackage;`)
    .replace(/from ['"]\.\.\/services\/publicMetadataService['"]/g, `from ${JSON.stringify(pathToFileURL(source('services', 'publicMetadataService.js')).href)}`)
    .replace('import.meta.env.VITE_PUBLIC_SITE_URL', JSON.stringify('https://public.example.invalid')))).default,
};

function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { 'data-location': 'true' }, `${location.pathname}${location.search}${location.hash}`);
}
function BackControl() {
  const navigate = useNavigate();
  return React.createElement('button', { type: 'button', 'data-router-back': 'true', onClick: () => navigate(-1) }, 'Back');
}
function installDom(pathname = '/') {
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', {
    url: `http://ui6.public.test${pathname}`,
    pretendToBeVisual: true,
  });
  dom.window.scrollTo = () => {};
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLAnchorElement', 'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT'];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const supplied = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLAnchorElement: dom.window.HTMLAnchorElement,
    Node: dom.window.Node,
    Element: dom.window.Element,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(supplied)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom,
    root,
    host: dom.window.document.getElementById('root'),
    async render(node) { await act(async () => { root.render(node); await Promise.resolve(); }); },
    async close() {
      await act(async () => { root.unmount(); });
      dom.window.close();
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
    },
  };
}
async function waitFor(predicate, label) {
  let last;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try { if (predicate()) return; } catch (error) { last = error; }
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
  }
  throw last || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected an actionable DOM element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await Promise.resolve();
  });
}
async function changeValue(element, value) {
  assert.ok(element, 'expected a controlled input');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const previous = element.value;
  setter.call(element, value);
  element._valueTracker?.setValue(previous);
  const propsKey = Object.keys(element).find((key) => key.startsWith('__reactProps$'));
  const props = propsKey ? element[propsKey] : null;
  await act(async () => {
    if (typeof props?.onChange === 'function') props.onChange({ target: element });
    else {
      element.dispatchEvent(new window.Event('input', { bubbles: true, cancelable: true }));
      element.dispatchEvent(new window.Event('change', { bubbles: true, cancelable: true }));
    }
    await Promise.resolve();
  });
}
function anchors(host, href) { return [...host.querySelectorAll(`a[href="${href}"]`)]; }
function text(host) { return host.textContent.replace(/\s+/g, ' ').trim(); }
function suppressExpectedFixtureConsoleError() {
  const original = console.error;
  console.error = () => {};
  return () => { console.error = original; };
}
function routeElement(pathname, routePath, Component, key = pathname) {
  return React.createElement(MemoryRouter, { initialEntries: [pathname], key },
    React.createElement(React.Fragment, null,
      React.createElement(Routes, null,
        React.createElement(Route, { path: routePath, element: React.createElement(Component) }),
        React.createElement(Route, { path: '*', element: React.createElement('span', { 'data-unmatched-route': 'true' }) }),
      ),
      React.createElement(LocationProbe),
    ));
}

// These public pages have no role gate or write API. The loop uses the source
// leaf components, actual React Router DOM links, and a fresh mount as the
// permitted/guest and refresh evidence; role-specific denial is not applicable.
test('UI6 public static route DOM fixtures mount, remount, and expose every recorded internal or external boundary', { concurrency: false }, async () => {
  const view = installDom('/');
  const fixtures = [
    ['/', '/', pages.Home, 'Explore trading programs with', [['/programs', 2], ['/how-it-works', 1], ['/faq', 1], ['/support', 1]]],
    ['/home', '/home', pages.Home, 'Explore trading programs with', [['/programs', 2], ['/how-it-works', 1], ['/faq', 1], ['/support', 1]]],
    ['/about', '/about', pages.About, 'A clear place to explore our programs.', [['/programs', 2]]],
    ['/how-it-works', '/how-it-works', pages.How, 'How it works', [['/programs', 2]]],
    ['/contact', '/contact', pages.Contact, 'How can we help?', [['/support', 1], ['/faq', 1], ['/programs', 1]]],
    ['/free-course', '/free-course', pages.FreeCourse, 'Introductory trading topics', [['/programs', 1], ['/contact', 1]]],
    ['/terms-of-service', '/terms-of-service', pages.Terms, 'Terms of Service', [['/trading-rules', 1], ['/contact', 1]]],
    ['/privacy-policy', '/privacy-policy', pages.Privacy, 'Privacy Policy', [['mailto:privacy@marketedgepros.com', 1]]],
    ['/risk-disclosure', '/risk-disclosure', pages.Risk, 'Risk Disclosure', [['mailto:info@marketedgepros.com', 1]]],
    ['/trading-rules', '/trading-rules', pages.TradingRules, 'Trading rules and program terms', [['/programs', 1]]],
    ['/refund-policy', '/refund-policy', pages.Refund, 'Refund Policy', [['mailto:info@marketedgepros.com', 1]]],
    ['/cookie-policy', '/cookie-policy', pages.Cookie, 'Cookie Policy', [['mailto:info@marketedgepros.com', 1]]],
    ['/careers', '/careers', pages.Careers, 'Build thoughtful tools for traders.', [['/contact', 2]]],
  ];
  try {
    for (const [pathname, routePath, Component, marker, linkChecks] of fixtures) {
      await view.render(routeElement(pathname, routePath, Component, `initial-${pathname}`));
      await waitFor(() => text(view.host).includes(marker), `${pathname} content`);
      assert.equal(view.host.querySelector('[data-location]').textContent, pathname, `${pathname} remains public for an anonymous fixture`);
      for (const [href, count] of linkChecks) assert.equal(anchors(view.host, href).length, count, `${pathname} exact anchor ${href}`);
      assert.ok(view.host.querySelector('[data-ui6-layout="public"]'), `${pathname} uses the shared public layout slot`);
      await view.render(null);
      await view.render(routeElement(pathname, routePath, Component, `refresh-${pathname}`));
      await waitFor(() => text(view.host).includes(marker), `${pathname} remount`);
    }

    for (const [alias, destination, Component, marker] of [
      ['/terms', '/terms-of-service', pages.Terms, 'Terms of Service'],
      ['/privacy', '/privacy-policy', pages.Privacy, 'Privacy Policy'],
    ]) {
      await view.render(React.createElement(MemoryRouter, { initialEntries: [alias], key: alias },
        React.createElement(React.Fragment, null,
          React.createElement(Routes, null,
            React.createElement(Route, { path: alias, element: React.createElement(Navigate, { to: destination, replace: true }) }),
            React.createElement(Route, { path: destination, element: React.createElement(Component) }),
          ),
          React.createElement(LocationProbe),
        )));
      await waitFor(() => view.host.querySelector('[data-location]').textContent === destination, `${alias} alias`);
      assert.ok(text(view.host).includes(marker), `${alias} alias mounts the actual policy component`);
    }

    await view.render(React.createElement(MemoryRouter, { initialEntries: ['/', '/about'], initialIndex: 1, key: 'back-forward' },
      React.createElement(React.Fragment, null,
        React.createElement(Routes, null,
          React.createElement(Route, { path: '/', element: React.createElement(pages.Home) }),
          React.createElement(Route, { path: '/about', element: React.createElement(pages.About) }),
        ),
        React.createElement(BackControl), React.createElement(LocationProbe),
      )));
    await click(view.host.querySelector('[data-router-back]'));
    await waitFor(() => view.host.querySelector('[data-location]').textContent === '/', 'MemoryRouter Back outcome');
    assert.ok(text(view.host).includes('Explore trading programs with'));
  } finally {
    await view.close();
  }
});

test('UI6 FAQ DOM expands, filters, and clears source state while retaining canonical public anchors', { concurrency: false }, async () => {
  const view = installDom('/faq');
  try {
    await view.render(routeElement('/faq', '/faq', pages.FAQ));
    await waitFor(() => view.host.querySelector('#faq-search'), 'FAQ form');
    const question = [...view.host.querySelectorAll('button')].find((node) => node.textContent.includes('What is MarketEdgePros?'));
    await click(question);
    assert.equal(question.getAttribute('aria-expanded'), 'true');
    const answer = view.host.querySelector(`#${question.getAttribute('aria-controls')}`);
    assert.equal(answer.hidden, false, 'the clicked source question exposes its answer');
    await changeValue(view.host.querySelector('#faq-search'), 'payout');
    await waitFor(() => text(view.host).includes('2 matching questions'), 'filtered FAQ');
    assert.equal(question.isConnected, false, 'changing a filter removes prior expanded DOM rather than retaining stale content');
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Clear search'));
    await waitFor(() => view.host.querySelector('#faq-search').value === '', 'cleared FAQ filter');
    // Answer panels now offer additional links; the public bottom actions remain
    // singular and must still resolve to the canonical destinations.
    const actions = [...view.host.querySelectorAll('section')].find((node) => node.querySelector('h2')?.textContent === 'Need more information?');
    assert.equal(anchors(actions, '/programs').length, 1);
    assert.equal(anchors(actions, '/contact').length, 1);
  } finally {
    await view.close();
  }
});

test('UI6 support DOM consumes only a synthetic public fixture, surfaces loading/error/empty states, and binds source links', { concurrency: false }, async () => {
  const view = installDom('/support');
  const restoreConsoleError = suppressExpectedFixtureConsoleError();
  const calls = [];
  const requests = [];
  let mode = 'loading';
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  globalThis.__ui6PublicApi = {
    get: async (endpoint, config = {}) => {
      calls.push(endpoint);
      requests.push({ endpoint, config });
      if (mode === 'loading') await pending;
      if (mode === 'error') throw new Error('synthetic support failure');
      return { data: { articles: [{ title: 'Synthetic help article', slug: 'synthetic-help', category: 'Getting Started', status: 'published' }] } };
    },
  };
  try {
    await view.render(routeElement('/support', '/support', pages.SupportHub));
    await waitFor(() => text(view.host).includes('Loading articles...'), 'support loading state');
    mode = 'success';
    release();
    await waitFor(() => text(view.host).includes('Synthetic help article'), 'support synthetic content');
    assert.deepEqual(calls, ['/support/articles']);
    assert.equal(anchors(view.host, '/support/synthetic-help').length, 1, 'published fixture has a real article Link');
    assert.equal(anchors(view.host, '/support/create-ticket').length, 2, 'both quick-link and CTA retain the recorded destination');
    assert.equal(anchors(view.host, '/faq').length, 1);
    assert.equal(view.host.querySelectorAll('a[target="_blank"]').length, 0, 'the unreachable external quick-link branch renders no active external control');
    await changeValue(view.host.querySelector('input[aria-label="Search help articles"]'), 'no match');
    await waitFor(() => text(view.host).includes('No articles match'), 'support empty filter state');
    await changeValue(view.host.querySelector('input[aria-label="Search help articles"]'), '');
    await waitFor(() => anchors(view.host, '/support/synthetic-help').length === 1, 'support cleared filter state');
    await click(anchors(view.host, '/support/synthetic-help')[0]);
    await waitFor(() => view.host.querySelector('[data-location]').textContent === '/support/synthetic-help', 'support article navigation');

    mode = 'error';
    await view.render(routeElement('/support', '/support', pages.SupportHub, 'support-error'));
    await waitFor(() => view.host.querySelector('[role="alert"]')?.textContent.includes('Articles could not be loaded. Please try again later.'), 'support read failure state');
    const requestsBeforeRetry = requests.length;
    mode = 'success';
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Try again'));
    await waitFor(() => text(view.host).includes('Synthetic help article'), 'support explicit retry result');
    assert.equal(requests.length, requestsBeforeRetry + 1, 'support failure retries only after the explicit action');
    assert.ok(requests.every(({ endpoint, config }) => endpoint === '/support/articles' && config.signal instanceof AbortSignal), 'all support fixture reads retain the abortable request contract');
  } finally {
    restoreConsoleError();
    delete globalThis.__ui6PublicApi;
    await view.close();
  }
});

test('UI6 support article DOM renders synthetic reads, safe failure navigation, dynamic related links, and a mail-client boundary', { concurrency: false }, async () => {
  const view = installDom('/support/synthetic-article');
  const restoreConsoleError = suppressExpectedFixtureConsoleError();
  const calls = [];
  let failed = false;
  globalThis.__ui6PublicApi = {
    get: async (endpoint, config) => {
      calls.push([endpoint, config]);
      if (failed) throw new Error('synthetic article failure');
      if (endpoint === '/support/articles/synthetic-article') return { data: { title: 'Synthetic Article', content: 'Safe fixture content', category: 'Getting Started', excerpt: 'Fixture excerpt' } };
      if (endpoint === '/support/articles') return { data: { articles: [{ slug: 'synthetic-article', title: 'Current' }, { slug: 'related-article', title: 'Related Article', excerpt: 'Related fixture' }] } };
      throw new Error(`unexpected synthetic endpoint ${endpoint}`);
    },
  };
  const render = (key) => view.render(React.createElement(MemoryRouter, { initialEntries: ['/support/synthetic-article'], key },
    React.createElement(React.Fragment, null,
      React.createElement(Routes, null,
        React.createElement(Route, { path: '/support/:slug', element: React.createElement(pages.Article) }),
        React.createElement(Route, { path: '/support', element: React.createElement('p', null, 'Support destination') }),
      ),
      React.createElement(LocationProbe),
    )));
  try {
    await render('article-success');
    await waitFor(() => text(view.host).includes('Synthetic Article'), 'article response');
    assert.equal(calls[0][0], '/support/articles/synthetic-article');
    assert.equal(calls[1][0], '/support/articles');
    assert.equal(anchors(view.host, '/support').length, 2, 'source back and CTA Links are concrete router anchors');
    assert.equal(anchors(view.host, '/support/related-article').length, 1, 'related fixture retains the dynamic source destination');
    assert.equal(anchors(view.host, 'mailto:info@marketedgepros.com').length, 1, 'mailto remains a client boundary, not an attempted send');
    await click(anchors(view.host, '/support')[0]);
    await waitFor(() => view.host.querySelector('[data-location]').textContent === '/support', 'article Back Link outcome');

    failed = true;
    await render('article-failure');
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'article error state');
    await click(anchors(view.host, '/support')[0]);
    await waitFor(() => view.host.querySelector('[data-location]').textContent === '/support', 'article failure return outcome');
  } finally {
    restoreConsoleError();
    delete globalThis.__ui6PublicApi;
    await view.close();
  }
});

test('UI6 blog DOM binds public synthetic reads to filtering, categories, pagination, retry, and router destinations', { concurrency: false }, async () => {
  const view = installDom('/blog');
  const restoreConsoleError = suppressExpectedFixtureConsoleError();
  const calls = [];
  let mode = 'loading';
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const post = { id: 7, slug: 'synthetic-post', title: 'Synthetic Post', excerpt: 'A fixture article', category: 'Education', published_at: '2026-10-12T00:00:00Z', reading_time: 3 };
  globalThis.__ui6PublicApi = {
    get: async (endpoint, config = {}) => {
      calls.push([endpoint, config]);
      if (endpoint === '/blog/posts') {
        if (mode === 'loading') await pending;
        if (mode === 'error') throw new Error('synthetic blog failure');
        return { data: { posts: [post], pagination: { page: config.params?.page ?? 1, per_page: 9, total_posts: 2, total_pages: 2 } } };
      }
      if (endpoint === '/blog/categories') return { data: { categories: [{ name: 'Education' }] } };
      if (endpoint === '/blog/featured') return { data: { posts: [post] } };
      throw new Error(`unexpected synthetic endpoint ${endpoint}`);
    },
  };
  const render = (key) => view.render(routeElement('/blog', '/blog', pages.Blog, key));
  try {
    await render('blog-loading');
    await waitFor(() => view.host.querySelector('[role="status"][aria-label="Loading posts"]'), 'blog loading state');
    mode = 'success';
    release();
    await waitFor(() => text(view.host).includes('Synthetic Post'), 'blog fixture content');
    await waitFor(() => anchors(view.host, '/blog/synthetic-post').length === 3, 'all blog source links');
    assert.equal(anchors(view.host, '/blog/synthetic-post').length, 3, 'title, read-more, and featured source Links are rendered');
    assert.equal(anchors(view.host, '/contact').length, 1, 'newsletter boundary points to the public contact page');

    const readsBeforeSearch = calls.filter(([endpoint]) => endpoint === '/blog/posts').length;
    await changeValue(view.host.querySelector('#blog-search'), 'missing');
    await waitFor(() => text(view.host).includes('No posts match your search on the currently loaded page.'), 'blog empty current-page search state');
    assert.equal(calls.filter(([endpoint]) => endpoint === '/blog/posts').length, readsBeforeSearch, 'current-page search filters already loaded posts without an additional request');
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Clear search'));
    await waitFor(() => text(view.host).includes('Synthetic Post'), 'blog clear search state');

    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Education'));
    await waitFor(() => calls.some(([endpoint, config]) => endpoint === '/blog/posts' && config.params?.category === 'Education'), 'category-bound public read');
    assert.equal([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Education').getAttribute('aria-pressed'), 'true');
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === '2'));
    await waitFor(() => calls.some(([endpoint, config]) => endpoint === '/blog/posts' && config.params?.page === 2 && config.params?.category === 'Education'), 'page-bound public read');
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === 'All'));
    await waitFor(() => calls.filter(([endpoint, config]) => endpoint === '/blog/posts' && config.params?.page === 1 && !('category' in config.params)).length >= 2, 'all-category public read');
    await click(anchors(view.host, '/blog/synthetic-post')[0]);
    await waitFor(() => view.host.querySelector('[data-location]').textContent === '/blog/synthetic-post', 'blog post Link outcome');

    mode = 'error';
    await render('blog-error');
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'blog load failure state');
    mode = 'success';
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Try again'));
    await waitFor(() => text(view.host).includes('Synthetic Post'), 'blog retry acknowledged by rendered synthetic result');
    const retry = calls.filter(([endpoint]) => endpoint === '/blog/posts').at(-1);
    assert.deepEqual(retry[1].params, { page: 1, per_page: 9 }, 'retry preserves the active page and unfiltered current category request');
    assert.ok(retry[1].signal instanceof AbortSignal, 'retry remains abortable');
  } finally {
    restoreConsoleError();
    delete globalThis.__ui6PublicApi;
    await view.close();
  }
});

test('UI6 blog post DOM keeps social buttons as synthetic external-client boundaries and executes both Back outcomes', { concurrency: false }, async () => {
  const view = installDom('/blog/synthetic-post');
  const restoreConsoleError = suppressExpectedFixtureConsoleError();
  const calls = [];
  const opened = [];
  let missing = false;
  globalThis.__ui6PublicApi = {
    get: async (endpoint, config) => {
      calls.push([endpoint, config]);
      if (endpoint === '/blog/posts/synthetic-post') {
        if (missing) throw { response: { status: 404 } };
        return { data: { id: 7, title: 'Synthetic Post', content: '<p>Fixture content</p>', category: 'Education', created_at: '2026-10-12T00:00:00Z', tags: ['fixture'] } };
      }
      if (endpoint === '/blog/posts') return { data: { posts: [{ id: 8, slug: 'related-post', title: 'Related Post', excerpt: 'Fixture related', category: 'Education' }] } };
      throw new Error(`unexpected synthetic endpoint ${endpoint}`);
    },
  };
  const originalOpen = view.dom.window.open;
  view.dom.window.open = (...args) => { opened.push(args); return null; };
  const render = (key) => view.render(React.createElement(MemoryRouter, { initialEntries: ['/blog/synthetic-post'], key },
    React.createElement(React.Fragment, null,
      React.createElement(Routes, null,
        React.createElement(Route, { path: '/blog/:slug', element: React.createElement(pages.BlogPost) }),
        React.createElement(Route, { path: '/blog', element: React.createElement('p', null, 'Blog destination') }),
      ),
      React.createElement(LocationProbe),
    )));
  try {
    await render('post-success');
    await waitFor(() => text(view.host).includes('Synthetic Post'), 'blog post fixture');
    for (const label of ['Share on Facebook', 'Share on X/Twitter', 'Share on LinkedIn']) await click(view.host.querySelector(`button[aria-label="${label}"]`));
    assert.equal(opened.length, 3, 'each social control only delegates to window.open in the synthetic DOM');
    assert.match(opened[0][0], /^https:\/\/www\.facebook\.com\/sharer\//);
    assert.match(opened[1][0], /^https:\/\/twitter\.com\/intent\/tweet/);
    assert.match(opened[2][0], /^https:\/\/www\.linkedin\.com\/sharing\//);
    assert.equal(anchors(view.host, '/blog/related-post').length, 1, 'related post Link holds the dynamic source destination');
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.includes('Back to Blog')));
    await waitFor(() => view.host.querySelector('[data-location]').textContent === '/blog', 'normal Back outcome');

    missing = true;
    await render('post-missing');
    await waitFor(() => text(view.host).includes('Blog post not found'), 'not-found state');
    await click([...view.host.querySelectorAll('button')].find((node) => node.textContent.includes('Back to Blog')));
    await waitFor(() => view.host.querySelector('[data-location]').textContent === '/blog', 'failure Back outcome');
    assert.ok(calls.every(([endpoint]) => endpoint.startsWith('/blog/')), 'all calls stayed on supplied synthetic blog endpoints');
  } finally {
    restoreConsoleError();
    view.dom.window.open = originalOpen;
    delete globalThis.__ui6PublicApi;
    await view.close();
  }
});

test('UI6 public catalog and SEO DOM show explicit unavailable payment state and real head link targets without provider access', { concurrency: false }, async () => {
  const view = installDom('/free-course');
  try {
    for (const [fixture, expected] of [
      [{ loading: true, error: null, data: [] }, 'loading'],
      [{ loading: false, error: new Error('synthetic'), data: [] }, 'error'],
      [{ loading: false, error: null, data: [] }, 'empty'],
      [{ loading: false, error: null, data: [{ id: 1, name: 'Synthetic', terms: { type: 'one-phase' } }] }, 'ready'],
    ]) {
      globalThis.__ui6Catalog = fixture;
      await view.render(routeElement('/free-course', '/free-course', pages.CatalogPreview, `catalog-${expected}`));
      await waitFor(() => view.host.querySelector('[data-catalog-state], [data-catalog-card]'), `catalog ${expected}`);
      if (expected === 'ready') assert.ok(view.host.querySelector('[data-catalog-card="1"]'));
      else assert.equal(view.host.querySelector('[data-catalog-state]').getAttribute('data-catalog-state'), expected);
      assert.ok(view.host.querySelector('[data-payment-boundary]'), 'catalog visibly preserves the unavailable payment boundary');
      assert.equal(anchors(view.host, '/programs').length, 1);
    }

    await view.render(React.createElement(HelmetProvider, null, React.createElement(pages.SEO, { title: 'Fixture SEO', canonical: '/free-course' })));
    await waitFor(() => document.head.querySelector('link[rel="canonical"]'), 'canonical head element');
    assert.equal(document.head.querySelector('link[rel="canonical"]').getAttribute('href'), 'https://public.example.invalid/free-course');
    assert.equal(document.head.querySelector('link[rel="icon"]').getAttribute('href'), '/favicon.ico');
    assert.equal(document.head.querySelector('link[rel="apple-touch-icon"]').getAttribute('href'), '/apple-touch-icon.png');
  } finally {
    delete globalThis.__ui6Catalog;
    await view.close();
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
