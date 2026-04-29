# Latency Tracing L0/L1/L2/L3/L4/L4.1/L4.2/L4.3/L4.5/L5

Stormhelm latency tracing is the shared observability contract for core
requests, route handling, voice evaluation, and command/Kraken evaluation rows.
L0 measures where time went. L1 adds budget-aware response posture so known
slow or unavailable work can be acknowledged, blocked, or continued truthfully
without changing routing authority, trust gates, verification, provider policy,
or voice authority boundaries. L2 adds fast route triage so obvious native
request shapes can narrow planner work before heavy context is assembled. L3
adds bounded, freshness-aware context snapshots so common requests can reuse
recent backend-owned context without presenting stale evidence as live truth.
L4 adds a narrow async route-handler posture for job-backed long work: return a
truthful initial handle quickly, then keep progress visible through existing
job/task/event machinery.
L4.1 makes the existing worker layer inspectable and fairer: jobs now carry
lane/priority metadata, queue wait is separated from run time, worker
saturation is reported, and cheap deterministic work remains inline.
L4.2 adds worker-backed subsystem continuations for selected slow direct
subsystem back halves. The inline route/subsystem layer still owns planning,
trust, approvals, and initial truth; workers only run an approved continuation
request and publish progress.
L4.3 expands those continuations beyond the first workspace assembly path:
software verification, software recovery, Discord approved dispatch, and live
network diagnosis now have registry-backed handlers where their seams are
available. The handler registry also reports implemented versus missing
handlers so unsupported conversion remains visible instead of silent.
L4.5 hardens the existing in-process scheduler: queued jobs are selected by
priority and lane only when they are eligible under protected interactive
capacity and subsystem concurrency caps. Queue pressure, cap waits, retry
policy, cancellation state, and restart/interruption state are now reported.
L5 adds voice first-audio observability for the live speech path: streaming TTS
state, live playback stream state, prewarm use, fallback use, partial playback,
and Core-result-to-first-audio timing are projected into the same trace and
Kraken surfaces.

Fast route triage is advisory. It does not execute tools, approve actions,
verify results, mutate trust/session state, or replace the deterministic planner.
It marks likely lanes and skipped lanes; the existing planner, route contracts,
trust gates, adapters, and subsystems still own the final decision.

Context snapshots are also advisory unless the owning route or subsystem
accepts their freshness and confidence. A cached workspace or software catalog
may help planning; it is not verification. A clipboard hint is not screen truth.
A stale trust prompt is not approval authority.

## Where Traces Appear

`/chat/send` responses keep the existing `assistant_message.metadata.stage_timings_ms`
field for backward compatibility and also expose:

- `assistant_message.metadata.latency_trace`
- `assistant_message.metadata.latency_summary`
- `assistant_message.metadata.budget_result`
- `assistant_message.metadata.latency_policy`
- `assistant_message.metadata.execution_mode`
- `assistant_message.metadata.partial_response`
- `assistant_message.metadata.first_feedback`

