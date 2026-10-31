# Decisions

Hong's key decisions for agentic-media-stack, one line each, oldest first within each area.

## Scope and safety

- 2026-10-31: Start with a genuinely usable import and repair slice. Live systems are evidence only during development; the engine must never blocklist or delete downloads as part of an import.
- 2026-10-31: Clear Sonarr and Radarr imports may be automated only after deterministic matching and a post-import verification. Ambiguous matches remain review work.
- 2026-10-31: Diagnostics may recommend a restart, but never restart a container automatically and never exceed a configured restart cap.
- 2026-10-31: Live Sonarr, Radarr, and download-client endpoints are opt-in through environment variables. Configuration validation is offline and dry-run remains the default.

## Architecture

- 2026-10-31: Keep the first implementation dependency-light and adapter-driven so it can run on Unraid as a single CLI/API container while additional media apps are added behind the same interfaces.
