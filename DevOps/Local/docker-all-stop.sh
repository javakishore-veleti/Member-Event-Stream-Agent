#!/usr/bin/env bash
# docker-all-stop.sh
# Stop and remove every local infra stack under DevOps/Local/<service>/docker-compose.yml.
# Named volumes (mesa_*_data) are preserved so data survives across restarts.
# Pass --volumes (or -v) to also delete the named volumes — destructive.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES=(postgres mongodb kafka)

DOWN_ARGS=()
if [[ "${1:-}" == "--volumes" || "${1:-}" == "-v" ]]; then
  echo "[warn] --volumes passed: named volumes will be DELETED."
  DOWN_ARGS+=("--volumes")
fi

for svc in "${SERVICES[@]}"; do
  compose_file="$SCRIPT_DIR/$svc/docker-compose.yml"
  if [[ ! -f "$compose_file" ]]; then
    echo "[skip] $svc — no docker-compose.yml at $compose_file"
    continue
  fi
  echo "[down] $svc"
  docker compose -f "$compose_file" down "${DOWN_ARGS[@]}"
done

echo
echo "All requested stacks are stopped."
