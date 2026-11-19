/* Jobs page controller: Jobs table, Job Details split view, Device Log viewer, and 4-step Add Job wizard */

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
    statusTagHtml,
    fillSelect,
    openModal,
    closeModal,
    showConfirm,
    wireDataTableToolbar,
    renderPagination,
    pingDevices,
    icon,
    hasPermission,
  } = UI;

  const page = {
    jobs: [],
    snippets: [],
    devices: [],
    selectedJobId: null,
    activeJobSubtab: "details",
    toolbars: {},
    pages: {
      jobs: { page: 1, size: 25 },
      jobDevices: { page: 1, size: 25 },
      wizDevices: { page: 1, size: 25 },
    },
    wizard: {
      stepKey: "command",
      variables: [],
      paramValues: {},
      selectedDeviceIds: new Set(),
      renderedCommands: "",
      renderedAudit: "",
      pinged: false,
    },
    pollTimer: null,
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
    const jobStatusOpts = [
      { value: "All", label: t("All") },
      { value: "Running", label: t("Running") },
      { value: "Success", label: t("Success") },
      { value: "Failed", label: t("Failed") },
    ];
    const devResStatusOpts = [
      { value: "All", label: t("All") },
      { value: "Success", label: t("Success") },
      { value: "Failed", label: t("Failed") },
      { value: "Running", label: t("Running") },
      { value: "Pending", label: t("Pending") },
    ];
    const pingStatusOpts = [
      { value: "All", label: t("All") },
      { value: "Up", label: t("Up") },
      { value: "Down", label: t("Down") },
      { value: "Unknown", label: t("Unknown") },
    ];

    fillSelect($("flt-job-type"), typeOpts, true);
    fillSelect($("flt-job-os"), osOpts, true);
    fillSelect($("flt-job-status"), jobStatusOpts, true);
    fillSelect($("flt-jd-status"), devResStatusOpts, true);
    fillSelect($("wiz-flt-os"), osOpts, true);
    fillSelect($("wiz-flt-status"), pingStatusOpts, true);
    Object.values(page.toolbars).forEach((tb) => tb && tb.sync());
  }

  async function reloadPageData() {
    const [jobsData, snipsData, devsData] = await Promise.all([
      api("/api/jobs"),
      api("/api/snippets"),
      api("/api/devices"),
    ]);
    page.jobs = jobsData.items || [];
    page.snippets = snipsData.items || [];
    page.devices = devsData.items || [];

    populateFilterDropdowns();
    $("btn-add-job").classList.toggle("hidden", !hasPermission("jobs:run"));
    if (!page.selectedJobId && page.jobs.length) {
      page.selectedJobId = page.jobs[0].job_id;
    }
    renderJobsView();
    scheduleJobPolling();
  }

  function scheduleJobPolling() {
    if (page.pollTimer) {
      clearInterval(page.pollTimer);
      page.pollTimer = null;
    }
    if (page.jobs.some((j) => j.status === "Running")) {
      page.pollTimer = setInterval(async () => {
        try {
          const data = await api("/api/jobs");
          page.jobs = data.items || [];
          renderJobsView();
          if (!page.jobs.some((j) => j.status === "Running")) {
            clearInterval(page.pollTimer);
            page.pollTimer = null;
          }
        } catch (_e) {}
      }, 1500);
    }
  }

  function renderJobsView() {
    const q = ($("jobs-dt-search") ? $("jobs-dt-search").value : "").trim().toLowerCase();
    const typeQ = $("flt-job-type").value || "All";
    const osQ = $("flt-job-os").value || "All";
    const stQ = $("flt-job-status").value || "All";

    const filtered = page.jobs.filter((j) => {
      if (q) {
        const platLbl = j.device_type_label || platformLabel(j.device_type);
        const hay = [j.name, t(j.job_type), j.device_type, platLbl, t(j.status), j.snippet_name]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (typeQ !== "All" && j.job_type !== typeQ) return false;
      if (osQ !== "All" && j.device_type !== osQ) return false;
      if (stQ !== "All" && j.status !== stQ) return false;
      return true;
    });

    const pageItems = renderPagination(
      "jobs-pagination",
      filtered,
      page.pages.jobs,
      renderJobsView,
      "Total Records: {total}"
    );
    const tbody = $("jobs-tbody");
    if (!pageItems.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="8">-</td></tr>`;
    } else {
      const canRun = hasPermission("jobs:run");
      const canDel = hasPermission("jobs:delete");
      tbody.innerHTML = pageItems
        .map((j) => {
          const sel = j.job_id === page.selectedJobId ? "selected" : "";
          const platDisp = j.device_type_label || platformLabel(j.device_type);
          const replayBtn = canRun
            ? `<button type="button" class="cds--btn--icon act-replay" data-id="${escHtml(j.job_id)}" title="${escHtml(t("Replay Job"))}">${icon("renew", 16)}</button>`
            : "";
          const stopOrDel =
            j.status === "Running"
              ? (canRun ? `<button type="button" class="cds--btn--icon danger act-stop" data-id="${escHtml(j.job_id)}" title="${escHtml(t("Stop Job"))}">${icon("stop-outline", 16)}</button>` : "")
              : (canDel ? `<button type="button" class="cds--btn--icon danger act-del" data-id="${escHtml(j.job_id)}" title="${escHtml(t("Delete Job"))}">${icon("trash-can", 16)}</button>` : "");
          return `
            <tr class="${sel}" data-job-id="${escHtml(j.job_id)}">
              <td><strong>${escHtml(j.name)}</strong></td>
              <td>${escHtml(t(j.job_type))}</td>
              <td>${escHtml(platDisp)}</td>
              <td>${statusTagHtml(j.status)}</td>
              <td class="nowrap">${escHtml(j.creation_time || "-")}</td>
              <td class="nowrap">${escHtml(j.start_time || "-")}</td>
              <td class="nowrap">${escHtml(j.end_time || "-")}</td>
              <td class="col-actions">
                ${replayBtn}
                ${stopOrDel}
              </td>
            </tr>
          `;
        })
        .join("");

      tbody.querySelectorAll("tr[data-job-id]").forEach((tr) => {
        tr.addEventListener("click", (ev) => {
          if (ev.target.closest("button")) return;
          page.selectedJobId = tr.getAttribute("data-job-id");
          page.pages.jobDevices.page = 1;
          renderJobsView();
        });
      });
      tbody.querySelectorAll(".act-replay").forEach((btn) => {
        btn.addEventListener("click", () => {
          const job = page.jobs.find((x) => x.job_id === btn.getAttribute("data-id"));
          if (job) openAddJobWizard(job);
        });
      });
      tbody.querySelectorAll(".act-stop").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const jid = btn.getAttribute("data-id");
          await api(`/api/jobs/${encodeURIComponent(jid)}/stop`, { method: "POST" });
          toast(t("Stop Job"), "info");
        });
      });
      tbody.querySelectorAll(".act-del").forEach((btn) => {
        btn.addEventListener("click", () => {
          const jid = btn.getAttribute("data-id");
          const job = page.jobs.find((x) => x.job_id === jid);
          if (!job) return;
          showConfirm(
            t("Delete Job"),
            t("Remove job '{name}' from history?", { name: job.name }),
            async () => {
              await api(`/api/jobs/${encodeURIComponent(jid)}`, { method: "DELETE" });
              page.jobs = page.jobs.filter((x) => x.job_id !== jid);
              if (page.selectedJobId === jid) {
                page.selectedJobId = page.jobs.length ? page.jobs[0].job_id : null;
              }
              renderJobsView();
            },
            t("Delete"),
            true
          );
        });
      });
    }
    renderJobDetails();
  }

  function renderJobDetails() {
    const job = page.jobs.find((j) => j.job_id === page.selectedJobId) || null;
    $("job-details-title").textContent = job ? `${t("Job Details")} — ${job.name}` : t("Job Details");
    if (!job) {
      $("jd-total").textContent = "0";
      $("jd-ok").textContent = "0";
      $("jd-fail").textContent = "0";
      $("jd-meta-extra").textContent = "";
      $("jd-desc").textContent = "-";
      $("jd-cmds").innerHTML = "";
      $("jd-audit-wrap").classList.add("hidden");
      $("job-devices-tbody").innerHTML = `<tr class="empty-row"><td colspan="7">-</td></tr>`;
      $("job-devices-pagination").innerHTML = "";
      return;
    }

    $("jd-total").textContent = String(job.counts.total);
    $("jd-ok").textContent = String(job.counts.success);
    $("jd-fail").textContent = String(job.counts.failed);
    const platDisp = job.device_type_label || platformLabel(job.device_type);
    const metaBits = [job.snippet_name, platDisp, job.schedule_sequence].filter(Boolean);
    $("jd-meta-extra").textContent = metaBits.join("  |  ");
    $("jd-desc").textContent = job.description || "-";
    $("jd-cmds").innerHTML = highlightCliHtml(job.commands_rendered || job.commands_raw || "");

    if (job.audit_regex && job.audit_regex.trim()) {
      $("jd-audit-wrap").classList.remove("hidden");
      $("jd-audit").innerHTML = highlightCliHtml(job.audit_regex);
    } else {
      $("jd-audit-wrap").classList.add("hidden");
    }

    const q = ($("jd-dt-search") ? $("jd-dt-search").value : "").trim().toLowerCase();
    const stQ = $("flt-jd-status").value || "All";
    const results = (job.results || []).filter((r) => {
      if (q) {
        const hay = [r.host_name, r.host_ip, r.host_protocol, r.operation_result_localized, r.operation_result]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (stQ !== "All" && r.status !== stQ) return false;
      return true;
    });

    const pageRes = renderPagination(
      "job-devices-pagination",
      results,
      page.pages.jobDevices,
      renderJobDetails,
      "Total Records: {total}"
    );
    const tbody = $("job-devices-tbody");
    if (!pageRes.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="7">-</td></tr>`;
      return;
    }
    tbody.innerHTML = pageRes
      .map(
        (r) => `
      <tr>
        <td>${escHtml(r.host_name)}</td>
        <td class="mono">${escHtml(`${r.host_ip}:${r.host_port} (${r.host_protocol})`)}</td>
        <td>${statusTagHtml(r.status)}</td>
        <td class="nowrap">${escHtml(r.started_at || "-")}</td>
        <td class="nowrap">${escHtml(r.finished_at || "-")}</td>
        <td>${escHtml(r.operation_result_localized || r.operation_result || "-")}</td>
        <td class="col-actions">
          <button type="button" class="cds--btn--icon act-log" data-rid="${r.id}" title="${escHtml(t("Device Log"))}">${icon("document", 16)}</button>
        </td>
      </tr>`
      )
      .join("");

    tbody.querySelectorAll(".act-log").forEach((btn) => {
      btn.addEventListener("click", () => openDeviceLogModal(job.job_id, btn.getAttribute("data-rid")));
    });
  }

  async function openDeviceLogModal(jobId, resultId) {
    try {
      const data = await api(`/api/jobs/${encodeURIComponent(jobId)}/results/${encodeURIComponent(resultId)}/log`);
      $("log-modal-title").textContent = `${t("Device Log")} — ${data.host_name} (${data.host_ip}:${data.host_port} · ${data.host_protocol})`;
      const errs = data.error_lines || [];
      const banner = $("log-banner");
      if (errs.length) {
        banner.style.color = "var(--cds-support-error)";
        banner.textContent = `⚠ ${errs.length} ${errs.length === 1 ? "error" : "errors"}: ${errs[0].reason || errs[0].text || ""}`;
      } else {
        banner.style.color = data.status === "Success" ? "var(--cds-support-success)" : "var(--cds-text-primary)";
        banner.textContent = data.operation_result_localized || data.operation_result || data.status;
      }
      $("log-conn-meta").textContent = `${t("Connection:")} ${data.connection_method}   |   ${t("Port")}: ${data.host_port}`;
      $("btn-download-log").href = `/api/jobs/${encodeURIComponent(jobId)}/results/${encodeURIComponent(resultId)}/log?download=1`;
      $("btn-download-log").setAttribute("download", data.filename || "device.log");

      const content = data.formatted_log || data.raw_output || data.exception_message || "";
      const errSet = new Set(errs.map((e) => e.line_no).filter((n) => n != null));
      const lines = content.split(/\r?\n/);
      const rawStartIdx = lines.findIndex((ln) => ln.startsWith("--- Raw ") && ln.endsWith("Terminal Output ---"));
      $("log-terminal").innerHTML = lines
        .map((ln, idx) => {
          const lineNo = idx + 1;
          const rawLineNo = rawStartIdx >= 0 ? lineNo - (rawStartIdx + 1) : lineNo;
          const isErr = errSet.has(rawLineNo) && rawLineNo > 0;
          return `<div class="log-line ${isErr ? "error-line" : ""}"><span class="log-line-num">${lineNo}</span><span>${escHtml(ln)}</span></div>`;
        })
        .join("");
      openModal("modal-log");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ---------- ADD JOB 4-STEP WIZARD ----------
  function wizardActiveStepKeys() {
    return page.wizard.variables.length > 0
      ? ["command", "params", "devices", "confirm"]
      : ["command", "devices", "confirm"];
  }

  function renderWizardHeader() {
    const defs = {
      command: t("Config Command"),
      params: t("Parameters"),
      devices: t("Select Device"),
      confirm: t("Confirm"),
    };
    const keys = wizardActiveStepKeys();
    const curIdx = Math.max(0, keys.indexOf(page.wizard.stepKey));
    const bar = $("wizard-steps-bar");
    bar.innerHTML = keys
      .map((k, idx) => {
        const cls = idx === curIdx ? "active" : (idx < curIdx ? "completed" : "");
        return `<button type="button" class="wizard-step ${cls}" data-step="${k}"><span class="step-circle">${idx + 1}</span><span>${escHtml(defs[k])}</span></button>`;
      })
      .join("");
    bar.querySelectorAll(".wizard-step.completed").forEach((btn) => {
      btn.addEventListener("click", () => goToWizardStep(btn.getAttribute("data-step")));
    });
  }

  function populateWizardSnippets() {
    const plat = $("wiz-os").value;
    const jtype = document.querySelector('input[name="wiz-job-type"]:checked').value;
    const matching = page.snippets.filter((s) => s.device_type === plat && s.snippet_type === jtype);
    fillSelect(
      $("wiz-snippet"),
      [{ value: "", label: "" }].concat(matching.map((s) => ({ value: String(s.id), label: s.name }))),
      false
    );
    $("wiz-snippet-desc").textContent = matching.length ? "" : `${t(jtype)} / ${platformLabel(plat)}: 0`;
  }

  async function refreshWizardVariables() {
    const cmds = $("wiz-cmds").value;
    const audit = document.querySelector('input[name="wiz-job-type"]:checked').value === "Audit and Remediate"
      ? $("wiz-audit").value
      : "";
    try {
      const parsed = await api("/api/variables/parse", {
        method: "POST",
        body: { commands: cmds, audit_regex: audit, values: page.wizard.paramValues },
      });
      page.wizard.variables = parsed.variables || [];
      page.wizard.renderedCommands = parsed.rendered_commands || "";
      page.wizard.renderedAudit = parsed.rendered_audit_regex || "";
      for (const v of page.wizard.variables) {
        if (!(v.name in page.wizard.paramValues)) {
          page.wizard.paramValues[v.name] = v.is_secret ? "" : (v.default_value || "");
        }
      }
      renderWizardHeader();
      return parsed;
    } catch (_e) {
      return { variables: [], errors: {} };
    }
  }

  function renderWizardParamsStep(parsedErrors) {
    const box = $("wiz-params-container");
    if (!page.wizard.variables.length) {
      box.innerHTML = `<p class="cds--helper-text">${escHtml(t("No variables required by this snippet. Click Next to select devices."))}</p>`;
      return;
    }
    box.innerHTML = page.wizard.variables
      .map((v, idx) => {
        const val = page.wizard.paramValues[v.name] || "";
        const err = (parsedErrors || {})[v.name];
        const statusBadge = err
          ? `<span style="color:var(--cds-support-error);font-size:12px;">&#10007; ${escHtml(err)}</span>`
          : `<span style="color:var(--cds-support-success);font-size:12px;">&#10003;</span>`;
        if (v.field_type === "select" && v.options && v.options.length) {
          const opts = v.options
            .map((o) => `<option value="${escHtml(o)}" ${o === val ? "selected" : ""}>${escHtml(o)}</option>`)
            .join("");
          return `
            <div class="cds--form-item">
              <label class="cds--label" for="wp-${idx}">${escHtml(v.name)} *</label>
              <select id="wp-${idx}" class="cds--select-input wiz-param-input" data-vname="${escHtml(v.name)}">
                <option value=""></option>${opts}
              </select>
              <div class="wp-status" data-vname="${escHtml(v.name)}">${statusBadge}</div>
            </div>`;
        }
        const inputType = v.field_type === "password" ? "password" : (["number", "email", "url"].includes(v.field_type) ? v.field_type : "text");
        const toggleBtn = v.field_type === "password"
          ? `<button type="button" class="cds--btn cds--btn--ghost cds--btn--sm wp-toggle" data-target="wp-${idx}">${escHtml(t("Show"))}</button>`
          : "";
        return `
          <div class="cds--form-item">
            <label class="cds--label" for="wp-${idx}">${escHtml(v.name)} *</label>
            <div style="display:flex;gap:6px;">
              <input id="wp-${idx}" class="cds--text-input wiz-param-input" type="${inputType}" data-vname="${escHtml(v.name)}" value="${escHtml(val)}" autocomplete="off" />
              ${toggleBtn}
            </div>
            <div class="wp-status" data-vname="${escHtml(v.name)}">${statusBadge}</div>
          </div>`;
      })
      .join("");

    box.querySelectorAll(".wiz-param-input").forEach((inp) => {
      inp.addEventListener("input", async () => {
        page.wizard.paramValues[inp.getAttribute("data-vname")] = inp.value;
        const p = await refreshWizardVariables();
        box.querySelectorAll(".wp-status").forEach((stEl) => {
          const vn = stEl.getAttribute("data-vname");
          const er = (p.errors || {})[vn];
          stEl.innerHTML = er
            ? `<span style="color:var(--cds-support-error);font-size:12px;">&#10007; ${escHtml(er)}</span>`
            : `<span style="color:var(--cds-support-success);font-size:12px;">&#10003;</span>`;
        });
      });
    });
    box.querySelectorAll(".wp-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const inp = $(btn.getAttribute("data-target"));
        const isPw = inp.type === "password";
        inp.type = isPw ? "text" : "password";
        btn.textContent = t(isPw ? "Hide" : "Show");
      });
    });
  }

  function getWizardFilteredDevices() {
    const targetOs = $("wiz-os").value.toLowerCase();
    const q = ($("wiz-dt-search") ? $("wiz-dt-search").value : "").trim().toLowerCase();
    const oq = $("wiz-flt-os").value || "All";
    const gq = $("wiz-flt-group").value.trim().toLowerCase();
    const sq = $("wiz-flt-status").value || "All";

    const list = page.devices.filter((d) => {
      if (q) {
        const hay = [d.name, d.ip, d.os_type, d.os_type_label || platformLabel(d.os_type), d.folder_path]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (oq !== "All" && d.os_type !== oq) return false;
      if (gq && !(d.folder_path || "").toLowerCase().includes(gq)) return false;
      if (sq !== "All" && (d.ping_status || "Unknown") !== sq) return false;
      return true;
    });
    list.sort((a, b) => {
      const am = (a.os_type || "").toLowerCase() === targetOs ? 0 : 1;
      const bm = (b.os_type || "").toLowerCase() === targetOs ? 0 : 1;
      if (am !== bm) return am - bm;
      return (a.display_label || "").localeCompare(b.display_label || "");
    });
    return list;
  }

  function renderWizardDevices() {
    $("wiz-target-os-hint").textContent = t("Snippet Target Platform: {os}", {
      os: platformLabel($("wiz-os").value),
    });
    const filtered = getWizardFilteredDevices();
    const pageItems = renderPagination(
      "wiz-devices-pagination",
      filtered,
      page.pages.wizDevices,
      renderWizardDevices,
      "Total Records: {total}"
    );
    const tbody = $("wiz-devices-tbody");
    if (!pageItems.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="7">-</td></tr>`;
      return;
    }
    tbody.innerHTML = pageItems
      .map((d) => {
        const chk = page.wizard.selectedDeviceIds.has(d.id) ? "checked" : "";
        const platDisp = d.os_type_label || platformLabel(d.os_type);
        return `
          <tr>
            <td class="col-check"><input type="checkbox" class="wiz-dev-chk" data-id="${d.id}" ${chk} /></td>
            <td><strong>${escHtml(d.display_label)}</strong></td>
            <td>${statusTagHtml(d.ping_status || "Unknown")}</td>
            <td class="mono">${escHtml(d.ip)}</td>
            <td class="mono">${escHtml(`${d.protocol}:${d.port}`)}</td>
            <td>${escHtml(platDisp || "-")}</td>
            <td>${escHtml(d.folder_path || "")}</td>
          </tr>`;
      })
      .join("");

    tbody.querySelectorAll(".wiz-dev-chk").forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = parseInt(cb.getAttribute("data-id"), 10);
        if (cb.checked) page.wizard.selectedDeviceIds.add(id);
        else page.wizard.selectedDeviceIds.delete(id);
      });
    });
  }

  async function goToWizardStep(stepKey) {
    page.wizard.stepKey = stepKey;
    $("wizard-error").classList.add("hidden");
    ["command", "params", "devices", "confirm"].forEach((k) => {
      $(`wiz-step-${k}`).classList.toggle("hidden", k !== stepKey);
    });
    const keys = wizardActiveStepKeys();
    const idx = keys.indexOf(stepKey);
    $("wiz-back-btn").disabled = idx <= 0;
    $("wiz-next-btn").classList.toggle("hidden", idx >= keys.length - 1);
    $("wiz-run-btn").classList.toggle("hidden", idx < keys.length - 1);
    renderWizardHeader();

    if (stepKey === "params") {
      const parsed = await refreshWizardVariables();
      renderWizardParamsStep(parsed.errors || {});
    } else if (stepKey === "devices") {
      renderWizardDevices();
      if (!page.wizard.pinged) {
        page.wizard.pinged = true;
        pingDevices(
          getWizardFilteredDevices().slice(0, page.pages.wizDevices.size),
          page.devices,
          () => {
            if ($("modal-add-job").classList.contains("open") && page.wizard.stepKey === "devices") {
              renderWizardDevices();
            }
          }
        );
      }
    } else if (stepKey === "confirm") {
      const parsed = await refreshWizardVariables();
      const jtype = document.querySelector('input[name="wiz-job-type"]:checked').value;
      $("wiz-save-cfg-wrap").classList.toggle("hidden", jtype !== "Config");
      const selCount = page.wizard.selectedDeviceIds.size;
      const snipOpt = $("wiz-snippet").selectedOptions[0];
      $("wiz-confirm-summary").textContent =
        `${t("Job Name")}: ${$("wiz-name").value.trim()}   |   ${t("Netmiko Platform")}: ${platformLabel($("wiz-os").value)}   |   ` +
        `${t("Snippets")}: ${(snipOpt && snipOpt.textContent) || "-"}   |   ${t("Devices")}: ${selCount}`;
      $("wiz-confirm-preview").innerHTML = highlightCliHtml(parsed.rendered_commands || "");
    }
  }

  async function openAddJobWizard(replayJob) {
    const meta = UI.state.meta || {};
    const settings = UI.state.settings || {};
    page.wizard = {
      stepKey: "command",
      variables: [],
      paramValues: {},
      selectedDeviceIds: new Set(),
      renderedCommands: "",
      renderedAudit: "",
      pinged: false,
    };
    const choices = meta.job_platform_choices || ["aruba_procurve", "aruba_aoscx"];
    fillSelect($("wiz-os"), platformOptions(choices), false);

    if (replayJob) {
      document.querySelectorAll('input[name="wiz-job-type"]').forEach((r) => {
        r.checked = r.value === replayJob.job_type;
      });
      $("wiz-os").value = choices.includes(replayJob.device_type) ? replayJob.device_type : choices[0];
      populateWizardSnippets();
      $("wiz-name").value = replayJob.name || "";
      $("wiz-desc").value = replayJob.description || "";
      if (replayJob.snippet_name) {
        const matchOpt = Array.from($("wiz-snippet").options).find((o) => o.textContent === replayJob.snippet_name);
        if (matchOpt) $("wiz-snippet").value = matchOpt.value;
      }
      $("wiz-cmds").value = replayJob.commands_raw || replayJob.commands_rendered || "";
      $("wiz-audit").value = replayJob.audit_regex || "";
      $("wiz-audit-wrap").classList.toggle("hidden", replayJob.job_type !== "Audit and Remediate");

      for (const [k, v] of Object.entries(replayJob.parameters_masked || {})) {
        if (v !== "••••••••") page.wizard.paramValues[k] = v;
      }
      const resKeys = new Set((replayJob.results || []).map((r) => r.host_key));
      const resIps = new Set((replayJob.results || []).map((r) => r.host_ip));
      page.devices.forEach((d) => {
        if (resKeys.has(d.unique_key) || resIps.has(d.ip)) page.wizard.selectedDeviceIds.add(d.id);
      });
      $("wiz-max-parallel").value = replayJob.max_parallel || settings.max_parallel || 10;
      $("wiz-seq").checked = replayJob.schedule_sequence === "Sequential";
      $("wiz-max-parallel").disabled = $("wiz-seq").checked;
      $("wiz-save-cfg").checked = Boolean(replayJob.include_write);
    } else {
      document.querySelectorAll('input[name="wiz-job-type"]').forEach((r) => {
        r.checked = r.value === "Config";
      });
      $("wiz-os").value = choices[0] || "aruba_procurve";
      populateWizardSnippets();
      $("wiz-name").value = "";
      $("wiz-desc").value = "";
      $("wiz-cmds").value = "";
      $("wiz-audit").value = "";
      $("wiz-audit-wrap").classList.add("hidden");
      $("wiz-max-parallel").value = settings.max_parallel || 10;
      $("wiz-seq").checked = settings.schedule_sequence === "Sequential";
      $("wiz-max-parallel").disabled = $("wiz-seq").checked;
      $("wiz-save-cfg").checked = false;
    }

    $("wiz-ssh-user").value = settings.ssh_username || "";
    $("wiz-ssh-pass").value = "";
    $("wiz-enable-pass").value = "";
    await refreshWizardVariables();
    await goToWizardStep("command");
    openModal("modal-add-job");
  }

  function wirePageEvents() {
    page.toolbars.jobs = wireDataTableToolbar({
      searchInputId: "jobs-dt-search",
      searchClearId: "jobs-dt-search-clear",
      filterBtnId: "jobs-filter-btn",
      filterBadgeId: "jobs-filter-badge",
      popoverId: "jobs-filter-popover",
      applyBtnId: "jobs-filter-apply",
      resetBtnId: "jobs-filter-reset",
      chipsContainerId: "jobs-active-filters",
      fields: [
        { id: "flt-job-type", labelKey: "Job Type", defaultVal: "All", formatValue: t },
        { id: "flt-job-os", labelKey: "Netmiko Platform", defaultVal: "All", formatValue: platformLabel },
        { id: "flt-job-status", labelKey: "Status", defaultVal: "All", formatValue: t },
      ],
      onChange: () => { page.pages.jobs.page = 1; renderJobsView(); },
    });

    page.toolbars.jobDevices = wireDataTableToolbar({
      searchInputId: "jd-dt-search",
      searchClearId: "jd-dt-search-clear",
      filterBtnId: "jd-filter-btn",
      filterBadgeId: "jd-filter-badge",
      popoverId: "jd-filter-popover",
      applyBtnId: "jd-filter-apply",
      resetBtnId: "jd-filter-reset",
      chipsContainerId: "jd-active-filters",
      fields: [
        { id: "flt-jd-status", labelKey: "Status", defaultVal: "All", formatValue: t },
      ],
      onChange: () => { page.pages.jobDevices.page = 1; renderJobDetails(); },
    });

    page.toolbars.wizDevices = wireDataTableToolbar({
      searchInputId: "wiz-dt-search",
      searchClearId: "wiz-dt-search-clear",
      filterBtnId: "wiz-filter-btn",
      filterBadgeId: "wiz-filter-badge",
      popoverId: "wiz-filter-popover",
      applyBtnId: "wiz-filter-apply",
      resetBtnId: "wiz-filter-reset",
      chipsContainerId: "wiz-active-filters",
      fields: [
        { id: "wiz-flt-os", labelKey: "Netmiko Platform", defaultVal: "All", formatValue: platformLabel },
        { id: "wiz-flt-group", labelKey: "Group", defaultVal: "" },
        { id: "wiz-flt-status", labelKey: "Status", defaultVal: "All", formatValue: t },
      ],
      onChange: () => { page.pages.wizDevices.page = 1; renderWizardDevices(); },
    });

    document.querySelectorAll("[data-job-subtab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        page.activeJobSubtab = btn.getAttribute("data-job-subtab");
        document.querySelectorAll("[data-job-subtab]").forEach((b) => b.classList.toggle("active", b === btn));
        $("job-subtab-details").classList.toggle("hidden", page.activeJobSubtab !== "details");
        $("job-subtab-devices").classList.toggle("hidden", page.activeJobSubtab !== "devices");
      });
    });
    $("btn-add-job").addEventListener("click", () => openAddJobWizard(null));

    document.querySelectorAll('input[name="wiz-job-type"]').forEach((r) => {
      r.addEventListener("change", async () => {
        $("wiz-audit-wrap").classList.toggle("hidden", r.value !== "Audit and Remediate");
        populateWizardSnippets();
        await refreshWizardVariables();
      });
    });
    $("wiz-os").addEventListener("change", populateWizardSnippets);
    $("wiz-snippet").addEventListener("change", async () => {
      const sid = parseInt($("wiz-snippet").value, 10);
      const snip = page.snippets.find((s) => s.id === sid);
      if (snip) {
        $("wiz-snippet-desc").textContent = snip.description || "";
        $("wiz-cmds").value = snip.commands || "";
        $("wiz-audit").value = snip.audit_regex || "";
        if (!$("wiz-desc").value.trim() && snip.description) $("wiz-desc").value = snip.description;
      } else {
        $("wiz-snippet-desc").textContent = "";
      }
      await refreshWizardVariables();
    });
    ["wiz-cmds", "wiz-audit"].forEach((id) => {
      $(id).addEventListener("input", () => { refreshWizardVariables(); });
    });
    $("wiz-dev-select-all").addEventListener("click", () => {
      getWizardFilteredDevices().forEach((d) => page.wizard.selectedDeviceIds.add(d.id));
      renderWizardDevices();
    });
    $("wiz-dev-clear-sel").addEventListener("click", () => {
      page.wizard.selectedDeviceIds.clear();
      renderWizardDevices();
    });
    $("wiz-seq").addEventListener("change", () => {
      $("wiz-max-parallel").disabled = $("wiz-seq").checked;
    });
    $("wiz-back-btn").addEventListener("click", () => {
      const keys = wizardActiveStepKeys();
      const idx = keys.indexOf(page.wizard.stepKey);
      if (idx > 0) goToWizardStep(keys[idx - 1]);
    });
    $("wiz-next-btn").addEventListener("click", async () => {
      $("wizard-error").classList.add("hidden");
      const keys = wizardActiveStepKeys();
      const cur = page.wizard.stepKey;
      const idx = keys.indexOf(cur);

      if (cur === "command") {
        if (!$("wiz-name").value.trim()) {
          $("wizard-error").textContent = t("Job Name") + " *";
          $("wizard-error").classList.remove("hidden");
          return;
        }
        if (!$("wiz-cmds").value.trim()) {
          $("wizard-error").textContent = t("Config Commands *");
          $("wizard-error").classList.remove("hidden");
          return;
        }
        await refreshWizardVariables();
        const updatedKeys = wizardActiveStepKeys();
        await goToWizardStep(updatedKeys[1]);
        return;
      }

      if (cur === "params") {
        const parsed = await refreshWizardVariables();
        const errs = Object.values(parsed.errors || {});
        if (errs.length) {
          $("wizard-error").textContent = errs.join(" | ");
          $("wizard-error").classList.remove("hidden");
          return;
        }
      }

      if (cur === "devices") {
        if (page.wizard.selectedDeviceIds.size === 0) {
          $("wizard-error").textContent = t("Select Devices");
          $("wizard-error").classList.remove("hidden");
          return;
        }
        const selected = page.devices.filter((d) => page.wizard.selectedDeviceIds.has(d.id));
        const downHosts = selected.filter((d) => d.ping_status === "Down");
        if (downHosts.length) {
          const names = downHosts.map((d) => `• ${d.display_label} (${d.ip})`).join("\n");
          showConfirm(
            t("Offline Device Warning"),
            `${t("One or more selected devices are currently Down (offline). Do you want to continue anyway?")}\n\n${names}`,
            () => goToWizardStep("confirm"),
            t("Next >"),
            false
          );
          return;
        }
      }

      if (idx >= 0 && idx + 1 < keys.length) {
        await goToWizardStep(keys[idx + 1]);
      }
    });

    $("wiz-run-btn").addEventListener("click", async () => {
      $("wizard-error").classList.add("hidden");
      const jtype = document.querySelector('input[name="wiz-job-type"]:checked').value;
      const snipOpt = $("wiz-snippet").selectedOptions[0];
      const payload = {
        name: $("wiz-name").value.trim(),
        description: $("wiz-desc").value.trim(),
        job_type: jtype,
        device_type: $("wiz-os").value,
        snippet_name: (snipOpt && snipOpt.value ? snipOpt.textContent : ""),
        commands_raw: $("wiz-cmds").value,
        audit_regex: jtype === "Audit and Remediate" ? $("wiz-audit").value : "",
        values: page.wizard.paramValues,
        device_ids: Array.from(page.wizard.selectedDeviceIds),
        username: $("wiz-ssh-user").value.trim(),
        password: $("wiz-ssh-pass").value,
        enable_password: $("wiz-enable-pass").value,
        max_parallel: parseInt($("wiz-max-parallel").value, 10) || 10,
        schedule_sequence: $("wiz-seq").checked ? "Sequential" : "Concurrent",
        include_write: jtype === "Config" && $("wiz-save-cfg").checked,
      };
      try {
        const created = await api("/api/jobs", { method: "POST", body: payload });
        closeModal("modal-add-job");
        page.selectedJobId = created.job_id;
        toast(`${t("Run Job")}: ${created.name}`, "success");
        await UI.loadCoreData();
        await reloadPageData();
      } catch (err) {
        $("wizard-error").textContent = (err.errors && err.errors.join(" | ")) || err.message;
        $("wizard-error").classList.remove("hidden");
      }
    });
  }

  wirePageEvents();
  UI.bootstrap(reloadPageData, reloadPageData);
})();
