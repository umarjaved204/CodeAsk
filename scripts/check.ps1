# Runs every offline check: the backend pytest suite, the frontend dangerouslySetInnerHTML
# check, the frontend lint and the frontend tests. slow and db tests stay opt-in
# (pytest -m slow / pytest -m db).
# The browser tests (a production build against a mocked API) run too, unless -Quick is given.
# Run from anywhere: powershell -ExecutionPolicy Bypass -File scripts\check.ps1 [-Quick]
param([switch]$Quick)
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & "$root\.venv\Scripts\python.exe" -m pytest
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

# dangerouslySetInnerHTML is allowed once: the static theme script in app/layout.tsx
# (PLAN.md slice 3, build step 3). Anywhere else it could render model text as HTML.
$sources = Get-ChildItem "$root\frontend" -Recurse -File -Include *.ts, *.tsx, *.js, *.jsx, *.mjs |
    Where-Object { $_.FullName -notmatch '\\(node_modules|\.next|\.next-e2e)\\' }
$hits = @($sources | Select-String -SimpleMatch "dangerouslySetInnerHTML")
$allowed = @($hits | Where-Object { $_.Path -eq "$root\frontend\app\layout.tsx" })
$bad = @($hits | Where-Object { $_.Path -ne "$root\frontend\app\layout.tsx" })
if ($bad.Count -gt 0 -or $allowed.Count -gt 1) {
    Write-Host "check: dangerouslySetInnerHTML outside the theme script:" -ForegroundColor Red
    $hits | ForEach-Object { Write-Host "  $($_.Path):$($_.LineNumber)" }
    if ($code -eq 0) { $code = 1 }
} else {
    Write-Host "check: dangerouslySetInnerHTML only in the theme script" -ForegroundColor Green
}

# Frontend lint (Next's rules + react/no-danger) and tests, from the exact pinned versions.
Push-Location "$root\frontend"
try {
    npm run lint --silent
    if ($LASTEXITCODE -ne 0 -and $code -eq 0) { $code = $LASTEXITCODE }
    # Frontend tests on Playwright's runner (logic tests need no browser).
    npm test --silent
    if ($LASTEXITCODE -ne 0 -and $code -eq 0) { $code = $LASTEXITCODE }
    if ($Quick) {
        Write-Host "check: browser tests skipped (-Quick)" -ForegroundColor Yellow
    } else {
        npm run test:e2e --silent
        if ($LASTEXITCODE -ne 0 -and $code -eq 0) { $code = $LASTEXITCODE }
    }
} finally {
    Pop-Location
}

if ($code -eq 0) { Write-Host "check: all offline checks passed" -ForegroundColor Green }
else { Write-Host "check: FAILED (exit code $code)" -ForegroundColor Red }
exit $code
