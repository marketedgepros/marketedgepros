import React from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowRight, Layers } from "lucide-react";
import useAuthStore from "../store/authStore";
import useProgramCatalog from "../hooks/useProgramCatalog";
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
    const destination = `/programs/${program.id}/checkout`;
    navigate(
      user ? destination : "/login",
      user ? undefined : { state: { from: destination } },
    );
  };
  return (
    <CatalogPage>
      <BackToPrograms />
      {catalog.loading || catalog.error || !program ? (
        <CatalogState {...catalog} />
      ) : (
        <>
          <header className="mb-9">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
              {typeLabel(program.terms.type)} / Program overview
            </p>
            <h1 className="mt-4 break-words text-3xl font-semibold tracking-tight sm:text-5xl">
              {program.terms.name}
            </h1>
            <p className="mt-4 max-w-2xl leading-relaxed text-slate-300">
              Review the published settings and optional add-ons. These are
              catalog values, not confirmation of payment, funding or an active
              trading account.
            </p>
          </header>
          <div className="grid items-start gap-6 lg:grid-cols-[1.4fr_1fr]">
            <div className="space-y-6">
              <section className={panelStyle} aria-labelledby="program-rules">
                <h2 id="program-rules" className="mb-4 text-xl font-semibold">
                  Published program settings
                </h2>
                <ProgramRules terms={program.terms} />
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
                  className="flex items-center gap-2 text-xl font-semibold"
                >
                  <Layers
                    size={20}
                    className="text-cyan-300"
                    aria-hidden="true"
                  />
                  Optional add-ons
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  Select options on the quote page. Percentage add-ons use the
                  base program fee, not the combined total.
                </p>
                {program.addons.length ? (
                  <ul className="mt-5 divide-y divide-slate-700">
                    {program.addons.map((addon) => (
                      <li key={addon.id} className="py-4">
                        <div className="flex flex-wrap justify-between gap-3">
                          <h3 className="break-words font-medium">
                            {addon.name}
                          </h3>
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
              <ConfiguredRules terms={program.terms} />
            </div>
            <aside
              className={`${panelStyle} space-y-6`}
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
                  This is the current base fee. Your quote will record the
                  server's current price, options and terms. No charge is made.
                </p>
              </div>
              <button
                type="button"
                onClick={proceed}
                className={`${primaryAction} w-full`}
              >
                Review quote options
                <ArrowRight size={17} aria-hidden="true" />
              </button>
              <PaymentBoundary />
            </aside>
          </div>
        </>
      )}
    </CatalogPage>
  );
}
