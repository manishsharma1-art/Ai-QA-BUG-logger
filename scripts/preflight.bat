@echo off
REM Preflight script (Windows) — runs every local check before any deploy.
REM
REM Steps mirror scripts/preflight.sh:
REM   1. git status --porcelain     — fail if working tree is dirty
REM   2. env validator              — validate_env_vars(settings)
REM   3. pytest -q                  — Tier 1 unit tests
REM   4. synthetic webhook          — Tier 2 scenarios S1..S9
REM   5. docker build --no-cache    — image builds clean
REM   6. docker run                 — container boots; /health is healthy
REM   7. curl /health               — verify build_marker + last_gcs_sync
REM
REM Usage:
REM   scripts\preflight.bat
REM
REM Exit code: 0 on success, 1 on any failure.

setlocal enableextensions
echo [preflight] starting...

echo [preflight] step 1: git status --porcelain
for /f %%i in ('git status --porcelain') do (
    echo [preflight] FAIL: working tree is dirty — commit or stash before deploy
    git status --porcelain
    exit /b 1
)
echo [preflight] step 1: clean

echo [preflight] step 2: env validator (placeholder — wired in task 7.4)
echo [preflight] step 2: skipped (not yet implemented)

echo [preflight] step 3: pytest -q
python -m pytest -q
if errorlevel 1 (
    echo [preflight] FAIL: pytest
    exit /b 1
)
echo [preflight] step 3: pytest passed

echo [preflight] step 4: synthetic webhook scenarios (placeholder — wired in task 11.x)
echo [preflight] step 4: skipped (not yet implemented)

echo [preflight] step 5: docker build --no-cache (placeholder — run manually for now)
echo [preflight] step 5: skipped (manual)

echo [preflight] step 6: docker run (placeholder — run manually for now)
echo [preflight] step 6: skipped (manual)

echo [preflight] step 7: curl /health (placeholder — run manually for now)
echo [preflight] step 7: skipped (manual)

echo [preflight] all checks passed (placeholder steps skipped)
exit /b 0
