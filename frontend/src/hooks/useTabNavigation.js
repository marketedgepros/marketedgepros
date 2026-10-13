import { useCallback, useRef } from 'react';

/**
 * Returns props for a controlled horizontal tab. Keep `ids` unique and stable across renders.
 *
 * @param {{ids: Array<string | number>, activeId: string | number, onChange?: (id: string | number) => void}} options
 * @returns {(id: string | number) => {role: string, tabIndex: number, 'aria-selected': boolean, ref: (node: HTMLElement | null) => void, onClick: () => void, onKeyDown: (event: KeyboardEvent) => void}}
 */
export function useTabNavigation({ ids, activeId, onChange }) {
  const idsRef = useRef(ids);
  const activeIdRef = useRef(activeId);
  const onChangeRef = useRef(onChange);
  const tabElementsRef = useRef(new Map());

  idsRef.current = Array.isArray(ids) ? ids : [];
  activeIdRef.current = activeId;
  onChangeRef.current = onChange;

  const registerTab = useCallback((id, node) => {
    if (node) tabElementsRef.current.set(id, node);
    else tabElementsRef.current.delete(id);
  }, []);

  const selectAndFocus = useCallback((id) => {
    onChangeRef.current?.(id);
    const nextTab = tabElementsRef.current.get(id);
    if (nextTab?.isConnected && !nextTab.disabled) nextTab.focus();
  }, []);

  const onKeyDown = useCallback((id, event) => {
    const currentIds = idsRef.current;
    const currentIndex = currentIds.indexOf(id);
    if (currentIndex === -1 || currentIds.length === 0) return;

    let nextIndex;
    switch (event.key) {
      case 'ArrowRight':
        nextIndex = (currentIndex + 1) % currentIds.length;
        break;
      case 'ArrowLeft':
        nextIndex = (currentIndex - 1 + currentIds.length) % currentIds.length;
        break;
      case 'Home':
        nextIndex = 0;
        break;
      case 'End':
        nextIndex = currentIds.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    selectAndFocus(currentIds[nextIndex]);
  }, [selectAndFocus]);

  return useCallback((id) => ({
    role: 'tab',
    tabIndex: activeIdRef.current === id ? 0 : -1,
    'aria-selected': activeIdRef.current === id,
    ref: (node) => registerTab(id, node),
    onClick: () => selectAndFocus(id),
    onKeyDown: (event) => onKeyDown(id, event),
  }), [onKeyDown, registerTab, selectAndFocus]);
}

export default useTabNavigation;
