/* ============================================================
   QUOTING STUDIO — GLOBAL UTILS
   Auto-scroll/auto-focus: whenever the user clicks, selects, or
   switches an active option ANYWHERE in the app (tabs, shape/door
   cards, colour swatches, hardware/glass grids, profile library,
   filter pills, dropdowns, JSON tab, …) the scrollable panel it
   lives in automatically brings it into view.

   This used to be opt-in: every feature had to remember to call
   scrollActiveIntoView() itself after changing selection state,
   which is exactly why it worked in some places and not others.
   This file now runs a single global engine that watches the whole
   app for selection changes and scrolls them into view on its own —
   no per-feature wiring required, current or future.

   Convention it watches for: any element that becomes the active/
   selected control in a panel carries one of the markers in
   ACTIVE_SELECTOR below (.on / .sel / .active / .selected /
   .qs-active / .qs-prc-active / aria-selected / aria-current).
   Every selection UI in the app already uses one of these — new
   features get auto-scroll for free just by following the same
   convention.
   ============================================================ */
(function () {
  'use strict';

  // ---- core primitives (still directly callable by page code —
  // existing explicit scrollActiveIntoView(...) calls keep working) ----
  function scrollToActiveElement(container, targetElement) {
    if (!container || !targetElement) return;
    targetElement.scrollIntoView({
      behavior: 'smooth',
      block: 'nearest',
      inline: 'nearest'
    });
  }

  // Convenience wrapper — resolves the scrollable container for you.
  // Pass containerSelector when the nearest scrollable ancestor isn't
  // the element's direct parent (e.g. ".dz-scroll", ".p3-hw-grid").
  function scrollActiveIntoView(targetElement, containerSelector) {
    if (!targetElement || !targetElement.isConnected) return;
    const container = containerSelector
      ? targetElement.closest(containerSelector)
      : _findScrollParent(targetElement);
    scrollToActiveElement(container || targetElement.parentElement, targetElement);
  }

  function _findScrollParent(el) {
    let node = el.parentElement;
    while (node && node !== document.body) {
      const cs = getComputedStyle(node);
      const scrollableY = (cs.overflowY === 'auto' || cs.overflowY === 'scroll') && node.scrollHeight > node.clientHeight;
      const scrollableX = (cs.overflowX === 'auto' || cs.overflowX === 'scroll') && node.scrollWidth  > node.clientWidth;
      if (scrollableY || scrollableX) return node;
      node = node.parentElement;
    }
    return null;
  }

  // ---- GLOBAL auto-scroll engine ------------------------------------
  const ACTIVE_SELECTOR =
    '.on:not(.dz-tab), .sel, .active, .selected, .qs-active, .qs-prc-active, ' +
    '[aria-selected="true"], [aria-current="true"]';

  let _pending = null;   // most recent candidate "just became active" element

  function _flagCandidate(el) {
    if (!el || el.nodeType !== 1 || !el.matches) return;
    if (el.matches(ACTIVE_SELECTOR)) _pending = el;
  }

  function _scanAddedSubtree(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.matches && node.matches(ACTIVE_SELECTOR)) _pending = node;
    if (node.querySelectorAll) {
      const found = node.querySelectorAll(ACTIVE_SELECTOR);
      if (found.length) _pending = found[found.length - 1];
    }
  }

  function _flushPending() {
    const el = _pending;
    _pending = null;
    if (window.__qsTabSwitching) return;
    if (!el || !el.isConnected) return;
    scrollActiveIntoView(el);
  }

  // Watches the whole document for two kinds of change that mean
  // "something just became the active selection":
  //  1) an existing element gains a marker class/attribute (persistent
  //     nodes like tabs, tool buttons, shape/door cards, filter pills)
  //  2) a whole subtree is rebuilt via innerHTML (profile library,
  //     glass grid, swatches, hardware/extras panels, JSON tab, …) and
  //     the freshly-created markup already contains the active marker
  function _initMutationObserver() {
    if (!window.MutationObserver || !document.body) return;
    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === 'attributes') {
          _flagCandidate(m.target);
        } else if (m.type === 'childList') {
          m.addedNodes.forEach(_scanAddedSubtree);
        }
      }
      if (_pending) requestAnimationFrame(_flushPending);
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'aria-selected', 'aria-current']
    });
  }

  // <select>/<input>/<textarea> value changes (Openers, Hardware colour
  // pickers, Frame Settings dropdowns, unit type, …) don't add/remove
  // any class, so the MutationObserver above won't see them — a single
  // delegated 'change' listener covers every dropdown/field in the app.
  function _initFormChangeScroll() {
    document.addEventListener('change', (e) => {
      const el = e.target;
      if (el && el.matches && el.matches('select, input, textarea')) {
        scrollActiveIntoView(el);
      }
    }, true);
  }

  function init() {
    _initMutationObserver();
    _initFormChangeScroll();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.scrollToActiveElement = scrollToActiveElement;
  window.scrollActiveIntoView  = scrollActiveIntoView;
})();
