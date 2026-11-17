"""Internationalization (i18n) with dynamic Transifex .po discovery and Babel display names."""

from __future__ import annotations

import gettext
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from babel import Locale, UnknownLocaleError

from pssh_ui.paths import get_locales_dir


DEFAULT_LOCALES_DIR = get_locales_dir()
DOMAIN = "pssh_ui"


def _unescape_po_string(raw: str) -> str:
    """Unescape standard PO string literal escape sequences."""
    result: List[str] = []
    i = 0
    length = len(raw)
    while i < length:
        ch = raw[i]
        if ch == "\\" and i + 1 < length:
            nxt = raw[i + 1]
            if nxt == "n":
                result.append("\n")
            elif nxt == "t":
                result.append("\t")
            elif nxt == "r":
                result.append("\r")
            elif nxt == '"':
                result.append('"')
            elif nxt == "\\":
                result.append("\\")
            else:
                result.append(nxt)
            i += 2
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def _extract_quoted(text: str) -> str:
    """Extract and unescape content inside a quoted PO literal line."""
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        return _unescape_po_string(stripped[1:-1])
    return ""


def parse_po_file(po_path: Path) -> Tuple[Dict[str, str], Dict[Tuple[str, int], str]]:
    """Parse a gettext .po file into singular and plural lookup dictionaries."""
    singulars: Dict[str, str] = {}
    plurals: Dict[Tuple[str, int], str] = {}

    msgid_parts: List[str] = []
    msgid_plural_parts: List[str] = []
    msgstr_parts: Dict[Optional[int], List[str]] = {}
    current_field: Optional[str] = None
    current_plural_idx: Optional[int] = None
    is_fuzzy = False

    def flush_entry() -> None:
        nonlocal msgid_parts, msgid_plural_parts, msgstr_parts, current_field, current_plural_idx, is_fuzzy
        if is_fuzzy:
            msgid_parts = []
            msgid_plural_parts = []
            msgstr_parts = {}
            current_field = None
            current_plural_idx = None
            is_fuzzy = False
            return

        msgid = "".join(msgid_parts)
        if msgid:
            if msgid_plural_parts:
                for idx, parts in msgstr_parts.items():
                    if idx is not None:
                        val = "".join(parts)
                        if val:
                            plurals[(msgid, idx)] = val
            else:
                val = "".join(msgstr_parts.get(None, []))
                if val:
                    singulars[msgid] = val

        msgid_parts = []
        msgid_plural_parts = []
        msgstr_parts = {}
        current_field = None
        current_plural_idx = None
        is_fuzzy = False

    with po_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                flush_entry()
                continue
            if line.startswith("#"):
                if line.startswith("#,") and "fuzzy" in line:
                    is_fuzzy = True
                continue
            if line.startswith("msgid_plural "):
                current_field = "msgid_plural"
                msgid_plural_parts = [_extract_quoted(line[len("msgid_plural "):])]
            elif line.startswith("msgid "):
                if msgid_parts or msgstr_parts:
                    flush_entry()
                current_field = "msgid"
                msgid_parts = [_extract_quoted(line[len("msgid "):])]
            elif line.startswith("msgstr["):
                bracket_end = line.find("]")
                if bracket_end != -1:
                    idx_str = line[len("msgstr["):bracket_end]
                    if idx_str.isdigit():
                        current_field = "msgstr_plural"
                        current_plural_idx = int(idx_str)
                        msgstr_parts[current_plural_idx] = [
                            _extract_quoted(line[bracket_end + 1 :])
                        ]
            elif line.startswith("msgstr "):
                current_field = "msgstr"
                current_plural_idx = None
                msgstr_parts[None] = [_extract_quoted(line[len("msgstr "):])]
            elif line.startswith('"'):
                piece = _extract_quoted(line)
                if current_field == "msgid":
                    msgid_parts.append(piece)
                elif current_field == "msgid_plural":
                    msgid_plural_parts.append(piece)
                elif current_field == "msgstr":
                    msgstr_parts.setdefault(None, []).append(piece)
                elif current_field == "msgstr_plural" and current_plural_idx is not None:
                    msgstr_parts.setdefault(current_plural_idx, []).append(piece)

    flush_entry()
    return singulars, plurals


