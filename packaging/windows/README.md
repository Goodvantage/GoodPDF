# Windows Packaging Notes

Target deliverable:

- signed `.exe` installer or `.msi`

Planned packaging flow:

1. bundle Python app with PyInstaller or Nuitka
2. create installer

Windows should default to CPU mode for PDF extraction unless GPU acceleration is proven stable.

Current starter build command:

```powershell
.\packaging\windows\build.ps1
```

Notes:

- this currently creates the PyInstaller app bundle structure
- an installer layer still needs to be added on top of the build output
- packaged subprocess extraction is supported through the `--internal-extract` app entrypoint
- malformed PDFs are reported as failures instead of being auto-repaired inside the app
