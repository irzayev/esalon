(function () {
  function sync(select) {
    const opt = select.options[select.selectedIndex];
    const status = opt && opt.dataset.status;
    if (status) {
      select.dataset.status = status;
    }
  }

  function init() {
    document.querySelectorAll('[data-status-select]').forEach(function (select) {
      sync(select);
      select.addEventListener('change', function () {
        sync(select);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
