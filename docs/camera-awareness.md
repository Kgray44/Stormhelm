# Camera Awareness

Camera Awareness is Stormhelm's explicit still-image lane for local camera context, artifact-backed visual analysis, helper results, comparison, and retake guidance. The backend owns routing, policy, provider selection, artifact lifecycle, provenance, telemetry, and UI view-model truth. Ghost Mode and Command Deck render backend state; they do not call camera hardware, vision providers, files, or cloud services directly.

Sources: `src/stormhelm/core/camera_awareness/`, `src/stormhelm/core/orchestrator/planner_v2.py`, `src/stormhelm/ui/camera_ghost_surface.py`, `src/stormhelm/ui/bridge.py`
Tests: `tests/test_camera_awareness_c0.py` through `tests/test_camera_awareness_c8_hardening_audit.py`, `tests/test_camera_awareness_planner.py`, `tests/test_camera_awareness_c4_deck_workspace.py`, `tests/test_camera_awareness_c7_guided_capture.py`

## Current Capabilities

- Disabled-by-default Camera Awareness config with mock-first providers.
- Route seam for explicit camera intent such as holding an object, asking for a camera still, or asking for retake guidance tied to camera/photo wording.
- Source-boundary protection for ambiguous visual requests, screen requests, uploaded images, files, clipboard, selected text, and general knowledge questions.
- Mock capture and mock vision paths for deterministic, hardware-free tests.
- Local single-still capture provider behind explicit policy and provider contracts.
- OpenAI/cloud vision provider integration behind separate cloud-analysis policy and confirmation gates.
- Ephemeral artifact metadata, readiness validation, expiry, cleanup, and safe preview refs.
- Explicit artifact save/retain foundation: when backend policy allows it and the user confirms, a fresh artifact can be marked saved with a safe `camera-library:*` ref. This prevents normal TTL expiry for that artifact metadata and records user-requested persistence without exposing raw image payloads.
- Ghost Mode camera cards for permission, capture/analyzing/status, answers, provenance, lifecycle, comparison, and guidance states.
- Command Deck visual artifact panel with safe artifact references, analysis details, provenance, lifecycle, trace-style details, and explicit backend-grounded actions where supported.
- Extensible helper-tool registry with `engineering_inspection` as the first helper category.
- Bounded multi-capture sessions and still-image comparison as visual evidence only.
- Guided capture-quality and retake guidance from existing artifact metadata, provider/helper uncertainty, and comparison/session state.
- C8 hardening coverage for routing pressure, policy separation, no-side-effect rendering/status reads, raw payload leakage, lifecycle cleanup, provider boundary failures, helper truthfulness, comparison truthfulness, guidance truthfulness, and Ghost/Deck consistency.

## Permission Boundaries

Camera Awareness separates these permissions:

- Capture permission: allows one explicit still capture only.
- Cloud analysis permission: allows an existing authorized artifact to leave the device for cloud vision only when global and vision-specific cloud flags allow it and confirmation gates pass.
- Save/attach permission: allows persistence only when explicit user action and backend policy permit it.
- Memory/task mutation permission: not granted by camera output.

Capture permission does not imply cloud analysis. Cloud analysis does not imply persistence. Save permission does not imply cloud analysis.

The save foundation is not automatic. `camera_awareness.allow_task_artifact_save` must be enabled, and save confirmation must be present for the backend save call to succeed.

Sources: `src/stormhelm/core/camera_awareness/policy.py`, `src/stormhelm/config/models.py`
Tests: `tests/test_camera_awareness_c21_boundary_hardening.py`, `tests/test_camera_awareness_c8_hardening_audit.py`

## Artifact Lifecycle

Artifacts are ephemeral by default. Normal status, telemetry, bridge, Ghost, and Deck payloads use metadata and safe refs, not raw bytes or base64. Readiness validation checks freshness, existence, readability, format, size, and provenance before analysis. Expired or missing artifacts block follow-up analysis/comparison truthfully. Cleanup attempts report typed success, pending, or failed state; cleanup failure is not reported as success.

When a user explicitly saves an eligible artifact, the artifact is moved to `saved` storage mode in Camera Awareness metadata and receives a safe library ref. This is not enabled by default and does not grant cloud analysis, task mutation, memory write, or camera action authority.

Sources: `src/stormhelm/core/camera_awareness/artifacts.py`, `src/stormhelm/core/camera_awareness/service.py`
Tests: `tests/test_camera_awareness_c11_artifact_readiness.py`, `tests/test_camera_awareness_c21_boundary_hardening.py`, `tests/test_camera_awareness_c8_hardening_audit.py`

## Privacy And Raw Payload Rules

Normal surfaces must not expose raw image bytes, base64/data URLs, provider request bodies, API keys, or unbounded raw provider responses. Image encoding is allowed only inside bounded provider request construction after policy and artifact validation pass.

Surfaces covered by tests include:

- service status,
- telemetry/event payloads,
- traces,
- Ghost cards,
- Command Deck panels,
- helper results,
- comparison results,
- guidance results,
- bridge composer/action/route-inspector surfaces.

Sources: `src/stormhelm/core/camera_awareness/telemetry.py`, `src/stormhelm/core/camera_awareness/providers.py`, `src/stormhelm/ui/camera_ghost_surface.py`
Tests: `tests/test_camera_awareness_c21_boundary_hardening.py`, `tests/test_camera_awareness_c4_deck_workspace.py`, `tests/test_camera_awareness_c8_hardening_audit.py`

## Visual Evidence Boundary

Camera Awareness output is visual evidence, not verification. It must not claim measured resistance, voltage, continuity, exact dimensions, repair success, safety certification, task completion, action execution, trust approval, identity recognition, or biometric inference from image content alone. Helper, comparison, and guidance models force action/verification flags false unless a separate trusted subsystem later supplies proof.

Sources: `src/stormhelm/core/camera_awareness/models.py`, `src/stormhelm/core/camera_awareness/helpers.py`, `src/stormhelm/core/camera_awareness/comparison.py`, `src/stormhelm/core/camera_awareness/guidance.py`
Tests: `tests/test_camera_awareness_c5_engineering_helpers.py`, `tests/test_camera_awareness_c6_multi_capture_comparison.py`, `tests/test_camera_awareness_c7_guided_capture.py`, `tests/test_camera_awareness_c8_hardening_audit.py`

## Non-Goals

Not implemented:

- live video or continuous frames,
- background monitoring,
- automatic capture or automatic retake,
- motion detection or surveillance,
- face, identity, emotion, or biometric analysis,
- image persistence by default,
- automatic datasheet or web lookup,
- camera-based command execution,
- provider-driven routing, approval, task mutation, or verification.

Manual live-provider smoke tests, when present, must remain opt-in and disabled by default. Normal tests remain hardware-free and network-free.
