import React from 'react';
import { ArrowUpRight, Compass, Layers3, ShieldCheck } from 'lucide-react';
import Layout from '../components/layout/Layout';

const principles = [
  {
    icon: Compass,
    title: 'Explore with clarity',
    description: 'Use the program catalog to review the information currently listed for each program.',
  },
  {
    icon: Layers3,
    title: 'Details are program-specific',
    description: 'Program descriptions and terms can differ. Check the selected program page for its available details.',
  },
  {
    icon: ShieldCheck,
    title: 'Review before you decide',
    description: 'Read the relevant program information and applicable site policies before taking any next step.',
  },
];

export default function AboutUs() {
  return (
    <Layout>
      <main className="min-h-screen overflow-hidden bg-[#071426] text-slate-100">
        <section aria-labelledby="about-title" className="relative isolate border-b border-cyan-300/10">
          <div aria-hidden="true" className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_72%_18%,rgba(6,182,212,0.18),transparent_42%),linear-gradient(135deg,#071426_0%,#0b1c33_55%,#071426_100%)]" />
          <div className="mx-auto max-w-6xl px-6 py-24 sm:px-8 sm:py-32">
            <p className="mb-5 text-sm font-semibold uppercase tracking-[0.24em] text-cyan-300">About MarketEdgePros</p>
            <h1 id="about-title" className="mep-heading max-w-4xl text-4xl font-bold leading-tight tracking-tight text-white sm:text-6xl">
              A clear place to explore our programs.
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-300 sm:text-xl">
              MarketEdgePros presents program information in an online catalog. This page introduces the company site; current program details are shown on the relevant program pages.
            </p>
            <a
              href="/programs"
              className="mep-primary mt-9 inline-flex min-h-12 items-center gap-2 px-6 py-3 font-semibold text-[#071426] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#071426] motion-reduce:transition-none"
            >
              Browse programs <ArrowUpRight aria-hidden="true" className="h-5 w-5" />
            </a>
          </div>
        </section>

        <section aria-labelledby="approach-title" className="mx-auto max-w-6xl px-6 py-20 sm:px-8 sm:py-24">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">How to use this site</p>
            <h2 id="approach-title" className="mep-heading mt-4 text-3xl font-bold tracking-tight text-white sm:text-4xl">Start with the details that matter.</h2>
            <p className="mt-5 text-base leading-7 text-slate-300">
              The catalog is the place to review the programs currently listed. Availability and displayed terms are specific to each program and may change; this overview does not establish program or payment terms.
            </p>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-3">
            {principles.map(({ icon: Icon, title, description }) => (
              <article key={title} className="mep-panel rounded-2xl border bg-[#0d2038]/80 p-7 shadow-lg shadow-black/10">
                <div className="mb-6 inline-flex rounded-xl border border-cyan-300/20 bg-cyan-300/10 p-3 text-cyan-300">
                  <Icon aria-hidden="true" className="h-6 w-6" />
                </div>
                <h3 className="text-xl font-semibold text-white">{title}</h3>
                <p className="mt-3 leading-7 text-slate-300">{description}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="next-title" className="border-t border-cyan-300/10 bg-[#0a1b31]">
          <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-16 sm:px-8 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 id="next-title" className="mep-heading text-2xl font-bold text-white sm:text-3xl">Want to compare the listed options?</h2>
              <p className="mt-3 max-w-2xl leading-7 text-slate-300">Open the catalog to see the information currently available for each program.</p>
            </div>
            <a
              href="/programs"
              className="inline-flex min-h-12 shrink-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/50 px-5 py-3 font-semibold text-cyan-200 transition-colors hover:border-cyan-200 hover:bg-cyan-300/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0a1b31] motion-reduce:transition-none"
            >
              View program catalog <ArrowUpRight aria-hidden="true" className="h-5 w-5" />
            </a>
          </div>
        </section>
      </main>
    </Layout>
  );
}
