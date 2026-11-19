/* Shared IBM Carbon v11 UI core, REST API client, RBAC, Global Device Search, SideNav Rail, DataTable Toolbar, i18n, and modals for aethernms */

(function () {
  "use strict";

  const shared = {
    meta: null,
    i18n: { catalog: {}, available_languages: [], effective_language: "en" },
    settings: null,
    modalStack: [],
    confirmCallback: null,
    onReloadCallback: null,
  };

  const $ = (id) => document.getElementById(id);

  // Hydrate SSR translation catalog immediately so dynamic UI helpers have strings before async fetches settle.
  try {
    const initEl = $("anms-initial-i18n");
    if (initEl && initEl.textContent) {
      const parsed = JSON.parse(initEl.textContent);
      if (parsed && typeof parsed === "object") {
        shared.i18n = parsed;
      }
    }
  } catch (_e) {}

  const FALLBACK_ICONS = {
    "trash-can": '<path d="M12 12h2v12h-2zm6 0h2v12h-2z"/><path d="M4 6v2h2v20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8h2V6zm4 22V8h16v20zm4-26h8v2h-8z"/>',
    edit: '<path d="M2 26h28v2H2zM25.4 9c.8-.8.8-2 0-2.8l-3.6-3.6c-.8-.8-2-.8-2.8 0l-15 15V24h6.4l15-15zm-5-5L24 7.6l-3 3L17.4 7l3-3zM6 22v-3.6l10-10l3.6 3.6l-10 10H6z"/>',
    view: '<path d="M30.94 15.66A16.69 16.69 0 0 0 16 5A16.69 16.69 0 0 0 1.06 15.66a1 1 0 0 0 0 .68A16.69 16.69 0 0 0 16 27a16.69 16.69 0 0 0 14.94-10.66a1 1 0 0 0 0-.68ZM16 25c-5.3 0-10.9-3.93-12.93-9C5.1 10.93 10.7 7 16 7s10.9 3.93 12.93 9C26.9 21.07 21.3 25 16 25Z"/><path d="M16 10a6 6 0 1 0 6 6a6 6 0 0 0-6-6Zm0 10a4 4 0 1 1 4-4a4 4 0 0 1-4 4Z"/>',
    renew: '<path d="M12 10H6.78A11 11 0 0 1 27 16h2A13 13 0 0 0 6 7.68V4H4v8h8zm8 12h5.22A11 11 0 0 1 5 16H3a13 13 0 0 0 23 8.32V28h2v-8h-8z"/>',
    "stop-outline": '<path d="M16 4A12 12 0 1 1 4 16A12 12 0 0 1 16 4m0-2a14 14 0 1 0 14 14A14 14 0 0 0 16 2z"/><path d="M12 12h8v8h-8z"/>',
    document: '<path d="m25.7 9.3l-7-7c-.2-.2-.4-.3-.7-.3H8c-1.1 0-2 .9-2 2v24c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V10c0-.3-.1-.5-.3-.7zM18 4.4l5.6 5.6H18V4.4zM24 28H8V4h8v6c0 1.1.9 2 2 2h6v16z"/><path d="M10 22h12v2H10zm0-6h12v2H10z"/>',
    "error-filled": '<path d="M16 2C8.2 2 2 8.2 2 16s6.2 14 14 14s14-6.2 14-14S23.8 2 16 2zm5.4 21L9 10.6L10.6 9L23 21.4L21.4 23z"/>',
    "page-first": '<path d="M14 16L24 6l1.4 1.4L16.8 16l8.6 8.6L24 26zM8 4h2v24H8z"/>',
    "page-last": '<path d="M18 16L8 26l-1.4-1.4l8.6-8.6l-8.6-8.6L8 6zM22 4h2v24h-2z"/>',
    "chevron-left": '<path d="M10 16L20 6l1.4 1.4l-8.6 8.6l8.6 8.6L20 26z"/>',
    "chevron-right": '<path d="M22 16L12 26l-1.4-1.4l8.6-8.6l-8.6-8.6L12 6z"/>',
    close: '<path d="M24 9.4L22.6 8L16 14.6L9.4 8L8 9.4l6.6 6.6L8 22.6L9.4 24l6.6-6.6l6.6 6.6l1.4-1.4l-6.6-6.6L24 9.4z"/>',
  };

  function icon(name, size) {
    const sz = size || 16;
    const map = (shared.meta && shared.meta.icons) || {};
    const body = map[name] || FALLBACK_ICONS[name] || "";
    return `<svg viewBox="0 0 32 32" width="${sz}" height="${sz}" fill="currentColor" focusable="false" aria-hidden="true">${body}</svg>`;
  }

  function hasPermission(perm) {
    if (!perm) return true;
    const perms = (shared.meta && shared.meta.permissions) || [];
    return perms.includes(perm);
  }

  function t(key, vars) {
    let text = (shared.i18n && shared.i18n.catalog && shared.i18n.catalog[key]) || key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        text = text.replaceAll(`{${k}}`, String(v));
      }
    }
    return text;
  }

  function platformLabel(key) {
    if (!key) return "-";
    const map = (shared.meta && shared.meta.platform_labels) || {};
    return map[key] || key;
  }

  function platformOptions(keys) {
    return (keys || [])
      .map((k) => ({ value: k, label: platformLabel(k) }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }

  function escHtml(str) {
    return String(str == null ? "" : str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function highlightCliHtml(text) {
    const lines = String(text || "").split(/\r?\n/);
    return lines
      .map((line) => {
        if (line.trimStart().startsWith("!")) {
          return `<span class="cli-comment">${escHtml(line)}</span>`;
        }
        let out = "";
        let i = 0;
        while (i < line.length) {
          if (line[i] === "$" && line[i + 1] === "{") {
            let depth = 1;
            let j = i + 2;
            while (j < line.length && depth > 0) {
              if (line[j] === "\\" && j + 1 < line.length) {
                j += 2;
                continue;
              }
              if (line[j] === "{") depth++;
              else if (line[j] === "}") depth--;
              j++;
            }
            if (depth === 0) {
              out += `<span class="cli-var">${escHtml(line.slice(i, j))}</span>`;
              i = j;
              continue;
            }
          }
          out += escHtml(line[i]);
          i++;
        }
        return out;
      })
      .join("\n");
  }

  function toast(msg, kind) {
    const box = $("toast-container");
    if (!box) return;
    const el = document.createElement("div");
    el.className = `toast-item ${kind || ""}`;
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  function redirectToLogin() {
    const next = encodeURIComponent(window.location.pathname || "/");
    window.location.href = next && next !== "%2F" ? `/login?next=${next}` : "/login";
  }

  async function api(path, opts) {
    const options = Object.assign({ headers: {} }, opts || {});
    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    const res = await fetch(path, options);
    const ctype = (res.headers.get("Content-Type") || "").toLowerCase();
    const data = ctype.includes("application/json") ? await res.json() : await res.text();
    if (res.status === 503 && data && data.setup_required) {
      window.location.href = "/setup";
      throw new Error("Initial setup required");
    }
    if (res.status === 401 || (res.status === 403 && data && data.auth_required)) {
      redirectToLogin();
      throw new Error("Authentication required");
    }
    if (!res.ok) {
      const msg = (data && data.error) || `HTTP ${res.status}`;
      const err = new Error(msg);
      err.errors = (data && data.errors) || [msg];
      throw err;
    }
    return data;
  }

  function applyTheme(mode) {
    let eff = (mode || "auto").toLowerCase();
    document.documentElement.setAttribute("data-theme-mode", eff);
    if (eff === "auto") {
      const prefersDark =
        window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      eff = prefersDark ? "dark" : "light";
    }
    const theme = eff === "dark" ? "g100" : "white";
    document.documentElement.setAttribute("data-carbon-theme", theme);
    document.documentElement.className = `cds--${theme}`;
  }

  function applyI18nDom() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
      el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria-label")));
    });
    const pageKey = document.documentElement.getAttribute("data-page-title");
    if (pageKey) {
      document.title = `${t(pageKey)} - aether`;
    }
  }

  function statusTagHtml(status) {
    const s = String(status || "Unknown");
    if (s === "Success" || s === "Up" || s === "Active") {
      return `<span class="cds--tag cds--tag--green">${escHtml(t(s))}</span>`;
    }
    if (s === "Failed" || s === "Down" || s === "Disabled") {
      return `<span class="cds--tag cds--tag--red">${escHtml(t(s))}</span>`;
    }
    if (s === "Running") {
      return `<span class="cds--tag cds--tag--blue">${escHtml(t(s))}</span>`;
    }
    return `<span class="cds--tag cds--tag--gray">${escHtml(t(s))}</span>`;
  }

  function fillSelect(el, options, keepValue) {
    if (!el) return;
    const prev = keepValue ? el.value : null;
    el.innerHTML = options
      .map((opt) => {
        const val = typeof opt === "string" ? opt : opt.value;
        const lbl = typeof opt === "string" ? opt : opt.label;
        return `<option value="${escHtml(val)}">${escHtml(lbl)}</option>`;
      })
      .join("");
    if (prev !== null && Array.from(el.options).some((o) => o.value === prev)) {
      el.value = prev;
    }
  }

  // ---------- Modal Manager (syncs .open and Carbon .is-visible; Esc closes topmost modal) ----------
  function openModal(id) {
    const el = $(id);
    if (!el) return;
    el.classList.add("open", "is-visible");
    shared.modalStack = shared.modalStack.filter((m) => m !== id);
    shared.modalStack.push(id);
  }

  function closeModal(id) {
    const el = $(id);
    if (el) el.classList.remove("open", "is-visible");
    shared.modalStack = shared.modalStack.filter((m) => m !== id);
  }

  function bindGlobalModalControls() {
    document.querySelectorAll(".cds--modal-backdrop").forEach((backdrop) => {
      backdrop.querySelectorAll("[data-modal-cancel]").forEach((btn) => {
        btn.addEventListener("click", () => closeModal(backdrop.id));
      });
    });

    document.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape" || shared.modalStack.length === 0) return;
      const topId = shared.modalStack[shared.modalStack.length - 1];
      const modal = $(topId);
      if (!modal) return;
      ev.preventDefault();
      const cancelBtn = modal.querySelector("[data-modal-cancel]");
      if (cancelBtn) cancelBtn.click();
      else closeModal(topId);
    });
  }

  function showConfirm(title, message, onConfirm, okLabel, isDanger = true) {
    $("confirm-title").textContent = title;
    $("confirm-message").textContent = message;
    const okBtn = $("confirm-ok-btn");
    okBtn.textContent = okLabel || t("Confirm");
    okBtn.className = `cds--btn ${isDanger ? "cds--btn--danger" : "cds--btn--primary"}`;
    shared.confirmCallback = onConfirm;
    openModal("modal-confirm");
  }

  // ---------- Reusable Carbon DataTable Toolbar + Popover Filter Controller ----------
  function wireDataTableToolbar(cfg) {
    const searchEl = $(cfg.searchInputId);
    const clearEl = cfg.searchClearId ? $(cfg.searchClearId) : null;
    const filterBtn = cfg.filterBtnId ? $(cfg.filterBtnId) : null;
    const filterBadge = cfg.filterBadgeId ? $(cfg.filterBadgeId) : null;
    const popoverEl = cfg.popoverId ? $(cfg.popoverId) : null;
    const applyBtn = cfg.applyBtnId ? $(cfg.applyBtnId) : null;
    const resetBtn = cfg.resetBtnId ? $(cfg.resetBtnId) : null;
    const chipsEl = cfg.chipsContainerId ? $(cfg.chipsContainerId) : null;
    const fields = cfg.fields || [];

    function updateClearBtn() {
      if (clearEl && searchEl) {
        clearEl.classList.toggle("hidden", !searchEl.value);
      }
    }

    function renderChips() {
      const active = [];
      fields.forEach((f) => {
        const el = $(f.id);
        if (!el) return;
        const val = String(el.value || "").trim();
        const def = String(f.defaultVal != null ? f.defaultVal : "");
        if (val && val !== def) {
          const displayVal = f.formatValue ? f.formatValue(val, el) : val;
          active.push({ field: f, val, displayVal });
        }
      });

      if (filterBadge) {
        filterBadge.textContent = String(active.length);
        filterBadge.classList.toggle("hidden", active.length === 0);
      }
      if (!chipsEl) return;

      const searchVal = searchEl ? searchEl.value.trim() : "";
      if (!active.length && !searchVal) {
        chipsEl.innerHTML = "";
        chipsEl.classList.add("hidden");
        return;
      }

      const chipsHtml = active
        .map(
          (item) => `
          <span class="anms-filter-chip" data-fid="${escHtml(item.field.id)}">
            <span>${escHtml(t(item.field.labelKey))}: <strong>${escHtml(item.displayVal)}</strong></span>
            <button type="button" class="anms-chip-remove" data-fid="${escHtml(item.field.id)}" title="${escHtml(t("Clear"))}">
              ${icon("close", 12)}
            </button>
          </span>`
        )
        .join("");

      const clearAllHtml = `<button type="button" class="anms-filter-clear-all">${escHtml(t("Clear Filters"))}</button>`;
      chipsEl.innerHTML = chipsHtml + clearAllHtml;
      chipsEl.classList.remove("hidden");

      chipsEl.querySelectorAll(".anms-chip-remove").forEach((btn) => {
        btn.addEventListener("click", () => {
          const fid = btn.getAttribute("data-fid");
          const spec = fields.find((f) => f.id === fid);
          const el = $(fid);
          if (el && spec) {
            el.value = spec.defaultVal != null ? String(spec.defaultVal) : "";
          }
          renderChips();
          if (cfg.onChange) cfg.onChange();
        });
      });

      const clearAllBtn = chipsEl.querySelector(".anms-filter-clear-all");
      if (clearAllBtn) {
        clearAllBtn.addEventListener("click", () => resetAll());
      }
    }

    function resetAll() {
      if (searchEl) searchEl.value = "";
      updateClearBtn();
      fields.forEach((f) => {
        const el = $(f.id);
        if (el) el.value = f.defaultVal != null ? String(f.defaultVal) : "";
      });
      if (popoverEl) popoverEl.classList.add("hidden");
      if (filterBtn) filterBtn.classList.remove("active");
      renderChips();
      if (cfg.onChange) cfg.onChange();
    }

    if (searchEl) {
      searchEl.addEventListener("input", () => {
        updateClearBtn();
        renderChips();
        if (cfg.onChange) cfg.onChange();
      });
    }
    if (clearEl && searchEl) {
      clearEl.addEventListener("click", () => {
        searchEl.value = "";
        updateClearBtn();
        renderChips();
        if (cfg.onChange) cfg.onChange();
        searchEl.focus();
      });
    }

    if (filterBtn && popoverEl) {
      filterBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const willOpen = popoverEl.classList.contains("hidden");
        popoverEl.classList.toggle("hidden", !willOpen);
        filterBtn.classList.toggle("active", willOpen);
      });

      document.addEventListener("click", (ev) => {
        if (
          !popoverEl.classList.contains("hidden") &&
          !popoverEl.contains(ev.target) &&
          !filterBtn.contains(ev.target)
        ) {
          popoverEl.classList.add("hidden");
          filterBtn.classList.remove("active");
        }
      });

      document.addEventListener("keydown", (ev) => {
        if (
          ev.key === "Escape" &&
          shared.modalStack.length === 0 &&
          !popoverEl.classList.contains("hidden")
        ) {
          popoverEl.classList.add("hidden");
          filterBtn.classList.remove("active");
        }
      });
    }

    if (applyBtn) {
      applyBtn.addEventListener("click", () => {
        if (popoverEl) popoverEl.classList.add("hidden");
        if (filterBtn) filterBtn.classList.remove("active");
        renderChips();
        if (cfg.onChange) cfg.onChange();
      });
    }

    if (resetBtn) {
      resetBtn.addEventListener("click", () => resetAll());
    }

    // Immediate update on select/enter inside popover if desired, plus chip sync
    fields.forEach((f) => {
      const el = $(f.id);
      if (!el) return;
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && applyBtn) {
          ev.preventDefault();
          applyBtn.click();
        }
      });
    });

    updateClearBtn();
    renderChips();
    return { sync: renderChips, reset: resetAll };
  }

  // ---------- Reusable Pagination ----------
  function renderPagination(containerId, items, pageObj, onRedraw, totalLabelKey) {
    const total = items.length;
    const totalPages = Math.max(1, Math.ceil(total / pageObj.size));
    if (pageObj.page > totalPages) pageObj.page = totalPages;
    const start = (pageObj.page - 1) * pageObj.size;
    const slice = items.slice(start, start + pageObj.size);

    const el = $(containerId);
    if (!el) return slice;
    const totalStr = t(totalLabelKey || "Total Records: {total}", { total });
    el.innerHTML = `
      <div class="cds--pagination__left">
        <strong>${escHtml(totalStr)}</strong>
      </div>
      <div class="cds--pagination__right">
        <span>${escHtml(t("Rows:"))}</span>
        <select class="pg-size" aria-label="Rows per page">
          ${[10, 25, 50, 100].map((s) => `<option value="${s}" ${s === pageObj.size ? "selected" : ""}>${s}</option>`).join("")}
        </select>
        <button type="button" class="cds--btn--icon pg-first" title="${escHtml(t("First Page"))}" ${pageObj.page <= 1 ? "disabled" : ""}>${icon("page-first", 16)}</button>
        <button type="button" class="cds--btn--icon pg-prev" title="${escHtml(t("Previous Page"))}" ${pageObj.page <= 1 ? "disabled" : ""}>${icon("chevron-left", 16)}</button>
        <span>${escHtml(t("Page {cur} of {total}", { cur: pageObj.page, total: totalPages }))}</span>
        <button type="button" class="cds--btn--icon pg-next" title="${escHtml(t("Next Page"))}" ${pageObj.page >= totalPages ? "disabled" : ""}>${icon("chevron-right", 16)}</button>
        <button type="button" class="cds--btn--icon pg-last" title="${escHtml(t("Last Page"))}" ${pageObj.page >= totalPages ? "disabled" : ""}>${icon("page-last", 16)}</button>
      </div>
    `;
    el.querySelector(".pg-size").addEventListener("change", (e) => {
      pageObj.size = parseInt(e.target.value, 10) || 25;
      pageObj.page = 1;
      onRedraw();
    });
    el.querySelector(".pg-first").addEventListener("click", () => { pageObj.page = 1; onRedraw(); });
    el.querySelector(".pg-prev").addEventListener("click", () => { pageObj.page = Math.max(1, pageObj.page - 1); onRedraw(); });
    el.querySelector(".pg-next").addEventListener("click", () => { pageObj.page = Math.min(totalPages, pageObj.page + 1); onRedraw(); });
    el.querySelector(".pg-last").addEventListener("click", () => { pageObj.page = totalPages; onRedraw(); });
    return slice;
  }

  // ---------- Shared Ping Helper ----------
  async function pingDevices(devicesSubset, allDevicesList, onUpdated) {
    const ids = (devicesSubset || []).map((d) => d.id).filter((id) => id != null);
    if (!ids.length) return;
    try {
      const res = await api("/api/devices/ping", { method: "POST", body: { device_ids: ids } });
      const byId = res.by_id || {};
      (allDevicesList || []).forEach((d) => {
        if (byId[String(d.id)]) d.ping_status = byId[String(d.id)];
      });
      if (onUpdated) onUpdated(byId);
    } catch (_e) {}
  }

  // ---------- Shared Core Metadata ----------
  async function loadCoreData() {
    const [i18nData, settingsData, metaData] = await Promise.all([
      api("/i18n"),
      api("/api/settings"),
      api("/api/meta"),
    ]);
    shared.i18n = i18nData;
    shared.settings = settingsData;
    shared.meta = metaData;

    applyTheme(shared.meta.theme_mode || shared.settings.theme_mode);
    applyI18nDom();
    if ($("hdr-username")) $("hdr-username").textContent = shared.meta.username || "";
    if ($("hdr-user-role")) $("hdr-user-role").textContent = shared.meta.role || "";
    if ($("hdr-api-docs-link")) {
      $("hdr-api-docs-link").classList.toggle("hidden", !shared.meta.api_enabled);
    }
  }

  // ---------- SideNav Rail & Global Device Search ----------
  function wireSideNav() {
    const sidenav = $("app-sidenav");
    const toggleBtn = $("btn-toggle-sidenav");
    if (sidenav && toggleBtn) {
      const setPinned = (isPinned) => {
        sidenav.classList.toggle("cds--side-nav--expanded", isPinned);
        toggleBtn.setAttribute("aria-expanded", isPinned ? "true" : "false");
        try {
          sessionStorage.setItem("anms_sidenav_pinned", isPinned ? "1" : "0");
        } catch (_e) {}
      };
      try {
        setPinned(sessionStorage.getItem("anms_sidenav_pinned") === "1");
      } catch (_e) {
        setPinned(false);
      }
      toggleBtn.addEventListener("click", () => {
        const currentlyPinned = sidenav.classList.contains("cds--side-nav--expanded");
        setPinned(!currentlyPinned);
      });
    }

    const adminToggle = $("sidenav-admin-toggle");
    if (adminToggle) {
      adminToggle.addEventListener("click", () => {
        const exp = adminToggle.getAttribute("aria-expanded") === "true";
        adminToggle.setAttribute("aria-expanded", exp ? "false" : "true");
      });
    }
  }

  function wireGlobalDeviceSearch() {
    const form = $("global-device-search-form");
    const inp = $("global-device-search-input");
    const clearBtn = $("global-device-search-clear");
    const resultsBox = $("global-search-results");
    if (!form || !inp || !resultsBox) return;

    let debounceTimer = null;

    const closeDropdown = () => {
      resultsBox.classList.add("hidden");
    };

    const renderDropdownItems = (query, items) => {
      if (!query) {
        closeDropdown();
        return;
      }
      if (!items.length) {
        resultsBox.innerHTML = `<div class="anms-search-item" style="cursor:default;"><span class="anms-search-item-sub">${escHtml(t("No matching devices found."))}</span></div>`;
        resultsBox.classList.remove("hidden");
        return;
      }
      const rowsHtml = items
        .map(
          (d) => `
          <a class="anms-search-item" href="/devices?highlight=${encodeURIComponent(d.id)}&q=${encodeURIComponent(query)}">
            <div class="anms-search-item-main">
              <span class="anms-search-item-title">${escHtml(d.display_label)}</span>
              <span class="anms-search-item-sub mono">${escHtml(d.ip)}:${escHtml(d.port)} (${escHtml(d.os_type_label || platformLabel(d.os_type) || "-")})${d.folder_path ? ` · ${escHtml(d.folder_path)}` : ""}</span>
            </div>
            <div>${statusTagHtml(d.ping_status || "Unknown")}</div>
          </a>`
        )
        .join("");
      const footerHtml = `<a class="anms-search-footer" href="/devices?q=${encodeURIComponent(query)}">${escHtml(t("View all matching devices in Devices"))} &rarr;</a>`;
      resultsBox.innerHTML = rowsHtml + footerHtml;
      resultsBox.classList.remove("hidden");
    };

    inp.addEventListener("input", () => {
      const q = inp.value.trim();
      if (clearBtn) clearBtn.classList.toggle("hidden", !inp.value);
      if (debounceTimer) clearTimeout(debounceTimer);
      if (!q) {
        closeDropdown();
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          const data = await api(`/api/devices/search?q=${encodeURIComponent(q)}&limit=8`);
          renderDropdownItems(q, data.items || []);
        } catch (_e) {}
      }, 150);
    });

    inp.addEventListener("focus", () => {
      const q = inp.value.trim();
      if (q && resultsBox.innerHTML) {
        resultsBox.classList.remove("hidden");
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        inp.value = "";
        clearBtn.classList.add("hidden");
        closeDropdown();
        inp.focus();
      });
    }

    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const q = inp.value.trim();
      closeDropdown();
      window.location.href = q ? `/devices?q=${encodeURIComponent(q)}` : "/devices";
    });

    document.addEventListener("click", (ev) => {
      if (!form.contains(ev.target)) {
        closeDropdown();
      }
    });

    inp.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        closeDropdown();
      }
    });
  }

  function wireHeaderAndGlobalEvents() {
    bindGlobalModalControls();
    wireSideNav();
    wireGlobalDeviceSearch();

    if ($("confirm-ok-btn")) {
      $("confirm-ok-btn").addEventListener("click", async () => {
        const cb = shared.confirmCallback;
        shared.confirmCallback = null;
        closeModal("modal-confirm");
        if (cb) await cb();
      });
    }

    if ($("btn-logout")) {
      $("btn-logout").addEventListener("click", async () => {
        try {
          await api("/logout", { method: "POST" });
        } catch (_e) {}
        window.location.href = "/login";
      });
    }
  }

  async function bootstrap(initPageFn, onReloadFn) {
    shared.onReloadCallback = onReloadFn || null;
    wireHeaderAndGlobalEvents();
    try {
      await loadCoreData();
      if (initPageFn) await initPageFn();
    } catch (err) {
      toast((err && err.message) || "Failed to load application data.", "error");
    }
  }

  window.AetherNMS = {
    state: shared,
    $,
    icon,
    hasPermission,
    t,
    platformLabel,
    platformOptions,
    escHtml,
    highlightCliHtml,
    toast,
    api,
    applyTheme,
    applyI18nDom,
    statusTagHtml,
    fillSelect,
    openModal,
    closeModal,
    showConfirm,
    wireDataTableToolbar,
    renderPagination,
    pingDevices,
    loadCoreData,
    bootstrap,
  };
})();
