/**
 * Persist locale cookie when user follows lang-switch links (server sets cookie too).
 */
(function () {
  const COOKIE_KEY = 'washer-locale';

  function readCookie() {
    const m = document.cookie.match(new RegExp('(?:^|; )' + COOKIE_KEY + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : null;
  }

  document.querySelectorAll('[data-locale]').forEach((el) => {
    el.addEventListener('click', () => {
      const loc = el.getAttribute('data-locale');
      if (loc === 'az' || loc === 'ru') {
        try {
          document.cookie =
            COOKIE_KEY + '=' + encodeURIComponent(loc) + ';path=/;max-age=31536000;samesite=lax';
        } catch { /* ignore */ }
      }
    });
  });

  window.WasherLocale = { get: readCookie };
})();
