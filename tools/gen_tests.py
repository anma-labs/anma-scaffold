#!/usr/bin/env python3
"""ANMA Test Stub Generator.

Generates TESTS.yaml stubs from CONTRACT.yaml — one happy-path and one error
test per interface. Intended as a starting point, not a final test suite.

Usage:
    python3 gen_tests.py auth-service                          # Print to stdout
    python3 gen_tests.py auth-service --output modules/auth-service/TESTS.yaml
    python3 gen_tests.py auth-service --append                 # Add missing tests only

Zero external dependencies.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules


def _module_dir(root, module_name):
    try:
        module_paths = discover_modules(root)
    except ValueError:
        module_paths = {}
    return module_paths.get(module_name, root / 'modules' / module_name)


def generate_tests(root, module_name):
    """Generate test stubs from a module's CONTRACT.yaml."""
    contract_path = _module_dir(root, module_name) / 'CONTRACT.yaml'
    if not contract_path.exists():
        print(f"ERROR: No CONTRACT.yaml at {contract_path}", file=sys.stderr)
        sys.exit(1)

    contract = parse_yaml_file(str(contract_path))
    if not contract:
        print(f"ERROR: Could not parse {contract_path}", file=sys.stderr)
        sys.exit(1)

    provides = contract.get('provides', [])
    if not isinstance(provides, list):
        provides = []

    tests = []
    for iface in provides:
        if not isinstance(iface, dict) or 'id' not in iface:
            continue

        iface_id = iface['id']
        input_spec = iface.get('input', {})
        output_spec = iface.get('output', {})
        errors = iface.get('errors', [])

        # Generate sample input
        sample_input = {}
        if isinstance(input_spec, dict):
            for key, type_hint in input_spec.items():
                sample_input[key] = _sample_value(key, str(type_hint))

        # Generate expected output keys
        output_keys = list(output_spec.keys()) if isinstance(output_spec, dict) else []

        # Happy path test
        happy = {
            'interface': iface_id,
            'case': f'{iface_id}_success',
            'input': sample_input,
            'expect': {},
        }
        if output_keys:
            happy['expect']['has_keys'] = output_keys
        tests.append(happy)

        # Error test for first error code (if any)
        if isinstance(errors, list) and errors:
            error_code = errors[0]
            error_test = {
                'interface': iface_id,
                'case': f'{iface_id}_{str(error_code).lower()}',
                'input': _error_input(sample_input, str(error_code)),
                'expect': {'error': str(error_code)},
            }
            tests.append(error_test)

    return tests


def _sample_value(key, type_hint):
    """Generate a sample value based on key name and type hint."""
    hint = type_hint.lower()
    if 'uuid' in hint or key.endswith('_id') or key == 'id':
        return 'test-uuid-001'
    if 'email' in key:
        return 'test@test.com'
    if 'password' in key:
        return 'test_password_123'
    if 'token' in key:
        return 'test_token_abc'
    if 'bool' in hint:
        return True
    if 'int' in hint or 'number' in hint:
        return 1
    if 'timestamp' in hint or 'date' in key:
        return '2026-01-01T00:00:00Z'
    return f'test_{key}'


def _error_input(sample_input, error_code):
    """Generate input that would trigger the given error."""
    error_input = dict(sample_input)
    code_lower = error_code.lower()
    if 'not_found' in code_lower:
        # Use a nonexistent ID
        for key in error_input:
            if key.endswith('_id') or key == 'id':
                error_input[key] = 'nonexistent-id'
                break
    elif 'invalid' in code_lower:
        # Use invalid data
        for key in error_input:
            if 'email' in key:
                error_input[key] = 'not-an-email'
            elif 'password' in key:
                error_input[key] = ''
            else:
                error_input[key] = None
            break
    return error_input


def format_tests_yaml(module_name, tests):
    """Format tests as TESTS.yaml content."""
    lines = [
        "# Auto-generated test stubs. Review and customize before using.",
        f"module: {module_name}",
        "tests:",
    ]

    for t in tests:
        lines.append(f"  - interface: {t['interface']}")
        lines.append(f"    case: {t['case']}")

        # Format input
        input_parts = []
        for k, v in t['input'].items():
            if isinstance(v, str):
                input_parts.append(f'{k}: "{v}"')
            elif v is None:
                input_parts.append(f'{k}: null')
            elif isinstance(v, bool):
                input_parts.append(f'{k}: {"true" if v else "false"}')
            else:
                input_parts.append(f'{k}: {v}')
        lines.append(f"    input: {{ {', '.join(input_parts)} }}")

        # Format expect
        expect = t['expect']
        if 'has_keys' in expect:
            keys_str = ', '.join(expect['has_keys'])
            lines.append(f"    expect:")
            lines.append(f"      has_keys: [{keys_str}]")
        elif 'error' in expect:
            lines.append(f"    expect:")
            lines.append(f"      error: {expect['error']}")
        else:
            lines.append(f"    expect: {{}}")

        lines.append("")

    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Test Stub Generator')
    parser.add_argument('module', help='Module name')
    parser.add_argument('--output', type=str, default=None,
                        help='Write to file instead of stdout')
    parser.add_argument('--append', action='store_true',
                        help='Only add tests for interfaces not already covered')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path')
    args = parser.parse_args()

    root = Path(args.path).resolve()
    tests = generate_tests(root, args.module)

    # Append mode: filter out tests for already-covered interfaces
    if args.append:
        existing_path = _module_dir(root, args.module) / 'TESTS.yaml'
        if existing_path.exists():
            existing = parse_yaml_file(str(existing_path))
            if existing and isinstance(existing.get('tests'), list):
                covered = set()
                for t in existing['tests']:
                    if isinstance(t, dict) and 'interface' in t:
                        covered.add(t['interface'])
                tests = [t for t in tests if t['interface'] not in covered]
                if not tests:
                    print("All interfaces already have tests.", file=sys.stderr)
                    sys.exit(0)

    content = format_tests_yaml(args.module, tests)

    if args.output:
        Path(args.output).write_text(content)
        print(f"Generated {len(tests)} test stub(s) → {args.output}", file=sys.stderr)
    else:
        print(content)


if __name__ == '__main__':
    main()
