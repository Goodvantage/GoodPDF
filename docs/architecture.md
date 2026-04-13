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
5. Produce the same cleaned zip format that Frappe already consumes.

## Planned Migration From Regen2

Move the current logic into modules in this order:

1. `convert_pdfs.py`
2. `scripts/preprocess/triage.py`
3. `scripts/preprocess/describe.py`
4. `scripts/preprocess/clean.py`

The first milestone is feature parity with the existing command-line workflow.
