import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Calendar, Clock, ArrowRight, Search, Loader, Mail, BookOpen } from 'lucide-react';
import Layout from '../components/layout/Layout';
import api from "../services/api";

const POSTS_PER_PAGE = 9;

export default function Blog() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [posts, setPosts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [featuredPosts, setFeaturedPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [pagination, setPagination] = useState({ page: 1, per_page: POSTS_PER_PAGE, total_posts: 0, total_pages: 0 });
  const [requestedPage, setRequestedPage] = useState(1);
  const postsRequestRef = useRef({ controller: null, version: 0 });

  const fetchPosts = async (page = 1, category = 'all') => {
    const previousRequest = postsRequestRef.current;
    previousRequest.controller?.abort();

    const controller = new AbortController();
    const version = previousRequest.version + 1;
    postsRequestRef.current = { controller, version };
    const isCurrentRequest = () => (
      postsRequestRef.current.version === version
      && postsRequestRef.current.controller === controller
    );

    try {
      setLoading(true);
      setError('');
      const params = { page, per_page: POSTS_PER_PAGE };
      if (category !== 'all') params.category = category;
      const response = await api.get('/blog/posts', { params, signal: controller.signal });
      if (!isCurrentRequest()) return;

      setPosts(Array.isArray(response.data?.posts) ? response.data.posts : []);
      setPagination(response.data?.pagination || {
        page,
        per_page: POSTS_PER_PAGE,
        total_posts: 0,
        total_pages: 0,
      });
    } catch (err) {
      if (controller.signal.aborted || !isCurrentRequest()) return;
      console.error('Failed to fetch posts:', err);
      setError('Blog posts could not be loaded. Please try again.');
      setPosts([]);
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  };

  const fetchCategories = async () => {
    try {
      const response = await api.get('/blog/categories');
      const result = response.data?.categories;
      setCategories(Array.isArray(result) ? result.filter((item) => typeof item?.name === 'string' && item.name.trim()) : []);
    } catch (err) {
      console.error('Failed to fetch categories:', err);
      setCategories([]);
    }
  };

  const fetchFeaturedPosts = async () => {
    try {
      const response = await api.get('/blog/featured');
      setFeaturedPosts(Array.isArray(response.data?.posts) ? response.data.posts : []);
    } catch (err) {
      console.error('Failed to fetch featured posts:', err);
      setFeaturedPosts([]);
    }
  };

  useEffect(() => {
    fetchPosts();
    fetchCategories();
    fetchFeaturedPosts();

    return () => {
      const activeRequest = postsRequestRef.current;
      activeRequest.version += 1;
      activeRequest.controller?.abort();
      postsRequestRef.current = { controller: null, version: activeRequest.version };
    };
  }, []);

  const handleCategoryChange = (category) => {
    setSelectedCategory(category);
    setRequestedPage(1);
    fetchPosts(1, category);
  };
  const handlePageChange = (page) => {
    setRequestedPage(page);
    fetchPosts(page, selectedCategory);
  };

  const retryPosts = () => {
    if (requestedPage === 1) {
      fetchPosts(1, selectedCategory);
      return;
    }
    fetchPosts(requestedPage, selectedCategory);
  };

  const query = searchQuery.trim().toLocaleLowerCase();
  const filteredPosts = posts.filter((post) => {
    const title = typeof post.title === 'string' ? post.title : '';
    const excerpt = typeof post.excerpt === 'string' ? post.excerpt : '';
    return `${title} ${excerpt}`.toLocaleLowerCase().includes(query);
  });

  return (
    <Layout>
      <main className="mep-screen min-h-screen text-slate-100">
        <section className="relative overflow-hidden border-b border-cyan-900/50 bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900">
          <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(34,211,238,0.14),transparent_55%)]" />
          <div className="relative mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
            <p className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-cyan-300"><BookOpen size={17} /> MarketEdgePros</p>
            <h1 className="mep-heading max-w-3xl text-4xl font-bold tracking-tight text-white sm:text-6xl">Trading articles</h1>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-slate-300">Browse the articles available here. Use search and categories to explore published posts.</p>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
          <div className="grid gap-10 lg:grid-cols-12">
            <section className="lg:col-span-8" aria-label="Blog posts">
              {loading ? (
                <div className="flex min-h-64 items-center justify-center" role="status" aria-label="Loading posts"><Loader className="h-9 w-9 animate-spin text-cyan-400" /></div>
              ) : error ? (
                <div className="rounded-2xl border border-rose-400/30 bg-rose-950/30 p-8 text-center" role="alert">
                  <p className="mb-4 text-rose-200">{error}</p>
                  <button type="button" onClick={retryPosts} className="rounded-lg border border-cyan-400/50 px-5 py-2.5 font-semibold text-cyan-200 hover:bg-cyan-400/10 focus:outline-none focus:ring-2 focus:ring-cyan-300">Try again</button>
                </div>
              ) : filteredPosts.length === 0 ? (
                <div className="mep-panel rounded-2xl border px-6 py-12 text-center">
                  <p className="text-lg text-slate-300">{query ? 'No posts match your search on the currently loaded page.' : 'No posts are available in this view.'}</p>
                  {query && <button type="button" onClick={() => setSearchQuery('')} className="mt-3 text-cyan-300 underline underline-offset-4 focus:outline-none focus:ring-2 focus:ring-cyan-300">Clear search</button>}
                </div>
              ) : (
                <div className="space-y-5">
                  {filteredPosts.map((post) => (
                    <article key={post.id} className="mep-panel rounded-2xl border p-6 shadow-lg shadow-slate-950/30 transition-colors hover:border-cyan-700 sm:p-8">
                      <h2 className="mep-heading text-2xl font-bold leading-snug text-white"><Link className="rounded-sm hover:text-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300" to={`/blog/${post.slug}`}>{post.title}</Link></h2>
                      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-slate-400">
                        {post.published_at && <span className="inline-flex items-center gap-2"><Calendar size={15} aria-hidden="true" />{new Date(post.published_at).toLocaleDateString()}</span>}
                        {(post.reading_time || post.read_time) && <span className="inline-flex items-center gap-2"><Clock size={15} aria-hidden="true" />{post.reading_time || post.read_time} min read</span>}
                      </div>
                      {typeof post.excerpt === 'string' && post.excerpt && <p className="mt-4 leading-7 text-slate-300">{post.excerpt}</p>}
                      <Link to={`/blog/${post.slug}`} className="mt-5 inline-flex items-center gap-2 rounded-sm font-semibold text-cyan-300 hover:text-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-300">Read article <ArrowRight size={16} aria-hidden="true" /></Link>
                    </article>
                  ))}
                </div>
              )}
              {!loading && !error && pagination.total_pages > 1 && <nav className="mt-8 flex flex-wrap justify-center gap-2" aria-label="Blog pages">
                {Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map((page) => <button key={page} type="button" aria-current={pagination.page === page ? 'page' : undefined} onClick={() => handlePageChange(page)} className={`min-h-11 min-w-11 rounded-lg border px-3 font-semibold focus:outline-none focus:ring-2 focus:ring-cyan-300 ${pagination.page === page ? 'border-cyan-400 bg-cyan-900/60 text-white' : 'border-slate-700 text-slate-300 hover:border-cyan-700'}`}>{page}</button>)}
              </nav>}
            </section>

            <aside className="space-y-8 lg:col-span-4">
              <section className="rounded-2xl border border-cyan-800/70 bg-gradient-to-br from-blue-950 to-slate-900 p-6">
                <div className="flex items-center gap-3"><Mail className="text-cyan-300" aria-hidden="true" /><h2 className="mep-heading text-xl font-bold text-white">Blog updates</h2></div>
                <p className="mt-3 leading-6 text-slate-300">Newsletter subscriptions are not available. Contact us for current information.</p>
                <Link to="/contact" className="mt-4 inline-flex min-h-11 items-center rounded-lg border border-cyan-400/50 px-4 font-semibold text-cyan-200 hover:bg-cyan-400/10 focus:outline-none focus:ring-2 focus:ring-cyan-300">Contact</Link>
              </section>

              <section>
                <h2 className="mep-heading mb-3 text-lg font-bold text-white">Search posts on this page</h2>
                <label htmlFor="blog-search" className="sr-only">Search posts loaded on this page</label>
                <div className="relative"><Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" aria-hidden="true" /><input id="blog-search" type="search" placeholder="Search posts on this page" aria-describedby="blog-search-scope" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} className="min-h-12 w-full rounded-lg border border-slate-700 bg-slate-900 pl-10 pr-3 text-white placeholder:text-slate-400 focus:border-cyan-400 focus:outline-none focus:ring-2 focus:ring-cyan-400/40" /></div>
                <p id="blog-search-scope" className="mt-2 text-sm leading-5 text-slate-400">Search is limited to posts loaded on the current page.</p>
              </section>

              {categories.length > 0 && <section>
                <h2 className="mep-heading mb-3 text-lg font-bold text-white">Categories</h2>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => handleCategoryChange('all')} aria-pressed={selectedCategory === 'all'} className={`min-h-10 rounded-full border px-4 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-cyan-300 ${selectedCategory === 'all' ? 'border-cyan-400 bg-cyan-900/70 text-white' : 'border-slate-700 text-slate-300 hover:border-cyan-700'}`}>All</button>
                  {categories.map((category) => <button type="button" key={category.name} onClick={() => handleCategoryChange(category.name)} aria-pressed={selectedCategory === category.name} className={`min-h-10 rounded-full border px-4 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-cyan-300 ${selectedCategory === category.name ? 'border-cyan-400 bg-cyan-900/70 text-white' : 'border-slate-700 text-slate-300 hover:border-cyan-700'}`}>{category.name}</button>)}
                </div>
              </section>}

              {featuredPosts.length > 0 && <section>
                <h2 className="mep-heading mb-3 text-lg font-bold text-white">Featured posts</h2>
                <div className="space-y-3">{featuredPosts.map((post) => <article key={post.id} className="mep-panel rounded-xl border p-4"><h3 className="font-semibold text-slate-100"><Link to={`/blog/${post.slug}`} className="rounded-sm hover:text-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300">{post.title}</Link></h3></article>)}</div>
              </section>}
            </aside>
          </div>
        </section>
      </main>
    </Layout>
  );
}
