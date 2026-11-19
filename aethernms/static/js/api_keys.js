/* API Keys (/administration/api-keys) management controller */

(function () {
  "use strict";

  const UI = window.AetherNMS;
  const { $, t, escHtml, hasPermission, toast, api, fillSelect, showConfirm, wireDataTableToolbar } = UI;

  const page = {
    keys: [],
    toolbar: null,
  };

  async function reloadPageData() {
    const meta = UI.state.meta || {};
    $("apikeys-disabled-banner").classList.toggle("hidden", Boolean(meta.api_enabled));

    if (hasPermission("roles:manage")) {
      try {
        const rolesData = await api("/api/roles");
        const roleOpts = [{ value: "", label: t("Inherit User Role") }].concat(
          (rolesData.items || []).map((r) => ({ value: r.name, label: r.name }))
        );
        fillSelect($("new-key-role"), roleOpts, true);
        $("new-key-role-wrap").classList.remove("hidden");
      } catch (_e) {}
    }

    if (hasPermission("users:manage")) {
      try {
        const usersData = await api("/api/users");
        const userOpts = (usersData.items || []).map((u) => ({
          value: String(u.id),
          label: `${u.username} (${u.role})`,
        }));
        fillSelect($("new-key-user"), userOpts, true);
        if (meta.user_id && !$("new-key-user").value) {
          $("new-key-user").value = String(meta.user_id);
        }
        $("new-key-user-wrap").classList.remove("hidden");
      } catch (_e) {}
    }

    await refreshApiKeysList();
  }

  async function refreshApiKeysList() {
    const data = await api("/api/auth/api-keys");
    page.keys = data.items || [];
    const roleNames = Array.from(new Set(page.keys.map((k) => k.role_name).filter(Boolean))).sort();
    fillSelect(
      $("flt-key-role"),
      [{ value: "All", label: t("All") }].concat(roleNames.map((r) => ({ value: r, label: r }))),
      true
    );
    if (page.toolbar) page.toolbar.sync();
    renderApiKeysTable();
  }

  function renderApiKeysTable() {
    const q = ($("apikeys-dt-search") ? $("apikeys-dt-search").value : "").trim().toLowerCase();
    const roleQ = $("flt-key-role").value || "All";
    const items = page.keys.filter((k) => {
      if (q) {
        const hay = [k.name, k.username, k.role_name, k.key_prefix].filter(Boolean).join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (roleQ !== "All" && k.role_name !== roleQ) return false;
      return true;
    });

    const tbody = $("api-keys-tbody");
    if (!items.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="7">${escHtml(t("No API keys created yet."))}</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map(
        (k) => `
      <tr>
        <td><strong>${escHtml(k.name)}</strong></td>
        <td>${escHtml(k.username || "-")}</td>
        <td><span class="cds--tag cds--tag--blue">${escHtml(k.role_name || "-")}</span></td>
        <td class="mono">${escHtml(k.key_prefix)}...</td>
        <td class="nowrap">${escHtml(k.created_at || "-")}</td>
        <td class="nowrap">${escHtml(k.last_used_at || "-")}</td>
        <td class="col-actions">
          <button type="button" class="cds--btn cds--btn--danger cds--btn--sm act-revoke-key" data-id="${k.id}" data-name="${escHtml(k.name)}">${escHtml(t("Revoke"))}</button>
        </td>
      </tr>`
      )
      .join("");

    tbody.querySelectorAll(".act-revoke-key").forEach((btn) => {
      btn.addEventListener("click", () => {
        const kid = btn.getAttribute("data-id");
        const kname = btn.getAttribute("data-name");
        showConfirm(
          t("Revoke API Key"),
          t("Revoke API key '{name}'? Any scripts using it will immediately lose access.", { name: kname }),
          async () => {
            await api(`/api/auth/api-keys/${kid}`, { method: "DELETE" });
            toast(t("API key revoked."), "success");
            await refreshApiKeysList();
          },
          t("Revoke"),
          true
        );
      });
    });
  }

  page.toolbar = wireDataTableToolbar({
    searchInputId: "apikeys-dt-search",
    searchClearId: "apikeys-dt-search-clear",
    filterBtnId: "apikeys-filter-btn",
    filterBadgeId: "apikeys-filter-badge",
    popoverId: "apikeys-filter-popover",
    applyBtnId: "apikeys-filter-apply",
    resetBtnId: "apikeys-filter-reset",
    chipsContainerId: "apikeys-active-filters",
    fields: [
      { id: "flt-key-role", labelKey: "Role", defaultVal: "All" },
    ],
    onChange: renderApiKeysTable,
  });

  $("btn-gen-key").addEventListener("click", async () => {
    const body = {
      name: $("new-key-name").value.trim() || "API Key",
    };
    if (hasPermission("roles:manage") && $("new-key-role").value) {
      body.role_name = $("new-key-role").value;
    }
    if (hasPermission("users:manage") && $("new-key-user").value) {
      body.user_id = parseInt($("new-key-user").value, 10);
    }
    try {
      const created = await api("/api/auth/api-keys", { method: "POST", body });
      $("new-key-value").value = created.token;
      $("new-key-banner").classList.remove("hidden");
      $("new-key-name").value = "";
      await refreshApiKeysList();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  $("btn-copy-key").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("new-key-value").value);
      toast(t("Copied!"), "success");
    } catch (_e) {
      $("new-key-value").select();
    }
  });

  UI.bootstrap(reloadPageData, reloadPageData);
})();
