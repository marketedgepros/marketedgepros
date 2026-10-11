import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Check, CheckCircle, Lock, Plus, RefreshCw } from 'lucide-react';
import api from '../services/api';
import useAuthStore from '../store/authStore';
import { ADMIN_ROLES } from '../constants/roles';
import {
  OrderQuoteIdempotencyKeys,
  formatUsdFromMinorUnits,
  normalizeQuoteContext,
  orderQuoteErrorMessage,
  requestOrderQuote,
} from '../services/orderQuoteViewService';

const isPositiveRouteId = (value) => /^\d+$/.test(String(value || '')) && Number(value) > 0 && Number(value) <= 2147483647;

const Checkout = () => {
  const { programId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const [program, setProgram] = useState(null);
  const [addons, setAddons] = useState([]);
  const [selectedAddons, setSelectedAddons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [quote, setQuote] = useState(null);
  const [quoteState, setQuoteState] = useState('idle');
  const [quoteError, setQuoteError] = useState('');
  const mountedRef = useRef(true);
  const programRequestRef = useRef({ id: 0, controller: null });
  const quoteRequestRef = useRef({ id: 0, controller: null });
  const quoteKeysRef = useRef(new OrderQuoteIdempotencyKeys());

  const isAdmin = Boolean(user && ADMIN_ROLES.includes(user.role));
  // A quote is not a purchase. Keep the server's existing quote authorization;
  // payment/entitlement prerequisites belong to their separate server contracts.

  useEffect(() => {
    if (!user) {
      navigate('/login', {
        replace: true,
        state: { from: `/programs/${programId}/checkout` },
      });
    } else if (ADMIN_ROLES.includes(user.role)) {
      navigate('/admin', { replace: true });
    }
  }, [user, navigate, programId]);

  useEffect(() => {
    quoteRequestRef.current.controller?.abort();
    quoteRequestRef.current.id += 1;
    quoteKeysRef.current.invalidate();
    setQuote(null);
    setQuoteState('idle');
    setQuoteError('');
  }, [user?.id]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      programRequestRef.current.controller?.abort();
      quoteRequestRef.current.controller?.abort();
    };
  }, []);

  useEffect(() => {
    programRequestRef.current.controller?.abort();
    quoteRequestRef.current.controller?.abort();
    quoteRequestRef.current.id += 1;
    quoteKeysRef.current.invalidate();
    setProgram(null);
    setAddons([]);
    setSelectedAddons([]);
    setQuote(null);
    setQuoteState('idle');
    setQuoteError('');
    setLoadError('');

    if (!isPositiveRouteId(programId)) {
      setLoading(false);
      setLoadError('The program identifier is invalid.');
      return undefined;
    }

    const controller = new AbortController();
    const requestId = programRequestRef.current.id + 1;
    programRequestRef.current = { id: requestId, controller };
    setLoading(true);

    api.get(`/programs/${Number(programId)}`, { signal: controller.signal })
      .then((response) => {
        if (!mountedRef.current || programRequestRef.current.id !== requestId) return;
        const data = response?.data;
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
          throw new Error('The program response was invalid.');
        }
        setProgram(data);
        setAddons(Array.isArray(data.addons) ? data.addons : []);
        setLoading(false);
      })
      .catch((error) => {
        if (controller.signal.aborted || !mountedRef.current || programRequestRef.current.id !== requestId) return;
        setLoading(false);
        setLoadError(error?.response?.data?.error || error?.message || 'Program details could not be loaded.');
      });

    return () => controller.abort();
  }, [programId]);

  const invalidateQuote = () => {
    quoteRequestRef.current.controller?.abort();
    quoteRequestRef.current.id += 1;
    quoteKeysRef.current.invalidate();
    setQuote(null);
    setQuoteState('idle');
    setQuoteError('');
  };

  const toggleAddon = (addonId) => {
    if (!Number.isSafeInteger(addonId) || addonId < 1) return;
    invalidateQuote();
    setSelectedAddons((current) => (
      current.includes(addonId)
        ? current.filter((id) => id !== addonId)
        : [...current, addonId]
    ));
  };

  const requestQuote = async () => {
    if (!program || !user || isAdmin) return;

    let context;
    try {
      context = normalizeQuoteContext(Number(programId), selectedAddons);
    } catch (error) {
      setQuote(null);
      setQuoteState('error');
      setQuoteError(orderQuoteErrorMessage(error));
      return;
    }

    quoteRequestRef.current.controller?.abort();
    const controller = new AbortController();
    const requestId = quoteRequestRef.current.id + 1;
    quoteRequestRef.current = { id: requestId, controller };
    setQuote(null);
    setQuoteError('');
    setQuoteState('loading');

    try {
      const idempotencyKey = quoteKeysRef.current.forContext(context);
      const nextQuote = await requestOrderQuote({
        programId: context.programId,
        addonIds: context.addonIds,
        idempotencyKey,
        signal: controller.signal,
      });
      if (!mountedRef.current || quoteRequestRef.current.id !== requestId || controller.signal.aborted) return;
      setQuote(nextQuote);
      setQuoteState('quoted');
    } catch (error) {
      if (!mountedRef.current || quoteRequestRef.current.id !== requestId || controller.signal.aborted) return;
      setQuote(null);
      setQuoteState('error');
      // Retry deliberately retains the same key for this unchanged selection.
      setQuoteError(orderQuoteErrorMessage(error));
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center">
        <div className="text-white text-xl">Loading program details…</div>
      </div>
    );
  }

  if (loadError || !program) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center px-4">
        <div className="max-w-lg bg-slate-800/50 backdrop-blur-sm rounded-2xl p-6 border border-slate-700 text-center">
          <p className="text-red-400 font-semibold">{loadError || 'Program not found.'}</p>
          <button
            onClick={() => navigate('/programs')}
            className="mt-5 bg-slate-700 text-white px-4 py-2 rounded-lg hover:bg-slate-600 transition"
          >
            Back to programs
          </button>
        </div>
      </div>
    );
  }

  const quoteButtonDisabled = quoteState === 'loading' || !user || isAdmin;
  const quoteButtonLabel = quoteState === 'loading'
    ? 'Requesting server quote…'
    : quoteState === 'error'
      ? 'Retry server quote'
      : quote
        ? 'Refresh server quote'
        : 'Request server quote';

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 py-12 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-white mb-2">Review your program</h1>
          <p className="text-gray-400">Select add-ons, then request an immutable server-priced quote.</p>
        </div>

        <div className="grid md:grid-cols-2 gap-8">
          <section className="bg-slate-800/50 backdrop-blur-sm rounded-2xl p-6 border border-slate-700">
            <h2 className="text-2xl font-bold text-white mb-4">Program details</h2>
            <div className="space-y-4">
              <div>
                <h3 className="text-xl font-bold text-cyan-400 mb-2">{program.name}</h3>
                {program.description && <p className="text-gray-400">{program.description}</p>}
              </div>

              <div className="border-t border-slate-700 pt-4 space-y-2">
                {program.account_size !== undefined && program.account_size !== null && (
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-400">Account size</span>
                    <span className="text-white font-semibold">{String(program.account_size)}</span>
                  </div>
                )}
                {program.profit_target !== undefined && program.profit_target !== null && (
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-400">Profit target</span>
                    <span className="text-green-400 font-semibold">{String(program.profit_target)}%</span>
                  </div>
                )}
                {program.max_daily_loss !== undefined && program.max_daily_loss !== null && (
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-400">Max daily loss</span>
                    <span className="text-red-400 font-semibold">{String(program.max_daily_loss)}%</span>
                  </div>
                )}
                {program.profit_split !== undefined && program.profit_split !== null && (
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-400">Profit split</span>
                    <span className="text-cyan-400 font-semibold">{String(program.profit_split)}%</span>
                  </div>
                )}
              </div>

              {addons.length > 0 && (
                <div className="border-t border-slate-700 pt-4">
                  <h3 className="text-lg font-bold text-white mb-3 flex items-center">
                    <Plus className="mr-2 text-cyan-400" />
                    Optional add-ons
                  </h3>
                  <div className="space-y-2">
                    {addons.map((addon) => {
                      const selected = selectedAddons.includes(addon.id);
                      return (
                        <button
                          type="button"
                          key={addon.id}
                          onClick={() => toggleAddon(addon.id)}
                          className={`w-full text-left p-3 rounded-lg border transition-all ${
                            selected
                              ? 'bg-cyan-500/20 border-cyan-500'
                              : 'bg-slate-900/50 border-slate-700 hover:border-slate-600'
                          }`}
                        >
                          <div className="flex items-start">
                            <div className={`w-5 h-5 rounded border-2 flex items-center justify-center mr-2 mt-0.5 flex-shrink-0 ${
                              selected ? 'bg-cyan-500 border-cyan-500' : 'border-slate-600'
                            }`}>
                              {selected && <Check className="w-3 h-3 text-white" />}
                            </div>
                            <div>
                              <span className="font-semibold text-white">{addon.name}</span>
                              {addon.description && <p className="text-sm text-gray-400 mt-1">{addon.description}</p>}
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="border-t border-slate-700 pt-4">
                <div className="flex justify-between items-center gap-4">
                  <span className="text-xl font-bold text-white">Server quote</span>
                  <span className="text-right text-cyan-400 font-bold">
                    {quote ? formatUsdFromMinorUnits(quote.order.amountMinor) : 'Not requested'}
                  </span>
                </div>
                <p className="text-sm text-gray-400 mt-2">
                  Totals are calculated only by the server after you request a quote.
                </p>
              </div>
            </div>
          </section>

          <section className="bg-slate-800/50 backdrop-blur-sm rounded-2xl p-6 border border-slate-700">
            <h2 className="text-2xl font-bold text-white mb-4">Quote status</h2>

            {isAdmin && (
              <div className="bg-yellow-500/10 border border-yellow-500 text-yellow-300 px-4 py-3 rounded-lg mb-4">
                Administrative accounts cannot purchase programs.
              </div>
            )}
            {quoteError && (
              <div className="bg-red-500/10 border border-red-500 text-red-300 px-4 py-3 rounded-lg mb-4" role="alert">
                {quoteError}
              </div>
            )}

            <div className="bg-slate-900/50 rounded-lg border border-slate-700 p-4 mb-5">
              <p className="text-sm text-gray-400">Current state</p>
              <p className="text-lg font-semibold text-white mt-1">
                {quoteState === 'loading' && 'Requesting quote'}
                {quoteState === 'quoted' && 'Quoted'}
                {quoteState === 'error' && 'Quote request failed'}
                {quoteState === 'idle' && 'Not requested'}
              </p>
              {quote && (
                <>
                  <p className="text-sm text-cyan-300 mt-2">Order state: {quote.order.state}</p>
                  <p className="text-sm text-gray-300">Payment status: not paid</p>
                  {quote.replayed && <p className="text-sm text-gray-400 mt-2">Existing quote returned for this selection.</p>}
                </>
              )}
            </div>

            {quote && (
              <div className="border-t border-slate-700 pt-4 mb-5">
                <h3 className="text-lg font-bold text-white mb-3">Immutable quote summary</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-400">Base amount</span>
                    <span className="text-white">USD {quote.order.snapshot.baseAmount}</span>
                  </div>
                  {quote.order.snapshot.addons.map((addon) => (
                    <div className="flex justify-between gap-4" key={addon.id}>
                      <span className="text-gray-400">{addon.name}</span>
                      <span className="text-white">USD {addon.amount}</span>
                    </div>
                  ))}
                  <div className="border-t border-slate-700 pt-2 flex justify-between gap-4 font-semibold">
                    <span className="text-white">Quoted total</span>
                    <span className="text-cyan-400">{formatUsdFromMinorUnits(quote.order.amountMinor)}</span>
                  </div>
                </div>
              </div>
            )}

            <button
              type="button"
              onClick={requestQuote}
              disabled={quoteButtonDisabled}
              className="w-full bg-gradient-to-r from-cyan-500 to-teal-500 text-white py-4 rounded-lg font-bold text-lg hover:shadow-lg hover:shadow-cyan-500/50 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
            >
              {quoteState === 'error' ? <RefreshCw className="mr-2" /> : <Lock className="mr-2" />}
              {quoteButtonLabel}
            </button>

            <div className="mt-5 bg-cyan-500/10 border border-cyan-500/50 rounded-lg p-4">
              <div className="flex items-start text-cyan-100">
                <CheckCircle className="w-5 h-5 mr-2 mt-0.5 flex-shrink-0 text-cyan-400" />
                <p className="text-sm">
                  Payment integrations must be verified and enabled by the server before payment can be offered.
                  This page only creates an unpaid quote; it does not initiate a provider, wallet transfer, account activation, or funding.
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};

export default Checkout;
