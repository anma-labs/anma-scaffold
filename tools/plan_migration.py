#!/usr/bin/env python3
"""ANMA Contract Migration Planner.

When a module's contract changes, generates a migration plan showing
affected consumers, update order, and a step-by-step checklist.

Usage:
    python3 plan_migration.py user-store 2     # Plan migration to v2
    python3 plan_migration.py user-store 2 --json  # Machine-readable

Zero external dependencies.
"""

import argparse
import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file, load_all_contracts


def find_all_consumers(module, graph_modules, depth=0, seen=None):
    """Find all direct and transitive consumers using iterative BFS."""
    if seen is None:
        seen = set()
    seen.add(module)

    consumers = []
    queue = deque([(module, depth)])

    while queue:
        current, cur_depth = queue.popleft()

        mod_data = graph_modules.get(current, {})
        if not isinstance(mod_data, dict):
            continue

        direct = mod_data.get('consumed_by', [])
        if not isinstance(direct, list):
            continue

        for consumer in direct:
            c_str = str(consumer)
            if c_str not in seen:
                seen.add(c_str)
                consumers.append({
                    'module': c_str,
                    'depth': cur_depth + 1,
                    'via': current,
                })
                queue.append((c_str, cur_depth + 1))

    return consumers


def compute_update_order(consumers):
    """Sort consumers: deepest first (leaf consumers update before intermediaries)."""
    return sorted(consumers, key=lambda c: -c['depth'])


def build_migration_plan(root, module_name, target_version):
    """Build a complete migration plan."""
    contracts = load_all_contracts(root)
    graph = parse_yaml_file(str(root / 'GRAPH.yaml')) or {}
    graph_modules = graph.get('modules', {})
    if not isinstance(graph_modules, dict):
        graph_modules = {}

    if module_name not in contracts:
        return None, f"Module '{module_name}' not found"

    provider = contracts[module_name]
    current_version = provider.get('version', '?')

    # Find all consumers (direct + transitive)
    consumers = find_all_consumers(module_name, graph_modules)

    # Pre-build reverse index: {consumer_module: {dep_module: consumes_entry}}
    consumer_deps = {}
    for mod, c in contracts.items():
        raw = c.get('consumes', [])
        if isinstance(raw, list):
            consumer_deps[mod] = {
                str(e.get('module', '')): e
                for e in raw if isinstance(e, dict)
            }

    # Enrich with version pin data
    for consumer in consumers:
        c_contract = contracts.get(consumer['module'], {})
        consumer['status'] = str(c_contract.get('status', '?'))
        consumer['pinned_version'] = None

        entry = consumer_deps.get(consumer['module'], {}).get(module_name)
        if entry:
            consumer['pinned_version'] = entry.get('contract_version')
            consumer['interface'] = str(entry.get('interface', '?'))

    # Compute update order
    ordered = compute_update_order(consumers)

    # Single pass: classify consumers and collect frozen blockers
    frozen = []
    direct_consumers = []
    transitive_consumers = []
    for c in ordered:
        if c['status'] == 'frozen':
            frozen.append(c)
        if c['depth'] == 1:
            direct_consumers.append(c)
        elif c['depth'] > 1:
            transitive_consumers.append(c)

    plan = {
        'provider': module_name,
        'current_version': current_version,
        'target_version': target_version,
        'total_affected': len(consumers),
        'direct_consumers': direct_consumers,
        'transitive_consumers': transitive_consumers,
        'update_order': ordered,
        'frozen_blockers': frozen,
        'rollback': {
            'strategy': f"Revert {module_name} CONTRACT.yaml to v{current_version}",
            'steps': [
                f"Restore {module_name}/CONTRACT.yaml from git/backup",
                f"Publish revert delta to BUS/deltas/",
                "Run lint_contracts.py to verify consistency",
            ]
        }
    }

    return plan, None


def format_plan(plan):
    """Format migration plan as human-readable text."""
    lines = [
        f"# Migration Plan: {plan['provider']} v{plan['current_version']} → v{plan['target_version']}",
        "",
    ]

    if plan['frozen_blockers']:
        lines.append("## BLOCKERS")
        lines.append("")
        for c in plan['frozen_blockers']:
            lines.append(f"  FROZEN: {c['module']} is frozen and cannot be updated")
            lines.append(f"    This migration CANNOT proceed without unfreezing {c['module']}")
        lines.append("")

    lines.append(f"## Impact: {plan['total_affected']} consumer(s) affected")
    lines.append("")

    if plan['direct_consumers']:
        lines.append("### Direct consumers (depend on this module)")
        for c in plan['direct_consumers']:
            pin = f"pinned v{c['pinned_version']}" if c['pinned_version'] else "UNPINNED"
            lines.append(f"  {c['module']} ({c['status']}, {pin})")
        lines.append("")

    if plan['transitive_consumers']:
        lines.append("### Transitive consumers (depend via intermediary)")
        for c in plan['transitive_consumers']:
            pin = f"pinned v{c['pinned_version']}" if c['pinned_version'] else "UNPINNED"
            lines.append(f"  {c['module']} ({c['status']}, {pin}) via {c['via']}")
        lines.append("")

    lines.append("## Update Order (leaf consumers first)")
    lines.append("")
    for i, c in enumerate(plan['update_order'], 1):
        pin = f"v{c['pinned_version']}" if c['pinned_version'] else "no pin"
        lines.append(f"  {i}. {c['module']} ({pin})")
    lines.append("")

    lines.append("## Checklist")
    lines.append("")
    lines.append(f"  [ ] 1. Update {plan['provider']}/CONTRACT.yaml to v{plan['target_version']}")
    lines.append(f"  [ ] 2. Publish delta to BUS/deltas/")
    lines.append(f"  [ ] 3. Run lint_contracts.py — expect version pin warnings")

    for i, c in enumerate(plan['update_order'], 4):
        lines.append(f"  [ ] {i}. Update {c['module']} consumes: contract_version → {plan['target_version']}")

    next_step = len(plan['update_order']) + 4
    lines.append(f"  [ ] {next_step}. Run lint_contracts.py --strict — must pass clean")
    lines.append(f"  [ ] {next_step + 1}. Run gen_graph.py to regenerate dependency graph")
    lines.append("")

    lines.append("## Rollback Plan")
    lines.append("")
    lines.append(f"  Strategy: {plan['rollback']['strategy']}")
    for step in plan['rollback']['steps']:
        lines.append(f"  - {step}")

    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Contract Migration Planner')
    parser.add_argument('module', help='Module being changed')
    parser.add_argument('target_version', type=int,
                        help='Target contract version')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = Path(args.path).resolve()

    plan, error = build_migration_plan(root, args.module, args.target_version)
    if error:
        print(f"ERROR: {error}")
        sys.exit(1)

    if args.json:
        print(json.dumps(plan, indent=2, default=str))
    else:
        print(format_plan(plan))


if __name__ == '__main__':
    main()