Command evaluation rows include the same normalized latency fields, including
`longest_stage`, `longest_stage_ms`, `budget_label`, `budget_exceeded`,
provider/model call flags, job/event counts, async continuation, and hard-timeout
status. L1 rows also include `execution_mode`, `partial_response_returned`,
`async_expected`, `first_feedback_ms`, `budget_exceeded_continuing`, and
`fail_fast_reason`. L2 rows add `fast_path_used`, `route_triage_ms`,
`triage_confidence`, `triage_reason_codes`, `likely_route_families`,
`skipped_route_families`, `heavy_context_loaded`,
`provider_fallback_suppressed_reason`, `planner_candidates_pruned_count`,
`route_family_seams_evaluated`, and `route_family_seams_skipped`. L3 rows add
`snapshots_checked`, `snapshots_used`, `snapshots_refreshed`,
`snapshots_invalidated`, `snapshot_freshness`, `snapshot_age_ms`,
`snapshot_hot_path_hit`, `snapshot_miss_reason`,
`heavy_context_avoided_by_snapshot`, `stale_snapshot_used_cautiously`,
`invalidation_count`, and `freshness_warnings`. L4 rows add
`async_strategy`, `async_initial_response_returned`, `route_continuation_id`,
`route_progress_stage`, `route_progress_status`, `progress_event_count`,
`job_required`, `task_required`, and `event_progress_required`. L4.1 rows add
`worker_lane`, `worker_priority`, `queue_depth_at_submit`, `queue_wait_ms`,
`job_start_delay_ms`, `job_run_ms`, `job_total_ms`, `worker_index`,
`worker_capacity`, `workers_busy_at_submit`, `workers_idle_at_submit`,
`worker_saturation_percent`, `starvation_detected`,
`interactive_jobs_waiting`, `background_jobs_running`,
`background_job_count`, and `interactive_job_count`. L4.2 rows add
`subsystem_continuation_created`, `subsystem_continuation_id`,
`subsystem_continuation_kind`, `subsystem_continuation_stage`,
`subsystem_continuation_status`, `subsystem_continuation_worker_lane`,
`returned_before_subsystem_completion`, `inline_front_half_ms`,
`worker_back_half_ms`, `continuation_queue_wait_ms`, `continuation_run_ms`,
`continuation_total_ms`, `continuation_progress_event_count`,
`continuation_final_result_state`, `continuation_verification_state`,
`direct_subsystem_async_converted`, `async_conversion_expected`, and
`async_conversion_missing_reason`. L4.3 rows add
`subsystem_continuation_handler`,
`subsystem_continuation_handler_implemented`,
`subsystem_continuation_handler_missing_reason`,
`continuation_progress_stages`, `continuation_verification_required`,
`continuation_verification_attempted`,
`continuation_verification_evidence_count`,
`continuation_result_limitations`, and
`continuation_truth_clamps_applied`. L4.5 rows add
`scheduler_strategy`, `scheduler_pressure_state`,
`scheduler_pressure_reasons`, `protected_interactive_capacity`,
`background_capacity_limit`, `protected_capacity_wait_reason`,
`queue_wait_budget_ms`, `queue_wait_budget_exceeded`,
`subsystem_cap_key`, `subsystem_cap_limit`, `subsystem_cap_wait_ms`,
`retry_policy`, `retry_count`, `retry_max_attempts`, `retry_backoff_ms`,
`attempt_count`, `cancellation_state`, `yield_state`, and
`restart_recovery_state`. L5 rows add `voice_streaming_tts_enabled`,
`voice_first_audio_ms`, `voice_core_to_first_audio_ms`,
`voice_tts_first_chunk_ms`, `voice_playback_start_ms`, `voice_live_format`,
`voice_streaming_fallback_used`, `voice_prewarm_used`, and
`voice_partial_playback`.

Voice release/evaluation latency still exposes `VoiceLatencyBreakdown`, with a
compatible `latency_summary` projection for comparing voice stages against core
request traces. In L5 that projection also includes first-audio timings and
explicit `user_heard_claimed=false`.

## Stage Meaning

The trace is built from cheap existing timing marks. Important current stages
include:

- `session_create_or_load_ms`
- `history_context_ms`
- `memory_context_ms`
- `minimal_context_ms`
- `route_triage_ms`
- `snapshot_lookup_ms`
- `heavy_context_ms`
- `planner_route_ms`
- `route_handler_ms`
- `provider_call_ms`
- `provider_fallback_ms`
- `tool_planning_ms`
- `dry_run_executor_ms`
- `event_collection_ms`
- `job_collection_ms`
- `job_create_ms`
- `job_wait_ms`
- `async_initial_response_ms`
- `db_write_ms`
- `response_compose_ms`
- `response_serialization_ms`
- `payload_compaction_ms`
- `endpoint_dispatch_ms`
- `endpoint_return_to_asgi_ms`

L2/L3 also record counter/flag fields such as `heavy_context_loaded`,
`fast_path_used`, `planner_candidates_pruned_count`, `snapshot_hot_path_hit`,
and `heavy_context_avoided_by_snapshot`. These are diagnostic metadata, not
duration stages.

