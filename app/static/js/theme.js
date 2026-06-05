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

  function getDefaultTheme() {
    const def = document.documentElement.dataset.defaultTheme || 'auto';
    if (def === 'dark' || def === 'light') return def;
    return systemPrefersDark() ? 'dark' : 'light';
  }

  function resolveTheme() {
    const stored = getStored();
    if (stored === 'dark' || stored === 'light') return stored;
    return getDefaultTheme();
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
    const theme = isDark ? 'dark' : 'light';
    document.querySelectorAll('.theme-switch [data-theme-mode]').forEach((btn) => {
      const active = btn.dataset.themeMode === theme;
      btn.classList.toggle('theme-switch__btn--active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function toggle() {
    apply(document.documentElement.classList.contains('dark') ? 'light' : 'dark');
  }

  function initToggles() {
    document.querySelectorAll('.theme-switch').forEach((group) => {
      if (group.dataset.themeBound) return;
      group.dataset.themeBound = '1';
      group.querySelectorAll('[data-theme-mode]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          apply(btn.dataset.themeMode);
        });
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
