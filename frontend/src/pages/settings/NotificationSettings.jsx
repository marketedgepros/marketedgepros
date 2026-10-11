import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Bell, CheckCircle, Loader, Mail, Save } from 'lucide-react';
import useNotificationStore from '../../stores/notificationStore';
import useAuthStore from '../../store/authStore';

const notificationTypes = [
  { key: 'withdrawal', label: 'Withdrawals', description: 'Changes to withdrawal requests' },
  { key: 'commission', label: 'Commissions', description: 'Recorded commission updates' },
  { key: 'kyc', label: 'KYC Verification', description: 'Verification status updates' },
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

function Toggle({ checked, disabled = false, label, onChange }) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={onChange}
      className="h-5 w-5 rounded border-gray-600 text-purple-600 focus:ring-purple-500 disabled:cursor-not-allowed"
    />
  );
}

export default function NotificationSettings() {
  const context = useAuthStore((state) => JSON.stringify([
    state.isAuthenticated, state.user?.id ?? null,
    state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
  ]));
  return <NotificationSettingsView key={context} />;
}

function NotificationSettingsView() {
  const preferences = useNotificationStore((state) => state.preferences);
  const loading = useNotificationStore((state) => state.preferencesLoading);
  const preferencesError = useNotificationStore((state) => state.preferencesError);
  const fetchPreferences = useNotificationStore((state) => state.fetchPreferences);
  const updatePreferences = useNotificationStore((state) => state.updatePreferences);
  const [localPreferences, setLocalPreferences] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const alive = useRef(false);
  const saveFlight = useRef(false);

  useEffect(() => {
    alive.current = true;
    fetchPreferences();
    return () => { alive.current = false; };
  }, [fetchPreferences]);

  useEffect(() => {
    setLocalPreferences(preferences ? clonePreferences(preferences) : null);
  }, [preferences]);

  const setCategory = (channel, type, checked) => {
    setLocalPreferences((current) => current && ({
      ...current,
      [channel]: { ...current[channel], [type]: checked },
    }));
  };

  const handleSave = async () => {
    if (!localPreferences || saveFlight.current) return;
    saveFlight.current = true;
    setSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    const saved = await updatePreferences(localPreferences);
    if (!alive.current) return;
    if (saved) {
      setSaveSuccess(true);
    } else {
      setSaveError('Unable to save notification preferences. Please try again.');
    }
    saveFlight.current = false;
    setSaving(false);
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto p-6">
        <div className="flex justify-center p-12"><Loader className="w-8 h-8 text-purple-500 animate-spin" /></div>
      </div>
    );
  }

  if (!localPreferences) {
    return (
      <div className="max-w-3xl mx-auto p-6">
        <div role="alert" className="rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-red-200">
          <p>{preferencesError || 'Notification preferences are unavailable.'}</p>
          <button type="button" onClick={() => fetchPreferences()} className="mt-2 text-sm underline hover:text-white">Try again</button>
        </div>
      </div>
    );
  }

  const emailEnabled = localPreferences.settings.email_enabled;

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-white mb-2">Notification Settings</h1>
        <p className="text-gray-400">Store your in-app and email notification preferences.</p>
      </div>

      {(preferencesError || saveError) && (
        <div role="alert" className="mb-6 p-4 bg-red-500/20 border border-red-500/50 rounded-lg flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-400" />
          <p className="text-red-200">{saveError || preferencesError}</p>
        </div>
      )}
      {saveSuccess && (
        <div className="mb-6 p-4 bg-green-500/20 border border-green-500/50 rounded-lg flex items-center gap-3">
          <CheckCircle className="w-5 h-5 text-green-400" />
          <p className="text-green-200">Preferences saved.</p>
        </div>
      )}

      <section className="mb-6 bg-slate-800/50 backdrop-blur-sm border border-white/10 rounded-lg p-6" aria-labelledby="in-app-heading">
        <div className="flex items-center gap-2 mb-3">
          <Bell className="w-5 h-5 text-purple-400" />
          <h2 id="in-app-heading" className="text-xl font-semibold text-white">In-App Notifications</h2>
        </div>
        <p className="text-gray-400 mb-4">Choose the categories shown within the application.</p>
        <div className="space-y-3">
          {notificationTypes.map((type) => (
            <label key={type.key} className="flex items-center justify-between gap-4 p-3 rounded-lg hover:bg-white/5 cursor-pointer transition-colors">
              <span className="flex-1">
                <span className="block text-white font-medium">{type.label}</span>
                <span className="block text-sm text-gray-400">{type.description}</span>
              </span>
              <Toggle
                label={`Enable in-app ${type.label} notifications`}
                checked={localPreferences.in_app[type.key]}
                onChange={(event) => setCategory('in_app', type.key, event.target.checked)}
              />
            </label>
          ))}
        </div>
      </section>

      <section className="mb-6 bg-slate-800/50 backdrop-blur-sm border border-white/10 rounded-lg p-6" aria-labelledby="email-heading">
        <div className="flex items-center gap-2 mb-3">
          <Mail className="w-5 h-5 text-purple-400" />
          <h2 id="email-heading" className="text-xl font-semibold text-white">Email Preferences</h2>
        </div>
        <p className="text-gray-400 mb-4">These stored category and frequency preferences do not guarantee email delivery.</p>

        <label className="flex items-center justify-between gap-4 p-3 rounded-lg hover:bg-white/5 cursor-pointer transition-colors mb-5">
          <span className="flex-1">
            <span className="block text-white font-medium">Enable email preferences</span>
            <span className="block text-sm text-gray-400">Apply the saved email category and frequency choices.</span>
          </span>
          <Toggle
            label="Enable email preferences"
            checked={emailEnabled}
            onChange={(event) => setLocalPreferences((current) => ({
              ...current,
              settings: { ...current.settings, email_enabled: event.target.checked },
            }))}
          />
        </label>

        <fieldset className="border-t border-white/10 pt-5 mb-5">
          <legend className="px-0 text-white font-medium mb-3">Email frequency preference</legend>
          <div className="space-y-3">
            {[
              { value: 'instant', label: 'Instant', description: 'Record an immediate preference.' },
              { value: 'daily', label: 'Daily digest', description: 'Record a daily digest preference.' },
              { value: 'weekly', label: 'Weekly digest', description: 'Record a weekly digest preference.' },
            ].map((option) => (
              <label key={option.value} className={`flex items-center p-3 rounded-lg ${emailEnabled ? 'cursor-pointer hover:bg-white/5' : 'opacity-50 cursor-not-allowed'}`}>
                <input
                  type="radio"
                  name="email_frequency"
                  value={option.value}
                  checked={localPreferences.settings.email_frequency === option.value}
                  disabled={!emailEnabled}
                  onChange={() => setLocalPreferences((current) => ({
                    ...current,
                    settings: { ...current.settings, email_frequency: option.value },
                  }))}
                  className="w-4 h-4 text-purple-600 border-gray-600 focus:ring-purple-500"
                />
                <span className="ml-3"><span className="block text-white">{option.label}</span><span className="block text-sm text-gray-400">{option.description}</span></span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="border-t border-white/10 pt-5 space-y-3">
          {notificationTypes.map((type) => (
            <label key={type.key} className={`flex items-center justify-between gap-4 p-3 rounded-lg ${emailEnabled ? 'cursor-pointer hover:bg-white/5' : 'opacity-50 cursor-not-allowed'}`}>
              <span className="flex-1">
                <span className="block text-white font-medium">{type.label}</span>
                <span className="block text-sm text-gray-400">{type.description}</span>
              </span>
              <Toggle
                label={`Enable email ${type.label} preferences`}
                checked={localPreferences.email[type.key]}
                disabled={!emailEnabled}
                onChange={(event) => setCategory('email', type.key, event.target.checked)}
              />
            </label>
          ))}
        </div>
      </section>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-purple-600 to-purple-800 text-white rounded-lg hover:from-purple-700 hover:to-purple-900 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? <><Loader className="w-5 h-5 animate-spin" />Saving...</> : <><Save className="w-5 h-5" />Save Preferences</>}
        </button>
      </div>
    </div>
  );
}
