#!/usr/bin/env python3
"""ANMA Full Sync.

Syncs all project files to match current contracts in one pass:
- Ensures all 6 required files exist per module
- Regenerates TESTS.yaml from contracts
- Regenerates GRAPH.yaml
- Rebuilds MANIFEST.yaml modules section
- Cleans orphaned BUS files

Usage:
    python3 tools/sync_all.py
    python3 tools/sync_all.py --path /path/to/project
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules, get_module_domain
from gen_tests import generate_tests, format_tests_yaml
from gen_graph import generate_graph, format_graph_yaml

TOOLS_DIR = Path(__file__).parent
REQUIRED_FILES = ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml',
                  'CHANGELOG.yaml', 'TESTS.yaml', 'ASSUMPTIONS.yaml']
SYNC_STATE_FILE = '.anma/sync-state.yaml'


def _sha256_file(path):
    """Return hex sha256 of a file, or empty string if it doesn't exist."""
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return ''


def _load_sync_state(root):
    """Load .anma/sync-state.yaml. Returns dict with tool_hash and contracts."""
    path = Path(root) / SYNC_STATE_FILE
    data = parse_yaml_file(str(path))
    if not data or not isinstance(data, dict):
        return {}
    return data


def _save_sync_state(root, tool_hash, contract_hashes):
    """Write .anma/sync-state.yaml."""
    root = Path(root)
    (root / '.anma').mkdir(exist_ok=True)
    lines = [
        '# Incremental sync state. Auto-managed by sync_all.py.\n',
        f'tool_hash: "{tool_hash}"\n',
    ]
    if not contract_hashes:
        lines.append('contracts: {}\n')
    else:
        lines.append('contracts:\n')
        for mod in sorted(contract_hashes):
            lines.append(f'  {mod}: "{contract_hashes[mod]}"\n')
    (root / SYNC_STATE_FILE).write_text(''.join(lines))


def timestamp_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def ensure_stub(filepath, module_name):
    """Create a missing module file using the same format as new_module.py."""
    name = filepath.name
    if name == 'STATE.yaml':
        filepath.write_text(
            f"module: {module_name}\n"
            f"status: green\n"
            f"updated: {timestamp_now()}\n"
            f"\n"
            f"current_work: \"Synced by sync_all.py\"\n"
            f"blockers: []\n"
        )
    elif name == 'MEMORY.yaml':
        filepath.write_text(
            f"module: {module_name}\n"
            f"entries: []\n"
        )
    elif name == 'CHANGELOG.yaml':
        filepath.write_text(
            f"# Structured diffs against CONTRACT.yaml.\n"
            f"module: {module_name}\n"
            f"changes: []\n"
        )
    elif name == 'TESTS.yaml':
        filepath.write_text(
            f"module: {module_name}\n"
            f"tests: []\n"
        )
    elif name == 'ASSUMPTIONS.yaml':
        filepath.write_text(
            f"# Implementation assumptions not captured in CONTRACT.\n"
            f"module: {module_name}\n"
            f"assumptions: []\n"
        )