L4 records counter/flag fields such as `async_initial_response_returned`,
`progress_event_count`, `job_required`, `task_required`, and
`event_progress_required`. These describe continuation posture and event
visibility. They are not proof that work completed.

L4.1 records worker timing fields such as `queue_wait_ms`,
`job_start_delay_ms`, `job_run_ms`, and `job_total_ms`. Queue wait means the job
was queued but not running. Run time means a worker actually owned the job.
Total job time includes both.

L4.2 records subsystem-continuation timing fields such as
`inline_front_half_ms`, `worker_back_half_ms`,
`subsystem_continuation_queue_wait_ms`, `subsystem_continuation_run_ms`, and
`subsystem_continuation_total_ms`. Inline front-half time covers authoritative
planning and initial response setup. Worker back-half time covers the queued
continuation work. A returned initial response is not evidence that the
continuation completed or verified.

L4.3 records handler detail such as the registered handler kind, progress stage
names, whether verification was required/attempted, evidence counts,
limitations, and truth clamps. These fields are summaries and counts; they do
not include large evidence payloads or sensitive tool arguments.

L4.5 records scheduler hardening fields. Queue wait budget exceedance means a
job waited longer than its lane policy allowed; it is pressure evidence, not
command failure. Subsystem cap wait means a worker was available or soon
available, but the owning subsystem already had the allowed number of matching
continuations running. Cancel requested is not cancelled until the job state
actually reaches `cancelled`. Retry only occurs when the job carries an explicit
safe retry policy; side-effect work defaults to no automatic retry.

L5 records voice first-audio fields:

- `core_result_to_tts_start_ms`: time from Core-approved spoken text to TTS request start.
- `tts_start_to_first_chunk_ms`: time from TTS request start to the first safe audio chunk.
- `first_chunk_to_playback_start_ms`: time from first chunk receipt to live playback start.
- `core_result_to_first_audio_ms`: time from Core-approved text to playback start.
- `request_to_first_audio_ms` / `voice_first_audio_ms`: total request-to-first-audio timing when available.
- `streaming_enabled`, `live_format`, `artifact_format`, `fallback_used`, and `prewarm_used`: live-output posture.
- `partial_playback`: audio began but the stream did not complete.

Playback started or completed is playback-provider state only. It is not proof
that the user heard the audio and it is not command/task completion.

Aggregate boundary fields such as `total_latency_ms`, `http_boundary_ms`, and
`endpoint_dispatch_ms` remain visible but are not treated as the "longest stage"
because they wrap other work.

## Budgets

Budgets are diagnostic evidence. L1 uses them to choose response posture for
safe cases, but a budget exceedance is not a command failure unless a test or
route contract explicitly scores it that way.

Initial labels:

- `ghost_interactive`: first feedback 250 ms, total target 1500 ms, soft 2500 ms, hard 5000 ms
- `voice_hot_path`: visual feedback 250 ms, core result 1500 ms, first audio 3000 ms, soft 4000 ms
- `deck_work`: first feedback 500 ms, initial plan 2500 ms, soft 5000 ms
- `provider_fallback`: first feedback 750 ms, total target 3000 ms, soft 6000 ms
- `long_task`: ack 500 ms, plan 2000 ms, async expected
- `background_job`: ack 500 ms, async expected
- `test_eval`: target 2500 ms, soft 5000 ms, hard 10000 ms

Route-family policy maps calculations, browser destinations, trust approvals,
and cached/simple status to `ghost_interactive`; provider fallback to
`provider_fallback`; and execution, repair, dispatch, deep scan, or live probe
work to `deck_work` or `long_task` depending on the route shape.

## Execution Modes

L1 exposes a small typed execution mode:

- `instant`: expected to complete inside the interactive path.
- `plan_first`: return a truthful plan/preview/approval posture before any long work.
- `async_first`: acknowledge or queue work that should continue through existing job, task, or event machinery.
- `provider_wait`: provider fallback is expected and visible.
- `unsupported`: current config or route state proves the path cannot proceed.
- `clarification`: more information is needed before execution.

