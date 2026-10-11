import { ADMIN_ROLES } from '../constants/roles.js';

export const ACCOUNT_PATHS = Object.freeze({
  affiliate: '/affiliate/dashboard',
  trader: '/trader',
  user: '/user/dashboard',
  admin: '/admin',
});

export function accountHome(user) {
  if (ADMIN_ROLES.includes(user?.role)) return ACCOUNT_PATHS.admin;
  if (user?.role === 'affiliate') return ACCOUNT_PATHS.affiliate;
  if (user?.role === 'trader') return ACCOUNT_PATHS.trader;
  if (user?.role === 'user') return ACCOUNT_PATHS.user;
  return '/';
}

export function programCheckoutPath(id) {
  const value = String(id ?? '');
  if (!/^[1-9]\d{0,9}$/.test(value)) throw new Error('Invalid program identifier.');
  return `/programs/${value}/checkout`;
}

const PUBLIC_DESTINATIONS = /^\/(?:$|programs(?:\/[1-9]\d{0,9}(?:\/checkout)?)?|about|how-it-works|faq|contact|affiliate|lightning-challenge|support|blog|terms-of-service|privacy-policy|risk-disclosure|trading-rules|refund-policy|cookie-policy|careers)$/;
const SHARED_DESTINATIONS = /^\/(?:dashboard|scaling|kyc|notifications|settings\/notifications|support\/(?:create-ticket|my-tickets|ticket\/[A-Za-z0-9_-]+))$/;
const CUSTOMER_DESTINATIONS = /^\/(?:profile|settings|wallet|documents|challenges(?:\/[1-9]\d{0,9})?)$/;
const AFFILIATE_DESTINATIONS = /^\/affiliate\/(?:dashboard|traders|commissions|reports|payout)$/;
const TRADER_DESTINATIONS = /^\/trader(?:\/(?:history|withdrawals|documents))?$/;
const ADMIN_DESTINATIONS = /^\/admin(?:\/(?:dashboard|analytics|users|programs|payments|challenges|kyc-approval|payment-approvals|withdrawals|crm(?:\/[1-9]\d{0,9})?|settings))?$/;

// An untrusted redirect must be an existing, local destination permitted by the UI role.
// Server authorization remains authoritative; this is not an access-control replacement.
export function postLoginDestination(user, search = '') {
  const fallback = accountHome(user);
  const candidate = new URLSearchParams(search).get('redirect');
  if (!candidate || candidate.length > 2048 || !candidate.startsWith('/')
      || candidate.startsWith('//') || /[\\\s\u0000-\u001f\u007f]/.test(candidate)
      || /%(?:2f|5c|0[0-9a-f]|1[0-9a-f]|7f)/i.test(candidate)) return fallback;
  const path = candidate.split(/[?#]/, 1)[0];
  const admin = ADMIN_ROLES.includes(user?.role);
  const allowed = PUBLIC_DESTINATIONS.test(path) || SHARED_DESTINATIONS.test(path)
    || (!admin && CUSTOMER_DESTINATIONS.test(path))
    || (user?.role === 'affiliate' && AFFILIATE_DESTINATIONS.test(path))
    || (user?.role === 'trader' && TRADER_DESTINATIONS.test(path))
    || (user?.role === 'user' && path === ACCOUNT_PATHS.user)
    || (admin && ADMIN_DESTINATIONS.test(path));
  return allowed ? candidate : fallback;
}
