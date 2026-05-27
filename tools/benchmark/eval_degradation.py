#!/usr/bin/env python3
"""
Phase 2 — Agent Degradation Testing via Claude Code CLI.

Uses `claude -p` (non-interactive print mode) to test how agent performance
degrades as recovery payload size increases. Runs on your Max plan — no API key needed.

Usage:
    python3 tools/benchmark/eval_degradation.py \
        --projects-dir benchmark_projects \
        --output benchmark_results/phase2_degradation.json \
        [--trials 3] [--test-modules 6] [--dry-run]
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from discover import discover_modules


# ── Token manipulation ───────────────────────────────────────────────────

def count_tokens(text):
    return len(text) // 4


def pad_memory_to_target(contract_yaml, state_yaml, memory_yaml, target_tokens):
    current = count_tokens(contract_yaml + state_yaml + memory_yaml)

    if current >= target_tokens:
        trimmed = memory_yaml.split("\n")[0] + "\nentries: []\n"
        current = count_tokens(contract_yaml + state_yaml + trimmed)
        if current >= target_tokens:
            return trimmed
        memory_yaml = trimmed
        current = count_tokens(contract_yaml + state_yaml + memory_yaml)

    gap_chars = (target_tokens - current) * 4

    padding_entries = [
        '  - type: decision\n    content: "Validated approach: retry with backoff on transient errors"',
        '  - type: warning\n    content: "Edge case: concurrent updates need optimistic locking on shared state"',
        '  - type: pattern\n    content: "Pagination uses cursor-based approach for stable ordering under writes"',
        '  - type: discovery\n    content: "Performance degrades above 10k records without composite indexing"',
        '  - type: decision\n    content: "Chose event-driven over polling for inter-module synchronization"',
        '  - type: warning\n    content: "Null checks required on all optional fields before property access"',
        '  - type: pattern\n    content: "Error responses include request_id for distributed tracing support"',
        '  - type: decision\n    content: "UTC timestamps everywhere, client handles timezone display conversion"',
        '  - type: discovery\n    content: "Batch operations faster than sequential above 50 items per request"',
        '  - type: warning\n    content: "Rate limiting must happen before auth to prevent user enumeration"',
        '  - type: pattern\n    content: "Idempotency keys prevent duplicate processing on network retry"',
        '  - type: decision\n    content: "Soft deletes with 30-day retention before permanent data removal"',
        '  - type: discovery\n    content: "JSON schema validation catches 90% of malformed input at boundary"',
        '  - type: warning\n    content: "Large payloads over 1MB should use chunked streaming responses"',
        '  - type: pattern\n    content: "Health check endpoint returns full dependency status map for ops"',
        '  - type: decision\n    content: "Feature flags stored in config service, not hardcoded in logic"',
        '  - type: discovery\n    content: "Connection pooling reduced p99 latency by 40% under sustained load"',
        '  - type: warning\n    content: "Cache invalidation on write path — stale reads cause data bugs"',
        '  - type: pattern\n    content: "Structured logging with correlation IDs across all service calls"',
        '  - type: decision\n    content: "Input validation at service boundary, trust data internally after"',
    ]

    if "entries: []" in memory_yaml:
        padded = memory_yaml.replace("entries: []", "entries:")
    elif "entries:" in memory_yaml:
        padded = memory_yaml.rstrip()
    else:
        padded = memory_yaml.rstrip() + "\nentries:"

    added = 0
    for entry in padding_entries:
        if added >= gap_chars:
            break
        padded += "\n" + entry
        added += len(entry) + 1

    while added < gap_chars:
        filler = f'  - type: pattern\n    content: "Observation #{random.randint(100,999)}: consistent naming across module boundaries improves agent comprehension and reduces recovery error rate significantly"'
        padded += "\n" + filler
        added += len(filler) + 1

    return padded


# ── Prompt ────────────────────────────────────────────────────────────────

EVAL_TASK = """You are an ANMA agent. Your task is to implement all interfaces defined in the CONTRACT.yaml below.

Read the recovery payload carefully, then write a Python module that implements every interface as a function.
Each function should:
- Accept the inputs defined in the contract
- Return the output structure defined in the contract
- Raise appropriate exceptions for each declared error
- Respect all invariants

