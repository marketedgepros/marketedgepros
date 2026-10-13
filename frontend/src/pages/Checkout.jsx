import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { FileText, RefreshCw, ArrowRight } from "lucide-react";
import useAuthStore from "../store/authStore";
import useProgramCatalog from "../hooks/useProgramCatalog";
import { ADMIN_ROLES } from "../constants/roles";
import {
  addonPriceLabel,
  formatCatalogMoney,
  mapQuotedCatalog,
} from "../services/programCatalogViewService";
import {
  OrderQuoteIdempotencyKeys,
  MAX_ORDER_ADDONS,
  formatUsdFromMinorUnits,
  normalizeQuoteContext,
  orderQuoteErrorMessage,
  requestOrderQuote,
} from "../services/orderQuoteViewService";
import {
  CatalogPage,
  CatalogState,
  BackToPrograms,
  ProgramRules,
  PaymentBoundary,
  primaryAction,
  secondaryAction,
  panelStyle,
} from "../components/programs/CatalogUI";

export default function Checkout() {
  const { programId } = useParams();
  const { user, isLoading: authLoading } = useAuthStore();
  const navigate = useNavigate();
  const catalog = useProgramCatalog(programId);
  const program = catalog.data;
  const isAdmin = Boolean(user && ADMIN_ROLES.includes(user.role));
  const ownerKey = user
    ? `${user.id}:${user.tenant_id}:${user.role}:${programId}`
    : `guest:${programId}`;
  const currentOwner = useRef(ownerKey);
  currentOwner.current = ownerKey;
  const [selection, setSelection] = useState({ ownerKey, ids: [] });
  const addonIds = selection.ownerKey === ownerKey ? selection.ids : [];
  const selectionKey = `${ownerKey}:${addonIds.join(",")}`;
  const currentSelection = useRef(selectionKey);
  currentSelection.current = selectionKey;
  const [result, setResult] = useState({
    key: "",
    state: "idle",
    quote: null,
    catalogQuote: null,
    error: "",
  });
  const quoteRequest = useRef({ id: 0, controller: null, pending: false });
  const quoteKeys = useRef(new OrderQuoteIdempotencyKeys());
  const alive = useRef(false);
  const visible =
    result.key === selectionKey
      ? result
      : { state: "idle", quote: null, catalogQuote: null, error: "" };

  const invalidateQuote = () => {
    quoteRequest.current.controller?.abort();
    quoteRequest.current = {
      id: quoteRequest.current.id + 1,
      controller: null,
      pending: false,
    };
    quoteKeys.current.invalidate();
    setResult({
      key: "",
      state: "idle",
      quote: null,
      catalogQuote: null,
      error: "",
    });
  };
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      quoteRequest.current.controller?.abort();
    };
  }, []);
  useEffect(() => {
    invalidateQuote();
    setSelection({ ownerKey, ids: [] });
  }, [ownerKey]);
  useEffect(() => {
    if (authLoading) return;
    if (!user)
      navigate("/login", {
        replace: true,
        state: { from: `/programs/${programId}/checkout` },
      });
    else if (isAdmin) navigate("/admin", { replace: true });
  }, [ownerKey, user, authLoading, isAdmin, navigate, programId]);

  const toggleAddon = (id) => {
    const selected = addonIds.includes(id);
    if (!selected && addonIds.length >= MAX_ORDER_ADDONS) return;
    invalidateQuote();
    setSelection({
      ownerKey,
      ids: selected
        ? addonIds.filter((value) => value !== id)
        : [...addonIds, id].sort((a, b) => a - b),
    });
  };
  const requestQuote = async () => {
    if (!program || !user || isAdmin || quoteRequest.current.pending) return;
    const key = selectionKey;
    const owner = ownerKey;
    const controller = new AbortController();
    const id = quoteRequest.current.id + 1;
    quoteRequest.current = { id, controller, pending: true };
    setResult({
      key,
      state: "loading",
      quote: null,
      catalogQuote: null,
      error: "",
    });
    try {
      const context = normalizeQuoteContext(program.id, addonIds);
      const quote = await requestOrderQuote({
        programId: context.programId,
        addonIds: context.addonIds,
        idempotencyKey: quoteKeys.current.forContext(context),
        signal: controller.signal,
      });
      const catalogQuote = mapQuotedCatalog(quote, program, user.id);
      if (
        !alive.current ||
        controller.signal.aborted ||
        quoteRequest.current.id !== id ||
        currentOwner.current !== owner ||
        currentSelection.current !== key
      )
        return;
      setResult({ key, state: "quoted", quote, catalogQuote, error: "" });
    } catch (error) {
      if (
        !alive.current ||
        controller.signal.aborted ||
        quoteRequest.current.id !== id ||
        currentOwner.current !== owner ||
        currentSelection.current !== key
      )
        return;
      setResult({
        key,
        state: "error",
        quote: null,
        catalogQuote: null,
        error: orderQuoteErrorMessage(error),
      });
    } finally {
      if (quoteRequest.current.id === id) quoteRequest.current.pending = false;
    }
  };

  if (authLoading || !user || isAdmin)
    return (
      <CatalogPage>
        <CatalogState loading />
      </CatalogPage>
    );
  return (
    <CatalogPage>
      <BackToPrograms />
      {catalog.loading || catalog.error || !program ? (
        <CatalogState {...catalog} />
      ) : (
        <>
          <header className="mb-9">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
              Program selection / Unpaid quote
            </p>
            <h1 className="mep-heading mt-4 text-3xl font-semibold tracking-tight sm:text-5xl">
              Review your program.
            </h1>
            <p className="mt-4 max-w-2xl leading-relaxed text-slate-300">
              Choose optional add-ons, then request a quote. Only the server
              calculates the final amount and records the terms for this
              selection.
            </p>
          </header>
          <div className="grid items-start gap-6 lg:grid-cols-[1.25fr_1fr]">
            <div className="space-y-6">
              <section
                className={panelStyle}
                aria-labelledby="selection-program"
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-wider text-slate-400">
                      Current catalog
                    </p>
                    <h2
                      id="selection-program"
                      className="mep-heading mt-2 break-words text-xl font-semibold"
                    >
                      {program.terms.name}
                    </h2>
                  </div>
                  <Link
                    to={`/programs/${program.id}`}
                    className="rounded text-sm text-cyan-200 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                  >
                    View all rules
                    <ArrowRight
                      className="ml-1 inline"
                      size={14}
                      aria-hidden="true"
                    />
                  </Link>
                </div>
                <div className="mt-5 border-l-2 border-cyan-400 pl-4">
                  <p className="text-sm text-slate-400">Catalog base fee</p>
                  <p className="mt-1 text-3xl font-bold tabular-nums text-cyan-200">
                    {formatCatalogMoney(program.price)}
                  </p>
                  <p className="mt-2 text-xs text-slate-400">
                    Not a final total or payment request.
                  </p>
                </div>
                <div className="mt-5">
                  <ProgramRules terms={program.terms} />
                </div>
              </section>
              <section className={panelStyle} aria-labelledby="select-addons">
                <h2 id="select-addons" className="mep-heading text-xl font-semibold">
                  Optional add-ons
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  Choose up to {MAX_ORDER_ADDONS}. Percentage charges use the
                  base fee and are rounded by the server per line.
                </p>
                {program.addons.length ? (
                  <fieldset className="mt-5 space-y-3">
                    <legend className="sr-only">Add-ons for your quote</legend>
                    {program.addons.map((addon) => {
                      const checked = addonIds.includes(addon.id);
                      return (
                        <label
                          key={addon.id}
                          className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 ${checked ? "border-cyan-400/60 bg-cyan-400/10" : "border-slate-700 hover:border-slate-500"}`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleAddon(addon.id)}
                            disabled={
                              !checked && addonIds.length >= MAX_ORDER_ADDONS
                            }
                            className="mt-1 h-4 w-4 shrink-0 accent-cyan-400 focus-visible:outline focus-visible:outline-cyan-300"
                          />
                          <div className="min-w-0 flex-1">
                            <span className="block break-words font-medium">
                              {addon.name}
                            </span>
                            <span className="mt-1 block text-sm tabular-nums text-cyan-200">
                              {addonPriceLabel(addon)}
                            </span>
                            {addon.description && (
                              <span className="mt-2 block break-words text-xs leading-relaxed text-slate-400">
                                {addon.description}
                              </span>
                            )}
                          </div>
                        </label>
                      );
                    })}
                  </fieldset>
                ) : (
                  <p className="mt-5 text-sm text-slate-300">
                    No active add-ons are available.
                  </p>
                )}
              </section>
            </div>
            <section
              className={`${panelStyle} space-y-6`}
              aria-labelledby="quote-summary"
              aria-busy={visible.state === "loading" || undefined}
            >
              <div>
                <div className="flex items-center gap-2 text-cyan-300">
                  <FileText size={19} aria-hidden="true" />
                  <p className="text-xs font-semibold uppercase tracking-wider">
                    Server-priced quote
                  </p>
                </div>
                <h2 id="quote-summary" className="mep-heading mt-3 text-2xl font-semibold">
                  Your quote summary
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  No browser-calculated total is used.
                </p>
              </div>
              <div
                className="mep-panel rounded-xl border p-4"
                aria-live="polite"
              >
                <p className="text-xs uppercase tracking-wider text-slate-400">
                  Current state
                </p>
                <p className="mt-2 font-semibold">
                  {
                    {
                      idle: "Not requested",
                      loading: "Requesting quote…",
                      error: "Quote unavailable",
                      quoted: "Quoted — not paid",
                    }[visible.state]
                  }
                </p>
                {visible.quote && (
                  <p className="mt-2 text-sm text-slate-400">
                    {visible.quote.replayed
                      ? "Existing quote returned for this selection."
                      : "The server recorded this unpaid quote."}
                  </p>
                )}
              </div>
              {visible.error && (
                <p
                  role="alert"
                  className="rounded-xl border border-red-400/30 bg-red-400/5 p-4 text-sm leading-relaxed text-red-200"
                >
                  {visible.error}
                </p>
              )}
              {visible.quote && (
                <div>
                  <p className="mb-4 text-sm font-semibold text-cyan-200">
                    Immutable quote summary
                  </p>
                  <dl className="space-y-3 text-sm">
                    <div className="flex flex-wrap justify-between gap-2">
                      <dt className="text-slate-400">Base fee</dt>
                      <dd className="tabular-nums">
                        {formatCatalogMoney(visible.catalogQuote.baseAmount)}
                      </dd>
                    </div>
                    {visible.quote.order.snapshot.addons.map((addon) => (
                      <div
                        key={addon.id}
                        className="flex flex-wrap justify-between gap-2"
                      >
                        <dt className="break-words text-slate-400">
                          {addon.name}
                        </dt>
                        <dd className="tabular-nums">
                          {formatCatalogMoney(addon.amount)}
                        </dd>
                      </div>
                    ))}
                    <div className="flex flex-wrap justify-between gap-3 border-t border-slate-700 pt-4">
                      <dt className="font-semibold">Quoted total</dt>
                      <dd className="text-2xl font-semibold tabular-nums text-cyan-200">
                        {formatUsdFromMinorUnits(
                          visible.quote.order.amountMinor,
                        )}
                      </dd>
                    </div>
                  </dl>
                  {visible.catalogQuote.differsFromCatalog && (
                    <p
                      role="status"
                      className="mt-4 rounded-lg border border-amber-300/30 p-3 text-sm text-amber-100"
                    >
                      The quoted price or terms differ from the catalog shown
                      when you selected this program. Review the recorded terms
                      below. This is not a payment.
                    </p>
                  )}
                  <details className="mt-5 rounded-lg border border-slate-700 p-3">
                    <summary className="cursor-pointer text-sm text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
                      Recorded program settings
                    </summary>
                    <h3 className="mt-4 break-words font-semibold">
                      {visible.catalogQuote.terms.name}
                    </h3>
                    <ProgramRules terms={visible.catalogQuote.terms} />
                    <pre className="mt-3 whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-xs leading-relaxed text-slate-400">
                      {JSON.stringify(visible.catalogQuote.terms, null, 2)}
                    </pre>
                  </details>
                </div>
              )}
              <button
                type="button"
                onClick={requestQuote}
                disabled={visible.state === "loading"}
                className={`${primaryAction} w-full`}
              >
                {visible.state === "error" ? (
                  <RefreshCw size={18} aria-hidden="true" />
                ) : (
                  <FileText size={18} aria-hidden="true" />
                )}
                {visible.state === "loading"
                  ? "Requesting server quote…"
                  : visible.state === "error"
                    ? "Retry server quote"
                    : visible.quote
                      ? "View recorded quote again"
                      : "Request server quote"}
              </button>
              <p className="text-xs leading-relaxed text-slate-400">
                Retries for an unchanged selection use the same request key.
                Changing a selection creates a new quote request.
              </p>
              <PaymentBoundary />
              <Link
                to="/support/create-ticket"
                className={`${secondaryAction} w-full`}
              >
                Ask about availability
              </Link>
            </section>
          </div>
        </>
      )}
    </CatalogPage>
  );
}
