import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  Camera,
  CheckCircle,
  Lock,
  Phone,
  Shield,
  Trash2,
  Upload,
  User,
} from 'lucide-react';
import useAuthStore from '../../store/authStore';
import { profileAPI } from '../../services/api';
import useDialogFocus from '../../hooks/useDialogFocus';
import useTabNavigation from '../../hooks/useTabNavigation';
import {
  createProfileApiTransport,
  createProfileViewService,
  isAbortError,
  personalDraftFromUser,
  profileErrorMessage,
  profilePrincipalFromUser,
  safeAvatarUrl,
  validateAvatarFile,
} from '../../services/profileViewService';

const EMPTY_PASSWORDS = {
  current_password: '',
  new_password: '',
  confirm_password: '',
};

const operationNames = ['load', 'personal', 'avatar', 'password'];
const mutationOperationNames = ['personal', 'avatar', 'password'];
const PROFILE_TAB_IDS = Object.freeze(['personal', 'security']);

const statusClasses = {
  success: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
  error: 'border-red-400/40 bg-red-400/10 text-red-100',
  info: 'border-cyan-400/30 bg-cyan-400/10 text-cyan-100',
};

function InlineStatus({ status, id }) {
  if (!status?.message) return null;
  const role = status.kind === 'error' ? 'alert' : 'status';
  return (
    <div id={id} role={role} aria-live="polite" className={`rounded-lg border px-3 py-2 text-sm ${statusClasses[status.kind] || statusClasses.info}`}>
      {status.message}
    </div>
  );
}

function fieldClassName() {
  return 'w-full rounded-lg border border-slate-600 bg-slate-950/50 px-3 py-2.5 text-white shadow-inner shadow-black/10 outline-none transition placeholder:text-slate-500 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/40 disabled:cursor-not-allowed disabled:opacity-60';
}

