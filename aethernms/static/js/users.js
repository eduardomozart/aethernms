/* Users (/administration/users) RBAC management controller */

(function () {
  "use strict";

  const UI = window.AetherNMS;
  const { $, t, escHtml, icon, toast, api, statusTagHtml, fillSelect, openModal, closeModal, showConfirm } = UI;

  const page = {
    users: [],
    roles: [],
    editingUserId: null,
  };

  async function reloadPageData() {
    const [usersData, rolesData] = await Promise.all([
      api("/api/users"),
      api("/api/roles"),
    ]);
    page.users = usersData.items || [];
    page.roles = rolesData.items || [];
    renderUsersTable();
  }

  function renderUsersTable() {
    const tbody = $("users-tbody");
    const curUserId = UI.state.meta && UI.state.meta.user_id;
    if (!page.users.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="6">-</td></tr>`;
      return;
    }
    tbody.innerHTML = page.users
      .map((u) => {
        const isSelf = u.id === curUserId;
        const delBtn = isSelf
          ? ""
          : `<button type="button" class="cds--btn--icon danger act-usr-del" data-id="${u.id}" title="${escHtml(t("Delete"))}">${icon("trash-can", 16)}</button>`;
        return `
          <tr>
            <td><strong>${escHtml(u.username)}</strong>${isSelf ? ` <span class="cds--tag cds--tag--gray">${escHtml(t("You"))}</span>` : ""}</td>
            <td>${escHtml(u.display_name || "-")}</td>
            <td><span class="cds--tag cds--tag--blue">${escHtml(u.role)}</span></td>
            <td>${statusTagHtml(u.is_active ? "Active" : "Disabled")}</td>
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
    page.editingUserId = user ? user.id : null;
    $("modal-user-title").textContent = user ? t("Edit User") : t("Add User");
    $("user-editor-err").classList.add("hidden");

    const roleNames = page.roles.length
      ? page.roles.map((r) => r.name)
      : ["Admin", "Operator", "Viewer"];
    fillSelect($("usr-role"), roleNames, false);

    $("usr-username").value = user ? user.username : "";
    $("usr-username").readOnly = Boolean(user);
    $("usr-display-name").value = user ? (user.display_name || "") : "";
    $("usr-role").value = user && roleNames.includes(user.role) ? user.role : "Viewer";
    $("usr-password").value = "";
    $("usr-password-label").textContent = user ? t("New Password") : t("Password *");
    $("usr-password-hint").classList.toggle("hidden", !user);
    $("usr-active").checked = user ? Boolean(user.is_active) : true;
    const isSelf = user && UI.state.meta && user.id === UI.state.meta.user_id;
    $("usr-active").disabled = Boolean(isSelf);

    openModal("modal-user-editor");
  }

  async function saveUser() {
    $("user-editor-err").classList.add("hidden");
    const body = {
      username: $("usr-username").value.trim(),
      display_name: $("usr-display-name").value.trim(),
      role: $("usr-role").value,
      is_active: $("usr-active").checked,
    };
    const pw = $("usr-password").value;
    if (!page.editingUserId || pw) {
      body.password = pw;
    }
    try {
      if (page.editingUserId) {
        await api(`/api/users/${page.editingUserId}`, { method: "PUT", body });
      } else {
        await api("/api/users", { method: "POST", body });
      }
      closeModal("modal-user-editor");
      toast(t("User saved."), "success");
      await reloadPageData();
    } catch (err) {
      $("user-editor-err").textContent = err.message;
      $("user-editor-err").classList.remove("hidden");
    }
  }

  $("btn-add-user").addEventListener("click", () => openUserModal(null));
  $("btn-save-user").addEventListener("click", saveUser);

  UI.bootstrap(reloadPageData, reloadPageData);
})();
