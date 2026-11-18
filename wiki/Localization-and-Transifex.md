# Localization & Transifex Workflow

`pssh-ui` supports multiple UI languages via standard **GNU gettext / Babel** message catalogs managed on **[Transifex](https://app.transifex.com/eduardomozart/pssh-ui/)**.

---

## 1. Repository Layout

```text
.github/workflows/updatepot.yml        # Auto-extracts locales/pssh_ui.pot on push
babel.cfg                              # Babel string extraction config
transifex.yml                          # Transifex Git integration mapping
locales/
├── pssh_ui.pot                        # Master source template (English)
├── en/LC_MESSAGES/
│   └── pssh_ui.po                     # English catalog
└── pt_BR/LC_MESSAGES/
    └── pssh_ui.po                     # Brazilian Portuguese catalog
```

---

## 2. Zero-Code Language Discovery (`pssh_ui/i18n.py`)

* At startup or when opening **Settings (⚙)**, `available_languages()` scans `locales/<lang>/LC_MESSAGES/` automatically for any `.po` or `.mo` catalog.
* `get_language_label(code)` resolves the human-readable native name dynamically via **Babel** (`babel.Locale.parse(code).get_display_name(code)`), e.g., `Português (Brasil)`, `Español`, `Français`, `Deutsch` — without needing any hardcoded language dictionary in Python source code and without exposing raw codes like `pt_BR`.
* Dropping a new Transifex `.po` file into `locales/<lang>/LC_MESSAGES/pssh_ui.po` makes that language immediately available in **Settings (⚙)** and selectable without editing source code or compiling `.mo` files manually (`pssh_ui/i18n.py` includes a pure-Python `.po` parser when `.mo` is absent or older).

---

## 3. Extracting & Compiling Catalogs with Babel

Extract updated strings from Python source files into `locales/pssh_ui.pot`:

```bash
python -m babel.messages.frontend extract -F babel.cfg -o locales/pssh_ui.pot --project=pssh-ui --version=0.1.0 .
```

Update existing `.po` files from the updated `.pot` template (omitting obsolete `#~` entries so Transifex never sees duplicate `msgid` conflicts):

```bash
python -m babel.messages.frontend update --ignore-obsolete -i locales/pssh_ui.pot -d locales -D pssh_ui
```

Optionally compile `.mo` binaries locally:

```bash
python -m babel.messages.frontend compile -d locales -D pssh_ui
```

---

## 4. Transifex Git Integration (`transifex.yml`)

Configured resource mapping in `transifex.yml`:

```yaml
git:
  filters:
    - filter_type: file
      file_format: PO
      source_file: locales/pssh_ui.pot
      source_language: en
      translation_files_expression: locales/<lang>/LC_MESSAGES/pssh_ui.po
```

When connected via the **[Transifex](https://app.transifex.com/eduardomozart/pssh-ui/)** GitHub Integration, Transifex monitors `locales/pssh_ui.pot` in the repository and opens Pull Requests containing updated `locales/<lang>/LC_MESSAGES/pssh_ui.po` catalogs automatically.

Every push to `main` touching Python source files (`pssh_ui/**/*.py`, `main.py`) or `babel.cfg` automatically triggers `.github/workflows/updatepot.yml`, re-extracts `locales/pssh_ui.pot` with Babel, and commits any string or location changes (ignoring timestamp-only diffs).

