"""Tests for ${var|type|regex} and ${var|['Item 1', 'Item 2']} parsing, validation, and rendering."""

from pssh_ui.models import HostEntry
from pssh_ui.variables import (
    extract_variables,
    render_template,
    validate_single_value,
    validate_variable_values,
)


def test_extract_html_types_password_and_uppercase_accents():
    tpl = (
        "! Comentário com ${Variável Ignorada|text|^[a-z]+$}\n"
        'snmpv3 user "${Usuário SNMP|text|^[A-Za-z0-9_.-]{1,32}$}" '
        'auth sha "${Auth Password|password|^.{8,64}$}" '
        'priv aes "${Privacy Password|password|^.{8,64}$}"\n'
        "vlan ${VLAN ID|number}\n"
        "syslocation ${Localização Física}\n"
        "banner %percent_literal%\n"
    )
    specs = extract_variables(tpl)
    names = [s.name for s in specs]
    assert names == [
        "Usuário SNMP",
        "Auth Password",
        "Privacy Password",
        "VLAN ID",
        "Localização Física",
    ]
    assert "percent_literal" not in names

    by_name = {s.name: s for s in specs}
    assert by_name["Usuário SNMP"].field_type == "text"
    assert by_name["Usuário SNMP"].regex == "^[A-Za-z0-9_.-]{1,32}$"
    assert by_name["Usuário SNMP"].is_secret is False

    # Password behavior is strictly controlled by HTML-like |password type, never guessed from name
    assert by_name["Auth Password"].field_type == "password"
    assert by_name["Auth Password"].is_secret is True
    assert by_name["Auth Password"].regex == "^.{8,64}$"
    assert by_name["Privacy Password"].is_secret is True

    assert by_name["VLAN ID"].field_type == "number"
    assert by_name["Localização Física"].field_type == "text"
    assert by_name["Localização Física"].regex is None

    rendered = render_template(
        tpl,
        {
            "Usuário SNMP": "operador_v3",
            "Auth Password": "ExemploAuth123!",
            "Privacy Password": "ExemploPriv456!",
            "VLAN ID": "100",
            "Localização Física": "Data Center - Sala 2",
            "percent_literal": "IGNORE",
        },
    )
    assert 'snmpv3 user "operador_v3" auth sha "ExemploAuth123!" priv aes "ExemploPriv456!"' in rendered
    assert "vlan 100" in rendered
    assert "syslocation Data Center - Sala 2" in rendered
    assert "banner %percent_literal%" in rendered


def test_extract_and_validate_python_list_select_variables():
    tpl = (
        'stp mode ${STP Mode|["mstp", "rpvst"]}\n'
        'snmp level ${Security Level|select|["priv", "auth"]}\n'
    )
    specs = extract_variables(tpl)
    by_name = {s.name: s for s in specs}

    assert by_name["STP Mode"].field_type == "select"
    assert by_name["STP Mode"].options == ["mstp", "rpvst"]
    assert by_name["Security Level"].field_type == "select"
    assert by_name["Security Level"].options == ["priv", "auth"]

    errs = validate_variable_values(
        specs, {"STP Mode": "invalid_mode", "Security Level": "priv"}
    )
    assert "STP Mode" in errs
    assert "Security Level" not in errs

    ok = validate_variable_values(
        specs, {"STP Mode": "rpvst", "Security Level": "priv"}
    )
    assert ok == {}

    rendered = render_template(tpl, {"STP Mode": "rpvst", "Security Level": "priv"})
    assert "stp mode rpvst" in rendered
    assert "snmp level priv" in rendered


def test_backwards_compatible_regex_and_html_type_validation():
    specs = extract_variables(
        "vlan ${ID da VLAN|^[0-9]{1,4}$}\n"
        "contact ${Admin Email|email}\n"
        "name ${Nome da VLAN}\n"
        "pass ${Secret Token|password|^.{8,64}$}"
    )
    errs = validate_variable_values(
        specs,
        {
            "ID da VLAN": "abc",
            "Admin Email": "not-an-email",
            "Nome da VLAN": "",
            "Secret Token": "short",
        },
    )
    assert set(errs.keys()) == {"ID da VLAN", "Admin Email", "Nome da VLAN", "Secret Token"}

    errs_ok = validate_variable_values(
        specs,
        {
            "ID da VLAN": "100",
            "Admin Email": "noc@example.org",
            "Nome da VLAN": "CORPORATE",
            "Secret Token": "ValidExamplePass!123",
        },
    )
    assert errs_ok == {}

    bad_spec = extract_variables("cmd ${broken|text|[unclosed}")[0]
    err_msg = validate_single_value(bad_spec, "anything")
    assert err_msg is not None and "Invalid regex" in err_msg


def test_render_template_substitutes_host_context():
    tpl = "hostname ${device_name}\nlogging source-ip ${device_ip}\n"
    host = HostEntry(name="SW-EDGE-01", ip="10.20.30.40", os_type="aruba_procurve")
    rendered = render_template(tpl, {}, host=host)
    assert "hostname SW-EDGE-01" in rendered
    assert "logging source-ip 10.20.30.40" in rendered
