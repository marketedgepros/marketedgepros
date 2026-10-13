import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import Layout from '../../components/layout/Layout';
import ReactMarkdown from 'react-markdown';
import DOMPurify from 'isomorphic-dompurify';
import api from "../../services/api";

const isRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError' || error?.__CANCEL__ === true
);

const Article = () => {
  const { slug } = useParams();
  const [article, setArticle] = useState(null);
  const [articleSlug, setArticleSlug] = useState(null);
  const [content, setContent] = useState('');
  const [relatedArticles, setRelatedArticles] = useState([]);
  const [relatedArticlesSlug, setRelatedArticlesSlug] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const requestRef = useRef(null);
  const requestSequenceRef = useRef(0);

  const loadArticle = useCallback(async () => {
    requestRef.current?.abort();
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    const controller = new AbortController();
    requestRef.current = controller;
    const isCurrentRequest = () => requestSequenceRef.current === requestId && !controller.signal.aborted;

    setLoading(true);
    setError(null);
    setArticle(null);
    setArticleSlug(null);
    setContent('');
    setRelatedArticles([]);
    setRelatedArticlesSlug(null);

    try {
      const response = await api.get(`/support/articles/${encodeURIComponent(slug || '')}`, { signal: controller.signal });
      if (!isCurrentRequest()) return;
      const data = response.data;
      if (!data || typeof data !== 'object') throw new Error('Article not found');

      setArticle(data);
      setArticleSlug(slug);
      setContent(typeof data.content === 'string' ? data.content : '');

      try {
        const relatedResponse = await api.get('/support/articles', {
          params: { category: data.category, limit: 3 },
          signal: controller.signal,
        });
        if (!isCurrentRequest()) return;
        const candidates = Array.isArray(relatedResponse.data?.articles) ? relatedResponse.data.articles : [];
        setRelatedArticles(candidates.filter((candidate) => candidate.slug !== slug).slice(0, 3));
        setRelatedArticlesSlug(slug);
      } catch (relatedError) {
        if (!isCurrentRequest() || isRequestCanceled(relatedError)) return;
        console.error('Failed to load related articles:', relatedError);
      }
    } catch (requestError) {
      if (!isCurrentRequest() || isRequestCanceled(requestError)) return;
      console.error('Failed to load article:', requestError);
      setError({ slug, message: requestError.message });
    } finally {
      if (requestSequenceRef.current === requestId) {
        setLoading(false);
        if (requestRef.current === controller) requestRef.current = null;
      }
    }
  }, [retryVersion, slug]);

  useEffect(() => {
    loadArticle();
    return () => {
      requestSequenceRef.current += 1;
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, [loadArticle]);

  const currentError = error?.slug === slug ? error.message : null;
  const hasCurrentArticle = articleSlug === slug && article !== null;
  const currentRelatedArticles = relatedArticlesSlug === slug ? relatedArticles : [];
  const retryLoad = () => setRetryVersion((version) => version + 1);

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

  if (loading || (!hasCurrentArticle && !currentError)) {
    return (
      <Layout>
        <div className="mep-screen min-h-screen from-black via-gray-900 to-black flex items-center justify-center">
          <div className="text-white text-xl" role="status" aria-live="polite">Loading...</div>
        </div>
      </Layout>
    );
  }

  if (currentError || !hasCurrentArticle) {
    return (
      <Layout>
        <div className="mep-screen min-h-screen from-black via-gray-900 to-black flex items-center justify-center">
          <div className="text-center" role="alert">
            <h1 className="mep-heading text-4xl font-bold text-white mb-4">Unable to Load Article</h1>
            <p className="text-gray-400 mb-8">We couldn't load this article. Please try again or browse the Support Hub.</p>
            <button
              type="button"
              onClick={retryLoad}
              className="mep-primary mr-3 px-6 py-3 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
            >
              Try again
            </button>
            <Link 
              to="/support" 
              className="mep-primary px-6 py-3 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
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

      <div className="mep-screen min-h-screen from-black via-gray-900 to-black py-20">
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
            <h1 className="mep-heading text-4xl font-bold text-white mb-4">{article.title}</h1>
            {article.excerpt && (
              <p className="text-xl text-gray-400">{article.excerpt}</p>
            )}
          </div>

          {/* Article Content */}
          <div className="bg-gray-800/50 backdrop-blur-sm rounded-2xl p-8 mb-12">
            {!content.trim() ? (
              <section role="status" aria-live="polite" className="rounded-xl border border-slate-700 bg-slate-900/50 p-5 text-gray-300">
                This article does not have any content yet.
              </section>
            ) : isHTML(content) ? (
              <div 
                className="prose prose-invert max-w-none"
                dangerouslySetInnerHTML={{ __html: styleHTMLContent(content) }}
              />
            ) : (
              <ReactMarkdown
                className="prose prose-invert max-w-none"
                components={{
                  h1: ({ node, ...props }) => <h1 className="mep-heading text-3xl font-bold text-white mb-4 mt-8" {...props} />,
                  h2: ({ node, ...props }) => <h2 className="mep-heading text-2xl font-bold text-white mb-3 mt-6" {...props} />,
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
          {currentRelatedArticles.length > 0 && (
            <div className="mb-12">
              <h2 className="mep-heading text-2xl font-bold text-white mb-6">Related Articles</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {currentRelatedArticles.map((related) => (
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
            <h2 className="mep-heading text-2xl font-bold text-white mb-4">Still Need Help?</h2>
            <p className="text-gray-400 mb-6">
              Can't find what you're looking for? Contact us and we'll do our best to help.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a
                href="mailto:info@marketedgepros.com"
                className="mep-primary px-8 py-3 transition-colors font-medium"
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