These modes appear in latency summaries, command-eval rows, and safe response
metadata. They describe posture, not success.

## Partial Response Law

`partial_response` is a bounded, debug-safe contract for fast truthful feedback.
It includes route family, subsystem, result state, budget label, execution mode,
async continuation, task/job identifiers when available, and explicit
`completion_claimed` and `verification_claimed` booleans.

Truth rules:

- `acknowledged`, `planning`, `queued`, and `running` do not mean completed.
- `completed_unverified` does not mean verified.
- `budget_exceeded_continuing` and `timed_out_continuing` are continuation states, not hard failures.
- `blocked` and `unsupported` mean Stormhelm has evidence the path cannot safely proceed now.
- A fast acknowledgement must never become a fake success claim.

## Async Route Progress

L4 introduces `classify_async_route_policy` and typed progress contracts for
long work:

- `AsyncRouteDecision`
- `AsyncRouteStrategy`
- `RouteProgressState`
- `AsyncRouteHandle`
- `AsyncRouteContinuation`
- `RouteContinuationSummary`

The current async strategies are `none`, `initial_response_only`,
`plan_then_return`, `create_job`, `create_task`, `create_job_and_task`,
`wait_for_fast_completion`, `fail_fast_unavailable`,
`approval_required_before_job`, and `unsupported_async`.

The first wired continuation path is job-backed async tool execution. When a
tool is already registered as async, the orchestrator can submit the job,
return a bounded queued/running handle, publish
`route.async_continuation_started`, and avoid waiting on `jobs.wait()` inside
the hot `/chat/send` response. Job progress callbacks publish bounded
`job.progress` events.

Progress stages are truth-bearing: `queued` is not `running`, `running` is not
`completed_unverified`, and `completed_unverified` is not `verified`.
`completion_claimed` and `verification_claimed` remain false until the owning
subsystem/job actually reaches that state. L4 does not create fake completion,
fake verification, or fake playback/user-heard claims.

The L4 metadata fields are:

- `async_strategy`
- `async_initial_response_returned`
- `route_continuation_id`
- `async_route_handle`
- `route_progress_state`
- `route_progress_stage`
- `route_progress_status`
- `progress_event_count`
- `job_required`
- `task_required`
- `event_progress_required`

These fields appear in response metadata, latency traces/summaries, and
Kraken rows when present. They are bounded and redacted with the same privacy
rules as the rest of the latency trace.

## Worker Lanes And Queue Intelligence

L4.1 adds typed worker metadata for the existing `JobManager` and
`ToolExecutor` path. It does not make every route async, and it does not move
authority into the scheduler.

Worker lanes:

- `interactive`: urgent user-facing work that should not wait behind polite
  background work.
- `normal`: regular job-backed work such as slow external, verification-heavy,
  or async route continuations.
- `background`: maintenance and preparation work that may yield to
  interactive requests.

Priority levels:

- `critical_interactive`
- `interactive`
- `normal`
- `background`
- `maintenance`

Jobs can also carry `route_family`, `subsystem`, `continuation_id`,
`latency_trace_id`, `interactive_deadline_ms`, `background_ok`,
`operator_visible`, `can_yield`, `starvation_sensitive`, and
`safe_for_verification`. These fields are posture and reporting metadata; they
do not bypass trust, adapter contracts, safety policy, or verification.

`JobManager.worker_status_snapshot()` exposes bounded worker status:

- `worker_capacity`
- `workers_busy`
- `workers_idle`
- `active_jobs`
- `queued_jobs`
- `queue_depth`
- `queue_depth_by_lane`
- `active_jobs_by_lane`
- `oldest_queued_job_age_ms`
- `worker_saturation_percent`
- `interactive_jobs_waiting`
- `background_jobs_running`
- `background_job_count`
- `interactive_job_count`
- `starvation_detected`
- `starvation_state`

