/* Devices page controller: Devices CRUD, ICMP ping checks, AirWave Import, and Unmapped Models mapping */

(function () {
  "use strict";

  const UI = window.AetherNMS;
  const { $, t, escHtml, toast, api, statusTagHtml, fillSelect, openModal, closeModal, showConfirm, renderPagination, pingDevices, icon, hasPermission } = UI;

  const page = {
    devices: [],
    editingDeviceId: null,
    globalQuery: "",
    highlightDeviceId: null,
    pages: {
      devices: { page: 1, size: 25 },
      airwave: { page: 1, size: 25 },
    },
    airwave: {
      items: [],
      folderOptions: [],
      checkedKeys: new Set(),
      totalRecords: 0,
    },
  };

  function populateFilterDropdowns() {
    const meta = UI.state.meta || {};
    const usedPlatforms = meta.used_platforms || [];
    const osOpts = [{ value: "All", label: t("All") }].concat(
      usedPlatforms.map((p) => ({ value: p, label: p }))
    );
    const pingStatusOpts = [
      { value: "All", label: t("All") },
      { value: "Up", label: t("Up") },
      { value: "Down", label: t("Down") },
      { value: "Unknown", label: t("Unknown") },
    ];

    fillSelect($("flt-dev-os"), osOpts, true);
    fillSelect($("flt-dev-status"), pingStatusOpts, true);

    $("dl-models").innerHTML = (meta.assigned_models || [])
      .map((m) => `<option value="${escHtml(m)}"></option>`).join("");
    $("dl-groups").innerHTML = (meta.assigned_groups || [])
      .map((g) => `<option value="${escHtml(g)}"></option>`).join("");
  }

  function getFilteredDevices() {
    const gq = (page.globalQuery || "").trim().toLowerCase();
    const nameQ = $("flt-dev-name").value.trim().toLowerCase();
    const ipQ = $("flt-dev-ip").value.trim().toLowerCase();
    const osQ = $("flt-dev-os").value || "All";
    const grpQ = $("flt-dev-group").value.trim().toLowerCase();
    const stQ = $("flt-dev-status").value || "All";
    return page.devices.filter((d) => {
      if (gq) {
        const hay = [d.name, d.ip, d.model, d.folder_path, d.os_type, d.serial_number]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(gq)) return false;
      }
      if (nameQ && !(d.name || "").toLowerCase().includes(nameQ)) return false;
      if (ipQ && !(d.ip || "").toLowerCase().includes(ipQ)) return false;
      if (osQ !== "All" && d.os_type !== osQ) return false;
      if (grpQ && !(d.folder_path || "").toLowerCase().includes(grpQ)) return false;
      if (stQ !== "All" && (d.ping_status || "Unknown") !== stQ) return false;
      return true;
    });
  }

  function pingVisibleDevices() {
    const pg = page.pages.devices;
    const visible = getFilteredDevices().slice((pg.page - 1) * pg.size, pg.page * pg.size);
    pingDevices(visible, page.devices, () => renderDevicesView());
  }

  function readInitialUrlSearchParams() {
    const params = new URLSearchParams(window.location.search);
    const q = (params.get("q") || "").trim();
    const hl = parseInt(params.get("highlight") || "", 10);
    page.globalQuery = q;
    page.highlightDeviceId = Number.isFinite(hl) ? hl : null;
    if ($("global-device-search-input") && q) {
      $("global-device-search-input").value = q;
      if ($("global-device-search-clear")) $("global-device-search-clear").classList.remove("hidden");
    }
    syncGlobalQueryBanner();
  }

  function syncGlobalQueryBanner() {
    const banner = $("dev-global-query-banner");
    if (!banner) return;
    if (page.globalQuery) {
      $("dev-global-query-text").textContent = page.globalQuery;
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
    }
  }

  async function reloadPageData(runInitialPing) {
    if (runInitialPing) readInitialUrlSearchParams();
    const data = await api("/api/devices");
    page.devices = data.items || [];
    $("btn-add-device").classList.toggle("hidden", !hasPermission("devices:write"));
    $("btn-open-airwave").classList.toggle("hidden", !hasPermission("airwave:import"));
    populateFilterDropdowns();
    renderDevicesView();
    if (runInitialPing && page.devices.length) {
      pingVisibleDevices();
    }
  }

  function renderDevicesView() {
    const filtered = getFilteredDevices();
    const pageItems = renderPagination(
      "devices-pagination",
      filtered,
      page.pages.devices,
      () => {
        renderDevicesView();
        pingVisibleDevices();
      },
      "Total Records: {total}"
    );

    const tbody = $("devices-tbody");
    if (!pageItems.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="9">-</td></tr>`;
      return;
    }
    const canWrite = hasPermission("devices:write");
    tbody.innerHTML = pageItems
      .map(
        (d) => `
      <tr class="${d.id === page.highlightDeviceId ? "selected" : ""}" data-dev-id="${d.id}">
        <td><strong>${escHtml(d.display_label)}</strong></td>
        <td>${statusTagHtml(d.ping_status || "Unknown")}</td>
        <td class="mono">${escHtml(d.ip)}</td>
        <td class="mono">${escHtml(d.os_type || "-")}</td>
        <td>${escHtml(d.protocol)}</td>
        <td class="mono">${escHtml(d.port)}</td>
        <td>${escHtml(d.model || "")}</td>
        <td>${escHtml(d.folder_path || "")}</td>
        <td class="col-actions">
          ${canWrite ? `<button type="button" class="cds--btn--icon act-dev-edit" data-id="${d.id}" title="${escHtml(t("Edit"))}">${icon("edit", 16)}</button>` : ""}
          ${canWrite ? `<button type="button" class="cds--btn--icon danger act-dev-del" data-id="${d.id}" title="${escHtml(t("Delete"))}">${icon("trash-can", 16)}</button>` : ""}
        </td>
      </tr>`
      )
      .join("");

    if (canWrite) {
      tbody.querySelectorAll("tr[data-dev-id]").forEach((tr) => {
        tr.addEventListener("dblclick", () => {
          const d = page.devices.find((x) => x.id === parseInt(tr.getAttribute("data-dev-id"), 10));
          if (d) openDeviceModal(d);
        });
      });
    }
    tbody.querySelectorAll(".act-dev-edit").forEach((btn) => {
      btn.addEventListener("click", () => {
        const d = page.devices.find((x) => x.id === parseInt(btn.getAttribute("data-id"), 10));
        if (d) openDeviceModal(d);
      });
    });
    tbody.querySelectorAll(".act-dev-del").forEach((btn) => {
      btn.addEventListener("click", () => {
        const did = parseInt(btn.getAttribute("data-id"), 10);
        const d = page.devices.find((x) => x.id === did);
        if (!d) return;
        showConfirm(
          t("Delete Device"),
          t("Remove device '{name}'?", { name: d.display_label }),
          async () => {
            await api(`/api/devices/${did}`, { method: "DELETE" });
            page.devices = page.devices.filter((x) => x.id !== did);
            renderDevicesView();
          },
          t("Delete"),
          true
        );
      });
    });
  }

  function syncDeviceProtocolOptions(platform, preferredProto, updatePort) {
    const meta = UI.state.meta || {};
    const settings = UI.state.settings || {};
    const map = meta.protocols_by_platform || {};
    const supported = map[platform] || ["SSH"];
    fillSelect($("dev-proto"), supported, false);
    if (preferredProto && supported.includes(preferredProto)) {
      $("dev-proto").value = preferredProto;
    } else {
      $("dev-proto").value = supported[0];
    }
    if (updatePort) {
      const proto = $("dev-proto").value;
      $("dev-port").value = proto === "Telnet" ? (settings.telnet_port || 23) : (settings.ssh_port || 22);
    }
  }

  function openDeviceModal(dev) {
    const meta = UI.state.meta || {};
    const settings = UI.state.settings || {};
    page.editingDeviceId = dev ? dev.id : null;
    const isAw = Boolean(dev && dev.is_airwave);
    $("modal-device-title").textContent = dev ? t("Edit Device") : t("Add Device");
    $("dev-err").classList.add("hidden");
    $("dev-airwave-note").classList.toggle("hidden", !isAw);

    const platforms = meta.platforms || ["aruba_procurve", "aruba_aoscx"];
    fillSelect($("dev-os"), platforms, false);

    const initOs = dev && platforms.includes(dev.os_type)
      ? dev.os_type
      : (platforms.includes("aruba_procurve") ? "aruba_procurve" : platforms[0]);
    $("dev-os").value = initOs;

    const initProto = dev ? dev.protocol : settings.default_protocol;
    syncDeviceProtocolOptions(initOs, initProto, false);
    const effProto = $("dev-proto").value;
    $("dev-port").value = dev ? dev.port : (effProto === "Telnet" ? (settings.telnet_port || 23) : (settings.ssh_port || 22));

    $("dev-name").value = dev ? dev.name : "";
    $("dev-ip").value = dev ? dev.ip : "";
    $("dev-model").value = dev ? dev.model : "";
    $("dev-group").value = dev ? dev.folder_path : "";

    // Enforce AirWave read-only identity/inventory fields
    $("dev-name").readOnly = isAw;
    $("dev-ip").readOnly = isAw;
    $("dev-model").readOnly = isAw;
    $("dev-group").readOnly = isAw;

    openModal("modal-device");
  }

  // ---------- AIRWAVE IMPORT & UNMAPPED MODELS ----------
  function openAirWaveModal() {
    const settings = UI.state.settings || {};
    $("aw-err").classList.add("hidden");
    $("aw-url").value = settings.airwave_url || "";
    $("aw-user").value = settings.airwave_username || "";
    $("aw-pass").value = "";
    $("aw-ssl").checked = Boolean(settings.airwave_verify_ssl);
    // Preview starts empty until Fetch Inventory runs
    page.airwave = { items: [], folderOptions: [], checkedKeys: new Set(), totalRecords: 0 };
    fillSelect($("aw-flt-folder"), [{ value: "All", label: t("All") }], false);
    fillSelect($("aw-flt-os"), [{ value: "All", label: t("All") }], false);
    $("aw-flt-name").value = "";
    $("aw-flt-ip").value = "";
    $("aw-status-text").textContent = t("Enter AirWave credentials and click Fetch Inventory.");
    renderAirWaveTable();
    openModal("modal-airwave");
  }

  function getFilteredAirWaveItems() {
    const fltFolder = $("aw-flt-folder").value || "All";
    const fltName = $("aw-flt-name").value.trim().toLowerCase();
    const fltIp = $("aw-flt-ip").value.trim().toLowerCase();
    const fltOs = $("aw-flt-os").value || "All";
    return page.airwave.items.filter((h) => {
      if (fltFolder !== "All" && h.folder_id !== fltFolder && !(h.folder_path || "").toLowerCase().includes(fltFolder.toLowerCase())) return false;
      if (fltName && !(h.name || "").toLowerCase().includes(fltName)) return false;
      if (fltIp && !(h.ip || "").toLowerCase().includes(fltIp)) return false;
      if (fltOs === "Unmapped" && h.os_type) return false;
      if (fltOs !== "All" && fltOs !== "Unmapped" && h.os_type !== fltOs) return false;
      return true;
    });
  }

  function renderAirWaveTable() {
    const filtered = getFilteredAirWaveItems();
    const pageItems = renderPagination(
      "aw-pagination",
      filtered,
      page.pages.airwave,
      renderAirWaveTable,
      "Total Records: {total}"
    );
    const tbody = $("aw-tbody");
    if (!pageItems.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="9">-</td></tr>`;
      return;
    }
    tbody.innerHTML = pageItems
      .map((h) => {
        const chk = page.airwave.checkedKeys.has(h.unique_key) ? "checked" : "";
        const osDisp = h.os_type
          ? `<span class="mono">${escHtml(h.os_type)}</span>`
          : `<span class="cds--tag cds--tag--warm">${escHtml(t("Unmapped"))}</span>`;
        return `
          <tr>
            <td class="col-check"><input type="checkbox" class="aw-chk" data-key="${escHtml(h.unique_key)}" ${chk} /></td>
            <td>${escHtml(h.name || h.ip)}</td>
            <td>${statusTagHtml(h.airwave_status || "Unknown")}</td>
            <td class="mono">${escHtml(h.ip)}</td>
            <td>${escHtml(h.model || "")}</td>
            <td>${escHtml(h.airwave_os || "-")}</td>
            <td>${osDisp}</td>
            <td>${escHtml(h.protocol)}</td>
            <td>${escHtml(h.folder_path || "")}</td>
          </tr>`;
      })
      .join("");

    tbody.querySelectorAll(".aw-chk").forEach((cb) => {
      cb.addEventListener("change", () => {
        const k = cb.getAttribute("data-key");
        if (cb.checked) page.airwave.checkedKeys.add(k);
        else page.airwave.checkedKeys.delete(k);
        updateAirWaveStatusLabel();
      });
    });
  }

  function updateAirWaveStatusLabel() {
    const unmapped = page.airwave.items.filter((h) => !h.os_type).length;
    $("aw-status-text").textContent =
      `${page.airwave.items.length} / ${page.airwave.totalRecords}  |  Selected: ${page.airwave.checkedKeys.size}` +
      (unmapped ? `  |  ${t("Unmapped")}: ${unmapped}` : "");
  }

  async function submitAirWaveImport(selectedHosts, osMappings) {
    try {
      const res = await api("/api/airwave/import", {
        method: "POST",
        body: {
          devices: selectedHosts,
          os_mappings: osMappings || {},
          airwave_url: $("aw-url").value.trim(),
          airwave_username: $("aw-user").value.trim(),
          airwave_verify_ssl: $("aw-ssl").checked,
        },
      });
      closeModal("modal-unmapped");
      closeModal("modal-airwave");
      toast(`${t("Import Selected")}: ${res.imported}`, "success");
      await UI.loadCoreData();
      await reloadPageData(false);
    } catch (err) {
      $("aw-err").textContent = err.message;
      $("aw-err").classList.remove("hidden");
    }
  }

  function wirePageEvents() {
    ["flt-dev-name", "flt-dev-ip", "flt-dev-os", "flt-dev-group", "flt-dev-status"].forEach((id) => {
      $(id).addEventListener("input", () => { page.pages.devices.page = 1; renderDevicesView(); });
      $(id).addEventListener("change", () => { page.pages.devices.page = 1; renderDevicesView(); });
    });
    if ($("btn-clear-global-query")) {
      $("btn-clear-global-query").addEventListener("click", () => {
        page.globalQuery = "";
        page.highlightDeviceId = null;
        if ($("global-device-search-input")) $("global-device-search-input").value = "";
        if ($("global-device-search-clear")) $("global-device-search-clear").classList.add("hidden");
        window.history.replaceState({}, "", "/devices");
        syncGlobalQueryBanner();
        page.pages.devices.page = 1;
        renderDevicesView();
      });
    }
    $("btn-ping-devices").addEventListener("click", pingVisibleDevices);
    $("btn-add-device").addEventListener("click", () => openDeviceModal(null));
    $("dev-os").addEventListener("change", () => {
      syncDeviceProtocolOptions($("dev-os").value, $("dev-proto").value, true);
    });
    $("dev-proto").addEventListener("change", () => {
      const settings = UI.state.settings || {};
      $("dev-port").value = $("dev-proto").value === "Telnet" ? (settings.telnet_port || 23) : (settings.ssh_port || 22);
    });
    $("btn-save-device").addEventListener("click", async () => {
      $("dev-err").classList.add("hidden");
      const body = {
        name: $("dev-name").value.trim(),
        ip: $("dev-ip").value.trim(),
        model: $("dev-model").value.trim(),
        os_type: $("dev-os").value,
        protocol: $("dev-proto").value,
        port: parseInt($("dev-port").value, 10),
        folder_path: $("dev-group").value.trim(),
      };
      try {
        if (page.editingDeviceId) {
          await api(`/api/devices/${page.editingDeviceId}`, { method: "PUT", body });
        } else {
          await api("/api/devices", { method: "POST", body });
        }
        closeModal("modal-device");
        await UI.loadCoreData();
        await reloadPageData(false);
      } catch (err) {
        $("dev-err").textContent = err.message;
        $("dev-err").classList.remove("hidden");
      }
    });

    $("btn-open-airwave").addEventListener("click", openAirWaveModal);
    $("btn-aw-fetch").addEventListener("click", async () => {
      $("aw-err").classList.add("hidden");
      $("btn-aw-fetch").disabled = true;
      $("aw-status-text").textContent = t("Fetching inventory...");
      try {
        const res = await api("/api/airwave/fetch", {
          method: "POST",
          body: {
            url: $("aw-url").value.trim(),
            username: $("aw-user").value.trim(),
            password: $("aw-pass").value,
            verify_ssl: $("aw-ssl").checked,
          },
        });
        page.airwave.items = res.items || [];
        page.airwave.folderOptions = res.folder_options || [];
        page.airwave.totalRecords = res.total_records || 0;
        page.airwave.checkedKeys = new Set(res.preselected_keys || []);

        fillSelect(
          $("aw-flt-folder"),
          [{ value: "All", label: t("All") }].concat(
            page.airwave.folderOptions.map((f) => ({ value: f.id, label: f.label }))
          ),
          false
        );
        const foundOs = Array.from(new Set(page.airwave.items.map((h) => h.os_type).filter(Boolean))).sort();
        const osOpts = [{ value: "All", label: t("All") }].concat(foundOs.map((p) => ({ value: p, label: p })));
        if (page.airwave.items.some((h) => !h.os_type)) {
          osOpts.push({ value: "Unmapped", label: t("Unmapped") });
        }
        fillSelect($("aw-flt-os"), osOpts, false);
        page.pages.airwave.page = 1;
        renderAirWaveTable();
        updateAirWaveStatusLabel();
      } catch (err) {
        $("aw-err").textContent = err.message;
        $("aw-err").classList.remove("hidden");
        $("aw-status-text").textContent = err.message;
      } finally {
        $("btn-aw-fetch").disabled = false;
      }
    });
    ["aw-flt-folder", "aw-flt-name", "aw-flt-ip", "aw-flt-os"].forEach((id) => {
      $(id).addEventListener("input", () => { page.pages.airwave.page = 1; renderAirWaveTable(); });
      $(id).addEventListener("change", () => { page.pages.airwave.page = 1; renderAirWaveTable(); });
    });
    $("btn-aw-select-all").addEventListener("click", () => {
      const visible = getFilteredAirWaveItems();
      const allChecked = visible.length > 0 && visible.every((h) => page.airwave.checkedKeys.has(h.unique_key));
      visible.forEach((h) => {
        if (allChecked) page.airwave.checkedKeys.delete(h.unique_key);
        else page.airwave.checkedKeys.add(h.unique_key);
      });
      renderAirWaveTable();
      updateAirWaveStatusLabel();
    });
    $("btn-aw-import").addEventListener("click", () => {
      $("aw-err").classList.add("hidden");
      const chosen = page.airwave.items.filter((h) => page.airwave.checkedKeys.has(h.unique_key));
      if (!chosen.length) {
        $("aw-err").textContent = t("Select Devices");
        $("aw-err").classList.remove("hidden");
        return;
      }
      const unmapped = chosen.filter((h) => !h.os_type);
      if (unmapped.length) {
        const groups = {};
        unmapped.forEach((h) => {
          const key = (h.airwave_os || h.model || h.name || h.ip).trim();
          if (!groups[key]) groups[key] = { key, count: 0, firmware: h.firmware || "" };
          groups[key].count += 1;
        });
        const platforms = (UI.state.meta && UI.state.meta.platforms) || [];
        const platOpts = `<option value=""></option>` + platforms.map((p) => `<option value="${escHtml(p)}">${escHtml(p)}</option>`).join("");
        $("unmapped-rows").innerHTML = Object.values(groups)
          .map(
            (g) => `
          <div class="form-grid" style="align-items:center;">
            <div><strong>${escHtml(g.key)}</strong> (${g.count})${g.firmware ? ` — FW: ${escHtml(g.firmware)}` : ""}</div>
            <select class="cds--select-input unmapped-plat-select" data-key="${escHtml(g.key)}">${platOpts}</select>
          </div>`
          )
          .join("");
        openModal("modal-unmapped");
        return;
      }
      submitAirWaveImport(chosen, {});
    });
    $("btn-apply-unmapped").addEventListener("click", () => {
      const mappings = {};
      let missing = false;
      document.querySelectorAll(".unmapped-plat-select").forEach((sel) => {
        if (!sel.value) missing = true;
        else mappings[sel.getAttribute("data-key")] = sel.value;
      });
      if (missing) {
        toast(t("Validation"), "error");
        return;
      }
      const chosen = page.airwave.items.filter((h) => page.airwave.checkedKeys.has(h.unique_key));
      submitAirWaveImport(chosen, mappings);
    });
  }

  wirePageEvents();
  UI.bootstrap(() => reloadPageData(true), () => reloadPageData(false));
})();
