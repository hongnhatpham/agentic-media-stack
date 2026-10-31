#!/bin/sh
set -eu

# Docker CLI fallback for Unraid installations without the Compose plugin.
# This only replaces containers owned by this deployment. Existing media
# containers and their data are never stopped or reconfigured.

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file=${STACKARR_ENV_FILE:-$repo/deploy/unraid.env}
[ -f "$env_file" ] || { echo "missing env file: $env_file" >&2; exit 2; }

value() {
  sed -n "s/^$1=//p" "$env_file" | head -n 1
}

host_port=$(value STACKARR_HOST_PORT)
host_port=${host_port:-18080}
socket_path=$(value TAILSCALE_SOCKET_PATH)
socket_path=${socket_path:-/var/run/tailscale/tailscaled.sock}
state_path=$(value UNRAID_APPDATA_PATH)
state_path=${state_path:-/mnt/user/appdata/stackarr/state}
image=${STACKARR_IMAGE:-stackarr:$(git -C "$repo" rev-parse --short HEAD)}

docker network inspect arr >/dev/null 2>&1 || {
  echo 'required Docker network arr is missing' >&2
  exit 2
}
[ -S "$socket_path" ] || {
  echo "host Tailscale socket is missing: $socket_path" >&2
  exit 2
}

mkdir -p "$state_path/backups"
chmod 700 "$state_path" "$state_path/backups"
docker build --tag "$image" "$repo"

if docker inspect stackarr >/dev/null 2>&1; then
  docker exec stackarr media-stack backup \
    --destination "/config/backups/predeploy-$(date -u +%Y%m%dT%H%M%SZ).db" >/dev/null || true
  docker rm --force stackarr >/dev/null
fi
if docker inspect stackarr-tailscale >/dev/null 2>&1; then
  docker rm --force stackarr-tailscale >/dev/null
fi

docker run --detach \
  --name stackarr \
  --restart unless-stopped \
  --network arr \
  --publish "127.0.0.1:${host_port}:8080" \
  --env-file "$env_file" \
  --env MEDIA_DOWNLOADS_ROOT=/downloads \
  --env MEDIA_AUDIT_PATH=/config/audit.jsonl \
  --env MEDIA_STATE_PATH=/config/state.db \
  --volume /mnt/user/data:/downloads:ro \
  --volume "$state_path:/config" \
  --read-only \
  --tmpfs /tmp \
  --security-opt no-new-privileges:true \
  "$image" >/dev/null

for _ in $(seq 1 30); do
  status=$(docker inspect -f '{{.State.Health.Status}}' stackarr 2>/dev/null || true)
  [ "$status" = healthy ] && break
  sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' stackarr)" = healthy ] || {
  docker logs --tail 80 stackarr >&2 || true
  exit 1
}

docker run --detach \
  --name stackarr-tailscale \
  --restart unless-stopped \
  --network host \
  --entrypoint /bin/sh \
  --volume "$socket_path:/var/run/tailscale/tailscaled.sock" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --health-cmd "tailscale --socket=/var/run/tailscale/tailscaled.sock serve status --json | grep -q stackarr" \
  --health-interval 15s \
  --health-timeout 5s \
  --health-retries 8 \
  --health-start-period 30s \
  tailscale/tailscale:stable \
  -ec "tailscale --socket=/var/run/tailscale/tailscaled.sock serve --bg --service=svc:stackarr --https=443 127.0.0.1:${host_port} && exec sleep infinity" >/dev/null

echo 'stackarr containers started'
