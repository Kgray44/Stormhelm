# Stormhelm Deep Hardware Telemetry Design

## Goal

Add a two-layer deep hardware telemetry system to Stormhelm so it can deliver materially stronger CPU, GPU, thermal, and power intelligence than the current Windows/CIM-grade probe, while preserving Stormhelm's existing shell, orchestrator authority, and deterministic-first behavior.

The design must make Stormhelm:

- native-first for hardware telemetry
- deep enough to feel meaningfully closer to HWiNFO-class insight
- lightweight in normal operation
- explicit about capability limits and source provenance
- ready for optional HWiNFO enrichment
- ready for a future driver-backed provider seam without requiring a driver now

## Scope

This pass includes:

- a bundled-by-default local telemetry helper installed with Stormhelm
- a native-first provider stack for deeper CPU, GPU, thermal, and power telemetry
- a normalized hardware telemetry schema shared across helper, core, tools, and UI
- Stormhelm core integration that prefers helper-backed telemetry but preserves the current probe as fallback
- capability reporting for helper reachability, elevation, provider availability, and metric availability
- battery projection upgrades that prefer measured power and current when available
- an optional HWiNFO enrichment seam that can merge additional telemetry without becoming the primary authority
- failure isolation, freshness tracking, and source attribution

This pass explicitly excludes:

- Ghost redesign
- Deck redesign
- orchestrator replacement
- kernel driver implementation
- HWiNFO bundling or embedding
- broad long-term memory work
- major unrelated diagnostics overhauls beyond hardware telemetry

## Recommended Approach

### Option A: Native-first helper service with optional HWiNFO enrichment

Pros:

- preserves Stormhelm's authority and packaging posture
- isolates low-level telemetry work away from the core process
- allows native telemetry to work even when HWiNFO is absent
- keeps a clean seam for future vendor- or driver-backed providers
- avoids making Stormhelm operationally dependent on a third-party app

Cons:

- requires a new helper process and provider stack
- deeper native telemetry will still not cover every vendor-specific sensor in the first pass

### Option B: HWiNFO-first companion with Stormhelm fallback

Pros:

- fastest path to broad sensor coverage
- easiest route to very rich telemetry on machines where HWiNFO is present

Cons:

- makes Stormhelm's best experience dependent on a third-party companion
- complicates packaging, support expectations, and licensing boundaries
- weakens Stormhelm's identity as a self-contained local operator

### Option C: Direct deep telemetry inside the existing core process

Pros:

- fewer processes
- less IPC plumbing

Cons:

- worse fault isolation
- harder to reason about privilege boundaries
- more dangerous if a provider blocks, crashes, or becomes slow
- harder to evolve toward future elevated or driver-backed providers

## Decision

Choose Option A.

Stormhelm should ship with its own bundled local telemetry helper and use native telemetry as the primary hardware authority. Optional HWiNFO integration should be treated as enrichment, not as the main engine. The current Windows-grade probe remains the lowest fallback layer when deeper telemetry is unavailable.

## System Design

### Architectural Overview

The design introduces a new helper tier between the core and low-level telemetry providers:

- **Stormhelm Core**
  - remains the authority for orchestration, tools, routing, and UI-facing state
  - requests normalized hardware telemetry snapshots from the helper
  - never directly owns low-level vendor probing logic

- **Stormhelm Telemetry Helper**
  - is bundled and installed with Stormhelm by default
  - runs locally and can use elevated access when needed
  - owns provider discovery, sampling tiers, caching, normalization, capability detection, and source attribution
  - isolates provider faults from the core

- **Provider Layer**
  - collects and merges native telemetry from multiple local sources
  - later supports optional HWiNFO enrichment
  - later supports a future driver-backed provider seam without changing the core-facing contract

### Process Model

The helper should be a separate local component rather than part of the main core process.

Responsibilities of the helper:

- sample deep telemetry on a bounded cadence
- normalize readings into Stormhelm's schema
- maintain short trend windows and rolling averages
- expose a small local IPC surface for snapshot and capability requests
- stay lightweight during idle periods

Responsibilities of the core:

- ask the helper for the latest snapshot rather than polling raw providers itself
- merge helper telemetry into system state and tool responses
- degrade gracefully if the helper is unavailable

This preserves the current product model:

- Ghost stays the same
- Deck stays the same
- the orchestrator remains authoritative
- deterministic tools remain the execution path

