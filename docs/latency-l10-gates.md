# Stormhelm L10 Latency Gates

L10 adds a release-policy layer on top of existing Kraken and latency traces. It does not change planner authority, provider eligibility, trust gates, verification, Ghost layout, or subsystem hot paths.

## Local Smoke Commands

Run focused deterministic L10 unit coverage:

```powershell
python -m pytest tests/test_latency_l10_* -q
```

Generate a mock provider profile without real provider/network calls:

```powershell
python -m stormhelm.command_eval.run_latency_profile --profile provider_mock --output-dir .artifacts/latency-profiles/provider-mock --mock-provider-samples 25
```

Generate a mock voice profile:

```powershell
python -m stormhelm.command_eval.run_latency_profile --profile voice_mock --output-dir .artifacts/latency-profiles/voice-mock --mock-voice-samples 25
```

Build an L10 report from an existing command-eval JSONL:

```powershell
python -m stormhelm.command_eval.run_latency_profile --profile command_eval_profile --results-jsonl .artifacts/command-usability-eval/latest/full_results.jsonl --output-dir .artifacts/latency-profiles/latest
```

Run the existing command-eval harness; checkpoint summaries now include `latency_gate_report`, and full artifact writes include dedicated L10 JSON and Markdown gate reports:

```powershell
python scripts/run_command_usability_eval.py --focused-limit 80 --full-limit 1000 --per-test-timeout-seconds 10 --server-startup-timeout-seconds 20 --process-scope per_case
```

## Report Outputs

The L10 report writes:

- `latency_profile_report.json` for automation.
- `latency_profile_report.md` for human review.
- Command-eval artifact runs also write `focused_latency_gate_report.json`, `focused_latency_gate_report.md`, `full_latency_gate_report.json`, and `full_latency_gate_report.md`.

## Release Policy

Release-blocking failures include hard timeouts, unexpected provider calls on protected native routes, unclassified severe outliers, expired known slow-lane matches, and fake render-visible confirmations. Provider fallback remains disabled by default and provider timing is reported separately from native/local timing.

Known baseline gaps remain visible but non-blocking unless the selected profile explicitly requires that lane. Current carried-forward notes include unknown true QML render timing in non-live UI modes, mock-vs-live provider streaming separation, the unrelated `web_retrieval_fetch` command-usability coverage mismatch, and Windows pytest temp cleanup `WinError 5` after otherwise passing tests.
