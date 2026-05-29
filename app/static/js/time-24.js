/**
 * Normalize schedule time fields to 24h HH:MM (e.g. "930" -> "09:30").
 */
(function () {
  function normalizeTime(raw) {
    if (!raw) return '';
    var v = String(raw).trim().replace(/[^\d:]/g, '');
    if (v.indexOf(':') >= 0) {
      var parts = v.split(':');
      var h = parseInt(parts[0], 10);
      var m = parseInt(parts[1] || '0', 10);
      if (isNaN(h) || h < 0 || h > 23 || isNaN(m) || m < 0 || m > 59) return raw.trim();
      return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
    }
    if (v.length <= 2) {
      var h2 = parseInt(v, 10);
      if (isNaN(h2) || h2 > 23) return raw.trim();
      return String(h2).padStart(2, '0') + ':00';
    }
    if (v.length === 3) {
      var h3 = parseInt(v.slice(0, 1), 10);
      var m3 = parseInt(v.slice(1), 10);
      if (h3 <= 9 && m3 <= 59) return '0' + h3 + ':' + String(m3).padStart(2, '0');
    }
    if (v.length >= 4) {
      var h4 = parseInt(v.slice(0, v.length - 2), 10);
      var m4 = parseInt(v.slice(-2), 10);
      if (!isNaN(h4) && h4 <= 23 && !isNaN(m4) && m4 <= 59) {
        return String(h4).padStart(2, '0') + ':' + String(m4).padStart(2, '0');
      }
    }
    return raw.trim();
  }

  function bind(el) {
    el.addEventListener('blur', function () {
      var n = normalizeTime(el.value);
      if (n) el.value = n;
    });
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        var n = normalizeTime(el.value);
        if (n) el.value = n;
      }
    });
  }

  document.querySelectorAll('[data-time-24]').forEach(bind);
})();
