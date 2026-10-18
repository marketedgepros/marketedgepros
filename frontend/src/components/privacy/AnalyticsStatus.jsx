import { ShieldCheck } from 'lucide-react';

// This reports the absence of the optional analytics integration in this build.
// It is not a privacy policy, a consent receipt or a toggle for a live provider.
export default function AnalyticsStatus() {
  return (
    <section
      id="analytics-status"
      aria-labelledby="analytics-status-heading"
      className="mep-panel scroll-mt-24 rounded-2xl border p-5 text-slate-200 sm:p-8"
    >
      <div className="flex items-start gap-3">
        <ShieldCheck aria-hidden="true" className="mt-1 h-6 w-6 shrink-0 text-cyan-300" />
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-cyan-300">Technical collection status</p>
          <h2 id="analytics-status-heading" className="mep-heading mt-2 text-2xl font-semibold text-white">Optional analytics is off</h2>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            This version does not load the Google Analytics integration. There is no analytics acceptance
            button because optional measurement is not enabled.
          </p>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            Account sign-in and security storage are separate from optional analytics. This change does
            not clear account data or cookies left by earlier visits. Browser settings can be used to
            inspect and clear previously stored site data.
          </p>
          <p className="mt-3 text-sm leading-6 text-slate-400">
            This technical status is not an approval or replacement of the privacy or cookie policy.
          </p>
        </div>
      </div>
    </section>
  );
}
