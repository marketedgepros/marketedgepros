import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Bell, CheckCircle2, Loader, Mail, Save } from 'lucide-react';
import useNotificationStore from '../../stores/notificationStore';
import useAuthStore from '../../store/authStore';

const notificationTypes = [
  { key: 'withdrawal', label: 'Withdrawals', description: 'Changes to withdrawal requests' },
  { key: 'commission', label: 'Commissions', description: 'Recorded commission updates' },
  { key: 'kyc', label: 'KYC verification', description: 'Verification status updates' },
  { key: 'payment', label: 'Payments', description: 'Recorded payment updates' },
  { key: 'challenge', label: 'Challenges', description: 'Challenge progress and result updates' },
  { key: 'system', label: 'System', description: 'Application announcements and updates' },
];

const clonePreferences = (preferences) => ({
  ...preferences,
  in_app: { ...preferences.in_app },
  email: { ...preferences.email },
  settings: { ...preferences.settings },
});

const actorIdentity = (state) => JSON.stringify([
  state.isAuthenticated,
  state.user?.id ?? null,
  state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
  state.user?.role ?? null,
]);

function Toggle({ checked, disabled = false, label, onChange }) {
  return <input type="checkbox" aria-label={label} checked={checked} disabled={disabled} onChange={onChange}
    className="h-5 w-5 rounded border-slate-500 bg-slate-900 text-cyan-400 focus:ring-cyan-300 disabled:cursor-not-allowed" />;
}

export default function NotificationSettings() {
  const context = useAuthStore(actorIdentity);
  return <NotificationSettingsView key={context} />;
}

