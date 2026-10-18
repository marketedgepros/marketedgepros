import { useState, useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import useAuthStore from './store/authStore';
import Notification from './components/Notification';
import ChatWidget from './components/ChatWidget';
import { ADMIN_ROLES } from './constants/roles';
import { postLoginDestination } from './services/navigationService.js';
import { useLocation } from 'react-router-dom';
import { ToastProvider } from './contexts/ToastContext';
import useNotificationStore from './stores/notificationStore.js';
import RouteScrollManager from './components/RouteScrollManager.js';

// Auth Pages (Lazy Loaded)
const Login = lazy(() => import('./pages/Login'));
const Register = lazy(() => import('./pages/Register'));
const VerifyEmail = lazy(() => import('./pages/VerifyEmail'));
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'));
const ResetPassword = lazy(() => import('./pages/ResetPassword'));

// Public Pages (Lazy Loaded)
const HomePage = lazy(() => import('./pages/NewHomePage'));
const Programs = lazy(() => import('./pages/ProgramsNew'));
const ProgramDetails = lazy(() => import('./pages/ProgramDetails'));
const Checkout = lazy(() => import('./pages/Checkout'));

const AboutUs = lazy(() => import('./pages/AboutUs'));
const HowItWorks = lazy(() => import('./pages/HowItWorks'));
const FAQ = lazy(() => import('./pages/FAQ'));
const Contact = lazy(() => import('./pages/Contact'));
const FreeCourse = lazy(() => import('./pages/FreeCourse'));
const LightningChallenge = lazy(() => import('./pages/LightningChallenge'));
const SupportHub = lazy(() => import('./pages/support/SupportHub'));

const CreateTicket = lazy(() => import('./pages/support/CreateTicket'));
const MyTickets = lazy(() => import('./pages/support/MyTickets'));
const TicketDetail = lazy(() => import('./pages/support/TicketDetail'));
const Article = lazy(() => import("./pages/support/Article"));
const Blog = lazy(() => import('./pages/Blog'));
const BlogPost = lazy(() => import('./pages/BlogPost'));
const AffiliateLanding = lazy(() => import('./pages/affiliate/AffiliateLanding'));
const AffiliateDashboard = lazy(() => import('./pages/affiliate/AffiliateDashboard'));
const AffiliatePayout = lazy(() => import('./pages/affiliate/AffiliatePayout'));
const TermsOfService = lazy(() => import('./pages/TermsOfService'));
const PrivacyPolicy = lazy(() => import('./pages/PrivacyPolicy'));
const RiskDisclosure = lazy(() => import("./pages/RiskDisclosure"));
const TradingRules = lazy(() => import("./pages/TradingRules"));
const RefundPolicy = lazy(() => import("./pages/RefundPolicy"));
const CookiePolicy = lazy(() => import("./pages/CookiePolicy"));
const Careers = lazy(() => import("./pages/Careers"));

// Shared Pages (Lazy Loaded)
const ScalingProgress = lazy(() => import("./pages/ScalingProgress"));
const RoleBasedDashboard = lazy(() => import('./components/RoleBasedDashboard'));
const KYC = lazy(() => import('./pages/KYC'));
const Profile = lazy(() => import('./pages/user/Profile'));
const MyChallenges = lazy(() => import('./pages/user/MyChallenges'));
const ChallengeDetails = lazy(() => import('./pages/ChallengeDetails'));

// Admin Pages (Lazy Loaded)
const AdminLayout = lazy(() => import('./components/admin/AdminLayout'));
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboardConnected'));
const AnalyticsDashboard = lazy(() => import('./pages/admin/AnalyticsDashboard'));
const UserManagement = lazy(() => import('./pages/admin/UserManagementConnected'));
const ProgramsManagement = lazy(() => import('./pages/admin/ProgramsManagement'));
const ChallengesManagement = lazy(() => import('./pages/admin/ChallengesManagement'));
const PaymentsManagement = lazy(() => import('./pages/admin/PaymentsManagementConnected'));
const KYCApproval = lazy(() => import('./pages/admin/KYCApprovalConnected'));
const PaymentApprovals = lazy(() => import('./pages/admin/PaymentApprovals'));
const Settings = lazy(() => import('./pages/admin/Settings'));
const WithdrawalManagement = lazy(() => import('./pages/admin/WithdrawalManagement'));
const CRM = lazy(() => import('./pages/admin/CRM'));
const LeadDetails = lazy(() => import('./pages/admin/LeadDetails'));

// Notification Pages (Lazy Loaded)
const Notifications = lazy(() => import('./pages/Notifications'));
const NotificationSettings = lazy(() => import('./pages/settings/NotificationSettings'));

// Affiliate Pages (Lazy Loaded)
const TradersManagement = lazy(() => import('./pages/agent/TradersManagement'));
const Commissions = lazy(() => import('./pages/agent/Commissions'));
const Reports = lazy(() => import('./pages/agent/Reports'));

// Trader Pages (Lazy Loaded)
const TraderDashboard = lazy(() => import('./pages/user/UserDashboard'));
const TradingHistory = lazy(() => import('./pages/trader/TradingHistory'));
const Withdrawals = lazy(() => import('./pages/trader/Withdrawals'));
const Documents = lazy(() => import('./pages/user/Documents'));
const Wallet = lazy(() => import('./pages/user/Wallet'));
const UserLayout = lazy(() => import('./components/layout/UserLayout'));

// Guards
import RoleGuard from './components/guards/RoleGuard';

// Protected Route Component
function ProtectedRoute({ children, adminOnly = false, userOnly = false }) {
  const { isAuthenticated, isLoading, user } = useAuthStore();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="mep-screen min-h-screen flex items-center justify-center p-4">
        <div className="text-center" role="status">
          <div aria-hidden="true" className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400"></div>
          <p className="text-slate-300 mt-4">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }

  // Check if admin trying to access user-only pages
  const isAdmin = user && ADMIN_ROLES.includes(user.role);
  
  if (userOnly && isAdmin) {
    return <Navigate to="/admin" replace />;
  }

  return children;
}

