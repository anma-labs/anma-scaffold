import re
#!/usr/bin/env python3
"""
Phase 1 — Measurement: Compute token distributions across all generated archetypes.

Reads every CONTRACT.yaml, STATE.yaml, MEMORY.yaml across all benchmark projects,
computes token counts (chars // 4, matching the existing linter), and outputs
distribution statistics to guide threshold decisions.

Usage:
    python3 tools/benchmark/measure_tokens.py [--projects-dir benchmark_projects] [--output benchmark_results/phase1_measurements.json]
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from discover import discover_modules


def count_tokens(filepath: Path) -> int:
    """Count tokens using chars // 4 (matching check_principles.py)."""
    if not filepath.exists():
        return 0
    return len(filepath.read_text(encoding="utf-8")) // 4


def measure_module(module_dir: Path) -> dict:
    """Measure all files for a single module."""
    contract_tokens = count_tokens(module_dir / "CONTRACT.yaml")
    state_tokens = count_tokens(module_dir / "STATE.yaml")
    memory_tokens = count_tokens(module_dir / "MEMORY.yaml")
    assumptions_tokens = count_tokens(module_dir / "ASSUMPTIONS.yaml")
    recovery_tokens = contract_tokens + state_tokens + memory_tokens

    # Count interfaces and invariants
    contract_text = (module_dir / "CONTRACT.yaml").read_text(encoding="utf-8") if (module_dir / "CONTRACT.yaml").exists() else ""
    interface_count = contract_text.count("\n- id:")
    invariant_count = len(re.findall(r'- "', contract_text))
    consumes_count = contract_text.count("\n  - module:")
    error_count = len([line for line in contract_text.split("\n") if "errors:" in line and "[" in line])

    return {
        "module": module_dir.name,
        "contract_tokens": contract_tokens,
        "state_tokens": state_tokens,
        "memory_tokens": memory_tokens,
        "assumptions_tokens": assumptions_tokens,
        "recovery_tokens": recovery_tokens,
        "total_tokens": recovery_tokens + assumptions_tokens,
        "interface_count": interface_count,
        "invariant_count": invariant_count,
        "consumes_count": consumes_count,
        "tokens_per_interface": round(contract_tokens / max(interface_count, 1), 1),
    }


def measure_project(project_dir: Path) -> dict:
    """Measure all modules in a project."""
    try:
        module_paths = discover_modules(project_dir)
    except ValueError as e:
        return {"project": project_dir.name, "modules": [], "error": str(e)}

    if not module_paths:
        return {"project": project_dir.name, "modules": [], "error": "no modules found"}

    modules = [measure_module(mod_dir) for _, mod_dir in sorted(module_paths.items())]

    return {
        "project": project_dir.name,
        "module_count": len(modules),
        "modules": modules,
    }


def compute_distribution(values: list, label: str) -> dict:
    """Compute distribution statistics for a list of values."""
    if not values:
        return {"label": label, "count": 0}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    return {
        "label": label,
        "count": n,
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "mean": round(statistics.mean(sorted_vals), 1),
        "median": round(statistics.median(sorted_vals), 1),
        "stdev": round(statistics.stdev(sorted_vals), 1) if n > 1 else 0,
        "p10": sorted_vals[int(n * 0.10)],
        "p25": sorted_vals[int(n * 0.25)],
        "p50": sorted_vals[int(n * 0.50)],
        "p75": sorted_vals[int(n * 0.75)],
        "p85": sorted_vals[int(n * 0.85)],
        "p90": sorted_vals[int(n * 0.90)],
        "p95": sorted_vals[min(int(n * 0.95), n - 1)],
        "p99": sorted_vals[min(int(n * 0.99), n - 1)],
        "histogram": _histogram(sorted_vals),
    }


