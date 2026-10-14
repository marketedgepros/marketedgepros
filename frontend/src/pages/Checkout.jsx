import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { FileText, RefreshCw, ArrowRight } from "lucide-react";
import useAuthStore from "../store/authStore";
import useProgramCatalog from "../hooks/useProgramCatalog";
import { isProgramComingSoon } from "../services/programEvaluationPolicy.js";
import ComingSoonProgram from "../components/programs/ComingSoonProgram";
import { ADMIN_ROLES } from "../constants/roles";
import { addonPriceLabel, formatCatalogMoney, mapQuotedCatalog } from "../services/programCatalogViewService";
import {
  OrderQuoteIdempotencyKeys, MAX_ORDER_ADDONS, formatUsdFromMinorUnits,
  normalizeQuoteContext, orderQuoteErrorMessage, requestOrderQuote,
} from "../services/orderQuoteViewService";
import { normalizePaymentOrderId, paymentErrorMessage, readStoredPurchaseQuote } from "../services/orderPaymentViewService";
import OrderPaymentPanel, { PurchaseProgress } from "../components/payments/OrderPaymentPanel";
import { CatalogPage, CatalogState, BackToPrograms, ProgramRules, ConfiguredRules, PaymentBoundary, primaryAction, secondaryAction, panelStyle } from "../components/programs/CatalogUI";

const idle = () => ({ key: "", state: "idle", quote: null, catalogQuote: null, error: "" });
const storedCatalog = (quote, principal) => {
  // Comparison is deliberately unavailable until a current catalog is supplied.
  // This reference uses only the verified owner-scoped immutable quote itself.
  const snapshotReference = { id: quote.context.programId, tenantId: principal.tenant_id, price: quote.order.snapshot.baseAmount, terms: quote.order.snapshot.terms };
  return { ...mapQuotedCatalog(quote, snapshotReference, principal.id), differsFromCatalog: false, comparedWithCatalog: false };
};