The current starvation states are `no_starvation`, `saturated`,
`interactive_waiting`, `background_pressure`, and `queue_backlog`. L4.1 reports
these states and uses priority ordering for queued jobs, but it does not
introduce a durable cross-process scheduler.

L4.5 keeps the scheduler in-process but makes selection stricter:

- interactive and critical-interactive jobs outrank normal and background jobs.
- background jobs cannot consume the protected interactive slot when capacity
  is greater than one.
- selected subsystem stages can declare a concurrency cap, such as one approved
  Discord dispatch or one software verification continuation at a time.
- queue wait budgets are recorded by lane and surfaced as pressure metadata.
- safe read-style jobs can retry only when their retry policy explicitly allows
  it.
- queued cancellation, running cancellation, and shutdown interruption are
  separate states.

The scheduler still does not decide what the user meant, grant approval,
override adapter contracts, verify outcomes, or claim completion.

## Inline Fast-Path Law

Workers are for slow, external, verification-heavy, or background work. Cheap
deterministic truth stays inline. In particular, L4.1 keeps these off the
worker queue unless an owning future route explicitly changes the contract:

- calculations
- route triage
- simple planner classification
- scoped trust approval binding
- voice stop-speaking / playback stop dispatch
- simple clarification
- direct URL route selection
- cached status reads
- context snapshot lookup
- small response formatting

This protects Ghost Mode from paying queue overhead for work that can already
answer truthfully in the hot path.

## Background Preparation Law

`submit_background_refresh()` is the first safe hook for maintenance-style
preparation jobs. Background refreshes use the `background` lane and
`maintenance` priority, are not operator-first by default, may yield, and are
not verification authority. A failed background refresh must not break the
request path.

Future background refresh coverage can include software catalog snapshots,
provider readiness, voice/playback readiness, network/system telemetry,
workspace/task summaries, expired snapshot pruning, and route-family readiness.
Each refresh must still obey the L3 freshness policy and must not claim live
truth beyond that policy.

## Worker Progress Events

Job lifecycle and `job.progress` events now include safe worker fields when
available: lane, priority, route family, subsystem, continuation id, latency
trace id, worker index, queue wait, run time, total time, worker capacity,
queue depth, saturation, and starvation indicators.

Progress events remain bounded and redacted. API keys, authorization/token
fields, raw bytes, raw audio, generated audio bytes, and audio-like payloads are
scrubbed. `job.progress` explicitly keeps `completion_claimed` and
`verification_claimed` false.

## Subsystem Continuations

L4.2 introduces a backend-owned continuation contract:

- `SubsystemContinuationRequest`
- `SubsystemContinuationResult`
- `SubsystemContinuationPolicy`
- `SubsystemContinuationRegistry`
- `SubsystemContinuationRunner`
- `subsystem_continuation` internal async tool

The request is created by the inline route/subsystem layer after route
ownership, trust posture, and approval state are known. The worker receives a
typed continuation request; it does not reinterpret the user prompt, approve an
action, choose a route, or claim verification without evidence.

The first wired direct subsystem conversion is workspace deep assembly:
`workspace_assemble` can return a queued `subsystem_continuation` handle while
`workspace.assemble_deep` continues through JobManager. The initial response
sets `completion_claimed=false` and `verification_claimed=false`. Existing
cheap workspace operations, calculations, scoped trust approvals, voice
stop-speaking, direct URLs, simple clarification, cached reads, and small
formatting remain inline.

Continuation policy marks these slow back halves as eligible when already
approved or not approval-bearing:

- `software_control.execute_approved_operation`
- `software_control.verify_operation`
- `software_recovery.run_recovery_plan`
- `discord_relay.dispatch_approved_preview`
- `screen_awareness.verify_change`
- `screen_awareness.run_action`
- `screen_awareness.run_workflow`
- `workspace.assemble_deep`
- `workspace.restore_deep`
- `network.run_live_diagnosis`

L4.2 only wires handlers where the seam is clean. Unsupported or not-yet-wired
operation kinds stay honest through `async_conversion_missing_reason`.