function NotificationSettingsView() {
  const preferences = useNotificationStore((state) => state.preferences);
  const loading = useNotificationStore((state) => state.preferencesLoading);
  const preferencesError = useNotificationStore((state) => state.preferencesError);
  const pendingAction = useNotificationStore((state) => state.pendingAction);
  const actionErrors = useNotificationStore((state) => state.actionErrors);
  const fetchPreferences = useNotificationStore((state) => state.fetchPreferences);
  const updatePreferences = useNotificationStore((state) => state.updatePreferences);
  const [localPreferences, setLocalPreferences] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const alive = useRef(false);
  const saveFlight = useRef(false);
  const isSaving = saving || pendingAction?.name === 'save-preferences';

  useEffect(() => {
    alive.current = true;
    fetchPreferences();
    return () => { alive.current = false; };
  }, [fetchPreferences]);

  useEffect(() => {
    setLocalPreferences(preferences ? clonePreferences(preferences) : null);
  }, [preferences]);

  const editDraft = (update) => {
    if (isSaving) return;
    setSaveSuccess(false);
    setSaveError(null);
    setLocalPreferences((current) => (current ? update(current) : current));
  };

  const setCategory = (channel, type, checked) => editDraft((current) => ({
    ...current,
    [channel]: { ...current[channel], [type]: checked },
  }));

  const handleSave = async () => {
    if (!localPreferences || saveFlight.current || isSaving) return;
    saveFlight.current = true;
    setSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      const saved = await updatePreferences(localPreferences);
      if (!alive.current) return;
      if (saved) setSaveSuccess(true);
      else setSaveError('Unable to save notification preferences. The saved state is unknown; refresh before trying again.');
    } finally {
      saveFlight.current = false;
      if (alive.current) setSaving(false);
    }
  };

  if (loading) return <div className="mx-auto max-w-3xl p-6"><div className="flex justify-center p-12"><Loader className="h-8 w-8 animate-spin text-cyan-300" aria-label="Loading notification settings" /></div></div>;
  if (!localPreferences) return <div className="mx-auto max-w-3xl p-6"><div role="alert" className="rounded-lg border border-red-400/50 bg-red-500/10 p-4 text-red-100"><p className="break-words">{preferencesError || 'Notification preferences are unavailable.'}</p><button type="button" onClick={() => fetchPreferences()} className="mt-2 text-sm text-cyan-100 underline hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">Try again</button></div></div>;

  const emailEnabled = localPreferences.settings.email_enabled;
  const saveActionError = actionErrors['save-preferences'];
  const fieldsDisabled = isSaving;
  return (
    <div className="mx-auto max-w-3xl p-4 sm:p-6">
      <div className="mb-6"><h1 className="mep-heading mb-2 text-3xl font-bold text-white">Notification settings</h1><p className="text-slate-300">Store your in-app notification preferences.</p></div>
      {!localPreferences.persisted && <div role="status" className="mb-6 rounded-lg border border-cyan-300/35 bg-cyan-300/10 p-4 text-cyan-50">These are defaults and are not saved until you select <strong>Save preferences</strong>.</div>}
      {(preferencesError || saveError || saveActionError) && <div role="alert" className="mb-6 flex gap-3 rounded-lg border border-red-400/50 bg-red-500/10 p-4 text-red-100"><AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" /><p className="break-words">{saveError || saveActionError || preferencesError}</p></div>}
      {saveSuccess && <div role="status" className="mb-6 flex gap-3 rounded-lg border border-cyan-300/35 bg-cyan-300/10 p-4 text-cyan-50"><CheckCircle2 className="h-5 w-5 shrink-0" aria-hidden="true" /><p>Preferences saved.</p></div>}

      <section className="mep-panel mb-6 rounded-lg border p-4 sm:p-6" aria-labelledby="in-app-heading">
        <div className="mb-3 flex items-center gap-2"><Bell className="h-5 w-5 text-cyan-300" aria-hidden="true" /><h2 id="in-app-heading" className="mep-heading text-xl font-semibold text-white">In-app notifications</h2></div>
        <p className="mb-4 text-slate-300">Choose the categories shown within the application.</p>
        <div className="space-y-3">{notificationTypes.map((type) => <label key={type.key} className="flex cursor-pointer items-center justify-between gap-4 rounded-lg p-3 hover:bg-white/5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"><span className="min-w-0 flex-1"><span className="block break-words font-medium text-white">{type.label}</span><span className="block break-words text-sm text-slate-300">{type.description}</span></span><Toggle label={`Enable in-app ${type.label} notifications`} checked={localPreferences.in_app[type.key]} disabled={fieldsDisabled} onChange={(event) => setCategory('in_app', type.key, event.target.checked)} /></label>)}</div>
      </section>

      <section className="mep-panel mb-6 rounded-lg border p-4 sm:p-6" aria-labelledby="email-heading">
        <div className="mb-3 flex items-center gap-2"><Mail className="h-5 w-5 text-cyan-300" aria-hidden="true" /><h2 id="email-heading" className="mep-heading text-xl font-semibold text-white">Email preferences</h2></div>
        <p className="mb-4 rounded border border-amber-300/35 bg-amber-300/10 p-3 text-amber-50"><strong>Email delivery is not configured.</strong> These values are stored preferences only; saving them does not send email or confirm delivery.</p>
        <label className="mb-5 flex cursor-pointer items-center justify-between gap-4 rounded-lg p-3 hover:bg-white/5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"><span className="min-w-0 flex-1"><span className="block break-words font-medium text-white">Enable email preferences</span><span className="block break-words text-sm text-slate-300">Store email category and frequency choices.</span></span><Toggle label="Enable email preferences" checked={emailEnabled} disabled={fieldsDisabled} onChange={(event) => editDraft((current) => ({ ...current, settings: { ...current.settings, email_enabled: event.target.checked } }))} /></label>
        <fieldset disabled={fieldsDisabled || !emailEnabled} className="mb-5 border-t border-white/10 pt-5"><legend className="mb-3 text-white">Email frequency preference</legend><div className="space-y-3">{[
          { value: 'instant', label: 'Instant', description: 'Store an immediate preference.' },
          { value: 'daily', label: 'Daily digest', description: 'Store a daily digest preference.' },
          { value: 'weekly', label: 'Weekly digest', description: 'Store a weekly digest preference.' },
        ].map((option) => <label key={option.value} className="flex cursor-pointer items-center rounded-lg p-3 hover:bg-white/5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"><input type="radio" name="email_frequency" value={option.value} checked={localPreferences.settings.email_frequency === option.value} onChange={() => editDraft((current) => ({ ...current, settings: { ...current.settings, email_frequency: option.value } }))} className="h-4 w-4 border-slate-500 text-cyan-400 focus:ring-cyan-300" /><span className="ml-3 min-w-0"><span className="block break-words text-white">{option.label}</span><span className="block break-words text-sm text-slate-300">{option.description}</span></span></label>)}</div></fieldset>
        <div className="space-y-3 border-t border-white/10 pt-5">{notificationTypes.map((type) => <label key={type.key} className="flex cursor-pointer items-center justify-between gap-4 rounded-lg p-3 hover:bg-white/5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"><span className="min-w-0 flex-1"><span className="block break-words font-medium text-white">{type.label}</span><span className="block break-words text-sm text-slate-300">{type.description}</span></span><Toggle label={`Enable email ${type.label} preferences`} checked={localPreferences.email[type.key]} disabled={fieldsDisabled || !emailEnabled} onChange={(event) => setCategory('email', type.key, event.target.checked)} /></label>)}</div>
      </section>
      <div className="flex justify-end"><button type="button" onClick={handleSave} disabled={fieldsDisabled} className="mep-primary flex items-center gap-2 px-6 py-3 font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-100 disabled:cursor-not-allowed disabled:opacity-50">{fieldsDisabled ? <><Loader className="h-5 w-5 animate-spin" aria-hidden="true" />Saving…</> : <><Save className="h-5 w-5" aria-hidden="true" />Save preferences</>}</button></div>
    </div>
  );
}
