import React from 'react';
import SchemaMarkup from "../components/seo/SchemaMarkup";
import { Link } from 'react-router-dom';
import CatalogPreview from '../components/programs/CatalogPreview';
import Layout from '../components/layout/Layout';
import useScrollReveal from '../hooks/useScrollReveal';
import useAmbientMotion from '../hooks/useAmbientMotion';
import PlatformShowcase from '../components/visual/PlatformShowcase';
import '../components/visual/homeMotion.css';

const NewHomePage = () => {
  const ambient = useAmbientMotion();
  const globeMotion = useAmbientMotion();
  const heroCopy = useScrollReveal();
  const heroArtwork = useScrollReveal();
  const heroDetails = useScrollReveal();
  const catalogIntro = useScrollReveal();
  const explorationSteps = useScrollReveal();
  const supportPanel = useScrollReveal();

  return (
    <Layout>
      <div data-visual-paused={ambient.reduced ? "true" : "false"} className="mep-screen home-motion min-h-screen overflow-hidden scroll-smooth text-white">
      <SchemaMarkup />
      <section ref={ambient.ref} data-motion-running={ambient.running ? "true" : "false"} className="premium-hero relative isolate flex min-h-[76vh] items-center overflow-hidden">
        <div aria-hidden="true" className="home-motion__hero-background pointer-events-none absolute inset-0">
          <img src="/images/abstract-trading-flow.webp" alt="" width="1536" height="1024" fetchpriority="high" decoding="async" className="h-full w-full object-cover opacity-[0.65]" />
          <div className="absolute inset-0 bg-gradient-to-r from-slate-950/90 via-slate-950/65 to-slate-950/30" />
        </div>
        <div aria-hidden="true" className="premium-hero__grid pointer-events-none absolute inset-0" />
        <div aria-hidden="true" className="premium-hero__beam pointer-events-none absolute inset-0" />
        <div aria-hidden="true" className="home-motion__ambient-ring pointer-events-none absolute -right-24 top-16 h-80 w-80 rounded-full border border-cyan-300/10" />
        <div className="home-motion__content mx-auto grid w-full max-w-7xl gap-12 px-6 py-24 lg:grid-cols-[1.2fr_.8fr] lg:items-center lg:px-8">
          <div ref={heroCopy.ref} className={heroCopy.className}>
            <p className="mb-6 text-sm font-semibold uppercase tracking-[0.24em] text-cyan-300">MarketEdgePros · Trading programs</p>
            <h1 className="mep-heading premium-hero__title max-w-3xl text-5xl font-bold leading-tight tracking-tight sm:text-6xl">Explore trading programs with <span className="text-cyan-300">clear information.</span></h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-300">Compare the programs currently shown in our catalog. Review each program’s displayed price and terms before requesting a quote.</p>
            <div className="mt-9 flex flex-wrap gap-4">
              <Link to="/programs" className="mep-primary px-6 py-3 font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950">Explore programs</Link>
              <Link to="/how-it-works" className="rounded-lg border border-slate-500 px-6 py-3 font-semibold text-white transition-colors hover:border-cyan-300 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">How it works</Link>
            </div>
            <p className="mt-6 max-w-2xl text-sm leading-6 text-slate-400">Catalog details may vary by program. A quote is not a payment, funded account, or account activation. Payment availability is checked separately for your account in checkout.</p>
          </div>
          <div className="min-w-0 space-y-5">
            <figure ref={heroArtwork.ref} className={`${heroArtwork.className} home-motion__panel home-motion__image-panel premium-hero__artwork overflow-hidden rounded-2xl border border-cyan-200/15 bg-slate-950/70 shadow-2xl shadow-cyan-950/30`}>
              <img src="/images/hero-trading-3d.webp" alt="Decorative illustration of trading charts on three screens" width="1536" height="1024" decoding="async" className="h-auto w-full object-contain" />
              <figcaption className="border-t border-cyan-200/10 px-5 py-3 text-xs leading-5 text-slate-300">Illustrative artwork, not a live platform view or account performance.</figcaption>
            </figure>
            <aside ref={heroDetails.ref} className={`${heroDetails.className} home-motion__panel rounded-2xl border border-cyan-200/20 bg-slate-900/85 p-6`}>
              <div className="mb-4 h-1 w-14 rounded bg-cyan-400" />
              <h2 className="mep-heading text-xl font-semibold">Start with the published details</h2>
              <ol className="mt-5 space-y-4 text-sm leading-6 text-slate-300">
                <li className="flex gap-4"><span className="font-mono text-cyan-300">01</span><span>Browse programs available in the catalog.</span></li>
                <li className="flex gap-4"><span className="font-mono text-cyan-300">02</span><span>Check the displayed price and program-specific terms.</span></li>
                <li className="flex gap-4"><span className="font-mono text-cyan-300">03</span><span>Request a quote if that option is available.</span></li>
              </ol>
            </aside>
          </div>
        </div>
      </section>

      <section id="programs" className="border-y border-white/5 bg-slate-900/50 py-20">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div ref={catalogIntro.ref} className={`${catalogIntro.className} mb-10 flex flex-col justify-between gap-5 sm:flex-row sm:items-end`}>
            <div><p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">Current catalog</p><h2 className="mep-heading mt-3 text-3xl font-bold sm:text-4xl">Review available programs</h2></div>
            <p className="max-w-xl text-sm leading-6 text-slate-400">Only catalog information returned for display is shown here. Availability of programs and their terms depends on the current catalog data.</p>
          </div>
          <CatalogPreview interactive />
        </div>
      </section>

      <PlatformShowcase />

      <section id="how-it-works" className="mx-auto max-w-7xl px-6 py-20 lg:px-8">
        <div className="grid gap-10 md:grid-cols-[.7fr_1.3fr]">
          <div><p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">A transparent starting point</p><h2 className="mep-heading mt-3 text-3xl font-bold">How to explore</h2></div>
          <div ref={explorationSteps.ref} className={`${explorationSteps.className} grid gap-5 sm:grid-cols-3`}>
            {[['Browse','Open the catalog to see the programs currently listed.'],['Review','Read the displayed price and terms for the specific program.'],['Understand','A quote does not itself take payment or activate an account.']].map(([title, text], index) => <article key={title} className="mep-panel home-motion__panel rounded-xl border p-6"><p className="font-mono text-sm text-cyan-300">0{index + 1}</p><h3 className="mt-4 text-lg font-semibold">{title}</h3><p className="mt-2 text-sm leading-6 text-slate-400">{text}</p></article>)}
          </div>
        </div>
      </section>

      <section id="home-help" ref={globeMotion.ref} data-motion-running={globeMotion.running ? "true" : "false"} className="home-help-globe border-t border-white/5" aria-labelledby="home-help-heading">
        <div aria-hidden="true" className="home-help-globe__scene">
          <div className="home-help-globe__light" />
          <div className="home-help-globe__orbit"><img src="/images/stats-globe-hologram.webp" alt="" width="1024" height="1024" loading="lazy" decoding="async" className="home-help-globe__image" /></div>
        </div>
        <div ref={supportPanel.ref} className={`${supportPanel.className} home-help-globe__copy mx-auto max-w-4xl px-6 text-center lg:px-8`}>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">Clarity before commitment</p>
          <h2 id="home-help-heading" className="mep-heading mt-4 text-3xl font-bold tracking-tight sm:text-4xl">Questions before you decide?</h2>
          <p className="mt-4 text-base leading-relaxed text-slate-300 sm:text-lg">Review the available help and program information.</p>
          <div className="mt-7 flex flex-wrap justify-center gap-x-6 gap-y-3">
            <Link to="/faq" className="inline-flex min-h-11 items-center rounded-lg px-2 font-semibold text-cyan-300 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">Read FAQs</Link>
            <Link to="/support" className="inline-flex min-h-11 items-center rounded-lg px-2 font-semibold text-cyan-300 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">Visit support</Link>
            <Link to="/programs" className="inline-flex min-h-11 items-center rounded-lg px-2 font-semibold text-cyan-300 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">Browse programs</Link>
          </div>
        </div>
      </section>
      </div>
    </Layout>
  );
};

export default NewHomePage;
