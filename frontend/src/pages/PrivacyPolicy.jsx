import React from 'react';
import Layout from '../components/layout/Layout';
import { Shield, Lock, Eye, Database, UserCheck } from 'lucide-react';

export default function PrivacyPolicy() {
  const sections = [
    {
      icon: Database,
      title: "Information We Collect",
      content: "We collect information you provide directly to us, such as when you create an account, participate in our challenges, or contact us for support. This includes your name, email address, payment information, and trading data."
    },
    {
      icon: Eye,
      title: "How We Use Your Information",
      content: "We use the information we collect to provide, maintain, and improve our services, process your transactions, send you technical notices and support messages, and respond to your comments and questions."
    },
    {
      icon: Lock,
      title: "Information Security",
      content: "We take reasonable measures to help protect your personal information from loss, theft, misuse, unauthorized access, disclosure, alteration, and destruction. However, no internet or email transmission is ever fully secure or error-free."
    },
    {
      icon: UserCheck,
      title: "Your Rights",
      content: "You have the right to access, update, or delete your personal information at any time. You may also opt out of receiving promotional communications from us by following the instructions in those messages."
    }
  ];

  const dataTypes = [
    "Account information (name, email, password)",
    "Payment and billing information",
    "Trading history and performance data",
    "Device and usage information",
    "Communications with our support team",
    "Cookies and similar tracking technologies"
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
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                <Shield className="w-10 h-10 text-white" />
              </div>
            </div>
            <h1 className="mep-heading text-5xl md:text-7xl font-bold mb-8">
              Privacy{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400">
                Policy
              </span>
            </h1>
            <p className="text-xl md:text-2xl text-gray-300 max-w-3xl mx-auto">
              Your privacy is important to us. Learn how we collect, use, and protect your data.
            </p>
            <p className="text-sm text-gray-400 mt-4">Last Updated: January 1, 2025</p>
          </div>
        </section>

        {/* Main Sections */}
        <section className="relative py-32">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="grid md:grid-cols-2 gap-8 mb-16">
              {sections.map((section, index) => {
                const Icon = section.icon;
                return (
                  <div
                    key={index}
                    className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8 hover:bg-white/10 transition-all duration-300"
                  >
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center mb-6">
                      <Icon className="w-6 h-6 text-white" />
                    </div>
                    <h2 className="mep-heading text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400">
                      {section.title}
                    </h2>
                    <p className="text-gray-300 text-lg leading-relaxed">
                      {section.content}
                    </p>
                  </div>
                );
              })}
            </div>

            {/* Data We Collect */}
            <div className="max-w-4xl mx-auto mb-16">
              <h2 className="mep-heading text-4xl font-bold mb-8 text-center">
                Data We{' '}
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">
                  Collect
                </span>
              </h2>
              <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8">
                <ul className="space-y-4">
                  {dataTypes.map((item, index) => (
                    <li key={index} className="flex items-start gap-3">
                      <div className="w-2 h-2 rounded-full bg-gradient-to-r from-purple-400 to-pink-400 mt-2 flex-shrink-0"></div>
                      <span className="text-gray-300 text-lg">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {/* Additional Sections */}
            <div className="max-w-4xl mx-auto space-y-8">
              <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8">
                <h3 className="text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">
                  Cookies and Tracking
                </h3>
                <p className="text-gray-300 text-lg leading-relaxed">
                  We use cookies and similar tracking technologies to track activity on our service and hold certain information. 
                  You can instruct your browser to refuse all cookies or to indicate when a cookie is being sent.
                </p>
              </div>

              <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8">
                <h3 className="text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400">
                  Third-Party Services
                </h3>
                <p className="text-gray-300 text-lg leading-relaxed">
                  We may employ third-party companies and individuals to facilitate our service, provide the service on our behalf, 
                  perform service-related services, or assist us in analyzing how our service is used.
                </p>
              </div>

              <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8">
                <h3 className="text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">
                  Changes to This Policy
                </h3>
                <p className="text-gray-300 text-lg leading-relaxed">
                  We may update our Privacy Policy from time to time. We will notify you of any changes by posting the new Privacy Policy on this page 
                  and updating the "Last Updated" date.
                </p>
              </div>
            </div>

            {/* Contact Section */}
            <div className="mt-16 max-w-4xl mx-auto bg-gradient-to-br from-purple-500/10 to-pink-500/10 border border-purple-500/30 rounded-2xl p-8 text-center">
              <h3 className="text-2xl font-bold mb-4">Questions About Your Privacy?</h3>
              <p className="text-gray-300 mb-6">
                If you have any questions about this Privacy Policy, please contact us
              </p>
              <a
                href="mailto:privacy@marketedgepros.com"
                className="inline-block px-8 py-4 bg-gradient-to-r from-purple-500 to-pink-500 rounded-full font-semibold transition-all duration-300 hover:scale-105 hover:shadow-2xl hover:shadow-purple-500/50"
              >
                Contact Privacy Team
              </a>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}