def sync_all(root, regenerate_only=False, force=False):
    root = Path(root).resolve()
    created = []
    updated = []
    deleted = []

    try:
        module_paths = discover_modules(root)
    except ValueError as e:
        print(f"  ✗ {e}")
        return

    if not module_paths:
        print("No modules with CONTRACT.yaml found.")
        return

    module_names = sorted(module_paths.keys())

    print(f"Found {len(module_names)} module(s): {', '.join(module_names)}")
    print()

    # Parse all contracts once upfront — reused by TESTS, GRAPH, and MANIFEST
    all_contracts = {}
    for mn in module_names:
        cp = module_paths[mn] / 'CONTRACT.yaml'
        all_contracts[mn] = parse_yaml_file(str(cp)) or {}

    freshly_stubbed_tests = set()

    if not regenerate_only:
        # Step 1: Ensure all 6 required files exist
        for mod_name in module_names:
            mod_dir = module_paths[mod_name]
            for req_file in REQUIRED_FILES:
                filepath = mod_dir / req_file
                if not filepath.exists():
                    ensure_stub(filepath, mod_name)
                    created.append(f"{mod_name}/{req_file}")
                    print(f"  Created {mod_name}/{req_file}")
                    if req_file == 'TESTS.yaml':
                        freshly_stubbed_tests.add(mod_name)
            # Ensure BUS subdirectories
            for bus_sub in ['requests', 'deltas']:
                bus_dir = mod_dir / 'BUS' / bus_sub
                bus_dir.mkdir(parents=True, exist_ok=True)

        # Step 2: Regenerate TESTS.yaml for each module (hash-based incremental)
        tool_hash = _sha256_file(TOOLS_DIR / 'gen_tests.py')
        state = {} if force else _load_sync_state(root)
        stored_tool_hash = state.get('tool_hash', '')
        stored_contracts = state.get('contracts', {}) or {}
        tool_changed = (stored_tool_hash != tool_hash)
        if force:
            pass  # full regen, no message
        elif tool_changed and stored_tool_hash:
            print("  gen_tests.py changed — full regeneration")

        new_contract_hashes = {}
        for mod_name in module_names:
            mod_dir = module_paths[mod_name]
            contract_path = mod_dir / 'CONTRACT.yaml'
            contract = all_contracts[mod_name]
            provides = contract.get('provides', [])
            if not provides or not isinstance(provides, list):
                print(f"  Skipped {mod_name}/TESTS.yaml (no interfaces yet)")
                continue

            current_hash = _sha256_file(contract_path)
            new_contract_hashes[mod_name] = current_hash

            if (not force and not tool_changed
                    and stored_contracts.get(mod_name) == current_hash
                    and (mod_dir / 'TESTS.yaml').exists()
                    and mod_name not in freshly_stubbed_tests):
                print(f"  Skipped {mod_name}/TESTS.yaml (unchanged)")
                continue

            tests_path = mod_dir / 'TESTS.yaml'
            try:
                tests = generate_tests(root, mod_name,
                                       module_paths=module_paths)
                content = format_tests_yaml(mod_name, tests)
                tests_path.write_text(content)
                updated.append(f"{mod_name}/TESTS.yaml")
                print(f"  Regenerated {mod_name}/TESTS.yaml")
            except (Exception, SystemExit) as e:
                print(f"  WARNING: gen_tests failed for {mod_name}: {e}")
                new_contract_hashes.pop(mod_name, None)

        _save_sync_state(root, tool_hash, new_contract_hashes)

    # Step 3: Regenerate GRAPH.yaml
    print()
    try:
        consumes_map, consumed_by = generate_graph(root, contracts=all_contracts)
        graph_content = format_graph_yaml(consumes_map, consumed_by)
        (root / 'GRAPH.yaml').write_text(graph_content)
        updated.append('GRAPH.yaml')
        print("  Regenerated GRAPH.yaml")
    except Exception as e:
        print(f"  WARNING: gen_graph failed: {e}")

    # Step 4: Rebuild MANIFEST.yaml modules section
    manifest_path = root / 'MANIFEST.yaml'
    if manifest_path.exists():
        data = parse_yaml_file(str(manifest_path)) or {}
        project_name = data.get('project', 'my-project')
        version = data.get('version', 1)
        managers = data.get('managers', {})
        orchestrator = data.get('orchestrator', 'active')

        # Pre-build owner lookup: O(M) instead of O(N*M)
        owner_map = {}
        if isinstance(managers, dict):
            for mgr_name, mgr_data in managers.items():
                if isinstance(mgr_data, dict):
                    owns = mgr_data.get('owns', [])
                elif isinstance(mgr_data, list):
                    owns = mgr_data
                else:
                    owns = []
                for m in owns:
                    owner_map[m] = mgr_name

        # Build modules dict from cached contracts
        modules_dict = {}
        for mod_name in module_names:
            mod_dir = module_paths[mod_name]
            contract = all_contracts[mod_name]
            status = contract.get('status', 'draft')
            owner = owner_map.get(mod_name)
            entry = {'status': status}
            if owner:
                entry['owner'] = owner
            domain = get_module_domain(root, mod_dir)
            if domain:
                entry['domain'] = domain
            modules_dict[mod_name] = entry

        # Write manifest preserving structure
        lines = [
            f"project: {project_name}",
            f"version: {version}",
            f"updated: {timestamp_now()}",
            "",
            "modules:",
        ]
        for mod_name in sorted(modules_dict):
            entry = modules_dict[mod_name]
            parts = [f"status: {entry['status']}"]
            if 'owner' in entry:
                parts.append(f"owner: {entry['owner']}")
            if 'domain' in entry:
                parts.append(f"domain: {entry['domain']}")
            lines.append(f"  {mod_name}: {{ {', '.join(parts)} }}")

        lines.append("")
        lines.append("managers:")
        if isinstance(managers, dict) and managers:
            for mgr_name, mgr_data in sorted(managers.items()):
                if isinstance(mgr_data, dict):
                    owns = mgr_data.get('owns', [])
                elif isinstance(mgr_data, list):
                    owns = mgr_data
                else:
                    owns = []
                # Filter to only modules that still exist
                owns = [m for m in owns if m in modules_dict]
                lines.append(
                    f"  {mgr_name}: {{ owns: [{', '.join(owns)}] }}")
        else:
            lines.append("  {}")

        lines.append("")
        lines.append(f"orchestrator: {orchestrator}")
        lines.append("")

        manifest_path.write_text('\n'.join(lines))
        updated.append('MANIFEST.yaml')
        print("  Rebuilt MANIFEST.yaml")
    else:
        modules_dict = {}
        for mod_name in module_names:
            mod_dir = module_paths[mod_name]
            contract = all_contracts[mod_name]
            status = contract.get('status', 'draft')
            entry = {'status': status}
            domain = get_module_domain(root, mod_dir)
            if domain:
                entry['domain'] = domain
            modules_dict[mod_name] = entry

        lines = [
            "project: my-project",
            "version: 1",
            f"updated: {timestamp_now()}",
            "",
            "modules:",
        ]
        for mod_name in sorted(modules_dict):
            entry = modules_dict[mod_name]
            parts = [f"status: {entry['status']}"]
            if 'domain' in entry:
                parts.append(f"domain: {entry['domain']}")
            lines.append(f"  {mod_name}: {{ {', '.join(parts)} }}")
        lines.append("")
        lines.append("managers: {}")
        lines.append("")
        lines.append("orchestrator: active")
        lines.append("")

        manifest_path.write_text('\n'.join(lines))
        updated.append('MANIFEST.yaml')
        print(f"  Created MANIFEST.yaml ({len(modules_dict)} modules)")

    if not regenerate_only:
        # Step 5: Clean orphaned BUS files
        module_names_set = set(module_names)
        for bus_subdir in ['deltas', 'requests']:
            bus_dir = root / 'BUS' / bus_subdir
            if not bus_dir.exists():
                continue
            for f in sorted(bus_dir.iterdir()):
                if not f.name.endswith('.yaml'):
                    continue
                data = parse_yaml_file(str(f))
                if not data or not isinstance(data, dict):
                    continue
                refs = set()
                for key in ['source', 'from', 'to']:
                    val = data.get(key)
                    if val and isinstance(val, str):
                        refs.add(val)
                affected = data.get('impact', {})
                if isinstance(affected, dict):
                    for consumer in affected.get('consumers_affected', []):
                        refs.add(str(consumer))
                orphaned = refs - module_names_set
                if orphaned and not refs & module_names_set:
                    f.unlink()
                    deleted.append(f"BUS/{bus_subdir}/{f.name}")
                    print(f"  Deleted orphaned BUS/{bus_subdir}/{f.name}")

    # Report
    print()
    print(f"Sync complete: {len(created)} created, {len(updated)} updated, "
          f"{len(deleted)} deleted")


def main():
    parser = argparse.ArgumentParser(description='Sync all ANMA project files')
    parser.add_argument('--path', default='.', help='Project root path')
    parser.add_argument('--regenerate-only', action='store_true',
                        help='Only regenerate GRAPH and MANIFEST (skip stubs and TESTS)')
    parser.add_argument('--force', action='store_true',
                        help='Skip hash checks and regenerate all TESTS.yaml')
    args = parser.parse_args()
    sync_all(args.path, regenerate_only=args.regenerate_only, force=args.force)


if __name__ == '__main__':
    main()