L4.3 wires real handlers for:

- `software_control.verify_operation`: runs the existing software verification
  seam behind a continuation and claims `verified` only with fresh evidence.
- `software_recovery.run_recovery_plan`: runs bounded recovery work and reports
  `completed_unverified` unless verification proves the fix.
- `discord_relay.dispatch_approved_preview`: requires approval plus preview
  fingerprint binding before dispatch, and does not claim delivery without
  delivery evidence.
- `network.run_live_diagnosis`: runs bounded live diagnosis and reports
  evidence/limitations without treating diagnosis as repair.

`workspace.restore_deep` remains registered alongside
`workspace.assemble_deep`. Screen verification and broader software execution
continuations remain policy-declared until their direct seams are converted
cleanly.

## Fail Fast

L1 may fail fast only when existing config or route state proves the path is
unavailable, such as provider disabled, unsupported native route, shell command
disabled, voice/playback unavailable, or an unsafe/blocked action. The trace
uses `fail_fast_reason` for this evidence. Fail-fast is not a planner rewrite
and must not bypass trust, approval, or verification gates.

## Fast Route Triage

L2 introduces `FastRouteClassifier` near the planner/orchestrator boundary. It
performs cheap text inspection before full deterministic planning and context
assembly. It can identify obvious shapes such as:

- calculations and formula-helper requests, including engineering suffixes
- direct URLs/domains and browser destination phrases
- software lifecycle requests such as install, update, uninstall, repair, and status checks
- Discord relay previews and deictic payload references
- pending trust approvals, only when scoped active request state exists
- voice control commands such as stop speaking or mute voice
- screen-awareness inspection, change, click, and verification wording
- workspace/task continuity requests
- system, network, power, storage, and resource status wording
- open-ended provider-shaped requests when no native lane owns the text

The classifier returns a bounded `route_triage_result` with likely route
families, excluded route families, reason codes, confidence, context needs,
provider fallback eligibility, budget label, and execution mode. It does not
call providers, tools, semantic memory, screen capture, workspace scans, or
subsystems.

`safe_to_short_circuit` means the planner may prune unrelated route-family seam
evaluation. It does not mean the request is complete, approved, verified, or
safe to execute. Ambiguous, deictic, follow-up, screen-grounded, and active
request-dependent text keeps the necessary context path open.

## Lazy Context Tiers

L2 separates minimal context from heavier context:

- Tier A is always cheap: session id, surface mode, active module, raw input,
  response profile, and a lightweight active request snapshot.
- Tier B is conditional: workspace summaries, recent tool results, semantic
  memory, deictic context, screen context, and similar heavier evidence.

Obvious calculation, direct browser destination, voice-control, and software
shape requests can avoid Tier B when triage is high-confidence and the route
does not need context. Deictic relay, screen-awareness, continuity, and
ambiguous requests still load the relevant context. Skips are reported through
`heavy_context_loaded`, `heavy_context_reason`, `skipped_route_families`, and
`route_family_seams_skipped`.

## Context Snapshots

L3 introduces an in-memory `ContextSnapshotStore` owned by the core. It stores
small summaries, not raw context payloads, and each snapshot carries a family,
source, TTL, freshness state, confidence, fingerprint, limitations, and safety
flags for hot-path use, user-facing claims, deictic binding, and verification.

Snapshot families include:

- `active_request_state`
- `pending_trust`
- `active_workspace`
- `active_task`
- `recent_tool_results`
- `recent_resolutions`
- `screen_context`
- `clipboard_hint`
- `selection_hint`
- `software_catalog`
- `software_verification_cache`
- `discord_aliases`
- `discord_recent_preview`
- `voice_readiness`
- `voice_playback_readiness`
- `provider_readiness`
- `system_status`
- `network_status`
- `hardware_telemetry`
- `semantic_memory_index`
- `route_family_status`

Freshness states are:

