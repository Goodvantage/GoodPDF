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
4. Prefer real markdown captions, then describe the remaining images with OpenAI
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
- caption-first image annotation with app-wide extra caption labels
- settings tab for workspace, provider config, and caption label overrides
- resume mode for starting from an existing marker folder at Triage, Describe, or Clean
- secure API key persistence via system keychain/keyring
- starter PyInstaller packaging setup for macOS and Windows

## Development Run

```bash
cd /Users/benediktmathis/Dev/GoodPDF
uv run goodpdf
```

## Caption Detection

GoodPDF now prefers real figure captions from marker-converted markdown before it
falls back to cloud vision descriptions.

- image blocks are detected from standalone `![](...)` lines
- one caption can apply to a contiguous image block
- the first non-blank line after the image block must be a bold caption line
- built-in caption labels cover the current English/Bahasa corpus
- Settings -> `Additional caption labels` lets you add new label words app-wide

Caption matches are written directly into `.desc` sidecars, so rerunning
`Describe` can upgrade older generic alt text without paying for extra vision
calls when the markdown already contains the real caption.

## Resume Mode

Use `Start from -> Existing marker folder` when extraction already exists.

- choose any marker output folder
- start at `Triage`, `Describe`, or `Clean`
- GoodPDF reads and updates sidecars in that marker folder
- cleaned output, archive, and reports are written to a fresh job folder under the configured workspace

## Next Build Steps

1. add installer creation on top of the PyInstaller output
2. add saved job history and retry actions in the UI
3. finalize app branding and packaging polish
