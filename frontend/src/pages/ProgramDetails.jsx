import React from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { ArrowRight, Layers } from "lucide-react";
import useAuthStore from "../store/authStore";
import useProgramCatalog from "../hooks/useProgramCatalog";
import { programRulesPath } from "../services/programRuleFamilies.js";
import { APPROVED_ACCOUNT_MODEL, isProgramComingSoon } from "../services/programEvaluationPolicy.js";
import ComingSoonProgram from "../components/programs/ComingSoonProgram";
import {
  addonPriceLabel,
  formatCatalogMoney,
  typeLabel,
} from "../services/programCatalogViewService";
import {
  CatalogPage,
  CatalogState,
  ProgramRules,
  ConfiguredRules,
  PaymentBoundary,
  BackToPrograms,
  primaryAction,
  panelStyle,
} from "../components/programs/CatalogUI";

export default function ProgramDetails() {
  const { id } = useParams();
  const catalog = useProgramCatalog(id);
  const { user } = useAuthStore();
  const navigate = useNavigate();
  const program = catalog.data;
  const proceed = () => {
    if (!program || isProgramComingSoon(program.terms)) return;
    const destination = `/programs/${program.id}/checkout`;
    navigate(
      user ? destination : `/login?redirect=${encodeURIComponent(destination)}`,
      user ? undefined : { state: { from: destination } },
    );
  };
  return (
    <CatalogPage>
      <BackToPrograms />
      {catalog.loading || catalog.error || !program ? (
        <CatalogState loading={catalog.loading} error={catalog.error} retry={catalog.retry} />
      ) : isProgramComingSoon(program.terms) ? (
        <>
          <h1 className="mep-heading mb-7 text-3xl font-semibold sm:text-5xl">Instant Funding</h1>
          <ComingSoonProgram showTitle={false} />
        </>
      ) : (
        <>
          <header className="mb-9">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
              {typeLabel(program.terms.type)} / Program overview
            </p>
            <h1 className="mep-heading mt-4 break-words text-3xl font-semibold tracking-tight sm:text-5xl">
              {program.terms.name}
            </h1>
            <p className="mt-4 max-w-2xl leading-relaxed text-slate-300">
              Review the published settings and optional add-ons. These are
              catalog values, not confirmation of payment, funding or an active
              trading account.
            </p>
          </header>
          <nav aria-label="On this program page" className="mb-7 flex flex-wrap gap-2">
            {[
              ["program-rules", "Settings"],
              ["program-addons", "Add-ons"],
              ["program-additional", "Additional rules"],
              ["program-next-step", "Next step"],
            ].map(([target, label]) => (
              <Link
                key={target}
                to={`#${target}`}
                className="rounded-full border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:border-cyan-400 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
              >
                {label}
              </Link>
            ))}
          </nav>
          <div className="grid items-start gap-6 lg:grid-cols-[1.4fr_1fr]">
            <div className="space-y-6">
              <section className={panelStyle} aria-labelledby="program-rules">
                <h2 id="program-rules" className="mep-heading mb-4 scroll-mt-28 text-xl font-semibold">
                  Published program settings
                </h2>
                <ProgramRules terms={program.terms} />
                <p className="mt-4 text-sm leading-relaxed text-slate-400">
                  “Not specified” means a value has not been published in this
                  catalog entry. It does not mean zero or no restriction.
                </p>
                <p data-account-model={APPROVED_ACCOUNT_MODEL.version} className="mt-4 text-sm leading-relaxed text-slate-300">
                  {APPROVED_ACCOUNT_MODEL.description}
                </p>
                {program.terms.description && (
                  <div className="mt-5 border-t border-slate-700 pt-4">
                    <h3 className="text-sm font-semibold text-cyan-200">
                      Catalog description
                    </h3>
                    <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">
                      {program.terms.description}
                    </p>
                    <p className="mt-3 text-xs text-slate-400">
                      Descriptions do not override the payment availability
                      notice.
                    </p>
                  </div>
                )}
              </section>
              <section className={panelStyle} aria-labelledby="program-addons">
                <h2
                  id="program-addons"
                  className="mep-heading flex scroll-mt-28 items-center gap-2 text-xl font-semibold"
                >
                  <Layers size={20} className="text-cyan-300" aria-hidden="true" />
                  Optional add-ons
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  If quotes are available, options can be selected there.
                  Percentage add-ons use the base program fee, not the combined
                  total.
                </p>
                {program.addons.length ? (
                  <ul className="mt-5 divide-y divide-slate-700">
                    {program.addons.map((addon) => (
                      <li key={addon.id} className="py-4">
                        <div className="flex flex-wrap justify-between gap-3">
                          <h3 className="break-words font-medium">{addon.name}</h3>
                          <span className="text-sm tabular-nums text-cyan-200">
                            {addonPriceLabel(addon)}
                          </span>
                        </div>
                        {addon.description && (
                          <p className="mt-2 break-words text-sm text-slate-400">
                            {addon.description}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-5 text-sm text-slate-300">
                    No active add-ons are listed for this program.
                  </p>
                )}
              </section>
              <div id="program-additional" className="scroll-mt-28">
                <ConfiguredRules terms={program.terms} />
              </div>
            </div>
            <aside
              id="program-next-step"
              className={`${panelStyle} scroll-mt-28 space-y-6`}
              aria-label="Program fee and next step"
            >
              <div>
                <p className="text-xs uppercase tracking-wider text-slate-400">
                  Catalog base fee
                </p>
                <p className="mt-3 text-4xl font-bold tabular-nums text-cyan-200">
                  {formatCatalogMoney(program.price)}
                </p>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">
                  This is the base fee shown in the catalog. If quotes are
                  available, the server records the price, selected options and
                  terms in an unpaid quote. No charge is made.
                </p>
              </div>
              <button type="button" onClick={proceed} className={`${primaryAction} w-full`}>
                Check quote availability
                <ArrowRight size={17} aria-hidden="true" />
              </button>
              <p className="text-sm leading-relaxed text-slate-400">
                If you are not signed in, this step opens sign-in first and
                keeps the selected program as the return destination. It does
                not confirm that a quote is available.
              </p>
              <PaymentBoundary />
              <div className="border-t border-slate-700 pt-5">
                <h2 className="mep-heading text-base font-semibold">Need more context?</h2>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">
                  Browse general questions or view contact options for details
                  not specified in this listing.
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  <Link to="/faq" className="rounded text-sm font-semibold text-cyan-200 underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Browse FAQ</Link>
                  <Link to="/contact" className="rounded text-sm font-semibold text-cyan-200 underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Contact options</Link>
                  <Link to={programRulesPath(program.terms.type)} className="rounded text-sm font-semibold text-cyan-200 underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Rules for this program category</Link>
                </div>
              </div>
            </aside>
          </div>
        </>
      )}
    </CatalogPage>
  );
}
