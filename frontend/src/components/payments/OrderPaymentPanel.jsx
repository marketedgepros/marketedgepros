import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, Copy, FileCheck, RefreshCw, ShieldCheck } from 'lucide-react';
import api from '../../services/api.js';
import { formatUsdFromMinorUnits } from '../../services/orderQuoteViewService.js';
import { createOrderPayment, getPaymentCapabilities, paymentCreationKey, paymentErrorMessage, readOrderPayment, refreshOrderPayment } from '../../services/orderPaymentViewService.js';
import { primaryAction, secondaryAction } from '../programs/CatalogUI';
import './paymentFlow.css';

export function PurchaseProgress({ stage = 0 }) {
  const labels = ['Review selection', 'Server quote', 'Payment details', 'Recorded purchase'];
  return <ol aria-label="Purchase stages" className="mep-purchase-stages">
    {labels.map((label, index) => <li key={label} aria-current={stage === index ? 'step' : undefined} data-complete={stage > index || undefined}>
      <span aria-hidden="true" className="mep-purchase-stage-marker">{stage > index ? <Check size={14} /> : index + 1}</span>
      <span>{label}</span>
    </li>)}
  </ol>;
}

const labels = {
  not_started: 'Not requested', awaiting_payment: 'Awaiting your payment', creation_uncertain: 'Creation needs verification',
  processing: 'Provider processing', manual_review: 'Needs manual review', paid: 'Purchase recorded', expired: 'Payment expired',
  failed: 'Payment failed', unavailable: 'Payment unavailable',
};
const explanations = {
  creation_uncertain: 'The request may have reached the provider. Do not send another payment or create a replacement. Check this saved order or contact support.',
  processing: 'The provider has reported processing. This is not a completed purchase; do not send a second payment.',
  manual_review: 'The records require review. A partial, extra, wrong-asset or otherwise unclear deposit is not treated as a new completed purchase.',
  expired: 'Do not send money to these details. Expiry does not prove that a late deposit cannot arrive. Contact support if you have already sent funds.',
  failed: 'No new successful purchase is being assumed. If you sent funds, use the saved order when contacting support.',
  paid: 'NOWPayments reported the payment as finished and the purchase was recorded. This does not activate a trading account or enable payouts.',
};
const blank = (key) => ({ key, loading: true, capabilities: null, projection: null, error: '', attempted: false });

