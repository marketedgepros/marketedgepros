import React from 'react';
import Layout from '../components/layout/Layout';
import { DollarSign, CheckCircle, Clock, AlertCircle } from 'lucide-react';

function RefundPolicy() {
  const sections = [
    {
      title: "Challenge Fees",
      icon: DollarSign,
      content: "All fees for our trading challenges are non-refundable once the challenge has started. This is because we incur costs for providing the trading platform and data feeds.",
      color: "from-cyan-500 to-blue-600"
    },
    {
      title: "Eligibility for Refund",
      icon: CheckCircle,
      content: "You may be eligible for a refund under the following circumstances:",
      items: [
        "If you request a refund within 24 hours of purchase AND you have not placed any trades.",
        "If there was a technical issue on our end that prevented you from starting the challenge."
      ],
      color: "from-green-500 to-emerald-600"
    },
    {
      title: "Processing Time",
      icon: Clock,
      content: "Refunds, if approved, will be processed within 5-7 business days to the original method of payment.",
      color: "from-purple-500 to-pink-600"
    }
  ];

  return (
    <Layout>
      <div className="min-h-screen bg-gray-900 text-white">
        {/* Hero Section */}
        <div className="relative overflow-hidden bg-gradient-to-br from-gray-900 via-blue-900/20 to-purple-900/20">
          <div className="container mx-auto px-4 sm:px-6 lg:px-8 py-24 relative">
            <div className="text-center max-w-4xl mx-auto">
              <h1 className="mep-heading text-5xl md:text-6xl font-bold mb-6">
                Refund <span className="bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">Policy</span>
              </h1>
              <p className="text-xl text-gray-300 mb-8">
                Transparent and fair refund terms for all our traders
              </p>
            </div>
          </div>
        </div>

        {/* Policy Sections */}
        <div className="container mx-auto px-4 sm:px-6 lg:px-8 py-16">
          <div className="max-w-4xl mx-auto space-y-8">
            {sections.map((section, index) => {
              const Icon = section.icon;
              return (
                <div key={index} className="bg-gray-800/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-700/50 hover:border-cyan-500/50 transition-all duration-300">
                  <div className="flex items-center gap-4 mb-6">
                    <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${section.color} flex items-center justify-center`}>
                      <Icon className="w-6 h-6 text-white" />
                    </div>
                    <h2 className="mep-heading text-2xl font-bold">{section.title}</h2>
                  </div>
                  <p className="text-gray-300 mb-4">{section.content}</p>
                  {section.items && (
                    <ul className="space-y-3 mt-4">
                      {section.items.map((item, i) => (
                        <li key={i} className="flex items-start gap-3">
                          <CheckCircle className="w-5 h-5 text-cyan-400 flex-shrink-0 mt-0.5" />
                          <span className="text-gray-300">{item}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}

            {/* How to Request */}
            <div className="bg-gradient-to-br from-cyan-900/20 to-blue-900/20 rounded-2xl p-8 border border-cyan-500/30">
              <div className="flex items-center gap-4 mb-6">
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center">
                  <AlertCircle className="w-6 h-6 text-white" />
                </div>
                <h2 className="mep-heading text-2xl font-bold">How to Request a Refund</h2>
              </div>
              <p className="text-gray-300">
                To request a refund, please contact our support team at{' '}
                <a href="mailto:info@marketedgepros.com" className="text-cyan-400 hover:text-cyan-300 transition-colors font-semibold">
                  info@marketedgepros.com
                </a>
                {' '}with your account details and reason for the request. All refund requests are subject to review.
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}

export default RefundPolicy;

