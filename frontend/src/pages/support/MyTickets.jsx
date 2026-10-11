import { useCallback, useEffect, useRef, useState } from 'react';
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
    waiting_customer: { color: 'bg-amber-500/10 text-amber-300 border-amber-500/30', icon: AlertCircle, label: 'Waiting for you' },
    resolved: { color: 'bg-teal-500/10 text-teal-400 border-teal-500/30', icon: CheckCircle, label: 'Resolved' },
    closed: { color: 'bg-gray-500/10 text-gray-400 border-gray-500/30', icon: CheckCircle, label: 'Closed' },
  };
  return badges[status] || badges.open;
};

const getPriorityBadge = (priority) => ({
  low: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
  medium: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
  high: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  urgent: 'bg-red-500/10 text-red-300 border-red-500/30',
}[priority] || 'bg-slate-500/10 text-slate-300 border-slate-500/30');

export function MyTicketsView() {
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
    const controller = new AbortController();
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    requestRef.current = controller;

    setLoading(true);
    setError('');
    // Clear the previous account view before showing a result for another filter/page.
    setTickets([]);
    setPagination(null);

    try {
      const view = await loadMySupportTickets({
        page,
        perPage: DEFAULT_TICKETS_PER_PAGE,
        status: statusFilter === 'all' ? null : statusFilter,
        signal: controller.signal,
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
  }, [page, statusFilter]);

  useEffect(() => {
    loadTickets();
    return () => requestRef.current?.abort();
  }, [loadTickets]);

  const selectStatus = (nextStatus) => {
    if (nextStatus === statusFilter) return;
    setPage(1);
    setStatusFilter(nextStatus);
  };

  const selectedFilter = STATUS_FILTERS.find((filter) => filter.value === statusFilter);

  return (
    <Layout>
      <SEO title="My Support Tickets" description="View your authenticated support requests." keywords="support tickets, help, customer service" />

      <section className="relative pt-32 pb-12 overflow-hidden bg-black">
        <div className="absolute inset-0" aria-hidden="true">
          <div className="absolute top-20 left-10 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl" />
          <div className="absolute bottom-20 right-10 w-96 h-96 bg-teal-500/10 rounded-full blur-3xl" />
        </div>
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-5xl md:text-6xl font-bold text-white mb-4">My Support <span className="bg-gradient-to-r from-cyan-400 to-teal-400 bg-clip-text text-transparent">Tickets</span></h1>
              <p className="text-xl text-gray-300">Track support requests for the account you are signed in to.</p>
              {pagination && <p className="text-sm text-gray-500 mt-3">{pagination.totalTickets} matching ticket{pagination.totalTickets === 1 ? '' : 's'}</p>}
            </div>
            <div className="flex flex-wrap gap-3">
              <button type="button" onClick={loadTickets} disabled={loading} className="inline-flex items-center gap-2 px-5 py-3 bg-slate-800 text-white rounded-xl font-semibold hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed">
                <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <Link to="/support/create-ticket" className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-xl font-semibold hover:shadow-lg hover:shadow-cyan-500/50 transition-all">
                <Ticket className="w-5 h-5" /> New ticket
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="py-12 bg-black min-h-[42rem]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-center gap-3 mb-6" aria-label="Ticket status filter">
            <Filter className="w-5 h-5 text-gray-400" />
            {STATUS_FILTERS.map((filter) => (
              <button key={filter.value} type="button" onClick={() => selectStatus(filter.value)} disabled={loading} className={`px-4 py-2 rounded-lg font-medium transition-all disabled:opacity-50 ${statusFilter === filter.value ? 'bg-gradient-to-r from-cyan-500 to-teal-500 text-white' : 'bg-slate-800 text-gray-300 hover:bg-slate-700'}`}>
                {filter.label}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="flex flex-col justify-center items-center py-20 text-gray-300" role="status">
              <Loader className="w-8 h-8 text-cyan-500 animate-spin mb-4" /> Loading tickets…
            </div>
          ) : error ? (
            <div role="alert" className="max-w-2xl p-6 bg-red-500/10 border border-red-500/30 rounded-xl">
              <div className="flex gap-3 text-red-300"><AlertCircle className="w-5 h-5 shrink-0 mt-0.5" /><div><h2 className="font-semibold text-white">Tickets could not be loaded</h2><p className="mt-1">{error}</p></div></div>
              <button type="button" onClick={loadTickets} className="mt-5 px-4 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-700">Try again</button>
            </div>
          ) : tickets.length === 0 ? (
            <div className="text-center py-20">
              <div className="w-20 h-20 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-6"><Ticket className="w-10 h-10 text-gray-400" /></div>
              <h2 className="text-2xl font-bold text-white mb-2">No {selectedFilter?.label.toLowerCase()} tickets found</h2>
              <p className="text-gray-400 mb-6">There are no support requests in this view.</p>
              <Link to="/support/create-ticket" className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-xl font-semibold hover:shadow-lg hover:shadow-cyan-500/50 transition-all"><Ticket className="w-5 h-5" /> Create a ticket</Link>
            </div>
          ) : (
            <div className="space-y-4">
              {tickets.map((ticket) => {
                const statusBadge = getStatusBadge(ticket.status);
                const StatusIcon = statusBadge.icon;
                return (
                  <Link key={ticket.id} to={`/support/ticket/${encodeURIComponent(ticket.ticketNumber)}`} className="block bg-slate-900/50 backdrop-blur-sm border border-slate-700 rounded-xl p-6 hover:border-cyan-500/50 transition-all">
                    <div className="flex items-start justify-between gap-4 mb-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-3 mb-2">
                          <span className="text-cyan-400 font-mono font-semibold">#{ticket.ticketNumber}</span>
                          <span className={`px-3 py-1 rounded-full text-xs font-medium border ${statusBadge.color} flex items-center gap-1.5`}><StatusIcon className="w-3.5 h-3.5" />{statusBadge.label}</span>
                          <span className={`px-3 py-1 rounded-full text-xs font-medium border ${getPriorityBadge(ticket.priority)}`}>{ticket.priority.charAt(0).toUpperCase() + ticket.priority.slice(1)}</span>
                        </div>
                        <h2 className="text-xl font-semibold text-white mb-2">{ticket.subject}</h2>
                        <p className="text-gray-400 text-sm line-clamp-2">{ticket.description}</p>
                      </div>
                    </div>
                    <p className="text-sm text-gray-400">Created {formatDate(ticket.createdAt)}</p>
                  </Link>
                );
              })}
            </div>
          )}

          {!loading && !error && pagination && (pagination.hasPrev || pagination.hasNext) && (
            <nav className="mt-8 flex items-center justify-between gap-4" aria-label="Ticket pages">
              <button type="button" disabled={!pagination.hasPrev} onClick={() => setPage((current) => Math.max(1, current - 1))} className="px-5 py-3 bg-slate-800 text-white rounded-xl disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-700">Previous</button>
              <span className="text-sm text-gray-400">Page {pagination.page} of {Math.max(1, pagination.totalPages)}</span>
              <button type="button" disabled={!pagination.hasNext} onClick={() => setPage((current) => current + 1)} className="px-5 py-3 bg-slate-800 text-white rounded-xl disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-700">Next</button>
            </nav>
          )}
        </div>
      </section>
    </Layout>
  );
}

/** Reset list state and abort its request whenever the verified principal changes. */
export default function MyTickets() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const tenantId = useAuthStore((state) => state.user?.tenant_id ?? null);
  const contextKey = JSON.stringify([isAuthenticated === true, userId, tenantId]);

  return <MyTicketsView key={contextKey} />;
}

export { CUSTOMER_TICKET_STATUSES };
