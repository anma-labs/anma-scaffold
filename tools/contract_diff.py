#!/usr/bin/env python3
"""ANMA Contract Diff — detects contract changes and generates BUS deltas.

Workflow:
    # Before editing, snapshot the current contract:
    python3 contract_diff.py auth-service --snapshot

    # Edit modules/auth-service/CONTRACT.yaml ...

    # Diff against snapshot, generate BUS delta + CHANGELOG entry:
    python3 contract_diff.py auth-service

    # Or compare against a specific old file:
    python3 contract_diff.py auth-service --old path/to/old.yaml

    # Preview without writing files:
    python3 contract_diff.py auth-service --dry-run

Zero external dependencies.
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file, load_all_contracts
from discover import discover_modules


def _module_dir(root, module):
    try:
        module_paths = discover_modules(root)
    except ValueError:
        module_paths = {}
    return module_paths.get(module, root / 'modules' / module)


def find_project_root(start='.'):
    p = Path(start).resolve()
    if (p / 'MANIFEST.yaml').exists():
        return p
    for parent in p.parents:
        if (parent / 'MANIFEST.yaml').exists():
            return parent
    return Path(start).resolve()


def snapshot(root, module):
    """Save current CONTRACT.yaml for later diffing."""
    src = _module_dir(root, module) / 'CONTRACT.yaml'
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        sys.exit(1)

    snap_dir = root / '.anma-snapshots' / module
    snap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(snap_dir / 'CONTRACT.yaml'))
    print(f"Snapshot saved: .anma-snapshots/{module}/CONTRACT.yaml")


def diff_provides(old_provides, new_provides):
    """Compare provides sections. Returns (added, removed, modified) interfaces."""
    old_map = {}
    for iface in (old_provides or []):
        if isinstance(iface, dict) and 'id' in iface:
            old_map[iface['id']] = iface

    new_map = {}
    for iface in (new_provides or []):
        if isinstance(iface, dict) and 'id' in iface:
            new_map[iface['id']] = iface

    added = [new_map[k] for k in new_map if k not in old_map]
    removed = [old_map[k] for k in old_map if k not in new_map]

    modified = []
    for k in old_map:
        if k in new_map:
            old_i = old_map[k]
            new_i = new_map[k]
            changes = {}
            for field in ['input', 'output', 'errors', 'invariants']:
                old_val = old_i.get(field)
                new_val = new_i.get(field)
                if old_val != new_val:
                    changes[field] = {'old': old_val, 'new': new_val}
            if changes:
                modified.append({'id': k, 'changes': changes})

    return added, removed, modified


def diff_consumes(old_consumes, new_consumes):
    """Compare consumes sections. Returns (added, removed) dependencies."""
    def consumes_key(entry):
        if isinstance(entry, dict):
            return f"{entry.get('module', '?')}.{entry.get('interface', '?')}"
        return str(entry)

    old_keys = {consumes_key(e) for e in (old_consumes or []) if isinstance(e, dict)}
    new_keys = {consumes_key(e) for e in (new_consumes or []) if isinstance(e, dict)}

    new_map = {consumes_key(e): e for e in (new_consumes or []) if isinstance(e, dict)}
    old_map = {consumes_key(e): e for e in (old_consumes or []) if isinstance(e, dict)}

    added = [new_map[k] for k in new_keys - old_keys]
    removed = [old_map[k] for k in old_keys - new_keys]
    return added, removed


def format_interface_yaml(iface, indent=4):
    """Format an interface dict as YAML lines."""
    prefix = ' ' * indent
    lines = [f"{prefix}id: {iface.get('id', '?')}"]
    for field in ['input', 'output', 'errors']:
        val = iface.get(field)
        if val is not None:
            if isinstance(val, dict):
                parts = []
                for k, v in val.items():
                    if isinstance(v, str):
                        parts.append(f'{k}: {v}')
                    else:
                        parts.append(f'{k}: {v}')
                lines.append(f"{prefix}{field}: {{ {', '.join(parts)} }}")
            elif isinstance(val, list):
                items = ', '.join(str(v) for v in val)
                lines.append(f"{prefix}{field}: [{items}]")
            else:
                lines.append(f"{prefix}{field}: {val}")
    return '\n'.join(lines)


def generate_deltas(module, old_contract, new_contract, root):
    """Generate BUS delta files and CHANGELOG entries."""
    old_version = old_contract.get('version', 0)
    new_version = new_contract.get('version', old_version)

    added, removed, modified = diff_provides(
        old_contract.get('provides'), new_contract.get('provides'))

    cons_added, cons_removed = diff_consumes(
        old_contract.get('consumes'), new_contract.get('consumes'))

    if not added and not removed and not modified and not cons_added and not cons_removed:
        return None, []

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    now_file = now.replace(':', '-')

    # Determine affected consumers
    all_contracts = load_all_contracts(root)
    consumers = []
    graph_file = root / 'GRAPH.yaml'
    if graph_file.exists():
        graph = parse_yaml_file(str(graph_file))
        if graph and isinstance(graph.get('modules'), dict):
            mod_data = graph['modules'].get(module, {})
            if isinstance(mod_data, dict):
                consumers = mod_data.get('consumed_by', [])
                if not isinstance(consumers, list):
                    consumers = []

    # Determine action required
    if removed or modified:
        action = 'migrate' if consumers else 'none'
    else:
        action = 'acknowledge' if consumers else 'none'

    deltas = []
    changelog_entries = []

    for iface in added:
        delta = {
            'filename': f"{now_file}_{module}.yaml",
            'content': (
                f"source: {module}\n"
                f"contract_version: {old_version} -> {new_version}\n"
                f"timestamp: {now}\n"
                f"type: interface_added\n"
                f"\n"
                f"change:\n"
                f"  added:\n"
                f"{format_interface_yaml(iface, 4)}\n"
                f"\n"
                f"impact:\n"
                f"  consumers_affected: [{', '.join(consumers)}]\n"
                f"  action_required: {action}\n"
            ),
        }
        deltas.append(delta)
        changelog_entries.append({
            'type': 'interface_added',
            'summary': f"Added {iface.get('id', '?')} interface",
        })

    for iface in removed:
        delta = {
            'filename': f"{now_file}_{module}.yaml",
            'content': (
                f"source: {module}\n"
                f"contract_version: {old_version} -> {new_version}\n"
                f"timestamp: {now}\n"
                f"type: interface_removed\n"
                f"\n"
                f"change:\n"
                f"  removed:\n"
                f"    id: {iface.get('id', '?')}\n"
                f"\n"
                f"impact:\n"
                f"  consumers_affected: [{', '.join(consumers)}]\n"
                f"  action_required: migrate\n"
            ),
        }
        deltas.append(delta)
        changelog_entries.append({
            'type': 'interface_removed',
            'summary': f"Removed {iface.get('id', '?')} interface",
        })

    for mod_info in modified:
        changed_fields = ', '.join(mod_info['changes'].keys())
        delta = {
            'filename': f"{now_file}_{module}.yaml",
            'content': (
                f"source: {module}\n"
                f"contract_version: {old_version} -> {new_version}\n"
                f"timestamp: {now}\n"
                f"type: interface_modified\n"
                f"\n"
                f"change:\n"
                f"  modified:\n"
                f"    id: {mod_info['id']}\n"
                f"    fields: [{changed_fields}]\n"
                f"\n"
                f"impact:\n"
                f"  consumers_affected: [{', '.join(consumers)}]\n"
                f"  action_required: {action}\n"
            ),
        }
        deltas.append(delta)
        changelog_entries.append({
            'type': 'interface_modified',
            'summary': f"Modified {mod_info['id']} ({changed_fields})",
        })

    summary = {
        'added': len(added),
        'removed': len(removed),
        'modified': len(modified),
        'consumers_affected': consumers,
        'deltas': deltas,
        'changelog_entries': changelog_entries,
        'version_change': f"{old_version} -> {new_version}",
        'timestamp': now,
    }

    return summary, deltas


def write_deltas(root, module, summary, deltas, dry_run=False):
    """Write BUS delta files and update CHANGELOG."""
    if dry_run:
        print(f"\nDry run — would generate {len(deltas)} delta(s):\n")
        for d in deltas:
            print(f"--- BUS/deltas/{d['filename']} ---")
            print(d['content'])
        return

    # Write delta files
    deltas_dir = root / 'BUS' / 'deltas'
    deltas_dir.mkdir(parents=True, exist_ok=True)

    written = set()
    for d in deltas:
        fname = d['filename']
        # Avoid overwriting — append number if needed
        if fname in written:
            base = fname.rsplit('.', 1)[0]
            fname = f"{base}_{len(written)}.yaml"
        (deltas_dir / fname).write_text(d['content'])
        written.add(fname)
        print(f"  Created BUS/deltas/{fname}")

    # Update CHANGELOG
    changelog_path = _module_dir(root, module) / 'CHANGELOG.yaml'
    if changelog_path.exists():
        content = changelog_path.read_text()
        if 'changes: []' in content:
            entries_yaml = 'changes:'
        else:
            entries_yaml = None  # append to existing

        new_entries = []
        for entry in summary['changelog_entries']:
            new_entries.append(
                f"  - contract_version: {summary['version_change']}\n"
                f"    timestamp: {summary['timestamp']}\n"
                f"    type: {entry['type']}\n"
                f"    summary: \"{entry['summary']}\""
            )

        if entries_yaml == 'changes:':
            content = content.replace('changes: []',
                                      'changes:\n' + '\n'.join(new_entries))
        else:
            # Find end of changes list and append
            lines = content.split('\n')
            insert_idx = len(lines) - 1
            for i, line in enumerate(lines):
                if line.startswith('changes:'):
                    insert_idx = i
                    # Find last entry
                    for j in range(i + 1, len(lines)):
                        if lines[j].startswith('  - ') or lines[j].startswith('    '):
                            insert_idx = j
                        elif lines[j].strip() and not lines[j].startswith('#'):
                            break
            for entry_yaml in new_entries:
                lines.insert(insert_idx + 1, entry_yaml)
                insert_idx += 1
            content = '\n'.join(lines)

        changelog_path.write_text(content)
        print(f"  Updated modules/{module}/CHANGELOG.yaml")


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Contract Diff — detect changes and generate BUS deltas')
    parser.add_argument('module', help='Module name')
    parser.add_argument('--snapshot', action='store_true',
                        help='Save current CONTRACT as snapshot for later diffing')
    parser.add_argument('--old', type=str, default=None,
                        help='Path to old CONTRACT.yaml to compare against')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview deltas without writing files')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path')
    args = parser.parse_args()

    root = find_project_root(args.path)

    if args.snapshot:
        snapshot(root, args.module)
        return

    # Load current contract
    current_path = _module_dir(root, args.module) / 'CONTRACT.yaml'
    if not current_path.exists():
        print(f"ERROR: {current_path} not found", file=sys.stderr)
        sys.exit(1)
    current = parse_yaml_file(str(current_path))

    # Load old contract
    if args.old:
        old_path = Path(args.old)
        if not old_path.exists():
            print(f"ERROR: {old_path} not found", file=sys.stderr)
            sys.exit(1)
        old = parse_yaml_file(str(old_path))
    else:
        snap_path = root / '.anma-snapshots' / args.module / 'CONTRACT.yaml'
        if not snap_path.exists():
            print(f"ERROR: No snapshot found. Run with --snapshot first, or use --old.",
                  file=sys.stderr)
            sys.exit(1)
        old = parse_yaml_file(str(snap_path))

    if not old or not isinstance(old, dict):
        print("ERROR: Could not parse old contract", file=sys.stderr)
        sys.exit(1)
    if not current or not isinstance(current, dict):
        print("ERROR: Could not parse current contract", file=sys.stderr)
        sys.exit(1)

    # Diff
    summary, deltas = generate_deltas(args.module, old, current, root)

    if summary is None:
        print(f"No changes detected in {args.module} CONTRACT.")
        sys.exit(0)

    print(f"\nContract diff for '{args.module}': "
          f"{summary['added']} added, {summary['removed']} removed, "
          f"{summary['modified']} modified")
    if summary['consumers_affected']:
        print(f"  Consumers affected: {', '.join(summary['consumers_affected'])}")

    write_deltas(root, args.module, summary, deltas, dry_run=args.dry_run)

    if not args.dry_run:
        # Clean up snapshot
        snap_path = root / '.anma-snapshots' / args.module
        if snap_path.exists():
            shutil.rmtree(snap_path)
            print(f"  Cleaned up snapshot")

    print(f"\n  Done. Run 'python3 lint_contracts.py' to verify.")


if __name__ == '__main__':
    main()
