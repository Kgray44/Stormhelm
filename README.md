# Stormhelm

Stormhelm is a local-first Windows desktop assistant. The current repository contains a FastAPI core service, a PySide6/QML shell, deterministic routing, local tools, SQLite persistence, event streaming, trust gates, and several bounded subsystems for calculations, screen-aware help, software planning, recovery, Discord relay previews, task continuity, and workspace state.

Start with the documentation map in [docs/README.md](docs/README.md). It is the source-referenced entry point for what is implemented now, what is limited, and what is still planned.

## Quick Start

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev,packaging]

.\scripts\run_core.ps1
.\scripts\run_ui.ps1
```

Useful local checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/settings
```

OpenAI is disabled by default. Set `OPENAI_API_KEY` and `STORMHELM_OPENAI_ENABLED=true` only if you want provider-backed fallback behavior.

## Documentation

- [Docs home](docs/README.md)
- [Feature inventory](docs/features.md)
- [Usage workflows](docs/usage.md)
- [Commands and route families](docs/commands.md)
- [Architecture](docs/architecture.md)
- [Settings reference](docs/settings.md)
- [Security and trust](docs/security-and-trust.md)
- [Development](docs/development.md)
- [Archive of historical planning docs](docs/archive/phase-documents.md)

Older phase books, reports, and planning specs are not the main documentation path anymore. They are indexed as historical material in the archive page.
