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

  function dialOptionLabel(option, showCountry) {
    const code = option.value || '';
    const name = option.dataset.countryName || '';
    if (showCountry && name) return code + ' ' + name;
    return code;
  }

  function setDialSelectLabels(select, showCountry) {
    Array.from(select.options).forEach(function (option) {
      option.textContent = dialOptionLabel(option, showCountry);
    });
  }

  function init(root) {
    const dial = root.querySelector('[data-phone-dial]');
    const local = root.querySelector('[data-phone-local]');
    const full = root.querySelector('[data-phone-full]');
    if (!dial || !local || !full) return;

    setDialSelectLabels(dial, false);
    dial.addEventListener('mousedown', function () {
      setDialSelectLabels(dial, true);
    });
    dial.addEventListener('focus', function () {
      setDialSelectLabels(dial, true);
    });
    dial.addEventListener('blur', function () {
      setDialSelectLabels(dial, false);
    });
    dial.addEventListener('change', function () {
      setDialSelectLabels(dial, false);
    });

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
