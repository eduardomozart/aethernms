/* System Settings (/administration/settings) page controller */

(function () {
  "use strict";

  const UI = window.AetherNMS;
  const { $, t, toast, api, fillSelect } = UI;

  let apiEnabledState = false;

  function setApiToggleUi(enabled) {
    apiEnabledState = Boolean(enabled);
    const btn = $("set-api-enabled");
    const sw = $("set-api-switch");
    const lbl = $("set-api-state-text");
    if (btn) btn.setAttribute("aria-checked", apiEnabledState ? "true" : "false");
    if (sw) sw.classList.toggle("cds--toggle__switch--checked", apiEnabledState);
    if (lbl) lbl.textContent = t(apiEnabledState ? "Enabled" : "Disabled");
    if ($("set-swagger-link")) {
      $("set-swagger-link").classList.toggle("hidden", !apiEnabledState);
    }
  }

  function populateSettingsForm() {
    const s = UI.state.settings || {};
    const i18n = UI.state.i18n || {};

    const langOpts = [{ value: "auto", label: t("Auto (OS Default)") }].concat(
      (i18n.available_languages || []).map((l) => ({ value: l.code, label: l.label }))
    );
    fillSelect($("set-lang"), langOpts, false);
    $("set-lang").value = s.language || "auto";

    fillSelect(
      $("set-theme"),
      [
        { value: "auto", label: t("Auto (OS Default)") },
        { value: "light", label: t("Light") },
        { value: "dark", label: t("Dark") },
      ],
      false
    );
    $("set-theme").value = s.theme_mode || "auto";

    $("set-user").value = s.ssh_username || "";
    $("set-parallel").value = s.max_parallel || 10;
    $("set-conn-to").value = s.connect_timeout || 10;
    $("set-cmd-to").value = s.command_timeout || 15;
    $("set-proto").value = s.default_protocol || "SSH";
    $("set-ssh-port").value = s.ssh_port || 22;
    $("set-telnet-port").value = s.telnet_port || 23;

    setApiToggleUi(Boolean(s.api_enabled));
    $("set-api-allowed-ips").value = s.api_allowed_ips || "127.0.0.1, ::1";
    if ($("set-client-ip")) {
      $("set-client-ip").textContent = s.client_ip || (UI.state.meta && UI.state.meta.client_ip) || "127.0.0.1";
    }
  }

  async function saveSettings() {
    const msg = $("settings-msg");
    msg.classList.add("hidden");
    const body = {
      language: $("set-lang").value,
      theme_mode: $("set-theme").value,
      ssh_username: $("set-user").value.trim(),
      max_parallel: parseInt($("set-parallel").value, 10) || 10,
      connect_timeout: parseInt($("set-conn-to").value, 10) || 10,
      command_timeout: parseInt($("set-cmd-to").value, 10) || 15,
      default_protocol: $("set-proto").value,
      ssh_port: parseInt($("set-ssh-port").value, 10) || 22,
      telnet_port: parseInt($("set-telnet-port").value, 10) || 23,
      api_enabled: apiEnabledState,
      api_allowed_ips: $("set-api-allowed-ips").value.trim() || "127.0.0.1, ::1",
    };
    try {
      await api("/api/settings", { method: "PUT", body });
      await UI.loadCoreData();
      populateSettingsForm();
      msg.className = "cds--inline-notification cds--inline-notification--success";
      msg.textContent = t("Settings saved.");
      msg.classList.remove("hidden");
      toast(t("Settings saved."), "success");
    } catch (err) {
      msg.className = "cds--inline-notification cds--inline-notification--error";
      msg.textContent = err.message;
      msg.classList.remove("hidden");
      toast(err.message, "error");
    }
  }

  function wireEvents() {
    $("set-api-enabled").addEventListener("click", () => {
      setApiToggleUi(!apiEnabledState);
    });
    $("btn-save-settings").addEventListener("click", saveSettings);
  }

  wireEvents();
  UI.bootstrap(populateSettingsForm, populateSettingsForm);
})();
