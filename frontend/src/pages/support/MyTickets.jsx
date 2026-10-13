import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle, Clock, Filter, Loader, MessageCircle, RefreshCw, Ticket } from 'lucide-react';
import { Link } from 'react-router-dom';
import Layout from '../../components/layout/Layout';
import SEO from '../../components/SEO';
import useAuthStore from '../../store/authStore';
import {
  CUSTOMER_TICKET_STATUSES,
  DEFAULT_TICKETS_PER_PAGE,
  isSupportTicketRequestCanceled,
  loadMySupportTickets,
  supportPrincipalFromAuth,
} from '../../services/supportTicketViewService';

const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'waiting_customer', label: 'Waiting for you' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' },
];

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
  waiting_customer: { color: 'bg-amber-500/10 text-amber-300 border-amber-500/30', icon: AlertCircle, label: 'Waiting for you' },
  resolved: { color: 'bg-teal-500/10 text-teal-400 border-teal-500/30', icon: CheckCircle, label: 'Resolved' },
  closed: { color: 'bg-gray-500/10 text-gray-400 border-gray-500/30', icon: CheckCircle, label: 'Closed' },
}[status]);

const getPriorityBadge = (priority) => ({
  low: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
  medium: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
  high: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  urgent: 'bg-red-500/10 text-red-300 border-red-500/30',
}[priority]);

const Unavailable = () => (
  <div className="mep-panel rounded-xl border p-6 text-center" role="status">
    <h1 className="mep-heading text-2xl font-bold text-white">Tickets are unavailable</h1>
    <p className="mt-3 text-gray-400">Please sign in with a verified account context to view support tickets.</p>
  </div>
);

