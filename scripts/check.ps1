# Runs every offline test: the backend pytest suite. slow and db tests stay opt-in
# (pytest -m slow / pytest -m db); frontend tests join in slice 3.
# Run from anywhere: powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & "$root\.venv\Scripts\python.exe" -m pytest
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($code -eq 0) { Write-Host "check: all offline tests passed" -ForegroundColor Green }
else { Write-Host "check: FAILED (pytest exit code $code)" -ForegroundColor Red }
exit $code
