import { useLayoutEffect, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

// Render inside the route Suspense boundary: the destination DOM, not the
// loading fallback, must be committed before scrolling to an anchor.
export default function RouteScrollManager() {
  const { pathname, hash } = useLocation();
  const navigationType = useNavigationType();
  const previous = useRef(null);

  useLayoutEffect(() => {
    const last = previous.current;
    previous.current = { pathname, hash };
    const pathChanged = last !== null && last.pathname !== pathname;
    const hashChanged = last === null || last.hash !== hash || pathChanged;

    if (hash && hashChanged) {
      let id;
      try {
        id = decodeURIComponent(hash.slice(1));
      } catch {
        id = hash.slice(1);
      }
      const target = document.getElementById(id);
      if (target) {
        target.scrollIntoView({ block: 'start', behavior: 'instant' });
        return;
      }
    }

    // Native history restoration handles reload/back/forward. Query-only
    // changes and same-page links keep the user's current reading position.
    if (!pathChanged || navigationType === 'POP') return;
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    document.querySelectorAll('[data-route-scroll-container]').forEach((container) => {
      container.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    });
  }, [pathname, hash, navigationType]);

  return null;
}
