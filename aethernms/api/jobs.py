"""Jobs execution, cancellation, history, and SQLite per-device log (/api/jobs*) REST API routes."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Any, List
import uuid

from py4web.core import action, request, response

from aethernms.api.common import (
    CtxGetter,
    activate_request_locale,
    json_error,
    json_response,
    read_json_body,
    require_api_user,
    serialize_job,
)
from aethernms.common import format_operation_result_ui
from aethernms.job_builder import build_commands_for_job, validate_job_inputs
from aethernms.logger import format_host_log, sanitize_log_filename
from aethernms.models import (
    HostEntry,
    HostExecutionResult,
    JobRecord,
    ScheduleSequence,
    SnippetType,
)
from aethernms.netmiko_catalog import (
    canonical_platform,
    is_supported_platform,
    normalize_legacy_platform,
)
from aethernms.parser import detect_output_errors, parse_commands
from aethernms.variables import extract_variables, render_template


def register_jobs_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register /api/jobs* routes."""

    @action("/api/jobs", method="GET")
    @action.uses(session)
    def api_list_jobs():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="jobs:read")
        if err:
            return err
        activate_request_locale(ctx)
        jobs = ctx.db.list_jobs()
        return json_response({"items": [serialize_job(j, include_results=True) for j in jobs]})

    @action("/api/jobs", method="POST")
    @action.uses(session)
    def api_create_job():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="jobs:run")
        if err:
            return err
        activate_request_locale(ctx)
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")

        job_name = str(body.get("name") or "").strip()
        if not job_name:
            return json_error(400, "Job Name is required.", errors=["Job Name is required."])

        raw_type = str(body.get("job_type") or SnippetType.CONFIG.value).strip()
        job_type = (
            SnippetType.AUDIT
            if raw_type.lower() == SnippetType.AUDIT.value.lower()
            else SnippetType.CONFIG
        )
        raw_plat = str(body.get("device_type") or "").strip()
        plat = canonical_platform(raw_plat) or normalize_legacy_platform(raw_plat)[0]
        if not plat or not is_supported_platform(plat):
            return json_error(400, f"Unsupported Netmiko platform: '{raw_plat}'.")

        raw_commands = str(body.get("commands_raw") or "")
        raw_audit = str(body.get("audit_regex") or "") if job_type == SnippetType.AUDIT else ""
        values_raw = body.get("values") if isinstance(body.get("values"), dict) else {}
        values = {str(k): ("" if v is None else str(v)) for k, v in values_raw.items()}

        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        enable_password = str(body.get("enable_password") or "")

        all_hosts = ctx.db.list_devices()
        hosts_by_id = {h.id: h for h in all_hosts if h.id is not None}
        hosts_by_key = {h.unique_key: h for h in all_hosts}
        selected_hosts: List[HostEntry] = []
        seen_keys: set[str] = set()

        for did in body.get("device_ids") or []:
            try:
                h = hosts_by_id.get(int(did))
            except (TypeError, ValueError):
                h = None
            if h is not None and h.unique_key not in seen_keys:
                seen_keys.add(h.unique_key)
                selected_hosts.append(h)

        for dkey in body.get("device_keys") or []:
            h = hosts_by_key.get(str(dkey).strip())
            if h is not None and h.unique_key not in seen_keys:
                seen_keys.add(h.unique_key)
                selected_hosts.append(h)

        val_errors = validate_job_inputs(
            raw_commands=f"{raw_commands}\n{raw_audit}" if raw_audit.strip() else raw_commands,
            selected_hosts=selected_hosts,
            values=values,
            username=username,
            password=password,
        )
        if val_errors:
            return json_error(400, val_errors[0], errors=val_errors)

        settings = ctx.db.get_settings()
        raw_seq = str(body.get("schedule_sequence") or settings.schedule_sequence.value).strip().lower()
        seq = (
            ScheduleSequence.SEQUENTIAL
            if raw_seq == ScheduleSequence.SEQUENTIAL.value.lower()
            else ScheduleSequence.CONCURRENT
        )
        try:
            max_parallel = max(1, int(body.get("max_parallel") or settings.max_parallel or 10))
        except (TypeError, ValueError):
            max_parallel = settings.max_parallel
        if seq == ScheduleSequence.SEQUENTIAL:
            max_parallel = 1
        include_write = bool(job_type == SnippetType.CONFIG and body.get("include_write", False))

        specs = extract_variables(f"{raw_commands}\n{raw_audit}")
        secret_names = {sp.name for sp in specs if sp.is_secret}
        ctx.db.save_parameters(values, secret_names=secret_names)

        cmd_map = build_commands_for_job(raw_commands, values, selected_hosts)
        template_counts_map = {h.unique_key: len(cmd_map.get(h.unique_key, [])) for h in selected_hosts}
        audit_regex_map = (
            {h.unique_key: render_template(raw_audit, values, host=h) for h in selected_hosts}
            if raw_audit.strip()
            else {}
        )
        masked_params = {
            k: ("••••••••" if k in secret_names else v) for k, v in values.items()
        }
        display_values = {
            k: ("********" if k in secret_names else v) for k, v in values.items()
        }
        commands_rendered = "\n".join(
            parse_commands(render_template(raw_commands, display_values))
        )
        audit_rendered = render_template(raw_audit, display_values) if raw_audit else ""

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job_uid = uuid.uuid4().hex[:10]
        initial_results = [
            HostExecutionResult(
                host=h,
                status="Pending",
                commands_run=cmd_map.get(h.unique_key, []),
                operation_result="Queued",
                connection_method=f"{h.protocol.value} ({h.os_type or '-'})",
            )
            for h in selected_hosts
        ]
        job_record = JobRecord(
            job_id=job_uid,
            name=job_name,
            job_type=job_type,
            device_type=plat,
            status="Running",
            creation_time=now_str,
            start_time=now_str,
            end_time="",
            description=str(body.get("description") or "").strip(),
            snippet_name=str(body.get("snippet_name") or "").strip(),
            commands_raw=raw_commands,
            commands_rendered=commands_rendered,
            audit_regex=audit_rendered,
            max_parallel=max_parallel,
            schedule_sequence=seq,
            include_write=include_write,
            parameters_masked=masked_params,
            results=initial_results,
        )
        created = ctx.db.create_job(job_record, secret_names=secret_names)

        cancel_evt = threading.Event()
        with ctx.lock:
            ctx.running_jobs[job_uid] = cancel_evt

        conn_to = settings.connect_timeout
        cmd_to = settings.command_timeout

        def _worker() -> None:
            try:
                executor = ctx.executor_factory()
                _run_dir, results = executor.run_batch(
                    hosts=selected_hosts,
                    username=username,
                    password=password,
                    commands_by_host=cmd_map,
                    max_parallel=max_parallel,
                    schedule_sequence=seq,
                    connect_timeout=conn_to,
                    command_timeout=cmd_to,
                    cancel_event=cancel_evt,
                    on_host_start=lambda h: ctx.db.update_job_result_running(
                        job_uid, h.unique_key
                    ),
                    on_host_complete=lambda r: ctx.db.update_job_result(job_uid, r),
                    audit_regex_by_host=audit_regex_map,
                    enable_password=enable_password,
                    job_type=job_type,
                    include_write=include_write,
                    template_counts_by_host=template_counts_map,
                )
                ctx.db.finalize_job(
                    job_uid,
                    results,
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception as exc:
                err_results = [
                    HostExecutionResult(
                        host=h,
                        status="Failed",
                        operation_result=f"Execution error: {exc}",
                        exception_message=str(exc),
                        connection_method=f"{h.protocol.value} ({h.os_type or '-'})",
                    )
                    for h in selected_hosts
                ]
                ctx.db.finalize_job(
                    job_uid,
                    err_results,
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            finally:
                with ctx.lock:
                    ctx.running_jobs.pop(job_uid, None)
                    ctx.job_threads.pop(job_uid, None)

        th = threading.Thread(target=_worker, daemon=True, name=f"aethernms-job-{job_uid}")
        with ctx.lock:
            ctx.job_threads[job_uid] = th
        th.start()

        return json_response(serialize_job(created, include_results=True), status=201)

    @action("/api/jobs/<job_uid>", method="GET")
    @action.uses(session)
    def api_get_job(job_uid: str):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="jobs:read")
        if err:
            return err
        activate_request_locale(ctx)
        job = ctx.db.get_job(job_uid)
        if job is None:
            return json_error(404, "Job not found.")
        return json_response(serialize_job(job, include_results=True))

    @action("/api/jobs/<job_uid>/stop", method="POST")
    @action.uses(session)
    def api_stop_job(job_uid: str):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="jobs:run")
        if err:
            return err
        job = ctx.db.get_job(job_uid)
        if job is None:
            return json_error(404, "Job not found.")
        with ctx.lock:
            evt = ctx.running_jobs.get(job_uid)
        if evt is not None:
            evt.set()
        return json_response({"ok": True, "stopping": evt is not None})

    @action("/api/jobs/<job_uid>", method="DELETE")
    @action.uses(session)
    def api_delete_job(job_uid: str):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="jobs:delete")
        if err:
            return err
        with ctx.lock:
            is_running = job_uid in ctx.running_jobs
        if is_running:
            return json_error(400, "Stop the running job before deleting it.")
        if not ctx.db.delete_job(job_uid):
            return json_error(404, "Job not found.")
        return json_response({"ok": True})

    @action("/api/jobs/<job_uid>/results/<result_id:int>/log", method="GET")
    @action.uses(session)
    def api_get_job_result_log(job_uid: str, result_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="jobs:read")
        if err:
            return err
        activate_request_locale(ctx)
        res = ctx.db.get_job_result(job_uid, result_id)
        if res is None:
            return json_error(404, "Job result not found.")
        formatted = res.formatted_log or format_host_log(res)
        filename = sanitize_log_filename(res.host)
        dl = str(request.query.get("download") or "").strip().lower() in ("1", "true", "yes")
        if dl:
            response.status = 200
            response.headers["Content-Type"] = "text/plain; charset=utf-8"
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
            return formatted

        errs = res.error_lines or detect_output_errors(res.raw_output or formatted)
        return json_response(
            {
                "id": res.id,
                "filename": filename,
                "host_name": res.host.display_label,
                "host_ip": res.host.ip,
                "host_port": int(res.host.port),
                "host_os": res.host.os_type,
                "host_protocol": res.host.protocol.value,
                "status": res.status,
                "started_at": res.started_at,
                "finished_at": res.finished_at,
                "operation_result": res.operation_result,
                "operation_result_localized": format_operation_result_ui(res.operation_result),
                "connection_method": res.connection_method
                or f"{res.host.protocol.value} ({res.host.os_type or '-'})",
                "exception_message": res.exception_message,
                "raw_output": res.raw_output,
                "formatted_log": formatted,
                "error_lines": errs,
                "step_results": [
                    {
                        "index": s.index,
                        "command": s.command,
                        "result": s.result,
                        "suggestion": s.suggestion,
                        "begin_time": s.begin_time,
                        "finish_time": s.finish_time,
                        "output_snippet": s.output_snippet,
                    }
                    for s in res.step_results
                ],
            }
        )