Only implement interfaces from the contract. Do not add extra functions or endpoints.

Here is the recovery payload:

--- CONTRACT.yaml ---
{contract}

--- STATE.yaml ---
{state}

--- MEMORY.yaml ---
{memory}

Write the complete Python implementation. Return ONLY the code, no explanations."""


# ── Scoring (fixed: parses YAML properly, strips markdown) ───────────────

def _strip_markdown(text):
    """Remove ```python fences from Claude's response."""
    text = re.sub(r'```(?:python|py)?\n', '', text)
    text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
    return text


def _parse_contract(contract_yaml):
    """Parse interfaces, errors, invariants from YAML using yaml.safe_load."""
    try:
        contract = yaml.safe_load(contract_yaml)
    except Exception:
        return {"interface_ids": [], "all_errors": [], "invariants": []}

    interface_ids = []
    all_errors = []
    invariants = []

    for iface in (contract or {}).get("provides", []):
        if not isinstance(iface, dict):
            continue
        iid = iface.get("id", "")
        if iid:
            interface_ids.append(iid)
        for err in iface.get("errors", []):
            if err and isinstance(err, str):
                all_errors.append(err)
        for inv in iface.get("invariants", []):
            if inv and isinstance(inv, str):
                invariants.append(inv)

    return {
        "interface_ids": interface_ids,
        "all_errors": list(set(all_errors)),
        "invariants": invariants,
    }


def score_response(response_text, contract_yaml):
    """Score implementation against contract on 4 dimensions."""
    code = _strip_markdown(response_text)
    fields = _parse_contract(contract_yaml)
    interface_ids = fields["interface_ids"]
    all_errors = fields["all_errors"]
    invariants = fields["invariants"]
    code_lower = code.lower()

    # 1. Correctness: functions matching interface IDs
    found = set()
    for iface in interface_ids:
        if re.search(rf'\bdef\s+{iface}\b', code) or re.search(rf'\basync\s+def\s+{iface}\b', code):
            found.add(iface)
    correctness = len(found) / max(len(interface_ids), 1)

    # 2. Adherence: invariant concepts present in code
    skip = {"should", "always", "never", "every", "their", "these", "those",
            "which", "about", "other", "after", "before", "returns", "within",
            "callers", "depend", "module", "when", "must", "only", "that", "this",
            "from", "with", "same", "each", "than", "more", "does", "have"}
    inv_hits = 0
    for inv in invariants:
        keywords = [w.lower() for w in inv.split() if len(w) > 3 and w.lower() not in skip]
        threshold = min(2, max(1, len(keywords)))
        hits = sum(1 for kw in keywords if kw in code_lower)
        if hits >= threshold:
            inv_hits += 1
    adherence = inv_hits / max(len(invariants), 1)

    # 3. Hallucination: public functions not in contract
    all_defs = re.findall(r'def\s+(\w+)\s*\(', code)
    public = [d for d in all_defs if not d.startswith("_")]
    hallucinated = [d for d in public if d not in interface_ids]
    hallucination_score = max(0, 1.0 - len(hallucinated) / max(len(interface_ids), 1) * 0.5)

    # 4. Error handling: error codes referenced in code
    err_found = 0
    for err in all_errors:
        if not err:
            continue
        # Check exact match, or case-insensitive without underscores
        if err in code or err in response_text:
            err_found += 1
        elif err.lower().replace("_", "") in code_lower.replace("_", ""):
            err_found += 1
    error_score = err_found / max(len(all_errors), 1)

    composite = (correctness * 0.35 + adherence * 0.25 +
                 hallucination_score * 0.15 + error_score * 0.25)

    return {
        "correctness": round(correctness, 3),
        "adherence": round(adherence, 3),
        "hallucination": round(hallucination_score, 3),
        "error_handling": round(error_score, 3),
        "composite": round(composite, 3),
        "interfaces_expected": len(interface_ids),
        "interfaces_found": len(found),
        "interfaces_hallucinated": len(hallucinated),
        "errors_expected": len(all_errors),
        "errors_found": err_found,
        "invariants_total": len(invariants),
        "invariants_hit": inv_hits,
    }


# ── Claude Code CLI ──────────────────────────────────────────────────────

