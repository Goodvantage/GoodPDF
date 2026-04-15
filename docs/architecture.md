# GoodPDF Architecture

## Decision

GoodPDF will be a local desktop application built with `PySide6` and Python.

This was chosen because it satisfies the hard requirements:

- no terminal installation for end users
- local processing on the user's machine
- macOS and Windows support
- as much shared code as possible across both platforms

## High-Level Shape

```text
PySide6 desktop UI
        |
        v
Python job runner
        |
        v
Pipeline stages
  - extract
  - triage
  - describe
  - clean
  - zip
```

## Key Design Rules

1. Keep the core pipeline pure Python and reusable.
2. Run heavy work in subprocesses.
3. Isolate each PDF conversion to avoid whole-job crashes.
4. Keep cloud LLM usage optional and explicit.
5. Prefer real markdown captions over generic vision alt text.
6. Keep caption-label vocabulary data-driven so new languages only need label additions.
7. Allow later pipeline stages to resume from an existing marker folder.
8. Produce the same cleaned zip format that Frappe already consumes.

## Current Pipeline Notes

- Caption detection mirrors the WhatsApp app's block-based marker caption extractor,
  but GoodPDF converts matched captions into plain text for `.desc` sidecars.
- `describe` is caption-first and only falls back to OpenAI vision when the markdown
  does not provide a usable caption.
- Resume jobs can start from `Triage`, `Describe`, or `Clean` against any existing
  marker folder while still writing a new cleaned/archive/report job under the
  configured workspace.
