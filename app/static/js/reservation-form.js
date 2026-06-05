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
  const scheduleSection = document.getElementById("schedule-section");
  const scheduleDate = document.getElementById("schedule_date");
  const scheduleTime = document.getElementById("schedule_time");
  const bayIdInput = document.getElementById("bay_id");
  const slotsGrid = document.getElementById("slots-grid");
  const slotsEmpty = document.getElementById("slots-empty");
  const slotsPickDate = document.getElementById("slots-pick-date");
  const slotsLoading = document.getElementById("slots-loading");

  let offeringsController = null;
  let slotsController = null;

  function formatMoney(value) {
    const n = Number(value) || 0;
    return `${n.toFixed(0)} ${currency}`;
  }

  function selectedBodyType() {
    const checked = form.querySelector("[data-body-type-radio]:checked");
    return checked ? checked.value : "";
  }

  function selectedPackageId() {
    const pkg = form.querySelector("[data-package-input]:checked");
    return pkg ? pkg.value : "";
  }

  function selectedServiceIds() {
    return Array.from(form.querySelectorAll("[data-service-input]:checked")).map((el) => el.value);
  }

  function hasServiceSelection() {
    return Boolean(selectedPackageId()) || selectedServiceIds().length > 0;
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

  function clearServiceSelections() {
    form.querySelectorAll("[data-package-input]").forEach((el) => {
      el.checked = false;
    });
    form.querySelectorAll("[data-service-input]").forEach((el) => {
      el.checked = false;
    });
    updateTotal();
    clearSlotSelection();
    updateScheduleVisibility();
  }

  function clearSlotSelection() {
    if (scheduleTime) scheduleTime.value = "";
    if (bayIdInput) bayIdInput.value = "";
    if (slotsGrid) {
      slotsGrid.querySelectorAll("[data-slot-btn]").forEach((btn) => {
        btn.classList.remove("border-primary-container", "bg-primary-container/10", "text-primary-container");
        btn.classList.add("border-outline-variant/50", "dark:border-outline-dark", "text-on-surface");
      });
    }
    updateSubmitState();
  }

  function updateScheduleVisibility() {
    if (!scheduleSection) return;
    scheduleSection.classList.toggle("hidden", !hasServiceSelection());
    if (!hasServiceSelection()) {
      clearSlotSelection();
      if (slotsGrid) slotsGrid.innerHTML = "";
      if (slotsEmpty) slotsEmpty.classList.add("hidden");
      if (slotsPickDate) slotsPickDate.classList.remove("hidden");
    }
    updateSubmitState();
  }

  function updateSubmitState() {
    if (!submitBtn) return;
    const ready =
      hasServiceSelection() &&
      scheduleDate &&
      scheduleDate.value &&
      scheduleTime &&
      scheduleTime.value &&
      bayIdInput &&
      bayIdInput.value;
    submitBtn.disabled = !ready;
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
        clearSlotSelection();
        updateScheduleVisibility();
        loadSlots();
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
        clearSlotSelection();
        updateScheduleVisibility();
        loadSlots();
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

  function renderSlotButton(slot) {
    return `
      <button type="button"
              data-slot-btn
              data-time="${escapeHtml(slot.time)}"
              data-bay-id="${slot.bay_id}"
              class="min-h-[44px] px-2 py-2.5 rounded-lg border border-outline-variant/50 dark:border-outline-dark bg-surface dark:bg-slate-dark text-sm font-semibold tabular-nums text-on-surface transition-all active:scale-[0.98] hover:border-primary-container">
        ${escapeHtml(slot.time)}
      </button>`;
  }

  function bindSlotButtons() {
    if (!slotsGrid) return;
    slotsGrid.querySelectorAll("[data-slot-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        slotsGrid.querySelectorAll("[data-slot-btn]").forEach((el) => {
          el.classList.remove("border-primary-container", "bg-primary-container/10", "text-primary-container");
          el.classList.add("border-outline-variant/50", "dark:border-outline-dark", "text-on-surface");
        });
        btn.classList.add("border-primary-container", "bg-primary-container/10", "text-primary-container");
        btn.classList.remove("border-outline-variant/50", "dark:border-outline-dark", "text-on-surface");
        if (scheduleTime) scheduleTime.value = btn.dataset.time || "";
        if (bayIdInput) bayIdInput.value = btn.dataset.bayId || "";
        updateSubmitState();
      });
    });
  }

  function setOfferingsLoading(loading) {
    bodyTypeRadios.forEach((el) => {
      el.disabled = loading;
    });
  }

  function setSlotsLoading(loading) {
    if (slotsLoading) slotsLoading.classList.toggle("hidden", !loading);
  }

  async function loadOfferings(bodyType) {
    if (!bodyType) return;
    if (offeringsController) offeringsController.abort();
    offeringsController = new AbortController();
    setOfferingsLoading(true);
    try {
      const res = await fetch(`/reservation/api/offerings?body_type=${encodeURIComponent(bodyType)}`, {
        signal: offeringsController.signal,
        headers: { Accept: "application/json" },
      });
      if (!res.ok) return;
      const data = await res.json();
      clearServiceSelections();

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
      setOfferingsLoading(false);
    }
  }

  async function loadSlots() {
    if (!hasServiceSelection()) return;
    const bodyType = selectedBodyType();
    const dateValue = scheduleDate ? scheduleDate.value : "";
    if (!bodyType || !dateValue) {
      if (slotsPickDate) slotsPickDate.classList.remove("hidden");
      if (slotsEmpty) slotsEmpty.classList.add("hidden");
      if (slotsGrid) slotsGrid.innerHTML = "";
      clearSlotSelection();
      return;
    }

    if (slotsController) slotsController.abort();
    slotsController = new AbortController();
    setSlotsLoading(true);
    clearSlotSelection();

    const params = new URLSearchParams({
      body_type: bodyType,
      date: dateValue,
    });
    const packageId = selectedPackageId();
    if (packageId) {
      params.set("package_id", packageId);
    } else {
      selectedServiceIds().forEach((id) => params.append("service_ids", id));
    }

    try {
      const res = await fetch(`/reservation/api/slots?${params.toString()}`, {
        signal: slotsController.signal,
        headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        if (slotsGrid) slotsGrid.innerHTML = "";
        if (slotsEmpty) slotsEmpty.classList.remove("hidden");
        if (slotsPickDate) slotsPickDate.classList.add("hidden");
        return;
      }
      const data = await res.json();
      const slots = data.slots || [];
      if (slotsGrid) slotsGrid.innerHTML = slots.map(renderSlotButton).join("");
      bindSlotButtons();
      if (slotsEmpty) slotsEmpty.classList.toggle("hidden", slots.length > 0);
      if (slotsPickDate) slotsPickDate.classList.add("hidden");
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error(err);
      }
    } finally {
      setSlotsLoading(false);
      updateSubmitState();
    }
  }

  bodyTypeRadios.forEach((el) => {
    el.addEventListener("change", () => {
      if (el.checked) loadOfferings(el.value);
    });
  });

  if (scheduleDate) {
    scheduleDate.addEventListener("change", loadSlots);
  }

  bindSelectionHandlers(form);
  updateTotal();
  updateScheduleVisibility();
  submitBtn.disabled = true;
})();
