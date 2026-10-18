import { useCallback, useEffect, useRef, useState } from 'react';
import { Search, BookOpen, MessageCircle, FileText, Video, HelpCircle, ExternalLink, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import Layout from '../../components/layout/Layout';
import SEO from '../../components/SEO';
import api from "../../services/api";

const isRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError' || error?.__CANCEL__ === true
);

export default function SupportHub() {
  const [searchTerm, setSearchTerm] = useState('');
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const requestRef = useRef(null);
  const requestSequenceRef = useRef(0);

  const loadArticles = useCallback(async () => {
    requestRef.current?.abort();
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setLoadError(false);

    try {
      const response = await api.get('/support/articles', { signal: controller.signal });
      if (requestSequenceRef.current !== requestId || controller.signal.aborted) return;
      setArticles(Array.isArray(response.data?.articles) ? response.data.articles : []);
    } catch (error) {
      if (requestSequenceRef.current !== requestId || isRequestCanceled(error)) return;
      console.error('Error fetching articles:', error);
      setLoadError(true);
    } finally {
      if (requestSequenceRef.current === requestId) {
        setLoading(false);
        if (requestRef.current === controller) requestRef.current = null;
      }
    }
  }, []);

  useEffect(() => {
    loadArticles();
    return () => {
      requestSequenceRef.current += 1;
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, [loadArticles]);

  // Group articles by category
  const getCategorizedArticles = () => {
    const categoryMap = {
      'Getting Started': { title: 'Getting Started', icon: BookOpen, articles: [] },
      'Challenges & Evaluation': { title: 'Challenges & Evaluation', icon: FileText, articles: [] },
      'Funded Accounts': { title: 'Funded Accounts', icon: Video, articles: [] },
      'Payments & Withdrawals': { title: 'Payments & Withdrawals', icon: MessageCircle, articles: [] },
      'Platform & Technical': { title: 'Platform & Technical', icon: HelpCircle, articles: [] },
      'Account Management': { title: 'Account Management', icon: FileText, articles: [] }
    };

    articles.forEach(article => {
      if (article.status === 'published' && article.category) {
        // Normalize category name
        const category = article.category;
        if (categoryMap[category]) {
          categoryMap[category].articles.push({
            title: article.title,
            link: `/support/${article.slug}`,
          });
        }
      }
    });

    return Object.values(categoryMap).filter(cat => cat.articles.length > 0);
  };

  const categories = getCategorizedArticles();

  const quickLinks = [
    { title: 'Create Support Ticket', icon: MessageCircle, link: '/support/create-ticket' },
    { title: 'Browse FAQ', icon: HelpCircle, link: '/faq' }
  ];
  const normalizedSearchTerm = searchTerm.trim();
  const hasSearchTerm = normalizedSearchTerm.length > 0;

  // Filter articles based on search term
  const getFilteredArticles = () => {
    if (!hasSearchTerm) return categories;
    
    const term = normalizedSearchTerm.toLowerCase();
    return categories.map(category => ({
      ...category,
      articles: category.articles.filter(article => 
        article.title.toLowerCase().includes(term)
      )
    })).filter(category => category.articles.length > 0);
  };

  const filteredCategories = getFilteredArticles();

  return (
    <Layout>
      <SEO 
        title="Support Hub - Help Center & Knowledge Base"
        description="Find answers to common questions, browse our knowledge base, and get help from our support team."
      />

      {/* Hero Section */}
      <section className="relative py-20 bg-black">
        <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/10 via-transparent to-teal-500/10"></div>
        <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="mep-heading text-4xl md:text-5xl lg:text-6xl font-bold text-white mb-6">
            How Can We <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">Help You?</span>
          </h1>
          <p className="text-xl text-gray-400 mb-8">
            Search our knowledge base for guides, tutorials, and answers to common questions
          </p>
          <div className="relative max-w-2xl mx-auto">
            <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
            <input
              type="text"
              placeholder="Search for help articles..."
              aria-label="Search help articles"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-12 pr-4 py-4 bg-white/5 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-400"
            />
          </div>
        </div>
      </section>

      {/* Quick Links */}
      <section className="py-12 bg-black border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {quickLinks.map((link, index) => {
              const Icon = link.icon;
              if (link.external) {
                return (
                  <a
                    key={index}
                    href={link.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-3 p-4 bg-white/5 border border-white/10 rounded-lg hover:bg-gradient-to-r hover:from-cyan-500/20 hover:to-teal-500/20 hover:border-cyan-500/50 transition-all group"
                  >
                    <Icon className="w-5 h-5 text-cyan-400" />
                    <span className="font-semibold text-white group-hover:text-cyan-300">{link.title}</span>
                  </a>
                );
              }
              return (
                <Link
                  key={index}
                  to={link.link}
                  className="flex items-center gap-3 p-4 bg-white/5 border border-white/10 rounded-lg hover:bg-gradient-to-r hover:from-cyan-500/20 hover:to-teal-500/20 hover:border-cyan-500/50 transition-all group"
                >
                  <Icon className="w-5 h-5 text-cyan-400" />
                  <span className="font-semibold text-white group-hover:text-cyan-300">{link.title}</span>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* Categories */}
      <section className="py-20 bg-black">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2 className="mep-heading text-3xl md:text-4xl font-bold text-white mb-12 text-center">
            Browse by Category
          </h2>
          
          {loading ? (
            <div className="text-center py-12">
              <p className="text-gray-400 text-lg">Loading articles...</p>
            </div>
          ) : loadError ? (
            <div className="mep-panel rounded-xl border px-6 py-12 text-center" role="alert">
              <p className="text-gray-300 text-lg">Articles could not be loaded. Please try again later.</p>
              <button
                type="button"
                onClick={loadArticles}
                disabled={loading}
                className="mt-5 rounded-lg border border-cyan-500/50 px-5 py-3 font-semibold text-cyan-200 transition-colors hover:bg-cyan-500/10 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Try again
              </button>
            </div>
          ) : (
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
              {filteredCategories.length > 0 ? filteredCategories.map((category, index) => {
                const Icon = category.icon;
                return (
                  <div
                    key={index}
                    className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:bg-white/10 hover:border-cyan-500/30 transition-all group"
                  >
                    <div className="flex items-center gap-3 mb-4">
                      <div className="p-3 rounded-lg bg-gradient-to-r from-cyan-500/20 to-teal-500/20 border border-cyan-500/30 group-hover:from-cyan-500/30 group-hover:to-teal-500/30 transition-all">
                        <Icon className="w-6 h-6 text-cyan-400" />
                      </div>
                      <h3 className="text-xl font-bold text-white">{category.title}</h3>
                    </div>
                    <ul className="space-y-2">
                      {category.articles.map((article, articleIndex) => (
                        <li key={articleIndex}>
                          <Link
                            to={article.link}
                            className="flex items-center justify-between text-gray-400 hover:text-cyan-300 transition-colors group/item"
                          >
                            <span className="text-sm">{article.title}</span>
                            <ChevronRight className="w-4 h-4 opacity-0 group-hover/item:opacity-100 transition-opacity text-cyan-400" />
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              }) : (
                <div className="col-span-full text-center py-12">
                  <p className="text-gray-400 text-lg" role="status" aria-live="polite">
                    {hasSearchTerm
                      ? <>No articles match “{normalizedSearchTerm}”. Try another search.</>
                      : <>No support articles are available right now. Please check back later.</>}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* Contact Support CTA */}
      <section className="py-20 bg-black border-t border-white/10">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="mep-heading text-3xl md:text-4xl font-bold text-white mb-6">
            Still Need Help?
          </h2>
          <p className="text-xl text-gray-400 mb-8">
            Can't find what you're looking for? You can submit a support ticket.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              to="/support/create-ticket"
              className="mep-primary inline-flex items-center justify-center px-8 py-4 font-semibold transition-all"
            >
              <MessageCircle className="w-5 h-5 mr-2" />
              Contact Support
            </Link>
          </div>
        </div>
      </section>
    </Layout>
  );
}
