#!/usr/bin/env python3
"""ANMA Product Spec Generator.

Converts CONTRACT.yaml files into plain-English user stories and feature
descriptions. Helps non-engineers validate contracts without reading YAML.

Usage:
    python3 gen_product_spec.py                     # All modules
    python3 gen_product_spec.py --module auth        # Single module
    python3 gen_product_spec.py --output spec.md     # Save to file

Zero external dependencies.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def interface_to_story(mod_name, iface):
    """Convert a single interface to a user story."""
    iface_id = iface.get('id', 'unknown')
    errors = iface.get('errors', [])
    invariants = iface.get('invariants', [])

    # Parse input/output
    raw_input = iface.get('input', {})
    raw_output = iface.get('output', {})
    input_fields = list(raw_input.keys()) if isinstance(raw_input, dict) else []
    output_fields = list(raw_output.keys()) if isinstance(raw_output, dict) else []

    # Build the story
    action = iface_id.replace('_', ' ')
    story = f"**{action}**"

    if input_fields:
        story += f" (takes: {', '.join(input_fields)})"
    if output_fields:
        story += f" → returns {', '.join(output_fields)}"

    parts = [story]

    if invariants and isinstance(invariants, list):
        for inv in invariants:
            if isinstance(inv, str):
                parts.append(f"  - {inv}")

    if errors and isinstance(errors, list):
        error_list = ', '.join(str(e) for e in errors)
        parts.append(f"  - Can fail with: {error_list}")

    return '\n'.join(parts)


def contract_to_spec(mod_name, contract):
    """Convert a full contract to a product spec."""
    purpose = contract.get('purpose', 'No purpose defined')
    provides = contract.get('provides', [])
    consumes = contract.get('consumes', [])
    status = contract.get('status', 'unknown')

    lines = [
        f"## {mod_name}",
        f"*{purpose}* (status: {status})",
        "",
    ]

    if isinstance(provides, list) and provides:
        lines.append("### What it does:")
        for iface in provides:
            if isinstance(iface, dict):
                lines.append(interface_to_story(mod_name, iface))
                lines.append("")

    if isinstance(consumes, list) and consumes:
        deps = []
        for dep in consumes:
            if isinstance(dep, dict) and dep.get('module'):
                deps.append(f"{dep['module']}.{dep.get('interface', '?')}")
        if deps:
            lines.append(f"### Depends on: {', '.join(deps)}")
            lines.append("")

    return '\n'.join(lines)


def generate_full_spec(root, module_filter=None):
    """Generate the complete product spec."""
    from lint_contracts import parse_yaml_file, load_all_contracts
    contracts = load_all_contracts(root)
    manifest = parse_yaml_file(str(root / 'MANIFEST.yaml')) or {}
    project = manifest.get('project', 'Unknown Project')

    lines = [
        f"# {project} — Product Spec",
        f"*Auto-generated from ANMA contracts. {len(contracts)} modules.*",
        "",
    ]

    # Build per-module specs and count interfaces in a single pass
    total_interfaces = 0
    module_lines = []
    for mod_name in sorted(contracts.keys()):
        contract = contracts[mod_name]
        provides = contract.get('provides', [])
        if isinstance(provides, list):
            total_interfaces += len(provides)
        if module_filter and mod_name not in module_filter:
            continue
        module_lines.append(contract_to_spec(mod_name, contract))
        module_lines.append("---")
        module_lines.append("")

    lines.extend([
        f"**Modules:** {len(contracts)}",
        f"**Total features:** {total_interfaces}",
        "",
        "---",
        "",
    ])

    lines.extend(module_lines)

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Product Spec Generator')
    parser.add_argument('--module', action='append', default=None,
                        help='Filter to specific module(s)')
    parser.add_argument('--output', type=str, default=None,
                        help='Output file path (default: stdout)')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path')
    args = parser.parse_args()

    root = Path(args.path).resolve()
    spec = generate_full_spec(root, args.module)

    if args.output:
        Path(args.output).write_text(spec)
        print(f"Product spec written to {args.output}")
    else:
        print(spec)


if __name__ == '__main__':
    main()
