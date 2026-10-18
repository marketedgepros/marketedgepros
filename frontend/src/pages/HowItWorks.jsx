import React from 'react';
import { ArrowUpRight, BookOpen, ClipboardList, Compass, ShieldCheck } from 'lucide-react';
import Layout from '../components/layout/Layout';

const steps = [
  {
    number: '01',
    icon: Compass,
    title: 'Explore the current catalog',
    description: 'Compare the programs and account options currently listed. Availability and details may change.',
  },
  {
    number: '02',
    icon: BookOpen,
    title: 'Review the program details',
    description: 'Before choosing, read that program’s displayed objectives, account size, price, terms, and trading rules.',
  },
  {
    number: '03',
    icon: ClipboardList,
    title: 'Consider the next steps',
    description: 'If you decide to continue, review the information presented for the selected program. Participation or approval is not guaranteed.',
  },
  {
    number: '04',
    icon: ShieldCheck,
    title: 'Check applicable terms',
    description: 'Any later account arrangements, trading conditions, or withdrawal terms must be confirmed for the specific program; do not assume they are available.',
  },
];

export default function HowItWorks() {
  return (
    <Layout>
      <main className="mep-screen min-h-screen text-slate-100">
        <section className="relative overflow-hidden border-b border-cyan-300/10 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950/50">
          <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-28 h-96 w-96 rounded-full bg-cyan-400/10 blur-3xl" />
          <div className="relative mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-28">
            <p className="mb-5 text-sm font-semibold uppercase tracking-[0.22em] text-cyan-300">MarketEdgePros · Overview</p>
            <h1 className="mep-heading max-w-3xl text-4xl font-bold tracking-tight text-white sm:text-6xl">How it works</h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300 sm:text-xl">
              A practical guide to exploring available programs and reviewing their terms before making a decision.
            </p>
            <a href="/programs" className="mep-primary mt-9 inline-flex min-h-12 items-center gap-2 border border-cyan-300/50 px-6 py-3 font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-200">
              Browse current programs <ArrowUpRight aria-hidden="true" className="h-5 w-5" />
            </a>
          </div>
        </section>

        <section aria-labelledby="process-heading" className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
          <div className="mb-10 max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">The evaluation journey</p>
            <h2 id="process-heading" className="mep-heading mt-3 text-3xl font-bold text-white sm:text-4xl">Four points to review</h2>
          </div>
          <ol className="grid gap-5 md:grid-cols-2">
            {steps.map(({ number, icon: Icon, title, description }) => (
              <li key={number} className="rounded-2xl border border-slate-700/80 bg-slate-900/80 p-6 shadow-xl shadow-black/10 sm:p-8">
                <div className="flex items-start gap-4">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/10 text-cyan-200">
                    <Icon aria-hidden="true" className="h-6 w-6" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold tracking-widest text-cyan-300">{number}</p>
                    <h3 className="mt-1 text-xl font-semibold text-white">{title}</h3>
                    <p className="mt-3 leading-7 text-slate-300">{description}</p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="border-t border-slate-800 bg-slate-900/60">
          <div className="mx-auto flex max-w-6xl flex-col gap-5 px-5 py-12 sm:px-8 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="mep-heading text-2xl font-bold text-white">Terms are program-specific</h2>
              <p className="mt-2 max-w-2xl leading-7 text-slate-300">Use the current catalog and each program’s details as your reference. This overview does not promise evaluation outcomes, funding, trading-platform access, profit shares, or withdrawals.</p>
            </div>
            <a href="/programs" className="inline-flex min-h-11 w-fit items-center gap-2 rounded-lg border border-cyan-300/40 px-5 py-2.5 font-semibold text-cyan-200 transition-colors hover:bg-cyan-300/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-200">
              View program details <ArrowUpRight aria-hidden="true" className="h-4 w-4" />
            </a>
          </div>
        </section>
      </main>
    </Layout>
  );
}
