import axios from 'axios';

const API_BASE_URL = '/api/v1';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const INVALID_REFRESH_RESPONSE = 'Refresh response was invalid.';

export const isJsonObject = (value) => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
);

export const isUnsafeMethod = (method) => UNSAFE_METHODS.has((method || 'GET').toUpperCase());

const isNonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0;

export const isSameOriginRequest = (url, baseURL = API_BASE_URL, origin) => {
  const currentOrigin = origin || (typeof window !== 'undefined' ? window.location.origin : null);
  if (!currentOrigin) {
    // In non-browser environments, only relative URLs are safe to decorate.
    return !/^(?:[a-z][a-z\d+.-]*:)?\/\//i.test(String(url || ''))
      && !/^(?:[a-z][a-z\d+.-]*:)?\/\//i.test(String(baseURL || ''));
  }

  try {
    const resolvedBase = new URL(baseURL || API_BASE_URL, currentOrigin);
    const resolvedUrl = new URL(url || '', resolvedBase);
    return resolvedUrl.origin === currentOrigin;
  } catch (error) {
    return false;
  }
};

export const shouldAttachCsrfToken = (config, csrfToken, origin) => (
  isNonEmptyString(csrfToken)
  && isUnsafeMethod(config?.method)
  && isSameOriginRequest(config?.url, config?.baseURL || API_BASE_URL, origin)
);

export const isCompleteRefreshResponse = (data) => (
  isJsonObject(data)
  && isNonEmptyString(data.access_token)
  && isNonEmptyString(data.refresh_token)
  && isNonEmptyString(data.csrf_token)
);

const readStorage = (key) => (
  typeof localStorage === 'undefined' ? null : localStorage.getItem(key)
);

const clearLegacyAuthStorage = () => {
  if (typeof localStorage === 'undefined') return;
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('csrf_token');
  localStorage.removeItem('user');
};

const saveRotatedTokens = (data) => {
  if (!isCompleteRefreshResponse(data)) {
    throw new Error(INVALID_REFRESH_RESPONSE);
  }

  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  localStorage.setItem('csrf_token', data.csrf_token);
};

const isLoginOrRefreshRequest = (config) => {
  const url = String(config?.url || '').split('?')[0];
  return url.includes('/auth/login')
    || url.includes('/auth/refresh')
    || url.includes('/auth/register')
    || url.includes('/auth/password/');
};

// Create axios instance
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Keep bearer-token compatibility while cookie sessions are being introduced. CSRF is
// sent only to same-origin unsafe requests, never to a caller-supplied foreign URL.
api.interceptors.request.use(
  (config) => {
    const isSameOrigin = isSameOriginRequest(config.url, config.baseURL || API_BASE_URL);
    const token = readStorage('access_token');
    const csrfToken = readStorage('csrf_token');
    config.headers = config.headers || {};

    if (!config._skipAuthorization && isSameOrigin && isNonEmptyString(token)) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    if (shouldAttachCsrfToken(config, csrfToken)) {
      config.headers['X-CSRF-Token'] = csrfToken;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

let refreshPromise = null;

const refreshSession = async () => {
  const refreshToken = readStorage('refresh_token');
  const response = await api.post(
    '/auth/refresh',
    isNonEmptyString(refreshToken) ? { refresh_token: refreshToken } : {},
    {
      // The endpoint accepts either its HttpOnly cookie or this legacy body token.
      _skipAuthRefresh: true,
      _skipAuthorization: true,
    }
  );
  saveRotatedTokens(response?.data);
  return response.data;
};

const requestRefresh = () => {
  if (!refreshPromise) {
    refreshPromise = refreshSession().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
};

const redirectToLogin = () => {
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.assign('/login');
  }
};

// Response interceptor retries a request once after a single shared refresh. Refresh can
// rely on an HttpOnly cookie even when the legacy refresh_token key is absent.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const canRefresh = error.response?.status === 401
      && originalRequest
      && !originalRequest._retry
      && !originalRequest._skipAuthRefresh
      && !isLoginOrRefreshRequest(originalRequest)
      && isSameOriginRequest(originalRequest.url, originalRequest.baseURL || API_BASE_URL);

    if (!canRefresh) {
      return Promise.reject(error);
    }

    originalRequest._retry = true;
    try {
      const refreshed = await requestRefresh();
      originalRequest.headers = originalRequest.headers || {};
      originalRequest.headers.Authorization = `Bearer ${refreshed.access_token}`;
      return api(originalRequest);
    } catch (refreshError) {
      clearLegacyAuthStorage();
      redirectToLogin();
      return Promise.reject(refreshError);
    }
  }
);

// Auth API
export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  login2FA: (data) => api.post('/auth/login/2fa', data),
  logout: () => api.post('/auth/logout'),
  verifyEmail: (token) => api.get(`/auth/verify-email/${token}`),
  requestPasswordReset: (email) => api.post('/auth/password/reset-request', { email }),
  resetPassword: (data) => api.post('/auth/password/reset', data),
  enable2FA: () => api.post('/auth/2fa/enable'),
  confirm2FA: (token) => api.post('/auth/2fa/confirm', { token }),
  disable2FA: (password) => api.post('/auth/2fa/disable', { password }),
  getCurrentUser: () => api.get('/auth/me'),
};

