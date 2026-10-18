import assert from 'node:assert/strict';
import test from 'node:test';
import React, { act } from 'react';
import { createPortal } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import useDialogFocus from '../src/hooks/useDialogFocus.js';
import useTabNavigation from '../src/hooks/useTabNavigation.js';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function installDom() {
  const instance = new JSDOM(
    '<!doctype html><html><body><button id="trigger">Open drawer</button><div id="root"></div><div id="portal"></div></body></html>',
    { url: 'https://foundation.test/', pretendToBeVisual: true },
  );
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'KeyboardEvent', 'Event'];
  const previous = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const key of keys) {
    Object.defineProperty(globalThis, key, {
      value: instance.window[key], configurable: true, writable: true,
    });
  }

  return {
    instance,
    document: instance.window.document,
    restore() {
      for (const [key, descriptor] of previous) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      instance.window.close();
    },
  };
}

function keydown(target, key, options = {}) {
  const event = new window.KeyboardEvent('keydown', {
    key, bubbles: true, cancelable: true, ...options,
  });
  target.dispatchEvent(event);
  return event;
}

function PortalDialog({ open, onClose, empty = false }) {
  const dialogRef = useDialogFocus({ open, onClose });
  if (!open) return null;

  return createPortal(
    React.createElement('section', {
      ref: dialogRef,
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': 'Synthetic drawer',
    }, empty
      ? null
      : [
        React.createElement('button', { key: 'hidden', type: 'button', hidden: true }, 'Hidden'),
        React.createElement('span', { key: 'display-none', style: { display: 'none' } },
          React.createElement('button', { type: 'button' }, 'CSS hidden')),
        React.createElement('button', { key: 'first', type: 'button', 'data-autofocus': true }, 'First'),
        React.createElement('button', { key: 'last', type: 'button' }, 'Last'),
      ]),
    document.getElementById('portal'),
  );
}

function Tabs({ ids, activeId, onChange }) {
  const getTabProps = useTabNavigation({ ids, activeId, onChange });
  return React.createElement('div', { role: 'tablist', 'aria-label': 'Synthetic tabs' },
    ids.map((id) => React.createElement('button', { key: id, ...getTabProps(id) }, id)));
}

test('foundation dialog hook focuses a portal, traps Tab, calls the latest close callback, restores focus, and restores body overflow', async () => {
  const dom = installDom();
  const root = createRoot(dom.document.getElementById('root'));
  const trigger = dom.document.getElementById('trigger');
  let firstCallbackCalls = 0;
  let latestCallbackCalls = 0;

  try {
    dom.document.body.style.overflow = 'scroll';
    trigger.focus();
    await act(async () => {
      root.render(React.createElement(PortalDialog, {
        open: true,
        onClose: () => { firstCallbackCalls += 1; },
      }));
    });

    const dialog = dom.document.querySelector('[role="dialog"]');
    const first = dialog.querySelector('[data-autofocus]');
    const last = Array.from(dialog.querySelectorAll('button')).find((button) => button.textContent === 'Last');
    assert.equal(dom.document.activeElement, first, 'the data-autofocus control receives initial focus in a portal');
    assert.equal(dom.document.body.style.overflow, 'hidden', 'the existing inline overflow is locked only while open');

    trigger.focus();
    assert.equal(dom.document.activeElement, first, 'focus escaping to the background is returned into the open dialog');
    last.focus();
    const tabFromLast = keydown(last, 'Tab');
    assert.equal(tabFromLast.defaultPrevented, true);
    assert.equal(dom.document.activeElement, first, 'Tab wraps from the last focusable control');

    first.focus();
    const shiftTabFromFirst = keydown(first, 'Tab', { shiftKey: true });
    assert.equal(shiftTabFromFirst.defaultPrevented, true);
    assert.equal(dom.document.activeElement, last, 'Shift+Tab wraps from the first focusable control');

    await act(async () => {
      root.render(React.createElement(PortalDialog, {
        open: true,
        onClose: () => { latestCallbackCalls += 1; },
      }));
    });
    assert.equal(dom.document.activeElement, last, 'a new callback does not reset focus while the dialog stays open');

    const escape = keydown(last, 'Escape');
    assert.equal(escape.defaultPrevented, true);
    assert.equal(firstCallbackCalls, 0);
    assert.equal(latestCallbackCalls, 1, 'Escape uses the latest onClose callback without reinstalling focus');

    await act(async () => {
      root.render(React.createElement(PortalDialog, { open: false, onClose: () => {} }));
    });
    assert.equal(dom.document.activeElement, trigger, 'closing restores focus to the connected trigger');
    assert.equal(dom.document.body.style.overflow, 'scroll', 'the exact prior overflow value is restored');
    keydown(dom.document, 'Escape');
    assert.equal(latestCallbackCalls, 1, 'the document listener is removed on close');
    dom.document.getElementById('root').setAttribute('tabindex', '0');
    dom.document.getElementById('root').focus();
    assert.equal(dom.document.activeElement.id, 'root', 'focusin listener is removed after close');
  } finally {
    await act(async () => { root.unmount(); });
    dom.restore();
  }
});

