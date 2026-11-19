/* 3-Step Initial Setup Guide (/setup) controller */

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  let catalog = {};
  let effLang = "";
  let setupInfo = null;
  let currentStep = 1;
  let lastSelectedEngine = "sqlite";
  let lastTestedFingerprint = null;
  let lastTestOk = false;

  try {
    const initEl = $("anms-initial-i18n");
    if (initEl && initEl.textContent) {
      const initData = JSON.parse(initEl.textContent);
      catalog = initData.catalog || {};
      effLang = initData.effective_language || "";
    }
  } catch (_e) {}

  function t(key, vars) {
    let text = (catalog && catalog[key]) || key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        text = text.replaceAll(`{${k}}`, String(v));
      }
    }
    return text;
  }

  function escHtml(str) {
    return String(str == null ? "" : str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function applyI18nDom() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
    document.title = `${t("Initial Setup Guide")} - aether`;
  }

  function clearError() {
    $("setup-error").classList.add("hidden");
    $("setup-error-msg").textContent = "";
  }

  function showError(msg) {
    $("setup-error-msg").textContent = msg;
    $("setup-error").classList.remove("hidden");
  }

  function clearTestBanner() {
    $("setup-db-test-result").classList.add("hidden");
    $("setup-db-test-msg").textContent = "";
  }

  function showTestBanner(ok, msg) {
    const box = $("setup-db-test-result");
    box.className = `cds--inline-notification ${
      ok ? "cds--inline-notification--success" : "cds--inline-notification--error"
    }`;
    $("setup-db-test-msg").textContent = msg;
    box.classList.remove("hidden");
  }

  function getSelectedEngineSpec() {
    const engId = ($("setup-engine").value || "sqlite").toLowerCase();
    const list = (setupInfo && setupInfo.engines) || [];
    return list.find((e) => e.id === engId) || { id: engId, label: engId, driver_available: true };
  }

  function maskCustomUri(raw) {
    const text = String(raw || "").trim();
    if (!text) return "";
    const low = text.toLowerCase();
    if (low.startsWith("sqlite://") || low.startsWith("sqlite:memory")) return text;
    const schemeIdx = text.indexOf("://");
    if (schemeIdx === -1) return text;
    const scheme = text.slice(0, schemeIdx);
    const rest = text.slice(schemeIdx + 3);
    const slashIdx = rest.indexOf("/");
    const qIdx = rest.indexOf("?");
    let splitAt = rest.length;
    if (slashIdx !== -1) splitAt = Math.min(splitAt, slashIdx);
    if (qIdx !== -1) splitAt = Math.min(splitAt, qIdx);
    const authority = rest.slice(0, splitAt);
    const tail = rest.slice(splitAt).replace(/\b(pwd|password|passwd)=([^&;]*)/gi, "$1=********");
    const atIdx = authority.lastIndexOf("@");
    if (atIdx !== -1) {
      const userinfo = authority.slice(0, atIdx);
      const hostport = authority.slice(atIdx + 1);
      const colonIdx = userinfo.indexOf(":");
      const maskedAuth =
        colonIdx !== -1 ? `${userinfo.slice(0, colonIdx)}:********@${hostport}` : `${userinfo}@${hostport}`;
      return `${scheme}://${maskedAuth}${tail}`;
    }
    return `${scheme}://${rest.replace(/\b(pwd|password|passwd)=([^&;]*)/gi, "$1=********")}`;
  }

  function buildPreviewMaskedUri() {
    if (setupInfo && setupInfo.db_locked && setupInfo.current_uri_masked) {
      return setupInfo.current_uri_masked;
    }
    const spec = getSelectedEngineSpec();
    const eng = spec.id;
    if (eng === "sqlite") {
      const p = ($("setup-sqlite-path").value || "").trim() || (setupInfo && setupInfo.default_sqlite_path) || "";
      if (p.toLowerCase().startsWith("sqlite://") || p.toLowerCase().startsWith("sqlite:memory")) return p;
      return `sqlite://${p.replaceAll("\\", "/")}`;
    }
    if (eng === "custom") {
      return maskCustomUri($("setup-custom-uri").value);
    }
    const host = ($("setup-db-host").value || "").trim();
    const port = ($("setup-db-port").value || spec.default_port || "").toString().trim();
    const dbName = ($("setup-db-name").value || "").trim().replace(/^\/+/, "");
    const user = ($("setup-db-user").value || "").trim();
    const pass = $("setup-db-pass").value || "";
    const hostPart = host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
    const authPart = pass ? `${encodeURIComponent(user)}:********` : encodeURIComponent(user);
    const queryParts = [];
    const extra = ($("setup-db-extra").value || "").trim().replace(/^\?/, "");
    if (eng === "mssql" && !/(?:^|[&;])driver=/i.test(extra)) {
      const drv = ($("setup-odbc-driver").value || spec.default_odbc_driver || "ODBC Driver 17 for SQL Server").trim();
      const wrapped = drv.startsWith("{") && drv.endsWith("}") ? drv : `{${drv}}`;
      queryParts.push(`DRIVER=${wrapped}`);
    }
    if (extra) queryParts.push(extra);
    let uri = `${spec.scheme}://${authPart}@${hostPart}:${port}/${dbName}`;
    if (queryParts.length) uri += `?${queryParts.join("&")}`;
    return uri;
  }

  function collectDbPayload() {
    const eng = ($("setup-engine").value || "sqlite").toLowerCase();
    return {
      engine: eng,
      sqlite_path: ($("setup-sqlite-path").value || "").trim(),
      host: ($("setup-db-host").value || "").trim(),
      port: ($("setup-db-port").value || "").trim(),
      database: ($("setup-db-name").value || "").trim(),
      db_username: ($("setup-db-user").value || "").trim(),
      db_password: $("setup-db-pass").value || "",
      odbc_driver: ($("setup-odbc-driver").value || "").trim(),
      extra_params: ($("setup-db-extra").value || "").trim(),
      custom_uri: ($("setup-custom-uri").value || "").trim(),
    };
  }

  function getDbFingerprint() {
    if (setupInfo && setupInfo.db_locked) {
      return "__locked__";
    }
    return JSON.stringify(collectDbPayload());
  }

  function invalidateDbTestState() {
    lastTestOk = false;
    lastTestedFingerprint = null;
  }

  function updateEngineUi(resetPort) {
    invalidateDbTestState();
    clearTestBanner();
    clearError();
    const spec = getSelectedEngineSpec();
    const eng = spec.id;
    const isLocked = Boolean(setupInfo && setupInfo.db_locked);

    $("setup-sqlite-wrap").classList.toggle("hidden", eng !== "sqlite");
    $("setup-netdb-wrap").classList.toggle("hidden", eng === "sqlite" || eng === "custom");
    $("setup-custom-wrap").classList.toggle("hidden", eng !== "custom");
    $("setup-odbc-wrap").classList.toggle("hidden", eng !== "mssql");

    if (resetPort && spec.default_port) {
      $("setup-db-port").value = String(spec.default_port);
    }
    if (eng === "mssql" && !$("setup-odbc-driver").value) {
      $("setup-odbc-driver").value = spec.default_odbc_driver || "ODBC Driver 17 for SQL Server";
    }

    const badge = $("setup-driver-badge");
    const hint = $("setup-driver-hint");
    if (eng === "custom") {
      badge.className = "cds--tag cds--tag--blue";
      badge.textContent = t("Custom Adapter URI");
      hint.classList.add("hidden");
      hint.textContent = "";
    } else if (spec.driver_available) {
      badge.className = "cds--tag cds--tag--green";
      badge.textContent = t("Driver Installed");
      const installed = (spec.installed_drivers || []).join(", ");
      if (installed) {
        hint.textContent = installed;
        hint.classList.remove("hidden");
      } else {
        hint.classList.add("hidden");
      }
    } else {
      badge.className = "cds--tag cds--tag--red";
      badge.textContent = t("Driver Missing");
      if (spec.pip_install) {
        hint.textContent = spec.pip_install;
        hint.classList.remove("hidden");
      } else {
        hint.classList.add("hidden");
      }
    }

    const dbInputs = [
      "setup-engine",
      "setup-sqlite-path",
      "setup-db-host",
      "setup-db-port",
      "setup-db-name",
      "setup-db-user",
      "setup-db-pass",
      "setup-odbc-driver",
      "setup-db-extra",
      "setup-custom-uri",
    ];
    dbInputs.forEach((id) => {
      if ($(id)) $(id).disabled = isLocked;
    });
    lastSelectedEngine = eng;
  }

  function validateStep1() {
    clearError();
    if (setupInfo && setupInfo.db_locked) return true;
    const spec = getSelectedEngineSpec();
    const eng = spec.id;

    if (eng !== "custom" && !spec.driver_available) {
      showError(
        t("Required Python driver is missing ({cmd}). Install it first or choose SQLite.", {
          cmd: spec.pip_install || (spec.checked_drivers || []).join(", "),
        })
      );
      return false;
    }

    if (eng === "sqlite") {
      if (!($("setup-sqlite-path").value || "").trim()) {
        showError(t("SQLite database path is required."));
        $("setup-sqlite-path").focus();
        return false;
      }
      return true;
    }

    if (eng === "custom") {
      const uri = ($("setup-custom-uri").value || "").trim();
      if (!uri || (!uri.includes("://") && !uri.toLowerCase().startsWith("sqlite:memory"))) {
        showError(t("Custom PyDAL URI must include a scheme such as 'scheme://...'."));
        $("setup-custom-uri").focus();
        return false;
      }
      return true;
    }

    const host = ($("setup-db-host").value || "").trim();
    const port = parseInt(($("setup-db-port").value || "").trim(), 10);
    const dbName = ($("setup-db-name").value || "").trim();
    const user = ($("setup-db-user").value || "").trim();
    if (!host) {
      showError(t("Database host is required."));
      $("setup-db-host").focus();
      return false;
    }
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      showError(t("Database port must be between 1 and 65535."));
      $("setup-db-port").focus();
      return false;
    }
    if (!dbName) {
      showError(t("Database name is required."));
      $("setup-db-name").focus();
      return false;
    }
    if (!user) {
      showError(t("Database username is required."));
      $("setup-db-user").focus();
      return false;
    }
    return true;
  }

  function validateStep2() {
    clearError();
    const username = ($("setup-admin-user").value || "").trim();
    const password = $("setup-admin-pass").value || "";
    const confirm = $("setup-admin-confirm").value || "";
    if (!username) {
      showError(t("Username is required."));
      $("setup-admin-user").focus();
      return false;
    }
    if (password.length < 6) {
      showError(t("Password must be at least 6 characters long."));
      $("setup-admin-pass").focus();
      return false;
    }
    if (password !== confirm) {
      showError(t("Passwords do not match."));
      $("setup-admin-confirm").focus();
      return false;
    }
    return true;
  }

  function renderStepsBar() {
    const steps = [
      { num: 1, label: t("Database Backend") },
      { num: 2, label: t("Administrator Account") },
      { num: 3, label: t("Review & Complete") },
    ];
    $("setup-steps-bar").innerHTML = steps
      .map((s) => {
        const cls =
          s.num === currentStep ? "active" : s.num < currentStep ? "completed" : "";
        return `
          <button type="button" class="wizard-step ${cls}" data-step="${s.num}">
            <span class="step-circle">${s.num < currentStep ? "✓" : s.num}</span>
            <span>${escHtml(s.label)}</span>
          </button>
        `;
      })
      .join("");

    $("setup-steps-bar")
      .querySelectorAll(".wizard-step")
      .forEach((btn) => {
        btn.addEventListener("click", () => {
          const target = parseInt(btn.getAttribute("data-step"), 10);
          if (target < currentStep) {
            goToStep(target);
          }
        });
      });
  }

  function populateReviewSummary() {
    const spec = getSelectedEngineSpec();
    const disp = ($("setup-admin-display").value || "").trim();
    $("sum-db-engine").textContent = t(spec.label || spec.id);
    $("sum-db-uri").textContent = buildPreviewMaskedUri();
    $("sum-admin-user").textContent = ($("setup-admin-user").value || "").trim();
    $("sum-admin-display").textContent = disp || "-";
  }

  function goToStep(step) {
    currentStep = step;
    clearError();
    $("setup-step-1").classList.toggle("hidden", step !== 1);
    $("setup-step-2").classList.toggle("hidden", step !== 2);
    $("setup-step-3").classList.toggle("hidden", step !== 3);
    renderStepsBar();

    if (step === 2) {
      $("setup-admin-user").focus();
    } else if (step === 3) {
      populateReviewSummary();
    }
  }

  async function handleTestConnection() {
    clearError();
    clearTestBanner();
    const fingerprint = getDbFingerprint();
    const btn = $("btn-setup-test-db");
    btn.disabled = true;
    try {
      const payload = setupInfo && setupInfo.db_locked ? {} : collectDbPayload();
      const res = await fetch("/setup/test-db", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        invalidateDbTestState();
        showTestBanner(false, t(data.error || "Connection test failed."));
        return false;
      }
      const ok = Boolean(data.ok);
      const msg = data.message || (ok ? t("Connection succeeded.") : t("Connection failed."));
      showTestBanner(ok, msg);
      if (ok) {
        lastTestOk = true;
        lastTestedFingerprint = fingerprint;
      } else {
        invalidateDbTestState();
      }
      return ok;
    } catch (err) {
      invalidateDbTestState();
      showTestBanner(false, String(err));
      return false;
    } finally {
      btn.disabled = false;
    }
  }

  async function handleCompleteSetup() {
    if (!validateStep1() || !validateStep2()) return;
    clearError();
    const btn = $("btn-setup-complete");
    btn.disabled = true;
    try {
      const body = Object.assign(
        setupInfo && setupInfo.db_locked ? {} : collectDbPayload(),
        {
          username: ($("setup-admin-user").value || "").trim(),
          display_name: ($("setup-admin-display").value || "").trim(),
          password: $("setup-admin-pass").value || "",
          confirm_password: $("setup-admin-confirm").value || "",
        }
      );
      const res = await fetch("/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(t(data.error || "Setup failed."));
        return;
      }
      window.location.href = data.redirect || "/jobs";
    } catch (err) {
      showError(String(err));
    } finally {
      btn.disabled = false;
    }
  }

  function getPreferredBrowserLang() {
    const params = new URLSearchParams(window.location.search);
    const queryLang = (params.get("lang") || "").trim();
    if (queryLang) return queryLang;
    if (Array.isArray(navigator.languages) && navigator.languages.length) {
      return navigator.languages.join(",");
    }
    return (navigator.language || navigator.userLanguage || "").trim();
  }

  async function init() {
    const preferredLang = getPreferredBrowserLang();
    const firstToken = (preferredLang.split(",")[0] || "").trim().replaceAll("-", "_").toLowerCase();
    const effNorm = effLang.toLowerCase();
    if (preferredLang && (!effNorm || (firstToken && !firstToken.startsWith(effNorm.split("_")[0])))) {
      try {
        const i18nRes = await fetch(`/i18n?lang=${encodeURIComponent(preferredLang)}`);
        if (i18nRes.ok) {
          const i18nData = await i18nRes.json();
          catalog = i18nData.catalog || {};
          if (i18nData.effective_language) {
            document.documentElement.setAttribute(
              "lang",
              i18nData.effective_language.replaceAll("_", "-")
            );
          }
        }
      } catch (_e) {}
    }

    applyI18nDom();

    try {
      const infoRes = await fetch("/setup/info");
      if (infoRes.status === 403) {
        window.location.href = "/login";
        return;
      }
      if (infoRes.ok) {
        setupInfo = await infoRes.json();
      }
    } catch (err) {
      showError(String(err));
    }

    const engines = (setupInfo && setupInfo.engines) || [
      { id: "sqlite", label: "SQLite (Local — Default)", driver_available: true },
    ];
    const sel = $("setup-engine");
    sel.innerHTML = engines
      .map((e) => `<option value="${escHtml(e.id)}">${escHtml(t(e.label))}</option>`)
      .join("");

    const initialEng = (setupInfo && setupInfo.current_engine) || "sqlite";
    if (Array.from(sel.options).some((o) => o.value === initialEng)) {
      sel.value = initialEng;
    }

    $("setup-sqlite-path").value =
      (setupInfo && (setupInfo.current_sqlite_path || setupInfo.default_sqlite_path)) || "";

    if (setupInfo && setupInfo.db_locked) {
      $("setup-db-locked-msg").textContent = t(
        "Database backend is configured via environment variable or CLI flag: {uri}",
        { uri: setupInfo.current_uri_masked || "" }
      );
      $("setup-db-locked-banner").classList.remove("hidden");
    }

    [
      "setup-sqlite-path",
      "setup-db-host",
      "setup-db-port",
      "setup-db-name",
      "setup-db-user",
      "setup-db-pass",
      "setup-odbc-driver",
      "setup-db-extra",
      "setup-custom-uri",
    ].forEach((id) => {
      if ($(id)) {
        $(id).addEventListener("input", invalidateDbTestState);
        $(id).addEventListener("change", invalidateDbTestState);
      }
    });

    sel.addEventListener("change", () => {
      updateEngineUi(sel.value !== lastSelectedEngine);
    });
    $("btn-setup-test-db").addEventListener("click", handleTestConnection);
    $("btn-setup-step1-next").addEventListener("click", async () => {
      if (!validateStep1()) return;
      const fp = getDbFingerprint();
      if (lastTestOk && lastTestedFingerprint === fp) {
        goToStep(2);
        return;
      }
      const nextBtn = $("btn-setup-step1-next");
      nextBtn.disabled = true;
      try {
        const ok = await handleTestConnection();
        if (ok) {
          goToStep(2);
        }
      } finally {
        nextBtn.disabled = false;
      }
    });
    $("btn-setup-step2-back").addEventListener("click", () => goToStep(1));
    $("setup-admin-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      if (validateStep2()) goToStep(3);
    });
    $("btn-setup-step3-back").addEventListener("click", () => goToStep(2));
    $("btn-setup-complete").addEventListener("click", handleCompleteSetup);

    updateEngineUi(true);
    goToStep(1);
  }

  init();
})();
