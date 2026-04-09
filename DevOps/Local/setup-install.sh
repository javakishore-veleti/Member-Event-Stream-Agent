#!/usr/bin/env bash
# setup-install.sh
# Install this repository (and its dev extras) into the project venv created by
# setup-venv.sh. Editable install so source edits are picked up immediately.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="${MESA_VENV_DIR:-$HOME/runtime_data/python_venvs/Member-Event-Stream-Agent}"

if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
  echo "[err]  venv not found at $VENV_DIR — run setup-venv.sh first."
  exit 1
fi

echo "[pip]  installing $REPO_ROOT in editable mode (with [dev] extras)"
"$VENV_DIR/bin/pip" install -e "$REPO_ROOT[dev]"

echo
echo "Installed. Verify with:"
echo "  $VENV_DIR/bin/python -c 'import member_event_stream_agent; print(member_event_stream_agent.__version__)'"
