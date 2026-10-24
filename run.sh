#!/usr/bin/env bash
set -euo pipefail

# Run from the project root so saved drafts always use the same database.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ -x .venv/bin/python ]]; then
  python=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  python=python3
elif command -v python >/dev/null 2>&1; then
  python=python
else
  printf 'Python 3.11+ is required. Install Python and run this script again.\n' >&2
  exit 1
fi

# The backend also serves the frontend; no separate build or dev server needed.
exec "$python" -m operator_app.server "$@"
