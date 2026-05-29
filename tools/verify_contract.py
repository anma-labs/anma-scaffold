#!/usr/bin/env python3
"""ANMA Contract Verifier.

Validates module implementations against CONTRACT and TESTS.yaml.
Works in two modes:
  --plan     Generate a test plan (no implementation needed)
  --endpoint Run tests against a live HTTP endpoint

Usage:
    python3 verify_contract.py auth-service --plan
    python3 verify_contract.py auth-service --endpoint http://localhost:3000

Zero external dependencies for plan mode. Endpoint mode uses urllib (stdlib).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file
from discover import discover_modules


def load_module_tests(root, module_name, module_paths=None):
    """Load TESTS.yaml and CONTRACT for a module."""
    if module_paths is None:
        try:
            module_paths = discover_modules(root)
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    mod_dir = module_paths.get(module_name, root / 'modules' / module_name)
    tests_file = mod_dir / 'TESTS.yaml'
    contract_file = mod_dir / 'CONTRACT.yaml'

    if not tests_file.exists():
        print(f"ERROR: TESTS.yaml not found for '{module_name}'")
        sys.exit(1)
    if not contract_file.exists():
        print(f"ERROR: CONTRACT.yaml not found for '{module_name}'")
        sys.exit(1)

    tests = parse_yaml_file(str(tests_file))
    if not tests or not isinstance(tests, dict) or '_parse_error' in tests:
        print(f"ERROR: Could not parse TESTS.yaml for '{module_name}'")
        if isinstance(tests, dict) and '_parse_error' in tests:
            print(f"  {tests['_parse_error']}")
        sys.exit(1)
    contract = parse_yaml_file(str(contract_file))
    if not contract or not isinstance(contract, dict) or '_parse_error' in contract:
        print(f"ERROR: Could not parse CONTRACT.yaml for '{module_name}'")
        if isinstance(contract, dict) and '_parse_error' in contract:
            print(f"  {contract['_parse_error']}")
        sys.exit(1)
    return tests, contract


def validate_response(response, expect):
    """Validate a response dict against expect rules. Returns (pass, details)."""
    if not isinstance(expect, dict):
        return True, "no expectations"

    failures = []

    # Check error
    expected_error = expect.get('error')
    if expected_error:
        if isinstance(response, dict):
            actual_error = response.get('error', response.get('code'))
            if str(actual_error) != str(expected_error):
                failures.append(f"expected error '{expected_error}', got '{actual_error}'")
        else:
            failures.append(f"expected error '{expected_error}', got non-dict response")

    # Check has_keys
    has_keys = expect.get('has_keys')
    if has_keys and isinstance(has_keys, list) and isinstance(response, dict):
        for key in has_keys:
            if str(key) not in response:
                failures.append(f"missing key '{key}'")

    # Check valid field
    if 'valid' in expect and isinstance(response, dict):
        expected_valid = expect['valid']
        actual_valid = response.get('valid')
        if actual_valid != expected_valid:
            failures.append(f"expected valid={expected_valid}, got valid={actual_valid}")

    # Check no_throw
    if expect.get('no_throw') and isinstance(response, dict):
        if 'error' in response or 'exception' in response:
            failures.append("expected no_throw but got error/exception")

    if failures:
        return False, '; '.join(failures)
    return True, "OK"


def generate_plan(tests, contract, module_name):
    """Generate a human/AI-readable test plan."""
    test_list = tests.get('tests', [])
    if not isinstance(test_list, list):
        test_list = []

    # Get interface details from contract
    iface_map = {}
    provides = contract.get('provides', [])
    if isinstance(provides, list):
        for p in provides:
            if isinstance(p, dict) and p.get('id'):
                iface_map[str(p['id'])] = p

    lines = [
        f"# Test Plan: {module_name}",
        f"# {len(test_list)} test case(s)",
        "",
    ]

    by_interface = {}
    for t in test_list:
        if not isinstance(t, dict):
            continue
        iface = str(t.get('interface', ''))
        if iface not in by_interface:
            by_interface[iface] = []
        by_interface[iface].append(t)

    for iface_name, cases in sorted(by_interface.items()):
        iface_spec = iface_map.get(iface_name, {})
        lines.append(f"## Interface: {iface_name}")
        if iface_spec.get('invariants'):
            for inv in iface_spec['invariants']:
                lines.append(f"  Invariant: {inv}")
        lines.append("")

        for t in cases:
            case_name = t.get('case', '??')
            test_input = t.get('input', {})
            expect = t.get('expect', {})
            precondition = t.get('precondition')

            lines.append(f"  Case: {case_name}")
            if precondition:
                lines.append(f"    Precondition: {precondition}")
            lines.append(f"    Input: {json.dumps(test_input, default=str)}")
            lines.append(f"    Expect: {json.dumps(expect, default=str)}")
            lines.append("")

    return '\n'.join(lines)


def run_endpoint_tests(tests, module_name, endpoint):
    """Run tests against a live HTTP endpoint."""
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError

    test_list = tests.get('tests', [])
    if not isinstance(test_list, list):
        test_list = []

    passed = 0
    failed = 0
    skipped = 0

    for t in test_list:
        if not isinstance(t, dict):
            continue

        iface = t.get('interface', '??')
        case = t.get('case', '??')
        test_input = t.get('input', {})
        expect = t.get('expect', {})
        precondition = t.get('precondition')

        if precondition:
            print(f"  SKIP {iface}.{case} (has precondition: {precondition})")
            skipped += 1
            continue

        url = f"{endpoint.rstrip('/')}/{iface}"
        try:
            req = Request(url, data=json.dumps(test_input).encode(),
                          headers={'Content-Type': 'application/json'})
            resp = urlopen(req, timeout=10)
            body = json.loads(resp.read())
            ok, details = validate_response(body, expect)
        except HTTPError as e:
            try:
                body = json.loads(e.read())
                ok, details = validate_response(body, expect)
            except Exception:
                ok, details = False, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            ok, details = False, f"Connection failed: {e.reason}"
        except Exception as e:
            ok, details = False, str(e)

        if ok:
            print(f"  PASS {iface}.{case}")
            passed += 1
        else:
            print(f"  FAIL {iface}.{case}: {details}")
            failed += 1

    return passed, failed, skipped


def main():
    parser = argparse.ArgumentParser(
        description='ANMA Contract Verifier')
    parser.add_argument('module', help='Module name to verify')
    parser.add_argument('--plan', action='store_true',
                        help='Generate test plan (no implementation needed)')
    parser.add_argument('--endpoint', type=str, default=None,
                        help='HTTP endpoint to test against (e.g., http://localhost:3000)')
    parser.add_argument('--path', type=str, default='.',
                        help='Project root path (default: current directory)')
    args = parser.parse_args()

    root = Path(args.path).resolve()
    tests, contract = load_module_tests(root, args.module)

    if args.plan:
        print(generate_plan(tests, contract, args.module))
        return

    if args.endpoint:
        print(f"\nANMA Contract Verifier: {args.module}")
        print(f"  Endpoint: {args.endpoint}")
        print()
        passed, failed, skipped = run_endpoint_tests(tests, args.module, args.endpoint)
        print(f"\n  {passed} passed, {failed} failed, {skipped} skipped")
        sys.exit(1 if failed > 0 else 0)

    # Default: just validate test plan structure
    test_list = tests.get('tests', [])
    total = len(test_list) if isinstance(test_list, list) else 0
    print(f"{args.module}: {total} contract test(s) defined")
    print(f"  Run with --plan for details or --endpoint URL to verify live")


if __name__ == '__main__':
    main()
