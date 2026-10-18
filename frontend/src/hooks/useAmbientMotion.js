import { useEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from './useScrollReveal';

/** Visible-only decorative CSS motion; no JavaScript animation loop or feed. */
export default function useAmbientMotion() {
  const ref = useRef(null);
  const reduced = usePrefersReducedMotion();
  const [visible, setVisible] = useState(false);
  const [pageVisible, setPageVisible] = useState(true);

  useEffect(() => {
    const target = ref.current;
    const Observer = window.IntersectionObserver;
    const updatePage = () => setPageVisible(document.visibilityState !== 'hidden');
    updatePage();
    document.addEventListener('visibilitychange', updatePage);
    let observer;
    let active = true;
    if (target && typeof Observer === 'function') {
      observer = new Observer((entries) => {
        if (!active) return;
        const entry = entries.find((candidate) => candidate.target === target);
        if (entry) setVisible(entry.isIntersecting);
      }, { threshold: 0.05 });
      observer.observe(target);
    }
    // Unsupported observation leaves the illustration static, not hidden.
    return () => {
      active = false;
      observer?.disconnect();
      document.removeEventListener('visibilitychange', updatePage);
    };
  }, []);

  return { ref, reduced, running: visible && pageVisible && !reduced };
}