export function MyTicketsView({ expectedOwner }) {
  const requestRef = useRef(null);
  const requestSequenceRef = useRef(0);
  const [tickets, setTickets] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);

  const loadTickets = useCallback(async () => {
    requestRef.current?.abort();
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;

    if (!expectedOwner) {
      requestRef.current = null;
      setLoading(false);
      setTickets([]);
      setPagination(null);
      setError('');
      return;
    }

    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError('');
    setTickets([]);
    setPagination(null);

    try {
      const view = await loadMySupportTickets({
        page,
        perPage: DEFAULT_TICKETS_PER_PAGE,
        status: statusFilter === 'all' ? null : statusFilter,
        signal: controller.signal,
        expectedOwner,
      });
      if (requestSequenceRef.current !== requestId || controller.signal.aborted) return;
      setTickets(view.tickets);
      setPagination(view.pagination);
    } catch (requestError) {
      if (requestSequenceRef.current !== requestId || isSupportTicketRequestCanceled(requestError)) return;
      setError(getErrorMessage(requestError, 'Unable to load your tickets.'));
    } finally {
      if (requestSequenceRef.current === requestId) {
        setLoading(false);
        if (requestRef.current === controller) requestRef.current = null;
      }
    }
  }, [expectedOwner, page, statusFilter]);

  useEffect(() => {
    loadTickets();
    return () => requestRef.current?.abort();
  }, [loadTickets]);

  const selectStatus = (nextStatus) => {
    if (!expectedOwner || nextStatus === statusFilter) return;
    setPage(1);
    setStatusFilter(nextStatus);
  };

  const selectedFilter = STATUS_FILTERS.find((filter) => filter.value === statusFilter);

  return (
    <Layout>
      <SEO title="Support tickets" description="View support tickets for your account." />
      <main className="min-h-screen bg-black">
        <header className="border-b border-slate-800 px-4 pb-8 pt-24 sm:px-6 sm:pb-10 sm:pt-28 lg:px-8">
          <div className="mx-auto flex max-w-7xl flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-400">Support</p>
              <h1 className="mep-heading mt-2 text-3xl font-bold text-white sm:text-4xl">My tickets</h1>
              <p className="mt-3 text-base text-gray-300 sm:text-lg">Track support requests for the account you are signed in to.</p>
              {pagination && <p className="mt-3 text-sm text-gray-500">{pagination.totalTickets} matching ticket{pagination.totalTickets === 1 ? '' : 's'}</p>}
            </div>
            {expectedOwner && <div className="flex flex-wrap gap-3"><button type="button" onClick={loadTickets} disabled={loading} className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-5 py-3 font-semibold text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-black disabled:cursor-not-allowed disabled:opacity-50"><RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />Refresh</button><Link to="/support/create-ticket" className="mep-primary inline-flex items-center gap-2 px-5 py-3 font-semibold focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-black"><Ticket className="h-5 w-5" aria-hidden="true" />New ticket</Link></div>}
          </div>
        </header>

        <section className="min-h-[36rem] px-4 py-8 sm:px-6 sm:py-10 lg:px-8">
          <div className="mx-auto max-w-7xl">
            {!expectedOwner ? <Unavailable /> : <>
              <div className="mb-6 flex flex-wrap items-center gap-2" aria-label="Ticket status filter">
                <Filter className="mr-1 h-5 w-5 text-gray-400" aria-hidden="true" />
                {STATUS_FILTERS.map((filter) => <button key={filter.value} type="button" onClick={() => selectStatus(filter.value)} disabled={loading} aria-pressed={statusFilter === filter.value} className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-black disabled:cursor-not-allowed disabled:opacity-50 ${statusFilter === filter.value ? 'bg-cyan-600 text-white' : 'bg-slate-800 text-gray-300 hover:bg-slate-700'}`}>{filter.label}</button>)}
              </div>

              {loading ? <div className="flex flex-col items-center justify-center py-20 text-gray-300" role="status"><Loader className="mb-4 h-8 w-8 animate-spin text-cyan-500" aria-hidden="true" />Loading tickets…</div>
                : error ? <div role="alert" className="max-w-2xl rounded-xl border border-red-500/30 bg-red-500/10 p-5"><div className="flex gap-3 text-red-300"><AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" /><div><h2 className="mep-heading font-semibold text-white">Tickets could not be loaded</h2><p className="mt-1 break-words">{error}</p></div></div><button type="button" onClick={loadTickets} className="mt-5 rounded-lg bg-slate-800 px-4 py-2 text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400">Try again</button></div>
                  : tickets.length === 0 ? <div className="py-16 text-center"><Ticket className="mx-auto mb-5 h-10 w-10 text-gray-400" aria-hidden="true" /><h2 className="mep-heading text-2xl font-bold text-white">No {selectedFilter?.label.toLowerCase()} tickets found</h2><p className="mt-2 text-gray-400">There are no support requests in this view.</p><Link to="/support/create-ticket" className="mep-primary mt-6 inline-flex items-center gap-2 px-5 py-3 font-semibold focus:outline-none focus:ring-2 focus:ring-cyan-400"><Ticket className="h-5 w-5" aria-hidden="true" />Create a ticket</Link></div>
                    : <div className="space-y-4">{tickets.map((ticket) => {
                      const statusBadge = getStatusBadge(ticket.status);
                      const StatusIcon = statusBadge.icon;
                      const priorityBadge = ticket.priority ? getPriorityBadge(ticket.priority) : null;
                      return <Link key={ticket.id} to={`/support/ticket/${encodeURIComponent(ticket.ticketNumber)}`} className="block rounded-xl border border-slate-700 bg-slate-900/50 p-4 transition-colors hover:border-cyan-500/50 focus:outline-none focus:ring-2 focus:ring-cyan-400 sm:p-6"><div className="min-w-0"><div className="mb-2 flex flex-wrap items-center gap-2"><span className="break-all font-mono font-semibold text-cyan-400">#{ticket.ticketNumber}</span><span className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${statusBadge.color}`}><StatusIcon className="h-3.5 w-3.5" aria-hidden="true" />{statusBadge.label}</span>{ticket.priority && <span className={`rounded-full border px-3 py-1 text-xs font-medium ${priorityBadge}`}>{ticket.priority.charAt(0).toUpperCase() + ticket.priority.slice(1)}</span>}</div><h2 className="mep-heading break-words text-xl font-semibold text-white">{ticket.subject}</h2><p className="mt-2 break-words text-sm text-gray-400">{ticket.description}</p></div><p className="mt-4 text-sm text-gray-400">Created {formatDate(ticket.createdAt)}</p></Link>;
                    })}</div>}

              {!loading && !error && pagination && (pagination.hasPrev || pagination.hasNext) && <nav className="mt-8 flex items-center justify-between gap-4" aria-label="Ticket pages"><button type="button" disabled={!pagination.hasPrev} onClick={() => setPage((current) => Math.max(1, current - 1))} className="rounded-xl bg-slate-800 px-4 py-3 text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40">Previous</button><span className="text-center text-sm text-gray-400">Page {pagination.page} of {Math.max(1, pagination.totalPages)}</span><button type="button" disabled={!pagination.hasNext} onClick={() => setPage((current) => current + 1)} className="rounded-xl bg-slate-800 px-4 py-3 text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40">Next</button></nav>}
            </>}
          </div>
        </section>
      </main>
    </Layout>
  );
}

export default function MyTickets() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const principal = useMemo(
    () => supportPrincipalFromAuth(user, isAuthenticated === true),
    [isAuthenticated, user?.id, user?.tenant_id, user?.role],
  );
  return <MyTicketsView key={principal?.key ?? 'support-unavailable'} expectedOwner={principal?.owner} />;
}

export { CUSTOMER_TICKET_STATUSES };
