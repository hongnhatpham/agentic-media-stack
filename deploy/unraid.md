# Unraid

The deployment uses the existing `arr` Docker network, does not publish a host port, and exposes the app only through the Tailscale sidecar. Copy both examples to protected files, set mode 600, and keep them out of git:

```bash
install -m 600 deploy/unraid.env.example deploy/unraid.env
install -m 600 deploy/tailscale.env.example deploy/tailscale.env
```

Set the real values on Unraid. `TS_AUTHKEY` must be a reusable or pre-authorized tailnet auth key. The sidecar uses persistent state under `/mnt/user/appdata/stackarr/tailscale` and does not advertise routes.

Validate the configuration without making network calls:

```bash
docker compose -f docker-compose.unraid.yml run --rm stackarr validate-config
```

Build and start the stack with `docker compose -f docker-compose.unraid.yml up -d --build`. It maps the existing `/mnt/user/data` tree read-only at `/downloads`, persists state and audit data in `/mnt/user/appdata/stackarr`, and keeps `MEDIA_DRY_RUN=true`. The requested URL is `https://stackarr.feist-beardie.ts.net`; Tailscale HTTPS Serve terminates TLS and proxies to the app's private port 8080. There is no host port publication.

The existing qBittorrent container shares Gluetun's network namespace. Its WebUI/API is therefore `http://GluetunVPN:8080` from the `arr` network. The current qBittorrent password is stored only as a hash in its config, so leave `qbittorrent` out of `MEDIA_DOWNLOAD_CLIENTS` until a plaintext credential is supplied through the protected env file. Do not change qBittorrent's config to work around that.

When `SONARR_URL`, `RADARR_URL`, and a download-client URL plus credentials are present, the plan path reads those services through the configured adapters. The validation command remains offline and never tests credentials.

For a disposable local check, use `docker compose -f docker-compose.mock.yml up --build`. It uses in-process mock indexer, qBittorrent, and Jellyfin adapters and does not reach Hong's live services. Before upgrading the real container, run `media-stack backup --destination /config/backups/state.db`; SQLite migrations are applied automatically on startup.

Set `MEDIA_AUTH_TOKEN` even though the URL is private. The application checks the token for every API endpoint and does not trust forwarded identity headers.

The container never needs access to the Docker socket and does not restart Gluetun, FlareSolverr, Prowlarr, or any other service. API keys belong in an environment file or Unraid secret field and are redacted from audit data.