## Telemetry Layers

### Layer 1: Current Probe Fallback

The existing probe in `C:\Stormhelm\src\stormhelm\core\system\probe.py` remains the lowest fallback layer for:

- machine identity
- coarse CPU/GPU identity
- RAM totals
- drive totals
- coarse battery state
- network state

This layer ensures Stormhelm still functions if the helper is absent, unreachable, disabled, or partially degraded.

### Layer 2: Native Helper Telemetry

The helper becomes the preferred source for deep hardware telemetry, especially:

- CPU temperatures, power, clocks, load, and thermal flags where available
- GPU temperatures, hotspot or junction metrics, clocks, power, utilization, VRAM usage, and fan speed where available
- platform and cooling telemetry such as board temperatures and fan/pump RPM where available
- deeper power telemetry including battery current, charge/discharge power, health, wear, and rolling draw estimates where available

This layer is native-first and bundled with Stormhelm by default.

### Layer 3: Optional HWiNFO Enrichment

If HWiNFO is present and configured, Stormhelm may merge additional sensor detail into the normalized schema. This layer:

- is optional
- never becomes the only source of truth
- source-tags its readings as HWiNFO-derived
- can fill gaps the native helper cannot reach cleanly

Stormhelm should never imply that HWiNFO is required for normal operation. It is an enrichment layer for users who want maximum available sensor breadth.

## Provider Strategy

The helper should use a provider stack with explicit boundaries.

### Native CPU Provider

Targets:

- package temperature
- per-core or per-cluster temperature where available
- effective clock and base clock context
- package power
- utilization
- throttle or thermal-limit flags where available

### Native GPU Provider

Targets:

- core temperature
- hotspot or memory junction where available
- clocks
- utilization
- VRAM usage
- GPU power or board power where available
- fan speed
- vendor or perf-limit flags where available

This is the highest-priority native telemetry domain in the first pass.

### Native Thermal Provider

Targets:

- motherboard or platform thermal sensors where available
- chassis, CPU, GPU, and auxiliary fan RPMs
- pump speed if exposed
- short trend windows for thermal rise, cooling, and spikes

### Native Power Provider

Targets:

- battery charge and discharge rate
- battery current and voltage where available
- AC state
- full-charge capacity
- remaining capacity
- battery wear and health
- rolling power draw windows

### Optional HWiNFO Enrichment Provider

Targets:

- missing or higher-granularity sensors unavailable through the native helper
- additional vendor-specific readings
- expanded board and cooling telemetry

This provider must preserve source attribution and never silently overwrite native data without explicit precedence rules.

### Future Driver-Backed Provider Seam

This phase does not implement a driver. It only reserves the interface boundary so a later driver-backed provider can plug into the helper without changing the core-facing telemetry schema.

## Normalized Hardware Telemetry Schema

Stormhelm needs one normalized hardware model regardless of data source.

Suggested top-level fields:

- `cpu`
- `gpu`
- `thermal`
- `power`
- `capabilities`
- `sources`
- `freshness`
- `monitoring`

### CPU

Suggested fields:

- package temperature
- per-core or grouped temperatures where available
- package power
- clocks
- effective clocks
- utilization
- throttle flags

### GPU

Suggested fields:

- core temperature
- hotspot
- memory junction
- clocks
- utilization
- power
- board power if available
- VRAM usage
- fan speed
- perf-limit or throttle flags

### Thermal

Suggested fields:

- board temperatures
- fan RPMs
- pump RPM
- sensor list with labels
- recent trend windows

### Power

Suggested fields:

- battery percent
- AC state
- battery current
- battery voltage
- charge or discharge watts
- remaining capacity
- full-charge capacity
- design capacity
- wear or health
- instant and rolling draw estimates

### Capabilities

Suggested fields:

- helper installed
- helper reachable
- elevated access active
- CPU deep telemetry available
- GPU deep telemetry available
- thermal sensor availability
- power current availability
- HWiNFO enrichment available
- HWiNFO enrichment active

### Sources

Suggested fields:

- per-domain source
- per-metric source where needed
- source confidence

### Freshness

Suggested fields:

- last sample time
- sample age
- sampling tier
- rolling-window availability

## Battery Prediction Design

The current battery prediction path in `C:\Stormhelm\src\stormhelm\core\system\probe.py` should be upgraded to prefer measured telemetry from the helper.

### Primary Estimation Path

