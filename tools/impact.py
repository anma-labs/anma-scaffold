#!/usr/bin/env python3
"""ANMA Impact Analysis — shows blast radius when a module's contract changes.

Usage:
    python3 impact.py auth-service              # Direct + transitive consumers
    python3 impact.py auth-service --depth 1    # Direct consumers only
    python3 impact.py auth-service --json       # Machine-readable

Zero external dependencies.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def find_project_root(start='.'):
    p = Path(start).resolve()
    if (p / 'MANIFEST.yaml').exists():
        return p
    for parent in p.parents:
        if (parent / 'MANIFEST.yaml').exists():
            return parent
    return Path(start).resolve()


def build_consumer_map(root):
    """Build {provider: [consumers]} from GRAPH.yaml."""
    graph_file = root / 'GRAPH.yaml'
    if not graph_file.exists():
        return {}
    from lint_contracts import parse_yaml_file
    graph = parse_yaml_file(str(graph_file))
    if not graph or not isinstance(graph.get('modules'), dict):
        return {}

    consumer_map = {}
    for mod_name, edges in graph['modules'].items():
        if not isinstance(edges, dict):
            continue
        consumed_by = edges.get('consumed_by', [])
        if isinstance(consumed_by, list):
            consumer_map[mod_name] = consumed_by
    return consumer_map


def find_impact(module, consumer_map, max_depth=None):
    """Find all modules affected by a change to `module`.
    Returns {depth: [modules_at_that_depth]}."""
    impact = {}
    visited = {module}
    frontier = [module]
    depth = 0

    while frontier:
        depth += 1
        if max_depth is not None and depth > max_depth:
            break

        next_frontier = []
        for mod in frontier:
            consumers = consumer_map.get(mod, [])
            for consumer in consumers:
                if consumer not in visited:
                    visited.add(consumer)
                    next_frontier.append(consumer)
                    if depth not in impact:
                        impact[depth] = []
                    impact[depth].append(consumer)
        frontier = next_frontier

    return impact


def main():
    parser = argparse.ArgumentParser(description='ANMA Impact Analysis')
    parser.add_argument('module', help='Module to analyze')
    parser.add_argument('--depth', type=int, default=None,
                        help='Max depth (default: unlimited)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path')
    args = parser.parse_args()

    root = find_project_root(args.path)
    consumer_map = build_consumer_map(root)

    if args.module not in consumer_map:
        from discover import discover_modules
        try:
            discovered = discover_modules(root)
        except ValueError:
            discovered = {}
        if args.module not in discovered:
            print(f"Module '{args.module}' not found.", file=sys.stderr)
            sys.exit(1)

    impact = find_impact(args.module, consumer_map, max_depth=args.depth)
    total = sum(len(mods) for mods in impact.values())

    if args.json:
        data = {
            'module': args.module,
            'total_affected': total,
            'by_depth': {str(d): mods for d, mods in sorted(impact.items())},
        }
        print(json.dumps(data, indent=2))
    else:
        if total == 0:
            print(f"No modules depend on '{args.module}'.")
        else:
            print(f"Impact of changing '{args.module}': {total} module(s) affected\n")
            for depth, mods in sorted(impact.items()):
                label = "direct" if depth == 1 else f"depth {depth}"
                print(f"  {label}: {', '.join(sorted(mods))}")


if __name__ == '__main__':
    main()
