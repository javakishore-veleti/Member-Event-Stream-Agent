#!/usr/bin/env bash
# docker-all-run.sh
# Ensure the shared docker network exists, then bring up every local infra stack
# defined under DevOps/Local/<service>/docker-compose.yml. Each service is its own
# compose project; they all attach to the dedicated mesa-local-net network so they
# can reach each other by container name.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES=(postgres mongodb kafka)
NETWORK="${MESA_NETWORK:-mesa-local-net}"

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "[net]  creating $NETWORK"
  docker network create "$NETWORK" >/dev/null
else
  echo "[net]  $NETWORK already exists"
fi

for svc in "${SERVICES[@]}"; do
  compose_file="$SCRIPT_DIR/$svc/docker-compose.yml"
  if [[ ! -f "$compose_file" ]]; then
    echo "[skip] $svc — no docker-compose.yml at $compose_file"
    continue
  fi
  echo "[up]   $svc"
  docker compose -f "$compose_file" up -d
done

echo
echo "All requested stacks are starting on network '$NETWORK'."
echo "Run docker-all-status.sh to verify health."
