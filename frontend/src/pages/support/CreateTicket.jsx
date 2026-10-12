import { useEffect, useRef, useState } from 'react';
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
} from '../../services/supportTicketViewService';

const EMPTY_DRAFT = {
  subject: '',
  category: 'general',
  priority: 'medium',
  description: '',
};

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
  error?.response?.data?.error
  || error?.response?.data?.message
  || error?.message
  || fallback
);

export function CreateTicketView({ user }) {
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
    if (mutationInFlightRef.current) return;

    const controller = new AbortController();
    const isCurrentSubmit = () => (
      submitControllerRef.current === controller && !controller.signal.aborted
    );
    mutationInFlightRef.current = true;
    submitControllerRef.current = controller;
    setIsSubmitting(true);
    setError('');

    try {
      // Do not send name or email: the authenticated backend derives ticket ownership.
      const ticket = await createMySupportTicket(draft, undefined, { signal: controller.signal });
      if (isCurrentSubmit()) setCreatedTicket(ticket);
    } catch (requestError) {
      if (isCurrentSubmit() && !isSupportTicketRequestCanceled(requestError)) {
        setError(getErrorMessage(requestError, 'Unable to create the ticket. Your details were not submitted.'));
      }
    } finally {
      if (submitControllerRef.current === controller) {
        submitControllerRef.current = null;
        mutationInFlightRef.current = false;
        if (!controller.signal.aborted) setIsSubmitting(false);
      }
    }
  };

  if (createdTicket) {
    return (
      <Layout>
        <SEO title="Ticket Created" />
        <section className="min-h-screen bg-black flex items-center justify-center py-20">
          <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <div className="bg-slate-900/50 backdrop-blur-sm border border-cyan-500/30 rounded-2xl p-12">
              <div className="w-20 h-20 bg-cyan-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <CheckCircle className="w-12 h-12 text-cyan-400" />
              </div>
              <h1 className="text-4xl font-bold text-white mb-4">Ticket created</h1>
              <p className="text-xl text-gray-300 mb-2">Your ticket number is:</p>
              <p className="text-3xl font-mono font-bold text-cyan-400 mb-6">#{createdTicket.ticketNumber}</p>
              <p className="text-gray-400 mb-8">
                You can review this request and any customer-visible replies from your ticket list.
              </p>
              <div className="flex flex-wrap gap-4 justify-center">
                <button
                  type="button"
                  onClick={() => navigate(`/support/ticket/${encodeURIComponent(createdTicket.ticketNumber)}`)}
                  className="px-8 py-4 bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-xl font-semibold hover:shadow-lg hover:shadow-cyan-500/50 transition-all"
                >
                  View ticket
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCreatedTicket(null);
                    setDraft(EMPTY_DRAFT);
                    setError('');
                  }}
                  className="px-8 py-4 bg-slate-700 text-white rounded-xl font-semibold hover:bg-slate-600 transition-all"
                >
                  Create another ticket
                </button>
              </div>
            </div>
          </div>
        </section>
      </Layout>
    );
  }

  return (
    <Layout>
      <SEO
        title="Create Support Ticket"
        description="Create an authenticated support request for your account."
        keywords="support ticket, help, customer service"
      />

      <section className="relative pt-32 pb-12 overflow-hidden bg-black">
        <div className="absolute inset-0" aria-hidden="true">
          <div className="absolute top-20 left-10 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl" />
          <div className="absolute bottom-20 right-10 w-96 h-96 bg-teal-500/10 rounded-full blur-3xl" />
        </div>
        <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-5xl md:text-6xl font-bold text-white mb-6">
            Create Support <span className="bg-gradient-to-r from-cyan-400 to-teal-400 bg-clip-text text-transparent">Ticket</span>
          </h1>
          <p className="text-xl text-gray-300">Describe your issue for the account you are signed in to. Your request is associated with that account.</p>
        </div>
      </section>

      <section className="py-12 bg-black">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          {error && (
            <div role="alert" className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-red-400">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="bg-slate-900/50 backdrop-blur-sm border border-slate-700 rounded-2xl p-8 space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="ticket-account-name">Signed-in account</label>
                <input
                  id="ticket-account-name"
                  type="text"
                  value={accountName || 'Authenticated account'}
                  readOnly
                  className="w-full px-4 py-3 bg-slate-950 border border-slate-700 rounded-xl text-gray-300 cursor-not-allowed"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="ticket-account-email">Account email</label>
                <input
                  id="ticket-account-email"
                  type="text"
                  value={accountEmail || 'Account email unavailable'}
                  readOnly
                  className="w-full px-4 py-3 bg-slate-950 border border-slate-700 rounded-xl text-gray-300 cursor-not-allowed"
                />
              </div>
            </div>
            <p className="text-sm text-gray-400 -mt-3">Account identity is derived by the support service and is not sent from this form.</p>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="ticket-subject">Subject *</label>
              <input
                id="ticket-subject"
                type="text"
                name="subject"
                value={draft.subject}
                onChange={handleChange}
                required
                maxLength={500}
                disabled={isSubmitting}
                className="w-full px-4 py-3 bg-black border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60"
                placeholder="Brief description of your issue"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="ticket-category">Category *</label>
                <select id="ticket-category" name="category" value={draft.category} onChange={handleChange} disabled={isSubmitting} className="w-full px-4 py-3 bg-black border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60">
                  {CUSTOMER_TICKET_CATEGORIES.map((category) => <option key={category} value={category}>{CATEGORY_LABELS[category]}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="ticket-priority">Priority *</label>
                <select id="ticket-priority" name="priority" value={draft.priority} onChange={handleChange} disabled={isSubmitting} className="w-full px-4 py-3 bg-black border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60">
                  {CUSTOMER_TICKET_PRIORITIES.map((priority) => <option key={priority} value={priority}>{PRIORITY_LABELS[priority]}</option>)}
                </select>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="ticket-description">Description *</label>
              <textarea
                id="ticket-description"
                name="description"
                value={draft.description}
                onChange={handleChange}
                required
                rows={6}
                maxLength={20000}
                disabled={isSubmitting}
                className="w-full px-4 py-3 bg-black border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 resize-none disabled:opacity-60"
                placeholder="Please provide as much detail as possible about your issue..."
              />
            </div>

            <button type="submit" disabled={isSubmitting} className="w-full px-8 py-4 bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-xl font-semibold hover:shadow-lg hover:shadow-cyan-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
              {isSubmitting ? <><Loader className="w-5 h-5 animate-spin" />Creating ticket…</> : <><Send className="w-5 h-5" />Submit ticket</>}
            </button>
          </form>
        </div>
      </section>
    </Layout>
  );
}

/** A draft belongs to the verified account, never to the browser tab alone. */
export default function CreateTicket() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const contextKey = JSON.stringify([
    isAuthenticated === true,
    user?.id ?? null,
    user?.tenant_id ?? null,
  ]);

  return <CreateTicketView key={contextKey} user={user} />;
}
