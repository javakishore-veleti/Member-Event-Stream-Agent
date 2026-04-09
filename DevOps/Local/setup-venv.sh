#!/usr/bin/env bash
# setup-venv.sh
# Create (or reuse) the project's Python virtualenv at a stable location under
# $HOME/runtime_data/python_venvs/Member-Event-Stream-Agent so it survives across
# repo clones and is easy to find from any tool.
set -euo pipefail

VENV_DIR="${MESA_VENV_DIR:-$HOME/runtime_data/python_venvs/Member-Event-Stream-Agent}"
PY_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$(dirname "$VENV_DIR")"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[venv] creating $VENV_DIR"
  "$PY_BIN" -m venv "$VENV_DIR"
else
  echo "[venv] reusing $VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip wheel setuptools

echo
echo "Venv ready at: $VENV_DIR"
echo "Activate with: source $VENV_DIR/bin/activate"
