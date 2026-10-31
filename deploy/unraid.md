# Unraid

Copy `deploy/unraid.env.example` to `deploy/unraid.env`, fill in the private values, and keep that file out of git. Then validate the configuration without making network calls:

```bash
docker compose -f docker-compose.unraid.yml run --rm media-stack validate-config
```

Build and start the profile with `docker compose -f docker-compose.unraid.yml up -d`. It maps Hong's usual `/mnt/user/downloads` and appdata paths through environment variables, and exposes the service on port 8080. Start with `MEDIA_DRY_RUN=true`; inspect `GET /plan` and the JSONL audit before setting it false and using `--execute` for an explicitly approved import run.

When `SONARR_URL`, `RADARR_URL`, and a download-client URL plus credentials are present, the plan path reads those services through the configured adapters. The validation command remains offline and never tests credentials.

The container never needs access to the Docker socket and does not restart Gluetun, FlareSolverr, Prowlarr, or any other service. API keys belong in an environment file or Unraid secret field and are redacted from audit data.
