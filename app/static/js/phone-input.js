(function () {
  function digitsOnly(value) {
    return (value || '').replace(/\D/g, '');
  }

  function buildFullPhone(dial, local) {
    const dialDigits = digitsOnly(dial);
    let localDigits = digitsOnly(local);
    if (!dialDigits || !localDigits) return '';
    while (localDigits.length > 1 && localDigits.startsWith('0')) {
      localDigits = localDigits.slice(1);
    }
    return '+' + dialDigits + localDigits;
  }

  function init(root) {
    const dial = root.querySelector('[data-phone-dial]');
    const local = root.querySelector('[data-phone-local]');
    const full = root.querySelector('[data-phone-full]');
    if (!dial || !local || !full) return;

    local.addEventListener('input', function () {
      const cleaned = digitsOnly(local.value);
      if (cleaned !== local.value) local.value = cleaned;
    });

    const sync = function () {
      full.value = buildFullPhone(dial.value, local.value);
    };

    dial.addEventListener('change', sync);
    local.addEventListener('input', sync);
    sync();

    const form = root.closest('form');
    if (form) {
      form.addEventListener('submit', sync);
    }
  }

  document.querySelectorAll('[data-phone-intl]').forEach(init);
})();
