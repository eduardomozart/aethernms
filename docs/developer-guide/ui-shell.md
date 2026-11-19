# IBM Carbon v11 UI Shell & Frontend Rules

This specification defines the mandatory frontend architecture implemented across `aethernms/templates/` and `aethernms/static/css/aethernms-carbon.css`.

## 1. Declarative Vendor Assets (`composer.json` / `composer.lock`)

* Never hand-copy or manually vendor IBM Carbon CSS, IBM Plex fonts, Carbon icons, or Swagger UI files.
* All vendor assets live under `aethernms/static/vendor/` installed via `composer install`:
  * `@carbon/styles` (`styles/css/styles.min.css`)
  * `@fontsource/ibm-plex-sans` & `@fontsource/ibm-plex-mono`
  * `@iconify-json/carbon` (inline SVG extraction via `aethernms/carbon_icons.py`)
  * `swagger-ui-dist`

## 2. Geometry, Theme Tokens & Buttons

* **Sharp Corners**: `border-radius: 0` across tiles, cards, inputs, tables, buttons, and modals (`0px` Carbon geometry). No drop-shadow cards.
* **Per-User Theme**: `html[data-carbon-theme="white" | "g100"]` binds Carbon theme classes (`cds--white` / `cds--g100`). Theme and language preferences belong to each `auth_user` (`language`, `theme_mode`), never global `app_settings`.
* **No Button Checkmarks**: Do not place `checkmark-filled` icons inside primary or secondary action buttons (e.g., **Complete**, **Save Settings**, **Save**).
* **No Link Underlines Inside Inline Notification Buttons**: Action links inside `.cds--inline-notification` use `.cds--btn--ghost` without `text-decoration: underline` on hover or focus.
* **Window `<title>` Format**: Every template renders `[[=page_title]] - aether` (short ASCII hyphen `-`, never an em-dash `—`).

## 3. Shared Header & Navbar Brand Lockup (`partials/header.html`)

All top-level shell templates (`layout.html`, `login.html`, `setup.html`, `forbidden.html`, `swagger.html`) include `[[include 'partials/header.html']]` and `[[include 'partials/head_icons.html']]`.

* **Dark 48px Global Header (`g100` surface)**: Fixed top bar (`height: 3rem`) across the entire viewport.
* **256px Brand Zone & Full-Height Search Bar**: When `show_header_search` is enabled (authenticated workspace shell), `.anms-header-brand-zone` occupies `width: 256px` on desktop so `.anms-header-search` aligns at `left: 256px` (immediately after the expanded SideNav), fills `100%` of the header height (`48px`), omits the bottom light-gray accent line, and embeds its clickable search icon on the right without an external blue submit button.
* **Navbar Brand Styling vs Body Lockup**:
  * Navbar: `.cds--header .anms-brand-wordmark` uses `font-weight: 600; letter-spacing: -2px; font-size: 20px;` and `.cds--header__subtitle.anms-brand-sub` leaves `letter-spacing` commented out.
  * Body/Auth lockups (`.anms-brand-lockup--lg` / `--xl` on `/login`, `/setup`, `/forbidden`): Retain the display lockup (`letter-spacing: -3px` + **NMS** subtitle).
* **Right Utility Actions**:
  * **User Button**: Shows display name; clicking navigates directly to `/administration/users?edit=me` to open self-profile editing.
  * **Contextual Help Link**: Replaces the legacy `(i)` About modal; opens the matching User Guide documentation URL (`help_url`) in a new tab with localized tooltip (`Help`).
  * **Logout Button**: Submits `POST /logout`.
* **Header Tooltips**: Always render `aria-label` and `title` server-side using `[[=T('...')]]` (`data-i18n-title` for dynamic updates).

## 4. Expandable Carbon SideNav Rail (`layout.html`)

* Fixed left rail below the 48px header (`48px` collapsed width on desktop, expanding cleanly to `256px` on hover, focus-within, or toggle click via `.anms-rail-expanded` / `aria-expanded`).
* Mobile/tablet (`< 1056px`) collapses off-canvas and opens via the hamburger menu button.
* Active route highlights via `.cds--side-nav__link--current` with `3px` left `#0f62fe` accent bar.

## 5. Outside-Tile Page Header & Carbon DataTable Filtering

* **Outside-Tile Page Header (`.anms-page-header`)**: Placed at the top of `.cds--content` outside `.cds--tile` cards, styled on `--cds-layer-01` (`#ffffff` in g10, `#262626` in g100) with crisp bottom hairline border, breadcrumbs (`<nav class="cds--breadcrumb">`), `<h1>` title, optional description, and optional `Help` / page actions.
* **DataTable Toolbars & Filter Popovers**: Fixed multi-column filter strips are prohibited. Every table uses Carbon `.cds--table-toolbar` with inline search (`.cds--search--sm`), a toggleable **Filter** popover panel (`Filters`, **Apply**, **Reset filters**), active filter dismissible tags (`.cds--tag--filter`), and primary/secondary table actions (`js/core.js` shared helpers).

## 6. Carbon Modals (`modals/*.html`, `js/core.js`)

* `@carbon/styles` hides `.cds--modal` via `opacity: 0; visibility: hidden` unless `.is-visible` is active.
* `window.openModal(id)` and `window.closeModal(id)` in `aethernms/static/js/core.js` **must toggle both `.is-visible` and `.open`** (`aria-hidden` synced accordingly) so View, Edit, Delete, and Add modals consistently appear and trap Escape/backdrop clicks.
