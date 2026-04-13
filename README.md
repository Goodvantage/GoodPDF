# GoodPDF

GoodPDF is a local desktop app for turning PDFs into clean, import-ready RAG source packages.

## Product Goals

- no terminal use for install
- local processing on the user's machine
- macOS and Windows support
- one codebase as much as possible
- optional cloud LLM step for image descriptions

## Chosen Shape

- desktop UI: `PySide6`
- core pipeline: Python
- packaging target: `.dmg` for macOS, `.exe` or `.msi` for Windows
- output target: cleaned zip files ready for Frappe `RAG Bulk Import`

## Planned Pipeline

1. Select PDFs
2. Extract markdown + images with Marker
3. Triage images
4. Describe important images with OpenAI
5. Build cleaned corpus
6. Zip for Frappe import
7. Export logs and error reports

## Repo Layout

```text
GoodPDF/
  src/goodpdf/
    app/         # desktop UI
    pipeline/    # extraction and preprocessing stages
    settings/    # app config and paths
    workers/     # background jobs and subprocess orchestration
  docs/          # architecture and packaging notes
  packaging/     # macOS and Windows build notes
```

## Current State

The desktop prototype is now runnable in development and includes:

- local extraction, triage, describe, clean, and zip pipeline
- per-PDF subprocess isolation with CPU fallback
- drag-and-drop PDF selection
- settings tab for workspace and provider config
- secure API key persistence via system keychain/keyring
- starter PyInstaller packaging setup for macOS and Windows

## Development Run

```bash
cd /Users/benediktmathis/Dev/GoodPDF
uv run goodpdf
```

## Next Build Steps

1. add installer creation on top of the PyInstaller output
2. add saved job history and retry actions in the UI
3. finalize app branding and packaging polish
