from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from goodpdf.settings.config import AppConfig


def app_icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "logo.png"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--internal-extract", action="store_true")
    parser.add_argument("--internal-language-code")
    parser.add_argument("--internal-pdf")
    parser.add_argument("--internal-output-root")
    return parser.parse_known_args(argv)[0]


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = parse_args(argv)
    if args.internal_extract:
        from goodpdf.pipeline.extract import run_internal_extract

        return run_internal_extract(
            language_code=args.internal_language_code,
            source_pdf=Path(args.internal_pdf).resolve(),
            marker_root=Path(args.internal_output_root).resolve(),
        )

    from goodpdf.app.window import MainWindow

    app = QApplication(sys.argv)
    config = AppConfig.default()
    app.setApplicationName(config.settings_application)
    app.setOrganizationName(config.settings_organization)
    icon_path = app_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    if not app.windowIcon().isNull():
        window.setWindowIcon(app.windowIcon())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
