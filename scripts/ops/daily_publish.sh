#!/usr/bin/env bash
# Generate one privacy-safe daily snapshot and publish only ops/ files to GitHub.
# Intended for a clean VPS clone. Local/manual use can call daily_report.py directly.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATE_SPEC="${1:-yesterday}"
TIMEZONE="${OPS_TIMEZONE:-Asia/Yekaterinburg}"
BRANCH="${OPS_PUBLISH_BRANCH:-main}"
PYTHON_BIN="${OPS_PYTHON:-python3}"

cd "$BASE"

CURRENT_BRANCH="$(git branch --show-current)"
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
  echo "ops publish: текущая ветка '$CURRENT_BRANCH', ожидается '$BRANCH'" >&2
  exit 2
fi

# Scheduled publishing must never commit or pull across unrelated local edits.
NON_OPS_DIRTY="$(git status --porcelain --untracked-files=no | awk '{print substr($0,4)}' | grep -v '^ops/' || true)"
if [ -n "$NON_OPS_DIRTY" ]; then
  echo "ops publish: есть tracked-изменения вне ops/, push отменён" >&2
  echo "$NON_OPS_DIRTY" >&2
  exit 2
fi

NON_OPS_STAGED="$(git diff --cached --name-only | grep -v '^ops/' || true)"
if [ -n "$NON_OPS_STAGED" ]; then
  echo "ops publish: в index есть изменения вне ops/, push отменён" >&2
  echo "$NON_OPS_STAGED" >&2
  exit 2
fi

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "ops publish: Python не найден: $PYTHON_BIN" >&2
  exit 1
}

# Keep the clean VPS clone current before generating code_revision.
git pull --ff-only origin "$BRANCH"

# Collector uses only Python stdlib. Do not run it through uv: daily publishing
# must not depend on PyPI/DNS or reinstall project/dev dependencies.
REPORT_PATH="$("$PYTHON_BIN" scripts/ops/daily_report.py --date "$DATE_SPEC" --timezone "$TIMEZONE")"
if [ ! -f "$REPORT_PATH" ]; then
  echo "ops publish: отчёт не создан: $REPORT_PATH" >&2
  exit 1
fi

git add -- "$REPORT_PATH" ops/latest.json
if git diff --cached --quiet -- "$REPORT_PATH" ops/latest.json; then
  echo "ops publish: изменений за $DATE_SPEC нет"
  exit 0
fi

REPORT_DATE="$(basename "$REPORT_PATH" .json)"
git commit -m "ops: daily snapshot $REPORT_DATE" -- "$REPORT_PATH" ops/latest.json
git push origin "$BRANCH"
echo "ops publish: опубликован $REPORT_PATH"
