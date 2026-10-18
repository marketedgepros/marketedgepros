import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { url: 'https://synthetic.invalid/blog/alpha' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
window.scrollTo = () => {};
const { createRoot } = await import('react-dom/client');
const sourceFile = new URL('../src/pages/BlogPost.jsx', import.meta.url);
let source = fs.readFileSync(sourceFile, 'utf8');
source = source.replace("import { useParams, Link, useNavigate } from 'react-router-dom';", "const useParams=()=>({slug:globalThis.__blogSlug}); const useNavigate=()=>()=>{}; const Link=({children,to})=><a href={to}>{children}</a>;")
  .replace("import Layout from '../components/layout/Layout';", "const Layout=({children})=>{React.useLayoutEffect(()=>{globalThis.__blogCommits.push(document.body.textContent);}); return <main>{children}</main>;};")
  .replace("import SEO from '../components/SEO';", 'const SEO=()=>null;')
  .replace('import api from "../services/api";', 'const api={get:(...args)=>globalThis.__blogRead(...args)};');
const { code } = await transformWithEsbuild(source, sourceFile.pathname, { loader: 'jsx', jsx: 'automatic' });
const target = new URL(`.remediation-blog-route-${process.pid}.mjs`, import.meta.url);
fs.writeFileSync(target, "import React from 'react';\n" + code);
let BlogPost;
try { BlogPost = (await import(pathToFileURL(target.pathname).href)).default; }
finally { fs.rmSync(target, { force: true }); }

function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }

test('BlogPost never commits alpha content under beta slug before its passive load effect; related reads and prior errors cannot revive alpha', async () => {
  const reads = []; const pending = new Map();
  globalThis.__blogSlug = 'alpha'; globalThis.__blogCommits = [];
  globalThis.__blogRead = (url, options) => { const d = deferred(); pending.set(url, d); reads.push({url, options}); return d.promise; };
  const root = createRoot(document.getElementById('root'));
  try {
    await act(async () => root.render(React.createElement(BlogPost)));
    await act(async () => pending.get('/blog/posts/alpha').resolve({ data: { id:1, title:'ALPHA PRIVATE FIXTURE', content:'<p>Alpha body</p>', category:'education', tags:[], created_at:'2026-10-13T00:00:00Z' } }));
    assert.match(document.body.textContent, /ALPHA PRIVATE FIXTURE/);
    const oldRelated = pending.get('/blog/posts');
    globalThis.__blogCommits = []; globalThis.__blogSlug = 'beta';
    await act(async () => root.render(React.createElement(BlogPost)));
    assert.ok(globalThis.__blogCommits.length > 0);
    assert.ok(globalThis.__blogCommits.every((text) => !text.includes('ALPHA PRIVATE FIXTURE')), 'No committed frame may show the old post under the new slug');
    assert.match(document.body.textContent, /Loading article/);
    assert.equal(reads.find((r)=>r.url==='/blog/posts/alpha').options.signal.aborted,true);
    await act(async () => oldRelated.resolve({data:{posts:[{id:99,title:'OLD RELATED FIXTURE',slug:'old'}]}}));
    assert.doesNotMatch(document.body.textContent, /OLD RELATED FIXTURE|ALPHA PRIVATE FIXTURE/);
    await act(async () => pending.get('/blog/posts/beta').resolve({data:{id:2,title:'BETA FIXTURE',content:'<p>Beta body</p>',tags:[],created_at:'2026-10-13T00:00:00Z'}}));
    assert.match(document.body.textContent,/BETA FIXTURE/);
    assert.doesNotMatch(document.body.textContent,/ALPHA PRIVATE FIXTURE|OLD RELATED FIXTURE/);
  } finally {
    await act(async()=>root.unmount());
    delete globalThis.__blogSlug; delete globalThis.__blogCommits; delete globalThis.__blogRead;
    dom.window.close();
  }
});
