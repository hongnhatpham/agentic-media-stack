# Unraid

Build the image from this repository, map the completed-download directory as read-only at `/downloads`, and map an appdata directory at `/config`. Start with `MEDIA_DRY_RUN=true`; inspect `GET /plan` and the JSONL audit before enabling any explicit import adapter.

The container never needs access to the Docker socket and does not restart Gluetun, FlareSolverr, Prowlarr, or any other service. API keys belong in an environment file or Unraid secret field and are redacted from audit data.
