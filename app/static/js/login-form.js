(function () {
  const form = document.getElementById('login-form');
  if (!form) return;

  const methodInput = form.querySelector('[data-login-method]');
  const tabs = form.querySelectorAll('[data-login-tab]');
  const panels = form.querySelectorAll('[data-login-panel]');
  const emailInput = form.querySelector('#email');
  const phoneLocal = form.querySelector('[data-phone-local]');
  const phoneDial = form.querySelector('[data-phone-dial]');

  const tabActive =
    'bg-primary-container text-white shadow-sm';
  const tabInactive =
    'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-low dark:hover:bg-slate-dark-muted';

  function setRequired(el, on) {
    if (!el || el.disabled) return;
    if (on) el.setAttribute('required', '');
    else el.removeAttribute('required');
  }

  function setPanelFields(panel, enabled) {
    panel.querySelectorAll('input, select, textarea').forEach((el) => {
      el.disabled = !enabled;
      if (!enabled) el.removeAttribute('required');
    });
  }

  function activate(method, shouldFocus) {
    if (methodInput) methodInput.value = method;

    tabs.forEach((tab) => {
      const active = tab.dataset.loginTab === method;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.classList.remove(...tabActive.split(' '), ...tabInactive.split(' '));
      tab.classList.add(...(active ? tabActive : tabInactive).split(' '));
    });

    panels.forEach((panel) => {
      const show = panel.dataset.loginPanel === method;
      panel.classList.toggle('hidden', !show);
      setPanelFields(panel, show);
    });

    if (phoneLocal) {
      phoneLocal.setAttribute('autocomplete', method === 'phone' ? 'tel-national' : 'off');
    }
    if (phoneDial) {
      phoneDial.setAttribute('autocomplete', method === 'phone' ? 'tel-country-code' : 'off');
    }
    if (emailInput) {
      emailInput.setAttribute('autocomplete', method === 'email' ? 'username' : 'off');
    }

    setRequired(phoneLocal, method === 'phone');
    setRequired(emailInput, method === 'email');

    if (!shouldFocus) return;
    const focusTarget = method === 'phone' ? phoneLocal : emailInput;
    if (focusTarget && !focusTarget.disabled) focusTarget.focus();
  }

  tabs.forEach((tab) => {
    tab.addEventListener('click', function () {
      activate(tab.dataset.loginTab, true);
    });
  });

  form.addEventListener('submit', function () {
    const method = methodInput ? methodInput.value || 'phone' : 'phone';
    activate(method, false);
  });

  activate(methodInput ? methodInput.value || 'phone' : 'phone', false);
})();
