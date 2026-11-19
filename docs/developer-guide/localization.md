# Localization & Transifex Workflow

`aethernms` supports multi-language UI rendering via **GNU gettext / Babel** message catalogs managed on **[Transifex](https://app.transifex.com/eduardomozart/aethernms/)**, combined with zero-FOUC server-side Renoir rendering.

## 1. Repository Layout

```text
.github/workflows/updatepot.yml        # Auto-extracts locales/aethernms.pot on push
babel.cfg                              # Babel extraction config (.py + templates .html)
transifex.yml                          # Transifex Git integration mapping
aethernms/web_strings.py               # Central catalog of JS / dynamic / error strings
locales/
├── aethernms.pot                      # Master source template (English)
├── en/LC_MESSAGES/
│   ├── aethernms.po                   # English catalog
│   └── aethernms.mo                   # Compiled English binary catalog
└── pt_BR/LC_MESSAGES/
    ├── aethernms.po                   # Brazilian Portuguese catalog
    └── aethernms.mo                   # Compiled Portuguese binary catalog
```

## 2. Server-Side Rendering & Zero-FOUC Hydration

To avoid English text flashing before JavaScript initializes:

1. Every HTML template wraps static and server-computed UI text in `[[=T("...")]]` using the request's resolved locale (`_build_i18n_render_context()` in `aethernms/web_app.py`).
2. `layout.html`, `login.html`, `setup.html`, `forbidden.html`, and `swagger.html` embed `<script id="anms-initial-i18n" type="application/json">[[=XML(initial_i18n_json)]]</script>`.
3. `aethernms/static/js/core.js` hydrates `window.__ANMS_I18N` synchronously from `#anms-initial-i18n` on initial parse, so `window.t(key)` translates client-rendered rows, notifications, and modals immediately without waiting for `/i18n`.
4. Unauthenticated routes (`/login`, `/setup`) resolve locale via query/header `navigator.languages` matching when no session user exists, while authenticated routes prioritize the logged-in user's personal `auth_user.language` preference.

## 3. Zero-Code Language Discovery (`aethernms/i18n.py`)

* `available_languages()` scans `locales/<lang>/LC_MESSAGES/` automatically for any `.po` or `.mo` catalog.
* `get_language_label(code)` resolves the native display name via **Babel** (`babel.Locale.parse(code).get_display_name(code)`), e.g., `Português (Brasil)`, `English`.
* `get_catalog(lang)` uses a thread-safe mtime-aware cache backed by compiled `.mo` files with a pure-Python `.po` fallback when `.mo` is absent or stale.
* Any string passed to `t('...')` in JS, dynamic titles/subtitles in `PAGE_META_MAP`, `DEFAULT_ROLES` descriptions in `auth.py`, or error strings returned by `db.py` / `api/` **must** exist in `aethernms/web_strings.py` (or a template/Python `_()`/`T()` call) so `pybabel extract` picks it up.

## 4. Extracting, Updating & Compiling Catalogs

Extract updated strings into `locales/aethernms.pot`:

```bash
python -m babel.messages.frontend extract -F babel.cfg -o locales/aethernms.pot --project=aethernms --version=0.1.0 .
```

Update `.po` catalogs while dropping obsolete `#~` entries so Transifex never sees duplicate `msgid` conflicts:

```bash
python -m babel.messages.frontend update --ignore-obsolete -i locales/aethernms.pot -d locales -D aethernms
```

Compile binary `.mo` catalogs (run tests `pytest tests/test_i18n.py` to assert 0 untranslated, 0 fuzzy, and 0 obsolete entries):

```bash
python -m babel.messages.frontend compile -d locales -D aethernms
```