function ProfileContent() {
  const {
    user,
    isAuthenticated,
    updateUser,
    clearAuthenticatedSession,
  } = useAuthStore();
  const navigate = useNavigate();
  const profileService = useMemo(
    () => createProfileViewService(createProfileApiTransport(profileAPI)),
    [],
  );
  const principal = useMemo(
    () => profilePrincipalFromUser(user, isAuthenticated),
    [user?.id, user?.tenant_id, user?.tenantId, user?.tenant?.id, user?.role, isAuthenticated],
  );

  const [activeTab, setActiveTab] = useState('personal');
  const [profileUser, setProfileUser] = useState(null);
  const [personalData, setPersonalData] = useState(() => personalDraftFromUser(null));
  const [passwordData, setPasswordData] = useState(EMPTY_PASSWORDS);
  const [loadState, setLoadState] = useState('idle');
  const [loadStatus, setLoadStatus] = useState(null);
  const [personalStatus, setPersonalStatus] = useState(null);
  const [avatarStatus, setAvatarStatus] = useState(null);
  const [passwordStatus, setPasswordStatus] = useState(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);

  const fileInputRef = useRef(null);
  const mountedRef = useRef(false);
  const dirtyDraftRef = useRef(false);
  const flightsRef = useRef(Object.fromEntries(operationNames.map((name) => [name, false])));
  const requestsRef = useRef({ context: 0, active: {} });
  const closeDeleteAvatarDialog = useCallback(() => {
    if (mutationOperationNames.some((name) => flightsRef.current[name])) return;
    setIsDeleteDialogOpen(false);
  }, []);
  const deleteAvatarDialogRef = useDialogFocus({
    open: isDeleteDialogOpen,
    onClose: closeDeleteAvatarDialog,
  });
  const getTabProps = useTabNavigation({
    ids: PROFILE_TAB_IDS,
    activeId: activeTab,
    onChange: setActiveTab,
  });

  const invalidateRequests = useCallback(() => {
    const requests = requestsRef.current;
    requests.context += 1;
    Object.values(requests.active).forEach((request) => request.controller.abort());
    requests.active = {};
    operationNames.forEach((name) => {
      flightsRef.current[name] = false;
    });
  }, []);

  const beginRequest = useCallback((operation, principalKey) => {
    if (flightsRef.current[operation]) return null;
    // A personal update, avatar mutation, and password change all affect the
    // current session/user representation. Do not allow two such responses to
    // race and replace each other in the store, even before React rerenders.
    if (mutationOperationNames.includes(operation)
      && mutationOperationNames.some((name) => flightsRef.current[name])) return null;
    const controller = new AbortController();
    const request = {
      id: Symbol(operation),
      operation,
      principalKey,
      context: requestsRef.current.context,
      controller,
    };
    flightsRef.current[operation] = true;
    requestsRef.current.active[operation] = request;
    return request;
  }, []);

  const isCurrentRequest = useCallback((request) => (
    mountedRef.current
    && requestsRef.current.context === request.context
    && requestsRef.current.active[request.operation]?.id === request.id
    && principal?.key === request.principalKey
  ), [principal?.key]);

  const finishRequest = useCallback((request) => {
    if (requestsRef.current.active[request.operation]?.id === request.id) {
      delete requestsRef.current.active[request.operation];
      flightsRef.current[request.operation] = false;
    }
  }, []);

  const loadProfile = useCallback(async (expectedPrincipal) => {
    if (!expectedPrincipal) return;
    const request = beginRequest('load', expectedPrincipal.key);
    if (!request) return;

    setLoadState('loading');
    setLoadStatus({ kind: 'info', message: 'Loading your current profile…' });
    try {
      const { user: freshUser } = await profileService.getProfile(expectedPrincipal, request.controller.signal);
      if (!isCurrentRequest(request)) return;

      // updateUser replaces, rather than merges, state. Only a complete, validated
      // server representation is allowed here.
      updateUser(freshUser);
      setProfileUser(freshUser);
      if (!dirtyDraftRef.current) setPersonalData(personalDraftFromUser(freshUser));
      setLoadState('ready');
      setLoadStatus(null);
    } catch (error) {
      if (!isCurrentRequest(request) || isAbortError(error)) return;
      setProfileUser(null);
      setLoadState('error');
      setLoadStatus({ kind: 'error', message: profileErrorMessage(error, 'We could not load the current profile.') });
    } finally {
      finishRequest(request);
    }
  }, [beginRequest, finishRequest, isCurrentRequest, profileService, updateUser]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      invalidateRequests();
    };
  }, [invalidateRequests]);

  useEffect(() => {
    // A user object from the store is merely a principal hint. Every identity key
    // change cancels its predecessor and starts with GET /profile.
    invalidateRequests();
    dirtyDraftRef.current = false;
    setIsDeleteDialogOpen(false);
    setProfileUser(null);
    setPersonalStatus(null);
    setAvatarStatus(null);
    setPasswordStatus(null);
    setPasswordData(EMPTY_PASSWORDS);

    if (!isAuthenticated) {
      setLoadState('idle');
      setLoadStatus(null);
      return undefined;
    }
    if (!principal) {
      setLoadState('error');
      setLoadStatus({ kind: 'error', message: 'Your signed-in account is missing a complete identity context. Reload and sign in again.' });
      return undefined;
    }

    loadProfile(principal);
    return undefined;
  }, [isAuthenticated, invalidateRequests, loadProfile, principal?.key]);

  const updateDraft = (field, value) => {
    dirtyDraftRef.current = true;
    setPersonalData((previous) => ({ ...previous, [field]: value }));
  };

  const handlePersonalUpdate = async (event) => {
    event.preventDefault();
    if (!principal || loadState !== 'ready') {
      setPersonalStatus({ kind: 'error', message: 'Wait for the current profile to finish loading before saving.' });
      return;
    }

    const request = beginRequest('personal', principal.key);
    if (!request) return;
    setPersonalStatus({ kind: 'info', message: 'Saving profile changes…' });

    try {
      const result = await profileService.updateProfile(personalData, principal, request.controller.signal);
      if (!isCurrentRequest(request)) return;

      updateUser(result.user);
      setProfileUser(result.user);
      dirtyDraftRef.current = false;
      setPersonalData(personalDraftFromUser(result.user));
      setPersonalStatus({ kind: 'success', message: 'Your profile details were saved.' });
    } catch (error) {
      if (!isCurrentRequest(request) || isAbortError(error)) return;
      setPersonalStatus({ kind: 'error', message: profileErrorMessage(error, 'We could not save your profile details.') });
    } finally {
      finishRequest(request);
    }
  };

  const handleAvatarClick = () => {
    if (!flightsRef.current.avatar && loadState === 'ready') fileInputRef.current?.click();
  };

  const handleAvatarChange = async (event) => {
    const file = event.target.files?.[0];
    // Let a user choose the same file after a client or server rejection.
    event.target.value = '';
    if (!file) return;

    const preflight = validateAvatarFile(file);
    if (!preflight.valid) {
      setAvatarStatus({ kind: 'error', message: preflight.message });
      return;
    }
    if (!principal || loadState !== 'ready') {
      setAvatarStatus({ kind: 'error', message: 'Wait for the current profile to finish loading before uploading a photo.' });
      return;
    }

    const request = beginRequest('avatar', principal.key);
    if (!request) return;
    setAvatarStatus({ kind: 'info', message: 'Uploading profile photo…' });

    try {
      const result = await profileService.uploadAvatar(file, principal, request.controller.signal);
      if (!isCurrentRequest(request)) return;

      updateUser(result.user);
      setProfileUser(result.user);
      setAvatarStatus({ kind: 'success', message: 'Your profile photo was updated.' });
    } catch (error) {
      if (!isCurrentRequest(request) || isAbortError(error)) return;
      setAvatarStatus({ kind: 'error', message: profileErrorMessage(error, 'We could not upload that profile photo.') });
    } finally {
      finishRequest(request);
    }
  };

  const confirmDeleteAvatar = async () => {
    if (!principal || loadState !== 'ready') return;
    const request = beginRequest('avatar', principal.key);
    if (!request) return;
    setAvatarStatus({ kind: 'info', message: 'Deleting profile photo…' });

    try {
      const result = await profileService.deleteAvatar(principal, request.controller.signal);
      if (!isCurrentRequest(request)) return;

      updateUser(result.user);
      setProfileUser(result.user);
      setIsDeleteDialogOpen(false);
      setAvatarStatus({ kind: 'success', message: 'Your profile photo was deleted.' });
    } catch (error) {
      if (!isCurrentRequest(request) || isAbortError(error)) return;
      setAvatarStatus({ kind: 'error', message: profileErrorMessage(error, 'We could not delete your profile photo.') });
    } finally {
      finishRequest(request);
    }
  };

  const handlePasswordUpdate = async (event) => {
    event.preventDefault();
    if (!principal || loadState !== 'ready') {
      setPasswordStatus({ kind: 'error', message: 'Wait for the current profile to finish loading before changing your password.' });
      return;
    }
    if (passwordData.new_password !== passwordData.confirm_password) {
      setPasswordStatus({ kind: 'error', message: 'New passwords do not match.' });
      return;
    }
    if (passwordData.new_password.length < 8) {
      setPasswordStatus({ kind: 'error', message: 'New passwords must be at least 8 characters.' });
      return;
    }

    const request = beginRequest('password', principal.key);
    if (!request) return;
    setPasswordStatus({ kind: 'info', message: 'Changing password…' });

    try {
      await profileService.changePassword(passwordData, request.controller.signal);
      if (!isCurrentRequest(request)) return;

      // The server invalidates the old token version. Clear local credentials only;
      // do not call logout after the server has already invalidated the session.
      setPasswordData(EMPTY_PASSWORDS);
      clearAuthenticatedSession();
      navigate('/login', {
        replace: true,
        state: { message: 'Password changed. Please sign in again.' },
      });
    } catch (error) {
      if (!isCurrentRequest(request) || isAbortError(error)) return;
      setPasswordStatus({ kind: 'error', message: profileErrorMessage(error, 'We could not change your password.') });
    } finally {
      finishRequest(request);
    }
  };

  const avatarUrl = safeAvatarUrl(profileUser?.avatar_url);
  const profileReady = loadState === 'ready';
  const isAvatarPending = flightsRef.current.avatar;
  const isPersonalPending = flightsRef.current.personal;
  const isPasswordPending = flightsRef.current.password;
  const isMutationPending = isAvatarPending || isPersonalPending || isPasswordPending;
  const initials = `${profileUser?.first_name?.[0] || ''}${profileUser?.last_name?.[0] || ''}`.toUpperCase() || 'ME';
  const kycRecord = typeof profileUser?.kyc_status === 'string' && profileUser.kyc_status.trim()
    ? `Recorded status: ${profileUser.kyc_status.replaceAll('_', ' ')}`
    : 'Unavailable';

  return (
    <div key={principal?.key || 'unauthenticated-profile'} className="mep-screen min-h-screen text-slate-100">
      <header className="border-b border-slate-700/70 bg-slate-900/80 backdrop-blur-sm">
        <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Account</p>
          <h1 className="mep-heading text-2xl font-bold tracking-tight text-white sm:text-3xl">Profile settings</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">Manage the personal details and security settings for your account.</p>
        </div>
      </header>

      <div className="mx-auto max-w-4xl space-y-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <InlineStatus id="profile-load-status" status={loadStatus} />

        <section aria-labelledby="profile-photo-heading" className="mep-panel rounded-xl border p-4 shadow-lg shadow-black/10 sm:p-6">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
            <div className="relative h-24 w-24 shrink-0 overflow-hidden rounded-full border border-cyan-300/30 bg-gradient-to-br from-cyan-600 to-blue-800 text-2xl font-bold text-white">
              {avatarUrl ? (
                <img src={avatarUrl} alt="Your profile photo" className="h-full w-full object-cover" />
              ) : (
                <span aria-hidden="true" className="flex h-full w-full items-center justify-center">{initials}</span>
              )}
              {isAvatarPending && <div aria-label="Profile photo request in progress" className="absolute inset-0 flex items-center justify-center bg-slate-950/70"><span className="h-7 w-7 animate-spin rounded-full border-2 border-cyan-200 border-t-transparent" /></div>}
            </div>
            <div className="min-w-0 flex-1">
              <h2 id="profile-photo-heading" className="mep-heading text-lg font-semibold text-white">Profile photo</h2>
              <p className="mt-1 text-sm leading-6 text-slate-400">JPG, PNG, GIF, or WEBP. Maximum file size is 5 MiB.</p>
              <div className="mt-4 flex flex-col gap-2 xs:flex-row sm:flex-row">
                <button type="button" onClick={handleAvatarClick} disabled={!profileReady || isMutationPending} className="mep-primary inline-flex min-h-11 items-center justify-center gap-2 px-4 py-2 font-semibold transition focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50">
                  <Upload className="h-4 w-4" aria-hidden="true" />
                  {isAvatarPending ? 'Uploading…' : 'Upload new photo'}
                </button>
                {avatarUrl && (
                    <button type="button" onClick={() => setIsDeleteDialogOpen(true)} disabled={!profileReady || isMutationPending} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 font-semibold text-slate-100 transition hover:border-red-400/70 hover:bg-red-400/10 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50">
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                    Delete photo
                  </button>
                )}
              </div>
              <input ref={fileInputRef} id="profile-avatar-file" type="file" accept="image/jpeg,image/png,image/gif,image/webp,.jpg,.jpeg,.png,.gif,.webp" onChange={handleAvatarChange} className="sr-only" />
              <div className="mt-3"><InlineStatus id="avatar-status" status={avatarStatus} /></div>
            </div>
          </div>
        </section>

        <section aria-label="Profile settings forms" className="mep-panel overflow-hidden rounded-xl border shadow-lg shadow-black/10">
          <div className="overflow-x-auto border-b border-slate-700">
            <div role="tablist" aria-label="Profile setting categories" className="flex min-w-max px-2">
              <button id="profile-personal-tab" type="button" aria-controls="profile-personal-panel" {...getTabProps('personal')} className={`inline-flex min-h-12 items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold outline-none transition focus:ring-2 focus:ring-inset focus:ring-cyan-300 ${activeTab === 'personal' ? 'border-cyan-400 text-cyan-200' : 'border-transparent text-slate-300 hover:text-white'}`}>
                <User className="h-4 w-4" aria-hidden="true" /> Personal details
              </button>
              <button id="profile-security-tab" type="button" aria-controls="profile-security-panel" {...getTabProps('security')} className={`inline-flex min-h-12 items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold outline-none transition focus:ring-2 focus:ring-inset focus:ring-cyan-300 ${activeTab === 'security' ? 'border-cyan-400 text-cyan-200' : 'border-transparent text-slate-300 hover:text-white'}`}>
                <Lock className="h-4 w-4" aria-hidden="true" /> Security
              </button>
            </div>
          </div>

          <div className="p-4 sm:p-6">
            {activeTab === 'personal' && (
              <form id="profile-personal-panel" role="tabpanel" aria-labelledby="profile-personal-tab" onSubmit={handlePersonalUpdate} className="space-y-5">
                <div>
                  <h2 className="mep-heading text-lg font-semibold text-white">Personal details</h2>
                  <p className="mt-1 text-sm text-slate-400">Only your name and phone number can be changed here.</p>
                </div>
                <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                  <div>
                    <label htmlFor="profile-first-name" className="mb-2 block text-sm font-medium text-slate-200">First name</label>
                    <input id="profile-first-name" name="first_name" autoComplete="given-name" value={personalData.first_name} onChange={(event) => updateDraft('first_name', event.target.value)} disabled={!profileReady || isMutationPending} required minLength={2} maxLength={50} className={fieldClassName()} aria-describedby="personal-status" />
                  </div>
                  <div>
                    <label htmlFor="profile-last-name" className="mb-2 block text-sm font-medium text-slate-200">Last name</label>
                    <input id="profile-last-name" name="last_name" autoComplete="family-name" value={personalData.last_name} onChange={(event) => updateDraft('last_name', event.target.value)} disabled={!profileReady || isMutationPending} required minLength={2} maxLength={50} className={fieldClassName()} aria-describedby="personal-status" />
                  </div>
                </div>
                <div>
                  <label htmlFor="profile-email" className="mb-2 block text-sm font-medium text-slate-200">Email address</label>
                  <input id="profile-email" type="email" value={profileUser?.email ?? ''} readOnly disabled={!profileReady} className={fieldClassName()} />
                  <p className="mt-2 text-sm text-slate-400">Email changes are not available from this screen.</p>
                </div>
                <div>
                  <label htmlFor="profile-phone" className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-200"><Phone className="h-4 w-4 text-cyan-300" aria-hidden="true" />Phone number</label>
                  <input id="profile-phone" name="phone" type="tel" autoComplete="tel" value={personalData.phone} onChange={(event) => updateDraft('phone', event.target.value)} disabled={!profileReady || isMutationPending} maxLength={32} placeholder="+1234567890" className={fieldClassName()} aria-describedby="personal-status" />
                </div>
                <InlineStatus id="personal-status" status={personalStatus} />
                <div className="flex justify-end">
                  <button type="submit" disabled={!profileReady || isMutationPending} className="mep-primary min-h-11 px-5 py-2 font-semibold transition focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50">
                    {isPersonalPending ? 'Saving…' : 'Save changes'}
                  </button>
                </div>
              </form>
            )}

            {activeTab === 'security' && (
              <form id="profile-security-panel" role="tabpanel" aria-labelledby="profile-security-tab" onSubmit={handlePasswordUpdate} className="space-y-5">
                <div>
                  <h2 className="mep-heading text-lg font-semibold text-white">Password</h2>
                  <p className="mt-1 text-sm leading-6 text-slate-400">After a successful change, you will be signed out and asked to sign in again.</p>
                </div>
                <div>
                  <label htmlFor="profile-current-password" className="mb-2 block text-sm font-medium text-slate-200">Current password</label>
                  <input id="profile-current-password" name="current_password" type="password" autoComplete="current-password" value={passwordData.current_password} onChange={(event) => setPasswordData((previous) => ({ ...previous, current_password: event.target.value }))} disabled={!profileReady || isMutationPending} required className={fieldClassName()} aria-describedby="password-status" />
                </div>
                <div>
                  <label htmlFor="profile-new-password" className="mb-2 block text-sm font-medium text-slate-200">New password</label>
                  <input id="profile-new-password" name="new_password" type="password" autoComplete="new-password" value={passwordData.new_password} onChange={(event) => setPasswordData((previous) => ({ ...previous, new_password: event.target.value }))} disabled={!profileReady || isMutationPending} required minLength={8} className={fieldClassName()} aria-describedby="new-password-help password-status" />
                  <p id="new-password-help" className="mt-2 text-sm text-slate-400">Use at least 8 characters with uppercase, lowercase and a number. A special character is recommended, not required. The server applies the final password-strength checks.</p>
                </div>
                <div>
                  <label htmlFor="profile-confirm-password" className="mb-2 block text-sm font-medium text-slate-200">Confirm new password</label>
                  <input id="profile-confirm-password" name="confirm_password" type="password" autoComplete="new-password" value={passwordData.confirm_password} onChange={(event) => setPasswordData((previous) => ({ ...previous, confirm_password: event.target.value }))} disabled={!profileReady || isMutationPending} required className={fieldClassName()} aria-describedby="password-status" />
                </div>
                <InlineStatus id="password-status" status={passwordStatus} />
                <div className="flex justify-end">
                  <button type="submit" disabled={!profileReady || isMutationPending} className="mep-primary min-h-11 px-5 py-2 font-semibold transition focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50">
                    {isPasswordPending ? 'Changing password…' : 'Change password'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </section>

        <section aria-labelledby="profile-status-heading" className="mep-panel rounded-xl border p-4 shadow-lg shadow-black/10 sm:p-6">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-cyan-300" aria-hidden="true" />
            <h2 id="profile-status-heading" className="mep-heading text-lg font-semibold text-white">Account status</h2>
          </div>
          <div className="mt-4 space-y-3">
            <div className="mep-panel flex items-start gap-3 rounded-lg border p-3">
              {profileUser?.is_verified === true ? <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" aria-hidden="true" /> : <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />}
              <div><p className="font-medium text-white">Email verification</p><p className="mt-0.5 text-sm text-slate-400">{profileUser?.is_verified === true ? 'Verified' : profileReady ? 'Not verified' : 'Unavailable'}</p></div>
            </div>
            <div className="mep-panel flex items-start gap-3 rounded-lg border p-3">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
              <div><p className="font-medium text-white">KYC record</p><p className="mt-0.5 break-words text-sm capitalize text-slate-400">{profileReady ? kycRecord : 'Unavailable'}</p></div>
            </div>
          </div>
        </section>

        {loadState === 'error' && (
          <button type="button" onClick={() => principal && loadProfile(principal)} disabled={flightsRef.current.load} className="min-h-11 rounded-lg border border-cyan-400/70 px-4 py-2 font-semibold text-cyan-100 transition hover:bg-cyan-400/10 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
            Retry loading profile
          </button>
        )}
      </div>

      {isDeleteDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-end bg-slate-950/80 p-4 sm:items-center sm:justify-center" role="presentation">
          <section ref={deleteAvatarDialogRef} role="dialog" aria-modal="true" aria-labelledby="delete-avatar-heading" aria-describedby="delete-avatar-description" className="mep-panel w-full max-w-md rounded-xl border p-5 shadow-2xl">
            <h2 id="delete-avatar-heading" className="mep-heading text-lg font-semibold text-white">Delete profile photo?</h2>
            <p id="delete-avatar-description" className="mt-2 text-sm leading-6 text-slate-300">This will remove the current photo from your profile. This action cannot be undone from this screen.</p>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" data-autofocus onClick={closeDeleteAvatarDialog} disabled={isMutationPending} className="min-h-11 rounded-lg border border-slate-600 px-4 py-2 font-semibold text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-300 disabled:opacity-50">Cancel</button>
              <button type="button" onClick={confirmDeleteAvatar} disabled={isMutationPending} className="min-h-11 rounded-lg bg-red-500 px-4 py-2 font-semibold text-white hover:bg-red-400 focus:outline-none focus:ring-2 focus:ring-red-200 disabled:opacity-50">{isAvatarPending ? 'Deleting…' : 'Delete photo'}</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

// Remount component state/refs for every account/tenant/role context, not only DOM.
export default function Profile() {
  const user = useAuthStore((state) => state.user);
  const authenticated = useAuthStore((state) => state.isAuthenticated);
  const principal = profilePrincipalFromUser(user, authenticated);
  const key = principal?.key ?? JSON.stringify([authenticated, user?.id, user?.tenant_id ?? user?.tenantId ?? user?.tenant?.id, user?.role]);
  return <ProfileContent key={key} />;
}
