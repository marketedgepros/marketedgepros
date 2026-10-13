import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle, Loader, Send } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/layout/Layout';
import SEO from '../../components/SEO';
import useAuthStore from '../../store/authStore';
import {
  CUSTOMER_TICKET_CATEGORIES,
  CUSTOMER_TICKET_PRIORITIES,
  createMySupportTicket,
  isSupportTicketRequestCanceled,
  supportPrincipalFromAuth,
} from '../../services/supportTicketViewService';

const EMPTY_DRAFT = { subject: '', category: 'general', priority: 'medium', description: '' };

const CATEGORY_LABELS = {
  general: 'General inquiry',
  technical: 'Technical support',
  billing: 'Billing and payments',
  account: 'Account management',
};

const PRIORITY_LABELS = {
  low: 'Low — general question',
  medium: 'Medium — need assistance',
  high: 'High — urgent issue',
  urgent: 'Urgent — critical problem',
};

const displayAccountName = (user) => {
  const firstName = typeof user?.first_name === 'string' ? user.first_name.trim() : '';
  const lastName = typeof user?.last_name === 'string' ? user.last_name.trim() : '';
  const fullName = [firstName, lastName].filter(Boolean).join(' ');
  return fullName || (typeof user?.name === 'string' && user.name.trim() ? user.name.trim() : '');
};

const getErrorMessage = (error, fallback) => (
  error?.response?.data?.error || error?.response?.data?.message || error?.message || fallback
);

const SupportUnavailable = () => (
  <Layout>
    <SEO title="Support" description="Access support resources for your account." />
    <main className="min-h-screen bg-black px-4 pt-28 sm:px-6 sm:pt-32">
      <section className="mep-panel mx-auto max-w-xl rounded-xl border p-6 text-center sm:p-8" role="status">
        <h1 className="mep-heading text-2xl font-bold text-white">Support is unavailable</h1>
        <p className="mt-3 text-gray-400">Please sign in with a verified account context before creating a support ticket.</p>
      </section>
    </main>
  </Layout>
);

