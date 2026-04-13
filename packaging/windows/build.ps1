$ErrorActionPreference = 'Stop'

$Root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $Root

uv sync --extra packaging
uv run --extra packaging pyinstaller packaging/pyinstaller/goodpdf.spec --noconfirm --clean

Write-Host ""
Write-Host "Build complete. Look in $Root\dist\GoodPDF"
