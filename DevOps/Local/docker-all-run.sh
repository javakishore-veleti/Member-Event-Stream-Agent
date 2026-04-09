#!/usr/bin/env bash
# docker-all-run.sh
# Bring up every local infra stack defined under DevOps/Local/<service>/docker-compose.yml.
# Each service is its own compose project so they can be started, stopped, and inspected
# independently. Run this from anywhere — paths are resolved relative to the script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES=(postgres mongodb kafka)

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
echo "All requested stacks are starting. Run docker-all-status.sh to verify health."
