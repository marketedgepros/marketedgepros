import React from 'react';
import Layout from '../components/layout/Layout';
import { Cookie, Shield, BarChart3, Settings } from 'lucide-react';
import AnalyticsStatus from '../components/privacy/AnalyticsStatus';

function CookiePolicy() {
  const cookieTypes = [
    {
      title: "Essential Cookies",
      icon: Shield,
      description: "These are necessary to provide you with services available through our website and to use some of its features, such as access to secure areas.",
      color: "from-cyan-500 to-blue-600"
    },
    {
      title: "Performance Cookies",
      icon: BarChart3,
      description: "These are used to enhance the performance and functionality of our website but are non-essential to their use.",
      color: "from-purple-500 to-pink-600"
    },
    {
      title: "Analytics Cookies",
      icon: Settings,
      description: "These cookies collect information that is used either in aggregate form to help us understand how our website is being used or how effective our marketing campaigns are.",
      color: "from-green-500 to-emerald-600"
    }
  ];

  return (
    <Layout>
      <div className="min-h-screen bg-gray-900 text-white">
        {/* Hero Section */}
        <div className="relative overflow-hidden bg-gradient-to-br from-gray-900 via-blue-900/20 to-purple-900/20">
          <div className="container mx-auto px-4 sm:px-6 lg:px-8 py-24 relative">
            <div className="text-center max-w-4xl mx-auto">
              <div className="flex justify-center mb-6">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center">
                  <Cookie className="w-10 h-10 text-white" />
                </div>
              </div>
              <h1 className="mep-heading text-5xl md:text-6xl font-bold mb-6">
                Cookie <span className="bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">Policy</span>
              </h1>
              <p className="text-xl text-gray-300 mb-8">
                Understanding how we use cookies to enhance your experience
              </p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 sm:px-6 lg:px-8 py-16">
          <div className="max-w-4xl mx-auto space-y-8">
            <AnalyticsStatus />
            <div className="rounded-2xl border border-amber-400/30 bg-amber-950/20 p-5 text-sm leading-6 text-amber-100 sm:p-8">
              <h2 className="mep-heading text-lg font-semibold">Cookie policy draft — awaiting approval</h2>
              <p className="mt-2">
                The policy wording below is retained for review and has not been confirmed as the
                current collection configuration. In particular, the analytics category below does
                not mean that Google Analytics is enabled in this version. The technical status above
                describes the current implementation; final policy wording remains to be approved.
              </p>
            </div>
            {/* What are cookies */}
            <div className="bg-gray-800/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-700/50">
              <h2 className="mep-heading text-3xl font-bold mb-4 bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">
                What are cookies?
              </h2>
              <p className="text-gray-300 text-lg">
                Cookies are small data files that are placed on your computer or mobile device when you visit a website. Cookies are widely used by website owners in order to make their websites work, or to work more efficiently, as well as to provide reporting information.
              </p>
            </div>

            {/* How we use cookies */}
            <div className="bg-gray-800/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-700/50">
              <h2 className="mep-heading text-3xl font-bold mb-4 bg-gradient-to-r from-purple-400 to-pink-500 bg-clip-text text-transparent">
                How we use cookies
              </h2>
              <p className="text-gray-300 text-lg">
                We use cookies for several reasons. Some cookies are required for technical reasons in order for our website to operate, and we refer to these as "essential" or "strictly necessary" cookies. Other cookies also enable us to track and target the interests of our users to enhance the experience on our website.
              </p>
            </div>

            {/* Types of cookies */}
            <div>
              <h2 className="mep-heading text-3xl font-bold mb-8 text-center">Types of cookies we use</h2>
              <div className="grid md:grid-cols-3 gap-6">
                {cookieTypes.map((type, index) => {
                  const Icon = type.icon;
                  return (
                    <div key={index} className="bg-gray-800/50 backdrop-blur-sm rounded-2xl p-6 border border-gray-700/50 hover:border-cyan-500/50 transition-all duration-300">
                      <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${type.color} flex items-center justify-center mb-4`}>
                        <Icon className="w-6 h-6 text-white" />
                      </div>
                      <h3 className="text-xl font-bold mb-3">{type.title}</h3>
                      <p className="text-gray-400">{type.description}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Your choices */}
            <div className="bg-gradient-to-br from-cyan-900/20 to-blue-900/20 rounded-2xl p-8 border border-cyan-500/30">
              <h2 className="mep-heading text-3xl font-bold mb-4">Your choices</h2>
              <p className="text-gray-300 text-lg mb-4">
                You have the right to decide whether to accept or reject cookies. You can exercise your cookie preferences by setting or amending your web browser controls to accept or refuse cookies.
              </p>
              <p className="text-gray-300 text-lg">
                If you have any questions about our use of cookies, please contact us at{' '}
                <a href="mailto:info@marketedgepros.com" className="text-cyan-400 hover:text-cyan-300 transition-colors font-semibold">
                  info@marketedgepros.com
                </a>
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}

export default CookiePolicy;
