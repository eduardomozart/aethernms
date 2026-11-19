/* Users (/administration/users) RBAC management & self-service profile/appearance controller */

(function () {
  "use strict";

  const UI = window.AetherNMS;
  const {
    $,
    t,
    escHtml,
    icon,
    toast,
    api,
    statusTagHtml,
    fillSelect,
    openModal,
    closeModal,
    showConfirm,
    wireDataTableToolbar,
  } = UI;

  const page = {
    users: [],
    roles: [],
    canManageUsers: true,
    editingUserId: null,
    handledUrlEdit: false,
    toolbar: null,
  };

  function getLanguageLabel(code) {
    if (!code || code === "auto") return t("Auto (OS Default)");
    const list = (UI.state.i18n && UI.state.i18n.available_languages) || [];
    const found = list.find((l) => l.code === code);
    return found ? found.label : code;
  }

  function getThemeLabel(mode) {
    const m = (mode || "auto").toLowerCase();
    if (m === "light") return t("Light");
    if (m === "dark") return t("Dark");
    return t("Auto (OS Default)");
  }

  function populateFilterDropdowns() {
    const roleNames = Array.from(new Set(page.users.map((u) => u.role).filter(Boolean))).sort();
    fillSelect(
      $("flt-usr-role"),
      [{ value: "All", label: t("All") }].concat(roleNames.map((r) => ({ value: r, label: r }))),
      true
    );
    fillSelect(
      $("flt-usr-status"),
      [
        { value: "All", label: t("All") },
        { value: "Active", label: t("Active") },
        { value: "Disabled", label: t("Disabled") },
      ],
      true
    );
    if (page.toolbar) page.toolbar.sync();
  }

  async function reloadPageData() {
    const usersData = await api("/api/users");
    page.users = usersData.items || [];
    page.canManageUsers = Boolean(usersData.can_manage_users);
    $("btn-add-user").classList.toggle("hidden", !page.canManageUsers);

    const perms = (UI.state.meta && UI.state.meta.permissions) || [];
    if (perms.includes("roles:manage") || perms.includes("users:manage") || perms.includes("api_keys:manage")) {
      try {
        const rolesData = await api("/api/roles");
        page.roles = rolesData.items || [];
      } catch (_e) {
        page.roles = [];
      }
    }

    populateFilterDropdowns();
    renderUsersTable();

    if (!page.handledUrlEdit) {
      page.handledUrlEdit = true;
      const editParam = new URLSearchParams(window.location.search).get("edit");
      if (editParam) {
        const curUserId = UI.state.meta && UI.state.meta.user_id;
        const target =
          editParam === "me"
            ? page.users.find((u) => u.id === curUserId)
            : page.users.find((u) => String(u.id) === editParam);
        if (target) {
          openUserModal(target);
        }
      }
    }
  }

  function renderUsersTable() {
    const q = ($("users-dt-search") ? $("users-dt-search").value : "").trim().toLowerCase();
    const roleQ = $("flt-usr-role").value || "All";
    const stQ = $("flt-usr-status").value || "All";

    const filtered = page.users.filter((u) => {
      const statusStr = u.is_active ? "Active" : "Disabled";
      if (q) {
        const hay = [u.username, u.display_name, u.role, t(statusStr), getLanguageLabel(u.language)]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (roleQ !== "All" && u.role !== roleQ) return false;
      if (stQ !== "All" && statusStr !== stQ) return false;
      return true;
    });

    const tbody = $("users-tbody");
    const curUserId = UI.state.meta && UI.state.meta.user_id;
    if (!filtered.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="7">-</td></tr>`;
      return;
    }
    tbody.innerHTML = filtered
      .map((u) => {
        const isSelf = u.id === curUserId;
        const canDel = page.canManageUsers && !isSelf;
        const delBtn = canDel
          ? `<button type="button" class="cds--btn--icon danger act-usr-del" data-id="${u.id}" title="${escHtml(t("Delete"))}">${icon("trash-can", 16)}</button>`
          : "";
        const appSummary = `${getLanguageLabel(u.language)} · ${getThemeLabel(u.theme_mode)}`;
        return `
          <tr>
            <td><strong>${escHtml(u.username)}</strong>${isSelf ? ` <span class="cds--tag cds--tag--gray">${escHtml(t("You"))}</span>` : ""}</td>
            <td>${escHtml(u.display_name || "-")}</td>
            <td><span class="cds--tag cds--tag--blue">${escHtml(u.role)}</span></td>
            <td>${statusTagHtml(u.is_active ? "Active" : "Disabled")}</td>
            <td>${escHtml(appSummary)}</td>
            <td class="nowrap">${escHtml(u.created_at || "-")}</td>
            <td class="col-actions">
              <button type="button" class="cds--btn--icon act-usr-edit" data-id="${u.id}" title="${escHtml(t("Edit"))}">${icon("edit", 16)}</button>
              ${delBtn}
            </td>
          </tr>`;
      })
      .join("");

    tbody.querySelectorAll(".act-usr-edit").forEach((btn) => {
      btn.addEventListener("click", () => {
        const u = page.users.find((x) => x.id === parseInt(btn.getAttribute("data-id"), 10));
        if (u) openUserModal(u);
      });
    });

    tbody.querySelectorAll(".act-usr-del").forEach((btn) => {
      btn.addEventListener("click", () => {
        const uid = parseInt(btn.getAttribute("data-id"), 10);
        const u = page.users.find((x) => x.id === uid);
        if (!u) return;
        showConfirm(
          t("Delete User"),
          t("Delete user account '{name}'?", { name: u.username }),
          async () => {
            try {
              await api(`/api/users/${uid}`, { method: "DELETE" });
              toast(t("User deleted."), "success");
              await reloadPageData();
            } catch (err) {
              toast(err.message, "error");
            }
          },
          t("Delete"),
          true
        );
      });
    });
  }

  function openUserModal(user) {
    const i18n = UI.state.i18n || {};
    const curUserId = UI.state.meta && UI.state.meta.user_id;
    const isSelf = Boolean(user && curUserId && user.id === curUserId);
    const selfRestricted = Boolean(isSelf && !page.canManageUsers);

    page.editingUserId = user ? user.id : null;
    $("modal-user-title").textContent = user ? t("Edit User") : t("Add User");
    $("user-editor-err").classList.add("hidden");

    const roleNames = page.roles.length
      ? page.roles.map((r) => r.name)
      : (user && user.role ? Array.from(new Set([user.role, "Admin", "Operator", "Viewer"])) : ["Admin", "Operator", "Viewer"]);
    fillSelect($("usr-role"), roleNames, false);

    const langOpts = [{ value: "auto", label: t("Auto (OS Default)") }].concat(
      (i18n.available_languages || []).map((l) => ({ value: l.code, label: l.label }))
    );
    fillSelect($("usr-lang"), langOpts, false);
    fillSelect(
      $("usr-theme"),
      [
        { value: "auto", label: t("Auto (OS Default)") },
        { value: "light", label: t("Light") },
        { value: "dark", label: t("Dark") },
      ],
      false
    );

    $("usr-username").value = user ? user.username : "";
    $("usr-username").readOnly = Boolean(user);
    $("usr-display-name").value = user ? (user.display_name || "") : "";
    $("usr-role").value = user && roleNames.includes(user.role) ? user.role : "Viewer";
    $("usr-role").disabled = selfRestricted;
    $("usr-lang").value = (user && user.language) || "auto";
    $("usr-theme").value = (user && user.theme_mode) || "auto";

    $("usr-cur-password").value = "";
    $("usr-cur-password-wrap").classList.toggle("hidden", !selfRestricted);

    $("usr-password").value = "";
    $("usr-password-label").textContent = user ? t("New Password") : t("Password *");
    $("usr-password-hint").classList.toggle("hidden", !user);
    $("usr-active").checked = user ? Boolean(user.is_active) : true;
    $("usr-active").disabled = Boolean(isSelf || selfRestricted);

    openModal("modal-user-editor");
  }

  async function saveUser() {
    $("user-editor-err").classList.add("hidden");
    const curUserId = UI.state.meta && UI.state.meta.user_id;
    const isSelf = Boolean(page.editingUserId && curUserId && page.editingUserId === curUserId);
    const selfRestricted = Boolean(isSelf && !page.canManageUsers);
    const prevLang = (UI.state.meta && UI.state.meta.language) || "auto";

    const body = {
      display_name: $("usr-display-name").value.trim(),
      language: $("usr-lang").value || "auto",
      theme_mode: $("usr-theme").value || "auto",
    };
    if (!page.editingUserId) {
      body.username = $("usr-username").value.trim();
    }
    if (!selfRestricted) {
      body.role = $("usr-role").value;
      body.is_active = $("usr-active").checked;
    }
    const pw = $("usr-password").value;
    if (!page.editingUserId || pw) {
      body.password = pw;
      if (selfRestricted && pw) {
        body.current_password = $("usr-cur-password").value;
      }
    }

    try {
      let updated;
      if (page.editingUserId) {
        updated = await api(`/api/users/${page.editingUserId}`, { method: "PUT", body });
      } else {
        updated = await api("/api/users", { method: "POST", body });
      }
      closeModal("modal-user-editor");
      toast(t("User saved."), "success");

      if (isSelf) {
        UI.applyTheme(updated.theme_mode);
        if (updated.language !== prevLang) {
          window.location.href = selfRestricted
            ? "/administration/users?edit=me"
            : "/administration/users";
          return;
        }
        await UI.loadCoreData();
      }
      await reloadPageData();
    } catch (err) {
      $("user-editor-err").textContent = err.message;
      $("user-editor-err").classList.remove("hidden");
    }
  }

  page.toolbar = wireDataTableToolbar({
    searchInputId: "users-dt-search",
    searchClearId: "users-dt-search-clear",
    filterBtnId: "users-filter-btn",
    filterBadgeId: "users-filter-badge",
    popoverId: "users-filter-popover",
    applyBtnId: "users-filter-apply",
    resetBtnId: "users-filter-reset",
    chipsContainerId: "users-active-filters",
    fields: [
      { id: "flt-usr-role", labelKey: "Role", defaultVal: "All" },
      { id: "flt-usr-status", labelKey: "Status", defaultVal: "All", formatValue: t },
    ],
    onChange: renderUsersTable,
  });

  $("btn-add-user").addEventListener("click", () => openUserModal(null));
  $("btn-save-user").addEventListener("click", saveUser);

  UI.bootstrap(reloadPageData, reloadPageData);
})();
