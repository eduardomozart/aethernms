"""Tests for multi-language (i18n), Transifex PO discovery, and dynamic Babel labels."""

from collections import Counter
from pathlib import Path

from babel.messages import pofile

from pssh_ui.common import format_operation_result_ui
from pssh_ui.i18n import (
    Translator,
    _,
    available_languages,
    get_language,
    get_language_label,
    ngettext,
    set_language,
)


def test_builtin_translations_en_and_pt_br():
    prev = get_language()
    try:
        langs = available_languages()
        assert langs == ["en", "pt_BR"]

        # Dynamic Babel labels must NOT show raw 'pt_BR'
        pt_label = get_language_label("pt_BR")
        assert pt_label == "Português (Brasil)"
        assert "pt_BR" not in pt_label
        assert get_language_label("en") == "English"

        set_language("en")
        assert _("Jobs") == "Jobs"
        assert _("Devices") == "Devices"
        assert _("Add Job") == "Add Job"

        set_language("pt_BR")
        assert _("Jobs") == "Tarefas"
        assert _("Devices") == "Dispositivos"
        assert _("Add Job") == "Nova Tarefa"
        assert _("Max Parallel Executions:") == "Máx. Execuções em Paralelo:"
        assert ngettext("%d error detected", "%d errors detected", 1) % 1 == "1 erro detectado"
        assert ngettext("%d error detected", "%d errors detected", 2) % 2 == "2 erros detectados"
        assert (
            format_operation_result_ui("1 error detected: Invalid CLI input")
            == "1 erro detectado: Entrada CLI inválida"
        )
        assert (
            format_operation_result_ui("2 errors detected: Invalid CLI input")
            == "2 erros detectados: Entrada CLI inválida"
        )
    finally:
        set_language(prev)


def test_transifex_po_discovery_works_without_source_edits(tmp_path: Path):
    for lang, translated in (("es", "Hola Mundo"), ("de", "Hallo Welt")):
        po_dir = tmp_path / lang / "LC_MESSAGES"
        po_dir.mkdir(parents=True)
        po_file = po_dir / "pssh_ui.po"
        po_file.write_text(
            'msgid ""\n'
            'msgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
            'msgid "Hello "\n'
            '"World"\n'
            f'msgstr "{translated}"\n\n'
            'msgid "{n} switch"\n'
            'msgid_plural "{n} switches"\n'
            'msgstr[0] "{n} switch_s"\n'
            'msgstr[1] "{n} switch_p"\n',
            encoding="utf-8",
        )

    tr = Translator(locales_dir=tmp_path, default_lang="es")
    discovered = tr.available_languages()
    assert "de" in discovered
    assert "es" in discovered
    assert tr.gettext("Hello World") == "Hola Mundo"
    assert tr.ngettext("{n} switch", "{n} switches", 1) == "{n} switch_s"
    assert tr.ngettext("{n} switch", "{n} switches", 3) == "{n} switch_p"

    # Dynamic display names computed without code edits
    assert get_language_label("es") == "Español"
    assert get_language_label("de") == "Deutsch"

    tr.set_language("de")
    assert tr.gettext("Hello World") == "Hallo Welt"

    tr.set_language("fr_UNKNOWN")
    assert tr.language == "en"
    assert tr.gettext("Hello World") == "Hello World"


def _extract_raw_po_keys(po_path: Path) -> list[tuple[str, str]]:
    """Collect (msgctxt, msgid) entries including obsolete blocks without deduplicating."""
    keys: list[tuple[str, str]] = []
    cur_ctx: list[str] = []
    cur_id: list[str] = []
    field: str | None = None
    obsolete = False

    def flush() -> None:
        nonlocal cur_ctx, cur_id, field, obsolete
        if cur_id:
            msgid = "".join(cur_id)
            if msgid != '""':
                keys.append(("".join(cur_ctx), msgid))
        cur_ctx = []
        cur_id = []
        field = None
        obsolete = False

    for raw_line in po_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        is_obs = line.startswith("#~ ")
        body = line[3:].strip() if is_obs else line
        if body.startswith("msgctxt "):
            if cur_id:
                flush()
            cur_ctx = [body[len("msgctxt "):]]
            field = "msgctxt"
            obsolete = is_obs
        elif body.startswith("msgid "):
            if cur_id:
                flush()
            cur_id = [body[len("msgid "):]]
            field = "msgid"
            obsolete = is_obs
        elif field == "msgctxt" and is_obs == obsolete and body.startswith('"'):
            cur_ctx.append(body)
        elif field == "msgid" and is_obs == obsolete and body.startswith('"'):
            cur_id.append(body)
        elif not body or body.startswith(("msgstr", "msgid_plural", "#")):
            if field in {"msgctxt", "msgid"} and (body.startswith("msgstr") or body.startswith("msgid_plural") or not body):
                flush()
    flush()
    return keys


def test_po_and_pot_catalogs_have_no_duplicate_or_colliding_msgids():
    """Ensure Transifex never rejects catalogs due to active or obsolete duplicate msgids."""
    locales_root = Path(__file__).resolve().parents[1] / "locales"
    catalog_paths = sorted(p for p in locales_root.rglob("*") if p.suffix in {".po", ".pot"})
    assert catalog_paths

    for catalog_path in catalog_paths:
        with catalog_path.open("rb") as fh:
            catalog = pofile.read_po(fh)
        assert not catalog.obsolete, f"Obsolete entries remain in {catalog_path}"
        raw_counts = Counter(_extract_raw_po_keys(catalog_path))
        collisions = {key: count for key, count in raw_counts.items() if count > 1}
        assert not collisions, f"Duplicate/colliding msgids in {catalog_path}: {collisions}"