export function CreateTicketView({ user, expectedOwner }) {
  const navigate = useNavigate();
  const submitControllerRef = useRef(null);
  const mutationInFlightRef = useRef(false);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [createdTicket, setCreatedTicket] = useState(null);

  const accountName = displayAccountName(user);
  const accountEmail = typeof user?.email === 'string' && user.email.trim() ? user.email.trim() : '';

  useEffect(() => () => submitControllerRef.current?.abort(), []);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setDraft((current) => ({ ...current, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!expectedOwner) return;
    if (mutationInFlightRef.current) return;

    const controller = new AbortController();
    const isCurrentSubmit = () => submitControllerRef.current === controller && !controller.signal.aborted;
    mutationInFlightRef.current = true;
    submitControllerRef.current = controller;
    setIsSubmitting(true);
    setError('');

    try {
      // Identity is not part of this body; the backend derives it from authentication.
      const ticket = await createMySupportTicket(draft, undefined, {
        signal: controller.signal,
        expectedOwner,
      });
      if (isCurrentSubmit()) setCreatedTicket(ticket);
    } catch (requestError) {
      if (isCurrentSubmit() && !isSupportTicketRequestCanceled(requestError)) {
        setError(getErrorMessage(
          requestError,
          'We could not confirm whether the ticket was created. Check My tickets before submitting again.',
        ));
      }
    } finally {
      if (submitControllerRef.current === controller) {
        submitControllerRef.current = null;
        mutationInFlightRef.current = false;
        if (!controller.signal.aborted) setIsSubmitting(false);
      }
    }
  };

  if (!expectedOwner) return <SupportUnavailable />;

  if (createdTicket) {
    return (
      <Layout>
        <SEO title="Support" description="Access support resources for your account." />
        <main className="min-h-screen bg-black px-4 py-16 sm:px-6 sm:py-20">
          <section className="mep-panel mx-auto max-w-2xl rounded-2xl border p-6 text-center sm:p-10">
            <CheckCircle className="mx-auto mb-5 h-12 w-12 text-cyan-400" aria-hidden="true" />
            <h1 className="mep-heading text-3xl font-bold text-white">Ticket created</h1>
            <p className="mt-4 text-gray-300">Your ticket number is:</p>
            <p className="mt-2 break-all font-mono text-2xl font-bold text-cyan-400">#{createdTicket.ticketNumber}</p>
            <p className="mt-5 text-gray-400">You can review this request and customer-visible replies in your ticket list.</p>
            <div className="mt-7 flex flex-wrap justify-center gap-3">
              <button type="button" onClick={() => navigate(`/support/ticket/${encodeURIComponent(createdTicket.ticketNumber)}`)} className="mep-primary px-6 py-3 font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-slate-950">
                View ticket
              </button>
              <button type="button" onClick={() => { setCreatedTicket(null); setDraft(EMPTY_DRAFT); setError(''); }} className="rounded-xl bg-slate-700 px-6 py-3 font-semibold text-white transition-colors hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-slate-950">
                Create another ticket
              </button>
            </div>
          </section>
        </main>
      </Layout>
    );
  }

  return (
    <Layout>
      <SEO title="Support" description="Access support resources for your account." />
      <main className="min-h-screen bg-black">
        <header className="border-b border-slate-800 px-4 pb-8 pt-24 sm:px-6 sm:pb-10 sm:pt-28 lg:px-8">
          <div className="mx-auto max-w-3xl">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-400">Support</p>
            <h1 className="mep-heading mt-2 text-3xl font-bold text-white sm:text-4xl">Create a support ticket</h1>
            <p className="mt-3 max-w-2xl text-base text-gray-300 sm:text-lg">Describe an issue for the account you are signed in to. The support service associates the request with that account.</p>
          </div>
        </header>

        <section className="px-4 py-8 sm:px-6 sm:py-10 lg:px-8">
          <div className="mx-auto max-w-3xl">
            {error && <div role="alert" className="mb-6 flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-300"><AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" /><p className="break-words">{error}</p></div>}

            <form onSubmit={handleSubmit} className="space-y-6 rounded-2xl border border-slate-700 bg-slate-900/50 p-4 sm:p-7">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-300" htmlFor="ticket-account-name">Signed-in account</label>
                  <input id="ticket-account-name" type="text" value={accountName || 'Authenticated account'} readOnly disabled={isSubmitting} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-gray-300 disabled:opacity-60" />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-300" htmlFor="ticket-account-email">Account email</label>
                  <input id="ticket-account-email" type="text" value={accountEmail || 'Account email unavailable'} readOnly disabled={isSubmitting} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-gray-300 disabled:opacity-60" />
                </div>
              </div>
              <p className="-mt-3 text-sm text-gray-400">Account identity is derived by the support service and is not sent from this form.</p>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-300" htmlFor="ticket-subject">Subject *</label>
                <input id="ticket-subject" type="text" name="subject" value={draft.subject} onChange={handleChange} required maxLength={500} disabled={isSubmitting} className="w-full rounded-xl border border-slate-700 bg-black px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60" placeholder="Brief description of your issue" />
              </div>

              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-300" htmlFor="ticket-category">Category *</label>
                  <select id="ticket-category" name="category" value={draft.category} onChange={handleChange} disabled={isSubmitting} className="w-full rounded-xl border border-slate-700 bg-black px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60">
                    {CUSTOMER_TICKET_CATEGORIES.map((category) => <option key={category} value={category}>{CATEGORY_LABELS[category]}</option>)}
                  </select>
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-300" htmlFor="ticket-priority">Priority *</label>
                  <select id="ticket-priority" name="priority" value={draft.priority} onChange={handleChange} disabled={isSubmitting} className="w-full rounded-xl border border-slate-700 bg-black px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60">
                    {CUSTOMER_TICKET_PRIORITIES.map((priority) => <option key={priority} value={priority}>{PRIORITY_LABELS[priority]}</option>)}
                  </select>
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-300" htmlFor="ticket-description">Description *</label>
                <textarea id="ticket-description" name="description" value={draft.description} onChange={handleChange} required rows={6} maxLength={20000} disabled={isSubmitting} className="w-full resize-none rounded-xl border border-slate-700 bg-black px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60" placeholder="Please provide as much detail as possible about your issue..." />
              </div>

              <button type="submit" disabled={isSubmitting} className="mep-primary flex w-full items-center justify-center gap-2 px-6 py-3 font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
                {isSubmitting ? <><Loader className="h-5 w-5 animate-spin" aria-hidden="true" />Creating ticket…</> : <><Send className="h-5 w-5" aria-hidden="true" />Submit ticket</>}
              </button>
            </form>
          </div>
        </section>
      </main>
    </Layout>
  );
}

export default function CreateTicket() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const principal = useMemo(
    () => supportPrincipalFromAuth(user, isAuthenticated === true),
    [isAuthenticated, user?.id, user?.tenant_id, user?.role],
  );
  return <CreateTicketView key={principal?.key ?? 'support-unavailable'} user={user} expectedOwner={principal?.owner} />;
}