class _POTranslations(gettext.NullTranslations):
    """gettext.Translations implementation backed by parsed .po files."""

    def __init__(self, po_path: Path) -> None:
        super().__init__()
        self._singulars, self._plurals = parse_po_file(po_path)

    def gettext(self, message: str) -> str:
        return self._singulars.get(message, message)

    def ngettext(self, msgid1: str, msgid2: str, n: int) -> str:
        idx = 0 if n == 1 else 1
        translated = self._plurals.get((msgid1, idx))
        if translated is not None:
            return translated
        return msgid1 if n == 1 else msgid2


class Translator:
    """Manages active UI locale and string translation with dynamic PO discovery."""

    def __init__(self, locales_dir: Optional[Path] = None, default_lang: str = "en") -> None:
        self.locales_dir = Path(locales_dir) if locales_dir else DEFAULT_LOCALES_DIR
        self._language = "en"
        self._translations: gettext.NullTranslations = gettext.NullTranslations()
        self.set_language(default_lang)

    @property
    def language(self) -> str:
        return self._language

    def available_languages(self) -> List[str]:
        """Return sorted list of language codes discovered in locales_dir (always includes 'en')."""
        langs = {"en"}
        if self.locales_dir.is_dir():
            for child in self.locales_dir.iterdir():
                if not child.is_dir():
                    continue
                lc_dir = child / "LC_MESSAGES"
                if (lc_dir / f"{DOMAIN}.mo").is_file() or (lc_dir / f"{DOMAIN}.po").is_file():
                    langs.add(child.name)
        return sorted(langs, key=lambda code: (code != "en", code.lower()))

    def set_language(self, lang: str) -> str:
        """Switch active language, loading .po or .mo dynamically from locales_dir."""
        candidate = (lang or "en").strip() or "en"
        lc_dir = self.locales_dir / candidate / "LC_MESSAGES"
        mo_path = lc_dir / f"{DOMAIN}.mo"
        po_path = lc_dir / f"{DOMAIN}.po"

        if po_path.is_file() and (
            not mo_path.is_file() or po_path.stat().st_mtime > mo_path.stat().st_mtime
        ):
            self._translations = _POTranslations(po_path)
            self._language = candidate
        elif mo_path.is_file():
            self._translations = gettext.translation(
                DOMAIN,
                localedir=str(self.locales_dir),
                languages=[candidate],
                fallback=True,
            )
            self._language = candidate
        elif po_path.is_file():
            self._translations = _POTranslations(po_path)
            self._language = candidate
        else:
            self._translations = gettext.NullTranslations()
            self._language = "en"
        return self._language

    def gettext(self, message: str) -> str:
        return self._translations.gettext(message)

    def ngettext(self, singular: str, plural: str, count: int) -> str:
        return self._translations.ngettext(singular, plural, count)


_translator = Translator()


def get_translator() -> Translator:
    """Return the global Translator instance."""
    return _translator


def set_language(lang: str) -> str:
    """Set the active global UI language."""
    return _translator.set_language(lang)


def get_language() -> str:
    """Return the active global UI language code."""
    return _translator.language


def available_languages() -> List[str]:
    """Return available language codes discovered in locales/."""
    return _translator.available_languages()


def get_language_label(lang: str) -> str:
    """
    Dynamically derive a human-readable native display name for any locale code
    using Babel without requiring hardcoded language maps in source code.
    """
    code = (lang or "en").strip()
    try:
        loc = Locale.parse(code)
        display = loc.get_display_name(code) or loc.get_display_name("en")
        if display:
            return display[0].upper() + display[1:]
    except (UnknownLocaleError, ValueError):
        pass
    return code


def _(message: str) -> str:
    """Translate a singular string using the active language."""
    return _translator.gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    """Translate a pluralized string using the active language."""
    return _translator.ngettext(singular, plural, count)
