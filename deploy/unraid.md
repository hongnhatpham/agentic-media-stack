# Unraid

The deployment uses the existing `arr` Docker network and binds the app to Unraid's loopback only. A helper container uses the already-authenticated host Tailscale socket to configure Tailscale HTTPS Serve; it does not start a second Tailscale daemon or need an auth key.

```bash
install -m 600 deploy/unraid.env.example deploy/unraid.env
```

Set the real values on Unraid. `TAILSCALE_SOCKET_PATH` should point to the host daemon socket, normally `/var/run/tailscale/tailscaled.sock`. `STACKARR_HOST_PORT` defaults to the loopback-only port 18080 because Gluetun already owns host port 8080.

Tailscale service hosts must be tagged. The host node must already be authorized with `tag:stackarr`; the deployment helper checks this and exits before changing containers if it is missing. This tag does not advertise or remove subnet routes.

Validate the configuration without making network calls:

```bash
docker compose -f docker-compose.unraid.yml run --rm stackarr validate-config
```

Unraid installs without the Compose plugin can run `deploy/unraid-run.sh` instead. It builds the image, keeps a pre-deploy SQLite backup, starts the loopback-only app, and starts the host-socket Tailscale helper:

```bash
deploy/unraid-run.sh
```

Build and start the stack with `docker compose -f docker-compose.unraid.yml up -d --build`. It maps the existing `/mnt/user/data` tree read-only at `/downloads`, persists state and audit data in `/mnt/user/appdata/stackarr`, and keeps `MEDIA_DRY_RUN=true`. The requested URL is `https://stackarr.feist-beardie.ts.net`; the helper advertises the `svc:stackarr` Tailscale service and HTTPS Serve terminates TLS. The only host binding is loopback `127.0.0.1:18080` by default.

The helper runs `tailscale serve --service=svc:stackarr --https=443 127.0.0.1:18080` through the mounted host socket. Tailscale may require an administrator to approve the new service host once; that approval is a tailnet policy action, not a secret handoff.

The existing qBittorrent container shares Gluetun's network namespace. Its WebUI/API is therefore `http://GluetunVPN:8080` from the `arr` network. The current qBittorrent password is stored only as a hash in its config, so leave `qbittorrent` out of `MEDIA_DOWNLOAD_CLIENTS` until a plaintext credential is supplied through the protected env file. Do not change qBittorrent's config to work around that.

When `SONARR_URL`, `RADARR_URL`, and a download-client URL plus credentials are present, the plan path reads those services through the configured adapters. The validation command remains offline and never tests credentials.

For a disposable local check, use `docker compose -f docker-compose.mock.yml up --build`. It uses in-process mock indexer, qBittorrent, and Jellyfin adapters and does not reach Hong's live services. Before upgrading the real container, run `media-stack backup --destination /config/backups/state.db`; SQLite migrations are applied automatically on startup.

Set `MEDIA_AUTH_TOKEN` even though the URL is private. The application checks the token for every API endpoint and does not trust forwarded identity headers.

The container never needs access to the Docker socket and does not restart Gluetun, FlareSolverr, Prowlarr, or any other service. API keys belong in an environment file or Unraid secret field and are redacted from audit data.
