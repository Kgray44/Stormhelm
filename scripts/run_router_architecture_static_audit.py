from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / ".artifacts" / "command-usability-eval" / "router-architecture-reset"
SOURCE_DIRS = [
    ROOT / "src" / "stormhelm" / "core" / "orchestrator",
    ROOT / "src" / "stormhelm" / "core" / "calculations",
    ROOT / "src" / "stormhelm" / "core" / "screen_awareness",
    ROOT / "src" / "stormhelm" / "core" / "software_control",
]
EXCLUDED_SOURCE_PARTS = {
    "command_eval",
    "fuzzy_eval",
}
LEGACY_ROUTING_FILES = {
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "planner.py",
}
PROMPT_SOURCE_GLOBS = [
    ".artifacts/command-usability-eval/250-checkpoint/*.jsonl",
    ".artifacts/command-usability-eval/250-remediation/*.jsonl",
    ".artifacts/command-usability-eval/generalization-overcapture-pass/*.jsonl",
    ".artifacts/command-usability-eval/generalization-overcapture-pass-2/*.jsonl",
    ".artifacts/command-usability-eval/readiness-pass-3/*.jsonl",
    ".artifacts/command-usability-eval/context-arbitration-pass/*.jsonl",
]


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    except OSError:
        return rows
    return rows


def _needle_values() -> tuple[set[str], set[str]]:
    prompts: set[str] = set()
    test_ids: set[str] = set()
    for pattern in PROMPT_SOURCE_GLOBS:
        for path in ROOT.glob(pattern):
            for row in _jsonl_rows(path):
                prompt = str(row.get("prompt") or row.get("input") or "").strip()
                test_id = str(row.get("test_id") or row.get("case_id") or "").strip()
                if len(prompt) >= 24:
                    prompts.add(prompt)
                if test_id:
                    test_ids.add(test_id)
    return prompts, test_ids


def _product_files() -> list[Path]:
    files: list[Path] = []
    for directory in SOURCE_DIRS:
        if directory.exists():
            files.extend(
                path
                for path in directory.rglob("*.py")
                if path.is_file() and not any(part in EXCLUDED_SOURCE_PARTS for part in path.parts)
            )
    return sorted(set(files))


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    prompts, test_ids = _needle_values()
    hits: list[dict[str, str]] = []
    legacy_hits: list[dict[str, str]] = []
    for path in _product_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        for prompt in prompts:
            if prompt in text:
                target = legacy_hits if path in LEGACY_ROUTING_FILES else hits
                target.append({"kind": "prompt", "needle": prompt, "path": str(path.relative_to(ROOT))})
        for test_id in test_ids:
            if test_id in text:
                target = legacy_hits if path in LEGACY_ROUTING_FILES else hits
                target.append({"kind": "test_id", "needle": test_id, "path": str(path.relative_to(ROOT))})

    summary = {
        "product_files_scanned": len(_product_files()),
        "prompt_needles": len(prompts),
        "test_id_needles": len(test_ids),
        "new_spine_hits": hits,
        "legacy_planner_hits": legacy_hits,
        "passed": not hits,
    }
    (ARTIFACT_DIR / "static_anti_overfitting_check.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Static Anti-Overfitting Check",
        "",
        f"- Product files scanned: {summary['product_files_scanned']}",
        f"- Exact prompt needles: {summary['prompt_needles']}",
        f"- Test id needles: {summary['test_id_needles']}",
        f"- Hits in new route-spine/product support files: {len(hits)}",
        f"- Legacy planner branch-chain hits recorded separately: {len(legacy_hits)}",
        f"- Result: {'PASS' if not hits else 'FAIL'}",
        "",
        "Exact prompt strings and test ids are allowed in tests, scripts, reports, and corpus artifacts. This pass treats the old planner branch chain as known legacy debt and checks that the new IntentFrame/RouteFamilySpec/RouteSpine path did not add benchmark-specific literals.",
    ]
    if hits:
        lines.append("")
        lines.append("## Hits")
        for hit in hits:
            lines.append(f"- {hit['kind']}: `{hit['needle']}` in `{hit['path']}`")
    if legacy_hits:
        lines.append("")
        lines.append("## Legacy Planner Debt")
        lines.append("These hits are in the pre-existing branch-chain planner. They are preserved as legacy fallback debt and are not evidence of new route-spine hardcoding.")
        for hit in legacy_hits[:50]:
            lines.append(f"- {hit['kind']}: `{hit['needle']}` in `{hit['path']}`")
        if len(legacy_hits) > 50:
            lines.append(f"- ... {len(legacy_hits) - 50} additional legacy hits omitted from this view.")
    (ARTIFACT_DIR / "static_anti_overfitting_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
