#!/usr/bin/env python3
"""ANMA Graph Generator.

Auto-generates GRAPH.yaml from CONTRACT consumes fields.
Computes consumed_by as the inverse of consumes.
Eliminates manual graph editing errors.

Usage:
    python3 gen_graph.py              # Regenerate GRAPH.yaml
    python3 gen_graph.py --dry-run    # Preview without writing
    python3 gen_graph.py --check      # Exit 1 if GRAPH.yaml is stale

Zero external dependencies — uses the same YAML parser as lint_contracts.py.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import load_all_contracts


def generate_graph(root):
    """Build graph data from all CONTRACT consumes fields."""
    contracts = load_all_contracts(root)

    # Build consumes and consumed_by
    consumes_map = {}   # {module: [dep1, dep2]}
    consumed_by = {}    # {module: [consumer1, consumer2]}

    for mod_name in sorted(contracts.keys()):
        contract = contracts[mod_name]
        raw_consumes = contract.get('consumes', [])
        deps = []
        if isinstance(raw_consumes, list):
            for entry in raw_consumes:
                if isinstance(entry, dict) and entry.get('module'):
                    deps.append(str(entry['module']))
        consumes_map[mod_name] = list(dict.fromkeys(deps))  # deduplicate, preserve order
        if mod_name not in consumed_by:
            consumed_by[mod_name] = []

    # Compute inverse
    for mod_name, deps in consumes_map.items():
        for dep in deps:
            if dep not in consumed_by:
                consumed_by[dep] = []
            if mod_name not in consumed_by[dep]:
                consumed_by[dep].append(mod_name)

    # Sort consumed_by lists
    for key in consumed_by:
        consumed_by[key].sort()

    return consumes_map, consumed_by


def format_graph_yaml(consumes_map, consumed_by):
    """Format graph data as YAML string."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    lines = [
        "# Auto-generated from CONTRACT consumes fields.",
        "# Regenerate with: python3 gen_graph.py",
        f"version: 1",
        f"updated: {now}",
        "",
        "modules:",
    ]

    for mod_name in sorted(consumes_map.keys()):
        deps = consumes_map[mod_name]
        cb = consumed_by.get(mod_name, [])
        deps_str = '[' + ', '.join(deps) + ']' if deps else '[]'
        cb_str = '[' + ', '.join(cb) + ']' if cb else '[]'
        lines.append(f"  {mod_name}:")
        lines.append(f"    consumes: {deps_str}")
        lines.append(f"    consumed_by: {cb_str}")

    return '\n'.join(lines) + '\n'


def parse_graph_modules(graph_text):
    """Extract module data from graph YAML for comparison (ignoring timestamps)."""
    data = {}
    current_mod = None
    for line in graph_text.split('\n'):
        stripped = line.strip()
        if line.startswith('  ') and not line.startswith('    ') and ':' in stripped:
            current_mod = stripped.rstrip(':').strip()
            data[current_mod] = {}
        elif current_mod and line.startswith('    ') and ':' in stripped:
            key, val = stripped.split(':', 1)
            data[current_mod][key.strip()] = val.strip()
    return data


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Graph Generator')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview generated graph without writing')
    parser.add_argument('--check', action='store_true',
                        help='Exit 1 if GRAPH.yaml differs from contracts')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = Path(args.path).resolve()

    consumes_map, consumed_by = generate_graph(root)
    new_content = format_graph_yaml(consumes_map, consumed_by)

    if args.dry_run:
        print(new_content)
        return

    if args.check:
        graph_path = root / 'GRAPH.yaml'
        if not graph_path.exists():
            print("GRAPH.yaml does not exist — run gen_graph.py to create it")
            sys.exit(1)

        existing = graph_path.read_text()
        existing_mods = parse_graph_modules(existing)
        new_mods = parse_graph_modules(new_content)

        if existing_mods == new_mods:
            print("GRAPH.yaml is up to date")
            sys.exit(0)
        else:
            print("GRAPH.yaml is STALE — run gen_graph.py to update")
            for mod in sorted(set(list(existing_mods.keys()) + list(new_mods.keys()))):
                old = existing_mods.get(mod, {})
                new = new_mods.get(mod, {})
                if old != new:
                    print(f"  {mod}: was {old} → should be {new}")
            sys.exit(1)

    # Write
    graph_path = root / 'GRAPH.yaml'
    graph_path.write_text(new_content)
    mod_count = len(consumes_map)
    edge_count = sum(len(v) for v in consumes_map.values())
    print(f"Generated GRAPH.yaml ({mod_count} modules, {edge_count} edges)")

    # Log activity
    try:
        from session_log import log_activity
        log_activity(root, f"generated GRAPH.yaml ({mod_count} modules, {edge_count} edges)", "gen_graph.py")
    except Exception:
        pass


if __name__ == '__main__':
    main()