def _histogram(values: list, bucket_size: int = 100) -> list:
    """Create a histogram with fixed bucket size."""
    if not values:
        return []
    buckets = {}
    for v in values:
        bucket = int(v // bucket_size) * bucket_size
        label = f"{bucket}-{bucket + bucket_size - 1}"
        buckets[label] = buckets.get(label, 0) + 1

    return [{"range": k, "count": v} for k, v in sorted(buckets.items(), key=lambda x: int(x[0].split("-")[0]))]


def main():
    parser = argparse.ArgumentParser(description="Measure token distributions across ANMA archetypes")
    parser.add_argument("--projects-dir", default="benchmark_projects",
                        help="Directory containing generated archetype projects")
    parser.add_argument("--output", default="benchmark_results/phase1_measurements.json",
                        help="Output JSON file for measurements")
    args = parser.parse_args()

    projects_dir = Path(args.projects_dir)
    if not projects_dir.exists():
        print(f"Error: {projects_dir} not found. Run generate_archetypes.py first.")
        return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Measure all projects
    projects = []
    all_contract_tokens = []
    all_state_tokens = []
    all_memory_tokens = []
    all_recovery_tokens = []
    all_tokens_per_interface = []
    all_interface_counts = []

    print("Measuring token distributions...\n")

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue

        result = measure_project(project_dir)
        projects.append(result)

        for mod in result.get("modules", []):
            all_contract_tokens.append(mod["contract_tokens"])
            all_state_tokens.append(mod["state_tokens"])
            all_memory_tokens.append(mod["memory_tokens"])
            all_recovery_tokens.append(mod["recovery_tokens"])
            all_tokens_per_interface.append(mod["tokens_per_interface"])
            all_interface_counts.append(mod["interface_count"])

        # Print summary for this project
        if result.get("modules"):
            contract_range = f"{min(m['contract_tokens'] for m in result['modules'])}-{max(m['contract_tokens'] for m in result['modules'])}"
            recovery_range = f"{min(m['recovery_tokens'] for m in result['modules'])}-{max(m['recovery_tokens'] for m in result['modules'])}"
            print(f"  {result['project']:25s} | {result['module_count']:2d} modules | contract: {contract_range:12s} | recovery: {recovery_range:12s}")

    # Compute distributions
    distributions = {
        "contract_tokens": compute_distribution(all_contract_tokens, "CONTRACT.yaml tokens"),
        "state_tokens": compute_distribution(all_state_tokens, "STATE.yaml tokens"),
        "memory_tokens": compute_distribution(all_memory_tokens, "MEMORY.yaml tokens"),
        "recovery_tokens": compute_distribution(all_recovery_tokens, "Recovery payload (C+S+M) tokens"),
        "tokens_per_interface": compute_distribution(all_tokens_per_interface, "Tokens per interface"),
        "interface_count": compute_distribution(all_interface_counts, "Interfaces per module"),
    }

    # Threshold analysis
    threshold_analysis = {
        "contract_p85_natural": distributions["contract_tokens"]["p85"],
        "contract_p90_natural": distributions["contract_tokens"]["p90"],
        "contract_p95_natural": distributions["contract_tokens"]["p95"],
        "recovery_p85_natural": distributions["recovery_tokens"]["p85"],
        "recovery_p90_natural": distributions["recovery_tokens"]["p90"],
        "recovery_p95_natural": distributions["recovery_tokens"]["p95"],
        "current_limits": {
            "P2_contract_max": 600,
            "P6_recovery_max_repo": "800/1200 (conflicting)",
            "CLAUDE_md_recovery": "800/1500 (conflicting)",
        },
        "modules_exceeding_current_p2_600": sum(1 for t in all_contract_tokens if t > 600),
        "modules_exceeding_700": sum(1 for t in all_contract_tokens if t > 700),
        "modules_exceeding_800": sum(1 for t in all_contract_tokens if t > 800),
        "modules_exceeding_current_p6_1200": sum(1 for t in all_recovery_tokens if t > 1200),
        "modules_exceeding_1500": sum(1 for t in all_recovery_tokens if t > 1500),
        "pct_exceeding_p2_600": round(sum(1 for t in all_contract_tokens if t > 600) / max(len(all_contract_tokens), 1) * 100, 1),
        "pct_exceeding_p6_1200": round(sum(1 for t in all_recovery_tokens if t > 1200) / max(len(all_recovery_tokens), 1) * 100, 1),
    }

    # Compile full results
    results = {
        "summary": {
            "total_projects": len(projects),
            "total_modules": len(all_contract_tokens),
            "avg_modules_per_project": round(len(all_contract_tokens) / max(len(projects), 1), 1),
        },
        "distributions": distributions,
        "threshold_analysis": threshold_analysis,
        "projects": projects,
    }

    # Write JSON output
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults written to {output_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("DISTRIBUTION SUMMARY")
    print("=" * 70)

    for key in ["contract_tokens", "recovery_tokens"]:
        d = distributions[key]
        print(f"\n{d['label']}:")
        print(f"  Range: {d['min']} — {d['max']}")
        print(f"  Mean:  {d['mean']}  Median: {d['median']}  Stdev: {d['stdev']}")
        print(f"  p25={d['p25']}  p50={d['p50']}  p75={d['p75']}  p85={d['p85']}  p90={d['p90']}  p95={d['p95']}")

    print(f"\n{'THRESHOLD ANALYSIS':^70}")
    print("-" * 70)
    ta = threshold_analysis
    print(f"  Modules exceeding current P2 (600):  {ta['modules_exceeding_current_p2_600']}/{len(all_contract_tokens)} ({ta['pct_exceeding_p2_600']}%)")
    print(f"  Modules exceeding 700:               {ta['modules_exceeding_700']}/{len(all_contract_tokens)}")
    print(f"  Modules exceeding 800:               {ta['modules_exceeding_800']}/{len(all_contract_tokens)}")
    print(f"  Modules exceeding current P6 (1200): {ta['modules_exceeding_current_p6_1200']}/{len(all_recovery_tokens)} ({ta['pct_exceeding_p6_1200']}%)")
    print(f"  Modules exceeding 1500:              {ta['modules_exceeding_1500']}/{len(all_recovery_tokens)}")

    # Suggest thresholds based on Phase 1 only
    print(f"\n{'PHASE 1 SUGGESTED RANGES (pending Phase 2 degradation testing)':^70}")
    print("-" * 70)
    print(f"  P2 contract max:  p85={ta['contract_p85_natural']}  p90={ta['contract_p90_natural']}  p95={ta['contract_p95_natural']}")
    print(f"  P6 recovery max:  p85={ta['recovery_p85_natural']}  p90={ta['recovery_p90_natural']}  p95={ta['recovery_p95_natural']}")
    print(f"\n  → Set P2 between {ta['contract_p85_natural']} and {ta['contract_p95_natural']}")
    print(f"  → Set P6 between {ta['recovery_p85_natural']} and {ta['recovery_p95_natural']}")
    print(f"  → Final values depend on Phase 2 degradation cliff")


if __name__ == "__main__":
    main()
