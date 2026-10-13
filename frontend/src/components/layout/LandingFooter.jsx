import { Link } from 'react-router-dom';
import { Facebook, Twitter, Instagram, Linkedin, Youtube, Mail, MessageCircle } from 'lucide-react';

export default function LandingFooter() {
  const currentYear = new Date().getFullYear();
  
  const footerSections = [
    {
      title: 'Company',
      links: [
        { name: 'About Us', to: '/about' },
        { name: 'How It Works', to: '/how-it-works' },
        { name: 'Blog', to: '/blog' },
        { name: 'Careers', to: '/careers' },
        { name: 'Contact', to: '/contact' },
      ],
    },
    {
      title: 'Programs',
      links: [
        { name: 'Current catalog', to: '/programs' },
        { name: 'Compare programs', to: '/programs#program-comparison' },
      ],
    },
    {
      title: 'Resources',
      links: [
        { name: 'Support Hub', to: '/support' },
        { name: 'FAQ', to: '/faq' },
        { name: 'Trading Rules', to: '/trading-rules' },
        { name: 'Affiliate Program', to: '/affiliate' },
        // { name: 'API Documentation', to: '/api-docs' }, // Removed - page doesn't exist
      ],
    },
    {
      title: 'Legal',
      links: [
        { name: 'Terms of Service', to: '/terms-of-service' },
        { name: 'Privacy Policy', to: '/privacy-policy' },
        { name: 'Risk Disclosure', to: '/risk-disclosure' },
        { name: 'Refund Policy', to: '/refund-policy' },
        { name: 'Cookie Policy', to: '/cookie-policy' },
        { name: 'Analytics status', to: '/cookie-policy#analytics-status' },
      ],
    },
  ];

  const socialLinks = [
    { name: 'Facebook', icon: Facebook, href: 'https://facebook.com/marketedgepros' },
    { name: 'Twitter', icon: Twitter, href: 'https://twitter.com/marketedgepros' },
    { name: 'Instagram', icon: Instagram, href: 'https://instagram.com/marketedgepros' },
    { name: 'LinkedIn', icon: Linkedin, href: 'https://linkedin.com/company/marketedgepros' },
    { name: 'YouTube', icon: Youtube, href: 'https://youtube.com/@marketedgepros' },
    { name: 'Discord', icon: MessageCircle, href: 'https://discord.gg/jKbmeSe7' },
  ];

  return (
    <footer className="min-w-0 bg-slate-950 border-t border-white/10">
      {/* Main Footer */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-8">
          {/* Brand Column */}
          <div className="lg:col-span-1">
            <Link to="/" className="mb-4 flex items-center space-x-2 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
              <div className="mep-brand-mark text-lg" aria-hidden="true">M</div>
              <span className="break-words text-xl font-bold text-white">MarketEdgePros</span>
            </Link>
            <p className="text-gray-400 text-sm mb-6">
              Explore program settings, compare options and manage your account in one place.
            </p>
            
            {/* Social Links */}
            <div className="flex flex-wrap gap-2">
              {socialLinks.map((social) => (
                <a
                  key={social.name}
                  href={social.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-gray-400 hover:text-cyan-500 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                  aria-label={social.name}
                >
                  <social.icon size={20} />
                </a>
              ))}
            </div>
          </div>

          {/* Footer Sections */}
          {footerSections.map((section) => (
            <div key={section.title}>
              <h3 className="text-white font-semibold mb-4">{section.title}</h3>
              <ul className="space-y-2">
                {section.links.map((link) => (
                  <li key={link.name}>
                    <Link
                      to={link.to}
                      className="rounded px-1 py-1 text-sm text-gray-400 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                    >
                      {link.name}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Newsletter Section */}
        <div className="mt-12 pt-8 border-t border-white/10">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="text-center md:text-left">
              <h3 className="text-white font-semibold mb-2">Information and help</h3>
              <p className="text-gray-400 text-sm">Newsletter subscriptions and message submission are unavailable. View the contact page for current information and available help options.</p>
            </div>
            <Link to="/contact" className="mep-cta max-w-full text-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200">
                <Mail size={18} className="mr-2" />
                View contact options
            </Link>
          </div>
        </div>
      </div>

      {/* Bottom Bar */}
      <div className="border-t border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-gray-400">
            <p>© {currentYear} MarketEdgePros. All rights reserved.</p>
            <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
              <Link to="/terms-of-service" className="rounded px-1 py-1 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Terms</Link>
              <Link to="/privacy-policy" className="rounded px-1 py-1 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Privacy</Link>
              <Link to="/risk-disclosure" className="rounded px-1 py-1 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Risk Disclosure</Link>
            </div>
          </div>
        </div>
      </div>

      {/* Risk Warning */}
      <div className="bg-red-900/20 border-t border-red-500/20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <p className="text-xs text-gray-400 text-center">
            <strong className="text-red-400">Risk Warning:</strong> Trading forex and CFDs involves significant risk of loss and is not suitable for all investors. 
            Past performance is not indicative of future results. Please ensure you fully understand the risks involved.
          </p>
        </div>
      </div>
    </footer>
  );
}
