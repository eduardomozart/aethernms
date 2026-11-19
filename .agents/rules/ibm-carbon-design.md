# IBM Carbon Design System v11 Rule (`aethernms`)

> Imported and adapted from `https://getdesign.md/ibm/design-md` (full verbatim reference in `DESIGN.md`) for the `aethernms` Py4Web web application.

## Core Design Principles
- **Authentic IBM Carbon v11 Only**: Always use official `@carbon/styles` v11 CSS classes (`.cds--header`, `.cds--side-nav`, `.cds--search`, `.cds--data-table`, `.cds--pagination`, `.cds--modal`, `.cds--tabs`, `.cds--progress`, `.cds--toggle`, `.cds--tag`, `.cds--btn`, `.cds--text-input`, `.cds--select-input`, `.cds--checkbox`, `.cds--breadcrumb`, `.cds--inline-notification`, `.cds--tile`), official `IBM Plex Sans` & `IBM Plex Mono` fonts (`@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`), and official Carbon SVG icons (`@iconify-json/carbon`).
- **Composer Asset Management**: Frontend Carbon packages are managed exclusively via `composer.json` + `composer.lock` (`asset-packagist.org`) into `aethernms/static/vendor/`. Never hand-copy or manually download third-party CSS/fonts/icons; run `composer install` / `composer update` instead.
- **Flat-Square Geometry (`0px` corners)**: Keep `border-radius: 0px` (`rounded.none`) on every button, tile/card, input, modal, table, and container. Only Carbon pill tags (`.cds--tag`) and status dots use pill radius.
- **Color Palette & Single Accent**:
  - Primary Accent: `#0f62fe` (IBM Blue 60), hover `#0050e6` / `#0353e9`, active `#002d9c`, link hover `#0043ce`.
  - Light Theme (`.cds--white` workspace + `#f4f4f4` surface-1): canvas `#ffffff`, surface-1 `#f4f4f4`, surface-2 `#e0e0e0`, ink `#161616`, muted `#525252`, subtle `#6f6f6f`/`#8c8c8c`, hairlines `#e0e0e0`.
  - Dark Theme (`.cds--g100`): canvas `#161616`, layer-01 `#262626`, layer-02 `#393939`, text `#f4f4f4`, secondary `#c6c6c6`, link `#78a9ff`.
  - Semantic Status Only: Success `#24a148` (dark `#42be65`), Warning `#f1c21b`, Error `#da1e28` (dark `#fa4d56`), Info `#0f62fe` (dark `#4589ff`). Never introduce a second brand color.
- **Typography (`IBM Plex Sans` & `IBM Plex Mono`)**:
  - Display sizes (`42px+`): weight `300` (IBM's light display voice — never bold display headlines).
  - Page headlines: `32px` / weight `400` / line-height `1.25`.
  - Section / Card headings: `20px–24px` / weight `400`.
  - Body: `16px` (`1.50` line-height) or compact UI body `14px` (`1.29` line-height) with Carbon's signature `letter-spacing: 0.16px`.
  - Captions / labels: `12px` / weight `400` / `letter-spacing: 0.32px` (sentence case, never all-caps tracked eyebrows).
  - CLI commands, IPs, ports, Netmiko platforms, logs, and API key prefixes: `IBM Plex Mono`.
- **Spacing & Elevation**:
  - Strict `4px` spacing grid (`4px`, `8px`, `12px`, `16px`, `24px`, `32px`, `48px`).
  - Prefer `1px` hairlines and surface layer contrast (`canvas` <-> `surface-1`) over drop shadows.
  - Focus state uses Carbon's `2px` `#0f62fe` focus outline (`#ffffff` on dark surfaces).

## `aethernms` UI Shell & Navigation Conventions
- **Header (`48px`, `.cds--header.cds--g100`)**: Always dark (`#161616`) in both Light and Dark themes. Contains hamburger SideNav toggle, `aethernms` brand, **Global Device Search** input + Search button + live dropdown, and monochrome `20×20` Carbon icon actions right-aligned. Do NOT place page navigation tabs in the header navbar.
- **SideNav (`256px`, `.cds--side-nav`)**: White in Light theme, Gray 100 in Dark theme, with `16×16` Carbon icons, `32px` items, `3px` `#0f62fe` left active bar, and expandable `.cds--side-nav__submenu` categories with rotating chevron:
  - Top-level links: `Jobs` (`/jobs`), `Snippets` (`/snippets`), `Devices` (`/devices`).
  - Expandable `Administration` menu: `System Settings` (`/administration/settings`), `Users` (`/administration/users`), `Roles` (`/administration/roles`), `API Keys` (`/administration/api-keys`).
- **Icons**: Use `carbon_icon(name, size)` (from `aethernms/carbon_icons.py`) in templates and `AetherNMS.icon(name)` in JS. Never use raw OS Unicode emojis (`🔑`, `🗑`, `📄`, `⚙`) as UI icons.
- **Modals & Keyboard**: Every modal uses official Carbon `.cds--modal` structure and closes cleanly on `Escape` via its `Cancel` / `Close` control.
