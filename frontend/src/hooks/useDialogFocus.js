import { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'object',
  'embed',
  '[contenteditable="true"]',
  '[tabindex]',
].join(',');

const dialogStacks = new WeakMap();
const bodyScrollLocks = new WeakMap();

function isFocusable(element, root) {
  if (!element.isConnected || element.disabled || element.getAttribute('aria-hidden') === 'true') return false;
  if (element.getAttribute('tabindex') === '-1') return false;

  let parent = element;
  while (parent) {
    if (parent.hidden || parent.getAttribute('aria-hidden') === 'true' || parent.hasAttribute('inert')) return false;
    const style = parent.ownerDocument.defaultView?.getComputedStyle(parent);
    if (style?.display === 'none' || style?.visibility === 'hidden' || style?.visibility === 'collapse') return false;
    if (parent === root) break;
    parent = parent.parentElement;
  }

  return element.tabIndex >= 0;
}

function focusableElements(root) {
  return Array.from(root.querySelectorAll(FOCUSABLE_SELECTOR))
    .filter((element) => isFocusable(element, root));
}

function focusElement(element) {
  try {
    element.focus({ preventScroll: true });
  } catch {
    element.focus();
  }
}

function pushDialog(documentRef, root) {
  const stack = dialogStacks.get(documentRef) ?? [];
  stack.push(root);
  dialogStacks.set(documentRef, stack);

  return () => {
    const current = dialogStacks.get(documentRef);
    if (!current) return;
    const index = current.lastIndexOf(root);
    if (index !== -1) current.splice(index, 1);
    if (current.length === 0) dialogStacks.delete(documentRef);
  };
}

function isTopDialog(documentRef, root) {
  const stack = dialogStacks.get(documentRef);
  return stack?.[stack.length - 1] === root;
}

function lockBodyScroll(documentRef) {
  const body = documentRef.body;
  if (!body) return () => {};

  let state = bodyScrollLocks.get(documentRef);
  if (!state) {
    state = { body, count: 0, overflow: body.style.overflow };
    bodyScrollLocks.set(documentRef, state);
  }

  if (state.count === 0) state.overflow = body.style.overflow;
  state.count += 1;
  body.style.overflow = 'hidden';

  return () => {
    state.count -= 1;
    if (state.count > 0) return;
    state.body.style.overflow = state.overflow;
    bodyScrollLocks.delete(documentRef);
  };
}

/**
 * Manages accessible focus for a conditionally rendered dialog, drawer, or portal.
 *
 * @param {{open: boolean, onClose?: (event: KeyboardEvent) => void}} options
 * @returns {import('react').MutableRefObject<HTMLElement | null>} Attach to the dialog root.
 */
export function useDialogFocus({ open, onClose }) {
  const rootRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open || typeof document === 'undefined') return undefined;

    const documentRef = document;
    const root = rootRef.current;
    if (!root) return undefined;

    const trigger = documentRef.activeElement instanceof HTMLElement ? documentRef.activeElement : null;
    const restoreStack = pushDialog(documentRef, root);
    const unlockBodyScroll = lockBodyScroll(documentRef);
    const originalTabIndex = root.getAttribute('tabindex');
    let addedRootTabIndex = false;

    const focusInitial = () => {
      const preferred = root.querySelector('[data-autofocus], [autofocus]');
      if (preferred && isFocusable(preferred, root)) {
        focusElement(preferred);
        return;
      }

      const [first] = focusableElements(root);
      if (first) {
        focusElement(first);
        return;
      }

      if (!root.hasAttribute('tabindex')) {
        root.setAttribute('tabindex', '-1');
        addedRootTabIndex = true;
      }
      focusElement(root);
    };

    const onKeyDown = (event) => {
      if (!isTopDialog(documentRef, root)) return;

      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current?.(event);
        return;
      }

      if (event.key !== 'Tab') return;

      const items = focusableElements(root);
      if (items.length === 0) {
        event.preventDefault();
        focusElement(root);
        return;
      }

      const activeElement = documentRef.activeElement;
      const index = items.indexOf(activeElement);
      const next = event.shiftKey
        ? items[index <= 0 ? items.length - 1 : index - 1]
        : items[index === -1 || index === items.length - 1 ? 0 : index + 1];

      event.preventDefault();
      focusElement(next);
    };

    const onFocusIn = (event) => {
      if (isTopDialog(documentRef, root) && !root.contains(event.target)) focusInitial();
    };
    focusInitial();
    documentRef.addEventListener('keydown', onKeyDown);
    documentRef.addEventListener('focusin', onFocusIn);

    return () => {
      documentRef.removeEventListener('keydown', onKeyDown);
      documentRef.removeEventListener('focusin', onFocusIn);
      restoreStack();
      unlockBodyScroll();
      if (addedRootTabIndex) {
        if (originalTabIndex === null) root.removeAttribute('tabindex');
        else root.setAttribute('tabindex', originalTabIndex);
      }
      if (trigger?.isConnected) focusElement(trigger);
    };
  }, [open]);

  return rootRef;
}

export default useDialogFocus;
