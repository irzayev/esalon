/**
 * Washer CRM theme: light / dark with localStorage persistence.
 */
(function () {
  const STORAGE_KEY = 'washer-theme';

  function systemPrefersDark() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function getStored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  function resolveTheme() {
    const stored = getStored();
    if (stored === 'dark' || stored === 'light') return stored;
    return systemPrefersDark() ? 'dark' : 'light';
  }

  function apply(theme) {
    const root = document.documentElement;
    const isDark = theme === 'dark';
    root.classList.toggle('dark', isDark);
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch { /* private browsing */ }
    syncToggles(isDark);
    window.dispatchEvent(new CustomEvent('washer-theme-change', { detail: { theme } }));
  }

  function syncToggles(isDark) {
    document.querySelectorAll('[data-theme-toggle]').forEach((el) => {
      el.setAttribute('aria-checked', isDark ? 'true' : 'false');
      el.dataset.state = isDark ? 'dark' : 'light';
    });
  }

  function toggle() {
    apply(document.documentElement.classList.contains('dark') ? 'light' : 'dark');
  }

  function initToggles() {
    document.querySelectorAll('[data-theme-toggle]').forEach((el) => {
      if (el.dataset.themeBound) return;
      el.dataset.themeBound = '1';
      el.addEventListener('click', (e) => {
        e.preventDefault();
        toggle();
      });
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        }
      });
    });
    syncToggles(document.documentElement.classList.contains('dark'));
  }

  window.WasherTheme = {
    get: () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light'),
    set: apply,
    toggle,
    initToggles,
  };

  apply(resolveTheme());

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initToggles);
  } else {
    initToggles();
  }
})();
