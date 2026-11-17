"""Template variable extraction (${var}, ${var|type|regex}, ${var|["A","B"]}), validation & rendering."""

from __future__ import annotations

import ast
import re
from typing import Dict, List, Optional, Tuple

from pssh_ui.i18n import _
from pssh_ui.models import HostEntry, VariableSpec


HTML_INPUT_TYPES = frozenset({"text", "password", "number", "email", "url", "tel", "select"})

DEFAULT_TYPE_REGEX: Dict[str, str] = {
    "number": r"^-?\d+(?:\.\d+)?$",
    "email": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    "url": r"^https?://\S+$",
}


def scan_dollar_brace_tokens(text: str) -> List[Tuple[int, int, str]]:
    """
    Scan balanced ${...} tokens so regex quantifiers like {1,32} or {8,64}
    inside ${var|...} do not prematurely terminate parsing.
    Variable names may include uppercase letters, spaces, accents, and punctuation.
    Returns tuples of (start_idx, end_idx_exclusive, inner_text).
    """
    tokens: List[Tuple[int, int, str]] = []
    i = 0
    n = len(text)
    while i < n - 1:
        if text[i] == "$" and text[i + 1] == "{":
            start = i
            i += 2
            depth = 1
            inner_chars: List[str] = []
            while i < n and depth > 0:
                ch = text[i]
                if ch == "\\" and i + 1 < n:
                    inner_chars.append(ch)
                    inner_chars.append(text[i + 1])
                    i += 2
                    continue
                if ch == "{":
                    depth += 1
                    inner_chars.append(ch)
                elif ch == "}":
                    depth -= 1
                    if depth > 0:
                        inner_chars.append(ch)
                else:
                    inner_chars.append(ch)
                i += 1
            if depth == 0:
                tokens.append((start, i, "".join(inner_chars)))
                continue
            i = start + 1
        else:
            i += 1
    return tokens


def _parse_python_list_options(expr: str) -> Optional[List[str]]:
    """Parse Python-style list declarations like '[\"Item 1\", \"Item 2\"]'."""
    stripped = (expr or "").strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    try:
        parsed = ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return None
    if isinstance(parsed, (list, tuple)):
        return [str(item) for item in parsed]
    return None


def _parse_token_spec(inner: str) -> Optional[Tuple[str, str, Optional[str], List[str]]]:
    """
    Parse the inner content of ${...} into (name, field_type, regex, options).
    Supported forms:
      - ${name}
      - ${name|password}
      - ${name|password|regex}
      - ${name|text|regex}
      - ${name|["Item 1", "Item 2"]}
      - ${name|select|["Item 1", "Item 2"]}
      - ${name|regex}
    """
    if "|" not in inner:
        name = inner.strip()
        return (name, "text", None, []) if name else None

    name_part, _sep, rest = inner.partition("|")
    var_name = name_part.strip()
    if not var_name:
        return None

    rest_stripped = rest.strip()
    if not rest_stripped:
        return (var_name, "text", None, [])

    # Check direct Python list declaration: ${name|["Item 1", "Item 2"]}
    opts = _parse_python_list_options(rest_stripped)
    if opts is not None:
        return (var_name, "select", None, opts)

    # Check explicit HTML-like field type: ${name|type} or ${name|type|regex_or_list}
    if "|" in rest_stripped:
        type_part, _sep2, third_part = rest_stripped.partition("|")
        type_candidate = type_part.strip().lower()
        third_stripped = third_part.strip()
        if type_candidate in HTML_INPUT_TYPES:
            if type_candidate == "select":
                opts3 = _parse_python_list_options(third_stripped)
                if opts3 is not None:
                    return (var_name, "select", None, opts3)
            regex_expr = third_stripped or DEFAULT_TYPE_REGEX.get(type_candidate)
            return (var_name, type_candidate, regex_expr, [])
    elif rest_stripped.lower() in HTML_INPUT_TYPES:
        ftype = rest_stripped.lower()
        return (var_name, ftype, DEFAULT_TYPE_REGEX.get(ftype), [])

    # Backwards-compatible fallback: ${name|regex}
    return (var_name, "text", rest_stripped, [])


