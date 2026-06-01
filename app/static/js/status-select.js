/**
 * Status picker with colored badges (replaces native <select> for order status).
 */
(function () {
  function closeAll(except) {
    document.querySelectorAll('[data-status-select]').forEach(function (root) {
      if (except && root === except) return;
      var menu = root.querySelector('[data-status-select-menu]');
      var trigger = root.querySelector('[data-status-select-trigger]');
      if (menu) menu.hidden = true;
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
  }

  function selectOption(root, option) {
    if (!option || option.classList.contains('ui-status-select__option--disabled')) return;
    var input = root.querySelector('[data-status-select-input]');
    var badge = root.querySelector('[data-status-select-badge]');
    var value = option.getAttribute('data-value');
    var label = option.getAttribute('data-label');
    var cls = option.getAttribute('data-cls');
    if (!input || !badge || !value) return;

    input.value = value;
    badge.textContent = label;
    badge.className = 'ui-badge ui-badge--status ' + cls;

    root.querySelectorAll('[data-status-select-menu] [role="option"]').forEach(function (opt) {
      var selected = opt === option;
      opt.classList.toggle('ui-status-select__option--selected', selected);
      opt.setAttribute('aria-selected', selected ? 'true' : 'false');
    });

    closeAll();
  }

  function bind(root) {
    var trigger = root.querySelector('[data-status-select-trigger]');
    var menu = root.querySelector('[data-status-select-menu]');
    if (!trigger || !menu) return;

    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      var willOpen = menu.hidden;
      closeAll();
      if (willOpen) {
        menu.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
      }
    });

    menu.querySelectorAll('[role="option"]').forEach(function (option) {
      option.addEventListener('click', function (e) {
        e.stopPropagation();
        selectOption(root, option);
      });
      option.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectOption(root, option);
        }
      });
    });
  }

  document.addEventListener('click', function () {
    closeAll();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll();
  });

  document.querySelectorAll('[data-status-select]').forEach(bind);
})();
