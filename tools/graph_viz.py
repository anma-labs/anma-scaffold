#!/usr/bin/env python3
"""ANMA Graph Visualization.

Renders GRAPH.yaml as a Mermaid diagram for architecture review.

Usage:
    python3 graph_viz.py                # Print Mermaid to stdout
    python3 graph_viz.py --output graph.mermaid  # Write to file

Zero external dependencies — uses the same YAML parser as lint_contracts.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules


def generate_mermaid(root):
    """Generate a Mermaid flowchart from GRAPH.yaml and CONTRACT metadata."""
    graph = parse_yaml_file(str(root / 'GRAPH.yaml')) or {}
    manifest = parse_yaml_file(str(root / 'MANIFEST.yaml')) or {}
    try:
        module_paths = discover_modules(root)
    except ValueError:
        module_paths = {}

    graph_modules = graph.get('modules', {})
    if not isinstance(graph_modules, dict):
        graph_modules = {}

    manifest_modules = manifest.get('modules', {})
    if not isinstance(manifest_modules, dict):
        manifest_modules = {}

    lines = [
        "graph TD",
    ]

    # Define nodes with status styling
    for mod_name in sorted(graph_modules.keys()):
        # Get status from manifest or contract
        mod_info = manifest_modules.get(mod_name, {})
        status = 'unknown'
        if isinstance(mod_info, dict):
            status = str(mod_info.get('status', 'unknown'))

        # Get type from contract
        contract_file = module_paths.get(mod_name, root / 'modules' / mod_name) / 'CONTRACT.yaml'
        mod_type = 'regular'
        purpose = ''
        if contract_file.exists():
            contract = parse_yaml_file(str(contract_file)) or {}
            mod_type = str(contract.get('type', 'regular'))
            purpose = str(contract.get('purpose', ''))

        # Node shape based on type
        label = mod_name
        if purpose:
            short_purpose = purpose[:40] + ('...' if len(purpose) > 40 else '')
            label = f"{mod_name}\\n{short_purpose}"

        if mod_type == 'infrastructure':
            lines.append(f"    {mod_name}[[\"{label}\"]]")
        else:
            lines.append(f"    {mod_name}[\"{label}\"]")

    lines.append("")

    # Define edges from consumes
    for mod_name, mod_data in sorted(graph_modules.items()):
        if not isinstance(mod_data, dict):
            continue
        consumes = mod_data.get('consumes', [])
        if not isinstance(consumes, list):
            continue
        for dep in consumes:
            dep_str = str(dep)
            if dep_str in graph_modules:
                lines.append(f"    {mod_name} --> {dep_str}")

    lines.append("")

    # Style nodes by status
    status_styles = {
        'draft': 'fill:#fff3cd,stroke:#ffc107',
        'stable': 'fill:#d4edda,stroke:#28a745',
        'frozen': 'fill:#cce5ff,stroke:#007bff',
        'deprecated': 'fill:#f8d7da,stroke:#dc3545',
    }

    for mod_name in sorted(graph_modules.keys()):
        mod_info = manifest_modules.get(mod_name, {})
        status = 'unknown'
        if isinstance(mod_info, dict):
            status = str(mod_info.get('status', 'unknown'))
        if status in status_styles:
            lines.append(f"    style {mod_name} {status_styles[status]}")

    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Graph Visualization')
    parser.add_argument('--output', type=str, default=None,
                        help='Output file path (default: stdout)')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = Path(args.path).resolve()

    graph_file = root / 'GRAPH.yaml'
    if not graph_file.exists():
        print(f"ERROR: GRAPH.yaml not found at {graph_file}")
        sys.exit(1)

    mermaid = generate_mermaid(root)

    if args.output:
        Path(args.output).write_text(mermaid)
        print(f"Generated {args.output}")
    else:
        print(mermaid)


if __name__ == '__main__':
    main()
