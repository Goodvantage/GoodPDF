from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "goodpdf" / "assets"
SVG_PATH = ASSETS / "logo.svg"
PNG_PATH = ASSETS / "logo.png"
ICO_PATH = ASSETS / "logo.ico"
ICNS_PATH = ASSETS / "logo.icns"
ICONSET_DIR = ASSETS / "AppIcon.iconset"


def render_svg_to_png(svg_path: Path, png_path: Path, size: int) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"Could not load SVG: {svg_path}")

    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    if not image.save(str(png_path)):
        raise RuntimeError(f"Could not write PNG: {png_path}")

    if app is not None and app is not QGuiApplication.instance():
        app.quit()


def generate_iconset(source_png: Path) -> None:
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True)

    base = Image.open(source_png).convert("RGBA")
    for size in (16, 32, 128, 256, 512):
        normal = base.resize((size, size), Image.Resampling.LANCZOS)
        retina = base.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
        normal.save(ICONSET_DIR / f"icon_{size}x{size}.png")
        retina.save(ICONSET_DIR / f"icon_{size}x{size}@2x.png")


def generate_ico(source_png: Path) -> None:
    img = Image.open(source_png).convert("RGBA")
    img.save(
        ICO_PATH,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def generate_icns() -> None:
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        return
    subprocess.run(
        [iconutil, "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)],
        check=True,
    )


def main() -> int:
    render_svg_to_png(SVG_PATH, PNG_PATH, 1024)
    generate_iconset(PNG_PATH)
    generate_ico(PNG_PATH)
    generate_icns()
    print(f"Generated icons in {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
