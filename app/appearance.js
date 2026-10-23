/* Apply the saved appearance before CSS and page content paint. This module is
   independent of data loading: changing a style never fetches or rerenders news. */
(() => {
  'use strict';
  const STORAGE_KEY = 'gni.appearance.v1';
  const THEMES = { newspaper: '#e9e0d1', minimal: '#f3f5f7', night: '#101822' };
  let currentTheme = 'newspaper';

  function applyTheme(value, persist = false) {
    currentTheme = Object.hasOwn(THEMES, value) ? value : 'newspaper';
    document.documentElement.dataset.theme = currentTheme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEMES[currentTheme]);
    document.querySelectorAll('input[name="visual-theme"]').forEach(input => {
      input.checked = input.value === currentTheme;
    });
    if (persist) {
      try { window.localStorage.setItem(STORAGE_KEY, currentTheme); } catch { /* Session choice still works. */ }
    }
  }

  let saved;
  try { saved = window.localStorage.getItem(STORAGE_KEY); } catch { /* Use the newspaper default. */ }
  applyTheme(saved);

  window.addEventListener('storage', event => {
    if (event.key === STORAGE_KEY || event.key === null) applyTheme(event.newValue);
  });

  document.addEventListener('DOMContentLoaded', () => {
    const button = document.querySelector('#appearance-button');
    const dialog = document.querySelector('#appearance-dialog');
    if (!button || !dialog) return;
    applyTheme(currentTheme);
    button.addEventListener('click', () => {
      if (dialog.open) return;
      dialog.showModal();
      button.setAttribute('aria-expanded', 'true');
      dialog.querySelector('input:checked')?.focus({ preventScroll: true });
    });
    document.querySelector('#appearance-close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => button.setAttribute('aria-expanded', 'false'));
    dialog.addEventListener('change', event => {
      if (event.target.matches('input[name="visual-theme"]')) applyTheme(event.target.value, true);
    });
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });
  });
})();
