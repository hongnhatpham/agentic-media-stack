# Unraid

Copy `deploy/unraid.env.example` to `deploy/unraid.env`, fill in the private values, and keep that file out of git. Then validate the configuration without making network calls:

```bash
docker compose -f docker-compose.unraid.yml run --rm media-stack validate-config
```

Build and start the profile with `docker compose -f docker-compose.unraid.yml up -d`. It maps Hong's usual `/mnt/user/downloads` and appdata paths through environment variables, and exposes the service on port 8080. Start with `MEDIA_DRY_RUN=true`; inspect `GET /plan` and the JSONL audit before setting it false and using `--execute` for an explicitly approved import run.

When `SONARR_URL`, `RADARR_URL`, and a download-client URL plus credentials are present, the plan path reads those services through the configured adapters. The validation command remains offline and never tests credentials.

For a disposable local check, use `docker compose -f docker-compose.mock.yml up --build`. It uses in-process mock indexer, qBittorrent, and Jellyfin adapters and does not reach Hong's live services. Before upgrading the real container, run `media-stack backup --destination /config/backups/state.db`; SQLite migrations are applied automatically on startup.

## Reverse proxy

Keep port 8080 on the private Docker network and terminate HTTPS at the reverse proxy. A minimal Caddy route is:

```text
media.example.internal {
    reverse_proxy media-stack:8080
}
```

Set `MEDIA_AUTH_TOKEN` even when the proxy already has access control. The application checks the token for every API write and does not trust forwarded identity headers.

The container never needs access to the Docker socket and does not restart Gluetun, FlareSolverr, Prowlarr, or any other service. API keys belong in an environment file or Unraid secret field and are redacted from audit data.
