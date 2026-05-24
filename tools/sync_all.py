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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file

TOOLS_DIR = Path(__file__).parent
REQUIRED_FILES = ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml',
                  'CHANGELOG.yaml', 'TESTS.yaml', 'ASSUMPTIONS.yaml']


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


def sync_all(root):
    root = Path(root).resolve()
    modules_dir = root / 'modules'
    created = []
    updated = []
    deleted = []

    if not modules_dir.exists():
        print("No modules/ directory found.")
        return

    # Find all modules with a CONTRACT.yaml
    module_names = sorted(
        d.name for d in modules_dir.iterdir()
        if d.is_dir() and (d / 'CONTRACT.yaml').exists()
    )

    if not module_names:
        print("No modules with CONTRACT.yaml found.")
        return

    print(f"Found {len(module_names)} module(s): {', '.join(module_names)}")
    print()

    # Step 1: Ensure all 6 required files exist
    for mod_name in module_names:
        mod_dir = modules_dir / mod_name
        for req_file in REQUIRED_FILES:
            filepath = mod_dir / req_file
            if not filepath.exists():
                ensure_stub(filepath, mod_name)
                created.append(f"{mod_name}/{req_file}")
                print(f"  Created {mod_name}/{req_file}")
        # Ensure BUS subdirectories
        for bus_sub in ['requests', 'deltas']:
            bus_dir = mod_dir / 'BUS' / bus_sub
            bus_dir.mkdir(parents=True, exist_ok=True)

    # Step 2: Regenerate TESTS.yaml for each module (skip if no interfaces)
    for mod_name in module_names:
        contract = parse_yaml_file(
            str(modules_dir / mod_name / 'CONTRACT.yaml')) or {}
        provides = contract.get('provides', [])
        if not provides or not isinstance(provides, list):
            print(f"  Skipped {mod_name}/TESTS.yaml (no interfaces yet)")
            continue

        tests_path = modules_dir / mod_name / 'TESTS.yaml'
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / 'gen_tests.py'), mod_name,
             '--output', str(tests_path), '--path', str(root)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            updated.append(f"{mod_name}/TESTS.yaml")
            print(f"  Regenerated {mod_name}/TESTS.yaml")
        else:
            err = result.stderr.strip() or result.stdout.strip()
            print(f"  WARNING: gen_tests.py failed for {mod_name}: {err}")

    # Step 3: Regenerate GRAPH.yaml
    print()
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / 'gen_graph.py'), '--path', str(root)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        updated.append('GRAPH.yaml')
        print("  Regenerated GRAPH.yaml")
    else:
        err = result.stderr.strip() or result.stdout.strip()
        print(f"  WARNING: gen_graph.py failed: {err}")

    # Step 4: Rebuild MANIFEST.yaml modules section
    manifest_path = root / 'MANIFEST.yaml'
    if manifest_path.exists():
        data = parse_yaml_file(str(manifest_path)) or {}
        project_name = data.get('project', 'my-project')
        version = data.get('version', 1)
        managers = data.get('managers', {})
        orchestrator = data.get('orchestrator', 'active')

        # Build modules dict from existing contracts
        modules_dict = {}
        for mod_name in module_names:
            contract = parse_yaml_file(
                str(modules_dir / mod_name / 'CONTRACT.yaml')) or {}
            status = contract.get('status', 'draft')
            # Find owner from existing managers
            owner = None
            if isinstance(managers, dict):
                for mgr_name, mgr_data in managers.items():
                    if isinstance(mgr_data, dict):
                        owns = mgr_data.get('owns', [])
                    elif isinstance(mgr_data, list):
                        owns = mgr_data
                    else:
                        owns = []
                    if mod_name in owns:
                        owner = mgr_name
                        break
            entry = {'status': status}
            if owner:
                entry['owner'] = owner
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
            lines.append(f"  {mod_name}: {{ {', '.join(parts)} }}")

        lines.append("")
        lines.append("managers:")
        if isinstance(managers, dict) and managers:
            for mgr_name, mgr_data in sorted(managers.items()):
                if isinstance(mgr_data, dict):
                    owns = mgr_data.get('owns', [])
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

    # Step 5: Clean orphaned BUS files
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
            orphaned = refs - set(module_names)
            if orphaned and not refs & set(module_names):
                f.unlink()
                deleted.append(f"BUS/{bus_subdir}/{f.name}")
                print(f"  Deleted orphaned BUS/{bus_subdir}/{f.name}")

    # Report
    print()
    print(f"Sync complete: {len(created)} created, {len(updated)} updated, "
          f"{len(deleted)} deleted")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sync all ANMA project files')
    parser.add_argument('--path', default='.', help='Project root path')
    args = parser.parse_args()
    sync_all(args.path)