// Public Route Component (redirect if already logged in)
function PublicRoute({ children }) {
  const { isAuthenticated, isLoading, user } = useAuthStore();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="mep-screen min-h-screen flex items-center justify-center p-4">
        <div className="text-center" role="status">
          <div aria-hidden="true" className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400"></div>
          <p className="text-slate-300 mt-4">Loading...</p>
        </div>
      </div>
    );
  }

  if (isAuthenticated && user) {
    return <Navigate to={postLoginDestination(user, location.search)} replace />;
  }

  return children;
}

function AccountChatWidget() {
  const location = useLocation();
  // Payout availability must remain unobscured, particularly on narrow screens.
  // The page has a supported support-ticket link instead of a floating overlay.
  if (location.pathname === '/affiliate/payout') return null;
  if (['/affiliate/traders', '/affiliate/commissions', '/affiliate/reports'].includes(location.pathname)) return null;
  if (['/wallet', '/trader/withdrawals', '/admin/withdrawals'].includes(location.pathname)) return null;
  if (['/admin/payments', '/admin/payment-approvals'].includes(location.pathname)) return null;
  if (location.pathname === '/admin' || location.pathname.startsWith('/admin/')) return null;
  if (location.pathname === '/programs' || /^\/programs\/[^/]+(?:\/checkout)?$/.test(location.pathname)) return null;
  // On narrow screens, use the normal support navigation instead of covering copy.
  return <div className="hidden md:block"><ChatWidget /></div>;
}