def run_claude_code(prompt, max_turns=1, timeout=120):
    cmd = ["claude", "-p", "--max-turns", str(max_turns), "--output-format", "text"]
    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout, cwd=os.path.expanduser("~"),
        )
        if result.returncode != 0:
            return f"ERROR: claude -p exited with code {result.returncode}\nstderr: {result.stderr[:500]}"
        return result.stdout
    except subprocess.TimeoutExpired:
        return "ERROR: claude -p timed out"
    except FileNotFoundError:
        return "ERROR: 'claude' not found. Install: npm install -g @anthropic-ai/claude-code"


def check_claude_available():
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ── Module selection ──────────────────────────────────────────────────────

def select_test_modules(projects_dir, count=6):
    candidates = []
    for pd in sorted(projects_dir.iterdir()):
        if not pd.is_dir() or pd.name.startswith("."):
            continue
        try:
            module_paths = discover_modules(pd)
        except ValueError:
            continue
        for mod_name, mod_dir in sorted(module_paths.items()):
            cp = mod_dir / "CONTRACT.yaml"
            if not cp.exists():
                continue
            text = cp.read_text()
            tokens = count_tokens(text)
            iface_count = text.count("\n- id:")
            candidates.append({
                "project": pd.name, "module": mod_name,
                "path": str(mod_dir), "contract_tokens": tokens,
                "interface_count": iface_count,
            })

    candidates.sort(key=lambda x: x["contract_tokens"])
    if len(candidates) <= count:
        return candidates

    n = len(candidates)
    indices = [0, n // 4, n // 2 - 1, n // 2, int(n * 0.75), n - 1]
    return [candidates[i] for i in indices[:count]]


# ── Eval runner ───────────────────────────────────────────────────────────

def run_eval(contract, state, memory, target_tokens, trial):
    padded = pad_memory_to_target(contract, state, memory, target_tokens)
    actual = count_tokens(contract + state + padded)
    prompt = EVAL_TASK.format(contract=contract, state=state, memory=padded)

    resp = run_claude_code(prompt)
    if resp.startswith("ERROR:"):
        return {"trial": trial, "target_tokens": target_tokens,
                "actual_tokens": actual, "error": resp, "scores": None}

    scores = score_response(resp, contract)
    return {"trial": trial, "target_tokens": target_tokens,
            "actual_tokens": actual, "scores": scores, "response_length": len(resp)}


def _degradation_summary(results, token_levels):
    by_level = {}
    for level in token_levels:
        all_s = []
        for mr in results:
            for ed in mr["evaluations"]:
                if ed["target_tokens"] == level and ed["avg_scores"]:
                    all_s.append(ed["avg_scores"])
        if all_s:
            avg = {}
            for k in all_s[0]:
                if isinstance(all_s[0][k], (int, float)):
                    avg[k] = round(sum(s[k] for s in all_s) / len(all_s), 3)
            by_level[level] = avg
        else:
            by_level[level] = None

    cliff = None
    max_drop = 0
    ls = sorted(by_level.keys())
    for i in range(1, len(ls)):
        if by_level[ls[i - 1]] and by_level[ls[i]]:
            drop = by_level[ls[i - 1]]["composite"] - by_level[ls[i]]["composite"]
            if drop > max_drop:
                max_drop = drop
                cliff = {"between": [ls[i - 1], ls[i]], "composite_drop": round(drop, 3),
                         "recommended_limit": ls[i - 1]}

    return {
        "by_token_level": [{"token_level": l, "avg_scores": by_level[l]} for l in ls],
        "degradation_cliff": cliff,
    }


def main():
    ap = argparse.ArgumentParser(description="Phase 2: Agent degradation testing via Claude Code")
    ap.add_argument("--projects-dir", default="benchmark_projects")
    ap.add_argument("--output", default="benchmark_results/phase2_degradation.json")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--token-levels", default="400,600,800,1000,1200,1500,2000")
    ap.add_argument("--test-modules", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    projects_dir = Path(args.projects_dir)
    if not projects_dir.exists():
        print(f"Error: {projects_dir} not found. Run generate_archetypes.py first.")
        sys.exit(1)

    token_levels = [int(x) for x in args.token_levels.split(",")]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    test_modules = select_test_modules(projects_dir, args.test_modules)
    total = len(test_modules) * len(token_levels) * args.trials

    print("Phase 2: Agent Degradation Testing (via Claude Code CLI)")
    print(f"  Engine:       claude -p (uses your Max plan)")
    print(f"  Test modules: {len(test_modules)}")
    print(f"  Token levels: {token_levels}")
    print(f"  Trials each:  {args.trials}")
    print(f"  Total calls:  {total}")
    print(f"  Est. time:    ~{total * 30 // 60} min\n")

    for m in test_modules:
        print(f"  {m['project']}/{m['module']} ({m['contract_tokens']} tok, {m['interface_count']} ifaces)")

    if args.dry_run:
        print("\n[DRY RUN]")
        print("  ✓ claude CLI found" if check_claude_available() else "  ✗ claude CLI not found")
        return

    if not check_claude_available():
        print("\nError: 'claude' not found. Install: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    print("\nStarting evaluation...\n")
    results = []

    for i, mod in enumerate(test_modules):
        md = Path(mod["path"])
        contract = (md / "CONTRACT.yaml").read_text()
        state = (md / "STATE.yaml").read_text()
        memory = (md / "MEMORY.yaml").read_text()

        mr = {"project": mod["project"], "module": mod["module"],
              "contract_tokens": mod["contract_tokens"],
              "interface_count": mod["interface_count"], "evaluations": []}

        for level in token_levels:
            trials = []
            for t in range(args.trials):
                n = i * len(token_levels) * args.trials + token_levels.index(level) * args.trials + t + 1
                print(f"  [{n}/{total}] {mod['module']} @ {level} tok (trial {t+1})...", end=" ", flush=True)

                r = run_eval(contract, state, memory, level, t + 1)
                trials.append(r)

                if r["scores"]:
                    print(f"composite={r['scores']['composite']:.3f}  "
                          f"correct={r['scores']['correctness']:.2f}  "
                          f"adhere={r['scores']['adherence']:.2f}  "
                          f"errors={r['scores']['error_handling']:.2f}")
                else:
                    print(f"ERROR: {r.get('error', '?')[:60]}")

                time.sleep(2)

            valid = [x["scores"] for x in trials if x["scores"]]
            avg = None
            if valid:
                avg = {}
                for k in valid[0]:
                    if isinstance(valid[0][k], (int, float)):
                        avg[k] = round(sum(s[k] for s in valid) / len(valid), 3)
                    else:
                        avg[k] = valid[0][k]

            mr["evaluations"].append({"target_tokens": level, "trials": trials,
                                       "avg_scores": avg, "trial_count": len(valid)})
        results.append(mr)

    out = {
        "config": {"engine": "claude -p (Claude Code CLI, Max plan)",
                   "trials_per_level": args.trials, "token_levels": token_levels,
                   "test_module_count": len(test_modules)},
        "results": results,
        "degradation_summary": _degradation_summary(results, token_levels),
    }

    output_path.write_text(json.dumps(out, indent=2))
    print(f"\nResults written to {output_path}")

    print(f"\n{'DEGRADATION CURVE':^70}")
    print("-" * 70)
    print(f"{'Tokens':>8} | {'Composite':>10} | {'Correct':>8} | {'Adhere':>8} | {'Errors':>8} | {'Halluc':>8}")
    print("-" * 70)
    for ld in out["degradation_summary"]["by_token_level"]:
        s = ld["avg_scores"]
        if s:
            print(f"{ld['token_level']:>8} | {s['composite']:>10.3f} | {s['correctness']:>8.3f} | "
                  f"{s['adherence']:>8.3f} | {s['error_handling']:>8.3f} | {s['hallucination']:>8.3f}")
        else:
            print(f"{ld['token_level']:>8} | {'N/A':>10} | {'N/A':>8} | {'N/A':>8} | {'N/A':>8} | {'N/A':>8}")

    cliff = out["degradation_summary"]["degradation_cliff"]
    if cliff:
        print(f"\n  ⚡ Degradation cliff: between {cliff['between'][0]} and {cliff['between'][1]} tokens")
        print(f"     Composite drop: {cliff['composite_drop']:.3f}")
        print(f"     Recommended limit: {cliff['recommended_limit']} tokens")


if __name__ == "__main__":
    main()
