import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Zap, Clock, TrendingUp, Shield, CheckCircle, ArrowRight, Star } from 'lucide-react';
import Layout from '../components/layout/Layout';
import SEO from '../components/SEO';
import StructuredData from '../components/seo/StructuredData';
import api from "../services/api";
import { programCheckoutPath } from '../services/navigationService.js';



export default function LightningChallenge() {
  const [programs, setPrograms] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetchPrograms();
  }, []);

  const fetchPrograms = async () => {
    try {
      const response = await api.get('/programs/');
      const lightningPrograms = response.data.programs?.filter(p => p.type === 'lightning') || [];
      setPrograms(lightningPrograms);
    } catch (error) {
      console.error('Failed to fetch programs:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleGetStarted = (programId) => {
    navigate(programCheckoutPath(programId));
  };

  const features = [
    {
      icon: Zap,
      title: 'Lightning Fast',
      description: 'Get funded in as little as 1 day with our accelerated evaluation process'
    },
    {
      icon: Clock,
      title: 'No Time Limits',
      description: 'Trade at your own pace - no pressure, no deadlines, just pure skill'
    },
    {
      icon: TrendingUp,
      title: 'Lower Targets',
      description: '6% profit target - easier to achieve while maintaining consistency'
    },
    {
      icon: Shield,
      title: 'Flexible Rules',
      description: 'Trade news, hold overnight, use EAs - maximum trading freedom'
    }
  ];

  const benefits = [
    'Single-phase evaluation',
    '6% profit target (vs 8-10% standard)',
    'No minimum trading days',
    'Trade during news events',
    'Weekend holding allowed',
    'Expert Advisors (EAs) permitted',
    'Up to 90% profit split',
    'Bi-weekly payouts',
    'Scale up to $400K',
    'Free retake on first attempt'
  ];

  const comparisonData = [
    {
      feature: 'Evaluation Phases',
      standard: '2 Phases',
      lightning: '1 Phase',
      highlight: true
    },
    {
      feature: 'Profit Target',
      standard: '8% + 5%',
      lightning: '6%',
      highlight: true
    },
    {
      feature: 'Time Limit',
      standard: 'Unlimited',
      lightning: 'Unlimited',
      highlight: false
    },
    {
      feature: 'Max Daily Loss',
      standard: '5%',
      lightning: '5%',
      highlight: false
    },
    {
      feature: 'Max Total Loss',
      standard: '10%',
      lightning: '10%',
      highlight: false
    },
    {
      feature: 'Minimum Trading Days',
      standard: '5 days',
      lightning: 'None',
      highlight: true
    },
    {
      feature: 'News Trading',
      standard: 'Allowed',
      lightning: 'Allowed',
      highlight: false
    },
    {
      feature: 'Profit Split',
      standard: '80-90%',
      lightning: '80-90%',
      highlight: false
    }
  ];

  return (
    <Layout>
      <SEO
        title="Lightning Challenge - Get Funded in 1 Day"
        description="Our fastest path to funded trading. Single-phase evaluation with 6% profit target. Get funded in as little as 1 day. No minimum trading days required."
        keywords="lightning challenge, fast funding, quick evaluation, single phase challenge, prop trading"
      />
      <StructuredData
        type="product"
        data={{
          name: 'Lightning Challenge',
          description: 'Fast-track prop trading evaluation with single-phase challenge',
          price: programs[0]?.price || '0',
          url: 'https://marketedgepros.com/lightning-challenge'
        }}
      />

      {/* Hero Section */}
      <section className="relative pt-32 pb-20 overflow-hidden bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
        <div className="absolute inset-0">
          <div className="absolute top-20 left-10 w-96 h-96 bg-yellow-500/20 rounded-full blur-3xl animate-pulse"></div>
          <div className="absolute bottom-20 right-10 w-96 h-96 bg-purple-500/20 rounded-full blur-3xl animate-pulse"></div>
        </div>

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <div className="inline-block mb-4 px-4 py-2 bg-yellow-500/10 border border-yellow-500/30 rounded-full animate-pulse">
            <span className="text-yellow-400 text-sm font-semibold flex items-center gap-2">
              <Zap className="w-4 h-4" />
              FASTEST PATH TO FUNDING
            </span>
          </div>

          <h1 className="text-5xl md:text-7xl font-bold mb-6">
            <span className="text-white">Get Funded in </span>
            <span className="bg-gradient-to-r from-yellow-400 to-orange-500 bg-clip-text text-transparent">
              1 Day
            </span>
          </h1>

          <p className="text-xl text-gray-300 mb-8 max-w-3xl mx-auto">
            Our revolutionary Lightning Challenge gets you funded faster than ever. Single-phase evaluation, 6% target, no minimum trading days.
          </p>

          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-12">
            <a
              href="#programs"
              className="px-8 py-4 bg-gradient-to-r from-yellow-500 to-orange-600 rounded-lg text-white font-bold text-lg hover:from-yellow-600 hover:to-orange-700 transition transform hover:scale-105 flex items-center justify-center gap-2"
            >
              <Zap className="w-5 h-5" />
              Start Lightning Challenge
            </a>
            <a
              href="#comparison"
              className="px-8 py-4 bg-white/10 backdrop-blur-sm border border-white/20 rounded-lg text-white font-bold text-lg hover:bg-white/20 transition"
            >
              Compare Programs
            </a>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            <div className="text-center">
              <div className="text-4xl font-bold text-yellow-400 mb-2">1 Day</div>
              <div className="text-gray-400">Fastest Funding</div>
            </div>
            <div className="text-center">
              <div className="text-4xl font-bold text-orange-400 mb-2">6%</div>
              <div className="text-gray-400">Profit Target</div>
            </div>
            <div className="text-center">
              <div className="text-4xl font-bold text-purple-400 mb-2">1 Phase</div>
              <div className="text-gray-400">Single Evaluation</div>
            </div>
            <div className="text-center">
              <div className="text-4xl font-bold text-cyan-400 mb-2">90%</div>
              <div className="text-gray-400">Profit Split</div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 bg-slate-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-4xl md:text-5xl font-bold text-white mb-4">
              Why Choose <span className="bg-gradient-to-r from-yellow-400 to-orange-500 bg-clip-text text-transparent">Lightning?</span>
            </h2>
            <p className="text-xl text-gray-400 max-w-3xl mx-auto">
              The fastest, most flexible path to becoming a funded trader
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-8">
            {features.map((feature, index) => {
              const Icon = feature.icon;
              return (
                <div
                  key={index}
                  className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:bg-white/10 transition-all duration-300 hover:transform hover:scale-105"
                >
                  <div className="p-3 bg-yellow-500/10 rounded-lg w-fit mb-4">
                    <Icon className="w-8 h-8 text-yellow-400" />
                  </div>
                  <h3 className="text-xl font-bold text-white mb-2">
                    {feature.title}
                  </h3>
                  <p className="text-gray-400">
                    {feature.description}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Benefits Section */}
      <section className="py-20 bg-gradient-to-br from-slate-900 to-purple-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <div>
              <h2 className="text-4xl md:text-5xl font-bold text-white mb-6">
                Everything You Need to <span className="bg-gradient-to-r from-yellow-400 to-orange-500 bg-clip-text text-transparent">Succeed</span>
              </h2>
              <p className="text-xl text-gray-300 mb-8">
                Lightning Challenge combines speed with flexibility, giving you the best chance to prove your trading skills and get funded fast.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {benefits.map((benefit, index) => (
                  <div key={index} className="flex items-start gap-3">
                    <CheckCircle className="w-5 h-5 text-green-400 mt-0.5 flex-shrink-0" />
                    <span className="text-gray-300">{benefit}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-white/5 backdrop-blur-lg border border-white/10 rounded-2xl p-8">
              <div className="text-center mb-6">
                <Star className="w-16 h-16 text-yellow-400 mx-auto mb-4" />
                <h3 className="text-2xl font-bold text-white mb-2">
                  Perfect For
                </h3>
              </div>
              <ul className="space-y-4 text-gray-300">
                <li className="flex items-start gap-3">
                  <ArrowRight className="w-5 h-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                  <span>Experienced traders who want to get funded quickly</span>
                </li>
                <li className="flex items-start gap-3">
                  <ArrowRight className="w-5 h-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                  <span>Traders who prefer lower profit targets</span>
                </li>
                <li className="flex items-start gap-3">
                  <ArrowRight className="w-5 h-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                  <span>Those who want maximum trading flexibility</span>
                </li>
                <li className="flex items-start gap-3">
                  <ArrowRight className="w-5 h-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                  <span>Traders who need to prove skills without time pressure</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Comparison Table */}
      <section id="comparison" className="py-20 bg-slate-900">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-4xl md:text-5xl font-bold text-white mb-4">
              Lightning vs <span className="bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">Standard</span>
            </h2>
            <p className="text-xl text-gray-400">
              See how Lightning Challenge compares to our standard programs
            </p>
          </div>

          <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-white/10">
                  <th className="px-6 py-4 text-left text-white font-semibold">Feature</th>
                  <th className="px-6 py-4 text-center text-white font-semibold">Standard Challenge</th>
                  <th className="px-6 py-4 text-center bg-yellow-500/10">
                    <div className="flex items-center justify-center gap-2">
                      <Zap className="w-5 h-5 text-yellow-400" />
                      <span className="text-yellow-400 font-bold">Lightning Challenge</span>
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {comparisonData.map((row, index) => (
                  <tr
                    key={index}
                    className={`border-b border-white/5 ${row.highlight ? 'bg-yellow-500/5' : ''}`}
                  >
                    <td className="px-6 py-4 text-gray-300 font-medium">{row.feature}</td>
                    <td className="px-6 py-4 text-center text-gray-400">{row.standard}</td>
                    <td className={`px-6 py-4 text-center ${row.highlight ? 'text-yellow-400 font-semibold' : 'text-gray-400'}`}>
                      {row.lightning}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Programs Section */}
      <section id="programs" className="py-20 bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-4xl md:text-5xl font-bold text-white mb-4">
              Choose Your <span className="bg-gradient-to-r from-yellow-400 to-orange-500 bg-clip-text text-transparent">Account Size</span>
            </h2>
            <p className="text-xl text-gray-400">
              All Lightning Challenge accounts come with the same great benefits
            </p>
          </div>

          {loading ? (
            <div className="text-center text-white">Loading programs...</div>
          ) : programs.length > 0 ? (
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
              {programs.map((program) => (
                <div
                  key={program.id}
                  className="bg-white/5 backdrop-blur-lg border border-yellow-500/30 rounded-2xl p-8 hover:bg-white/10 transition-all duration-300 hover:transform hover:scale-105"
                >
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-2xl font-bold text-white">{program.name}</h3>
                    <Zap className="w-8 h-8 text-yellow-400" />
                  </div>

                  <div className="mb-6">
                    <div className="text-4xl font-bold text-yellow-400 mb-2">
                      ${program.account_size?.toLocaleString()}
                    </div>
                    <div className="text-gray-400">Account Size</div>
                  </div>

                  <div className="space-y-3 mb-6">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-400">Profit Target</span>
                      <span className="text-white font-semibold">{program.profit_target}%</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-400">Max Daily Loss</span>
                      <span className="text-white font-semibold">{program.max_daily_loss}%</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-400">Max Total Loss</span>
                      <span className="text-white font-semibold">{program.max_total_loss}%</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-400">Profit Split</span>
                      <span className="text-white font-semibold">{program.profit_split}%</span>
                    </div>
                  </div>

                  <div className="border-t border-white/10 pt-6 mb-6">
                    <div className="text-3xl font-bold text-white mb-2">
                      ${program.price}
                    </div>
                    <div className="text-gray-400 text-sm">One-time fee</div>
                  </div>

                  <button
                    onClick={() => handleGetStarted(program.id)}
                    className="w-full px-6 py-4 bg-gradient-to-r from-yellow-500 to-orange-600 rounded-lg text-white font-bold hover:from-yellow-600 hover:to-orange-700 transition transform hover:scale-105 flex items-center justify-center gap-2"
                  >
                    <Zap className="w-5 h-5" />
                    Get Started
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center">
              <p className="text-gray-400 mb-6">Lightning Challenge programs coming soon!</p>
              <Link
                to="/programs"
                className="inline-block px-8 py-4 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg text-white font-bold hover:from-blue-600 hover:to-purple-700 transition"
              >
                View All Programs
              </Link>
            </div>
          )}
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 bg-gradient-to-r from-yellow-600 to-orange-600">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <Zap className="w-20 h-20 text-white mx-auto mb-6" />
          <h2 className="text-4xl md:text-5xl font-bold text-white mb-6">
            Ready to Get Funded Fast?
          </h2>
          <p className="text-xl text-yellow-100 mb-8">
            Join hundreds of traders who chose Lightning Challenge for the fastest path to funding.
          </p>
          <a
            href="#programs"
            className="inline-block px-8 py-4 bg-white text-orange-600 rounded-lg font-bold text-lg hover:bg-gray-100 transition transform hover:scale-105"
          >
            Start Your Lightning Challenge
          </a>
        </div>
      </section>
    </Layout>
  );
}

