# Historical Documentation Archive

This page indexes the documentation that existed before the practical KGFS-style rewrite. These documents are historical planning/source material. Users should not need to read them to understand the current product.

The current reader-facing docs are:

- [Docs home](../README.md)
- [Feature inventory](../features.md)
- [Usage](../usage.md)
- [Commands](../commands.md)
- [Architecture](../architecture.md)
- [Roadmap](../roadmap.md)

## What The Old Docs Were For

The previous docs mixed architecture notes, phase reviews, packaging notes, release checklists, generated reports, superpowers plans/specs, and voice design material. They were useful during build-out, but they were not a clean user/developer manual.

This rewrite treats them as source material only. Useful current behavior was re-derived from source code, tests, config, scripts, and package files.

## Superseded Main Docs

| Historical path | What it was for | Current status | Replacement |
|---|---|---|---|
| `docs/architecture-overview.md` | Early architecture overview and phase framing. | Superseded. Historical reference only. | [architecture.md](../architecture.md), [subsystems.md](../subsystems.md) |
| `docs/phase1-2-review.md` | Phase 1.2 architecture review. | Superseded. Historical reference only. | [architecture.md](../architecture.md), [features.md](../features.md) |
| `docs/packaging.md` | Packaging strategy notes. | Superseded. Historical reference only. | [development.md](../development.md), [integrations.md](../integrations.md) |
| `docs/release-checklist.md` | Release checklist. | Superseded. Historical reference only. | [development.md](../development.md), [testing-evaluation.md](../testing-evaluation.md), [troubleshooting.md](../troubleshooting.md) |
| Old `docs/roadmap.md` | Phase-based roadmap. | Replaced in place by current implemented-vs-planned roadmap. | [roadmap.md](../roadmap.md) |

## Generated Reports

| Historical path | What it was for | Current status |
|---|---|---|
| `docs/reports/stormhelm-feature-book.*` | Generated feature-book artifacts. | Historical report artifacts. Not part of current docs navigation. |
| `docs/reports/stormhelm-improvement-book.*` | Generated improvement-book artifacts. | Historical report artifacts. Not part of current docs navigation. |
| `docs/reports/stormhelm-full-file-manifest.*` | Generated file manifest artifacts. | Historical report artifacts. Use `git ls-files` and source tree directly for current truth. |
| `docs/reports/debug-pdf*/*` | PDF/font rendering debug artifacts. | Historical debug artifacts. Not current product docs. |

## Superpowers Plans And Specs

| Historical path | What it was for | Current status | Replacement |
|---|---|---|---|
| `docs/superpowers/plans/2026-04-18-stormhelm-phase1-foundation.md` | Phase 1 implementation plan. | Historical planning material. | [features.md](../features.md), [architecture.md](../architecture.md) |
| `docs/superpowers/specs/2026-04-18-stormhelm-phase1-design.md` | Phase 1 design spec. | Historical planning material. | [architecture.md](../architecture.md) |
| `docs/superpowers/plans/2026-04-18-stormhelm-glass-field-plan.md` | UI/visual plan. | Historical design reference. | [ui-surfaces.md](../ui-surfaces.md) |
| `docs/superpowers/specs/2026-04-18-stormhelm-glass-field-design.md` | UI/visual design spec. | Historical design reference. | [ui-surfaces.md](../ui-surfaces.md) |
| `docs/superpowers/plans/2026-04-20-stormhelm-phase2b-memory-context.md` | Memory/context plan. | Historical planning material. | [data-model.md](../data-model.md), [subsystems.md](../subsystems.md) |
| `docs/superpowers/specs/2026-04-20-stormhelm-phase2b-memory-context-design.md` | Memory/context design spec. | Historical design reference. | [data-model.md](../data-model.md), [subsystems.md](../subsystems.md) |
| `docs/superpowers/specs/2026-04-20-stormhelm-hardware-telemetry-design.md` | Hardware telemetry design. | Historical design reference. | [integrations.md](../integrations.md), [subsystems.md](../subsystems.md) |

## Voice Design Documents

Untracked voice documents were present under `docs/stormhelm_voice_docs/` during this rewrite.

| Historical path | What it was for | Current status | Replacement |
|---|---|---|---|
| `docs/stormhelm_voice_docs/README.md` | Voice docs folder index. | Planned/scaffolded reference only. | [roadmap.md](../roadmap.md) |
| `docs/stormhelm_voice_docs/01_stormhelm_voice_master_book.md` | Voice master book. | Planned/scaffolded reference only. | [roadmap.md](../roadmap.md) |
| `docs/stormhelm_voice_docs/02_openai_voice_research_and_provider_strategy.md` | OpenAI voice/provider research. | Planned/scaffolded reference only. | [integrations.md](../integrations.md) |
| `docs/stormhelm_voice_docs/03_voice_architecture_and_data_contracts.md` | Voice architecture/data contracts. | Planned/scaffolded reference only. | [roadmap.md](../roadmap.md) |
| `docs/stormhelm_voice_docs/04_voice_implementation_roadmap_and_codex_prompt.md` | Voice implementation roadmap/prompt material. | Planned/scaffolded reference only. | [roadmap.md](../roadmap.md) |
| `docs/stormhelm_voice_docs/05_voice_acceptance_and_test_book.md` | Voice acceptance/test design. | Planned/scaffolded reference only. | [testing-evaluation.md](../testing-evaluation.md) |

Current source truth: a QML `VoiceCore` component exists, but no backend voice subsystem package or voice settings section was found in the tracked source/config set during this rewrite.

Sources: `assets/qml/components/VoiceCore.qml`, `config/default.toml`, `src/stormhelm/core`  
Tests: `tests/test_qml_shell.py`; no backend voice pipeline tests found

## How To Use Historical Docs

Use phase docs only for:

- Understanding why a design direction was chosen.
- Recovering old packaging/release checklist context.
- Comparing planned voice/UI/memory directions against current implementation.
- Mining ideas for future tickets.

Do not use phase docs as proof that a feature exists. For current behavior, prefer:

1. Source files.
2. Tests.
3. Config defaults.
4. Current docs in this folder.

## Local Preservation

During this rewrite, the current docs were preserved in a local worktree snapshot before overwriting/removing repo-facing docs. That snapshot is not intended to be the GitHub documentation experience; it is preservation material so historical content is not lost locally while the repository docs become clean and current.

## Supersession Rule

If an old phase document conflicts with a current source-referenced doc, the current doc wins only when it cites implementation/config/tests. If neither document cites current implementation, verify the code before making a product claim.
