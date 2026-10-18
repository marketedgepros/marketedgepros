import { useEffect, useRef, useState } from 'react';

export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

function readReducedMotionPreference() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

export function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(readReducedMotionPreference);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;

    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches);
    updatePreference();

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', updatePreference);
      return () => mediaQuery.removeEventListener('change', updatePreference);
    }

    mediaQuery.addListener?.(updatePreference);
    return () => mediaQuery.removeListener?.(updatePreference);
  }, []);

  return prefersReducedMotion;
}

/**
 * Adds a one-time entrance state only when the browser can observe the target.
 * Targets stay visible by default so server rendering and unsupported browsers
 * never leave content hidden.
 */
export default function useScrollReveal({
  root = null,
  rootMargin = '0px 0px -8% 0px',
  threshold = 0.08,
} = {}) {
  const ref = useRef(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [state, setState] = useState('visible');

  useEffect(() => {
    const target = ref.current;
    const Observer = typeof window !== 'undefined' ? window.IntersectionObserver : undefined;

    if (!target || prefersReducedMotion || typeof Observer !== 'function') {
      setState('visible');
      return undefined;
    }

    let active = true;
    let completed = false;
    const observer = new Observer((entries) => {
      const entry = entries.find((candidate) => candidate.target === target && candidate.isIntersecting);
      if (!active || completed || !entry) return;

      completed = true;
      setState('revealed');
      observer.unobserve(target);
      observer.disconnect();
    }, { root, rootMargin, threshold });

    setState('pending');
    observer.observe(target);

    return () => {
      active = false;
      if (!completed) observer.disconnect();
    };
  }, [prefersReducedMotion, root, rootMargin, threshold]);

  const className = state === 'pending'
    ? 'scroll-reveal scroll-reveal--pending'
    : state === 'revealed'
      ? 'scroll-reveal scroll-reveal--revealed'
      : '';

  return { ref, state, className };
}
