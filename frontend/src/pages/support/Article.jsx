import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import Layout from '../../components/layout/Layout';
import ReactMarkdown from 'react-markdown';
import DOMPurify from 'isomorphic-dompurify';
import api from "../../services/api";

const Article = () => {
  const { slug } = useParams();
  const [article, setArticle] = useState(null);
  const [content, setContent] = useState('');
  const [relatedArticles, setRelatedArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchArticle = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // Fetch article from API
        const response = await api.get(`/support/articles/${slug}`);
        const data = response.data;
        
        setArticle(data);
        setContent(data.content || '');
        
        // Fetch related articles
        try {
          const relatedResponse = await api.get('/support/articles', {
            params: { category: data.category, limit: 3 }
          });
          const filtered = relatedResponse.data.articles.filter(a => a.slug !== slug).slice(0, 3);
          setRelatedArticles(filtered);
        } catch (err) {
          console.error('Failed to load related articles:', err);
        }
        
      } catch (err) {
        console.error('Failed to load article:', err);
        setError(err.message);
        setArticle(null);
      } finally {
        setLoading(false);
      }
    };

    fetchArticle();
  }, [slug]);

  // Detect if content is HTML
  const isHTML = (text) => {
    if (!text) return false;
    const trimmed = text.trim();
    return /<\/?[a-z][\s\S]*>/i.test(trimmed);
  };

  // Style HTML content to match Markdown styling
  const styleHTMLContent = (htmlContent) => {
    const sanitized = DOMPurify.sanitize(htmlContent);
    
    // Create a temporary div to manipulate the HTML
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = sanitized;
    
    // Apply Tailwind classes to HTML elements to match Markdown styling
    tempDiv.querySelectorAll('h1').forEach(el => {
      el.className = 'text-3xl font-bold text-white mb-4 mt-8';
    });
    
    tempDiv.querySelectorAll('h2').forEach(el => {
      el.className = 'text-2xl font-bold text-white mb-3 mt-6';
    });
    
    tempDiv.querySelectorAll('h3').forEach(el => {
      el.className = 'text-xl font-bold text-cyan-400 mb-2 mt-4';
    });
    
    tempDiv.querySelectorAll('p').forEach(el => {
      el.className = 'text-gray-300 mb-4 leading-relaxed';
    });
    
    tempDiv.querySelectorAll('a').forEach(el => {
      el.className = 'text-cyan-400 hover:text-cyan-300 underline';
    });
    
    tempDiv.querySelectorAll('ul').forEach(el => {
      el.className = 'list-disc list-inside text-gray-300 mb-4 space-y-2';
    });
    
    tempDiv.querySelectorAll('ol').forEach(el => {
      el.className = 'list-decimal list-inside text-gray-300 mb-4 space-y-2';
    });
    
    tempDiv.querySelectorAll('li').forEach(el => {
      el.className = 'text-gray-300';
    });
    
    tempDiv.querySelectorAll('strong, b').forEach(el => {
      el.className = 'font-bold text-white';
    });
    
    tempDiv.querySelectorAll('em, i').forEach(el => {
      el.className = 'italic';
    });
    
    tempDiv.querySelectorAll('blockquote').forEach(el => {
      el.className = 'border-l-4 border-cyan-400 pl-4 italic text-gray-400 my-4';
    });
    
    tempDiv.querySelectorAll('code').forEach(el => {
      el.className = 'bg-gray-800 px-2 py-1 rounded text-cyan-400 font-mono text-sm';
    });
    
    tempDiv.querySelectorAll('pre').forEach(el => {
      el.className = 'bg-gray-800 p-4 rounded-lg overflow-x-auto mb-4';
    });
    
    return tempDiv.innerHTML;
  };

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen bg-gradient-to-br from-black via-gray-900 to-black flex items-center justify-center">
          <div className="text-white text-xl" role="status" aria-live="polite">Loading...</div>
        </div>
      </Layout>
    );
  }

  if (error || !article) {
    return (
      <Layout>
        <div className="min-h-screen bg-gradient-to-br from-black via-gray-900 to-black flex items-center justify-center">
          <div className="text-center" role="alert">
            <h1 className="text-4xl font-bold text-white mb-4">Unable to Load Article</h1>
            <p className="text-gray-400 mb-8">We couldn't load this article. Please try again or browse the Support Hub.</p>
            <Link 
              to="/support" 
              className="bg-cyan-500 hover:bg-cyan-600 text-white px-6 py-3 rounded-lg transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
            >
              Back to Support Hub
            </Link>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <Helmet>
        <title>{article.title} - MarketEdgePros Support</title>
        <meta name="description" content={article.excerpt || article.title} />
      </Helmet>

      <div className="min-h-screen bg-gradient-to-br from-black via-gray-900 to-black py-20">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Back Link */}
          <Link 
            to="/support" 
            className="inline-flex items-center text-cyan-400 hover:text-cyan-300 mb-8 transition-colors"
          >
            <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Back to Support Hub
          </Link>

          {/* Article Header */}
          <div className="mb-8">
            {article.category && (
              <div className="flex items-center gap-2 mb-4">
                <span className="text-cyan-400 text-sm font-medium">{article.category}</span>
                {article.subcategory && (
                  <>
                    <span className="text-gray-600">•</span>
                    <span className="text-gray-400 text-sm">{article.subcategory}</span>
                  </>
                )}
              </div>
            )}
            <h1 className="text-4xl font-bold text-white mb-4">{article.title}</h1>
            {article.excerpt && (
              <p className="text-xl text-gray-400">{article.excerpt}</p>
            )}
          </div>

          {/* Article Content */}
          <div className="bg-gray-800/50 backdrop-blur-sm rounded-2xl p-8 mb-12">
            {isHTML(content) ? (
              <div 
                className="prose prose-invert max-w-none"
                dangerouslySetInnerHTML={{ __html: styleHTMLContent(content) }}
              />
            ) : (
              <ReactMarkdown
                className="prose prose-invert max-w-none"
                components={{
                  h1: ({ node, ...props }) => <h1 className="text-3xl font-bold text-white mb-4 mt-8" {...props} />,
                  h2: ({ node, ...props }) => <h2 className="text-2xl font-bold text-white mb-3 mt-6" {...props} />,
                  h3: ({ node, ...props }) => <h3 className="text-xl font-bold text-cyan-400 mb-2 mt-4" {...props} />,
                  p: ({ node, ...props }) => <p className="text-gray-300 mb-4 leading-relaxed" {...props} />,
                  a: ({ node, ...props }) => <a className="text-cyan-400 hover:text-cyan-300 underline" {...props} />,
                  ul: ({ node, ...props }) => <ul className="list-disc list-inside text-gray-300 mb-4 space-y-2" {...props} />,
                  ol: ({ node, ...props }) => <ol className="list-decimal list-inside text-gray-300 mb-4 space-y-2" {...props} />,
                  li: ({ node, ...props }) => <li className="text-gray-300" {...props} />,
                  strong: ({ node, ...props }) => <strong className="font-bold text-white" {...props} />,
                  em: ({ node, ...props }) => <em className="italic" {...props} />,
                  blockquote: ({ node, ...props }) => <blockquote className="border-l-4 border-cyan-400 pl-4 italic text-gray-400 my-4" {...props} />,
                  code: ({ node, inline, ...props }) => 
                    inline 
                      ? <code className="bg-gray-800 px-2 py-1 rounded text-cyan-400 font-mono text-sm" {...props} />
                      : <code className="block bg-gray-800 p-4 rounded-lg overflow-x-auto mb-4 text-cyan-400 font-mono text-sm" {...props} />,
                }}
              >
                {content}
              </ReactMarkdown>
            )}
          </div>

          {/* Related Articles */}
          {relatedArticles.length > 0 && (
            <div className="mb-12">
              <h2 className="text-2xl font-bold text-white mb-6">Related Articles</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {relatedArticles.map((related) => (
                  <Link
                    key={related.slug}
                    to={`/support/${related.slug}`}
                    className="bg-gray-800/50 backdrop-blur-sm rounded-xl p-6 hover:bg-gray-800/70 transition-all group"
                  >
                    <h3 className="text-lg font-semibold text-white mb-2 group-hover:text-cyan-400 transition-colors">
                      {related.title}
                    </h3>
                    <p className="text-gray-400 text-sm mb-4 line-clamp-2">{related.excerpt}</p>
                    <span className="text-cyan-400 text-sm font-medium inline-flex items-center">
                      Read more
                      <svg className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Support CTA */}
          <div className="bg-gradient-to-r from-cyan-500/10 to-blue-500/10 rounded-2xl p-8 text-center">
            <h2 className="text-2xl font-bold text-white mb-4">Still Need Help?</h2>
            <p className="text-gray-400 mb-6">
              Can't find what you're looking for? Contact us and we'll do our best to help.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a
                href="mailto:info@marketedgepros.com"
                className="bg-cyan-500 hover:bg-cyan-600 text-white px-8 py-3 rounded-lg transition-colors font-medium"
              >
                Contact Support
              </a>
              <Link
                to="/support"
                className="bg-gray-700 hover:bg-gray-600 text-white px-8 py-3 rounded-lg transition-colors font-medium"
              >
                Browse Support Articles
              </Link>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default Article;
