import { Fragment, lazy, Suspense } from 'react';
import useAuthStore from '../../store/authStore';
import { ADMIN_ROLES } from '../../constants/roles';

// Import all layouts
const TraderLayout = lazy(() => import('../trader/TraderLayout'));
const AffiliateLayout = lazy(() => import('../affiliate/AffiliateLayout'));
const AdminLayout = lazy(() => import('../admin/AdminLayout'));

/**
 * UserLayout - Smart layout that detects user role and renders appropriate sidebar
 * 
 * This component automatically selects the correct layout based on the user's role:
 * - Trader → TraderLayout
 * - Affiliate → AffiliateLayout
 * - Admin/Master/Supermaster → AdminLayout
 * 
 * Usage:
 * <UserLayout>
 *   <YourPage />
 * </UserLayout>
 */
export default function UserLayout({ children }) {
  const { user } = useAuthStore();

  // Loading state
  if (!user) {
    return (
      <div className="mep-shell min-h-screen flex items-center justify-center">
        <div className="text-center" role="status" aria-live="polite">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400" aria-hidden="true"></div>
          <p className="text-gray-300 mt-4">Loading...</p>
        </div>
      </div>
    );
  }

  // Detect role and render appropriate layout
  const role = user.role;
  const identityKey = JSON.stringify([user.id ?? null, user.tenant_id ?? user.tenantId ?? user.tenant?.id ?? null, role]);
  const accountContent = <Fragment key={identityKey}>{children}</Fragment>;

  // Admin roles
  if (ADMIN_ROLES.includes(role)) {
    return (
      <Suspense fallback={
        <div className="mep-shell min-h-screen flex items-center justify-center">
          <div className="text-center" role="status" aria-live="polite">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400" aria-hidden="true"></div>
            <p className="text-gray-300 mt-4">Loading...</p>
          </div>
        </div>
      }>
        <AdminLayout>{accountContent}</AdminLayout>
      </Suspense>
    );
  }

  // Affiliate role
  if (role === 'affiliate') {
    return (
      <Suspense fallback={
        <div className="mep-shell min-h-screen flex items-center justify-center">
          <div className="text-center" role="status" aria-live="polite">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400" aria-hidden="true"></div>
            <p className="text-gray-300 mt-4">Loading...</p>
          </div>
        </div>
      }>
        <AffiliateLayout>{accountContent}</AffiliateLayout>
      </Suspense>
    );
  }

  // Trader role (default)
  return (
    <Suspense fallback={
      <div className="mep-shell min-h-screen flex items-center justify-center">
        <div className="text-center" role="status" aria-live="polite">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400" aria-hidden="true"></div>
          <p className="text-gray-300 mt-4">Loading...</p>
        </div>
      </div>
    }>
      <TraderLayout>{accountContent}</TraderLayout>
    </Suspense>
  );
}
