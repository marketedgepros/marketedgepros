import React from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/layout/Layout';
import { ArrowRight, BookOpen, ShieldCheck } from 'lucide-react';

function TradingRules() {
  return (
    <Layout>
      <div className="mep-screen min-h-screen text-white">
        <section className="relative overflow-hidden border-b border-cyan-400/15 bg-gradient-to-br from-slate-950 via-blue-950/50 to-slate-900">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(34,211,238,0.12),transparent_55%)]" />
          <div className="relative mx-auto max-w-5xl px-5 py-16 sm:px-8 sm:py-24">
            <p className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-cyan-300">Trading information</p>
            <h1 className="mep-heading max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl">Trading rules and program terms</h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-slate-300">
              Trading requirements may differ by program. Review the settings and terms shown for the specific program you are considering.
            </p>
          </div>
        </section>

        <section className="mx-auto max-w-5xl px-5 py-12 sm:px-8 sm:py-16" aria-labelledby="program-settings-heading">
          <div className="mep-panel rounded-2xl border p-6 shadow-xl shadow-black/20 sm:p-9">
            <div className="flex items-start gap-4">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cyan-400/10 text-cyan-300">
                <ShieldCheck className="h-6 w-6" aria-hidden="true" />
              </span>
              <div>
                <h2 id="program-settings-heading" className="mep-heading text-2xl font-semibold">Check the program details</h2>
                <p className="mt-3 leading-relaxed text-slate-300">
                  Program-specific settings are displayed in the catalog and on each program details page. Those displayed settings are not a blanket set of live trading rules for every program; this page does not establish additional approved rules.
                </p>
                <Link to="/programs" className="mep-primary mt-6 inline-flex min-h-11 items-center gap-2 px-5 py-2.5 font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300">
                  Browse programs <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </div>
            </div>
          </div>

          <aside className="mep-panel mt-7 rounded-xl border p-6 sm:p-7" aria-labelledby="availability-heading">
            <div className="flex items-center gap-3">
              <BookOpen className="h-5 w-5 text-cyan-300" aria-hidden="true" />
              <h2 id="availability-heading" className="mep-heading text-lg font-semibold">General rules availability</h2>
            </div>
            <p className="mt-3 leading-relaxed text-slate-300">
              No general live trading rules are published here as approved policy. Risk limits, strategy restrictions, enforcement, and any consequences require confirmation through the applicable program terms; no additional thresholds or sanctions are stated on this page.
            </p>
          </aside>
        </section>
      </div>
    </Layout>
  );
}

export default TradingRules;
