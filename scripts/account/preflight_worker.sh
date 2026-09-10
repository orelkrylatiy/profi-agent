#!/usr/bin/env bash
# Read-only code gate for production worker starts/restarts.
# Must complete before an existing worker is killed.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$BASE"

if ! command -v uv >/dev/null 2>&1; then
  echo "worker preflight failed: uv not found" >&2
  exit 1
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
  tests/test_fast_path.py::TestProcessOpenCandidate::test_form_open_failure_before_llm_is_terminal_failed

echo "worker preflight: OK"
