# Stormhelm Latency Integration Audit

Phase L5A is an evidence ledger for the L0-L5 latency, async, worker, continuation, and voice stack. It does not add new runtime behavior. A feature is labeled live only when a normal path uses it and tests plus trace/status/Kraken surfaces expose it.

Machine-readable inventory is available through `stormhelm.core.latency_integration_audit.build_latency_integration_audit().to_dict()`. The markdown table below mirrors that inventory for human review.

## Executive Summary

- Fully live: L0 trace contracts, `/chat/send` latency metadata, command-eval latency projection, voice latency projection, route latency policy, fail-fast posture, L2 route triage, provider fallback suppression, the core context snapshot store, worker lane/timing, inline fast-path protection, workspace assemble continuation, L4.4 reporting, priority scheduler/caps, streaming TTS contracts, true OpenAI HTTP streaming, Windows local progressive speaker playback, normal assistant voice output streaming, and voice first-audio metrics.
- Partially wired: partial-response posture, snapshot policy breadth, invalidation hooks, async route progress contracts, most L4.3 continuation handlers, scheduler retry/yield/cancel cooperation, non-Windows speaker streaming, and broad UI rendering depth.
- Scaffold or policy-only: background refresh hooks, screen verify-change continuation, and software execute-approved-operation continuation.
- Future-deferred: none in this inventory.
- Dead/unknown: none identified in this inventory.

## Fully Live And Used

- `l0.latency_trace_contract`
- `l0.chat_send_metadata`
- `l0.command_eval_latency_projection`
- `l0.voice_latency_projection`
- `l1.route_latency_policy`
- `l1.fail_fast_posture`
- `l2.fast_route_classifier`
- `l2.provider_fallback_suppression`
- `l3.context_snapshot_store`
- `l41.job_manager_lane_timing`
- `l41.inline_fast_path_protection`
- `l42.workspace_assemble_deep_continuation`
- `l44.validation_and_kraken_reporting`
- `l45.priority_scheduler_and_caps`
- `l5.streaming_tts_contracts`
- `l5.true_openai_http_streaming`
- `l5.local_live_playback_backend_streaming`
- `l5.normal_assistant_voice_output_streaming`
- `l5.voice_first_audio_metrics`

## Partially Wired

- `l1.partial_response_posture`: metadata and first-feedback events are live, but non-blocking behavior depends on route/tool continuation seams.
- `l3.snapshot_family_policy_matrix`: all families have policies; only a subset is actively refreshed in normal request paths.
- `l3.snapshot_invalidation_hooks`: workspace invalidation is wired; many families rely on TTL.
- `l4.async_route_progress_contract`: live for job-backed async tools, not universal for direct subsystem routes.
- `l43.workspace_restore_deep_continuation`: handler exists, normal front-half creation is not broad.
- `l43.software_verify_operation_continuation`: handler exists and is tested through the runner, not automatically used by broad software routes.
- `l43.software_recovery_plan_continuation`: handler exists, direct recovery routes are not broadly converted.
- `l43.discord_dispatch_approved_preview_continuation`: handler exists with approval/fingerprint gates, dispatch front-half conversion is narrow.
- `l43.network_live_diagnosis_continuation`: handler exists, normal network route conversion is narrow.
- `l45.retry_yield_cancellation_cooperation`: JobManager tracks states, but real tool cooperation is not broad.
- `ui.status_and_deck_surfaces`: backend status is richer than the current UI proof surface.

## Scaffold Or Policy Only

- `l41.background_refresh_hook`: background lane helper exists; broad automatic refresh jobs are not scheduled.
- `l43.screen_awareness_verify_change_continuation`: policy-known, handler-missing, correctly reported by L4.4 coverage.
- `l42.software_execute_approved_operation_continuation`: policy-known but intentionally deferred until trust/side-effect front halves are proofed.

## Test-only, Dead, Or Unknown

None identified in the L5A inventory.

## Risk Ranking

- High: software execute continuations must not be claimed as worker-backed route behavior until the trust/side-effect front half is proofed.
- Medium: wake-loop streaming breadth, snapshot invalidation breadth, background refresh coverage, retry/yield/cancel cooperation, continuation handler reachability, non-Windows speaker streaming, and broad UI rendering depth need burn-down.
- Low: L0 tracing, route triage, provider suppression, core worker timing, inline fast-path protection, scheduler cap mechanics, streaming TTS contracts, true OpenAI HTTP streaming, Windows local progressive speaker playback, and normal assistant voice-output streaming are wired and tested.

## Recommended L5.1 Scope

- Keep normal assistant voice output on `VoiceService.stream_core_approved_spoken_text` when streaming is enabled and speech is allowed.
- Keep the OpenAI true HTTP stream path and buffered projection labels distinct.
- Keep Windows local progressive speaker playback as the supported desktop path and report typed unsupported state on non-Windows or unavailable backends.
- Keep mock smoke benchmarks for request-to-first-audio and Core-result-to-first-audio, and run opt-in live smoke when device/network credentials are available.
- Keep buffered fallback explicit and prevent duplicate speech.