export default function Checkout() {
  const { programId } = useParams();
  const { user, isAuthenticated, isLoading: authLoading } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [search, setSearch] = useSearchParams();
  const catalog = useProgramCatalog(programId);
  const program = catalog.data;
  const instantComingSoon = isProgramComingSoon(program?.terms);
  const isAdmin = Boolean(user && ADMIN_ROLES.includes(user.role));
  const ownerKey = isAuthenticated && user ? `${user.id}:${user.tenant_id}:${user.role}:${programId}` : `guest:${programId}`;
  const currentOwner = useRef(ownerKey); currentOwner.current = ownerKey;
  const savedValues = search.getAll("order");
  let savedOrderId = null, invalidSavedOrder = false;
  if (savedValues.length) {
    try { if (savedValues.length !== 1) throw new Error("Duplicate order"); savedOrderId = normalizePaymentOrderId(savedValues[0]); }
    catch { invalidSavedOrder = true; }
  }
  const resumeKey = `${ownerKey}:${savedValues.join(",")}`;
  const currentResume = useRef(resumeKey); currentResume.current = resumeKey;
  const [selection, setSelection] = useState({ ownerKey, ids: [] });
  const addonIds = selection.ownerKey === ownerKey ? selection.ids : [];
  const selectionKey = `${ownerKey}:${addonIds.join(",")}`;
  const currentSelection = useRef(selectionKey); currentSelection.current = selectionKey;
  const [result, setResult] = useState(idle);
  const [paymentLock, setPaymentLock] = useState({ key: "", locked: false });
  const [progress, setProgress] = useState({ key: "", stage: 0 });
  const quoteRequest = useRef({ id: 0, controller: null, pending: false });
  const quoteKeys = useRef(new OrderQuoteIdempotencyKeys());
  const alive = useRef(false);
  const requestedFocus = useRef(null);
  const paymentHost = useRef(null);
  const visible = result.key === selectionKey ? result : idle();
  const locked = Boolean(savedOrderId || invalidSavedOrder || (paymentLock.key === selectionKey && paymentLock.locked));
  let quotedCatalog = visible.catalogQuote;
  if (visible.quote && program) {
    try { quotedCatalog = { ...mapQuotedCatalog(visible.quote, program, user.id), comparedWithCatalog: true }; }
    catch { quotedCatalog = { ...visible.catalogQuote, comparedWithCatalog: false }; }
  }

  const invalidateQuote = () => {
    quoteRequest.current.controller?.abort();
    quoteRequest.current = { id: quoteRequest.current.id + 1, controller: null, pending: false };
    quoteKeys.current.invalidate();
    requestedFocus.current = null;
    setResult(idle());
  };
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; quoteRequest.current.controller?.abort(); };
  }, []);
  useEffect(() => { invalidateQuote(); setSelection({ ownerKey, ids: [] }); }, [ownerKey]);
  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated || !user) navigate(`/login?redirect=${encodeURIComponent(location.pathname + location.search)}`, { replace: true });
    else if (isAdmin) navigate("/admin", { replace: true });
  }, [ownerKey, user, authLoading, isAuthenticated, isAdmin, navigate, location.pathname, location.search]);

  const loadSavedQuote = useCallback(async () => {
    if (!savedOrderId || !user || !isAuthenticated || authLoading || isAdmin || quoteRequest.current.pending) return;
    const scope = ownerKey, resume = resumeKey;
    const controller = new AbortController(), requestId = quoteRequest.current.id + 1;
    quoteRequest.current = { id: requestId, controller, pending: true };
    setResult({ ...idle(), key: currentSelection.current, state: "loading" });
    try {
      const quote = await readStoredPurchaseQuote({ orderId: savedOrderId, programId: Number(programId), principal: user, signal: controller.signal });
      const catalogQuote = storedCatalog(quote, user);
      if (!alive.current || controller.signal.aborted || quoteRequest.current.id !== requestId || currentOwner.current !== scope || currentResume.current !== resume) return;
      const ids = [...quote.context.addonIds];
      const key = `${scope}:${ids.join(",")}`;
      setSelection({ ownerKey: scope, ids });
      setResult({ key, state: "quoted", quote, catalogQuote, error: "" });
    } catch (error) {
      if (!alive.current || controller.signal.aborted || quoteRequest.current.id !== requestId || currentOwner.current !== scope || currentResume.current !== resume) return;
      setResult({ ...idle(), key: currentSelection.current, state: "error", error: paymentErrorMessage(error) });
    } finally { if (quoteRequest.current.id === requestId) quoteRequest.current.pending = false; }
  }, [savedOrderId, ownerKey, resumeKey, user, isAuthenticated, authLoading, isAdmin, programId]);
  useEffect(() => {
    if (!savedOrderId || authLoading || !user || !isAuthenticated || isAdmin) return;
    // Saving the current order in the URL is not a request for a different quote.
    if (visible.quote?.order.id === savedOrderId) return;
    quoteRequest.current.controller?.abort();
    quoteRequest.current.pending = false;
    loadSavedQuote();
    return () => { quoteRequest.current.controller?.abort(); quoteRequest.current.pending = false; };
  }, [ownerKey, savedOrderId, authLoading, isAuthenticated, isAdmin]);
  useEffect(() => {
    if (requestedFocus.current !== selectionKey || !visible.quote) return;
    requestedFocus.current = null;
    paymentHost.current?.querySelector("#order-payment-title")?.focus();
  }, [visible.quote?.order.id, selectionKey]);
  const onLockSelection = useCallback((value) => {
    setPaymentLock((old) => old.key === selectionKey && old.locked === value ? old : { key: selectionKey, locked: value });
  }, [selectionKey]);
  const onStageChange = useCallback((stage) => {
    setProgress((old) => old.key === selectionKey && old.stage === stage ? old : { key: selectionKey, stage });
  }, [selectionKey]);
  const onPersistOrder = useCallback((orderId) => {
    const next = new URLSearchParams(search);
    next.set("order", normalizePaymentOrderId(orderId));
    next.set("payment-requested", "1");
    setSearch(next, { replace: true });
  }, [search, setSearch]);

  const toggleAddon = (id) => {
    if (locked || quoteRequest.current.pending) return;
    const selected = addonIds.includes(id);
    if (!selected && addonIds.length >= MAX_ORDER_ADDONS) return;
    invalidateQuote();
    setSelection({ ownerKey, ids: selected ? addonIds.filter((value) => value !== id) : [...addonIds, id].sort((a, b) => a - b) });
  };
  const requestQuote = async () => {
    if (savedOrderId) { await loadSavedQuote(); return; }
    if (!program || instantComingSoon || !user || !isAuthenticated || isAdmin || locked || quoteRequest.current.pending) return;
    const key = selectionKey, scope = ownerKey;
    const controller = new AbortController(), id = quoteRequest.current.id + 1;
    quoteRequest.current = { id, controller, pending: true };
    setResult({ ...idle(), key, state: "loading" });
    try {
      const context = normalizeQuoteContext(program.id, addonIds);
      const quote = await requestOrderQuote({ programId: context.programId, addonIds: context.addonIds, idempotencyKey: quoteKeys.current.forContext(context), signal: controller.signal });
      const catalogQuote = { ...mapQuotedCatalog(quote, program, user.id), comparedWithCatalog: true };
      if (!alive.current || controller.signal.aborted || quoteRequest.current.id !== id || currentOwner.current !== scope || currentSelection.current !== key) return;
      requestedFocus.current = key;
      setResult({ key, state: "quoted", quote, catalogQuote, error: "" });
    } catch (error) {
      if (!alive.current || controller.signal.aborted || quoteRequest.current.id !== id || currentOwner.current !== scope || currentSelection.current !== key) return;
      setResult({ ...idle(), key, state: "error", error: orderQuoteErrorMessage(error) });
    } finally { if (quoteRequest.current.id === id) quoteRequest.current.pending = false; }
  };

  if (authLoading || !isAuthenticated || !user || isAdmin) return <CatalogPage><CatalogState loading /></CatalogPage>;
  if (instantComingSoon && !savedOrderId) return <CatalogPage><BackToPrograms /><h1 className="mep-heading mb-7 text-3xl font-semibold sm:text-5xl">Instant Funding</h1><ComingSoonProgram showTitle={false} />{invalidSavedOrder && <p role="alert" className="mt-5 text-amber-100">The saved order reference is invalid. No order or payment has been requested.</p>}</CatalogPage>;
  const displayedTerms = savedOrderId ? quotedCatalog?.terms : (program?.terms ?? quotedCatalog?.terms);
  const instantReadOnly = instantComingSoon || isProgramComingSoon(quotedCatalog?.terms);
  const stage = visible.quote ? (progress.key === selectionKey ? progress.stage : 1) : 0;
  return <CatalogPage>
    <BackToPrograms />
    {!savedOrderId && (catalog.loading || catalog.error || !program) ? <CatalogState {...catalog} /> : <>
      <header className="mb-8">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Program selection / Order review</p>
        <h1 className="mep-heading mt-4 text-3xl font-semibold tracking-tight sm:text-5xl">Review your program.</h1>
        <p className="mt-4 max-w-2xl leading-relaxed text-slate-300">Choose optional add-ons, then request a quote. Only the server calculates the final amount and records the terms. Payment is a separate, account-specific step.</p>
      </header>
      <PurchaseProgress stage={stage} />
      {invalidSavedOrder && <p role="alert" className="mb-6 rounded-xl border border-amber-400/30 p-4 text-sm text-amber-100">The saved order reference is invalid. No order or payment has been requested. Open a valid purchase from your account records.</p>}
      {savedOrderId && <p className="mb-6 rounded-xl border border-cyan-400/20 p-4 text-sm leading-relaxed text-slate-300">You are viewing a saved order. Its quote is immutable; changing the catalog does not change this order. No payment is created by opening this page.</p>}
      <div className="grid items-start gap-6 lg:grid-cols-[1.25fr_1fr]">
        <div className="space-y-6">
          <section className={panelStyle} aria-labelledby="selection-program">
            <div className="flex flex-wrap items-start justify-between gap-4"><div>
              <p className="text-xs uppercase tracking-wider text-slate-400">{savedOrderId || !program ? "Stored program settings" : "Current catalog"}</p>
              <h2 id="selection-program" className="mep-heading mt-2 break-words text-xl font-semibold">{displayedTerms?.name ?? "Loading stored program information"}</h2>
            </div>{program && <Link to={`/programs/${program.id}`} className="rounded text-sm text-cyan-200 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">View all rules<ArrowRight className="ml-1 inline" size={14} aria-hidden="true" /></Link>}</div>
            <div className="mt-5 border-l-2 border-cyan-400 pl-4"><p className="text-sm text-slate-400">{savedOrderId || !program ? "Recorded base fee" : "Catalog base fee"}</p>
              <p className="mt-1 text-3xl font-bold tabular-nums text-cyan-200">{savedOrderId ? (quotedCatalog ? formatCatalogMoney(quotedCatalog.baseAmount) : "Awaiting stored record") : program || quotedCatalog ? formatCatalogMoney(program?.price ?? quotedCatalog.baseAmount) : "Awaiting stored record"}</p>
              <p className="mt-2 text-xs text-slate-400">Not a final total or payment request.</p>
            </div>
            {displayedTerms && <div className="mt-5"><ProgramRules terms={displayedTerms} historical={Boolean(savedOrderId)} /></div>}
            {!program && savedOrderId && <p className="mt-4 text-xs leading-relaxed text-slate-400">The current catalog is unavailable. Only stored order terms are shown; no current-catalog comparison is assumed.</p>}
          </section>
          <section className={panelStyle} aria-labelledby="select-addons">
            <h2 id="select-addons" className="mep-heading text-xl font-semibold">{savedOrderId ? "Recorded add-ons" : "Optional add-ons"}</h2>
            {savedOrderId ? <div className="mt-4 space-y-3">
              {!visible.quote ? <p className="text-sm text-slate-400">Recorded add-ons have not yet been verified.</p> : visible.quote.order.snapshot.addons.length ? visible.quote.order.snapshot.addons.map((addon) => <div key={addon.id} className="flex flex-wrap justify-between gap-2 rounded-xl border border-slate-700 p-4 text-sm"><span>{addon.name}</span><span className="tabular-nums text-cyan-200">{formatCatalogMoney(addon.amount)}</span></div>) : <p className="text-sm text-slate-300">No add-ons were recorded in this quote.</p>}
            </div> : <>
              <p className="mt-2 text-sm text-slate-400">Choose up to {MAX_ORDER_ADDONS}. Percentage charges use the base fee and are rounded by the server per line.</p>
              {program?.addons.length ? <fieldset className="mt-5 space-y-3" disabled={locked || visible.state === "loading"}>
                <legend className="sr-only">Add-ons for your quote</legend>
                {program.addons.map((addon) => {
                  const checked = addonIds.includes(addon.id);
                  return <label key={addon.id} className={`flex items-start gap-3 rounded-xl border p-4 ${checked ? "border-cyan-400/60 bg-cyan-400/10" : "border-slate-700 hover:border-slate-500"}`}>
                    <input type="checkbox" checked={checked} onChange={() => toggleAddon(addon.id)} disabled={locked || visible.state === "loading" || (!checked && addonIds.length >= MAX_ORDER_ADDONS)} className="mt-1 h-4 w-4 shrink-0 accent-cyan-400 focus-visible:outline focus-visible:outline-cyan-300" />
                    <div className="min-w-0 flex-1"><span className="block break-words font-medium">{addon.name}</span><span className="mt-1 block text-sm tabular-nums text-cyan-200">{addonPriceLabel(addon)}</span>{addon.description && <span className="mt-2 block break-words text-xs leading-relaxed text-slate-400">{addon.description}</span>}</div>
                  </label>;
                })}
              </fieldset> : <p className="mt-5 text-sm text-slate-300">No active add-ons are available.</p>}
              {locked && <p role="status" className="mt-4 text-xs leading-relaxed text-amber-100">The selection is locked to this payment request. Check the saved order instead of creating a replacement.</p>}
            </>}
          </section>
        </div>
        <section className={`${panelStyle} space-y-6`} aria-labelledby="quote-summary" aria-busy={visible.state === "loading" || undefined}>
          <div><div className="flex items-center gap-2 text-cyan-300"><FileText size={19} aria-hidden="true" /><p className="text-xs font-semibold uppercase tracking-wider">Server-priced quote</p></div><h2 id="quote-summary" className="mep-heading mt-3 text-2xl font-semibold">Your quote summary</h2><p className="mt-2 text-sm text-slate-400">No browser-calculated total is used.</p></div>
          <div className="mep-panel rounded-xl border p-4" aria-live="polite"><p className="text-xs uppercase tracking-wider text-slate-400">Quote record — not payment status</p>
            <p className="mt-2 font-semibold">{{ idle: "Not requested", loading: savedOrderId ? "Loading saved quote…" : "Requesting quote…", error: "Quote unavailable", quoted: "Quote recorded — payment checked separately" }[visible.state]}</p>
            {visible.quote && <p className="mt-2 text-sm text-slate-400">{visible.quote.replayed ? "Existing quote returned for this selection." : "The server recorded these quote terms."}</p>}
          </div>
          {visible.error && <p role="alert" className="rounded-xl border border-red-400/30 bg-red-400/5 p-4 text-sm leading-relaxed text-red-200">{visible.error}</p>}
          {visible.quote && quotedCatalog && <div><p className="mb-4 text-sm font-semibold text-cyan-200">Immutable quote summary</p>
            <dl className="space-y-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Base fee</dt><dd className="tabular-nums">{formatCatalogMoney(quotedCatalog.baseAmount)}</dd></div>
              {visible.quote.order.snapshot.addons.map((addon) => <div key={addon.id} className="flex flex-wrap justify-between gap-2"><dt className="break-words text-slate-400">{addon.name}</dt><dd className="tabular-nums">{formatCatalogMoney(addon.amount)}</dd></div>)}
              <div className="flex flex-wrap justify-between gap-3 border-t border-slate-700 pt-4"><dt className="font-semibold">Quoted total</dt><dd className="text-2xl font-semibold tabular-nums text-cyan-200">{formatUsdFromMinorUnits(visible.quote.order.amountMinor)}</dd></div>
            </dl>
            {quotedCatalog.comparedWithCatalog && quotedCatalog.differsFromCatalog && <p role="status" className="mt-4 rounded-lg border border-amber-300/30 p-3 text-sm text-amber-100">The quoted price or terms differ from the catalog shown when you selected this program. Review the recorded terms below. This quote is not a payment receipt.</p>}
            <details className="mt-5 rounded-lg border border-slate-700 p-3">
              <summary className="cursor-pointer text-sm text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Recorded program settings</summary>
              <h3 className="mt-4 break-words font-semibold">{quotedCatalog.terms.name}</h3>
              <ProgramRules terms={quotedCatalog.terms} historical />
              {quotedCatalog.terms.description && <p className="mt-4 break-words text-sm leading-relaxed text-slate-400">Recorded description — not a current availability promise: {quotedCatalog.terms.description}</p>}
              <p className="mt-4 text-xs leading-relaxed text-slate-400">Recorded payout settings below are historical catalog information, not confirmation of eligibility or an active payout service.</p>
              <dl className="mt-3 space-y-2 text-sm"><div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Recorded minimum payout amount</dt><dd>{quotedCatalog.terms.minimum_payout_amount === null ? "Not specified" : formatCatalogMoney(quotedCatalog.terms.minimum_payout_amount)}</dd></div><div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Recorded payout mode</dt><dd>{quotedCatalog.terms.payout_mode === null ? "Not specified" : quotedCatalog.terms.payout_mode.replaceAll("_", " ")}</dd></div></dl>
              <div className="mt-5"><ConfiguredRules terms={quotedCatalog.terms} headingId="recorded-program-additional" headingTag="h3" /></div>
            </details>
          </div>}
          <button type="button" onClick={requestQuote} disabled={visible.state === "loading" || invalidSavedOrder || (locked && !savedOrderId)} className={`${primaryAction} w-full`}>
            {visible.state === "error" ? <RefreshCw size={18} aria-hidden="true" /> : <FileText size={18} aria-hidden="true" />}
            {visible.state === "loading" ? "Requesting server quote…" : savedOrderId ? "Reload saved quote" : visible.state === "error" ? "Retry server quote" : visible.quote ? "View recorded quote again" : "Request server quote"}
          </button>
          <p className="text-xs leading-relaxed text-slate-400">{savedOrderId ? "This is an owner-scoped local read. It does not request another quote or payment." : "Retries for an unchanged selection use the same request key. Changing a selection creates a new quote request."}</p>
          {!visible.quote && <PaymentBoundary />}
          <Link to="/support/create-ticket" className={`${secondaryAction} w-full`}>Ask about availability</Link>
        </section>
      </div>
      {visible.quote && (instantReadOnly ? <div className="mt-7"><ComingSoonProgram /><p className="mt-4 text-sm text-slate-400">This saved order remains a historical read-only record. No new payment is available for Instant Funding.</p></div> : <div ref={paymentHost} className="mt-7"><OrderPaymentPanel quote={visible.quote} principal={user} initialCreationAttempted={search.getAll("payment-requested").length === 1 && search.get("payment-requested") === "1"} onPersistOrder={onPersistOrder} onLockSelection={onLockSelection} onStageChange={onStageChange} /></div>)}
    </>}
  </CatalogPage>;
}
