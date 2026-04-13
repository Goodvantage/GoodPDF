# macOS Packaging Notes

Target deliverable:

- signed `.app`
- distributable `.dmg`

Planned packaging flow:

1. bundle Python app with PyInstaller or Nuitka
2. sign the app bundle
3. create `.dmg`

Current starter build command:

```bash
./packaging/macos/build.sh
```

Notes:

- this currently creates the PyInstaller app bundle structure
- signing, notarization, and final `.dmg` creation still need to be added
- packaged subprocess extraction is supported through the `--internal-extract` app entrypoint
- malformed PDFs are reported as failures instead of being auto-repaired inside the app