- `fresh`: within policy TTL and not invalidated.
- `usable_stale`: expired but policy allows cautious use as last-known context.
- `stale`: reserved for downgraded context that should not support current claims.
- `expired`: outside TTL and not usable for the requested purpose.
- `invalidated`: explicitly invalidated by state change.
- `unavailable`: no usable snapshot exists.

Snapshots are redacted and bounded. They must not contain secrets, raw audio,
generated audio bytes, or large workspace/file payloads.

## Snapshot Policy

Each family has an explicit policy for TTL, stale-use allowance, invalidation
triggers, and whether it can support routing, deictic binding, user-facing
claims, or verification.

Important rules:

- `pending_trust` and `active_request_state` must be fresh and scoped.
- `active_workspace` can support cautious last-known summaries, not live claims.
- `screen_context` can support prior-observation wording when stale, not current screen truth.
- `clipboard_hint` is only a payload hint; it cannot impersonate the screen.
- `software_catalog` can help planning, not final verification.
- `software_verification_cache` cannot claim installed/running status when expired.
- `voice_readiness` can explain readiness posture, not claim capture, TTS, playback, or user hearing.

## Snapshot Integration

L3 uses L2 triage to decide which snapshots to check. Calculations and direct
browser destinations avoid workspace, semantic, and screen refreshes. Software
planning checks `software_catalog`. Discord relay can check `discord_aliases`
but still preserves deictic payload and preview fingerprint rules. Screen
requests require a fresh current observation for current-screen claims. Task
continuity can use active task/workspace snapshots with freshness labels.

Trace fields describe this behavior:

- `snapshots_checked`
- `snapshots_used`
- `snapshots_refreshed`
- `snapshots_invalidated`
- `snapshot_freshness`
- `snapshot_age_ms`
- `snapshot_hot_path_hit`
- `snapshot_miss_reason`
- `heavy_context_avoided_by_snapshot`
- `stale_snapshot_used_cautiously`
- `freshness_warnings`

## Invalidation

Current L3 invalidates or downgrades snapshots at lightweight backend seams,
including active-request updates/clears and direct workspace mutations such as
restore, assemble, save, clear, archive, rename, and tag. Other families rely on
short TTLs when clean invalidation hooks are not yet available.

Future invalidation hooks should attach to existing state changes rather than
introducing a new broad event-bus rewrite.

## Freshness Wording Law

Freshness details should appear where they matter, especially in Command Deck
debug output and Kraken reports. Ghost Mode should stay concise. Stale context
must never be worded as current truth.

Examples:

- "Using the last workspace snapshot from 8 seconds ago."
- "Using a prior screen observation; it is not current screen truth."
- "That clipboard value is only a hint, not screen truth."
- "The software catalog snapshot is usable for planning, not verification."

## Provider Fallback Protection

Native-owned shapes suppress generic provider fallback unless the native route
declines through existing policy. This prevents calculations, software control,
Discord relay, trust approvals, voice control, and browser destinations from
drifting into generic provider text. The trace field
`provider_fallback_suppressed_reason` records `native_route_triage` when L2
protected a native lane.

Provider-disabled fail-fast behavior remains owned by L1. L2 does not make
provider fallback available for native routes, and it does not provide generic
instructions when a local deterministic lane owns the request.

## Deictic And Follow-Up Caution

Triage must not pretend it resolved `this`, `that`, `it`, `same one`, `send it`,
`open that`, or `compare to before`. Those requests mark
`needs_deictic_context`, `needs_active_request_state`, `needs_recent_tool_results`,
or `needs_screen_context` as appropriate and continue through the existing
context-binding and clarification behavior. Clipboard-only evidence must remain
clipboard-only; it must not impersonate the current screen.

## Kraken Output

Kraken/command-eval summaries now include `kraken_latency_report`, which groups
latency by route family and longest stage, counts budget-exceeded rows, hard
timeouts, and provider calls, and lists the slowest rows plus planner,
route-handler, and response-serialization offenders.

L1 adds grouping by execution mode, budget exceedance by execution mode, partial
response counts, fail-fast counts/reasons, top slow instant rows, top slow
plan-first rows, top slow async-first acknowledgements, and rows that were
expected to continue asynchronously but still blocked synchronously too long.

