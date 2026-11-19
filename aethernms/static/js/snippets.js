/* Snippets page controller: Built-in read-only templates, Custom Snippets CRUD, CLI syntax preview, and XML Import/Export */

(function () {
  "use strict";

  const UI = window.AetherNMS;
  const {
    $,
    t,
    platformLabel,
    platformOptions,
    escHtml,
    highlightCliHtml,
    toast,
    api,
    fillSelect,
    openModal,
    closeModal,
    showConfirm,
    wireDataTableToolbar,
    renderPagination,
    icon,
    hasPermission,
  } = UI;

  const page = {
    snippets: [],
    selectedSnippetId: null,
    editingSnippetId: null,
    toolbar: null,
    pagination: { page: 1, size: 25 },
  };

  function populateFilterDropdowns() {
    const meta = UI.state.meta || {};
    const usedPlatforms = meta.used_platforms || [];
    const osOpts = [{ value: "All", label: t("All") }].concat(platformOptions(usedPlatforms));
    const typeOpts = [
      { value: "All", label: t("All") },
      { value: "Config", label: t("Config") },
      { value: "Audit and Remediate", label: t("Audit and Remediate") },
    ];
    const sevOpts = [{ value: "All", label: t("All") }].concat(
      (meta.severities || ["Info", "Warning", "Critical"]).map((s) => ({
        value: s,
        label: s,
      }))
    );

    fillSelect($("flt-snip-type"), typeOpts, true);
    fillSelect($("flt-snip-sev"), sevOpts, true);
    fillSelect($("flt-snip-os"), osOpts, true);
    if (page.toolbar) page.toolbar.sync();
  }

  async function reloadPageData() {
    const data = await api("/api/snippets");
    page.snippets = data.items || [];
    const canWrite = hasPermission("snippets:write");
    $("btn-add-snippet").classList.toggle("hidden", !canWrite);
    $("btn-import-snippet").classList.toggle("hidden", !canWrite);
    populateFilterDropdowns();
    renderSnippetsView();
  }

  function renderSnippetsView() {
    const q = ($("snippets-dt-search") ? $("snippets-dt-search").value : "").trim().toLowerCase();
    const typeQ = $("flt-snip-type").value || "All";
    const sevQ = $("flt-snip-sev").value || "All";
    const osQ = $("flt-snip-os").value || "All";

    const filtered = page.snippets.filter((s) => {
      if (q) {
        const platDisp = s.device_type_label || platformLabel(s.device_type);
        const hay = [s.name, s.description, s.commands, s.device_type, platDisp, t(s.snippet_type), s.severity]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (typeQ !== "All" && s.snippet_type !== typeQ) return false;
      if (sevQ !== "All" && s.severity !== sevQ) return false;
      if (osQ !== "All" && s.device_type !== osQ) return false;
      return true;
    });

    const pageItems = renderPagination(
      "snippets-pagination",
      filtered,
      page.pagination,
      renderSnippetsView,
      "Total Items: {total}"
    );
    const tbody = $("snippets-tbody");
    if (!pageItems.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="7">-</td></tr>`;
    } else {
      const canWrite = hasPermission("snippets:write");
      tbody.innerHTML = pageItems
        .map((s) => {
          const isBuiltin = Boolean(s.is_builtin);
          const platDisp = s.device_type_label || platformLabel(s.device_type);
          const builtinTag = isBuiltin
            ? ` <span class="cds--tag cds--tag--purple">${escHtml(t("Built-in"))}</span>`
            : "";
          const showEdit = canWrite && !isBuiltin;
          const actBtn = showEdit
            ? `<button type="button" class="cds--btn--icon act-snip-edit" data-id="${s.id}" title="${escHtml(t("Edit"))}">${icon("edit", 16)}</button>`
            : `<button type="button" class="cds--btn--icon act-snip-edit" data-id="${s.id}" title="${escHtml(t("View"))}">${icon("view", 16)}</button>`;
          const delBtn = showEdit
            ? `<button type="button" class="cds--btn--icon danger act-snip-del" data-id="${s.id}" title="${escHtml(t("Delete"))}">${icon("trash-can", 16)}</button>`
            : "";
          return `
        <tr class="${s.id === page.selectedSnippetId ? "selected" : ""}" data-snip-id="${s.id}">
          <td><strong>${escHtml(s.name)}</strong>${builtinTag}</td>
          <td>${escHtml(t(s.snippet_type))}</td>
          <td>${escHtml(s.severity)}</td>
          <td>${escHtml(platDisp)}</td>
          <td class="nowrap">${escHtml(s.created_at || "-")}</td>
          <td>${escHtml(s.description || "")}</td>
          <td class="col-actions">
            ${actBtn}
            ${delBtn}
          </td>
        </tr>`;
        })
        .join("");

      tbody.querySelectorAll("tr[data-snip-id]").forEach((tr) => {
        tr.addEventListener("click", (ev) => {
          if (ev.target.closest("button")) return;
          page.selectedSnippetId = parseInt(tr.getAttribute("data-snip-id"), 10);
          renderSnippetsView();
        });
        tr.addEventListener("dblclick", () => {
          const s = page.snippets.find((x) => x.id === parseInt(tr.getAttribute("data-snip-id"), 10));
          if (s) openSnippetModal(s);
        });
      });
      tbody.querySelectorAll(".act-snip-edit").forEach((btn) => {
        btn.addEventListener("click", () => {
          const s = page.snippets.find((x) => x.id === parseInt(btn.getAttribute("data-id"), 10));
          if (s) openSnippetModal(s);
        });
      });
      tbody.querySelectorAll(".act-snip-del").forEach((btn) => {
        btn.addEventListener("click", () => {
          const sid = parseInt(btn.getAttribute("data-id"), 10);
          const s = page.snippets.find((x) => x.id === sid);
          if (!s || s.is_builtin) return;
          showConfirm(
            t("Delete Snippet"),
            t("Delete snippet '{name}'?", { name: s.name }),
            async () => {
              await api(`/api/snippets/${sid}`, { method: "DELETE" });
              page.snippets = page.snippets.filter((x) => x.id !== sid);
              if (page.selectedSnippetId === sid) page.selectedSnippetId = null;
              renderSnippetsView();
            },
            t("Delete"),
            true
          );
        });
      });
    }

    const selSnip = page.snippets.find((s) => s.id === page.selectedSnippetId);
    $("snippet-preview").innerHTML = selSnip ? highlightCliHtml(selSnip.commands) : "";
  }

  function openSnippetModal(snip) {
    const meta = UI.state.meta || {};
    const canWrite = hasPermission("snippets:write");
    const isBuiltin = Boolean(snip && snip.is_builtin);
    const isReadOnly = Boolean(snip && (isBuiltin || !canWrite));

    page.editingSnippetId = snip ? snip.id : null;
    $("modal-snippet-title").textContent = snip
      ? (isReadOnly ? t("View Snippet") : t("Edit Snippet"))
      : t("Add Snippet");
    $("snip-err").classList.add("hidden");
    $("snip-builtin-note").classList.toggle("hidden", !isBuiltin);

    const platforms = meta.platforms || ["aruba_procurve", "aruba_aoscx"];
    fillSelect($("snip-os"), platformOptions(platforms), false);
    fillSelect($("snip-sev"), meta.severities || ["Info", "Warning", "Critical"], false);

    const stype = snip ? snip.snippet_type : "Config";
    document.querySelectorAll('input[name="snip-type"]').forEach((r) => {
      r.checked = r.value === stype;
      r.disabled = isReadOnly;
    });
    $("snip-name").value = snip ? snip.name : "";
    $("snip-name").readOnly = isReadOnly;
    $("snip-os").value = snip && platforms.includes(snip.device_type)
      ? snip.device_type
      : (platforms.includes("aruba_procurve") ? "aruba_procurve" : platforms[0]);
    $("snip-os").disabled = isReadOnly;
    $("snip-sev").value = snip ? snip.severity : "Info";
    $("snip-sev").disabled = isReadOnly;
    $("snip-desc").value = snip ? snip.description : "";
    $("snip-desc").readOnly = isReadOnly;
    $("snip-cmds").value = snip ? snip.commands : "";
    $("snip-cmds").readOnly = isReadOnly;
    $("snip-audit").value = snip ? snip.audit_regex : "";
    $("snip-audit").readOnly = isReadOnly;
    $("snip-audit-wrap").classList.toggle("hidden", stype !== "Audit and Remediate");

    $("btn-save-snippet").classList.toggle("hidden", isReadOnly);
    $("btn-cancel-snippet").textContent = isReadOnly ? t("Close") : t("Cancel");
    openModal("modal-snippet");
  }

  function wirePageEvents() {
    page.toolbar = wireDataTableToolbar({
      searchInputId: "snippets-dt-search",
      searchClearId: "snippets-dt-search-clear",
      filterBtnId: "snippets-filter-btn",
      filterBadgeId: "snippets-filter-badge",
      popoverId: "snippets-filter-popover",
      applyBtnId: "snippets-filter-apply",
      resetBtnId: "snippets-filter-reset",
      chipsContainerId: "snippets-active-filters",
      fields: [
        { id: "flt-snip-type", labelKey: "Snippet Type", defaultVal: "All", formatValue: t },
        { id: "flt-snip-sev", labelKey: "Severity", defaultVal: "All" },
        { id: "flt-snip-os", labelKey: "Netmiko Platform", defaultVal: "All", formatValue: platformLabel },
      ],
      onChange: () => { page.pagination.page = 1; renderSnippetsView(); },
    });

    $("btn-add-snippet").addEventListener("click", () => openSnippetModal(null));
    document.querySelectorAll('input[name="snip-type"]').forEach((r) => {
      r.addEventListener("change", () => {
        $("snip-audit-wrap").classList.toggle("hidden", r.value !== "Audit and Remediate");
      });
    });
    $("btn-save-snippet").addEventListener("click", async () => {
      $("snip-err").classList.add("hidden");
      const stype = document.querySelector('input[name="snip-type"]:checked').value;
      const body = {
        name: $("snip-name").value.trim(),
        snippet_type: stype,
        device_type: $("snip-os").value,
        severity: $("snip-sev").value,
        description: $("snip-desc").value.trim(),
        commands: $("snip-cmds").value,
        audit_regex: stype === "Audit and Remediate" ? $("snip-audit").value : "",
      };
      try {
        if (page.editingSnippetId) {
          await api(`/api/snippets/${page.editingSnippetId}`, { method: "PUT", body });
        } else {
          await api("/api/snippets", { method: "POST", body });
        }
        closeModal("modal-snippet");
        await UI.loadCoreData();
        await reloadPageData();
      } catch (err) {
        $("snip-err").textContent = err.message;
        $("snip-err").classList.remove("hidden");
      }
    });
    $("btn-import-snippet").addEventListener("click", () => $("snippet-import-file").click());
    $("snippet-import-file").addEventListener("change", async (ev) => {
      const file = ev.target.files && ev.target.files[0];
      ev.target.value = "";
      if (!file) return;
      try {
        const xmlText = await file.text();
        const imp = await api("/api/snippets/import", {
          method: "POST",
          body: { xml: xmlText, filename: file.name },
        });
        toast(`${t("Import Snippet")}: ${imp.name}`, "success");
        await UI.loadCoreData();
        await reloadPageData();
      } catch (err) {
        toast(err.message, "error");
      }
    });
    $("btn-export-snippet").addEventListener("click", () => {
      if (!page.selectedSnippetId) {
        toast(t("Select a snippet row to export."), "error");
        return;
      }
      window.location.href = `/api/snippets/${page.selectedSnippetId}/export`;
    });
  }

  wirePageEvents();
  UI.bootstrap(reloadPageData, reloadPageData);
})();