When available, battery prediction should prefer:

- live measured charge or discharge watts
- live current
- remaining capacity
- full-charge capacity
- recent rolling average draw

Stormhelm should maintain both:

- an **instant estimate** based on current measured draw
- a **stabilized estimate** based on a short rolling average

This allows responses such as:

- current-draw estimate
- recent-average estimate
- explicit note when live current is unavailable and the estimate is based on historical or averaged power instead

### Fallback Path

If live current or live charge/discharge power is unavailable, Stormhelm should fall back to:

- the current history-based battery-report logic
- system estimates
- explicit uncertainty messaging

Stormhelm must not fabricate precision when the helper cannot expose the underlying measurements.

## Sampling Strategy

The helper should use bounded sampling tiers so it stays lightweight.

### Idle Tier

Purpose:

- keep a modestly current hardware picture
- avoid unnecessary battery, CPU, or bus overhead

Behavior:

- slow polling
- keep recent values warm

### Active Tier

Purpose:

- support Systems, diagnostics, and hardware-heavy questions while the user is engaged

Behavior:

- faster polling than idle
- maintain short trend windows

### Burst Tier

Purpose:

- diagnose spikes, throttling, unstable power draw, thermals, or power transitions

Behavior:

- temporarily higher-rate sampling
- bounded duration
- explicit freshness tags so Stormhelm can state whether it is using burst-time measurements

## Capability And Trust Model

Stormhelm should report hardware telemetry capability honestly.

Examples:

- helper installed but not reachable
- helper reachable but not elevated
- GPU deep telemetry available
- power current unavailable on this machine
- HWiNFO enrichment available but inactive

This improves trust immediately and prevents raw status parroting.

## Integration Into Current Stormhelm

### Core Integration

Primary integration seam:

- `C:\Stormhelm\src\stormhelm\core\system\probe.py`

Supporting seam:

- `C:\Stormhelm\src\stormhelm\core\container.py`

Behavior:

- keep the current coarse probe as the fallback floor
- prefer helper-backed deep telemetry when the helper is available
- add helper capability state into the system snapshot
- preserve the current response-tier contract and deterministic tools

### Tool Integration

Existing system and power tools should consume the normalized helper-backed snapshot, especially:

- resource and system status tools
- power and projection tools
- capability-reporting tools

### UI Integration

The Systems surface should become richer from the new schema without requiring shell redesign.

The UI should prioritize:

- interpreted health and limits
- meaningful sensor highlights
- thermal and power behavior
- source and freshness where needed

It should avoid:

- dumping raw sensor walls by default
- pretending every machine exposes the same depth

## Error Handling And Degradation

The system must degrade gracefully.

Rules:

- if the helper is unavailable, fall back to the current probe
- if one provider fails, the helper continues serving the rest
- if a metric is missing, report it as unavailable rather than faking a zero or placeholder value
- if HWiNFO is absent, native telemetry still works
- if the helper is present but not elevated, serve what is still available and mark the missing deep path honestly

Stormhelm should never fail the entire Systems or power experience because one telemetry provider broke.

## HWiNFO Integration Policy

Stormhelm should support HWiNFO as a companion enrichment path, not a bundled dependency.

Operational policy:

- native helper remains primary
- HWiNFO fills gaps
- source attribution is explicit
- Stormhelm still functions well without HWiNFO

Packaging policy:

- do not bundle HWiNFO inside Stormhelm without explicit vendor approval
- keep the HWiNFO provider optional and capability-aware

## Testing

This design should ship with tests covering:

- helper snapshot normalization
- provider merge precedence
- source attribution
- capability reporting
- fallback behavior when helper is unavailable
- battery projection preferring measured telemetry
- battery projection fallback behavior
- tool and system-state shaping against the new schema

Manual verification should cover:

- helper installed and reachable on a supported system
- helper unavailable fallback path
- active vs burst sampling behavior
- Systems panel becoming materially richer without shell churn

## Success Criteria

This work is successful when:

- Stormhelm delivers materially deeper CPU, GPU, thermal, and power visibility than the current probe
- battery prediction uses measured current or power where available
- Stormhelm remains lightweight in idle behavior
- helper failures do not break the product
- native telemetry remains useful even without HWiNFO
- HWiNFO can enrich Stormhelm later without becoming its authority
- the design leaves a clean seam for a future driver-backed provider without requiring a driver now

