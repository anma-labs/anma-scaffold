#!/usr/bin/env python3
"""ANMA Project Initializer.

Clears the example modules and resets the scaffold for a new project.
Run once when starting fresh.

Usage:
    python3 tools/init_project.py
    python3 tools/init_project.py --path /path/to/project
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules


def init_project(root):
    root = Path(root)

    # Report what we're about to remove (uses discovery across both layouts)
    try:
        discovered = discover_modules(root)
    except ValueError:
        discovered = {}
    removed = []

    # Delete all flat module directories
    modules_dir = root / 'modules'
    if modules_dir.exists():
        for entry in sorted(modules_dir.iterdir()):
            if entry.is_dir():
                shutil.rmtree(entry)
                removed.append(entry.name)

    # Delete all domain module directories (and GATEWAY.yaml files)
    domains_dir = root / 'domains'
    if domains_dir.exists():
        for domain_dir in sorted(domains_dir.iterdir()):
            if not domain_dir.is_dir() or domain_dir.name.startswith('.'):
                continue
            for entry in sorted(domain_dir.iterdir()):
                if entry.is_dir():
                    shutil.rmtree(entry)
                    removed.append(f"{domain_dir.name}/{entry.name}")
                elif entry.name == 'GATEWAY.yaml':
                    entry.unlink()

    if removed:
        print(f"Removed {len(removed)} module(s): {', '.join(removed)}")
    else:
        print("No modules to remove.")

    # Reset MANIFEST.yaml — keep project name and version, clear modules
    manifest_path = root / 'MANIFEST.yaml'
    if manifest_path.exists():
        data = parse_yaml_file(str(manifest_path))
        if data and isinstance(data, dict):
            project_name = data.get('project', 'my-project')
            version = data.get('version', 1)
        else:
            project_name = 'my-project'
            version = 1

        manifest_path.write_text(
            f"project: {project_name}\n"
            f"version: {version}\n"
            f"updated: 2026-01-01T00:00:00Z\n"
            f"\n"
            f"modules: {{}}\n"
            f"\n"
            f"managers: {{}}\n"
            f"\n"
            f"orchestrator: active\n"
        )
        print("Reset MANIFEST.yaml")

    # Reset GRAPH.yaml
    graph_path = root / 'GRAPH.yaml'
    graph_path.write_text(
        "# Auto-generated from CONTRACT consumes fields.\n"
        "# Regenerate with: python3 tools/gen_graph.py\n"
        "version: 1\n"
        "updated: 2026-01-01T00:00:00Z\n"
        "\n"
        "modules: {}\n"
    )
    print("Reset GRAPH.yaml")

    # Clear BUS files (keep directories)
    for bus_subdir in ['deltas', 'requests']:
        bus_dir = root / 'BUS' / bus_subdir
        if not bus_dir.exists():
            continue
        cleared = 0
        for f in bus_dir.iterdir():
            if f.name.endswith('.yaml') or f.name.endswith('.yml'):
                f.unlink()
                cleared += 1
        if cleared:
            print(f"Cleared {cleared} file(s) from BUS/{bus_subdir}/")
        gitkeep = bus_dir / '.gitkeep'
        if not gitkeep.exists():
            gitkeep.touch()

    print()
    print("Clean scaffold ready. Create your first module with:")
    print("  python3 tools/new_module.py <name>")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Initialize a clean ANMA project')
    parser.add_argument('--path', default='.', help='Project root path')
    args = parser.parse_args()
    init_project(args.path)
