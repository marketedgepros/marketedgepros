import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Calendar, Clock, ArrowLeft, Share2, Facebook, Twitter, Linkedin, Tag, User } from 'lucide-react';
import Layout from '../components/layout/Layout';
import SEO from '../components/SEO';
import api from "../services/api";
import DOMPurify from 'isomorphic-dompurify';



export default function BlogPost() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [post, setPost] = useState(null);
  const [relatedPosts, setRelatedPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [contentSlug, setContentSlug] = useState(null);
  const [error, setError] = useState('');
  const [readingProgress, setReadingProgress] = useState(0);
  const [shareError, setShareError] = useState('');
  const postRequestRef = useRef({ controller: null, version: 0 });

  useEffect(() => {
    const handleScroll = () => {
      const windowHeight = window.innerHeight;
      const documentHeight = document.documentElement.scrollHeight;
      const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
      const scrollableHeight = documentHeight - windowHeight;
      const progress = scrollableHeight > 0
        ? (scrollTop / scrollableHeight) * 100
        : 0;
      setReadingProgress(Math.min(Math.max(progress, 0), 100));
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const fetchRelatedPosts = async (category, currentPostId, controller, version) => {
    const isCurrentRequest = () => (
      postRequestRef.current.version === version
      && postRequestRef.current.controller === controller
    );

    try {
      const response = await api.get('/blog/posts', {
        params: { category, per_page: 3 },
        signal: controller.signal,
      });
      if (!isCurrentRequest()) return;

      const related = Array.isArray(response.data?.posts)
        ? response.data.posts.filter((item) => item.id !== currentPostId).slice(0, 3)
        : [];
      setRelatedPosts(related);
    } catch (err) {
      if (controller.signal.aborted || !isCurrentRequest()) return;
      console.error('Error fetching related posts:', err);
      setRelatedPosts([]);
    }
  };

  const fetchPost = async (requestedSlug = slug) => {
    const previousRequest = postRequestRef.current;
    previousRequest.controller?.abort();

    const controller = new AbortController();
    const version = previousRequest.version + 1;
    postRequestRef.current = { controller, version };
    const isCurrentRequest = () => (
      postRequestRef.current.version === version
      && postRequestRef.current.controller === controller
    );

    try {
      setContentSlug(requestedSlug);
      setLoading(true);
      setError('');
      setPost(null);
      setRelatedPosts([]);
      setShareError('');
      const response = await api.get(`/blog/posts/${requestedSlug}`, { signal: controller.signal });
      if (!isCurrentRequest()) return;

      const nextPost = response.data;
      setPost(nextPost);

      if (nextPost?.category) {
        void fetchRelatedPosts(nextPost.category, nextPost.id, controller, version);
      }
    } catch (err) {
      if (controller.signal.aborted || !isCurrentRequest()) return;
      console.error('Error fetching post:', err);
      if (err.response?.status === 404) {
        setError('Blog post not found');
      } else {
        setError('Failed to load blog post');
      }
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  };

  useEffect(() => {
    fetchPost(slug);
    window.scrollTo(0, 0);

    return () => {
      const activeRequest = postRequestRef.current;
      activeRequest.version += 1;
      activeRequest.controller?.abort();
      postRequestRef.current = { controller: null, version: activeRequest.version };
    };
  }, [slug]);

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { 
      month: 'long', 
      day: 'numeric', 
      year: 'numeric' 
    });
  };

  const shareOnSocial = (platform) => {
    const url = window.location.href;
    const title = post?.title || '';
    
    const shareUrls = {
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`,
      twitter: `https://twitter.com/intent/tweet?url=${encodeURIComponent(url)}&text=${encodeURIComponent(title)}`,
      linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`
    };

    const shareUrl = shareUrls[platform];
    if (!shareUrl) return;

    try {
      const popup = window.open(shareUrl, '_blank', 'noopener,noreferrer,width=600,height=400');
      if (!popup) {
        setShareError('Your browser blocked the sharing window. Please allow pop-ups and try again.');
        return;
      }
      popup.opener = null;
      setShareError('');
    } catch (err) {
      setShareError('The sharing window could not be opened. Please try again.');
    }
  };

  // Route changes must hide old content before passive effects start the new read.
  if (loading || contentSlug !== slug) {
    return (
      <Layout>
        <div className="min-h-screen bg-black flex items-center justify-center">
          <div className="text-center">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500 mb-4"></div>
            <p className="text-gray-300">Loading article...</p>
          </div>
        </div>
      </Layout>
    );
  }

  if (error || !post) {
    return (
      <Layout>
        <div className="min-h-screen bg-black flex items-center justify-center">
          <div className="text-center">
            <h2 className="mep-heading text-2xl font-bold text-white mb-4">{error || 'Post not found'}</h2>
            <button
              type="button"
              onClick={() => fetchPost(slug)}
              className="mep-primary mr-3 px-6 py-3 font-bold transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-cyan-300"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => navigate('/blog')}
              className="mep-primary px-6 py-3 font-bold transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-cyan-300"
            >
              Back to Blog
            </button>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <SEO
        title={`${post.title} | MarketEdgePros Blog`}
        description={post.excerpt || post.title}
        keywords={post.tags?.join(', ')}
        canonical={`https://marketedgepros.com/blog/${slug}`}
      />

      {/* Reading Progress Bar */}
      <div className="fixed top-0 left-0 w-full h-1 bg-white/10 z-50">
        <div
          className="h-full bg-gradient-to-r from-cyan-500 to-teal-500 transition-all duration-150"
          style={{ width: `${readingProgress}%` }}
        />
      </div>

      <div className="min-h-screen bg-black py-20">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Back Button */}
          <button
            onClick={() => navigate('/blog')}
            className="flex items-center gap-2 text-gray-400 hover:text-white mb-8 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Blog
          </button>

          {/* Article Header */}
          <article className="mb-16">
            {/* Category Badge */}
            {post.category && (
              <div className="mb-6">
                <span className="inline-flex items-center gap-2 px-4 py-2 bg-cyan-500/10 border border-cyan-500/30 rounded-full text-cyan-400 text-sm font-semibold">
                  <Tag className="w-4 h-4" />
                  {post.category}
                </span>
              </div>
            )}

            {/* Title */}
            <h1 className="mep-heading text-4xl md:text-5xl font-bold text-white mb-6">
              {post.title}
            </h1>

            {/* Meta Info */}
            <div className="flex flex-wrap items-center gap-6 text-gray-400 mb-8">
              {post.author && (
                <div className="flex items-center gap-2">
                  <User className="w-4 h-4" />
                  <span>{post.author.name || post.author}</span>
                </div>
              )}
              <div className="flex items-center gap-2">
                <Calendar className="w-4 h-4" />
                <span>{formatDate(post.created_at || post.published_at)}</span>
              </div>
              {post.reading_time && (
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  <span>{post.reading_time} min read</span>
                </div>
              )}
            </div>

            {/* Featured Image */}
            {post.featured_image && (
              <div className="mb-12 rounded-2xl overflow-hidden border border-white/10">
                <img
                  src={post.featured_image}
                  alt={post.title}
                  className="w-full h-auto"
                />
              </div>
            )}

            {/* Content */}
            <div
              className="prose prose-invert prose-lg max-w-none
                prose-headings:text-white prose-headings:font-bold
                prose-h2:text-3xl prose-h2:mt-12 prose-h2:mb-6
                prose-h3:text-2xl prose-h3:mt-8 prose-h3:mb-4
                prose-p:text-gray-300 prose-p:leading-relaxed prose-p:mb-6
                prose-a:text-cyan-400 prose-a:no-underline hover:prose-a:text-cyan-300
                prose-strong:text-white prose-strong:font-bold
                prose-ul:text-gray-300 prose-ul:my-6
                prose-ol:text-gray-300 prose-ol:my-6
                prose-li:my-2
                prose-blockquote:border-l-4 prose-blockquote:border-cyan-500 prose-blockquote:pl-6 prose-blockquote:italic prose-blockquote:text-gray-400
                prose-code:text-cyan-400 prose-code:bg-white/5 prose-code:px-2 prose-code:py-1 prose-code:rounded
                prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-pre:rounded-xl
                prose-img:rounded-xl prose-img:border prose-img:border-white/10"
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(post.content) }}
            />

            {/* Tags */}
            {post.tags && post.tags.length > 0 && (
              <div className="mt-12 pt-8 border-t border-white/10">
                <div className="flex flex-wrap gap-2">
                  {post.tags.map((tag, index) => (
                    <span
                      key={index}
                      className="px-4 py-2 bg-white/5 border border-white/10 rounded-full text-gray-300 text-sm"
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Share Buttons */}
            <div className="mt-12 pt-8 border-t border-white/10">
              <div className="flex items-center gap-4">
                <span className="text-gray-400 font-semibold">Share:</span>
                <button
                  onClick={() => shareOnSocial('facebook')}
                  aria-label="Share on Facebook"
                  type="button"
                  className="p-3 bg-white/5 border border-white/10 rounded-xl hover:border-cyan-500/50 hover:bg-cyan-500/10 transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                >
                  <Facebook className="w-5 h-5 text-gray-300" />
                </button>
                <button
                  onClick={() => shareOnSocial('twitter')}
                  aria-label="Share on X/Twitter"
                  type="button"
                  className="p-3 bg-white/5 border border-white/10 rounded-xl hover:border-cyan-500/50 hover:bg-cyan-500/10 transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                >
                  <Twitter className="w-5 h-5 text-gray-300" />
                </button>
                <button
                  onClick={() => shareOnSocial('linkedin')}
                  aria-label="Share on LinkedIn"
                  type="button"
                  className="p-3 bg-white/5 border border-white/10 rounded-xl hover:border-cyan-500/50 hover:bg-cyan-500/10 transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                >
                  <Linkedin className="w-5 h-5 text-gray-300" />
                </button>
              </div>
              {shareError && <p className="mt-3 text-sm text-rose-200" role="status" aria-live="polite">{shareError}</p>}
            </div>
          </article>

          {/* Related Posts */}
          {relatedPosts.length > 0 && (
            <div>
              <h2 className="mep-heading text-3xl font-bold text-white mb-8">
                Related <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-teal-400">Articles</span>
              </h2>
              <div className="grid md:grid-cols-3 gap-6">
                {relatedPosts.map((relatedPost) => (
                  <Link
                    key={relatedPost.id}
                    to={`/blog/${relatedPost.slug}`}
                    className="group bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl overflow-hidden hover:border-cyan-500/50 transition-all duration-300 hover:scale-105"
                  >
                    {relatedPost.featured_image && (
                      <div className="aspect-video overflow-hidden">
                        <img
                          src={relatedPost.featured_image}
                          alt={relatedPost.title}
                          className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300"
                        />
                      </div>
                    )}
                    <div className="p-6">
                      {relatedPost.category && (
                        <span className="inline-block px-3 py-1 bg-cyan-500/10 border border-cyan-500/30 rounded-full text-cyan-400 text-xs font-semibold mb-3">
                          {relatedPost.category}
                        </span>
                      )}
                      <h3 className="text-lg font-bold text-white mb-2 line-clamp-2 group-hover:text-cyan-400 transition-colors">
                        {relatedPost.title}
                      </h3>
                      {relatedPost.excerpt && (
                        <p className="text-gray-400 text-sm line-clamp-2">
                          {relatedPost.excerpt}
                        </p>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
