#!/usr/bin/env bash
# Preflight script — runs every local check before any deploy.
#
# Steps (in order):
#   1. git status --porcelain     — fail if working tree is dirty
#   2. env validator              — validate_env_vars(settings)
#   3. pytest -q                  — Tier 1 unit tests
#   4. synthetic webhook          — Tier 2 scenarios S1..S9
#   5. docker build --no-cache    — image builds clean
#   6. docker run                 — container boots; /health is healthy
#   7. curl /health               — verify build_marker + last_gcs_sync
#
# Usage:
#   bash scripts/preflight.sh
#
# Exit code: 0 on success, 1 on any failure.
set -euo pipefail

echo "[preflight] starting…"

echo "[preflight] step 1: git status --porcelain"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "[preflight] FAIL: working tree is dirty — commit or stash before deploy"
  git status --porcelain
  exit 1
fi
echo "[preflight] step 1: clean"

echo "[preflight] step 2: env validator (placeholder — wired in task 7.4)"
# python -c "from env_validator import validate_env_vars; from config import get_settings; warnings = validate_env_vars(get_settings()); exit(1 if any(w.startswith('FATAL') for w in warnings) else 0)"
echo "[preflight] step 2: skipped (not yet implemented)"

echo "[preflight] step 3: pytest -q"
python -m pytest -q || { echo "[preflight] FAIL: pytest"; exit 1; }
echo "[preflight] step 3: pytest passed"

echo "[preflight] step 4: synthetic webhook scenarios (placeholder — wired in task 11.x)"
# python scripts/synthetic_webhook.py --scenario all || { echo "[preflight] FAIL: synthetic webhook"; exit 1; }
echo "[preflight] step 4: skipped (not yet implemented)"

echo "[preflight] step 5: docker build --no-cache (placeholder — run manually for now)"
# docker build -t qa-bugbot:local --no-cache --build-arg BUILD_MARKER="local-$(git rev-parse --short HEAD)" . || exit 1
echo "[preflight] step 5: skipped (manual)"

echo "[preflight] step 6: docker run (placeholder — run manually for now)"
echo "[preflight] step 6: skipped (manual)"

echo "[preflight] step 7: curl /health (placeholder — run manually for now)"
echo "[preflight] step 7: skipped (manual)"

echo "[preflight] all checks passed (placeholder steps skipped)"
exit 0
