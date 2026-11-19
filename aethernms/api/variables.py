"""Template Variable Extraction, Validation, and Preview (/api/variables/parse) REST API route."""

from __future__ import annotations

from typing import Any, Dict

from py4web.core import action

from aethernms.api.common import (
    CtxGetter,
    activate_request_locale,
    json_error,
    json_response,
    read_json_body,
    require_api_user,
)
from aethernms.parser import parse_commands
from aethernms.variables import extract_variables, render_template, validate_variable_values


def register_variables_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register POST /api/variables/parse route."""

    @action("/api/variables/parse", method="POST")
    @action.uses(session)
    def api_parse_variables():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session)
        if err:
            return err
        activate_request_locale(ctx)
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        commands = str(body.get("commands") or "")
        audit_regex = str(body.get("audit_regex") or "")
        values_in = body.get("values") if isinstance(body.get("values"), dict) else {}

        specs = extract_variables(f"{commands}\n{audit_regex}")
        saved_params = ctx.db.get_saved_parameters()
        merged_values: Dict[str, str] = {}
        for sp in specs:
            if sp.name in values_in and values_in[sp.name] is not None:
                merged_values[sp.name] = str(values_in[sp.name])
            elif not sp.is_secret and sp.name in saved_params:
                merged_values[sp.name] = saved_params[sp.name]
            else:
                merged_values[sp.name] = ""

        val_errors = validate_variable_values(specs, merged_values)
        display_values = {
            sp.name: ("********" if sp.is_secret and merged_values.get(sp.name) else merged_values.get(sp.name, ""))
            for sp in specs
        }
        rendered_cmds = "\n".join(parse_commands(render_template(commands, display_values)))
        rendered_audit = render_template(audit_regex, display_values) if audit_regex.strip() else ""
        return json_response(
            {
                "variables": [
                    {
                        "name": sp.name,
                        "field_type": sp.field_type,
                        "regex": sp.regex,
                        "options": list(sp.options),
                        "is_secret": sp.is_secret,
                        "default_value": "" if sp.is_secret else saved_params.get(sp.name, ""),
                    }
                    for sp in specs
                ],
                "errors": val_errors,
                "rendered_commands": rendered_cmds,
                "rendered_audit_regex": rendered_audit,
            }
        )