L2 adds route-triage aggregates:

- p95/max `route_triage_ms`
- fast-path hit rate and correctness rate
- slow planner rows where triage was available
- heavy-context-loaded count by route family
- provider-fallback-suppressed and native-route-protection counts
- top rows where triage likely helped
- rows where fast triage was wrong or ambiguous

L3 adds snapshot aggregates:

- snapshot hit rate
- snapshot miss count by family
- stale cautious-use count
- heavy-context avoidance count
- p95/max latency for snapshot-hit versus snapshot-miss rows
- top slow rows with snapshot misses
- route families benefiting from cache
- invalidation event count

L4 adds async progress aggregates:

- p50/p90/p95/max by `async_strategy`
- count of async initial responses
- total progress event count
- job/task/event-progress-required counts
- compact row fields for route continuation and progress stage/status

L4.1 adds worker utilization aggregates:

- p50/p90/p95/max for `queue_wait_ms`
- p50/p90/p95/max for `job_run_ms`
- p50/p90/p95/max for `job_total_ms`
- worker lane counts
- saturation event count
- starvation warning count
- slow rows by queue wait
- slow rows by job runtime
- async strategy by worker lane grouping
- background job impact summary

L4.2 adds subsystem-continuation aggregates:

- converted subsystem route count
- conversion count by route family
- expected conversion missing count
- p95 inline front-half time
- p95 worker back-half time
- p95 continuation queue wait/run/total time
- slowest continuation rows
- missing conversion rows
- unsafe claim rows

L4.3 adds handler aggregates:

- implemented handler count
- handler count by route family
- missing handler count by reason
- conversion success count
- expected-but-missing conversion count
- unsafe claim count by handler
- p95 continuation runtime by handler
- slowest rows grouped by handler

L4.4 adds validation aggregates under `l44_async_validation`:

- async coverage audit by route and continuation handler
- missing handler reasons and expected-but-not-triggered counts
- tail-latency category counts and top slow rows by planner, route handler,
  queue wait, continuation runtime, and serialization
- truth clamp validation counts for unsafe completion, dispatch, recovery,
  diagnosis, verification, and playback-style claims
- scheduler pressure assessment with queue-wait p95, runtime p95, saturation,
  starvation, primary pressure source, and recommended L4.5 scope

L4.4 is a benchmark and cleanup pass. It may fix missing metadata propagation,
incorrect report counts, tail classification gaps, or unsafe claim detection.
It must not redesign the scheduler, convert every route into a job, suppress
verification, or treat budget exceedance as correctness failure.

L4.5 adds scheduler hardening aggregates:

- scheduler strategy counts
- scheduler pressure state counts
- queue wait budget exceeded count
- subsystem cap wait p50/p90/p95/max
- retry policy counts and retry total
- cancellation, yield, and restart recovery state counts
- compact slow-row fields for scheduler pressure, cap waits, retries, and
  interruption classification

Use these fields to decide whether further scheduler cleanup is needed before
moving to L5 voice work. Scheduler pressure is operational evidence; it is not a
route correctness failure by itself.

Use this report to pick the next optimization target. Keep routing correctness,
truthfulness, and latency as separate axes.

## Privacy

Latency payloads are bounded and scrubbed. They must not contain API keys,
authorization headers, token-like values, raw audio, generated audio bytes, or
large payload bodies.

## Deferred To L5+

L4.5 intentionally does not implement a full planner rewrite, broad subsystem
async conversion, durable cross-process scheduler redesign, speculative
execution, durable semantic memory redesign, persistent screenshot/audio cache,
streaming TTS, playback backend replacement, Realtime warmup/reuse,
provider-first fuzzy routing, trust/approval weakening, verification weakening,
frontend-owned cache truth, fake job completion, fake verification, stale
context masquerading as current truth, cloud/distributed scheduling, screen
verification conversion where the seam is still too broad, broad software
execution conversion, side-effect auto-resume without explicit policy, or
workers as command authority.
