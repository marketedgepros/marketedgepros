import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, AlertCircle, AlertTriangle, Calendar, CheckCircle, Clock, Loader, MessageCircle, RefreshCw, Send, Star, Tag, User } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import Layout from '../../components/layout/Layout';
import SEO from '../../components/SEO';
import useAuthStore from '../../store/authStore';
import {
  addMySupportTicketMessage,
  closeMySupportTicket,
  DEFAULT_MESSAGES_PER_PAGE,
  isSupportTicketRequestCanceled,
  loadMySupportTicketDetail,
  rateMySupportTicket,
} from '../../services/supportTicketViewService';

const getErrorMessage = (error, fallback) => (
  error?.response?.data?.error
  || error?.response?.data?.message
  || error?.message
  || fallback
);

const formatDate = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : date.toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
};

const getStatusBadge = (status) => {
  const badges = {
    open: { color: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30', icon: Clock, label: 'Open' },
    in_progress: { color: 'bg-teal-500/10 text-teal-400 border-teal-500/30', icon: MessageCircle, label: 'In progress' },
    waiting_customer: { color: 'bg-amber-500/10 text-amber-300 border-amber-500/30', icon: AlertTriangle, label: 'Waiting for you' },
    resolved: { color: 'bg-teal-500/10 text-teal-400 border-teal-500/30', icon: CheckCircle, label: 'Resolved' },
    closed: { color: 'bg-gray-500/10 text-gray-400 border-gray-500/30', icon: CheckCircle, label: 'Closed' },
  };
  return badges[status] || badges.open;
};

const getPriorityColor = (priority) => ({
  low: 'text-slate-300', medium: 'text-cyan-400', high: 'text-amber-300', urgent: 'text-red-300',
}[priority] || 'text-slate-300');

const mergeUpdatedTicket = (current, updated) => (current ? {
  ...updated,
  messages: current.messages,
} : current);

export function TicketDetailView({ ticketNumber }) {
  const requestRef = useRef(null);
  const requestSequenceRef = useRef(0);
  const mutationControllerRef = useRef(null);
  const mutationInFlightRef = useRef(false);
  const [ticket, setTicket] = useState(null);
  const [messagePagination, setMessagePagination] = useState(null);
  const [messagePage, setMessagePage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [newMessage, setNewMessage] = useState('');
  const [mutation, setMutation] = useState(null);
  const [mutationError, setMutationError] = useState('');
  const [notice, setNotice] = useState('');

  const loadTicket = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    requestRef.current = controller;

    setLoading(true);
    setError('');
    setMutationError('');
    // A route/page request must not leave another ticket's content on screen.
    setTicket(null);
    setMessagePagination(null);

    try {
      const view = await loadMySupportTicketDetail(ticketNumber, {
        page: messagePage,
        perPage: DEFAULT_MESSAGES_PER_PAGE,
        signal: controller.signal,
      });
      if (requestSequenceRef.current !== requestId || controller.signal.aborted) return;
      setTicket(view.ticket);
      setMessagePagination(view.messagePagination);
    } catch (requestError) {
      if (requestSequenceRef.current !== requestId || isSupportTicketRequestCanceled(requestError)) return;
      setError(getErrorMessage(requestError, 'Unable to load this ticket.'));
    } finally {
      if (requestSequenceRef.current === requestId) {
        setLoading(false);
        if (requestRef.current === controller) requestRef.current = null;
      }
    }
  }, [messagePage, ticketNumber]);

  useEffect(() => {
    loadTicket();
    return () => requestRef.current?.abort();
  }, [loadTicket]);

  useEffect(() => () => mutationControllerRef.current?.abort(), []);

  const runMutation = async (kind, operation, successMessage, applyResult) => {
    if (mutationInFlightRef.current) return;
    const controller = new AbortController();
    const isCurrentMutation = () => (
      mutationControllerRef.current === controller && !controller.signal.aborted
    );
    mutationInFlightRef.current = true;
    mutationControllerRef.current = controller;
    setMutation(kind);
    setMutationError('');
    setNotice('');

    try {
      const result = await operation(controller.signal);
      // Aborting on a route/principal change is advisory to an HTTP client. Do
      // not let an adapter that resolves after abort update this view anyway.
      if (!isCurrentMutation()) return;
      applyResult?.(result);
      if (!isCurrentMutation()) return;
      setNotice(successMessage);
    } catch (requestError) {
      if (isCurrentMutation() && !isSupportTicketRequestCanceled(requestError)) {
        setMutationError(getErrorMessage(requestError, 'The ticket could not be updated. Please try again.'));
      }
    } finally {
      if (mutationControllerRef.current === controller) {
        mutationControllerRef.current = null;
        mutationInFlightRef.current = false;
        if (!controller.signal.aborted) setMutation(null);
      }
    }
  };

  const handleSendMessage = (event) => {
    event.preventDefault();
    const message = newMessage.trim();
    if (!message || !ticket) return;

    runMutation('message', async (signal) => {
      return addMySupportTicketMessage(ticket.ticketNumber, message, undefined, { signal });
      // The server accepted the exact message. Keep the input only after that confirmation;
      // the current message page is refreshed only by the customer's explicit Refresh action.
    }, 'Your reply was sent. Refresh the ticket history when you are ready to review the current message page.', () => {
      setNewMessage('');
    });
  };

  const handleClose = () => {
    if (!ticket) return;
    runMutation('close', async (signal) => {
      return closeMySupportTicket(ticket.id, undefined, { signal });
    }, 'Ticket closed.', (updated) => {
      setTicket((current) => mergeUpdatedTicket(current, updated));
    });
  };

  const handleRate = (rating) => {
    if (!ticket) return;
    runMutation('rating', async (signal) => {
      return rateMySupportTicket(ticket.id, rating, undefined, { signal });
    }, 'Thank you for rating this closed ticket.', (updated) => {
      setTicket((current) => mergeUpdatedTicket(current, updated));
    });
  };

  if (loading) {
    return (
      <Layout>
        <SEO title="Loading Support Ticket" />
        <div className="min-h-screen bg-black flex flex-col items-center justify-center text-gray-300" role="status"><Loader className="w-8 h-8 text-cyan-500 animate-spin mb-4" />Loading ticket…</div>
      </Layout>
    );
  }

  if (error || !ticket) {
    return (
      <Layout>
        <SEO title="Support Ticket" />
        <div className="min-h-screen bg-black flex items-center justify-center px-4">
          <div className="text-center max-w-xl">
            <AlertTriangle className="w-16 h-16 text-red-400 mx-auto mb-4" />
            <h1 className="text-2xl font-bold text-white mb-2">Ticket unavailable</h1>
            <p className="text-gray-400 mb-6">{error || 'This ticket could not be displayed.'}</p>
            <div className="flex flex-wrap justify-center gap-3">
              <button type="button" onClick={loadTicket} className="px-5 py-3 bg-slate-800 text-white rounded-xl hover:bg-slate-700">Try again</button>
              <Link to="/support/my-tickets" className="inline-flex items-center gap-2 px-5 py-3 bg-cyan-600 text-white rounded-xl font-semibold hover:bg-cyan-500"><ArrowLeft className="w-5 h-5" />My tickets</Link>
            </div>
          </div>
        </div>
      </Layout>
    );
  }

  const statusBadge = getStatusBadge(ticket.status);
  const StatusIcon = statusBadge.icon;
  const isClosed = ticket.status === 'closed';
  const isMutating = mutation !== null;

  return (
    <Layout>
      <SEO title={`Ticket #${ticket.ticketNumber} — ${ticket.subject}`} description={ticket.description} />

      <section className="relative pt-32 pb-12 overflow-hidden bg-black">
        <div className="absolute inset-0" aria-hidden="true"><div className="absolute top-20 left-10 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl" /><div className="absolute bottom-20 right-10 w-96 h-96 bg-teal-500/10 rounded-full blur-3xl" /></div>
        <div className="relative max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
            <Link to="/support/my-tickets" className="inline-flex items-center gap-2 text-gray-300 hover:text-white transition-colors"><ArrowLeft className="w-5 h-5" />My tickets</Link>
            <button type="button" onClick={loadTicket} disabled={isMutating} className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50"><RefreshCw className="w-4 h-4" />Refresh</button>
          </div>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-3 mb-3"><span className="font-mono text-lg text-gray-400">#{ticket.ticketNumber}</span><span className={`px-3 py-1 rounded-full text-sm font-medium border ${statusBadge.color} flex items-center gap-1.5`}><StatusIcon className="w-4 h-4" />{statusBadge.label}</span></div>
              <h1 className="text-4xl font-bold text-white mb-3">{ticket.subject}</h1>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-gray-400">
                <span className="flex items-center gap-2"><Calendar className="w-4 h-4" />{formatDate(ticket.createdAt)}</span>
                <span className="flex items-center gap-2"><Tag className="w-4 h-4" />{ticket.category}</span>
                <span className={`flex items-center gap-2 ${getPriorityColor(ticket.priority)}`}><AlertTriangle className="w-4 h-4" />{ticket.priority.charAt(0).toUpperCase() + ticket.priority.slice(1)} priority</span>
              </div>
            </div>
            {!isClosed && <button type="button" onClick={handleClose} disabled={isMutating} className="shrink-0 px-4 py-2 border border-gray-600 text-gray-200 rounded-lg hover:bg-gray-800 disabled:opacity-50">{mutation === 'close' ? 'Closing…' : 'Close ticket'}</button>}
          </div>
        </div>
      </section>

      <section className="py-12 bg-black min-h-[42rem]">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          {notice && <div role="status" className="mb-6 p-4 bg-cyan-500/10 border border-cyan-500/30 rounded-xl text-cyan-100">{notice}</div>}
          {mutationError && <div role="alert" className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl flex gap-3 text-red-300"><AlertCircle className="w-5 h-5 shrink-0" />{mutationError}</div>}

          <article className="bg-slate-900/50 backdrop-blur-sm border border-slate-700 rounded-xl p-6 mb-6">
            <div className="flex items-start gap-4"><div className="w-10 h-10 bg-cyan-500/20 rounded-full flex items-center justify-center shrink-0"><User className="w-5 h-5 text-cyan-400" /></div><div className="flex-1"><div className="flex items-center gap-3 mb-2"><span className="font-semibold text-white">Your original request</span><span className="text-sm text-gray-500">{formatDate(ticket.createdAt)}</span></div><div className="text-gray-300 whitespace-pre-wrap">{ticket.description}</div></div></div>
          </article>

          <section aria-labelledby="ticket-messages-heading" className="space-y-4 mb-6">
            <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="ticket-messages-heading" className="text-xl font-semibold text-white">Messages</h2>{messagePagination && <p className="text-sm text-gray-500">Page {messagePagination.page} of {Math.max(1, messagePagination.totalPages)} · {messagePagination.totalMessages} visible-message record{messagePagination.totalMessages === 1 ? '' : 's'}</p>}</div>
            {ticket.messages.length === 0 ? <p className="rounded-xl border border-slate-700 bg-slate-900/50 p-6 text-gray-400">There are no customer-visible replies on this message page.</p> : ticket.messages.map((message) => (
              <article key={message.id} className={`backdrop-blur-sm border rounded-xl p-6 ${message.isStaff ? 'border-teal-500/30 bg-teal-500/5' : 'border-slate-700 bg-slate-900/50'}`}>
                <div className="flex items-start gap-4"><div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${message.isStaff ? 'bg-teal-500/20' : 'bg-cyan-500/20'}`}><User className={`w-5 h-5 ${message.isStaff ? 'text-teal-400' : 'text-cyan-400'}`} /></div><div className="flex-1"><div className="flex items-center gap-3 mb-2"><span className="font-semibold text-white">{message.isStaff ? 'Support team' : 'You'}</span>{message.isStaff && <span className="px-2 py-0.5 bg-teal-500/20 text-teal-300 text-xs rounded-full border border-teal-500/30">Support</span>}<span className="text-sm text-gray-500">{formatDate(message.createdAt)}</span></div><div className="text-gray-300 whitespace-pre-wrap">{message.message}</div></div></div>
              </article>
            ))}
            {messagePagination && (messagePagination.hasPrev || messagePagination.hasNext) && <nav className="flex justify-between gap-4 pt-2" aria-label="Message pages"><button type="button" disabled={!messagePagination.hasPrev || isMutating} onClick={() => setMessagePage((current) => Math.max(1, current - 1))} className="px-4 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-40">Previous messages</button><button type="button" disabled={!messagePagination.hasNext || isMutating} onClick={() => setMessagePage((current) => current + 1)} className="px-4 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-40">More messages</button></nav>}
          </section>

          {isClosed ? (
            <section className="bg-slate-900/50 border border-slate-700 rounded-xl p-6" aria-labelledby="ticket-rating-heading">
              <CheckCircle className="w-10 h-10 text-gray-300 mb-3" />
              <h2 id="ticket-rating-heading" className="text-lg font-semibold text-white mb-2">This ticket is closed</h2>
              {ticket.rating ? <p className="text-gray-300">You rated this ticket {ticket.rating} out of 5.</p> : <><p className="text-gray-400 mb-4">How was your support experience?</p><div className="flex gap-2" aria-label="Rate this ticket">{[1, 2, 3, 4, 5].map((rating) => <button key={rating} type="button" onClick={() => handleRate(rating)} disabled={isMutating} aria-label={`Rate ${rating} out of 5`} className="p-2 rounded-lg text-amber-300 hover:bg-amber-500/10 disabled:opacity-50"><Star className="w-6 h-6" /></button>)}</div></>}
            </section>
          ) : (
            <section className="bg-slate-900/50 backdrop-blur-sm border border-slate-700 rounded-xl p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Add a reply</h2>
              <form onSubmit={handleSendMessage}>
                <textarea value={newMessage} onChange={(event) => setNewMessage(event.target.value)} placeholder="Type your message here..." rows={6} maxLength={4000} disabled={isMutating} className="w-full px-4 py-3 bg-black border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 resize-none mb-4 disabled:opacity-60" />
                <button type="submit" disabled={isMutating || !newMessage.trim()} className="px-6 py-3 bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-xl font-semibold hover:shadow-lg hover:shadow-cyan-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">{mutation === 'message' ? <><Loader className="w-5 h-5 animate-spin" />Sending…</> : <><Send className="w-5 h-5" />Send reply</>}</button>
              </form>
            </section>
          )}
        </div>
      </section>
    </Layout>
  );
}

/**
 * The data and mutations in a ticket detail are scoped to both the current
 * route and the verified principal. A key forces a fresh view immediately when
 * either changes, so an in-flight operation for ticket A cannot render in B.
 */
export default function TicketDetail() {
  const { ticketNumber = '' } = useParams();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const tenantId = useAuthStore((state) => state.user?.tenant_id ?? null);
  const contextKey = JSON.stringify([isAuthenticated === true, userId, tenantId, ticketNumber]);

  return <TicketDetailView key={contextKey} ticketNumber={ticketNumber} />;
}
