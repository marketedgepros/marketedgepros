import React, { useState, useEffect, useRef } from 'react';
import SchemaMarkup from "../components/seo/SchemaMarkup";
import { Link } from 'react-router-dom';
import CatalogPreview from '../components/programs/CatalogPreview';
import Layout from '../components/layout/Layout';

const NewHomePage = () => {
  const [stats, setStats] = useState({
    countries: 0,
    capital: 0,
    traders: 0,
    profitSplit: 0
  });
  const [imagesLoaded, setImagesLoaded] = useState(false);

  const heroRef = useRef(null);
  const statsRef = useRef(null);

  // Preload images
  useEffect(() => {
    const images = [
      '/images/abstract-trading-flow.webp',
      '/images/hero-trading-3d.webp',
      '/images/stats-globe-hologram.webp'
    ];
    
    let loadedCount = 0;
    images.forEach(src => {
      const img = new Image();
      img.onload = () => {
        loadedCount++;
        if (loadedCount === images.length) {
          setImagesLoaded(true);
        }
      };
      img.src = src;
    });
  }, []);

  // Animated counter
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            animateStats();
          }
        });
      },
      { threshold: 0.5 }
    );

    if (statsRef.current) {
      observer.observe(statsRef.current);
    }

    return () => observer.disconnect();
  }, []);

  const animateStats = () => {
    const duration = 2000;
    const steps = 60;
    const stepDuration = duration / steps;

    const targets = {
      countries: 200,
      capital: 10,
      traders: 5000,
      profitSplit: 90
    };

    let currentStep = 0;

    const interval = setInterval(() => {
      currentStep++;
      const progress = currentStep / steps;

      setStats({
        countries: Math.floor(targets.countries * progress),
        capital: Math.floor(targets.capital * progress),
        traders: Math.floor(targets.traders * progress),
        profitSplit: Math.floor(targets.profitSplit * progress)
      });

      if (currentStep >= steps) {
        clearInterval(interval);
        setStats(targets);
      }
    }, stepDuration);
  };

  return (
    <Layout>
      <div className="min-h-screen overflow-hidden scroll-smooth">
      <SchemaMarkup />
        
        {/* Hero Section */}
        <section ref={heroRef} className="relative min-h-screen flex items-center justify-center overflow-hidden">
          {/* Animated Background */}
          <div className="absolute inset-0 z-0">
            <img 
              src="/images/abstract-trading-flow.webp" 
              alt="" 
              loading="eager"
              className="w-full h-full object-cover opacity-30"
            />
            <div className="absolute inset-0 bg-gradient-to-b from-black/50 via-transparent to-black"></div>
          </div>

          {/* 3D Trading Screens - Floating */}
          <div className="absolute inset-0 z-10 pointer-events-none">
            <img 
              src="/images/hero-trading-3d.webp" 
              alt="" 
              loading="eager"
              className="absolute top-1/4 left-1/4 w-96 h-auto opacity-60 animate-float"
            />
          </div>

          {/* Content */}
          <div className="relative z-20 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            
            {/* Main Heading */}
            <h1 className="text-6xl md:text-8xl font-bold mb-8 leading-tight">
              Where <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-teal-400 to-cyan-400 animate-gradient-shift">Talent</span>
              <br />
              Meets <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 via-pink-400 to-purple-400 animate-gradient-shift">Capital</span>
            </h1>

            {/* Subheading */}
            <p className="text-xl md:text-2xl text-gray-300 mb-12 max-w-3xl mx-auto">
              Trade with up to <span className="text-cyan-400 font-bold">$400,000</span> in capital.
              Keep up to <span className="text-purple-400 font-bold">90%</span> of your profits.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-6">
              <Link
                to="/programs"
                className="group relative px-12 py-5 bg-gradient-to-r from-cyan-500 to-teal-500 rounded-full text-lg font-bold transition-all duration-300 hover:scale-110 hover:shadow-2xl hover:shadow-cyan-500/50"
              >
                <span className="relative z-10">Get Funded Now</span>
                <div className="absolute inset-0 rounded-full bg-gradient-to-r from-cyan-600 to-teal-600 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
              </Link>
              
              <Link
                to="/free-course"
                className="px-12 py-5 border-2 border-white/20 rounded-full text-lg font-semibold backdrop-blur-sm hover:bg-white/10 transition-all duration-300"
              >
                Start Free Course
              </Link>
            </div>

            {/* Trust Indicators */}
            <div className="mt-16 flex flex-wrap items-center justify-center gap-8 text-sm text-gray-400">
              <div className="flex items-center gap-2">
                <span className="text-2xl">✓</span>
                <span>Instant Payouts</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-2xl">✓</span>
                <span>No Time Limits</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-2xl">✓</span>
                <span>Trade Your Way</span>
              </div>
            </div>
          </div>
        </section>

        {/* Stats Section */}
        <section ref={statsRef} className="relative py-32 overflow-hidden">
          {/* Background */}
          <div className="absolute inset-0 z-0">
            <img 
              src="/images/stats-globe-hologram.webp" 
              alt="" 
              className="w-full h-full object-cover opacity-20"
            />
            <div className="absolute inset-0 bg-gradient-to-b from-black via-transparent to-black"></div>
          </div>

          {/* Content */}
          <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
              {/* Stat 1 */}
              <div className="text-center">
                <div className="text-5xl md:text-6xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400 mb-2">
                  {stats.countries}+
                </div>
                <div className="text-gray-400 text-lg">Countries</div>
              </div>

              {/* Stat 2 */}
              <div className="text-center">
                <div className="text-5xl md:text-6xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400 mb-2">
                  ${stats.capital}M+
                </div>
                <div className="text-gray-400 text-lg">Capital Funded</div>
              </div>

              {/* Stat 3 */}
              <div className="text-center">
                <div className="text-5xl md:text-6xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-red-400 mb-2">
                  {stats.traders}+
                </div>
                <div className="text-gray-400 text-lg">Active Traders</div>
              </div>

              {/* Stat 4 */}
              <div className="text-center">
                <div className="text-5xl md:text-6xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-indigo-400 mb-2">
                  {stats.profitSplit}%
                </div>
                <div className="text-gray-400 text-lg">Profit Split</div>
              </div>
            </div>
          </div>
        </section>

        {/* How It Works Section */}
        <section id="how-it-works" className="relative py-32">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-20">
              <h2 className="text-5xl md:text-6xl font-bold mb-6">
                How It <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">Works</span>
              </h2>
              <p className="text-xl text-gray-400 max-w-3xl mx-auto">
                Get funded in 3 simple steps and start trading with our capital
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
              {/* Step 1 */}
              <div className="relative group">
                <div className="absolute inset-0 bg-gradient-to-r from-cyan-500/20 to-teal-500/20 rounded-3xl blur-xl group-hover:blur-2xl transition-all duration-300"></div>
                <div className="relative bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-8 transition-all duration-300 hover:scale-105">
                  <div className="text-6xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400 mb-6">01</div>
                  <h3 className="text-2xl font-bold mb-4">Choose Your Challenge</h3>
                  <p className="text-gray-400">
                    Select from our range of funding programs. From $10K to $400K accounts.
                  </p>
                </div>
              </div>

              {/* Step 2 */}
              <div className="relative group">
                <div className="absolute inset-0 bg-gradient-to-r from-purple-500/20 to-pink-500/20 rounded-3xl blur-xl group-hover:blur-2xl transition-all duration-300"></div>
                <div className="relative bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-8 transition-all duration-300 hover:scale-105">
                  <div className="text-6xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400 mb-6">02</div>
                  <h3 className="text-2xl font-bold mb-4">Pass The Evaluation</h3>
                  <p className="text-gray-400">
                    Trade and hit the profit targets while following our simple rules.
                  </p>
                </div>
              </div>

              {/* Step 3 */}
              <div className="relative group">
                <div className="absolute inset-0 bg-gradient-to-r from-orange-500/20 to-red-500/20 rounded-3xl blur-xl group-hover:blur-2xl transition-all duration-300"></div>
                <div className="relative bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-8 transition-all duration-300 hover:scale-105">
                  <div className="text-6xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-red-400 mb-6">03</div>
                  <h3 className="text-2xl font-bold mb-4">Get Funded & Trade</h3>
                  <p className="text-gray-400">
                    Receive your funded account and keep up to 90% of your profits.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Programs Section */}
        <section id="programs" className="relative py-32 bg-gradient-to-b from-transparent via-white/5 to-transparent">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-16">
              <h2 className="text-5xl md:text-6xl font-bold mb-6">
                Choose Your <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">Challenge</span>
              </h2>
            </div>

            <CatalogPreview />
          </div>
        </section>

        {/* Features Section */}
        <section id="features" className="relative py-32">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-20">
              <h2 className="text-5xl md:text-6xl font-bold mb-6">
                Why Choose <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">Us</span>
              </h2>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
              {/* Feature 1 */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">⚡</div>
                <h3 className="text-2xl font-bold mb-4">Instant Payouts</h3>
                <p className="text-gray-400">
                  Request payouts anytime. Get paid within 24 hours.
                </p>
              </div>

              {/* Feature 2 */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">🎯</div>
                <h3 className="text-2xl font-bold mb-4">No Time Limits</h3>
                <p className="text-gray-400">
                  Trade at your own pace. No pressure, no deadlines.
                </p>
              </div>

              {/* Feature 3 */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">📈</div>
                <h3 className="text-2xl font-bold mb-4">Scale Your Account</h3>
                <p className="text-gray-400">
                  Grow your account up to $400K based on performance.
                </p>
              </div>

              {/* Feature 4 */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">🛡️</div>
                <h3 className="text-2xl font-bold mb-4">Simple Rules</h3>
                <p className="text-gray-400">
                  Clear, straightforward rules. No hidden conditions.
                </p>
              </div>

              {/* Feature 5 */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">💰</div>
                <h3 className="text-2xl font-bold mb-4">Up to 90% Profit Split</h3>
                <p className="text-gray-400">
                  Keep the majority of your profits. You deserve it.
                </p>
              </div>

              {/* Feature 6 */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">🌍</div>
                <h3 className="text-2xl font-bold mb-4">Global Community</h3>
                <p className="text-gray-400">
                  Join traders from 200+ countries worldwide.
                </p>
              </div>

              {/* Feature 7 - MT4/MT5 */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">💻</div>
                <h3 className="text-2xl font-bold mb-4">MT4 & MT5 Platforms</h3>
                <p className="text-gray-400">
                  Trade on industry-standard MetaTrader 4 & 5 platforms. TradingView coming soon.
                </p>
              </div>

              {/* Feature 8 - Payout Policy */}
              <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
                <div className="text-4xl mb-4">💵</div>
                <h3 className="text-2xl font-bold mb-4">Low Minimum Withdrawal</h3>
                <p className="text-gray-400">
                  Withdraw your profits starting from just $50. Flexible payout frequency options.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Testimonials Section */}
        <section className="relative py-32">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-20">
              <h2 className="text-5xl md:text-6xl font-bold mb-6">
                What Our <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">Traders Say</span>
              </h2>
              <p className="text-xl text-gray-300">Join thousands of successful funded traders</p>
            </div>

            <div className="grid md:grid-cols-3 gap-8">
              {[
                {
                  name: "Alex Thompson",
                  role: "Funded Trader",
                  image: "AT",
                  text: "MarketEdgePros changed my trading career. Fast payouts, fair rules, and excellent support. I scaled from $25K to $100K in 4 months!"
                },
                {
                  name: "Maria Garcia",
                  role: "Professional Trader",
                  image: "MG",
                  text: "Best prop firm I've worked with. No time pressure, realistic targets, and they actually care about trader success. Highly recommended!"
                },
                {
                  name: "James Wilson",
                  role: "Full-Time Trader",
                  image: "JW",
                  text: "The instant funding option was perfect for me. Started trading with real capital immediately and now making consistent profits with 90% split."
                }
              ].map((testimonial, index) => (
                <div key={index} className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8 hover:border-cyan-500/50 transition-all">
                  <div className="flex items-center gap-4 mb-6">
                    <div className="w-16 h-16 bg-gradient-to-r from-cyan-500 to-teal-500 rounded-full flex items-center justify-center text-white text-xl font-bold">
                      {testimonial.image}
                    </div>
                    <div>
                      <h4 className="text-white font-bold text-lg">{testimonial.name}</h4>
                      <p className="text-gray-400 text-sm">{testimonial.role}</p>
                    </div>
                  </div>
                  <div className="flex gap-1 mb-4">
                    {[...Array(5)].map((_, i) => (
                      <svg key={i} className="w-5 h-5 fill-cyan-400" viewBox="0 0 20 20">
                        <path d="M10 15l-5.878 3.09 1.123-6.545L.489 6.91l6.572-.955L10 0l2.939 5.955 6.572.955-4.756 4.635 1.123 6.545z" />
                      </svg>
                    ))}
                  </div>
                  <p className="text-gray-300 italic">"{testimonial.text}"</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Trust Badges Section */}
        <section className="relative py-20">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-12">
              <h3 className="text-2xl font-bold text-gray-400 mb-8">Trusted by traders worldwide</h3>
              <div className="flex flex-wrap justify-center items-center gap-12">
                {[
                  { icon: "🏆", text: "Top Rated 2024" },
                  { icon: "✓", text: "Verified Payouts" },
                  { icon: "🔒", text: "Secure Platform" },
                  { icon: "⚡", text: "Fast Support" },
                  { icon: "🌍", text: "200+ Countries" }
                ].map((badge, index) => (
                  <div key={index} className="flex items-center gap-3 bg-white/5 border border-white/10 rounded-full px-6 py-3">
                    <span className="text-2xl">{badge.icon}</span>
                    <span className="text-white font-semibold">{badge.text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Quick FAQ Section */}
        <section className="relative py-32">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-16">
              <h2 className="text-5xl md:text-6xl font-bold mb-6">
                Quick <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400">Answers</span>
              </h2>
              <p className="text-xl text-gray-300">Common questions from new traders</p>
            </div>

            <div className="space-y-6">
              {[
                {
                  q: "How fast can I get funded?",
                  a: "With instant funding, you can start trading immediately. For evaluation programs, most traders complete them in 2-4 weeks."
                },
                {
                  q: "Are there any time limits?",
                  a: "No! Unlike other firms, we don't impose time limits on evaluations. Trade at your own pace and comfort level."
                },
                {
                  q: "How do payouts work?",
                  a: "Request payouts anytime after your first profitable trade. We process all payout requests within 24 hours on business days."
                },
                {
                  q: "Can I scale my account?",
                  a: "Absolutely! Consistent traders can scale up to $400K and increase their profit split to 90% based on performance."
                }
              ].map((faq, index) => (
                <div key={index} className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-6 hover:border-cyan-500/50 transition-all">
                  <h4 className="text-xl font-bold text-white mb-3">{faq.q}</h4>
                  <p className="text-gray-300">{faq.a}</p>
                </div>
              ))}
            </div>

            <div className="text-center mt-12">
              <Link to="/faq" className="text-cyan-400 hover:text-cyan-300 font-semibold text-lg">
                View All FAQs →
              </Link>
            </div>
          </div>
        </section>

        {/* CTA Section */}
        <section className="relative py-32">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <h2 className="text-5xl md:text-6xl font-bold mb-8">
              Ready to Start <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-400">Trading</span>?
            </h2>
            <p className="text-xl text-gray-300 mb-12">
              Join thousands of traders worldwide and get funded today
            </p>
            <Link
              to="/programs"
              className="inline-block px-16 py-6 bg-gradient-to-r from-cyan-500 via-purple-500 to-pink-500 rounded-full text-xl font-bold transition-all duration-300 hover:scale-110 hover:shadow-2xl hover:shadow-purple-500/50"
            >
              Get Funded Now
            </Link>
          </div>
        </section>

        {/* Custom Animations */}
        <style jsx>{`
          @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-20px); }
          }

          @keyframes gradient-shift {
            0%, 100% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
          }

          @keyframes pulse-slow {
            0%, 100% { opacity: 0.6; transform: scale(1); }
            50% { opacity: 1; transform: scale(1.05); }
          }

          .animate-float {
            animation: float 6s ease-in-out infinite;
          }

          .animate-gradient-shift {
            background-size: 200% 200%;
            animation: gradient-shift 3s ease infinite;
          }

          .animate-pulse-slow {
            animation: pulse-slow 4s ease-in-out infinite;
          }
        `}</style>

      </div>
    </Layout>
  );
};

export default NewHomePage;

