(function () {
  const form = document.getElementById("reservation-form");
  if (!form) return;

  const currency = form.dataset.currency || "AZN";
  const minLabel = form.dataset.minLabel || "min";
  const packagesSection = document.getElementById("packages-section");
  const servicesSection = document.getElementById("services-section");
  const packagesList = document.getElementById("packages-list");
  const servicesList = document.getElementById("services-list");
  const emptyHint = document.getElementById("offerings-empty");
  const totalEl = document.getElementById("reservation-total");
  const submitBtn = document.getElementById("reservation-submit");
  const bodyTypeRadios = form.querySelectorAll("[data-body-type-radio]");

  let fetchController = null;

  function formatMoney(value) {
    const n = Number(value) || 0;
    return `${n.toFixed(0)} ${currency}`;
  }

  function selectedBodyType() {
    const checked = form.querySelector("[data-body-type-radio]:checked");
    return checked ? checked.value : "";
  }

  function updateTotal() {
    let total = 0;
    const pkg = form.querySelector("[data-package-input]:checked");
    if (pkg) {
      total += Number(pkg.dataset.price) || 0;
    } else {
      form.querySelectorAll("[data-service-input]:checked").forEach((el) => {
        total += Number(el.dataset.price) || 0;
      });
    }
    if (totalEl) totalEl.textContent = formatMoney(total);
  }

  function clearSelections() {
    form.querySelectorAll("[data-package-input]").forEach((el) => {
      el.checked = false;
    });
    form.querySelectorAll("[data-service-input]").forEach((el) => {
      el.checked = false;
    });
    updateTotal();
  }

  function bindSelectionHandlers(root) {
    root.querySelectorAll("[data-package-input]").forEach((el) => {
      el.addEventListener("change", () => {
        if (el.checked) {
          form.querySelectorAll("[data-service-input]").forEach((cb) => {
            cb.checked = false;
          });
        }
        updateTotal();
      });
    });
    root.querySelectorAll("[data-service-input]").forEach((el) => {
      el.addEventListener("change", () => {
        if (el.checked) {
          form.querySelectorAll("[data-package-input]").forEach((rb) => {
            rb.checked = false;
          });
        }
        updateTotal();
      });
    });
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function renderPackage(pkg) {
    const desc = pkg.description
      ? `<span class="block text-sm text-on-surface-variant mt-0.5">${escapeHtml(pkg.description)}</span>`
      : "";
    return `
      <label class="reservation-option flex items-start gap-3 p-3 sm:p-4 rounded-lg border border-outline-variant/50 dark:border-outline-dark bg-surface dark:bg-slate-dark cursor-pointer transition-all">
        <input type="radio" name="package_id" value="${pkg.id}" class="mt-1 w-5 h-5 shrink-0 accent-primary-container" data-package-input data-price="${pkg.price}"/>
        <span class="flex-1 min-w-0">
          <span class="block font-semibold text-on-surface leading-snug">${escapeHtml(pkg.name)}</span>
          ${desc}
          <span class="block text-sm font-bold text-primary-container mt-1 tabular-nums">${formatMoney(pkg.price)} · ${pkg.duration_min} ${minLabel}</span>
        </span>
      </label>`;
  }

  function renderService(svc) {
    const desc = svc.description
      ? `<span class="block text-sm text-on-surface-variant mt-0.5">${escapeHtml(svc.description)}</span>`
      : "";
    return `
      <label class="reservation-option flex items-start gap-3 p-3 sm:p-4 rounded-lg border border-outline-variant/50 dark:border-outline-dark bg-surface dark:bg-slate-dark cursor-pointer transition-all">
        <input type="checkbox" name="service_ids" value="${svc.id}" class="mt-1 w-5 h-5 shrink-0 accent-primary-container" data-service-input data-price="${svc.price}"/>
        <span class="flex-1 min-w-0">
          <span class="block font-semibold text-on-surface leading-snug">${escapeHtml(svc.name)}</span>
          ${desc}
          <span class="block text-sm font-bold text-primary-container mt-1 tabular-nums">${formatMoney(svc.price)} · ${svc.duration_min} ${minLabel}</span>
        </span>
      </label>`;
  }

  function setLoading(loading) {
    if (submitBtn) submitBtn.disabled = loading;
    bodyTypeRadios.forEach((el) => {
      el.disabled = loading;
    });
  }

  async function loadOfferings(bodyType) {
    if (!bodyType) return;
    if (fetchController) fetchController.abort();
    fetchController = new AbortController();
    setLoading(true);
    try {
      const res = await fetch(`/reservation/api/offerings?body_type=${encodeURIComponent(bodyType)}`, {
        signal: fetchController.signal,
        headers: { Accept: "application/json" },
      });
      if (!res.ok) return;
      const data = await res.json();
      clearSelections();

      const packages = data.packages || [];
      const services = data.services || [];

      if (packagesList) {
        packagesList.innerHTML = packages.map(renderPackage).join("");
        bindSelectionHandlers(packagesList);
      }
      if (servicesList) {
        servicesList.innerHTML = services.map(renderService).join("");
        bindSelectionHandlers(servicesList);
      }

      if (packagesSection) packagesSection.hidden = packages.length === 0;
      if (servicesSection) servicesSection.hidden = services.length === 0;
      if (emptyHint) emptyHint.classList.toggle("hidden", packages.length > 0 || services.length > 0);
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error(err);
      }
    } finally {
      setLoading(false);
    }
  }

  bodyTypeRadios.forEach((el) => {
    el.addEventListener("change", () => {
      if (el.checked) loadOfferings(el.value);
    });
  });

  bindSelectionHandlers(form);
  updateTotal();
})();