export default function OrderPaymentPanel({ quote, principal, client = api, initialCreationAttempted = false, onPersistOrder, onLockSelection, onStageChange }) {
  const key = `${principal?.id}:${principal?.tenant_id}:${principal?.role}:${quote.order.id}:${quote.context.programId}:${quote.order.amountMinor}`;
  const current = useRef(key); current.current = key;
  const request = useRef({ serial: 0, controller: null, pending: false });
  const mounted = useRef(false);
  const creationKey = useRef(null);
  const [result, setResult] = useState(() => blank(key));
  const [choice, setChoice] = useState({ key, currency: '', acknowledged: false });
  const [copyStatus, setCopyStatus] = useState({ key, text: '' });
  const [clock, setClock] = useState(Date.now);
  const visible = result.key === key ? result : blank(key);
  const selection = choice.key === key ? choice : { currency: '', acknowledged: false };
  const projection = visible.projection;
  const payment = projection?.payment;
  const attempted = initialCreationAttempted || visible.attempted || Boolean(projection?.creationAttempted);
  const expiredLocally = Boolean(payment?.expiresAt && Date.parse(payment.expiresAt) <= clock);
  const payable = projection?.state === 'awaiting_payment' && projection.providerStatus === 'waiting' && !projection.reviewRequired && !expiredLocally;

  const begin = () => {
    request.current.controller?.abort();
    const value = { serial: request.current.serial + 1, controller: new AbortController(), pending: true };
    request.current = value;
    return value;
  };
  const active = (value, scope) => mounted.current && current.current === scope && request.current.serial === value.serial && !value.controller.signal.aborted;
  const load = async () => {
    if (request.current.pending) return;
    const scope = key, value = begin();
    setResult((old) => ({ ...(old.key === scope ? old : blank(scope)), loading: true, error: '' }));
    try {
      // Two local, owner-bound reads only. No provider call or payment is made by mounting.
      const [cap, status] = await Promise.allSettled([
        getPaymentCapabilities({ principal, client, signal: value.controller.signal }),
        readOrderPayment({ quote, principal, client, signal: value.controller.signal }),
      ]);
      if (!active(value, scope)) return;
      const capabilities = cap.status === 'fulfilled' ? cap.value : null;
      const projection = status.status === 'fulfilled' ? status.value : null;
      setResult((old) => ({ key: scope, loading: false, capabilities, projection,
        attempted: initialCreationAttempted || Boolean(projection?.creationAttempted) || (old.key === scope && old.attempted),
        error: status.status === 'rejected' ? paymentErrorMessage(status.reason) : cap.status === 'rejected' ? paymentErrorMessage(cap.reason) : '',
      }));
      if (capabilities?.currencies.length) setChoice((old) => ({ key: scope, currency: capabilities.currencies.some((item) => item.code === old.currency) ? old.currency : capabilities.currencies[0].code, acknowledged: false }));
    } finally { if (request.current.serial === value.serial) request.current.pending = false; }
  };
  useEffect(() => {
    mounted.current = true;
    request.current.pending = false;
    creationKey.current = null;
    setResult(blank(key));
    setChoice({ key, currency: '', acknowledged: false });
    setCopyStatus({ key, text: '' });
    load();
    return () => { mounted.current = false; request.current.controller?.abort(); };
  }, [key, client]);
  useEffect(() => {
    onLockSelection?.(attempted || Boolean(payment));
    onStageChange?.(projection?.state === 'paid' ? 3 : attempted || payment ? 2 : 1);
  }, [key, attempted, payment, projection?.state, onLockSelection, onStageChange]);
  useEffect(() => {
    setClock(Date.now());
    const expires = payment?.expiresAt ? Date.parse(payment.expiresAt) : null;
    const remaining = expires === null ? 0 : expires - Date.now();
    // One bounded local expiry timer. No status polling, repeat, or network I/O.
    const timer = remaining > 0 && remaining <= 86400000 ? setTimeout(() => setClock(Date.now()), remaining + 1) : null;
    const onVisibility = () => { if (!document.hidden) setClock(Date.now()); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => { if (timer !== null) clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, [key, payment?.expiresAt]);

  const operate = async (creating) => {
    if (request.current.pending) return;
    if (creating && (!visible.capabilities?.enabled || !projection?.canCreate || attempted || !selection.acknowledged || !visible.capabilities.currencies.some((item) => item.code === selection.currency))) return;
    if (!creating && !projection?.canRefresh) return;
    const scope = key, value = begin();
    if (creating) {
      try { creationKey.current ??= paymentCreationKey(); }
      catch (error) { request.current.pending = false; setResult((old) => ({ ...old, error: paymentErrorMessage(error), loading: false })); return; }
      onPersistOrder?.(quote.order.id);
      onLockSelection?.(true);
    }
    setResult((old) => ({ ...old, loading: true, error: '', attempted: creating || old.attempted }));
    try {
      const next = creating
        ? await createOrderPayment({ quote, principal, payCurrency: selection.currency, idempotencyKey: creationKey.current, client, signal: value.controller.signal })
        : await refreshOrderPayment({ quote, principal, client, signal: value.controller.signal });
      if (!active(value, scope)) return;
      setResult((old) => ({ ...old, loading: false, projection: next, attempted: next.creationAttempted, error: '' }));
      setCopyStatus({ key: scope, text: '' });
    } catch (error) {
      if (!active(value, scope)) return;
      setResult((old) => ({ ...old, loading: false, projection: creating ? null : old.projection, attempted: creating || old.attempted, error: paymentErrorMessage(error, { creating }) }));
    } finally { if (request.current.serial === value.serial) request.current.pending = false; }
  };
  const copy = async (value, label) => {
    if (!payable || visible.loading || (payment.expiresAt && Date.parse(payment.expiresAt) <= Date.now())) { setClock(Date.now()); return; }
    const scope = key;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(value);
      if (mounted.current && current.current === scope) setCopyStatus({ key: scope, text: `${label} copied.` });
    } catch { if (mounted.current && current.current === scope) setCopyStatus({ key: scope, text: 'Automatic copying is unavailable. Select and copy the displayed value.' }); }
  };
  const selectedCurrency = visible.capabilities?.currencies.find((item) => item.code === selection.currency);
  const state = attempted && !projection ? 'creation_uncertain' : projection?.state ?? 'unavailable';
  const canCreate = !visible.loading && visible.capabilities?.enabled && projection?.canCreate && !attempted;

  return <section id="payment-details" className="mep-payment-panel mep-panel mep-interior-card rounded-2xl border p-5 sm:p-7" aria-labelledby="order-payment-title" aria-busy={visible.loading || undefined}>
    <div className="flex items-start gap-3">
      <span className="mep-payment-symbol" aria-hidden="true"><ShieldCheck size={22} /></span>
      <div className="min-w-0"><p className="text-xs uppercase tracking-[0.15em] text-cyan-300">Order-bound payment</p>
        <h2 id="order-payment-title" tabIndex={-1} className="mep-heading mt-2 text-2xl font-semibold focus-visible:outline-cyan-300">Payment details</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-400">Only an enabled checkout for this account can request payment. A recorded quote is not a paid purchase.</p>
      </div>
    </div>
    <div className="mep-payment-state mt-6 rounded-xl border p-4" data-state={state} role="status" aria-live="polite">
      <p className="font-semibold">{visible.loading ? 'Checking saved payment information…' : labels[state]}</p>
      {visible.capabilities && !visible.capabilities.enabled && !attempted && !payment && <p className="mt-2 text-sm text-slate-300">Quotes only. Payments are not enabled.</p>}
      {explanations[state] && <p className="mt-2 text-sm leading-relaxed text-slate-300">{explanations[state]}</p>}
      {attempted && projection?.state === 'not_started' && <p className="mt-2 text-sm leading-relaxed text-amber-200">A creation attempt was indicated for this saved order but no provider binding is available. Do not request a replacement; contact support to reconcile the attempt.</p>}
      {expiredLocally && projection?.state !== 'paid' && <p className="mt-2 text-sm font-medium text-amber-200">These payment details have passed their stated expiry. Do not send money; check the saved order.</p>}
      {visible.error && <p className="mt-2 text-sm leading-relaxed text-amber-200">{visible.error}</p>}
    </div>
    {canCreate && <div className="mt-6 space-y-5">
      <label className="block text-sm font-medium" htmlFor="payment-currency">Payment currency and network
        <select id="payment-currency" value={selection.currency} onChange={(event) => setChoice({ key, currency: event.target.value, acknowledged: false })} className="mt-2 w-full rounded-xl border border-slate-700 p-3">
          {visible.capabilities.currencies.map((item) => <option key={item.code} value={item.code}>{item.label} · {item.network}</option>)}
        </select>
      </label>
      <dl className="space-y-2 text-sm"><div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Recorded program total</dt><dd className="font-semibold tabular-nums">{formatUsdFromMinorUnits(quote.order.amountMinor)}</dd></div>
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Provider fee setting</dt><dd>{visible.capabilities.feePaidByUser ? 'Paid by customer' : 'Paid by merchant'}</dd></div>
      </dl>
      <p className="text-xs leading-relaxed text-slate-400">The provider supplies the exact crypto amount and address after creation. Wallet/network sending fees are separate. No money is sent by this button.</p>
      <label className="flex items-start gap-3 rounded-xl border border-slate-700 p-4 text-sm leading-relaxed">
        <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-cyan-400" checked={selection.acknowledged} onChange={(event) => setChoice({ ...selection, key, acknowledged: event.target.checked })} />
        <span>I reviewed {formatUsdFromMinorUnits(quote.order.amountMinor)}, {selectedCurrency?.label} on {selectedCurrency?.network}, and the provider fee setting. This records a program purchase, not an active trading account or payout permission.</span>
      </label>
      <button type="button" className={`${primaryAction} w-full`} disabled={!selection.acknowledged} onClick={() => operate(true)}>Create payment details<ArrowRight size={18} aria-hidden="true" /></button>
    </div>}
    {payment && <div className="mt-6 space-y-5">
      <div className="mep-payment-amount rounded-xl border p-5"><p className="text-xs uppercase tracking-wider text-slate-400">Provider-requested deposit</p><p className="mt-2 text-2xl font-semibold tabular-nums text-cyan-100">{payment.payAmount} <span className="text-base">{payment.label}</span></p><p className="mt-2 text-sm font-medium text-cyan-200">Network: {payment.network}</p></div>
      <p className="text-sm leading-relaxed text-amber-100">{payable ? 'Use exactly this asset and network. Do not use another network or reuse these details for another order. If you already sent funds, check this order instead of sending again.' : 'These details are a stored reference, not an instruction to send more funds. Do not make another deposit or use them for another order.'}</p>
      <div><p className="text-xs text-slate-400">Deposit address</p><div className="mep-payment-copy mt-2"><code className="mep-payment-value">{payment.address}</code><button type="button" className={secondaryAction} disabled={!payable || visible.loading} onClick={() => copy(payment.address, 'Address')} aria-label="Copy deposit address"><Copy size={17} aria-hidden="true" />Copy</button></div></div>
      <div className="flex flex-wrap gap-3"><button type="button" className={secondaryAction} disabled={!payable || visible.loading} onClick={() => copy(payment.payAmount, 'Amount')}><Copy size={16} aria-hidden="true" />Copy exact amount</button></div>
      {payment.memo && <div><p className="text-xs font-semibold text-amber-200">Required memo / tag</p><code className="mep-payment-value mt-2 block">{payment.memo}</code><button className={`${secondaryAction} mt-2`} type="button" disabled={!payable || visible.loading} onClick={() => copy(payment.memo, 'Memo')}>Copy required memo</button></div>}
      <dl className="space-y-3 text-sm">
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Expiry supplied by provider</dt><dd>{payment.expiresAt ? new Date(payment.expiresAt).toLocaleString() : 'Not provided — check before sending'}</dd></div>
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Provider status</dt><dd>{projection.providerStatus ?? 'Not provided'}</dd></div>
        {payment.actuallyPaid !== null && <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Provider-reported deposit</dt><dd className="tabular-nums">{payment.actuallyPaid} {payment.label}</dd></div>}
        {payment.outcomeAmount !== null && <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Provider-reported outcome{state === 'paid' ? '' : ' (not final)'}</dt><dd className="tabular-nums">{payment.outcomeAmount} {payment.outcomeCurrency ?? 'Currency not provided'}</dd></div>}
      </dl>
      {copyStatus.key === key && copyStatus.text && <p role="status" className="text-sm text-cyan-200">{copyStatus.text}</p>}
    </div>}
    {state === 'paid' && <div className="mt-5 flex items-start gap-3 rounded-xl border border-emerald-400/30 bg-emerald-400/5 p-4 text-sm text-emerald-100"><FileCheck size={20} className="shrink-0" aria-hidden="true" /><p>The purchase record is stored for this account. Trading provisioning and payouts remain unavailable.</p></div>}
    <div className="mt-6 flex flex-wrap gap-3">
      {projection?.canRefresh && <button type="button" className={secondaryAction} disabled={visible.loading} onClick={() => operate(false)}><RefreshCw size={17} aria-hidden="true" />Check provider status</button>}
      <button type="button" className={secondaryAction} disabled={visible.loading} onClick={load}><RefreshCw size={17} aria-hidden="true" />Check saved order</button>
      <Link className={secondaryAction} to="/support/create-ticket">Support with this order</Link>
    </div>
    <p className="mt-4 break-all text-xs leading-relaxed text-slate-400">Order reference: {quote.order.id}</p>
    <p className="mt-2 text-xs leading-relaxed text-slate-500">Status checks are explicit. No automatic repeat payment or background status polling is used.</p>
  </section>;
}
