#!/usr/bin/env python3
"""ANMA Compatibility Matrix.

Generates a cross-module compatibility report showing:
  - Dependency edges with version pin status
  - Stale version pins
  - Shared assumption categories needing review
  - Module health summary

Usage:
    python3 compat_matrix.py              # Print report to stdout
    python3 compat_matrix.py --json       # Machine-readable JSON output

Zero external dependencies.
"""

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file, load_all_contracts
from discover import discover_modules


def build_matrix(root):
    """Build the full compatibility matrix from project files."""
    try:
        module_paths = discover_modules(root)
    except ValueError:
        module_paths = {}
    contracts = load_all_contracts(root)
    manifest = parse_yaml_file(str(root / 'MANIFEST.yaml')) or {}
    manifest_modules = manifest.get('modules', {})
    if not isinstance(manifest_modules, dict):
        manifest_modules = {}

    # Build dependency edges with pin status
    edges = []
    for mod_name, contract in sorted(contracts.items()):
        raw_consumes = contract.get('consumes', [])
        if not isinstance(raw_consumes, list):
            continue
        for entry in raw_consumes:
            if not isinstance(entry, dict):
                continue
            dep = str(entry.get('module', ''))
            if not dep:
                continue
            iface = str(entry.get('interface', ''))
            pinned = entry.get('contract_version')
            provider_version = None
            if dep in contracts:
                pv = contracts[dep].get('version')
                if pv is not None:
                    try:
                        provider_version = int(pv)
                    except (ValueError, TypeError):
                        pass

            pin_status = 'missing'
            if pinned is not None:
                try:
                    pinned_int = int(pinned)
                    if provider_version is not None:
                        pin_status = 'current' if pinned_int == provider_version else 'stale'
                    else:
                        pin_status = 'unverifiable'
                except (ValueError, TypeError):
                    pin_status = 'invalid'

            edges.append({
                'consumer': mod_name,
                'provider': dep,
                'interface': iface,
                'pinned_version': pinned,
                'provider_version': provider_version,
                'pin_status': pin_status,
            })

    # Build assumption overlaps
    assumptions_by_cat = {}
    for mod_name in contracts:
        af = module_paths.get(mod_name, root / 'modules' / mod_name) / 'ASSUMPTIONS.yaml'
        if not af.exists():
            continue
        data = parse_yaml_file(str(af))
        if not data or not isinstance(data.get('assumptions'), list):
            continue
        for entry in data['assumptions']:
            if not isinstance(entry, dict):
                continue
            cat = str(entry.get('category', ''))
            if cat:
                if cat not in assumptions_by_cat:
                    assumptions_by_cat[cat] = []
                assumptions_by_cat[cat].append({
                    'module': mod_name,
                    'id': str(entry.get('id', '')),
                    'content': str(entry.get('content', '')),
                })

    overlaps = []
    for cat, entries in sorted(assumptions_by_cat.items()):
        modules = set(e['module'] for e in entries)
        if len(modules) >= 2:
            overlaps.append({
                'category': cat,
                'modules': sorted(modules),
                'entries': entries,
            })

    # Pre-compute edge counts for O(1) lookup per module
    provider_counts = collections.Counter(e['provider'] for e in edges)
    consumer_counts = collections.Counter(e['consumer'] for e in edges)

    # Module summary
    modules_summary = []
    for mod_name, contract in sorted(contracts.items()):
        mod_info = manifest_modules.get(mod_name, {})
        manifest_status = str(mod_info.get('status', '')) if isinstance(mod_info, dict) else ''
        provides = contract.get('provides', [])
        iface_count = len(provides) if isinstance(provides, list) else 0
        consumer_count = provider_counts.get(mod_name, 0)
        dependency_count = consumer_counts.get(mod_name, 0)

        modules_summary.append({
            'module': mod_name,
            'status': str(contract.get('status', '')),
            'type': str(contract.get('type', 'regular')),
            'version': contract.get('version'),
            'interfaces': iface_count,
            'consumers': consumer_count,
            'dependencies': dependency_count,
        })

    return {
        'edges': edges,
        'overlaps': overlaps,
        'modules': modules_summary,
    }


def format_report(matrix):
    """Format the matrix as a human-readable report."""
    lines = [
        "# ANMA Compatibility Matrix",
        "",
        "## Module Summary",
        "",
    ]

    for m in matrix['modules']:
        flag = ''
        if m['type'] == 'infrastructure':
            flag = ' [infrastructure]'
        lines.append(
            f"  {m['module']}: v{m['version']} ({m['status']}{flag}) "
            f"— {m['interfaces']} interfaces, "
            f"{m['consumers']} consumer(s), "
            f"{m['dependencies']} dependency(ies)")

    lines.extend(["", "## Dependency Edges", ""])

    stale = []
    unpinned = []
    if matrix['edges']:
        for e in matrix['edges']:
            pin_display = f"v{e['pinned_version']}" if e['pinned_version'] else 'UNPINNED'
            provider_display = f"v{e['provider_version']}" if e['provider_version'] else '?'
            status_icon = {'current': 'OK', 'stale': 'STALE', 'missing': 'UNPIN',
                           'invalid': 'ERR', 'unverifiable': '?'}.get(e['pin_status'], '?')
            lines.append(
                f"  {e['consumer']} → {e['provider']}.{e['interface']} "
                f"(pin: {pin_display}, provider: {provider_display}) [{status_icon}]")
            if e['pin_status'] == 'stale':
                stale.append(e)
            elif e['pin_status'] == 'missing':
                unpinned.append(e)
    else:
        lines.append("  (no dependencies)")

    if stale or unpinned:
        lines.extend(["", "## Action Required", ""])
        for e in stale:
            lines.append(
                f"  STALE: {e['consumer']} pins {e['provider']} at v{e['pinned_version']} "
                f"but provider is v{e['provider_version']}")
        for e in unpinned:
            lines.append(
                f"  UNPIN: {e['consumer']} → {e['provider']}.{e['interface']} has no version pin")

    if matrix['overlaps']:
        lines.extend(["", "## Assumption Overlaps (review for compatibility)", ""])
        for o in matrix['overlaps']:
            lines.append(f"  Category '{o['category']}': {o['modules']}")
            for entry in o['entries']:
                short = entry['content'][:60] + ('...' if len(entry['content']) > 60 else '')
                lines.append(f"    {entry['module']}:{entry['id']} — {short}")

    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Compatibility Matrix')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = Path(args.path).resolve()
    matrix = build_matrix(root)

    if args.json:
        print(json.dumps(matrix, indent=2, default=str))
    else:
        print(format_report(matrix))


if __name__ == '__main__':
    main()
