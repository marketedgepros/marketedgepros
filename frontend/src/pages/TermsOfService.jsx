import React from 'react';
import Layout from '../components/layout/Layout';
import { FileText, AlertCircle } from 'lucide-react';

export default function TermsOfService() {
  const sections = [
    {
      title: "1. Acceptance of Terms",
      content: "By accessing and using MarketEdgePros services, you accept and agree to be bound by the terms and provision of this agreement. If you do not agree to these terms, please do not use our services."
    },
    {
      title: "2. Eligibility",
      content: "You must be at least 18 years old and legally capable of entering into binding contracts to use our services. By using our platform, you represent and warrant that you meet these requirements."
    },
    {
      title: "3. Account Registration",
      content: "To access certain features, you must register for an account. You agree to provide accurate, current, and complete information during registration and to update such information to keep it accurate, current, and complete."
    },
    {
      title: "4. Trading Rules",
      content: "All traders must comply with our trading rules, including but not limited to: maximum daily loss limits, maximum total drawdown limits, minimum trading days requirements, and prohibited trading strategies. Violation of these rules may result in account termination."
    },
    {
      title: "5. Fees and Payments",
      content: "Challenge fees are non-refundable once the challenge has started. All fees must be paid in full before accessing the trading platform. We reserve the right to modify our fee structure at any time."
    },
    {
      title: "6. Profit Sharing",
      content: "Funded traders are entitled to keep up to 90% of their profits, depending on their program. Profit splits are calculated based on closed trades and are subject to our withdrawal policies."
    },
    {
      title: "7. Risk Disclosure",
      content: "Trading involves substantial risk of loss. Past performance is not indicative of future results. You should carefully consider whether trading is appropriate for you in light of your experience, objectives, financial resources, and other relevant circumstances."
    },
    {
      title: "8. Intellectual Property",
      content: "All content on our platform, including text, graphics, logos, and software, is the property of MarketEdgePros and is protected by intellectual property laws. You may not reproduce, distribute, or create derivative works without our express written permission."
    },
    {
      title: "9. Limitation of Liability",
      content: "MarketEdgePros shall not be liable for any indirect, incidental, special, consequential, or punitive damages resulting from your use or inability to use our services."
    },
    {
      title: "10. Termination",
      content: "We reserve the right to terminate or suspend your account at any time, with or without cause, with or without notice. Upon termination, your right to use our services will immediately cease."
    },
    {
      title: "11. Modifications",
      content: "We reserve the right to modify these terms at any time. We will notify users of any material changes. Your continued use of our services after such modifications constitutes your acceptance of the updated terms."
    },
    {
      title: "12. Governing Law",
      content: "These terms shall be governed by and construed in accordance with the laws of the jurisdiction in which MarketEdgePros operates, without regard to its conflict of law provisions."
    }
  ];

  return (
    <Layout>
      <div className="min-h-screen bg-black text-white">
        {/* Hero Section */}
        <section className="relative min-h-[60vh] flex items-center justify-center overflow-hidden">
          <div className="absolute inset-0 z-0">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(6,182,212,0.1)_0%,transparent_65%)]"></div>
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_80%_20%,rgba(168,85,247,0.15)_0%,transparent_50%)]"></div>
          </div>

          <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <div className="flex justify-center mb-6">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-cyan-500 to-teal-500 flex items-center justify-center">
                <FileText className="w-10 h-10 text-white" />
              </div>
            </div>
            <h1 className="mep-heading text-5xl md:text-7xl font-bold mb-8">
              Terms of{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">
                Service
              </span>
            </h1>
            <p className="text-xl md:text-2xl text-gray-300 max-w-3xl mx-auto">
              Please read these terms carefully before using our services
            </p>
            <p className="text-sm text-gray-400 mt-4">Last Updated: January 1, 2025</p>
          </div>
        </section>

        {/* Content Section */}
        <section className="relative py-32">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="bg-gradient-to-br from-yellow-500/10 to-orange-500/10 border border-yellow-500/30 rounded-2xl p-8 mb-16">
              <div className="flex items-start gap-4">
                <AlertCircle className="w-6 h-6 text-yellow-400 flex-shrink-0 mt-1" />
                <div>
                  <h3 className="text-xl font-bold mb-2 text-yellow-400">Important Notice</h3>
                  <p className="text-gray-300">
                    These Terms of Service constitute a legally binding agreement between you and MarketEdgePros. 
                    By using our services, you acknowledge that you have read, understood, and agree to be bound by these terms.
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-8">
              {sections.map((section, index) => (
                <div
                  key={index}
                  className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8 hover:bg-white/10 transition-all duration-300"
                >
                  <h2 className="mep-heading text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">
                    {section.title}
                  </h2>
                  <p className="text-gray-300 text-lg leading-relaxed">
                    {section.content}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-16 bg-gradient-to-br from-cyan-500/10 to-teal-500/10 border border-cyan-500/30 rounded-2xl p-8 text-center">
              <h3 className="text-2xl font-bold mb-4">Questions About These Terms?</h3>
              <p className="text-gray-300 mb-6">
                If you have any questions or concerns about these Terms of Service, please contact us
              </p>
              <a
                href="mailto:legal@marketedgepros.com"
                className="mep-primary inline-block px-8 py-4 font-semibold transition-all duration-300 hover:scale-105"
              >
                Contact Legal Team
              </a>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}

