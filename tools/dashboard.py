#!/usr/bin/env python3
"""ANMA Health Dashboard.

One-screen project health summary showing module statuses, open requests,
stale version pins, context budget usage, and assumption conflicts.
Everything the human overseer needs in 10 seconds.

Usage:
    python3 dashboard.py              # Print dashboard
    python3 dashboard.py --json       # Machine-readable

Zero external dependencies.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file, load_all_contracts, load_conventions
from discover import discover_modules


def build_dashboard(root):
    """Collect all health metrics."""
    contracts = load_all_contracts(root)
    try:
        module_paths = discover_modules(root)
    except ValueError:
        module_paths = {}
    conv = load_conventions(root)
    manifest = parse_yaml_file(str(root / 'MANIFEST.yaml')) or {}
    graph = parse_yaml_file(str(root / 'GRAPH.yaml')) or {}

    manifest_modules = manifest.get('modules', {})
    if not isinstance(manifest_modules, dict):
        manifest_modules = {}

    graph_modules = graph.get('modules', {})
    if not isinstance(graph_modules, dict):
        graph_modules = {}

    # --- Module health ---
    modules = []
    for mod_name, contract in sorted(contracts.items()):
        mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
        state_file = mod_dir / 'STATE.yaml'
        state = parse_yaml_file(str(state_file)) if state_file.exists() else {}
        if not isinstance(state, dict):
            state = {}

        # Context budget (content-only, excluding comments and blank lines)
        def _yaml_content_size(path):
            try:
                lines = [l for l in path.read_text().split('\n')
                         if l.strip() and not l.strip().startswith('#')]
                return sum(len(l) + 1 for l in lines)
            except OSError:
                return 0

        shared_size = sum(
            _yaml_content_size(root / f)
            for f in ['CONVENTIONS.yaml', 'MANIFEST.yaml', 'GRAPH.yaml']
            if (root / f).exists()
        )
        mod_size = sum(
            _yaml_content_size(mod_dir / f)
            for f in ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml']
            if (mod_dir / f).exists()
        )
        budget_tokens = (shared_size + mod_size) // 4

        budget_conf = conv.get('context_budget', {}) if isinstance(conv, dict) else {}
        if not isinstance(budget_conf, dict):
            budget_conf = {}
        warn_tokens = budget_conf.get('warn_tokens', 2000)

        # Memory usage
        mem_file = mod_dir / 'MEMORY.yaml'
        mem_entries = 0
        if mem_file.exists():
            mem = parse_yaml_file(str(mem_file))
            if mem and isinstance(mem.get('entries'), list):
                mem_entries = len(mem['entries'])

        # Interface count
        provides = contract.get('provides', [])
        iface_count = len(provides) if isinstance(provides, list) else 0
        iface_names = set()
        if isinstance(provides, list):
            for p in provides:
                if isinstance(p, dict) and 'id' in p:
                    iface_names.add(p['id'])

        # Test coverage
        test_file = mod_dir / 'TESTS.yaml'
        test_count = 0
        tested_ifaces = set()
        if test_file.exists():
            test_data = parse_yaml_file(str(test_file))
            if test_data and isinstance(test_data.get('tests'), list):
                for t in test_data['tests']:
                    if isinstance(t, dict):
                        test_count += 1
                        if 'interface' in t:
                            tested_ifaces.add(t['interface'])
        untested = sorted(iface_names - tested_ifaces)

        modules.append({
            'name': mod_name,
            'status': str(contract.get('status', '?')),
            'type': str(contract.get('type', 'regular')),
            'version': contract.get('version', '?'),
            'state_status': str(state.get('status', '?')),
            'current_work': str(state.get('current_work', '')),
            'blockers': state.get('blockers', []),
            'interfaces': iface_count,
            'test_count': test_count,
            'tested_interfaces': len(tested_ifaces),
            'untested_interfaces': untested,
            'budget_tokens': budget_tokens,
            'budget_pct': round(budget_tokens / warn_tokens * 100) if warn_tokens else 0,
            'memory_entries': mem_entries,
        })

    # --- Version pins ---
    stale_pins = []
    missing_pins = []
    for mod_name, contract in contracts.items():
        raw_consumes = contract.get('consumes', [])
        if not isinstance(raw_consumes, list):
            continue
        for entry in raw_consumes:
            if not isinstance(entry, dict):
                continue
            dep = str(entry.get('module', ''))
            if not dep:
                continue
            pinned = entry.get('contract_version')
            if pinned is None:
                missing_pins.append({'consumer': mod_name, 'provider': dep})
            elif dep in contracts:
                provider_v = contracts[dep].get('version')
                if provider_v is not None:
                    try:
                        if int(pinned) != int(provider_v):
                            stale_pins.append({
                                'consumer': mod_name,
                                'provider': dep,
                                'pinned': int(pinned),
                                'current': int(provider_v),
                            })
                    except (ValueError, TypeError):
                        pass

    # --- Open BUS requests ---
    open_requests = []
    now = datetime.now(timezone.utc)
    requests_dir = root / 'BUS' / 'requests'
    if requests_dir.exists():
        for req_file in sorted(requests_dir.iterdir()):
            if req_file.name.startswith('.') or not req_file.name.endswith('.yaml'):
                continue
            data = parse_yaml_file(str(req_file))
            if not data or not isinstance(data, dict):
                continue
            status = str(data.get('status', ''))
            if status in ('open', 'acknowledged'):
                age_days = None
                created = data.get('created')
                if created:
                    try:
                        clean = str(created).strip().replace('Z', '+00:00')
                        created_dt = datetime.fromisoformat(clean)
                        age_days = (now - created_dt).days
                    except (ValueError, AttributeError):
                        pass
                open_requests.append({
                    'id': str(data.get('id', req_file.name)),
                    'from': str(data.get('from', '?')),
                    'to': str(data.get('to', '?')),
                    'status': status,
                    'priority': str(data.get('priority', '?')),
                    'age_days': age_days,
                })

    # --- Assumption overlaps ---
    by_cat = {}
    for mod_name in contracts:
        af = module_paths.get(mod_name, root / 'modules' / mod_name) / 'ASSUMPTIONS.yaml'
        if not af.exists():
            continue
        data = parse_yaml_file(str(af))
        if not data or not isinstance(data.get('assumptions'), list):
            continue
        for entry in data['assumptions']:
            if isinstance(entry, dict) and entry.get('category'):
                cat = str(entry['category'])
                by_cat.setdefault(cat, set()).add(mod_name)

    overlaps = [{'category': cat, 'modules': sorted(mods)}
                for cat, mods in sorted(by_cat.items()) if len(mods) >= 2]

    # --- Aggregate stats ---
    total_interfaces = sum(m['interfaces'] for m in modules)
    total_tests = 0
    for mod_name in contracts:
        tf = module_paths.get(mod_name, root / 'modules' / mod_name) / 'TESTS.yaml'
        if tf.exists():
            td = parse_yaml_file(str(tf))
            if td and isinstance(td.get('tests'), list):
                total_tests += len(td['tests'])

    total_edges = 0
    for mod_data in graph_modules.values():
        if isinstance(mod_data, dict):
            cl = mod_data.get('consumes', [])
            if isinstance(cl, list):
                total_edges += len(cl)

    gran = conv.get('granularity', {}) if isinstance(conv, dict) else {}
    if not isinstance(gran, dict):
        gran = {}
    max_ifaces = gran.get('max_interfaces', 7)
    split_thresh = gran.get('split_threshold', 12)

    granularity_warnings = []
    for m in modules:
        if m['interfaces'] > split_thresh:
            granularity_warnings.append(f"{m['name']}: {m['interfaces']} interfaces (over {split_thresh}, consider splitting)")
        elif m['interfaces'] > max_ifaces:
            granularity_warnings.append(f"{m['name']}: {m['interfaces']} interfaces (over {max_ifaces} recommended)")

    return {
        'project': manifest.get('project', '?'),
        'module_count': len(modules),
        'modules': modules,
        'total_interfaces': total_interfaces,
        'total_tests': total_tests,
        'total_edges': total_edges,
        'granularity_warnings': granularity_warnings,
        'stale_pins': stale_pins,
        'missing_pins': missing_pins,
        'open_requests': open_requests,
        'assumption_overlaps': overlaps,
    }


def format_dashboard(data):
    """Format as a compact one-screen dashboard."""
    lines = [
        f"╔══════════════════════════════════════════════════╗",
        f"║  ANMA Health Dashboard — {data['project']}",
        f"║  {data['module_count']} module(s), {data['total_interfaces']} interfaces, "
        f"{data['total_tests']} tests, {data['total_edges']} edges",
        f"╚══════════════════════════════════════════════════╝",
        "",
    ]

    # Module table
    lines.append("  Module               Status   Ver  State   Budget   Mem  Tests    Ifaces")
    lines.append("  " + "─" * 73)
    for m in data['modules']:
        budget_bar = "OK" if m['budget_pct'] < 80 else "HIGH" if m['budget_pct'] < 100 else "OVER"
        name = m['name'][:20].ljust(20)
        # Test coverage: "6/2 ✓" = 6 tests covering 2/2 interfaces
        tested = m.get('tested_interfaces', 0)
        total_ifaces = m['interfaces']
        test_count = m.get('test_count', 0)
        if total_ifaces == 0:
            test_str = "—"
        elif tested >= total_ifaces:
            test_str = f"{test_count}/{total_ifaces} ✓"
        elif tested > 0:
            test_str = f"{test_count}/{total_ifaces} ◐"
        else:
            test_str = f"0/{total_ifaces} ✗"
        lines.append(
            f"  {name} {m['status']:8s} v{str(m['version']):3s} "
            f"{m['state_status']:7s} {m['budget_pct']:3d}% {budget_bar:4s} "
            f"{m['memory_entries']:2d}   {test_str:8s} {m['interfaces']}")

    # Untested interfaces
    untested_mods = [(m['name'], m.get('untested_interfaces', []))
                     for m in data['modules'] if m.get('untested_interfaces')]
    if untested_mods:
        lines.extend(["", "  UNTESTED INTERFACES:"])
        for mod_name, untested in untested_mods:
            lines.append(f"    {mod_name}: {', '.join(untested)}")

    # Blockers
    blocked = [m for m in data['modules'] if m.get('blockers') and isinstance(m['blockers'], list) and len(m['blockers']) > 0]
    if blocked:
        lines.extend(["", "  BLOCKERS:"])
        for m in blocked:
            for b in m['blockers']:
                lines.append(f"    {m['name']}: {b}")

    # Stale pins
    if data['stale_pins']:
        lines.extend(["", "  STALE VERSION PINS:"])
        for sp in data['stale_pins']:
            lines.append(f"    {sp['consumer']} → {sp['provider']}: pinned v{sp['pinned']}, current v{sp['current']}")

    # Missing pins
    if data['missing_pins']:
        lines.extend(["", "  MISSING VERSION PINS:"])
        for mp in data['missing_pins']:
            lines.append(f"    {mp['consumer']} → {mp['provider']}")

    # Open requests
    if data['open_requests']:
        lines.extend(["", "  OPEN REQUESTS:"])
        for r in data['open_requests']:
            age = f"{r['age_days']}d" if r['age_days'] is not None else "?"
            stale_flag = " ⚠ STALE" if r['age_days'] and r['age_days'] > 7 else ""
            lines.append(f"    {r['id']}: {r['from']} → {r['to']} [{r['status']}] "
                         f"pri={r['priority']} age={age}{stale_flag}")
    else:
        lines.extend(["", "  No open requests."])

    # Granularity warnings
    if data.get('granularity_warnings'):
        lines.extend(["", "  GRANULARITY WARNINGS:"])
        for w in data['granularity_warnings']:
            lines.append(f"    ⚠ {w}")

    # Assumption overlaps
    if data['assumption_overlaps']:
        lines.extend(["", "  ASSUMPTION OVERLAPS (review):"])
        for o in data['assumption_overlaps']:
            lines.append(f"    {o['category']}: {', '.join(o['modules'])}")

    lines.append("")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Health Dashboard')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = Path(args.path).resolve()
    data = build_dashboard(root)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(format_dashboard(data))


if __name__ == '__main__':
    main()
