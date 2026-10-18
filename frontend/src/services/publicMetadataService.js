export const SITE_DESCRIPTION = "Explore trading programs, compare published settings and manage your MarketEdgePros account.";

export function publicSiteOrigin(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/") return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function publicPageUrl(origin, path) {
  if (!origin || typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) return null;
  try {
    const url = new URL(path, origin);
    return url.origin === origin && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

export function isPrivatePage(path) {
  return /^\/(?:admin|affiliate\/(?:dashboard|payout|traders|commissions|reports)|trader|user|dashboard|scaling|kyc|profile|settings|challenges|documents|wallet|notifications|login|register|verify-email|forgot-password|reset-password|support\/(?:create-ticket|my-tickets|ticket))(?:\/|$)/.test(path || "");
}

const text = (value) => typeof value === "string" && value.trim() ? value.trim() : null;
const date = (value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$/.test(value) && Number.isFinite(Date.parse(value)) ? value : null;
const base = (type) => ({ "@context": "https://schema.org", "@type": type });

export function buildPublicSchema(type, data = {}, origin = null) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  switch (type) {
    case "website":
    case "organization":
      return { ...base(type === "website" ? "WebSite" : "Organization"), name: "MarketEdgePros", description: SITE_DESCRIPTION, ...(origin ? { url: origin } : {}) };
    case "product": {
      // Published catalog information is not a purchasable offer or confirmed funding.
      // Do not manufacture Offer/InStock/zero price from a catalog-only record.
      if (!text(data.name)) return null;
      return { ...base("Product"), name: text(data.name), ...(text(data.description) ? { description: text(data.description) } : {}), brand: { "@type": "Brand", name: "MarketEdgePros" } };
    }
    case "faq": {
      const questions = Array.isArray(data.questions) ? data.questions.filter(q => q && text(q.question) && text(q.answer)) : [];
      return questions.length ? { ...base("FAQPage"), mainEntity: questions.map(q => ({ "@type": "Question", name: text(q.question), acceptedAnswer: { "@type": "Answer", text: text(q.answer) } })) } : null;
    }
    case "article": {
      if (!text(data.title)) return null;
      const published = date(data.datePublished);
      const modified = date(data.dateModified);
      return { ...base("Article"), headline: text(data.title), ...(text(data.description) ? { description: text(data.description) } : {}), publisher: { "@type": "Organization", name: "MarketEdgePros" }, ...(published ? { datePublished: published } : {}), ...(modified ? { dateModified: modified } : {}) };
    }
    case "breadcrumb": {
      if (!origin || !Array.isArray(data.items)) return null;
      const items = data.items.map(item => {
        if (!item || !text(item.name) || typeof item.url !== "string") return null;
        const url = item.url.startsWith("/") ? publicPageUrl(origin, item.url) : (() => { try { const u = new URL(item.url); return u.origin === origin && !u.username && !u.password ? u.href : null; } catch { return null; } })();
        return url ? { name: text(item.name), url } : null;
      });
      if (!items.length || items.some(item => !item)) return null;
      return { ...base("BreadcrumbList"), itemListElement: items.map((item, index) => ({ "@type": "ListItem", position: index + 1, name: item.name, item: item.url })) };
    }
    default:
      return null;
  }
}

export function serializePublicSchema(schema) {
  // Escape script-breaking characters even for later static/SSR consumers.
  return JSON.stringify(schema).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}