## Recommended Later Phases

- Broaden event-driven snapshot invalidation and safe background refresh coverage.
- Convert more subsystem front halves only after trust, freshness, and verification seams are explicit.
- Tune scheduler pressure with real Kraken load and add cooperative cancellation/yield checks to selected safe tools.
- Add Deck-focused rendering for worker, scheduler, continuation, and voice first-audio details while keeping Ghost compact.

## Evidence Table

| Feature | Phase | Status | Runtime usage | Test coverage | Trace/Kraken visibility | Risk | Recommendation | Future phase |
|---|---|---|---|---|---|---|---|---|
| `l0.latency_trace_contract` | L0 | live_used | Normal responses normalize stage timings into latency trace and summary. | `tests/test_latency_l0_tracing.py` | trace, summary, budget, longest stage | Low | keep | |
| `l0.chat_send_metadata` | L0 | live_used | `/chat/send` preserves stage timings and attaches latency metadata. | `tests/test_latency_l0_tracing.py`, `tests/test_assistant_orchestrator.py` | endpoint timings, stage timings, trace | Low | keep | |
| `l0.command_eval_latency_projection` | L0 | live_used | Command eval rows project latency summary into row and aggregate fields. | `tests/test_command_usability_evaluation.py`, `tests/test_latency_l0_tracing.py` | p50/p90/p95/p99/max, longest stage | Low | keep | |
| `l0.voice_latency_projection` | L0 | live_used | Voice evaluation projects marks into unified summary shape. | `tests/test_voice_latency_instrumentation.py`, `tests/test_latency_l5_voice_streaming_first_audio.py` | voice summary, voice first-audio rows | Low | keep | |
| `l1.route_latency_policy` | L1 | live_used | Route family/request kind selects budget and execution mode. | `tests/test_latency_l1_budget_partial_response.py` | budget labels, execution modes, fail-fast fields | Low | keep | |
| `l1.partial_response_posture` | L1 | partial_used | Metadata and first-feedback events are attached; behavior is route-dependent. | `tests/test_latency_l1_budget_partial_response.py`, `tests/test_latency_l4_async_progress.py` | partial response, async expected, first feedback | Medium | defer_to_phase | L5.1/L6 |
| `l1.fail_fast_posture` | L1 | live_used | Provider/voice/playback unavailable states return typed reasons. | `tests/test_latency_l1_budget_partial_response.py` | fail_fast_reason, unsupported execution mode | Low | keep | |
| `l2.fast_route_classifier` | L2 | live_used | `/chat/send` runs triage before planner and passes advisory hints. | `tests/test_latency_l2_fast_route_triage.py` | route_triage_ms, likely/skipped families | Low | keep | |
| `l2.provider_fallback_suppression` | L2 | live_used | Native-owned triage suppresses provider fallback eligibility. | `tests/test_latency_l2_fast_route_triage.py` | native_route_triage suppression counts | Low | keep | |
| `l3.context_snapshot_store` | L3 | live_used | Assistant uses snapshots according to route triage and workspace summary needs. | `tests/test_latency_l3_context_snapshots.py` | snapshots used/refreshed/missed | Low | keep | |
| `l3.snapshot_family_policy_matrix` | L3 | partial_used | Policies exist for all families; only some populate in normal paths. | `tests/test_latency_l3_context_snapshots.py` | freshness, age, warnings | Medium | label_future | L5.1/L6 |
| `l3.snapshot_invalidation_hooks` | L3 | partial_used | Workspace invalidation is wired; many families rely on TTL. | `tests/test_latency_l3_context_snapshots.py` | invalidation count, freshness warnings | Medium | defer_to_phase | L5.1/L6 |
| `l4.async_route_progress_contract` | L4 | partial_used | Registered async tools can return handles; direct subsystems vary. | `tests/test_latency_l4_async_progress.py` | async strategy, continuation id, progress events | Medium | defer_to_phase | L5.1/L6 |
| `l41.job_manager_lane_timing` | L4.1 | live_used | Every queued job records lane, queue wait, run time, and worker index. | `tests/test_latency_l41_worker_utilization.py`, `tests/test_job_manager.py` | worker lane, queue/run/total job timing | Low | keep | |
| `l41.background_refresh_hook` | L4.1 | scaffold_only | Helper submits background-lane jobs; broad refresh scheduling is absent. | `tests/test_latency_l41_worker_utilization.py` | background job counts | Medium | label_future | L5.1/L6 |
| `l41.inline_fast_path_protection` | L4.1 | live_used | Cheap deterministic routes remain inline. | `tests/test_latency_l41_worker_utilization.py` | worker policy fields | Low | keep | |
| `l42.workspace_assemble_deep_continuation` | L4.2 | live_used | Workspace assemble front half creates a worker continuation job. | `tests/test_latency_l42_subsystem_continuations.py` | continuation created, returned before completion | Low | keep | |
| `l43.workspace_restore_deep_continuation` | L4.3 | partial_used | Handler registered; no broad automatic front-half creation. | `tests/test_latency_l43_subsystem_continuation_expansion.py` | handler status, truth clamps | Medium | defer_to_phase | L5.1 |
| `l43.software_verify_operation_continuation` | L4.3 | partial_used | Handler registered/tested through runner; broad software route offload is absent. | `tests/test_latency_l43_subsystem_continuation_expansion.py` | handler status, evidence counts | Medium | defer_to_phase | L5.1 |
| `l43.software_recovery_plan_continuation` | L4.3 | partial_used | Handler registered; direct recovery route conversion is narrow. | `tests/test_latency_l43_subsystem_continuation_expansion.py` | handler status, recovery truth clamps | Medium | defer_to_phase | L5.1 |
| `l43.discord_dispatch_approved_preview_continuation` | L4.3 | partial_used | Handler registered with approval/fingerprint gates; front-half conversion is narrow. | `tests/test_latency_l43_subsystem_continuation_expansion.py` | handler status, delivery truth clamps | Medium | defer_to_phase | L5.1 |
| `l43.network_live_diagnosis_continuation` | L4.3 | partial_used | Handler registered/tested; normal route conversion is narrow. | `tests/test_latency_l43_subsystem_continuation_expansion.py` | diagnosis-is-not-repair clamp | Medium | defer_to_phase | L5.1 |
| `l43.screen_awareness_verify_change_continuation` | L4.3 | policy_only | Policy-known but handler missing. | `tests/test_latency_l44_async_validation.py` | handler missing reason | Medium | defer_to_phase | L5.1/L6 |
| `l42.software_execute_approved_operation_continuation` | L4.2 | policy_only | Policy-known, intentionally deferred for trust/side-effect safety. | `tests/test_latency_l44_async_validation.py` | async coverage audit | High | defer_to_phase | L6 |
| `l44.validation_and_kraken_reporting` | L4.4 | live_used | Reports derive async coverage, truth clamps, scheduler pressure, and tails from rows. | `tests/test_latency_l44_async_validation.py` | L4.4 validation block | Medium | keep | L5.1 |
| `l45.priority_scheduler_and_caps` | L4.5 | live_used | Worker loop enforces priority/lane order, protected capacity, and caps. | `tests/test_latency_l45_scheduler_hardening.py` | pressure state, cap wait, queue budget | Medium | keep | L5.1 |
| `l45.retry_yield_cancellation_cooperation` | L4.5 | partial_used | JobManager records retry/cancel/restart; tool cooperation is limited. | `tests/test_latency_l45_scheduler_hardening.py`, `tests/test_job_manager.py` | retry/cancel/restart fields | Medium | defer_to_phase | L5.1/L6 |
| `l5.streaming_tts_contracts` | L5 | live_used | Core-approved normal voice output can use the streaming service path when streaming TTS and streaming playback are enabled. | `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_latency_l51_voice_streaming_reality.py` | `voice_streaming_tts_enabled`, `voice_tts_first_chunk_ms`, `voice_streaming_transport_kind`, `voice_streaming_enabled_count`, `voice_streaming_transport_kind_counts` | Low | keep | L6 |
| `l5.true_openai_http_streaming` | L5 | live_used | OpenAI provider uses an HTTP streaming path when the normal provider path is selected; injected transport tests prove true-stream labeling, while legacy buffered helpers are labeled `buffered_chunk_projection`. | `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_latency_l51_voice_streaming_reality.py` | `voice_streaming_transport_kind`, `voice_streaming_fallback_used`, `voice_buffered_projection_count` | Low | keep | |
| `l5.local_live_playback_backend_streaming` | L5 | live_used | Windows local provider accepts progressive PCM chunks from the Core-approved streaming path and plays them through the default output device when voice/playback gates are enabled. | `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_voice_playback_provider.py`, `tests/test_latency_l55_windows_voice_runtime.py` | playback start, partial playback, `speaker_backend_available` | Low | keep | |
| `l5.normal_assistant_voice_output_streaming` | L5 | live_used | `/chat/send` assistant voice output and capture play-response select the streaming service path when streaming TTS and streaming playback are enabled. | `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_latency_l51_voice_streaming_reality.py` | `voice_stream_used_by_normal_path`, `voice_first_audio_ms`, `voice_streaming_path_used_count`, `normal_path_streaming_miss_count` | Medium | keep | L6 |
| `l5.voice_first_audio_metrics` | L5 | live_used | Prewarm and first-audio summaries surface through voice status/trace. | `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_voice_latency_instrumentation.py` | prewarm, first-audio, partial playback | Medium | keep | L6 |
| `ui.status_and_deck_surfaces` | L0-L5 | partial_used | Backend status exposes rich state; Deck/Ghost rendering proof is not broad. | `tests/test_ui_bridge.py`, `tests/test_command_surface.py`, `tests/test_voice_ui_state_payload.py` | status, metadata, command rows | Medium | defer_to_phase | L6 |
