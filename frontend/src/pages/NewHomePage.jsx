import React from 'react';
import SchemaMarkup from "../components/seo/SchemaMarkup";
import { Link } from 'react-router-dom';
import CatalogPreview from '../components/programs/CatalogPreview';
import Layout from '../components/layout/Layout';

const NewHomePage = () => (
  <Layout>
    <div className="min-h-screen overflow-hidden scroll-smooth bg-slate-950 text-white">
      <SchemaMarkup />
      <section className="relative isolate flex min-h-[76vh] items-center overflow-hidden">
        <div aria-hidden="true" className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top_right,_rgba(8,145,178,0.28),_transparent_55%),linear-gradient(140deg,#071426_0%,#0b1730_55%,#06111f_100%)]" />
        <div aria-hidden="true" className="absolute -right-24 top-16 h-80 w-80 rounded-full border border-cyan-300/10" />
        <div className="mx-auto grid w-full max-w-7xl gap-12 px-6 py-24 lg:grid-cols-[1.2fr_.8fr] lg:items-center lg:px-8">
          <div>
            <p className="mb-6 text-sm font-semibold uppercase tracking-[0.24em] text-cyan-300">MarketEdgePros · Trading programs</p>
            <h1 className="max-w-3xl text-5xl font-bold leading-tight tracking-tight sm:text-6xl">Explore trading programs with <span className="text-cyan-300">clear information.</span></h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-300">Compare the programs currently shown in our catalog. Review each program’s displayed price and terms before requesting a quote.</p>
            <div className="mt-9 flex flex-wrap gap-4">
              <Link to="/programs" className="rounded-lg bg-cyan-400 px-6 py-3 font-semibold text-slate-950 transition-colors hover:bg-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:ring-offset-2 focus:ring-offset-slate-950">Explore programs</Link>
              <Link to="/how-it-works" className="rounded-lg border border-slate-500 px-6 py-3 font-semibold text-white transition-colors hover:border-cyan-300 hover:text-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-200">How it works</Link>
            </div>
            <p className="mt-6 max-w-2xl text-sm leading-6 text-slate-400">Catalog details may vary by program. A quote is not a payment, funded account, or account activation; payments are not enabled.</p>
          </div>
          <aside className="rounded-2xl border border-cyan-200/20 bg-slate-900/70 p-8 shadow-2xl shadow-cyan-950/30">
            <div className="mb-5 h-1 w-14 rounded bg-cyan-400" />
            <h2 className="text-2xl font-semibold">Start with the published details</h2>
            <ol className="mt-6 space-y-5 text-slate-300">
              <li className="flex gap-4"><span className="font-mono text-cyan-300">01</span><span>Browse programs available in the catalog.</span></li>
              <li className="flex gap-4"><span className="font-mono text-cyan-300">02</span><span>Check the displayed price and program-specific terms.</span></li>
              <li className="flex gap-4"><span className="font-mono text-cyan-300">03</span><span>Request a quote if that option is available.</span></li>
            </ol>
          </aside>
        </div>
      </section>

      <section id="programs" className="border-y border-white/5 bg-slate-900/50 py-20">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div className="mb-10 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
            <div><p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">Current catalog</p><h2 className="mt-3 text-3xl font-bold sm:text-4xl">Review available programs</h2></div>
            <p className="max-w-xl text-sm leading-6 text-slate-400">Only catalog information returned for display is shown here. Availability of programs and their terms depends on the current catalog data.</p>
          </div>
          <CatalogPreview />
        </div>
      </section>

      <section id="how-it-works" className="mx-auto max-w-7xl px-6 py-20 lg:px-8">
        <div className="grid gap-10 md:grid-cols-[.7fr_1.3fr]">
          <div><p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">A transparent starting point</p><h2 className="mt-3 text-3xl font-bold">How to explore</h2></div>
          <div className="grid gap-5 sm:grid-cols-3">
            {[['Browse','Open the catalog to see the programs currently listed.'],['Review','Read the displayed price and terms for the specific program.'],['Understand','A quote does not itself take payment or activate an account.']].map(([title, text], index) => <article key={title} className="rounded-xl border border-slate-700 bg-slate-900/60 p-6"><p className="font-mono text-sm text-cyan-300">0{index + 1}</p><h3 className="mt-4 text-lg font-semibold">{title}</h3><p className="mt-2 text-sm leading-6 text-slate-400">{text}</p></article>)}
          </div>
        </div>
      </section>

      <section className="border-t border-white/5 bg-[#081426] py-16">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 sm:flex-row sm:items-center sm:justify-between lg:px-8">
          <div><h2 className="text-2xl font-bold">Questions before you decide?</h2><p className="mt-2 text-slate-400">Review the available help and program information.</p></div>
          <div className="flex flex-wrap gap-5"><Link to="/faq" className="font-semibold text-cyan-300 hover:text-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-200">Read FAQs</Link><Link to="/support" className="font-semibold text-cyan-300 hover:text-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-200">Visit support</Link><Link to="/programs" className="font-semibold text-cyan-300 hover:text-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-200">Browse programs</Link></div>
        </div>
      </section>
    </div>
  </Layout>
);

export default NewHomePage;
