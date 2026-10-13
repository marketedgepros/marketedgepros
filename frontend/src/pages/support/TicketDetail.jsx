import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  supportPrincipalFromAuth,
} from '../../services/supportTicketViewService';

const getErrorMessage = (error, fallback) => (
  error?.response?.data?.error || error?.response?.data?.message || error?.message || fallback
);

const formatDate = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
};

const getStatusBadge = (status) => ({
  open: { color: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30', icon: Clock, label: 'Open' },
  in_progress: { color: 'bg-teal-500/10 text-teal-400 border-teal-500/30', icon: MessageCircle, label: 'In progress' },
  waiting_customer: { color: 'bg-amber-500/10 text-amber-300 border-amber-500/30', icon: AlertTriangle, label: 'Waiting for you' },
  resolved: { color: 'bg-teal-500/10 text-teal-400 border-teal-500/30', icon: CheckCircle, label: 'Resolved' },
  closed: { color: 'bg-gray-500/10 text-gray-400 border-gray-500/30', icon: CheckCircle, label: 'Closed' },
}[status]);

const getPriorityColor = (priority) => ({
  low: 'text-slate-300', medium: 'text-cyan-400', high: 'text-amber-300', urgent: 'text-red-300',
}[priority]);

const mergeUpdatedTicket = (current, updated) => (current ? { ...updated, messages: current.messages } : current);

const Unavailable = () => (
  <Layout>
    <SEO title="Support" description="Access support resources for your account." />
    <main className="min-h-screen bg-black px-4 pt-28 sm:px-6 sm:pt-32">
      <section className="mep-panel mx-auto max-w-xl rounded-xl border p-6 text-center sm:p-8" role="status">
        <h1 className="mep-heading text-2xl font-bold text-white">Ticket unavailable</h1>
        <p className="mt-3 text-gray-400">Please sign in with a verified account context before viewing support tickets.</p>
      </section>
    </main>
  </Layout>
);

export function TicketDetailView({ ticketNumber, expectedOwner }) {
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
    if (mutationInFlightRef.current) return;
    requestRef.current?.abort();
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;

    if (!expectedOwner) {
      requestRef.current = null;
      setLoading(false);
      setTicket(null);
      setMessagePagination(null);
      setError('');
      return;
    }

    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError('');
    // A route/page request must not leave another ticket's content on screen.
    setTicket(null);
    setMessagePagination(null);

    try {
      const view = await loadMySupportTicketDetail(ticketNumber, {
        page: messagePage,
        perPage: DEFAULT_MESSAGES_PER_PAGE,
        signal: controller.signal,
        expectedOwner,
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
  }, [expectedOwner, messagePage, ticketNumber]);

  useEffect(() => {
    loadTicket();
    return () => requestRef.current?.abort();
  }, [loadTicket]);

  useEffect(() => () => mutationControllerRef.current?.abort(), []);

  const runMutation = async (kind, operation, successMessage, applyResult) => {
    if (!expectedOwner || mutationInFlightRef.current) return;
    // A read that started before the write cannot replace the confirmed mutation.
    requestSequenceRef.current += 1;
    requestRef.current?.abort();
    requestRef.current = null;

    const controller = new AbortController();
    const isCurrentMutation = () => mutationControllerRef.current === controller && !controller.signal.aborted;
    mutationInFlightRef.current = true;
    mutationControllerRef.current = controller;
    setMutation(kind);
    setMutationError('');
    setNotice('');

    try {
      const result = await operation(controller.signal);
      if (!isCurrentMutation()) return;
      applyResult?.(result);
      if (isCurrentMutation()) setNotice(successMessage);
    } catch (requestError) {
      if (isCurrentMutation() && !isSupportTicketRequestCanceled(requestError)) {
        setMutationError(getErrorMessage(
          requestError,
          'We could not confirm this change. Refresh the ticket before trying again.',
        ));
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
    runMutation('message', (signal) => addMySupportTicketMessage(ticket.ticketNumber, message, undefined, {
      signal,
      expectedOwner,
      expectedTicketId: ticket.id,
    }), 'Your reply was confirmed. Refresh the ticket history when you are ready to review the current message page.', () => {
      setNewMessage('');
    });
  };

  const handleClose = () => {
    if (!ticket) return;
    runMutation('close', (signal) => closeMySupportTicket(ticket.id, undefined, { signal, expectedOwner }), 'Ticket closed.', (updated) => {
      setTicket((current) => mergeUpdatedTicket(current, updated));
    });
  };

  const handleRate = (rating) => {
    if (!ticket) return;
    runMutation('rating', (signal) => rateMySupportTicket(ticket.id, rating, undefined, { signal, expectedOwner }), 'Thank you for rating this closed ticket.', (updated) => {
      setTicket((current) => mergeUpdatedTicket(current, updated));
    });
  };

  if (!expectedOwner) return <Unavailable />;

  if (loading) {
    return <Layout><SEO title="Support" description="Access support resources for your account." /><main className="flex min-h-screen flex-col items-center justify-center bg-black px-4 text-gray-300" role="status"><Loader className="mb-4 h-8 w-8 animate-spin text-cyan-500" aria-hidden="true" />Loading ticket…</main></Layout>;
  }

  if (error || !ticket) {
    return <Layout><SEO title="Support" description="Access support resources for your account." /><main className="flex min-h-screen items-center justify-center bg-black px-4"><section role="alert" className="max-w-xl text-center"><AlertTriangle className="mx-auto mb-4 h-14 w-14 text-red-400" aria-hidden="true" /><h1 className="mep-heading text-2xl font-bold text-white">Ticket unavailable</h1><p className="mt-2 break-words text-gray-400">{error || 'This ticket could not be displayed.'}</p><div className="mt-6 flex flex-wrap justify-center gap-3"><button type="button" onClick={loadTicket} className="rounded-xl bg-slate-800 px-5 py-3 text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400">Try again</button><Link to="/support/my-tickets" className="mep-primary inline-flex items-center gap-2 px-5 py-3 font-semibold focus:outline-none focus:ring-2 focus:ring-cyan-400"><ArrowLeft className="h-5 w-5" aria-hidden="true" />My tickets</Link></div></section></main></Layout>;
  }

  const statusBadge = getStatusBadge(ticket.status);
  const StatusIcon = statusBadge.icon;
  const isClosed = ticket.status === 'closed';
  const isMutating = mutation !== null;

  return (
    <Layout>
      <SEO title="Support ticket" description="Review a support ticket for your account." />
      <main className="min-h-screen bg-black">
        <header className="border-b border-slate-800 px-4 pb-8 pt-24 sm:px-6 sm:pb-10 sm:pt-28 lg:px-8">
          <div className="mx-auto max-w-5xl">
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3"><Link to="/support/my-tickets" className="inline-flex items-center gap-2 text-gray-300 hover:text-white focus:outline-none focus:ring-2 focus:ring-cyan-400"><ArrowLeft className="h-5 w-5" aria-hidden="true" />My tickets</Link><button type="button" onClick={loadTicket} disabled={isMutating || loading} className="inline-flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2 text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh</button></div>
            <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-start"><div className="min-w-0"><div className="mb-3 flex flex-wrap items-center gap-2"><span className="break-all font-mono text-base text-gray-400">#{ticket.ticketNumber}</span><span className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium ${statusBadge.color}`}><StatusIcon className="h-4 w-4" aria-hidden="true" />{statusBadge.label}</span></div><h1 className="mep-heading break-words text-3xl font-bold text-white sm:text-4xl">{ticket.subject}</h1><div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-gray-400"><span className="flex items-center gap-2"><Calendar className="h-4 w-4" aria-hidden="true" />{formatDate(ticket.createdAt)}</span><span className="flex items-center gap-2"><Tag className="h-4 w-4" aria-hidden="true" />{ticket.category}</span>{ticket.priority && <span className={`flex items-center gap-2 ${getPriorityColor(ticket.priority)}`}><AlertTriangle className="h-4 w-4" aria-hidden="true" />{ticket.priority.charAt(0).toUpperCase() + ticket.priority.slice(1)} priority</span>}</div></div>{!isClosed && <button type="button" onClick={handleClose} disabled={isMutating} className="shrink-0 rounded-lg border border-gray-600 px-4 py-2 text-gray-200 hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50">{mutation === 'close' ? 'Closing…' : 'Close ticket'}</button>}</div>
          </div>
        </header>

        <section className="min-h-[36rem] px-4 py-8 sm:px-6 sm:py-10 lg:px-8"><div className="mx-auto max-w-5xl">
          {notice && <div role="status" aria-live="polite" className="mb-6 rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-4 text-cyan-100">{notice}</div>}
          {mutationError && <div role="alert" className="mb-6 flex gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-300"><AlertCircle className="h-5 w-5 shrink-0" aria-hidden="true" /><span className="break-words">{mutationError}</span></div>}

          <article className="mep-panel mb-6 rounded-xl border p-4 sm:p-6"><div className="flex items-start gap-4"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-cyan-500/20"><User className="h-5 w-5 text-cyan-400" aria-hidden="true" /></div><div className="min-w-0 flex-1"><div className="mb-2 flex flex-wrap items-center gap-3"><span className="font-semibold text-white">Your original request</span><span className="text-sm text-gray-500">{formatDate(ticket.createdAt)}</span></div><div className="break-words whitespace-pre-wrap text-gray-300">{ticket.description}</div></div></div></article>

          <section aria-labelledby="ticket-messages-heading" className="mb-6 space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><h2 id="ticket-messages-heading" className="mep-heading text-xl font-semibold text-white">Messages</h2>{messagePagination && <p className="text-sm text-gray-500">Page {messagePagination.page} of {Math.max(1, messagePagination.totalPages)} · {messagePagination.totalMessages} visible-message record{messagePagination.totalMessages === 1 ? '' : 's'}</p>}</div>{ticket.messages.length === 0 ? <p className="rounded-xl border border-slate-700 bg-slate-900/50 p-5 text-gray-400">There are no customer-visible replies on this message page.</p> : ticket.messages.map((message) => <article key={message.id} className={`rounded-xl border p-4 sm:p-6 ${message.isStaff ? 'border-teal-500/30 bg-teal-500/5' : 'border-slate-700 bg-slate-900/50'}`}><div className="flex items-start gap-4"><div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${message.isStaff ? 'bg-teal-500/20' : 'bg-cyan-500/20'}`}><User className={`h-5 w-5 ${message.isStaff ? 'text-teal-400' : 'text-cyan-400'}`} aria-hidden="true" /></div><div className="min-w-0 flex-1"><div className="mb-2 flex flex-wrap items-center gap-2"><span className="font-semibold text-white">{message.isStaff ? 'Support team' : 'You'}</span>{message.isStaff && <span className="rounded-full border border-teal-500/30 bg-teal-500/20 px-2 py-0.5 text-xs text-teal-300">Support</span>}<span className="text-sm text-gray-500">{formatDate(message.createdAt)}</span></div><div className="break-words whitespace-pre-wrap text-gray-300">{message.message}</div></div></div></article>)}{messagePagination && (messagePagination.hasPrev || messagePagination.hasNext) && <nav className="flex justify-between gap-4 pt-2" aria-label="Message pages"><button type="button" disabled={!messagePagination.hasPrev || isMutating} onClick={() => setMessagePage((current) => Math.max(1, current - 1))} className="rounded-lg bg-slate-800 px-4 py-2 text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40">Previous messages</button><button type="button" disabled={!messagePagination.hasNext || isMutating} onClick={() => setMessagePage((current) => current + 1)} className="rounded-lg bg-slate-800 px-4 py-2 text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40">More messages</button></nav>}</section>

          {isClosed ? <section className="mep-panel rounded-xl border p-5 sm:p-6" aria-labelledby="ticket-rating-heading" aria-busy={mutation === 'rating'}><CheckCircle className="mb-3 h-10 w-10 text-gray-300" aria-hidden="true" /><h2 id="ticket-rating-heading" className="mep-heading text-lg font-semibold text-white">This ticket is closed</h2>{ticket.rating ? <p className="mt-2 text-gray-300">You rated this ticket {ticket.rating} out of 5.</p> : <><p className="mb-4 mt-2 text-gray-400">How was your support experience?</p><div className="flex gap-2" aria-label="Rate this ticket">{[1, 2, 3, 4, 5].map((rating) => <button key={rating} type="button" onClick={() => handleRate(rating)} disabled={isMutating} aria-label={`Rate ${rating} out of 5`} aria-pressed={false} className="rounded-lg p-2 text-amber-300 hover:bg-amber-500/10 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"><Star className="h-6 w-6" aria-hidden="true" /></button>)}</div>{mutation === 'rating' && <p role="status" aria-live="polite" className="mt-3 text-sm text-cyan-200">Submitting your rating…</p>}</>}</section> : <section className="mep-panel rounded-xl border p-5 sm:p-6"><h2 className="mep-heading text-lg font-semibold text-white">Add a reply</h2><form className="mt-4" onSubmit={handleSendMessage}><label className="mb-2 block text-sm font-medium text-gray-300" htmlFor="ticket-reply">Reply</label><textarea id="ticket-reply" value={newMessage} onChange={(event) => setNewMessage(event.target.value)} placeholder="Type your message here..." rows={6} maxLength={4000} disabled={isMutating} className="mb-4 w-full resize-none rounded-xl border border-slate-700 bg-black px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60" /><button type="submit" disabled={isMutating || !newMessage.trim()} className="mep-primary flex items-center gap-2 px-6 py-3 font-semibold focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50">{mutation === 'message' ? <><Loader className="h-5 w-5 animate-spin" aria-hidden="true" />Sending…</> : <><Send className="h-5 w-5" aria-hidden="true" />Send reply</>}</button></form></section>}
        </div></section>
      </main>
    </Layout>
  );
}

export default function TicketDetail() {
  const { ticketNumber = '' } = useParams();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const principal = useMemo(
    () => supportPrincipalFromAuth(user, isAuthenticated === true),
    [isAuthenticated, user?.id, user?.tenant_id, user?.role],
  );
  const routeKey = JSON.stringify([principal?.key ?? 'support-unavailable', ticketNumber]);
  return <TicketDetailView key={routeKey} ticketNumber={ticketNumber} expectedOwner={principal?.owner} />;
}
