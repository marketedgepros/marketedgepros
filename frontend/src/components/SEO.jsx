import { Helmet } from 'react-helmet-async';
import { SITE_DESCRIPTION, isPrivatePage, publicSiteOrigin, publicPageUrl, serializePublicSchema } from '../services/publicMetadataService';

export default function SEO({
  title = 'MarketEdgePros',
  description = SITE_DESCRIPTION,
  keywords = 'trading programs, program comparison, account portal, trading education',
  ogImage = null,
  ogType = 'website',
  twitterCard = 'summary',
  canonical,
  noindex = false,
  nofollow = false,
  structuredData
}) {
  const siteOrigin = publicSiteOrigin(import.meta.env.VITE_PUBLIC_SITE_URL);
  const pathname = typeof window === 'undefined' ? '/' : window.location.pathname;
  const privatePage = isPrivatePage(pathname);
  const fullTitle = title === 'MarketEdgePros' ? title : `${title} | MarketEdgePros`;
  // Absolute tags require an explicit deployment origin, never the request host.
  const path = canonical || pathname;
  let canonicalUrl = publicPageUrl(siteOrigin, path);
  if (!canonicalUrl && siteOrigin && typeof canonical === 'string') {
    try { const url = new URL(canonical); if (url.origin === siteOrigin && !url.username && !url.password) canonicalUrl = url.href; } catch { /* omit invalid canonical */ }
  }
  const imageUrl = publicPageUrl(siteOrigin, ogImage);
  const hidden = noindex || privatePage;
  return (
    <Helmet>
      <title>{fullTitle}</title>
      <meta name="description" content={description} />
      <meta name="keywords" content={keywords} />
      {canonicalUrl && <link rel="canonical" href={canonicalUrl} />}
      <meta name="robots" content={`${hidden ? 'noindex' : 'index'},${nofollow || privatePage ? 'nofollow' : 'follow'}`} />
      <meta property="og:title" content={fullTitle} />
      <meta property="og:description" content={description} />
      <meta property="og:type" content={ogType} />
      {canonicalUrl && <meta property="og:url" content={canonicalUrl} />}
      {imageUrl && <meta property="og:image" content={imageUrl} />}
      <meta property="og:site_name" content="MarketEdgePros" />
      <meta name="twitter:card" content={imageUrl ? twitterCard : 'summary'} />
      <meta name="twitter:title" content={fullTitle} />
      <meta name="twitter:description" content={description} />
      {imageUrl && <meta name="twitter:image" content={imageUrl} />}
      <link rel="icon" type="image/x-icon" href="/favicon.ico" />
      <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
      {structuredData && !hidden && <script type="application/ld+json">{serializePublicSchema(structuredData)}</script>}
    </Helmet>
  );
}

// These describe page destinations, not business-policy or live-provider guarantees.
export const SEOConfigs = {
  home: { title: 'Trading Programs & Account Portal', description: SITE_DESCRIPTION },
  programs: { title: 'Trading Programs & Challenges', description: 'Compare published program settings, base fees and optional add-ons. Review payment availability before requesting a quote.' },
  onePhase: { title: 'One Phase Programs', description: 'Review one-phase program settings in the current catalog. Availability and terms depend on the published program.' },
  twoPhase: { title: 'Two Phase Programs', description: 'Review two-phase program settings in the current catalog. Targets and limits are program-specific.' },
  instantFunding: { title: 'Program Availability', description: 'Explore the current program catalog and review its published settings. Catalog information is not confirmation of funding.' },
  about: { title: 'About MarketEdgePros', description: 'Learn about the MarketEdgePros platform, program comparison and account tools.' },
  howItWorks: { title: 'How It Works', description: 'Understand program comparison, account registration and quote availability. A quote is not a payment or trading account.' },
  faq: { title: 'Frequently Asked Questions', description: 'Find information about the catalog, account access, support and current service availability.' },
  contact: { title: 'Contact & Support', description: 'Find available support routes for questions about your MarketEdgePros account and program information.' },
  login: { title: 'Login', description: 'Sign in to access the tools available to your MarketEdgePros account.', noindex: true },
  register: { title: 'Create an Account', description: 'Create a MarketEdgePros account. Registration does not purchase a program or confirm funding.', noindex: true },
  dashboard: { title: 'Account Dashboard', description: 'View the records and account tools available to your MarketEdgePros account.', noindex: true }
};
