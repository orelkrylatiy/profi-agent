#!/usr/bin/env bash
# Read-only code gate for production worker starts/restarts.
# Must complete before an existing worker is killed.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ACC="${1:-}"
cd "$BASE"

if ! command -v uv >/dev/null 2>&1; then
  echo "worker preflight failed: uv not found" >&2
  exit 1
fi

# When an account is supplied, validate its real env in an isolated subshell.
# Generic CI calls this script without an account and remains hermetic.
if [[ -n "$ACC" ]]; then
  ENVF="$BASE/accounts/$ACC.env"
  if [[ ! -f "$ENVF" ]]; then
    echo "worker preflight failed: account env not found: $ENVF" >&2
    exit 1
  fi
  echo "worker preflight: account config ($ACC)"
  (
    set -a
    # shellcheck disable=SC1090
    . "$ENVF"
    set +a
    export PROFI_DB="${PROFI_DB:-$BASE/data/$ACC.db}"
    export PROFI_RHYTHM_TAG="$ACC"
    uv run python -c "from profi import config; assert config.RESPOND_MODE in {'pay', 'commission'}; assert (not config.FAST_PATH_ENABLED) or (config.PROFILE_FALLBACK_ENABLED and config.PROFILE_FALLBACK_TEMPLATES), 'fast-path profile fallback is not configured'"
  )
fi

echo "worker preflight: compile"
uv run python -m compileall -q src/profi

echo "worker preflight: critical lint"
uv run ruff check \
  src/profi/integration/respond.py \
  src/profi/fastpath.py \
  src/profi/main.py

echo "worker preflight: response regressions"
uv run pytest -q \
  tests/test_respond_hidden_marker.py \
  tests/test_fast_path.py::TestProcessOpenCandidate::test_order_hidden_at_form_open_skips_before_llm \
  tests/test_fast_path.py::TestProcessOpenCandidate::test_form_open_failure_before_llm_is_terminal_failed \
  tests/test_fast_path_resilience.py::test_llm_cooldown_fallback_reaches_real_send_path

echo "worker preflight: OK"
