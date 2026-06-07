(function () {
  const form = document.getElementById("reservation-form");
  if (!form) return;

  const moneySymbol = form.dataset.moneySymbol || form.dataset.currency || "AZN";
  const moneyDecimals = Number(form.dataset.moneyDecimals) || 2;
  const minLabel = form.dataset.minLabel || "min";
  const offeringsErrorDefault = form.dataset.offeringsError || "";
  const slotsErrorDefault = form.dataset.slotsError || "";

  const packagesSection = document.getElementById("packages-section");
  const servicesSection = document.getElementById("services-section");
  const packagesList = document.getElementById("packages-list");
  const servicesList = document.getElementById("services-list");
  const emptyHint = document.getElementById("offerings-empty");
  const offeringsError = document.getElementById("offerings-error");
  const totalEl = document.getElementById("reservation-total");
  const submitBtn = document.getElementById("reservation-submit");
  const bodyTypeRadios = form.querySelectorAll("[data-body-type-radio]");
  const scheduleSection = document.getElementById("schedule-section");
  const scheduleDate = document.getElementById("schedule_date");
  const scheduleTime = document.getElementById("schedule_time");
  const bayIdInput = document.getElementById("bay_id");
  const slotsGrid = document.getElementById("slots-grid");
  const slotsEmpty = document.getElementById("slots-empty");
  const slotsError = document.getElementById("slots-error");
  const slotsPickDate = document.getElementById("slots-pick-date");
  const slotsLoading = document.getElementById("slots-loading");
  const phoneLocal = form.querySelector("[data-phone-local]");
  const phoneDial = form.querySelector("[data-phone-dial]");
  const phoneFull = form.querySelector("[data-phone-full]");
  const clientNameInput = document.getElementById("client_name");
  const clientNameDialog = document.getElementById("client-name-dialog");
  const clientNameField = document.getElementById("client_name_input");
  const clientNameError = document.getElementById("client-name-error");
  const clientNameConfirm = document.getElementById("client-name-confirm");

  let offeringsController = null;
  let slotsController = null;
  let phoneLookupController = null;
  let phoneLookupStatus = null;
  let lastLookedUpPhone = "";
  let phoneLookupTimer = null;

  function formatMoney(value) {
    const n = Number(value) || 0;
    const fixed = n.toFixed(moneyDecimals);
    const parts = fixed.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return `${parts.join(".")}\u00a0${moneySymbol}`;
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

  function hasValidPhone() {
    if (!phoneLocal) return true;
    return Boolean((phoneLocal.value || "").replace(/\D/g, "").length >= 7);
  }

  function currentFullPhone() {
    if (phoneFull && phoneFull.value) return phoneFull.value;
    const dial = phoneDial ? phoneDial.value : "";
    const local = phoneLocal ? phoneLocal.value : "";
    const dialDigits = (dial || "").replace(/\D/g, "");
    let localDigits = (local || "").replace(/\D/g, "");
    if (!dialDigits || !localDigits) return "";
    while (localDigits.length > 1 && localDigits.startsWith("0")) {
      localDigits = localDigits.slice(1);
    }
    return `+${dialDigits}${localDigits}`;
  }

  function resetPhoneLookup() {
    phoneLookupStatus = null;
    lastLookedUpPhone = "";
    if (clientNameInput) clientNameInput.value = "";
  }

  function needsClientName() {
    return phoneLookupStatus === "not_found" && !(clientNameInput && clientNameInput.value.trim());
  }

  function phoneLookupReady() {
    if (!hasValidPhone()) return false;
    if (phoneLookupStatus === "found") return true;
    if (phoneLookupStatus === "not_found") {
      return Boolean(clientNameInput && clientNameInput.value.trim());
    }
    return false;
  }

  function showClientNameDialog() {
    if (!clientNameDialog || typeof clientNameDialog.showModal !== "function") return;
    if (clientNameField) {
      clientNameField.value = clientNameInput ? clientNameInput.value.trim() : "";
    }
    if (clientNameError) clientNameError.classList.add("hidden");
    clientNameDialog.showModal();
    if (clientNameField) clientNameField.focus();
  }

  function hideClientNameDialog() {
    if (clientNameDialog && clientNameDialog.open) clientNameDialog.close();
  }

  function confirmClientName() {
    const name = clientNameField ? clientNameField.value.trim() : "";
    if (!name) {
      if (clientNameError) clientNameError.classList.remove("hidden");
      if (clientNameField) clientNameField.focus();
      return;
    }
    if (clientNameInput) clientNameInput.value = name;
    if (clientNameError) clientNameError.classList.add("hidden");
    hideClientNameDialog();
    updateSubmitState();
  }

  async function lookupClientByPhone(forceModal) {
    if (!hasValidPhone()) {
      resetPhoneLookup();
      updateSubmitState();
      return;
    }

    const phone = currentFullPhone();
    if (!phone) {
      resetPhoneLookup();
      updateSubmitState();
      return;
    }

    if (!forceModal && phone === lastLookedUpPhone && phoneLookupStatus) {
      updateSubmitState();
      return;
    }

    if (phone !== lastLookedUpPhone) {
      if (clientNameInput) clientNameInput.value = "";
      phoneLookupStatus = null;
    }

    if (phoneLookupController) phoneLookupController.abort();
    phoneLookupController = new AbortController();
    phoneLookupStatus = "loading";

    try {
      const params = new URLSearchParams({ phone });
      const res = await fetch(`/reservation/api/client-lookup?${params.toString()}`, {
        signal: phoneLookupController.signal,
        headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        phoneLookupStatus = "error";
        lastLookedUpPhone = phone;
        updateSubmitState();
        return;
      }
      const data = await res.json();
      lastLookedUpPhone = phone;
      phoneLookupStatus = data.found ? "found" : "not_found";
      if (data.found) {
        if (clientNameInput) clientNameInput.value = "";
      } else if (forceModal || !(clientNameInput && clientNameInput.value.trim())) {
        showClientNameDialog();
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error(err);
        phoneLookupStatus = "error";
        lastLookedUpPhone = phone;
      }
    } finally {
      updateSubmitState();
    }
  }

  function schedulePhoneLookup(forceModal) {
    if (phoneLookupTimer) clearTimeout(phoneLookupTimer);
    phoneLookupTimer = setTimeout(() => lookupClientByPhone(forceModal), 400);
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

  function hideOfferingsError() {
    if (offeringsError) {
      offeringsError.textContent = "";
      offeringsError.classList.add("hidden");
    }
    if (emptyHint) emptyHint.classList.remove("hidden");
  }

  function showOfferingsError(message) {
    if (packagesList) packagesList.innerHTML = "";
    if (servicesList) servicesList.innerHTML = "";
    if (packagesSection) packagesSection.hidden = true;
    if (servicesSection) servicesSection.hidden = true;
    if (emptyHint) emptyHint.classList.add("hidden");
    if (offeringsError) {
      offeringsError.textContent = message || offeringsErrorDefault;
      offeringsError.classList.remove("hidden");
    }
    clearServiceSelections();
  }

  function hideSlotsMessages() {
    if (slotsEmpty) slotsEmpty.classList.add("hidden");
    if (slotsError) {
      slotsError.textContent = "";
      slotsError.classList.add("hidden");
    }
  }

  function showSlotsError(message) {
    hideSlotsMessages();
    if (slotsGrid) slotsGrid.innerHTML = "";
    if (slotsPickDate) slotsPickDate.classList.add("hidden");
    if (slotsError) {
      slotsError.textContent = message || slotsErrorDefault;
      slotsError.classList.remove("hidden");
    }
  }

  function showSlotsEmpty() {
    hideSlotsMessages();
    if (slotsGrid) slotsGrid.innerHTML = "";
    if (slotsPickDate) slotsPickDate.classList.add("hidden");
    if (slotsEmpty) slotsEmpty.classList.remove("hidden");
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
      hideSlotsMessages();
      if (slotsPickDate) slotsPickDate.classList.remove("hidden");
    }
    updateSubmitState();
  }

  function updateSubmitState() {
    if (!submitBtn) return;
    const ready =
      hasServiceSelection() &&
      hasValidPhone() &&
      phoneLookupReady() &&
      scheduleDate &&
      scheduleDate.value &&
      scheduleTime &&
      scheduleTime.value &&
      bayIdInput &&
      bayIdInput.value;
    submitBtn.disabled = !ready;
  }

  function handleSelectionChange(target) {
    if (target.matches("[data-package-input]") && target.checked) {
      form.querySelectorAll("[data-service-input]").forEach((cb) => {
        cb.checked = false;
      });
    }
    if (target.matches("[data-service-input]") && target.checked) {
      form.querySelectorAll("[data-package-input]").forEach((rb) => {
        rb.checked = false;
      });
    }
    updateTotal();
    clearSlotSelection();
    updateScheduleVisibility();
    loadSlots();
  }

  function selectSlotButton(btn) {
    if (!slotsGrid || !btn) return;
    slotsGrid.querySelectorAll("[data-slot-btn]").forEach((el) => {
      el.classList.remove("border-primary-container", "bg-primary-container/10", "text-primary-container");
      el.classList.add("border-outline-variant/50", "dark:border-outline-dark", "text-on-surface");
    });
    btn.classList.add("border-primary-container", "bg-primary-container/10", "text-primary-container");
    btn.classList.remove("border-outline-variant/50", "dark:border-outline-dark", "text-on-surface");
    if (scheduleTime) scheduleTime.value = btn.dataset.time || "";
    if (bayIdInput) bayIdInput.value = btn.dataset.bayId || "";
    updateSubmitState();
  }

  function restoreSlotSelection(restoreSlot) {
    if (!restoreSlot || !slotsGrid) return;
    const buttons = slotsGrid.querySelectorAll("[data-slot-btn]");
    for (const btn of buttons) {
      if (btn.dataset.time === restoreSlot.time && btn.dataset.bayId === String(restoreSlot.bayId)) {
        selectSlotButton(btn);
        return;
      }
    }
    if (scheduleTime) scheduleTime.value = "";
    if (bayIdInput) bayIdInput.value = "";
    updateSubmitState();
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
    hideOfferingsError();
    try {
      const res = await fetch(`/reservation/api/offerings?body_type=${encodeURIComponent(bodyType)}`, {
        signal: offeringsController.signal,
        headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        let message = offeringsErrorDefault;
        try {
          const errData = await res.json();
          if (errData.message) message = errData.message;
        } catch (_) {
          /* ignore */
        }
        showOfferingsError(message);
        return;
      }
      const data = await res.json();
      clearServiceSelections();

      const packages = data.packages || [];
      const services = data.services || [];

      if (packagesList) packagesList.innerHTML = packages.map(renderPackage).join("");
      if (servicesList) servicesList.innerHTML = services.map(renderService).join("");

      if (packagesSection) packagesSection.hidden = packages.length === 0;
      if (servicesSection) servicesSection.hidden = services.length === 0;
      if (emptyHint) emptyHint.classList.toggle("hidden", packages.length > 0 || services.length > 0);
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error(err);
        showOfferingsError(offeringsErrorDefault);
      }
    } finally {
      setOfferingsLoading(false);
    }
  }

  async function loadSlots(restoreSlot) {
    if (!hasServiceSelection()) return;
    const bodyType = selectedBodyType();
    const dateValue = scheduleDate ? scheduleDate.value : "";
    if (!bodyType || !dateValue) {
      if (slotsPickDate) slotsPickDate.classList.remove("hidden");
      hideSlotsMessages();
      if (slotsGrid) slotsGrid.innerHTML = "";
      clearSlotSelection();
      return;
    }

    if (slotsController) slotsController.abort();
    slotsController = new AbortController();
    setSlotsLoading(true);
    if (!restoreSlot) clearSlotSelection();
    hideSlotsMessages();

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
        let message = slotsErrorDefault;
        try {
          const errData = await res.json();
          if (errData.message) message = errData.message;
        } catch (_) {
          /* ignore */
        }
        showSlotsError(message);
        return;
      }
      const data = await res.json();
      const slots = data.slots || [];
      if (slotsGrid) slotsGrid.innerHTML = slots.map(renderSlotButton).join("");
      if (slots.length === 0) {
        showSlotsEmpty();
      } else if (slotsPickDate) {
        slotsPickDate.classList.add("hidden");
      }
      if (restoreSlot) restoreSlotSelection(restoreSlot);
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error(err);
        showSlotsError(slotsErrorDefault);
      }
    } finally {
      setSlotsLoading(false);
      updateSubmitState();
    }
  }

  form.addEventListener("change", (e) => {
    const target = e.target;
    if (target.matches("[data-package-input], [data-service-input]")) {
      handleSelectionChange(target);
    }
  });

  if (slotsGrid) {
    slotsGrid.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-slot-btn]");
      if (btn) selectSlotButton(btn);
    });
  }

  bodyTypeRadios.forEach((el) => {
    el.addEventListener("change", () => {
      if (el.checked) loadOfferings(el.value);
    });
  });

  if (scheduleDate) {
    scheduleDate.addEventListener("change", () => loadSlots());
  }

  if (phoneLocal) {
    phoneLocal.addEventListener("input", () => {
      if (phoneLookupTimer) clearTimeout(phoneLookupTimer);
      const phone = currentFullPhone();
      if (phone && phone !== lastLookedUpPhone) {
        phoneLookupStatus = null;
        if (clientNameInput) clientNameInput.value = "";
      }
      updateSubmitState();
      if (hasValidPhone()) schedulePhoneLookup(false);
    });
    phoneLocal.addEventListener("change", () => {
      if (hasValidPhone()) lookupClientByPhone(true);
      else {
        resetPhoneLookup();
        updateSubmitState();
      }
    });
    phoneLocal.addEventListener("blur", () => {
      if (hasValidPhone()) lookupClientByPhone(true);
    });
  }

  if (phoneDial) {
    phoneDial.addEventListener("change", () => {
      resetPhoneLookup();
      updateSubmitState();
      if (hasValidPhone()) schedulePhoneLookup(true);
    });
  }

  if (clientNameConfirm) {
    clientNameConfirm.addEventListener("click", confirmClientName);
  }

  if (clientNameField) {
    clientNameField.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        confirmClientName();
      }
    });
  }

  if (clientNameDialog) {
    document.querySelectorAll(".client-name-dialog-close").forEach((btn) => {
      btn.addEventListener("click", hideClientNameDialog);
    });
    clientNameDialog.addEventListener("cancel", (e) => {
      e.preventDefault();
      hideClientNameDialog();
    });
  }

  form.addEventListener("submit", (e) => {
    if (needsClientName()) {
      e.preventDefault();
      showClientNameDialog();
    }
  });

  const pendingSlotRestore =
    scheduleTime?.value && bayIdInput?.value
      ? { time: scheduleTime.value, bayId: bayIdInput.value }
      : null;

  updateTotal();
  updateScheduleVisibility();
  if (submitBtn) submitBtn.disabled = true;

  if (hasServiceSelection() && scheduleDate?.value) {
    loadSlots(pendingSlotRestore);
  } else {
    updateSubmitState();
  }

  if (hasValidPhone()) {
    if (clientNameInput && clientNameInput.value.trim()) {
      lastLookedUpPhone = currentFullPhone();
      phoneLookupStatus = "not_found";
      updateSubmitState();
    } else {
      lookupClientByPhone(false);
    }
  }
})();
