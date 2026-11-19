/* Roles (/administration/roles) RBAC management controller */

(function () {
  "use strict";

  const UI = window.AetherNMS;
  const { $, t, escHtml, icon, toast, api, openModal, closeModal, showConfirm } = UI;

  const page = {
    roles: [],
    allPermissions: [],
    editingRoleId: null,
  };

  async function reloadPageData() {
    const data = await api("/api/roles");
    page.roles = data.items || [];
    page.allPermissions = data.all_permissions || (UI.state.meta && UI.state.meta.all_permissions) || [];
    renderRolesTable();
  }

  function renderRolesTable() {
    const tbody = $("roles-tbody");
    if (!page.roles.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="6">-</td></tr>`;
      return;
    }
    tbody.innerHTML = page.roles
      .map((r) => {
        const isImmutableAdmin = r.name === "Admin";
        const typeTag = r.is_system
          ? `<span class="cds--tag cds--tag--purple">${escHtml(t("System"))}</span>`
          : `<span class="cds--tag cds--tag--blue">${escHtml(t("Custom"))}</span>`;
        const permsCount = (r.permissions || []).length;
        const editIcon = isImmutableAdmin ? icon("view", 16) : icon("edit", 16);
        const editTitle = isImmutableAdmin ? t("View") : t("Edit");
        const delBtn = r.is_system
          ? ""
          : `<button type="button" class="cds--btn--icon danger act-role-del" data-id="${r.id}" title="${escHtml(t("Delete"))}">${icon("trash-can", 16)}</button>`;
        return `
          <tr>
            <td><strong>${escHtml(r.name)}</strong></td>
            <td>${typeTag}</td>
            <td><span class="cds--tag cds--tag--gray">${permsCount} / ${page.allPermissions.length}</span></td>
            <td>${escHtml(r.user_count != null ? r.user_count : 0)}</td>
            <td>${escHtml(r.description || "")}</td>
            <td class="col-actions">
              <button type="button" class="cds--btn--icon act-role-edit" data-id="${r.id}" title="${escHtml(editTitle)}">${editIcon}</button>
              ${delBtn}
            </td>
          </tr>`;
      })
      .join("");

    tbody.querySelectorAll(".act-role-edit").forEach((btn) => {
      btn.addEventListener("click", () => {
        const r = page.roles.find((x) => x.id === parseInt(btn.getAttribute("data-id"), 10));
        if (r) openRoleModal(r);
      });
    });

    tbody.querySelectorAll(".act-role-del").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rid = parseInt(btn.getAttribute("data-id"), 10);
        const r = page.roles.find((x) => x.id === rid);
        if (!r) return;
        showConfirm(
          t("Delete Role"),
          t("Delete custom role '{name}'?", { name: r.name }),
          async () => {
            try {
              await api(`/api/roles/${rid}`, { method: "DELETE" });
              toast(t("Role deleted."), "success");
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

  function renderPermissionsGrid(selectedKeys, readOnly) {
    const selected = new Set(selectedKeys || []);
    const groups = {};
    page.allPermissions.forEach((p) => {
      const grp = p.group || "General";
      if (!groups[grp]) groups[grp] = [];
      groups[grp].push(p);
    });

    $("role-perms-grid").innerHTML = Object.entries(groups)
      .map(([grpName, perms]) => {
        const itemsHtml = perms
          .map((p) => {
            const chk = selected.has(p.key) ? "checked" : "";
            const dis = readOnly ? "disabled" : "";
            return `
              <label class="checkbox-label">
                <input type="checkbox" class="role-perm-chk" value="${escHtml(p.key)}" ${chk} ${dis} />
                <span>${escHtml(t(p.label))} <code class="mono" style="color:var(--cds-text-helper);">(${escHtml(p.key)})</code></span>
              </label>`;
          })
          .join("");
        return `
          <div class="perm-group-card">
            <h4 class="perm-group-title">${escHtml(t(grpName))}</h4>
            <div class="perm-list">${itemsHtml}</div>
          </div>`;
      })
      .join("");
  }

  function openRoleModal(role) {
    page.editingRoleId = role ? role.id : null;
    const isImmutableAdmin = Boolean(role && role.name === "Admin");
    $("modal-role-title").textContent = role ? (isImmutableAdmin ? `${t("Role")}: Admin` : t("Edit Role")) : t("Add Role");
    $("role-editor-err").classList.add("hidden");

    $("role-name").value = role ? role.name : "";
    $("role-name").readOnly = Boolean(role && role.is_system);
    $("role-desc").value = role ? (role.description || "") : "";
    $("role-desc").readOnly = isImmutableAdmin;

    renderPermissionsGrid(role ? role.permissions : ["jobs:read", "snippets:read", "devices:read"], isImmutableAdmin);
    $("btn-save-role").classList.toggle("hidden", isImmutableAdmin);
    $("btn-role-perms-all").classList.toggle("hidden", isImmutableAdmin);
    $("btn-role-perms-none").classList.toggle("hidden", isImmutableAdmin);

    openModal("modal-role-editor");
  }

  async function saveRole() {
    $("role-editor-err").classList.add("hidden");
    const permissions = Array.from(document.querySelectorAll(".role-perm-chk:checked")).map((cb) => cb.value);
    const body = {
      name: $("role-name").value.trim(),
      description: $("role-desc").value.trim(),
      permissions,
    };
    try {
      if (page.editingRoleId) {
        await api(`/api/roles/${page.editingRoleId}`, { method: "PUT", body });
      } else {
        await api("/api/roles", { method: "POST", body });
      }
      closeModal("modal-role-editor");
      toast(t("Role saved."), "success");
      await reloadPageData();
    } catch (err) {
      $("role-editor-err").textContent = err.message;
      $("role-editor-err").classList.remove("hidden");
    }
  }

  $("btn-add-role").addEventListener("click", () => openRoleModal(null));
  $("btn-save-role").addEventListener("click", saveRole);
  $("btn-role-perms-all").addEventListener("click", () => {
    document.querySelectorAll(".role-perm-chk:not(:disabled)").forEach((cb) => { cb.checked = true; });
  });
  $("btn-role-perms-none").addEventListener("click", () => {
    document.querySelectorAll(".role-perm-chk:not(:disabled)").forEach((cb) => { cb.checked = false; });
  });

  UI.bootstrap(reloadPageData, reloadPageData);
})();
