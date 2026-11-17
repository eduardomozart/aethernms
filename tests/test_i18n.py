"""Tests for multi-language (i18n), Transifex PO discovery, and dynamic Babel labels."""

from pathlib import Path

from pssh_ui.i18n import (
    Translator,
    _,
    available_languages,
    get_language,
    get_language_label,
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