def extract_variables(template_text: str) -> List[VariableSpec]:
    """
    Extract unique VariableSpec entries from template text in order of appearance.
    Comment lines starting with '!' are skipped so commented-out lines
    do not generate phantom required inputs.
    """
    if not template_text:
        return []

    filtered_lines: List[str] = []
    for raw_line in template_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        filtered_lines.append(raw_line)
    active_text = "\n".join(filtered_lines)

    ordered: Dict[str, VariableSpec] = {}
    for start, end, inner in scan_dollar_brace_tokens(active_text):
        parsed = _parse_token_spec(inner)
        if parsed is None:
            continue
        var_name, field_type, regex_expr, options = parsed
        raw_token = active_text[start:end]

        if var_name not in ordered:
            ordered[var_name] = VariableSpec(
                name=var_name,
                field_type=field_type,
                regex=regex_expr,
                options=options,
                raw_tokens=[raw_token],
            )
        else:
            spec = ordered[var_name]
            if raw_token not in spec.raw_tokens:
                spec.raw_tokens.append(raw_token)
            if field_type != "text" and spec.field_type == "text":
                spec.field_type = field_type
            if regex_expr and not spec.regex:
                spec.regex = regex_expr
            if options and not spec.options:
                spec.options = options

    return list(ordered.values())


def validate_single_value(spec: VariableSpec, value: str) -> Optional[str]:
    """
    Validate a single variable value against its VariableSpec.
    Returns None if valid, or a localized error message if invalid.
    """
    val = "" if value is None else str(value)

    if spec.field_type == "select":
        if not spec.options:
            return _("No options available for '{name}'.").format(name=spec.name)
        if val not in spec.options:
            return _("Select a valid option for '{name}'.").format(name=spec.name)
        return None

    if spec.regex:
        try:
            pattern = re.compile(spec.regex)
        except re.error as exc:
            return _("Invalid regex '{regex}' for '{name}': {err}").format(
                regex=spec.regex, name=spec.name, err=exc
            )
        if pattern.fullmatch(val) is None:
            return _("Value for '{name}' must match regex: {regex}").format(
                name=spec.name, regex=spec.regex
            )
    else:
        if not val.strip():
            return _("Value for '{name}' is required.").format(name=spec.name)
    return None


def validate_variable_values(
    specs: List[VariableSpec],
    values: Dict[str, str],
) -> Dict[str, str]:
    """Validate all VariableSpec entries against provided values. Returns {var_name: error_msg}."""
    errors: Dict[str, str] = {}
    for spec in specs:
        err = validate_single_value(spec, values.get(spec.name, ""))
        if err:
            errors[spec.name] = err
    return errors


def render_template(
    template_text: str,
    values: Dict[str, str],
    host: Optional[HostEntry] = None,
) -> str:
    """
    Substitute ${var}, ${var|type|regex}, and ${var|["A","B"]} placeholders with concrete values.
    Built-in host context fallbacks (${device_name}, ${device_ip}, ${host_model})
    apply when not explicitly overridden in `values`.
    """
    if not template_text:
        return ""

    effective_values: Dict[str, str] = {}
    if host is not None:
        effective_values["device_name"] = host.display_label
        effective_values["device_ip"] = host.ip
        effective_values["host_model"] = host.model
    for k, v in (values or {}).items():
        if v is not None:
            effective_values[k] = str(v)

    rendered = template_text
    tokens = scan_dollar_brace_tokens(rendered)
    for start, end, inner in reversed(tokens):
        var_name = inner.partition("|")[0].strip() if "|" in inner else inner.strip()
        if var_name in effective_values:
            rendered = rendered[:start] + effective_values[var_name] + rendered[end:]
    return rendered
