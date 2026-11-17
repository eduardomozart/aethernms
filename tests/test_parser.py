"""Tests for ! comment parsing and Aruba CLI error detection."""

from pssh_ui.parser import detect_output_errors, parse_commands, validate_audit_regex


def test_parse_commands_ignores_bang_comments_and_preserves_inline_bang():
    raw_script = """
    configure terminal
    ! Enable SNMPv3 protocol on the switch
    snmpv3 enable
    ! Password intentionally contains '!' characters which must NOT be treated as comments
    snmpv3 user "example_user" auth sha "Auth!Pass123" priv aes "Priv!Pass!!#456"

    ! Final step
    no snmpv3 user initial
    """
    cmds = parse_commands(raw_script)
    assert cmds == [
        "configure terminal",
        "snmpv3 enable",
        'snmpv3 user "example_user" auth sha "Auth!Pass123" priv aes "Priv!Pass!!#456"',
        "no snmpv3 user initial",
    ]


def test_detect_output_errors_identifies_aoss_and_aoscx_errors():
    sample_output = (
        "Switch-Aruba# configure terminal\n"
        "Switch-Aruba(config)# snmpv3 enable\n"
        "Invalid input: snmpv3\n"
        "Switch-CX(config)# badcmd\n"
        "% Invalid input detected at '^' marker.\n"
        "User missing_user does not exist.\n"
        "! ignored comment line with Invalid input: inside\n"
        "Switch-Aruba(config)# snmpv3 only\n"
    )
    findings = detect_output_errors(sample_output)
    assert len(findings) == 3
    assert findings[0]["line_no"] == 3
    assert "Invalid" in findings[0]["reason"]
    assert findings[1]["line_no"] == 5
    assert findings[2]["line_no"] == 6


def test_validate_audit_regex_detects_missing_or_invalid_patterns():
    output = (
        "Switch-CX# show snmpv3 users\n"
        "User: netmon_v3 | Auth: sha | Priv: aes\n"
        "ntp server 10.10.1.5\n"
    )
    ok_rules = "! ignore comments\nsnmpv3 users?\nAuth:\\s+sha\nntp server 10\\."
    assert validate_audit_regex(output, ok_rules) == []

    fail_rules = "Auth:\\s+sha\nsnmpv3 only\n[unclosed"
    findings = validate_audit_regex(output, fail_rules)
    assert len(findings) == 2
    assert findings[0]["text"] == "snmpv3 only"
    assert "not found" in str(findings[0]["reason"]).lower()
    assert findings[1]["text"] == "[unclosed"
    assert "invalid" in str(findings[1]["reason"]).lower()
