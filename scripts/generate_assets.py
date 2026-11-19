"""Generate assets/ SVG logo, multi-size favicon.ico, iOS apple-touch-icon.png, PWA icons, and site.webmanifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ASSETS_DIR = ROOT_DIR / "assets"

BG_HEX = "#161616"
FG_HEX = "#f4f4f4"
BG_RGB: Tuple[int, int, int] = (22, 22, 22)
FG_RGB: Tuple[int, int, int] = (244, 244, 244)

LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">\n'
    f'  <rect width="32" height="32" fill="{BG_HEX}"/>\n'
    f'  <text x="16" y="22" font-family="IBM Plex Sans, -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif" '
    f'font-size="18" font-weight="600" fill="{FG_HEX}" text-anchor="middle">&#x00C6;</text>\n'
    '</svg>\n'
)


def _find_font_candidates() -> Iterable[Path]:
    plex_woff = (
        ROOT_DIR
        / "aethernms"
        / "static"
        / "vendor"
        / "npm-asset"
        / "fontsource--ibm-plex-sans"
        / "files"
        / "ibm-plex-sans-latin-600-normal.woff"
    )
    yield plex_woff
    for candidate in (
        Path("C:/Windows/Fonts/seguisb.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ):
        yield candidate


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _find_font_candidates():
        if path.is_file():
            try:
                font = ImageFont.truetype(str(path), size=size)
                # Confirm the font draws non-empty pixels for 'Æ'
                bbox = font.getbbox("\u00c6")
                if bbox and (bbox[2] - bbox[0]) > 0:
                    return font
            except OSError:
                continue
    return ImageFont.load_default()


def render_monogram_png(size: int, master_size: int = 512) -> Image.Image:
    """Render an opaque square #161616 tile with a centered #f4f4f4 'Æ' glyph."""
    canvas = Image.new("RGB", (master_size, master_size), BG_RGB)
    draw = ImageDraw.Draw(canvas)
    font = _load_font(int(master_size * 0.56))
    glyph = "\u00c6"
    bbox = draw.textbbox((0, 0), glyph, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (master_size - w) / 2.0 - bbox[0]
    y = (master_size - h) / 2.0 - bbox[1]
    draw.text((round(x), round(y)), glyph, fill=FG_RGB, font=font)
    if size != master_size:
        return canvas.resize((size, size), Image.Resampling.LANCZOS)
    return canvas


def generate_assets(output_dir: Optional[Path] = None) -> Path:
    """Write SVG, multi-size ICO, Apple Touch Icon, PWA PNGs, and site.webmanifest to output_dir."""
    out = Path(output_dir) if output_dir else DEFAULT_ASSETS_DIR
    out.mkdir(parents=True, exist_ok=True)

    (out / "aethernms.svg").write_text(LOGO_SVG, encoding="utf-8")

    master = render_monogram_png(512, master_size=512)
    master.save(
        out / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
    )

    render_monogram_png(180).save(out / "apple-touch-icon.png", format="PNG")
    render_monogram_png(192).save(out / "icon-192.png", format="PNG")
    master.save(out / "icon-512.png", format="PNG")

    manifest = {
        "name": "\u00c6THER NMS",
        "short_name": "aether",
        "start_url": "/",
        "display": "standalone",
        "background_color": BG_HEX,
        "theme_color": BG_HEX,
        "icons": [
            {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/assets/aethernms.svg", "sizes": "any", "type": "image/svg+xml"},
        ],
    }
    (out / "site.webmanifest").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate aethernms favicon, Apple touch icon, and SVG assets.")
    parser.add_argument("--output", default=str(DEFAULT_ASSETS_DIR), help="Target assets directory")
    args = parser.parse_args()
    out = generate_assets(Path(args.output))
    print(f"Generated assets in {out}")


if __name__ == "__main__":
    main()