test('foundation dialog hook safely handles a dialog with no focusable controls and a removed trigger', async () => {
  const dom = installDom();
  const root = createRoot(dom.document.getElementById('root'));
  const trigger = dom.document.getElementById('trigger');

  try {
    trigger.focus();
    await act(async () => {
      root.render(React.createElement(PortalDialog, { open: true, onClose: () => {}, empty: true }));
    });
    const dialog = dom.document.querySelector('[role="dialog"]');
    assert.equal(dom.document.activeElement, dialog, 'the root receives focus when no descendant can receive it');
    assert.equal(dialog.getAttribute('tabindex'), '-1');

    trigger.remove();
    trigger.focus = () => { throw new Error('a disconnected trigger must not be focused'); };
    await act(async () => {
      root.render(React.createElement(PortalDialog, { open: false, onClose: () => {}, empty: true }));
    });
    assert.equal(dialog.hasAttribute('tabindex'), false, 'temporary root tabindex is cleaned up exactly');
  } finally {
    await act(async () => { root.unmount(); });
    dom.restore();
  }
});

test('foundation tab hook implements roving tabindex with ArrowLeft/Right, Home, End, click selection, and current callbacks', async () => {
  const dom = installDom();
  const root = createRoot(dom.document.getElementById('root'));
  const ids = ['overview', 'activity', 'security'];
  let active = 'overview';
  const changes = [];
  const renderTabs = (onChange) => React.createElement(Tabs, { ids, activeId: active, onChange });
  const currentCallback = (id) => {
    changes.push(id);
    active = id;
    root.render(renderTabs(currentCallback));
  };

  try {
    await act(async () => { root.render(renderTabs(currentCallback)); });
    const tabs = () => Array.from(dom.document.querySelectorAll('[role="tab"]'));
    assert.deepEqual(tabs().map((tab) => tab.tabIndex), [0, -1, -1]);
    assert.deepEqual(tabs().map((tab) => tab.getAttribute('aria-selected')), ['true', 'false', 'false']);

    tabs()[0].focus();
    await act(async () => { keydown(tabs()[0], 'ArrowLeft'); });
    assert.equal(dom.document.activeElement.textContent, 'security', 'ArrowLeft wraps to the last stable id');
    assert.equal(active, 'security');

    await act(async () => { keydown(dom.document.activeElement, 'Home'); });
    assert.equal(dom.document.activeElement.textContent, 'overview');
    assert.equal(active, 'overview');

    await act(async () => { keydown(dom.document.activeElement, 'End'); });
    assert.equal(dom.document.activeElement.textContent, 'security');
    assert.equal(active, 'security');

    await act(async () => { tabs()[1].click(); });
    assert.equal(active, 'activity');
    assert.equal(tabs()[1].getAttribute('aria-selected'), 'true');
    assert.deepEqual(changes, ['security', 'overview', 'security', 'activity']);

    let staleCalls = 0;
    let freshCalls = 0;
    active = 'overview';
    await act(async () => { root.render(renderTabs(() => { staleCalls += 1; })); });
    await act(async () => { root.render(renderTabs(() => { freshCalls += 1; })); });
    await act(async () => { keydown(tabs()[0], 'ArrowRight'); });
    assert.equal(staleCalls, 0);
    assert.equal(freshCalls, 1, 'the returned keyboard handler reads the latest onChange callback');
  } finally {
    await act(async () => { root.unmount(); });
    dom.restore();
  }
});
