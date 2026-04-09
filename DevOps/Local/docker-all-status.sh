#!/usr/bin/env bash
# docker-all-status.sh
# Show ps + health for every local infra stack under DevOps/Local/<service>/docker-compose.yml.
# Read-only — never modifies state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES=(postgres mongodb kafka)

for svc in "${SERVICES[@]}"; do
  compose_file="$SCRIPT_DIR/$svc/docker-compose.yml"
  if [[ ! -f "$compose_file" ]]; then
    echo "[skip] $svc — no docker-compose.yml at $compose_file"
    continue
  fi
  echo "==== $svc ===="
  docker compose -f "$compose_file" ps
  echo
done