function App() {
  const { init } = useAuthStore();

  useEffect(() => {
    // Invalidate notification requests synchronously when the verified principal changes.
    const identity = (state) => JSON.stringify([
      state.isAuthenticated, state.user?.id ?? null,
      state.user?.tenant_id ?? state.user?.tenantId ?? state.user?.tenant?.id ?? null,
      state.user?.role ?? null,
    ]);
    const unsubscribe = useAuthStore.subscribe((state, previous) => {
      if (identity(state) !== identity(previous)) useNotificationStore.getState().reset();
    });
    init();
    return unsubscribe;
  }, [init]);

  return (
    <ToastProvider>
      <BrowserRouter>
        {import.meta.env?.VITE_DEMO_RELEASE === 'true' && (
          <aside aria-label="Demo release status" className="bg-slate-900 px-4 py-2 text-center text-sm text-cyan-200 border-b border-cyan-400/20">
            Limited release — live trading and payouts are disabled. Account access and purchase availability are controlled separately by the service.
          </aside>
        )}
        <Notification />
        <AccountChatWidget />
      <Suspense fallback={
        <div className="mep-screen min-h-screen flex items-center justify-center">
          <div className="text-center" role="status">
            <div aria-hidden="true" className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400"></div>
            <p className="text-gray-300 mt-4">Loading...</p>
          </div>
        </div>
      }>
        <RouteScrollManager />
        <Routes>
        {/* Public Routes */}
        <Route path="/" element={<HomePage />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/programs" element={<Programs />} />
        <Route path="/programs/:programId/checkout" element={<Checkout />} />
        <Route path="/programs/:id" element={<ProgramDetails />} />
        <Route path="/about" element={<AboutUs />} />
        <Route path="/how-it-works" element={<HowItWorks />} />
        <Route path="/faq" element={<FAQ />} />
        <Route path="/contact" element={<Contact />} />
        <Route path="/free-course" element={<FreeCourse />} />
        <Route path="/lightning-challenge" element={<LightningChallenge />} />
        <Route path="/support" element={<SupportHub />} />

        <Route path="/support/create-ticket" element={<ProtectedRoute><CreateTicket /></ProtectedRoute>} />
        <Route path="/support/my-tickets" element={<ProtectedRoute><MyTickets /></ProtectedRoute>} />
        <Route path="/support/ticket/:ticketNumber" element={<ProtectedRoute><TicketDetail /></ProtectedRoute>} />
        <Route path="/support/:slug" element={<Article />} />
        <Route path="/blog" element={<Blog />} />
        <Route path="/blog/:slug" element={<BlogPost />} />
        <Route path="/affiliate" element={<AffiliateLanding />} />
        <Route path="/affiliate/payout" element={<ProtectedRoute><RoleGuard allowedRoles={['affiliate']}><UserLayout><AffiliatePayout /></UserLayout></RoleGuard></ProtectedRoute>} />
        <Route path="/terms-of-service" element={<TermsOfService />} />
        <Route path="/terms" element={<Navigate to="/terms-of-service" replace />} />
        <Route path="/privacy-policy" element={<PrivacyPolicy />} />
        <Route path="/privacy" element={<Navigate to="/privacy-policy" replace />} />
        <Route path="/risk-disclosure" element={<RiskDisclosure />} />
        <Route path="/trading-rules" element={<TradingRules />} />
        <Route path="/refund-policy" element={<RefundPolicy />} />
        <Route path="/cookie-policy" element={<CookiePolicy />} />
        <Route path="/careers" element={<Careers />} />

        {/* Auth Routes */}
        <Route
          path="/login"
          element={
            <PublicRoute>
              <Login />
            </PublicRoute>
          }
        />
        <Route
          path="/register"
          element={
            <PublicRoute>
              <Register />
            </PublicRoute>
          }
        />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />

        {/* Shared Protected Routes */}
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <RoleBasedDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/scaling"
          element={
            <ProtectedRoute>
              <ScalingProgress />
            </ProtectedRoute>
          }
        />
        <Route
          path="/kyc"
          element={
            <ProtectedRoute>
              <UserLayout>
                <KYC />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/profile"
          element={
            <ProtectedRoute userOnly={true}>
              <UserLayout>
                <Profile />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/challenges"
          element={
            <ProtectedRoute userOnly={true}>
              <UserLayout>
                <MyChallenges />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/challenges/:id"
          element={
            <ProtectedRoute userOnly={true}>
              <UserLayout>
                <ChallengeDetails />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/documents"
          element={
            <ProtectedRoute userOnly={true}>
              <UserLayout>
                <Documents />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/wallet"
          element={
            <ProtectedRoute userOnly={true}>
              <UserLayout>
                <Wallet />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute userOnly={true}>
              <UserLayout>
                <Profile />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/notifications"
          element={
            <ProtectedRoute>
              <UserLayout>
                <Notifications />
              </UserLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings/notifications"
          element={
            <ProtectedRoute>
              <UserLayout>
                <NotificationSettings />
              </UserLayout>
            </ProtectedRoute>
          }
        />

        {/* Admin Routes */}
        <Route
          path="/admin"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <AdminDashboard />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/dashboard"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <AdminDashboard />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/analytics"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <AnalyticsDashboard />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/users"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <UserManagement />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/programs"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <ProgramsManagement />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/payments"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <PaymentsManagement />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/challenges"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <ChallengesManagement />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/kyc-approval"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <KYCApproval />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/payment-approvals"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <PaymentApprovals />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/withdrawals"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <WithdrawalManagement />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />

        <Route
          path="/admin/crm"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <CRM />
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/crm/:id"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <LeadDetails />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />

        <Route
          path="/admin/settings"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={ADMIN_ROLES}>
                <AdminLayout>
                  <Settings />
                </AdminLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />

        {/* Compatibility URLs point only to the protected canonical affiliate pages. */}
        <Route path="/agent" element={<Navigate to="/affiliate/dashboard" replace />} />
        <Route path="/agent/traders" element={<Navigate to="/affiliate/traders" replace />} />
        <Route path="/agent/commissions" element={<Navigate to="/affiliate/commissions" replace />} />
        <Route path="/agent/reports" element={<Navigate to="/affiliate/reports" replace />} />

        {/* Affiliate Routes */}
        <Route
          path="/affiliate/dashboard"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['affiliate']}>
                <UserLayout>
                  <AffiliateDashboard />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/affiliate/traders"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['affiliate']}>
                <UserLayout>
                  <TradersManagement />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/affiliate/commissions"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['affiliate']}>
                <UserLayout>
                  <Commissions />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/affiliate/reports"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['affiliate']}>
                <UserLayout>
                  <Reports />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />

        <Route path="/user/dashboard" element={
          <ProtectedRoute><RoleGuard allowedRoles={['user']}><UserLayout><TraderDashboard /></UserLayout></RoleGuard></ProtectedRoute>
        } />

        {/* Trader Routes */}
        <Route
          path="/trader"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['trader']}>
                <UserLayout>
                  <TraderDashboard />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/trader/history"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['trader']}>
                <UserLayout>
                  <TradingHistory />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/trader/withdrawals"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['trader']}>
                <UserLayout>
                  <Withdrawals />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />
        <Route
          path="/trader/documents"
          element={
            <ProtectedRoute>
              <RoleGuard allowedRoles={['trader']}>
                <UserLayout>
                  <Documents />
                </UserLayout>
              </RoleGuard>
            </ProtectedRoute>
          }
        />

        {/* 404 */}
        <Route
          path="*"
          element={
            <main className="mep-screen min-h-screen flex items-center justify-center p-4">
              <div className="text-center">
                <h1 className="mep-heading text-6xl font-bold text-slate-100 mb-4">404</h1>
                <p className="text-xl text-slate-300 mb-8">Page not found</p>
                <a href="/" className="btn btn-primary">
                  Go to Home
                </a>
              </div>
            </main>
          }
        />
        </Routes>
      </Suspense>
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
