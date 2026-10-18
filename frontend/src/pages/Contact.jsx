import React from 'react';
import { ArrowRight, BookOpen, CircleHelp, Compass } from 'lucide-react';
import Layout from '../components/layout/Layout';

const contactOptions = [
  {
    href: '/support',
    icon: CircleHelp,
    title: 'Browse support',
    description: 'Explore the support area for available help and guidance.'
  },
  {
    href: '/faq',
    icon: BookOpen,
    title: 'Read the FAQ',
    description: 'Review answers to frequently asked questions.'
  },
  {
    href: '/programs',
    icon: Compass,
    title: 'View programs',
    description: 'See the programs currently presented in the catalog.'
  }
];

export default function Contact() {
  return (
    <Layout>
      <main className="mep-screen min-h-screen text-slate-100">
        <section aria-labelledby="contact-title" className="relative isolate overflow-hidden border-b border-cyan-300/10">
          <div aria-hidden="true" className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,rgba(8,145,178,0.18),transparent_65%)]" />
          <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-28">
            <p className="mb-4 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">Contact</p>
            <h1 id="contact-title" className="mep-heading max-w-3xl text-4xl font-bold tracking-tight text-white sm:text-6xl">How can we help?</h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
              Choose a destination below to explore the information and support options available on this site.
            </p>
          </div>
        </section>

        <section aria-labelledby="options-title" className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
          <div className="mb-8 max-w-2xl">
            <h2 id="options-title" className="mep-heading text-2xl font-semibold text-white sm:text-3xl">Explore available options</h2>
            <p className="mt-3 leading-7 text-slate-300">
              Direct message submission is not available on this page. No message or personal details are submitted here.
            </p>
          </div>
          <ul className="grid gap-5 md:grid-cols-3">
            {contactOptions.map(({ href, icon: Icon, title, description }) => (
              <li key={href}>
                <a href={href} className="group flex h-full flex-col rounded-2xl border border-slate-700 bg-slate-900/80 p-6 transition-colors hover:border-cyan-400/70 hover:bg-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 motion-reduce:transition-none">
                  <Icon aria-hidden="true" className="mb-5 h-6 w-6 text-cyan-300" />
                  <span className="text-lg font-semibold text-white">{title}</span>
                  <span className="mt-2 flex-1 leading-6 text-slate-300">{description}</span>
                  <span className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-cyan-300">
                    Open page <ArrowRight aria-hidden="true" className="h-4 w-4 transition-transform group-hover:translate-x-1 motion-reduce:transition-none" />
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </Layout>
  );
}
