# Agent instructions

`DECISIONS.md` contains the durable architecture and safety choices. Read it before changing the engine or adapters.

Use `python -m pytest` and `python -m ruff check .` for local checks. Keep all live media integrations read-only unless an explicit, verified import action is being executed through the engine. Never log credentials, API keys, or full authorization headers.
