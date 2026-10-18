import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import UserLayout from '../components/layout/UserLayout';
import useAuthStore from '../store/authStore';
import useRecordedTradingRead from '../hooks/useRecordedTradingRead';
import { createRecordedTradingViewService, isScalingAdmin, recordedIdentityKey, recordedPrincipal } from '../services/recordedTradingViewService.js';
import { RecordedBoundary, RecordedMetric, RecordedPagination, RecordedReadState, recordedDisplay, tradingButton, tradingPanel } from '../components/trading/RecordedTradingUI';

const service = createRecordedTradingViewService();

export function RecordedScalingDetail({ data }) {
  return <>
    <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <RecordedMetric label="Legacy current tier" value={data.current_tier} />
      <RecordedMetric label="Stored account size" value={data.current_account_size} hint="Currency unspecified; not approved trading capital." />
      <RecordedMetric label="Stored total profit" value={data.total_profit} hint="Unverified record, not available funds." />
      <RecordedMetric label="Legacy scale count" value={data.times_scaled} />
    </dl>
    <section className={tradingPanel} aria-label="Stored scaling metadata">
      <h2 className="mep-heading text-lg font-semibold text-white">Stored progression metadata</h2>
      <p className="mt-2 text-sm text-slate-300">Targets and tier values below are historic records, not an approved scaling plan or eligibility decision.</p>
      <dl className="mt-5 grid gap-4 sm:grid-cols-2">
        {[
          ['Recorded status', data.status], ['Legacy next tier', data.next_tier],
          ['Stored next account size', data.next_account_size], ['Legacy target profit', data.target_profit],
          ['Stored progress percentage', data.progress_percentage === null ? null : `${data.progress_percentage}%`],
          ['Last recorded scale timestamp', data.last_scaled_at], ['Record created', data.created_at],
        ].map(([label, value]) => <div key={label} className="mep-panel min-w-0 rounded-xl border p-4">
          <dt className="text-xs text-slate-400">{label}</dt><dd className="mt-2 break-words font-mono text-sm text-slate-100">{recordedDisplay(value)}</dd>
        </div>)}
      </dl>
    </section>
  </>;
}
function ScalingContent({ principal }) {
  const admin = isScalingAdmin(principal);
  const [page, setPage] = useState(1);
  const key = JSON.stringify([recordedIdentityKey(principal), admin, page]);
  const load = useCallback((signal) => service.scaling({ expectedOwner: principal, admin, page, signal }), [key]);
  const { value: view, loading, error, retry } = useRecordedTradingRead(key, load);
  const empty = view && (admin ? view.data.length === 0 : view.data === null);
  return <div className="mx-auto min-w-0 max-w-7xl space-y-6 p-4 text-slate-100 sm:p-6 lg:p-8">
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Account records</p>
        <h1 className="mep-heading mt-2 text-3xl font-semibold tracking-tight text-white">{admin ? 'Scoped scaling records' : 'Account scaling records'}</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">{admin ? 'Review the historic records returned for your authorized management scope. This is not a list of all platform customers.' : 'Review stored progression metadata for your account. No provider-backed scale-up is available from this screen.'}</p>
      </div>
      <button type="button" className={tradingButton} onClick={retry} disabled={loading}><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh records</button>
    </header>
    <RecordedBoundary scaling />
    <RecordedReadState loading={loading} error={error} retry={retry} empty={empty}
      emptyTitle={admin ? 'No scaling records on this page' : 'No recorded scaling plan'} />
    {view && !loading && !error && !admin && view.data && <RecordedScalingDetail data={view.data} />}
    {view && !loading && !error && admin && <>
      {view.data.length > 0 && <section className="mep-panel min-w-0 overflow-hidden rounded-2xl border" aria-label="Scoped scaling records">
        <div className="border-b border-white/10 p-5"><h2 className="mep-heading font-semibold text-white">Current management page</h2>
          <p className="mt-2 text-xs text-slate-300">{view.data.length} records on this page · eligibility unavailable · currency unspecified</p></div>
        <div className="max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-cyan-300" role="region" aria-label="Scrollable scaling table" tabIndex={0}>
          <table className="w-full min-w-[800px] text-left text-sm">
            <caption className="sr-only">Legacy scaling metadata for authorized users. No record is permission to scale or fund an account.</caption>
            <thead className="bg-slate-950/40 text-xs text-slate-300"><tr>{['Recorded user', 'Current / next tier', 'Stored account size', 'Stored profit / target', 'Progress / count', 'Recorded status'].map((label) => <th key={label} scope="col" className="px-4 py-3 font-semibold">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-white/10">{view.data.map((record) => <tr key={record.user_id} className="hover:bg-white/[0.025]">
              <td className="max-w-64 break-words px-4 py-4"><p className="font-semibold">{recordedDisplay(record.name)}</p>
                <p className="mt-1 text-xs text-slate-400">{recordedDisplay(record.email)}</p><p className="mt-1 text-xs text-slate-400">User {record.user_id}</p></td>
              <td className="px-4 py-4 font-mono">{recordedDisplay(record.current_tier)} / {recordedDisplay(record.next_tier)}</td>
              <td className="px-4 py-4 font-mono">{recordedDisplay(record.current_account_size)}</td>
              <td className="px-4 py-4 font-mono"><p>{recordedDisplay(record.total_profit)}</p><p className="mt-1 text-slate-400">{recordedDisplay(record.target_profit)}</p></td>
              <td className="px-4 py-4 font-mono"><p>{record.progress_percentage === null ? 'Unavailable' : `${record.progress_percentage}%`}</p><p className="mt-1 text-slate-400">Count: {recordedDisplay(record.times_scaled)}</p></td>
              <td className="px-4 py-4">{recordedDisplay(record.status)}<span className="mt-1 block text-xs text-amber-200">Not verified for scaling</span></td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>}
      <RecordedPagination pagination={view.pagination} onPage={setPage} disabled={loading} />
    </>}
    <section className={`${tradingPanel} flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between`}>
      <div><h2 className="mep-heading font-semibold text-white">Scale-up is not enabled</h2><p className="mt-2 text-sm text-slate-300">Verified trading evidence, approved rules and an authorized provider command are required before this can become an account action.</p></div>
      <Link className={`${tradingButton} shrink-0`} to="/support/my-tickets">My support tickets</Link>
    </section>
  </div>;
}
export default function ScalingProgress() {
  const user = useAuthStore((state) => state.user);
  const principal = recordedPrincipal(user);
  return <UserLayout>{!principal || (!isScalingAdmin(principal) && principal.tenant_id === null)
    ? <section className={`${tradingPanel} m-4`} role="status"><h1 className="mep-heading text-xl font-semibold text-white">Scaling records unavailable</h1>
      <p className="mt-2 text-sm text-slate-300">An authenticated account with a recorded scope is required.</p></section>
    : <ScalingContent key={recordedIdentityKey(principal)} principal={principal} />}</UserLayout>;
}
