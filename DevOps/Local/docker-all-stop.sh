#!/usr/bin/env bash
# docker-all-stop.sh
# Stop and remove every local infra stack under DevOps/Local/<service>/docker-compose.yml.
# By default, named volumes are preserved so data survives across restarts.
# Pass --volumes (or -v) to also delete the named volumes AND tear down the shared
# docker network — destructive, intended for a clean slate.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES=(postgres mongodb kafka)
NETWORK="${MESA_NETWORK:-mesa-local-net}"

DESTRUCTIVE=0
DOWN_ARGS=()
if [[ "${1:-}" == "--volumes" || "${1:-}" == "-v" ]]; then
  echo "[warn] --volumes passed: named volumes AND the '$NETWORK' network will be DELETED."
  DOWN_ARGS+=("--volumes")
  DESTRUCTIVE=1
fi

for svc in "${SERVICES[@]}"; do
  compose_file="$SCRIPT_DIR/$svc/docker-compose.yml"
  if [[ ! -f "$compose_file" ]]; then
    echo "[skip] $svc — no docker-compose.yml at $compose_file"
    continue
  fi
  echo "[down] $svc"
  docker compose -f "$compose_file" down "${DOWN_ARGS[@]}" || true
done

if [[ $DESTRUCTIVE -eq 1 ]]; then
  if docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "[net]  removing $NETWORK"
    docker network rm "$NETWORK" >/dev/null || true
  fi
fi

echo
echo "All requested stacks are stopped."
