import React from 'react';
import Layout from '../components/layout/Layout';
import { AlertTriangle, TrendingDown, DollarSign, Target, Shield } from 'lucide-react';

export default function RiskDisclosure() {
  const risks = [
    {
      icon: TrendingDown,
      title: "Market Volatility",
      description: "Financial markets can be extremely volatile. Prices can change rapidly in very short periods, potentially resulting in substantial losses."
    },
    {
      icon: DollarSign,
      title: "Leverage Risk",
      description: "Trading with leverage amplifies both potential profits and losses. You can lose more than your initial investment when using leverage."
    },
    {
      icon: Target,
      title: "No Guarantee of Profit",
      description: "Past performance is not indicative of future results. There is no guarantee that any trading strategy will be profitable."
    },
    {
      icon: Shield,
      title: "Capital Loss",
      description: "You should only trade with money you can afford to lose. Never trade with borrowed money or funds needed for essential expenses."
    }
  ];

  return (
    <Layout>
      <div className="min-h-screen bg-black text-white">
        {/* Hero Section */}
        <section className="relative min-h-[60vh] flex items-center justify-center overflow-hidden">
          <div className="absolute inset-0 z-0">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(239,68,68,0.1)_0%,transparent_65%)]"></div>
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_80%_20%,rgba(251,146,60,0.15)_0%,transparent_50%)]"></div>
          </div>

          <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <div className="flex justify-center mb-6">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center animate-pulse">
                <AlertTriangle className="w-10 h-10 text-white" />
              </div>
            </div>
            <h1 className="mep-heading text-5xl md:text-7xl font-bold mb-8">
              Risk{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-orange-400">
                Disclosure
              </span>
            </h1>
            <p className="text-xl md:text-2xl text-gray-300 max-w-3xl mx-auto">
              Important information about the risks of trading you must understand
            </p>
          </div>
        </section>

        {/* Warning Banner */}
        <section className="relative py-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="bg-gradient-to-br from-red-500/20 to-orange-500/20 border-2 border-red-500/50 rounded-2xl p-8">
              <div className="flex items-start gap-4">
                <AlertTriangle className="w-8 h-8 text-red-400 flex-shrink-0 mt-1" />
                <div>
                  <h3 className="text-2xl font-bold mb-4 text-red-400">High Risk Warning</h3>
                  <p className="text-gray-300 text-lg leading-relaxed mb-4">
                    Trading foreign exchange, contracts for difference (CFDs), and other leveraged products involves substantial risk of loss 
                    and may not be suitable for all investors. The high degree of leverage can work against you as well as for you.
                  </p>
                  <p className="text-gray-300 text-lg leading-relaxed">
                    Before deciding to trade, you should carefully consider your investment objectives, level of experience, and risk appetite. 
                    You should only trade with money you can afford to lose.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Risk Cards */}
        <section className="relative py-16">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
            <h2 className="mep-heading text-4xl font-bold mb-12 text-center">
              Key{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-orange-400">
                Risk Factors
              </span>
            </h2>
            <div className="grid md:grid-cols-2 gap-8">
              {risks.map((risk, index) => {
                const Icon = risk.icon;
                return (
                  <div
                    key={index}
                    className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8 hover:bg-white/10 transition-all duration-300"
                  >
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center mb-6">
                      <Icon className="w-6 h-6 text-white" />
                    </div>
                    <h3 className="text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-orange-400">
                      {risk.title}
                    </h3>
                    <p className="text-gray-300 text-lg leading-relaxed">
                      {risk.description}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* Additional Information */}
        <section className="relative py-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8">
            <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8">
              <h3 className="text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">
                Past Performance
              </h3>
              <p className="text-gray-300 text-lg leading-relaxed">
                Past performance is not indicative of future results. Any trading symbols displayed are for illustrative purposes only 
                and are not intended to portray recommendations. Hypothetical or simulated performance results have certain limitations.
              </p>
            </div>

            <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8">
              <h3 className="text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400">
                No Financial Advice
              </h3>
              <p className="text-gray-300 text-lg leading-relaxed">
                MarketEdgePros does not provide investment, legal, or tax advice. Our services are for educational and evaluation purposes only. 
                You should seek advice from independent financial advisors regarding your specific circumstances.
              </p>
            </div>

            <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8">
              <h3 className="text-2xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-red-400">
                Demo vs Live Trading
              </h3>
              <p className="text-gray-300 text-lg leading-relaxed">
                Demo trading results may not reflect the impact of certain market factors such as liquidity, slippage, and execution delays 
                that can significantly affect actual trading results. Success in demo trading does not guarantee success in live trading.
              </p>
            </div>
          </div>
        </section>

        {/* Acknowledgment */}
        <section className="relative py-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="bg-gradient-to-br from-red-500/10 to-orange-500/10 border border-red-500/30 rounded-2xl p-8 text-center">
              <h3 className="text-2xl font-bold mb-4">Acknowledgment</h3>
              <p className="text-gray-300 text-lg mb-6">
                By using our services, you acknowledge that you have read and understood this risk disclosure and accept the risks associated with trading.
              </p>
              <p className="text-gray-400">
                If you have any questions about these risks, please contact us at{' '}
                <a href="mailto:info@marketedgepros.com" className="text-red-400 hover:text-red-300 transition-colors font-semibold">
                  info@marketedgepros.com
                </a>
              </p>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}