// Programs API
export const programsAPI = {
  getAll: (params) => api.get('/programs/', { params }),
  getById: (id) => api.get(`/programs/${id}`),
  create: (data) => api.post('/programs', data),
  update: (id, data) => api.put(`/programs/${id}`, data),
  purchase: (id, data) => api.post(`/programs/${id}/purchase`, data),
  getMyChallenges: () => api.get('/programs/my-challenges'),
  getChallenge: (id) => api.get(`/programs/challenges/${id}`),
  createAddon: (programId, data) => api.post(`/programs/${programId}/addons`, data),
};

// Payments API
export const paymentsAPI = {
  createPaymentIntent: (challengeId) => api.post('/payments/create-payment-intent', { challenge_id: challengeId }),
  confirmPayment: (paymentIntentId) => api.post('/payments/confirm-payment', { payment_intent_id: paymentIntentId }),
  refund: (challengeId, reason) => api.post(`/payments/refund/${challengeId}`, { reason }),
  getPaymentStatus: (paymentIntentId) => api.get(`/payments/status/${paymentIntentId}`),
};

// Uploads API
export const uploadsAPI = {
  uploadKYC: (file, documentType) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType);
    return api.post('/uploads/kyc', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  uploadProfileImage: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/uploads/profile-image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  uploadTenantLogo: (file, tenantId) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('tenant_id', tenantId);
    return api.post('/uploads/tenant-logo', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

export default api;



// Profile API
export const profileAPI = {
  get: (config = {}) => api.get('/profile', config),
  update: (data, config = {}) => api.put('/profile', data, config),
  changePassword: (data, config = {}) => api.put('/profile/password', data, { ...config, _skipAuthRefresh: true }),
  uploadAvatar: (file, config = {}) => {
    const formData = new FormData();
    formData.append('avatar', file);
    return api.post('/profile/avatar', formData, {
      ...config, headers: { ...config.headers, 'Content-Type': undefined },
    });
  },
  deleteAvatar: (config = {}) => api.delete('/profile/avatar', config),
  getStats: () => api.get('/profile/stats'),
};

// Admin API
export const adminAPI = {
  // Users
  getUsers: (params) => api.get('/admin/users', { params }),
  getUser: (id) => api.get(`/admin/users/${id}`),
  createUser: (data) => api.post('/admin/users', data),
  updateUser: (id, data) => api.put(`/admin/users/${id}`, data),
  deleteUser: (id) => api.delete(`/admin/users/${id}`),
  toggleUserStatus: (id) => api.post(`/admin/users/${id}/toggle-status`),
  
  // Programs
  getPrograms: (params) => api.get('/admin/programs', { params }),
  createProgram: (data) => api.post('/admin/programs', data),
  updateProgram: (id, data) => api.put(`/admin/programs/${id}`, data),
  deleteProgram: (id) => api.delete(`/admin/programs/${id}`),
  
  // Payments
  getPayments: (params) => api.get('/admin/payments', { params }),
  getPayment: (id) => api.get(`/admin/payments/${id}`),
  refundPayment: (id, data) => api.post(`/admin/payments/${id}/refund`, data),
  exportPayments: (params) => api.get('/admin/payments/export', { params, responseType: 'blob' }),
  
  // Settings
  getSettings: () => api.get('/admin/settings'),
  updateSettings: (data) => api.put('/admin/settings', data),
  
  // Statistics
  getStats: () => api.get('/admin/stats'),
  getAnalytics: (params) => api.get('/admin/analytics', { params }),
};

// KYC API
export const kycAPI = {
  getDocuments: () => api.get('/kyc/documents'),
  uploadDocument: (file, documentType) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/kyc/documents/${documentType}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  getPendingDocuments: () => api.get('/kyc/pending'),
  approveDocument: (id, notes) => api.post(`/kyc/${id}/approve`, { notes }),
  rejectDocument: (id, reason) => api.post(`/kyc/${id}/reject`, { reason }),
  getDocument: (id) => api.get(`/kyc/${id}`),
  deleteDocument: (id) => api.delete(`/kyc/${id}`),
};

// Challenges API
export const challengesAPI = {
  getMyChallenges: () => api.get('/challenges/my-challenges'),
  getChallenge: (id) => api.get(`/challenges/${id}`),
  createChallenge: (data) => api.post('/challenges', data),
  evaluateChallenge: (id) => api.post(`/challenges/${id}/evaluate`),
  fundAccount: (id, data) => api.post(`/challenges/${id}/fund`, data),
  getTrades: (id, params) => api.get(`/challenges/${id}/trades`, { params }),
  addTrade: (id, data) => api.post(`/challenges/${id}/trades`, data),
  getStatistics: (id) => api.get(`/challenges/${id}/statistics`),
};

// Traders API
export const tradersAPI = {
  getDashboard: () => api.get('/traders/dashboard'),
  getTradingHistory: (params, config = {}) => api.get('/traders/history', { ...config, params }),
  getWithdrawals: () => api.get('/traders/withdrawals'),
  requestWithdrawal: (data) => api.post('/traders/withdrawals', data),
  getDocuments: () => api.get('/traders/documents'),
  uploadDocument: (file, documentType) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType);
    return api.post('/traders/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

// Affiliates API
export const affiliatesAPI = {
  getAffiliates: (params) => api.get('/affiliates', { params }),
  getAffiliate: (id) => api.get(`/affiliates/${id}`),
  getTraders: (affiliateId) => api.get(`/affiliates/${affiliateId}/traders`),
  getCommissions: (affiliateId, params) => api.get(`/affiliates/${affiliateId}/commissions`, { params }),
  requestPayout: (data) => api.post('/affiliates/payout-request', data),
  getPayouts: () => api.get('/affiliates/payouts'),
};

// Reports API
export const reportsAPI = {
  getAffiliateStats: () => api.get('/reports/affiliate-stats'),
  getMonthlyTrends: (params) => api.get('/reports/monthly-trends', { params }),
  getTopPerformers: (params) => api.get('/reports/top-performers', { params }),
  getAdminAnalytics: (params) => api.get('/reports/admin-analytics', { params }),
  exportReport: (type, params) => api.get(`/reports/export/${type}`, { params, responseType: 'blob' }),
};

// Hierarchy API
export const hierarchyAPI = {
  getMyDownline: () => api.get('/hierarchy/my-downline'),
  getMyDirectTeam: (params) => api.get('/hierarchy/my-direct-team', { params }),
  createUser: (data) => api.post('/hierarchy/create-user', data),
  getUser: (id) => api.get(`/hierarchy/user/${id}`),
  updateUser: (id, data) => api.put(`/hierarchy/user/${id}`, data),
  getTree: (params) => api.get('/hierarchy/tree', { params }),
  getStats: () => api.get('/hierarchy/stats'),
};

// CRM API
export const crmAPI = {
  // Leads
  getLeads: (params) => api.get('/crm/leads', { params }),
  getLead: (id) => api.get(`/crm/leads/${id}`),
  createLead: (data) => api.post('/crm/leads', data),
  updateLead: (id, data) => api.put(`/crm/leads/${id}`, data),
  
  // Activities
  addActivity: (leadId, data) => api.post(`/crm/leads/${leadId}/activities`, data),
  
  // Notes
  addNote: (leadId, data) => api.post(`/crm/leads/${leadId}/notes`, data),
  
  // Conversion
  convertLead: (leadId, data) => api.post(`/crm/leads/${leadId}/convert`, data),
  markLost: (leadId, data) => api.post(`/crm/leads/${leadId}/lost`, data),
  
  // Analytics
  getStats: () => api.get('/crm/stats'),
  getPipeline: () => api.get('/crm/pipeline'),
};

// Helper function for error handling
export const handleApiError = (error) => {
  if (error.response) {
    // Server responded with error
    const message = error.response.data?.error || error.response.data?.message || 'An error occurred';
    return {
      success: false,
      message,
      status: error.response.status,
      data: error.response.data,
    };
  } else if (error.request) {
    // Request made but no response
    return {
      success: false,
      message: 'No response from server. Please check your connection.',
      status: 0,
    };
  } else {
    // Error in request setup
    return {
      success: false,
      message: error.message || 'An unexpected error occurred',
      status: 0,
    };
  }
};
