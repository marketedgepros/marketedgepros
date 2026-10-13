import React from 'react';
import Layout from '../components/layout/Layout';
import { Briefcase, ArrowRight } from 'lucide-react';

function Careers() {
  return (
    <Layout>
      <main className="mep-screen min-h-screen text-slate-100">
        <section className="relative overflow-hidden border-b border-cyan-400/15 bg-gradient-to-br from-slate-950 via-blue-950/50 to-slate-950">
          <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl" aria-hidden="true" />
          <div className="relative mx-auto max-w-5xl px-6 py-20 sm:py-28">
            <p className="mb-5 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">Careers</p>
            <h1 className="mep-heading max-w-3xl text-4xl font-bold leading-tight tracking-tight sm:text-6xl">Build thoughtful tools for traders.</h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
              Explore opportunities to contribute your skills and perspective to our product.
            </p>
          </div>
        </section>

        <section className="mx-auto max-w-5xl px-6 py-16 sm:py-20" aria-labelledby="open-positions">
          <div className="mep-panel max-w-3xl rounded-2xl border p-7 shadow-xl shadow-black/20 sm:p-10">
            <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-xl bg-cyan-400/10 text-cyan-300">
              <Briefcase className="h-6 w-6" aria-hidden="true" />
            </div>
            <h2 id="open-positions" className="mep-heading text-2xl font-semibold tracking-tight sm:text-3xl">Open positions</h2>
            <p className="mt-4 text-base leading-7 text-slate-300">
              Current openings and application details are not published on this page. Please check our <a href="/contact" className="rounded-sm font-medium text-cyan-300 underline decoration-cyan-300/50 underline-offset-4 transition-colors hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">contact page</a> for available support options.
            </p>
            <a href="/contact" className="mt-7 inline-flex items-center gap-2 rounded-lg border border-cyan-300/40 px-5 py-3 font-semibold text-cyan-200 transition-colors hover:border-cyan-200 hover:bg-cyan-300/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
              Visit contact page <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </a>
          </div>
        </section>
      </main>
    </Layout>
  );
}

export default Careers;
