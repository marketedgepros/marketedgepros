import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, FileCheck, RefreshCw } from 'lucide-react';
import api from '../../services/api.js';
import { formatUsdFromMinorUnits } from '../../services/orderQuoteViewService.js';
import { paymentErrorMessage, readPurchaseRecords } from '../../services/orderPaymentViewService.js';
import { secondaryAction } from '../programs/CatalogUI';
import './paymentFlow.css';

const labels = { not_started: 'Not requested', awaiting_payment: 'Awaiting payment', creation_uncertain: 'Creation needs verification', processing: 'Provider processing', manual_review: 'Manual review needed', paid: 'Purchase recorded', expired: 'Expired', failed: 'Failed', unavailable: 'Unavailable' };
const empty = (key) => ({ key, loading: true, data: null, error: '' });
export default function ProgramPurchaseRecords({ principal, ownOnly = true, client = api }) {
  const scope = `${principal?.id}:${principal?.tenant_id}:${principal?.role}:${ownOnly}`;
  const [paging, setPaging] = useState({ scope, page: 1 });
  const page = paging.scope === scope ? paging.page : 1;
  const key = `${scope}:${page}`;
  const current = useRef(key); current.current = key;
  const pending = useRef({ serial: 0, controller: null, busy: false });
  const mounted = useRef(false);
  const [result, setResult] = useState(() => empty(key));
  const visible = result.key === key ? result : empty(key);
  const titleId = ownOnly ? 'account-program-purchases' : 'admin-program-purchases';
  const load = async () => {
    if (!principal || pending.current.busy) return;
    pending.current.controller?.abort();
    const attempt = { serial: pending.current.serial + 1, controller: new AbortController(), busy: true };
    pending.current = attempt;
    const scopeKey = key;
    setResult(empty(scopeKey));
    try {
      const data = await readPurchaseRecords({ principal, ownOnly, page, client, signal: attempt.controller.signal });
      if (mounted.current && current.current === scopeKey && pending.current.serial === attempt.serial && !attempt.controller.signal.aborted) setResult({ key: scopeKey, loading: false, data, error: '' });
    } catch (error) {
      if (mounted.current && current.current === scopeKey && pending.current.serial === attempt.serial && !attempt.controller.signal.aborted) setResult({ key: scopeKey, loading: false, data: null, error: paymentErrorMessage(error) });
    } finally { if (pending.current.serial === attempt.serial) pending.current.busy = false; }
  };
  useEffect(() => {
    mounted.current = true;
    pending.current.busy = false;
    if (principal) load();
    else setResult({ key, loading: false, data: null, error: 'Sign in to view your stored purchase records.' });
    return () => { mounted.current = false; pending.current.controller?.abort(); };
  }, [key, client]);
  const move = (next) => { if (!visible.loading && !pending.current.busy) setPaging({ scope, page: next }); };
  const data = visible.data;
  return <section className="mep-purchase-records mep-panel mep-interior-card rounded-2xl border border-cyan-400/20 p-5 sm:p-6" aria-labelledby={titleId} aria-busy={visible.loading || undefined}>
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0">
      <p className="text-xs uppercase tracking-[0.16em] text-cyan-300">Stored order evidence</p>
      <h2 id={titleId} className="mep-heading mt-2 text-xl font-semibold text-slate-100">Program purchase records</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">{ownOnly ? 'Return to a saved purchase without creating another payment.' : 'Current-brand program purchases, separate from legacy payment records.'} Quoted USD is a program price, not a wallet balance, merchant net receipt or profit.</p>
    </div><button type="button" className={secondaryAction} disabled={visible.loading || !principal} onClick={load}><RefreshCw size={16} aria-hidden="true" />Refresh purchase records</button></div>
    {visible.loading && <p className="mt-5 text-sm text-slate-300" role="status">Loading stored purchase records…</p>}
    {visible.error && <p role="alert" className="mt-5 rounded-xl border border-amber-400/30 p-4 text-sm leading-relaxed text-amber-100">{visible.error} This is not an empty financial result.</p>}
    {data && !data.available && <p role="status" className="mt-5 rounded-xl border border-slate-700 p-4 text-sm leading-relaxed text-slate-300">Program purchase records are not currently available from this source. No zero balance or completed purchase is being assumed.</p>}
    {data?.available && data.records.length === 0 && <p role="status" className="mt-5 text-sm leading-relaxed text-slate-300">No program purchase records were returned for this page. This is not a statement about wallet funds or trading eligibility.</p>}
    {data?.available && data.records.length > 0 && <div className="mt-6 grid gap-4 lg:grid-cols-2">
      {data.records.map((row) => <article key={row.orderId} className="mep-panel rounded-xl border border-slate-700/70 p-4 sm:p-5">
        <div className="flex items-start gap-3"><FileCheck className="mt-1 shrink-0 text-cyan-300" size={19} aria-hidden="true" /><div className="min-w-0"><h3 className="break-words font-semibold text-slate-100">{row.programName ?? `Program #${row.programId} — name not provided`}</h3><p className={`mt-2 text-sm ${row.state === 'paid' ? 'text-emerald-200' : row.reviewRequired ? 'text-amber-200' : 'text-cyan-200'}`}>{labels[row.state]}{row.paid && row.state === 'manual_review' ? ' — prior purchase record retained' : ''}</p></div></div>
        <dl className="mt-4 space-y-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Immutable quoted total</dt><dd className="tabular-nums text-slate-100">{formatUsdFromMinorUnits(row.amountMinor)}</dd></div>
          {!ownOnly && <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Account reference</dt><dd>{row.userId}</dd></div>}
          <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Payment asset / network</dt><dd>{row.payCurrency ?? 'Not provided'} / {row.network ?? 'Not provided'}</dd></div>
          <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Provider-reported deposit</dt><dd className="tabular-nums">{row.actuallyPaid === null ? 'Not provided' : `${row.actuallyPaid} ${row.payCurrency ?? '(asset not provided)'}`}</dd></div>
          <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Provider-reported outcome{row.state === 'paid' ? '' : ' (not final)'}</dt><dd className="tabular-nums">{row.outcomeAmount === null ? 'Not provided' : `${row.outcomeAmount} ${row.outcomeCurrency ?? '(asset not provided)'}`}</dd></div>
          <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-400">Record updated</dt><dd>{row.updatedAt ? new Date(row.updatedAt).toLocaleString() : 'Not provided'}</dd></div>
        </dl><p className="mt-4 break-all text-xs leading-relaxed text-slate-500">Order: {row.orderId}</p>
        {ownOnly && <Link to={`/programs/${row.programId}/checkout?order=${encodeURIComponent(row.orderId)}`} className={`${secondaryAction} mt-4 w-full`}>View saved purchase<ArrowRight size={16} aria-hidden="true" /></Link>}
        <p className="mt-3 text-xs leading-relaxed text-slate-500">A recorded purchase is not an active trading account, payout permission or affiliate commission.</p>
      </article>)}
    </div>}
    {data?.available && <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-700/60 pt-4"><p className="text-xs text-slate-400">{data.pagination.total} scoped {data.pagination.total === 1 ? 'record' : 'records'} · page {data.pagination.page}{data.pagination.pages ? ` of ${data.pagination.pages}` : ''}</p><nav aria-label={ownOnly ? 'Your purchase record pages' : 'Admin purchase record pages'} className="flex flex-wrap gap-2"><button type="button" className={secondaryAction} disabled={visible.loading || !data.pagination.hasPrev} onClick={() => move(page - 1)}>Previous purchase page</button><button type="button" className={secondaryAction} disabled={visible.loading || !data.pagination.hasNext || page * data.pagination.perPage > 10000} onClick={() => move(page + 1)}>Next purchase page</button></nav></div>}
  </section>;
}
