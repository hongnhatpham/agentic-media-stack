# Agentic Media Stack

Agentic Media Stack is a single, explainable automation engine for media imports and repair. Its shared media graph joins completed downloads from download-client adapters to candidates from media-app adapters. The first slice scores those links, plans safe actions, verifies an accepted import, and writes an audit trail with provenance and rollback information.

## Safety model

- Discovery is read-only. The default CLI has no live app adapters.
- Plans are dry-run by default. Only a deterministic high-confidence match becomes an import action.
- Ambiguous matches are review items with their score and reasons.
- Import execution never blocklists or deletes the original download.
- Rollback is recorded when an adapter supports it. The generic HTTP adapter reports unsupported rollback instead of pretending it exists.
- Diagnostics explain the Gluetun, FlareSolverr, and Prowlarr failure pattern. They never restart containers automatically and honour a restart cap.
- `agentic_media_stack.diagnostics` accepts injectable service probes, so Unraid health checks can use the deployment's network path without coupling the core engine to Docker.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
MEDIA_DOWNLOAD_MANIFEST=tests/fixtures/downloads.json \
MEDIA_CANDIDATE_MANIFEST=tests/fixtures/candidates.json \
MEDIA_AUDIT_PATH=/tmp/media-stack-audit.jsonl \
media-stack plan
python -m pytest
python -m ruff check .
```

For a complete local flow without any live service, run `MEDIA_MOCK_MODE=true MEDIA_STATE_PATH=/tmp/media-state.db MEDIA_AUDIT_PATH=/tmp/media-audit.jsonl media-stack serve` and open `http://localhost:8080`. The mock indexer, qBittorrent queue, progress updates, jobs, and authenticated API flow are covered by `tests/test_mock_e2e.py`.

`MEDIA_DOWNLOADS_ROOT`, `MEDIA_DOWNLOAD_MANIFEST`, `MEDIA_CANDIDATE_MANIFEST`, `MEDIA_AUDIT_PATH`, `MEDIA_STATE_PATH`, `MEDIA_DRY_RUN`, `MEDIA_RESTART_CAP`, `MEDIA_HTTP_TIMEOUT`, `MEDIA_DOWNLOAD_CLIENTS`, and `MEDIA_AUTH_TOKEN` configure the process. `SONARR_URL` and `SONARR_API_KEY`, `RADARR_URL` and `RADARR_API_KEY`, `PROWLARR_URL` and `PROWLARR_API_KEY`, `JELLYFIN_URL` and `JELLYFIN_API_KEY`, `QBITTORRENT_URL` with its username/password, and `SABNZBD_URL` with `SABNZBD_API_KEY` enable live adapters. Secrets are supplied through environment variables and never written to validation output or audit events.

Run `media-stack validate-config` before `plan`. It checks URL shape, required credential pairs, enabled client names, and local manifest paths without contacting any service. It exits non-zero for invalid configuration and prints only redacted fields.

State migrations run automatically when the process starts. Use `media-stack migrate` after a container update and `media-stack backup --destination /config/backups/state-$(date +%Y%m%d-%H%M%S).db` before maintenance. Back up the mounted `/config` directory as well as the SQLite database so audit history and environment files stay together.

## API and Unraid

`media-stack serve` exposes `GET /health` and `GET /plan` on port 8080. See [deploy/unraid.md](deploy/unraid.md), `docker-compose.yml`, and `docker-compose.unraid.yml` for a read-only volume layout. Live adapters are selected from environment configuration; the default remains dry-run.

## Limitations

The HTTP adapter currently supports Sonarr/Radarr-shaped discovery and command submission, not every app-specific import workflow. Lidarr, Bazarr, Whisparr, Prowlarr, Seerr, and Jellyfin are represented by the same adapter boundary but need app-specific adapters and fixtures. Live import verification requires an endpoint that can report the resulting file, so the default deployment remains dry-run.
