#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

uv sync --extra packaging
uv run --extra packaging pyinstaller packaging/pyinstaller/goodpdf.spec --noconfirm --clean

printf '\nBuild complete. Look in %s/dist/GoodPDF\n' "$ROOT"
