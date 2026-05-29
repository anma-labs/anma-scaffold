#!/usr/bin/env python3
"""ANMA Linter Test Suite.

Regression tests for all 20 linter checks, the YAML parser,
and CLI behavior. Run with: python3 test_linter.py

Zero external dependencies — uses only stdlib unittest.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Import linter
sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import (
    LintResult, parse_yaml, parse_yaml_file,
    load_all_contracts, load_graph, load_conventions, load_manifest,
    check_cross_references, check_graph_consistency,
    check_naming_conventions, check_circular_dependencies,
    check_contract_structure, check_manifest_consistency,
    check_state_files, check_memory_files, check_granularity,
    check_test_files, check_context_budget, check_conventions_version,
    check_module_types, check_assumptions, check_changelog,
    check_replacement_ready, check_bus, check_assumption_compatibility,
    check_managers_orchestrator, check_delta_accuracy,
    check_version_pinning, check_stale_requests, check_schemas,
)
from discover import discover_modules, get_module_domain, discover_domains

TOOLS_DIR = Path(__file__).parent
PROJECT_ROOT = TOOLS_DIR.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TempProject:
    """Context manager for temporary ANMA project directories."""

    def __init__(self):
        self._tmpdir = None
        self.root = None

    def __enter__(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        return self

    def __exit__(self, *args):
        self._tmpdir.cleanup()

    def add_module(self, name, contract_text):
        d = self.root / 'modules' / name
        d.mkdir(parents=True, exist_ok=True)
        (d / 'CONTRACT.yaml').write_text(contract_text)
        return d

    def add_domain_module(self, domain, name, contract_text):
        d = self.root / 'domains' / domain / name
        d.mkdir(parents=True, exist_ok=True)
        (d / 'CONTRACT.yaml').write_text(contract_text)
        return d

    def add_gateway(self, domain, gateway_text):
        d = self.root / 'domains' / domain
        d.mkdir(parents=True, exist_ok=True)
        p = d / 'GATEWAY.yaml'
        p.write_text(gateway_text)
        return p

    def add_file(self, relpath, content):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p


# ---------------------------------------------------------------------------
# YAML Parser Tests
# ---------------------------------------------------------------------------

class TestYamlParser(unittest.TestCase):

    def test_basic_mapping(self):
        r = parse_yaml("key: value")
        self.assertEqual(r['key'], 'value')

    def test_integer(self):
        r = parse_yaml("count: 42")
        self.assertEqual(r['count'], 42)

    def test_boolean_variants(self):
        for truthy in ['true', 'True', 'TRUE', 'yes', 'Yes', 'on']:
            r = parse_yaml(f"val: {truthy}")
            self.assertTrue(r['val'], f"Failed for {truthy}")
        for falsy in ['false', 'False', 'FALSE', 'no', 'No', 'off']:
            r = parse_yaml(f"val: {falsy}")
            self.assertFalse(r['val'], f"Failed for {falsy}")

    def test_null_variants(self):
        for null in ['null', 'Null', 'NULL', '~']:
            r = parse_yaml(f"val: {null}")
            self.assertIsNone(r['val'], f"Failed for {null}")

    def test_list(self):
        r = parse_yaml("items:\n  - a\n  - b\n  - c")
        self.assertEqual(r['items'], ['a', 'b', 'c'])

    def test_flow_list(self):
        r = parse_yaml("items: [a, b, c]")
        self.assertEqual(r['items'], ['a', 'b', 'c'])

    def test_flow_mapping(self):
        r = parse_yaml("data: { key: value, num: 5 }")
        self.assertEqual(r['data']['key'], 'value')
        self.assertEqual(r['data']['num'], 5)

    def test_nested_mapping(self):
        r = parse_yaml("outer:\n  inner: val")
        self.assertEqual(r['outer']['inner'], 'val')

    def test_quoted_string(self):
        r = parse_yaml('msg: "hello world"')
        self.assertEqual(r['msg'], 'hello world')

    def test_empty_list(self):
        r = parse_yaml("items: []")
        self.assertEqual(r['items'], [])

    def test_comments_stripped(self):
        r = parse_yaml("key: value  # comment")
        self.assertEqual(r['key'], 'value')

    def test_forbidden_is_string(self):
        """'forbidden' is not a YAML boolean — stays as string."""
        r = parse_yaml("val: forbidden")
        self.assertEqual(r['val'], 'forbidden')
        self.assertIsInstance(r['val'], str)


# ---------------------------------------------------------------------------
# Scaffold Integration Tests
# ---------------------------------------------------------------------------

class TestScaffoldClean(unittest.TestCase):
    """Verify the shipped scaffold passes all checks."""

    @classmethod
    def setUpClass(cls):
        cls.root = PROJECT_ROOT
        cls.contracts = load_all_contracts(cls.root)
        cls.conv = load_conventions(cls.root)
        cls.graph = load_graph(cls.root)
        cls.manifest = load_manifest(cls.root)
        cls.module_paths = discover_modules(cls.root)

    def _run_check(self, fn, *args, **kwargs):
        r = LintResult()
        fn(*args, r, **kwargs)
        return r

    def test_cross_references(self):
        r = self._run_check(check_cross_references, self.contracts, self.contracts)
        self.assertTrue(r.ok())
        self.assertEqual(len(r.warnings), 0)

    def test_graph_consistency(self):
        r = self._run_check(check_graph_consistency, self.contracts, self.contracts, self.graph)
        self.assertTrue(r.ok())

    def test_naming(self):
        r = self._run_check(check_naming_conventions, self.contracts, self.conv)
        self.assertTrue(r.ok())

    def test_circular(self):
        r = self._run_check(check_circular_dependencies, self.contracts)
        self.assertTrue(r.ok())

    def test_structure(self):
        r = self._run_check(check_contract_structure, self.contracts)
        self.assertTrue(r.ok())

    def test_manifest(self):
        r = self._run_check(check_manifest_consistency, self.contracts, self.manifest)
        self.assertTrue(r.ok())

    def test_state(self):
        r = self._run_check(check_state_files, self.root, self.contracts, module_paths=self.module_paths)
        self.assertTrue(r.ok())

    def test_memory(self):
        r = self._run_check(check_memory_files, self.root, self.contracts, self.conv, module_paths=self.module_paths)
        self.assertTrue(r.ok())

    def test_granularity(self):
        r = self._run_check(check_granularity, self.contracts, self.conv)
        self.assertTrue(r.ok())

    def test_tests(self):
        r = self._run_check(check_test_files, self.root, self.contracts, module_paths=self.module_paths)
        self.assertTrue(r.ok())

    def test_budget(self):
        r = self._run_check(check_context_budget, self.root, self.contracts, self.conv, module_paths=self.module_paths)
        self.assertTrue(r.ok())

    def test_conventions_version(self):
        r = self._run_check(check_conventions_version, self.conv)
        self.assertTrue(r.ok())

    def test_module_types(self):
        r = self._run_check(check_module_types, self.contracts, self.conv)
        self.assertTrue(r.ok())

    def test_assumptions(self):
        r = self._run_check(check_assumptions, self.root, self.contracts, module_paths=self.module_paths)
        self.assertTrue(r.ok())

    def test_changelog(self):
        r = self._run_check(check_changelog, self.root, self.contracts, module_paths=self.module_paths)
        self.assertTrue(r.ok())

    def test_replacement(self):
        r = self._run_check(check_replacement_ready, self.root, self.contracts, module_paths=self.module_paths)
        self.assertTrue(r.ok())

    def test_bus(self):
        r = self._run_check(check_bus, self.root, self.contracts)
        self.assertTrue(r.ok())

    def test_assumption_compat(self):
        r = self._run_check(check_assumption_compatibility, self.root, self.contracts, module_paths=self.module_paths)
        self.assertTrue(r.ok())
        self.assertIsInstance(r.warnings, list)

    def test_managers_orchestrator(self):
        r = self._run_check(check_managers_orchestrator, self.root, self.contracts, self.manifest)
        self.assertTrue(r.ok())

    def test_delta_accuracy(self):
        r = self._run_check(check_delta_accuracy, self.root, self.contracts)
        self.assertTrue(r.ok())


# ---------------------------------------------------------------------------
# Check-Specific Edge Cases
# ---------------------------------------------------------------------------

class TestCircularDependencies(unittest.TestCase):

    def test_hard_cycle(self):
        r = LintResult()
        check_circular_dependencies({
            'a': {'consumes': [{'module': 'b', 'interface': 'x', 'required': True}]},
            'b': {'consumes': [{'module': 'a', 'interface': 'y', 'required': True}]},
        }, r)
        self.assertEqual(len(r.errors), 1)

    def test_boolean_string_required(self):
        """'True' (string from YAML) must be treated as truthy."""
        r = LintResult()
        check_circular_dependencies({
            'a': {'consumes': [{'module': 'b', 'interface': 'x', 'required': 'True'}]},
            'b': {'consumes': [{'module': 'a', 'interface': 'y', 'required': 'Yes'}]},
        }, r)
        self.assertEqual(len(r.errors), 1)

    def test_soft_cycle_warning(self):
        r = LintResult()
        check_circular_dependencies({
            'a': {'consumes': [{'module': 'b', 'interface': 'x', 'required': False}]},
            'b': {'consumes': [{'module': 'a', 'interface': 'y', 'required': False}]},
        }, r)
        self.assertEqual(len(r.errors), 0)
        self.assertEqual(len(r.warnings), 1)

    def test_no_cycle(self):
        r = LintResult()
        check_circular_dependencies({
            'a': {'consumes': [{'module': 'b', 'interface': 'x', 'required': True}]},
            'b': {'consumes': []},
        }, r)
        self.assertTrue(r.ok())


class TestFrozenContracts(unittest.TestCase):

    def _make_frozen(self, rules):
        return {'module': 'm', 'version': 1, 'status': 'frozen', 'purpose': 'x',
                'provides': [{'id': 'f', 'input': {}, 'output': {}, 'errors': [], 'invariants': ['x']}],
                'contract_rules': rules}

    def test_correct_frozen(self):
        r = LintResult()
        check_contract_structure({'m': self._make_frozen(
            {'modifying_interface': 'forbidden', 'removing_interface': 'forbidden'})}, r)
        self.assertTrue(r.ok())

    def test_frozen_bad_rules(self):
        r = LintResult()
        check_contract_structure({'m': self._make_frozen(
            {'modifying_interface': 'notify', 'removing_interface': 'breaking'})}, r)
        self.assertEqual(len(r.errors), 2)

    def test_frozen_missing_rules(self):
        """Frozen with no contract_rules → error (must explicitly set forbidden)."""
        c = self._make_frozen({})
        del c['contract_rules']
        r = LintResult()
        check_contract_structure({'m': c}, r)
        self.assertEqual(len(r.errors), 1)

    def test_frozen_empty_rules(self):
        """Frozen with empty rules → 2 errors (both fields missing)."""
        r = LintResult()
        check_contract_structure({'m': self._make_frozen({})}, r)
        self.assertEqual(len(r.errors), 2)

    def test_stable_not_affected(self):
        c = self._make_frozen({'modifying_interface': 'notify', 'removing_interface': 'breaking'})
        c['status'] = 'stable'
        r = LintResult()
        check_contract_structure({'m': c}, r)
        self.assertTrue(r.ok())


class TestGranularity(unittest.TestCase):

    def _make(self, count, status='stable'):
        return {'m': {'provides': [{'id': f'f{i}'} for i in range(count)], 'status': status}}

    def test_within_range(self):
        conv = {'granularity': {'min_interfaces': 3, 'max_interfaces': 7, 'split_threshold': 12}}
        r = LintResult()
        check_granularity(self._make(5), conv, r)
        self.assertTrue(r.ok())

    def test_too_many(self):
        conv = {'granularity': {'min_interfaces': 3, 'max_interfaces': 7, 'split_threshold': 12}}
        r = LintResult()
        check_granularity(self._make(13), conv, r)
        self.assertEqual(len(r.errors), 1)

    def test_too_few_stable(self):
        conv = {'granularity': {'min_interfaces': 3, 'max_interfaces': 7, 'split_threshold': 12}}
        r = LintResult()
        check_granularity(self._make(2, 'stable'), conv, r)
        self.assertEqual(len(r.warnings), 1)

    def test_too_few_draft_exempt(self):
        conv = {'granularity': {'min_interfaces': 3, 'max_interfaces': 7, 'split_threshold': 12}}
        r = LintResult()
        check_granularity(self._make(2, 'draft'), conv, r)
        self.assertEqual(len(r.warnings), 0)


class TestMemoryCaps(unittest.TestCase):

    def test_over_max_entries(self):
        with TempProject() as tp:
            tp.add_file('modules/tm/MEMORY.yaml',
                        "module: tm\nentries:\n" +
                        "\n".join(f"  - type: decision\n    content: \"e{i}\"" for i in range(21)))
            r = LintResult()
            check_memory_files(tp.root, {'tm': {}},
                               {'memory': {'max_entries': 20, 'max_content_chars': 100,
                                           'valid_types': ['decision', 'discovery', 'warning', 'pattern']}}, r)
            self.assertEqual(len(r.errors), 1)

    def test_missing_file(self):
        with TempProject() as tp:
            (tp.root / 'modules' / 'tm').mkdir(parents=True)
            r = LintResult()
            check_memory_files(tp.root, {'tm': {}}, {}, r)
            self.assertEqual(len(r.warnings), 1)


class TestConventionsVersion(unittest.TestCase):

    def test_valid(self):
        r = LintResult()
        check_conventions_version({'conventions_version': 1}, r)
        self.assertTrue(r.ok())

    def test_missing(self):
        r = LintResult()
        check_conventions_version({}, r)
        self.assertEqual(len(r.errors), 1)

    def test_zero(self):
        r = LintResult()
        check_conventions_version({'conventions_version': 0}, r)
        self.assertEqual(len(r.errors), 1)

    def test_string(self):
        r = LintResult()
        check_conventions_version({'conventions_version': 'one'}, r)
        self.assertEqual(len(r.errors), 1)

    def test_none_conventions(self):
        r = LintResult()
        check_conventions_version(None, r)
        self.assertEqual(len(r.errors), 1)


class TestModuleTypes(unittest.TestCase):

    def test_infra_frozen_ok(self):
        r = LintResult()
        check_module_types({'m': {'type': 'infrastructure', 'status': 'frozen'}},
                           {'module_types': {'valid': ['regular', 'infrastructure']}}, r)
        self.assertTrue(r.ok())

    def test_infra_draft_error(self):
        r = LintResult()
        check_module_types({'m': {'type': 'infrastructure', 'status': 'draft'}},
                           {'module_types': {'valid': ['regular', 'infrastructure']}}, r)
        self.assertEqual(len(r.errors), 1)

    def test_unknown_type_warning(self):
        r = LintResult()
        check_module_types({'m': {'type': 'unknown', 'status': 'draft'}},
                           {'module_types': {'valid': ['regular', 'infrastructure']}}, r)
        self.assertEqual(len(r.warnings), 1)


class TestTestFiles(unittest.TestCase):

    def test_coverage(self):
        with TempProject() as tp:
            tp.add_file('modules/tm/TESTS.yaml',
                        "module: tm\ntests:\n  - interface: fa\n    case: t1\n    expect: {}")
            r = LintResult()
            check_test_files(tp.root, {'tm': {'provides': [{'id': 'fa'}]}}, r)
            self.assertTrue(r.ok())

    def test_orphan(self):
        with TempProject() as tp:
            tp.add_file('modules/tm/TESTS.yaml',
                        "module: tm\ntests:\n  - interface: ghost\n    case: t1\n    expect: {}")
            r = LintResult()
            check_test_files(tp.root, {'tm': {'provides': [{'id': 'fa'}]}}, r)
            self.assertEqual(len(r.errors), 1)  # ghost reference

    def test_duplicate_case(self):
        with TempProject() as tp:
            tp.add_file('modules/tm/TESTS.yaml',
                        "module: tm\ntests:\n"
                        "  - interface: fa\n    case: t1\n    expect: {}\n"
                        "  - interface: fa\n    case: t1\n    expect: {}")
            r = LintResult()
            check_test_files(tp.root, {'tm': {'provides': [{'id': 'fa'}]}}, r)
            self.assertEqual(len(r.errors), 1)  # duplicate


class TestContextBudget(unittest.TestCase):

    def _setup(self, tp, shared_size, mod_sizes):
        tp.add_file('CONVENTIONS.yaml', 'x' * shared_size)
        tp.add_file('MANIFEST.yaml', '')
        tp.add_file('GRAPH.yaml', '')
        for fname, size in mod_sizes.items():
            tp.add_file(f'modules/tm/{fname}', 'x' * size)

    def test_under_budget(self):
        with TempProject() as tp:
            self._setup(tp, 2000, {'CONTRACT.yaml': 2000, 'STATE.yaml': 500, 'MEMORY.yaml': 500})
            r = LintResult()
            check_context_budget(tp.root, {'tm': {}},
                                 {'context_budget': {'warn_tokens': 2000, 'error_tokens': 3000}}, r)
            self.assertTrue(r.ok())

    def test_over_warn(self):
        with TempProject() as tp:
            self._setup(tp, 4000, {'CONTRACT.yaml': 2000, 'STATE.yaml': 1000, 'MEMORY.yaml': 1004})
            r = LintResult()
            check_context_budget(tp.root, {'tm': {}},
                                 {'context_budget': {'warn_tokens': 2000, 'error_tokens': 3000}}, r)
            self.assertEqual(len(r.warnings), 1)

    def test_over_error(self):
        with TempProject() as tp:
            self._setup(tp, 4000, {'CONTRACT.yaml': 4000, 'STATE.yaml': 2000, 'MEMORY.yaml': 2004})
            r = LintResult()
            check_context_budget(tp.root, {'tm': {}},
                                 {'context_budget': {'warn_tokens': 2000, 'error_tokens': 3000}}, r)
            self.assertEqual(len(r.errors), 1)


class TestBusValidation(unittest.TestCase):

    def test_valid_delta(self):
        with TempProject() as tp:
            tp.add_file('BUS/deltas/d.yaml',
                        "source: mod-a\ntimestamp: 2026-01-01T00:00:00Z\ntype: interface_added")
            tp.add_file('BUS/requests/.gitkeep', '')
            r = LintResult()
            check_bus(tp.root, {'mod-a': {}}, r)
            self.assertTrue(r.ok())

    def test_bad_source(self):
        with TempProject() as tp:
            tp.add_file('BUS/deltas/d.yaml',
                        "source: ghost\ntimestamp: 2026-01-01T00:00:00Z\ntype: interface_added")
            tp.add_file('BUS/requests/.gitkeep', '')
            r = LintResult()
            check_bus(tp.root, {'mod-a': {}}, r)
            self.assertEqual(len(r.errors), 1)

    def test_dup_request_id(self):
        with TempProject() as tp:
            tp.add_file('BUS/deltas/.gitkeep', '')
            tp.add_file('BUS/requests/r1.yaml',
                        "id: X\nfrom: a\nto: b\nstatus: open\nrequest: x")
            tp.add_file('BUS/requests/r2.yaml',
                        "id: X\nfrom: a\nto: b\nstatus: open\nrequest: y")
            r = LintResult()
            check_bus(tp.root, {'a': {}, 'b': {}}, r)
            self.assertEqual(len(r.errors), 1)


class TestDeltaAccuracy(unittest.TestCase):

    def test_added_exists(self):
        with TempProject() as tp:
            tp.add_file('BUS/deltas/d.yaml',
                        "source: m\ntype: interface_added\nchange:\n  added:\n    id: func_a")
            r = LintResult()
            check_delta_accuracy(tp.root, {'m': {'provides': [{'id': 'func_a'}]}}, r)
            self.assertEqual(len(r.warnings), 0)

    def test_added_missing(self):
        with TempProject() as tp:
            tp.add_file('BUS/deltas/d.yaml',
                        "source: m\ntype: interface_added\nchange:\n  added:\n    id: ghost")
            r = LintResult()
            check_delta_accuracy(tp.root, {'m': {'provides': [{'id': 'func_a'}]}}, r)
            self.assertEqual(len(r.warnings), 1)

    def test_removed_still_exists(self):
        with TempProject() as tp:
            tp.add_file('BUS/deltas/d.yaml',
                        "source: m\ntype: interface_removed\nchange:\n  removed:\n    id: func_a")
            r = LintResult()
            check_delta_accuracy(tp.root, {'m': {'provides': [{'id': 'func_a'}]}}, r)
            self.assertEqual(len(r.warnings), 1)


class TestReplacementReady(unittest.TestCase):

    def test_all_files_stable(self):
        with TempProject() as tp:
            for f in ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml',
                       'CHANGELOG.yaml', 'TESTS.yaml', 'ASSUMPTIONS.yaml']:
                tp.add_file(f'modules/tm/{f}', 'module: tm\n')
            r = LintResult()
            check_replacement_ready(tp.root, {'tm': {'status': 'stable'}}, r)
            self.assertEqual(len(r.warnings), 0)

    def test_missing_file_stable(self):
        with TempProject() as tp:
            for f in ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml']:
                tp.add_file(f'modules/tm/{f}', 'module: tm\n')
            r = LintResult()
            check_replacement_ready(tp.root, {'tm': {'status': 'stable'}}, r)
            self.assertEqual(len(r.warnings), 1)

    def test_missing_file_draft_exempt(self):
        with TempProject() as tp:
            for f in ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml']:
                tp.add_file(f'modules/tm/{f}', 'module: tm\n')
            r = LintResult()
            check_replacement_ready(tp.root, {'tm': {'status': 'draft'}}, r)
            self.assertEqual(len(r.warnings), 0)


class TestAssumptionCompatibility(unittest.TestCase):

    def test_no_overlap(self):
        with TempProject() as tp:
            tp.add_file('modules/a/ASSUMPTIONS.yaml',
                        "module: a\nassumptions:\n  - id: A1\n    category: data\n    content: \"x\"")
            tp.add_file('modules/b/ASSUMPTIONS.yaml',
                        "module: b\nassumptions:\n  - id: B1\n    category: retry\n    content: \"y\"")
            r = LintResult()
            check_assumption_compatibility(tp.root, {'a': {}, 'b': {}}, r)
            self.assertEqual(len(r.warnings), 0)

    def test_shared_category(self):
        with TempProject() as tp:
            tp.add_file('modules/a/ASSUMPTIONS.yaml',
                        "module: a\nassumptions:\n  - id: A1\n    category: data\n    content: \"x\"")
            tp.add_file('modules/b/ASSUMPTIONS.yaml',
                        "module: b\nassumptions:\n  - id: B1\n    category: data\n    content: \"y\"")
            r = LintResult()
            check_assumption_compatibility(tp.root, {'a': {}, 'b': {}}, r)
            self.assertEqual(len(r.warnings), 1)


# ---------------------------------------------------------------------------
# CLI Tests
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def test_normal_exit_zero(self):
        result = subprocess.run(
            [sys.executable, 'lint_contracts.py'],
            capture_output=True, cwd=str(TOOLS_DIR))
        self.assertEqual(result.returncode, 0)

    def test_strict_exit_nonzero(self):
        """Strict mode: warnings become errors, exit code 2."""
        with TempProject() as tp:
            tp.add_file('CONVENTIONS.yaml',
                        'conventions_version: 2\nmemory:\n  max_entries: 20\n  max_content_chars: 100\n'
                        'token_thresholds:\n  contract_max: 500\n  recovery_max: 800')
            tp.add_file('MANIFEST.yaml',
                        'project: test\nversion: 1\nupdated: 2026-01-01T00:00:00Z\n'
                        'modules:\n  a: { status: stable, owner: core }\n  b: { status: stable, owner: core }\n'
                        'managers:\n  core: { owns: [a, b] }\norchestrator: active')
            tp.add_file('GRAPH.yaml',
                        'modules:\n  a:\n    consumes: []\n  b:\n    consumes: []')
            contract_tpl = (
                'module: {mod}\nversion: 1\nconventions_version: 2\n'
                'status: stable\ntype: regular\npurpose: test module {mod}\n'
                'provides:\n'
                '- id: do_{mod}\n  input: {{ x: string }}\n  output: {{ y: string }}\n'
                '  errors: [ERR_1]\n  invariants: ["must validate input"]\n'
                '- id: get_{mod}\n  input: {{ id: uuid }}\n  output: {{ item: object }}\n'
                '  errors: [NOT_FOUND]\n  invariants: ["returns null if missing"]\n'
                '- id: list_{mod}\n  input: {{}}\n  output: {{ items: "[object]" }}\n'
                '  errors: []\n  invariants: ["sorted by date"]\n'
                'consumes: []')
            tests_tpl = (
                'module: {mod}\ntests:\n'
                '- interface: do_{mod}\n  case: basic\n  input: {{ x: "hi" }}\n  expect: {{ has_keys: [y] }}\n'
                '- interface: get_{mod}\n  case: found\n  input: {{ id: "uuid-1" }}\n  expect: {{ has_keys: [item] }}\n'
                '- interface: list_{mod}\n  case: empty\n  input: {{}}\n  expect: {{ has_keys: [items] }}')
            for mod in ['a', 'b']:
                tp.add_module(mod, contract_tpl.format(mod=mod))
                tp.add_file(f'modules/{mod}/STATE.yaml',
                    f'module: {mod}\nstatus: green\nupdated: 2026-01-01T00:00:00Z\ncurrent_work: done\nblockers: []')
                tp.add_file(f'modules/{mod}/MEMORY.yaml', f'module: {mod}\nentries: []')
                tp.add_file(f'modules/{mod}/TESTS.yaml', tests_tpl.format(mod=mod))
                tp.add_file(f'modules/{mod}/CHANGELOG.yaml', f'module: {mod}\nchanges: []')
            # Overlapping assumption categories → warning (the only non-clean signal)
            tp.add_file('modules/a/ASSUMPTIONS.yaml',
                        'module: a\nassumptions:\n  - id: A1\n    category: data\n    content: "uses PostgreSQL"')
            tp.add_file('modules/b/ASSUMPTIONS.yaml',
                        'module: b\nassumptions:\n  - id: B1\n    category: data\n    content: "uses MySQL"')
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'lint_contracts.py'), '--strict',
                 str(tp.root)],
                capture_output=True)
            self.assertEqual(result.returncode, 2,
                             f"Expected exit 2 in strict mode, got {result.returncode}\n"
                             f"stdout: {result.stdout.decode()[-500:]}")

    def test_module_filter(self):
        # Dynamically find the first available module instead of hardcoding
        modules_dir = PROJECT_ROOT / 'modules'
        module_dirs = [d.name for d in modules_dir.iterdir()
                       if d.is_dir() and (d / 'CONTRACT.yaml').exists()]
        self.assertTrue(module_dirs, "No modules found in scaffold")
        first_module = sorted(module_dirs)[0]
        result = subprocess.run(
            [sys.executable, 'lint_contracts.py', '--module', first_module],
            capture_output=True, cwd=str(TOOLS_DIR))
        self.assertEqual(result.returncode, 0)

    def test_deterministic(self):
        r1 = subprocess.run(
            [sys.executable, 'lint_contracts.py'],
            capture_output=True, cwd=str(TOOLS_DIR))
        r2 = subprocess.run(
            [sys.executable, 'lint_contracts.py'],
            capture_output=True, cwd=str(TOOLS_DIR))
        self.assertEqual(r1.stdout, r2.stdout)

    def test_no_stderr(self):
        result = subprocess.run(
            [sys.executable, 'lint_contracts.py'],
            capture_output=True, cwd=str(TOOLS_DIR))
        self.assertEqual(result.stderr, b'')


# ---------------------------------------------------------------------------
# YAML Editor Tests
# ---------------------------------------------------------------------------

class TestYamlEditor(unittest.TestCase):
    """Tests for yaml_editor.py centralized YAML editing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        # Minimal MANIFEST
        (self.root / 'MANIFEST.yaml').write_text(
            "project: test\nversion: 0.1.0\nupdated: 2026-01-01T00:00:00Z\n\n"
            "modules:\n  existing-mod: { status: draft, owner: agent-x, manager: mgr1 }\n\n"
            "managers:\n  mgr1: { owns: [existing-mod] }\n\norchestrator: active\n")
        # Minimal GRAPH
        (self.root / 'GRAPH.yaml').write_text(
            "version: 1\nupdated: 2026-01-01T00:00:00Z\n\n"
            "modules:\n  existing-mod:\n    consumes: []\n    consumed_by: []\n")
        # Manager SCOPE
        (self.root / 'managers' / 'mgr1').mkdir(parents=True)
        (self.root / 'managers' / 'mgr1' / 'SCOPE.yaml').write_text(
            "manager: mgr1\nowns: [existing-mod]\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_manifest_add_module(self):
        from yaml_editor import manifest_add_module, read_manifest
        ok, err = manifest_add_module(self.root, 'new-mod', manager='mgr1')
        self.assertTrue(ok)
        data = read_manifest(self.root)
        self.assertIn('new-mod', data['modules'])
        self.assertEqual(data['modules']['new-mod']['status'], 'draft')
        # Manager owns updated
        self.assertIn('new-mod', data['managers']['mgr1']['owns'])

    def test_manifest_add_duplicate_rejected(self):
        from yaml_editor import manifest_add_module
        ok, err = manifest_add_module(self.root, 'existing-mod')
        self.assertFalse(ok)
        self.assertIn('already', err)

    def test_manifest_remove_module(self):
        from yaml_editor import manifest_remove_module, read_manifest
        manifest_remove_module(self.root, 'existing-mod')
        data = read_manifest(self.root)
        modules = data.get('modules') or {}
        self.assertNotIn('existing-mod', modules)
        # Also removed from manager owns
        owns = data['managers']['mgr1'].get('owns') or []
        self.assertNotIn('existing-mod', owns)

    def test_manifest_add_manager(self):
        from yaml_editor import manifest_add_manager, read_manifest
        ok, err = manifest_add_manager(self.root, 'mgr2', owns=['existing-mod'])
        self.assertTrue(ok)
        data = read_manifest(self.root)
        self.assertIn('mgr2', data['managers'])
        self.assertIn('existing-mod', data['managers']['mgr2']['owns'])

    def test_manifest_rename(self):
        from yaml_editor import manifest_rename_project, read_manifest
        old = manifest_rename_project(self.root, 'new-name')
        self.assertEqual(old, 'test')
        data = read_manifest(self.root)
        self.assertEqual(data['project'], 'new-name')

    def test_graph_add_module(self):
        from yaml_editor import graph_add_module, read_graph
        graph_add_module(self.root, 'new-mod', ['existing-mod'])
        data = read_graph(self.root)
        self.assertIn('new-mod', data['modules'])
        self.assertEqual(data['modules']['new-mod']['consumes'], ['existing-mod'])
        # consumed_by updated on dependency
        self.assertIn('new-mod', data['modules']['existing-mod']['consumed_by'])

    def test_graph_remove_module(self):
        from yaml_editor import graph_add_module, graph_remove_module, read_graph
        graph_add_module(self.root, 'dep-mod', ['existing-mod'])
        graph_remove_module(self.root, 'dep-mod')
        data = read_graph(self.root)
        self.assertNotIn('dep-mod', data['modules'])
        self.assertNotIn('dep-mod', data['modules']['existing-mod'].get('consumed_by', []))

    def test_scope_add_module(self):
        from yaml_editor import scope_add_module
        scope_add_module(self.root, 'mgr1', 'another-mod')
        content = (self.root / 'managers' / 'mgr1' / 'SCOPE.yaml').read_text()
        self.assertIn('another-mod', content)
        self.assertIn('existing-mod', content)  # original still there

    def test_scope_remove_module(self):
        from yaml_editor import scope_remove_module
        scope_remove_module(self.root, 'mgr1', 'existing-mod')
        content = (self.root / 'managers' / 'mgr1' / 'SCOPE.yaml').read_text()
        self.assertNotIn('existing-mod', content)

    def test_manifest_roundtrip_preserves_data(self):
        """Read → write → read should produce identical data."""
        from yaml_editor import read_manifest, write_manifest
        data1 = read_manifest(self.root)
        write_manifest(self.root, data1)
        data2 = read_manifest(self.root)
        self.assertEqual(data1['project'], data2['project'])
        self.assertEqual(set(data1.get('modules', {}).keys()),
                         set(data2.get('modules', {}).keys()))
        self.assertEqual(set(data1.get('managers', {}).keys()),
                         set(data2.get('managers', {}).keys()))

    def test_empty_modules_section(self):
        """Handle MANIFEST with null modules section."""
        (self.root / 'MANIFEST.yaml').write_text(
            "project: test\nversion: 0.1.0\nupdated: 2026-01-01T00:00:00Z\n\n"
            "modules:\n\nmanagers:\n  mgr1: { owns: [] }\n\norchestrator: active\n")
        from yaml_editor import manifest_add_module, read_manifest
        ok, _ = manifest_add_module(self.root, 'fresh-mod')
        self.assertTrue(ok)
        data = read_manifest(self.root)
        self.assertIn('fresh-mod', data['modules'])


# ---------------------------------------------------------------------------
# Session Log Tests
# ---------------------------------------------------------------------------

class TestSessionLog(unittest.TestCase):
    """Tests for session_log.py."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_log_activity(self):
        (self.root / 'SESSION-HISTORY.yaml').write_text(
            "project: test\nlast_activity: null\nactivity_log: []\n")
        from session_log import log_activity
        log_activity(self.root, "test action", "test.py")
        content = (self.root / 'SESSION-HISTORY.yaml').read_text()
        self.assertIn('test action', content)
        self.assertIn('test.py', content)
        self.assertNotIn('null', content.split('last_activity:')[1].split('\n')[0])

    def test_log_no_file(self):
        """Should not crash when SESSION-HISTORY.yaml doesn't exist."""
        from session_log import log_activity
        log_activity(self.root, "test action", "test.py")  # should not raise

    def test_log_multiple_entries(self):
        (self.root / 'SESSION-HISTORY.yaml').write_text(
            "project: test\nlast_activity: null\nactivity_log: []\n")
        from session_log import log_activity
        log_activity(self.root, "action one", "a.py")
        log_activity(self.root, "action two", "b.py")
        content = (self.root / 'SESSION-HISTORY.yaml').read_text()
        self.assertIn('action one', content)
        self.assertIn('action two', content)


# ---------------------------------------------------------------------------
# Domain Scaling Tests
# ---------------------------------------------------------------------------

_VALID_CONTRACT = """module: {name}
version: 1
status: draft
type: regular
purpose: "{name} module"
provides:
  - id: do_thing
    input: {{ k: string }}
    output: {{ v: string }}
    errors: [NOT_FOUND]
    invariants: ["returns NOT_FOUND for missing keys"]
consumes: {consumes}
contract_rules:
  adding_interface: allowed
  modifying_interface: notify
  removing_interface: breaking
"""


def _flat_contract(name, consumes_yaml='[]'):
    return _VALID_CONTRACT.format(name=name, consumes=consumes_yaml)


def _consume_block(deps):
    """deps = list of (module, interface) tuples."""
    if not deps:
        return '[]'
    lines = ['']
    for mod, iface in deps:
        lines.append(f"  - module: {mod}")
        lines.append(f"    interface: {iface}")
        lines.append(f"    required: true")
    return '\n'.join(lines)


class TestDiscoverModules(unittest.TestCase):
    """Unit tests for tools/discover.py."""

    def test_flat_only(self):
        with TempProject() as tp:
            tp.add_module('mod-a', _flat_contract('mod-a'))
            tp.add_module('mod-b', _flat_contract('mod-b'))
            found = discover_modules(tp.root)
            self.assertEqual(set(found.keys()), {'mod-a', 'mod-b'})
            self.assertTrue(str(found['mod-a']).endswith('modules/mod-a'))

    def test_domain_only(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'user-auth', _flat_contract('user-auth'))
            found = discover_modules(tp.root)
            self.assertIn('user-auth', found)
            self.assertIn('domains/backend/user-auth', str(found['user-auth']))

    def test_mixed_layout(self):
        with TempProject() as tp:
            tp.add_module('shared', _flat_contract('shared'))
            tp.add_domain_module('backend', 'api', _flat_contract('api'))
            found = discover_modules(tp.root)
            self.assertEqual(set(found.keys()), {'shared', 'api'})

    def test_duplicate_raises(self):
        with TempProject() as tp:
            tp.add_module('dupe', _flat_contract('dupe'))
            tp.add_domain_module('backend', 'dupe', _flat_contract('dupe'))
            with self.assertRaises(ValueError):
                discover_modules(tp.root)

    def test_empty_project(self):
        with TempProject() as tp:
            self.assertEqual(discover_modules(tp.root), {})

    def test_get_module_domain_flat(self):
        with TempProject() as tp:
            d = tp.add_module('mod-a', _flat_contract('mod-a'))
            self.assertIsNone(get_module_domain(tp.root, d))

    def test_get_module_domain_domain(self):
        with TempProject() as tp:
            d = tp.add_domain_module('backend', 'api', _flat_contract('api'))
            self.assertEqual(get_module_domain(tp.root, d), 'backend')

    def test_discover_domains(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', _flat_contract('api'))
            tp.add_gateway('backend',
                'domain: backend\nversion: 1\nexports:\n'
                '  - module: api\n    interfaces: [do_thing]\n')
            tp.add_domain_module('frontend', 'ui', _flat_contract('ui'))
            domains = discover_domains(tp.root)
            self.assertEqual(set(domains.keys()), {'backend', 'frontend'})
            self.assertEqual(domains['backend']['modules'], ['api'])
            self.assertIsNotNone(domains['backend']['gateway'])
            self.assertIsNone(domains['frontend']['gateway'])

    def test_discover_domains_empty(self):
        with TempProject() as tp:
            self.assertEqual(discover_domains(tp.root), {})


def _run_gateway(root, contracts):
    from lint_contracts import check_gateway
    result = LintResult()
    paths = discover_modules(root)
    check_gateway(root, contracts, contracts, paths, result)
    return result


class TestDomainScaling(unittest.TestCase):
    """Integration tests for domain scaling end-to-end."""

    def test_flat_layout_still_works(self):
        with TempProject() as tp:
            tp.add_module('mod-a', _flat_contract('mod-a'))
            contracts = load_all_contracts(tp.root)
            self.assertIn('mod-a', contracts)

    def test_domain_layout_discovered(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'user-auth',
                                 _flat_contract('user-auth'))
            contracts = load_all_contracts(tp.root)
            self.assertIn('user-auth', contracts)

    def test_mixed_layout(self):
        with TempProject() as tp:
            tp.add_module('shared', _flat_contract('shared'))
            tp.add_domain_module('backend', 'api', _flat_contract('api'))
            contracts = load_all_contracts(tp.root)
            self.assertEqual(set(contracts.keys()), {'shared', 'api'})

    def test_duplicate_module_name_rejected(self):
        with TempProject() as tp:
            tp.add_module('dupe', _flat_contract('dupe'))
            tp.add_domain_module('backend', 'dupe', _flat_contract('dupe'))
            with self.assertRaises(ValueError):
                discover_modules(tp.root)

    def test_gateway_exports_unexported_interface_caught(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api',
                                 _flat_contract('api'))
            # Gateway exports only 'do_thing' which exists
            tp.add_gateway('backend',
                'domain: backend\nversion: 1\nexports:\n'
                '  - module: api\n    interfaces: [do_thing]\n')
            # frontend consumes api.secret which is NOT exported
            tp.add_domain_module('frontend', 'ui', _flat_contract(
                'ui', _consume_block([('api', 'secret')])))
            contracts = load_all_contracts(tp.root)
            result = _run_gateway(tp.root, contracts)
            errs = [e for e in result.errors if 'secret' in str(e)]
            self.assertTrue(errs, f"Expected gateway error, got: {result.errors}")

    def test_within_domain_no_gateway_needed(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'a',
                                 _flat_contract('a'))
            tp.add_domain_module('backend', 'b', _flat_contract(
                'b', _consume_block([('a', 'do_thing')])))
            # No GATEWAY.yaml — intra-domain consumption should be fine
            contracts = load_all_contracts(tp.root)
            result = _run_gateway(tp.root, contracts)
            self.assertFalse(result.errors,
                             f"Intra-domain should not error: {result.errors}")

    def test_flat_modules_no_gateway_needed(self):
        with TempProject() as tp:
            tp.add_module('a', _flat_contract('a'))
            tp.add_module('b', _flat_contract(
                'b', _consume_block([('a', 'do_thing')])))
            contracts = load_all_contracts(tp.root)
            result = _run_gateway(tp.root, contracts)
            self.assertFalse(result.errors,
                             f"Flat→flat should not error: {result.errors}")

    def test_cross_domain_no_gateway_at_all_errors(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', _flat_contract('api'))
            # No GATEWAY.yaml in backend
            tp.add_domain_module('frontend', 'ui', _flat_contract(
                'ui', _consume_block([('api', 'do_thing')])))
            contracts = load_all_contracts(tp.root)
            result = _run_gateway(tp.root, contracts)
            errs = [e for e in result.errors if 'GATEWAY' in str(e)]
            self.assertTrue(errs, f"Expected missing-gateway error: {result.errors}")

    def test_flat_to_domain_uses_gateway(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', _flat_contract('api'))
            tp.add_gateway('backend',
                'domain: backend\nversion: 1\nexports:\n'
                '  - module: api\n    interfaces: [do_thing]\n')
            tp.add_module('flat-consumer', _flat_contract(
                'flat-consumer', _consume_block([('api', 'do_thing')])))
            contracts = load_all_contracts(tp.root)
            result = _run_gateway(tp.root, contracts)
            self.assertFalse(result.errors,
                             f"Flat→domain (exported) should pass: {result.errors}")

    def test_gateway_exports_nonexistent_interface(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', _flat_contract('api'))
            tp.add_gateway('backend',
                'domain: backend\nversion: 1\nexports:\n'
                '  - module: api\n    interfaces: [does_not_exist]\n')
            contracts = load_all_contracts(tp.root)
            result = _run_gateway(tp.root, contracts)
            errs = [e for e in result.errors if 'does_not_exist' in str(e)]
            self.assertTrue(errs,
                            f"Expected nonexistent-interface error: {result.errors}")

    def test_gateway_exports_nonexistent_module(self):
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', _flat_contract('api'))
            tp.add_gateway('backend',
                'domain: backend\nversion: 1\nexports:\n'
                '  - module: ghost\n    interfaces: [whatever]\n')
            contracts = load_all_contracts(tp.root)
            result = _run_gateway(tp.root, contracts)
            errs = [e for e in result.errors if 'ghost' in str(e)]
            self.assertTrue(errs, f"Expected missing-module error: {result.errors}")


class TestCrossReferencesEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_cross_references (Check 1)."""

    def test_consumes_nonexistent_module(self):
        """consumes a module that doesn't exist -> error."""
        contracts = {'a': {'consumes': [{'module': 'ghost', 'interface': 'do_thing', 'required': True}]}}
        r = LintResult()
        check_cross_references(contracts, contracts, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_consumes_nonexistent_interface(self):
        """consumes an interface that doesn't exist in target -> error."""
        contracts = {
            'a': {'consumes': [{'module': 'b', 'interface': 'missing_func', 'required': True}]},
            'b': {'provides': [{'id': 'real_func'}]},
        }
        r = LintResult()
        check_cross_references(contracts, contracts, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_valid_cross_reference(self):
        """Valid consumes reference -> no errors."""
        contracts = {
            'a': {'consumes': [{'module': 'b', 'interface': 'do_thing', 'required': True}]},
            'b': {'provides': [{'id': 'do_thing'}]},
        }
        r = LintResult()
        check_cross_references(contracts, contracts, r)
        self.assertTrue(r.ok())

    def test_consumes_entry_missing_interface_field(self):
        """consumes entry without 'interface' key -> error."""
        contracts = {
            'a': {'consumes': [{'module': 'b', 'required': True}]},
            'b': {'provides': [{'id': 'do_thing'}]},
        }
        r = LintResult()
        check_cross_references(contracts, contracts, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_consumes_entry_missing_module_field(self):
        """consumes entry without 'module' key -> error."""
        contracts = {'a': {'consumes': [{'interface': 'do_thing'}]}}
        r = LintResult()
        check_cross_references(contracts, contracts, r)
        self.assertGreaterEqual(len(r.errors), 1)


class TestGraphConsistencyEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_graph_consistency (Check 2)."""

    def test_missing_graph(self):
        """None graph -> error."""
        r = LintResult()
        check_graph_consistency({'a': {'consumes': []}}, {'a': {}}, None, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_module_not_in_graph(self):
        """Module has contract but missing from GRAPH -> error."""
        contracts = {'a': {'consumes': []}}
        graph = {'modules': {}}
        r = LintResult()
        check_graph_consistency(contracts, contracts, graph, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_stale_graph_entry(self):
        """Module in graph but no contract -> warning."""
        contracts = {'a': {'consumes': []}}
        graph = {'modules': {'a': {'consumes': [], 'consumed_by': []}, 'ghost': {'consumes': [], 'consumed_by': []}}}
        r = LintResult()
        check_graph_consistency(contracts, contracts, graph, r)
        self.assertGreaterEqual(len(r.warnings), 1)

    def test_consumes_mismatch(self):
        """Graph says different consumes than contract -> error."""
        contracts = {'a': {'consumes': [{'module': 'b'}]}, 'b': {'consumes': []}}
        graph = {'modules': {'a': {'consumes': [], 'consumed_by': []}, 'b': {'consumes': [], 'consumed_by': []}}}
        r = LintResult()
        check_graph_consistency(contracts, contracts, graph, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_consumed_by_inconsistency(self):
        """consumed_by claims a consumer but consumer doesn't list this module -> error."""
        graph = {'modules': {
            'a': {'consumes': [], 'consumed_by': ['b']},
            'b': {'consumes': [], 'consumed_by': []},
        }}
        r = LintResult()
        check_graph_consistency({'a': {'consumes': []}, 'b': {'consumes': []}},
                                {'a': {}, 'b': {}}, graph, r)
        self.assertGreaterEqual(len(r.errors), 1)


class TestNamingEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_naming_conventions (Check 3)."""

    def test_bad_module_name_uppercase(self):
        """Module name with uppercase -> error."""
        r = LintResult()
        check_naming_conventions({'MyModule': {'provides': []}}, {}, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_bad_module_name_underscore(self):
        """Module name with underscore -> error."""
        r = LintResult()
        check_naming_conventions({'my_module': {'provides': []}}, {}, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_bad_interface_name(self):
        """Interface not snake_case -> error."""
        r = LintResult()
        check_naming_conventions({'good-mod': {'provides': [{'id': 'CamelCase'}]}}, {}, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_bad_error_code(self):
        """Error code not SCREAMING_SNAKE_CASE -> error."""
        r = LintResult()
        check_naming_conventions({'good-mod': {'provides': [{'id': 'do_thing', 'errors': ['lowercase_err']}]}}, {}, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_all_valid_naming(self):
        """All names follow conventions -> no errors."""
        r = LintResult()
        check_naming_conventions({'good-mod': {'provides': [{'id': 'do_thing', 'errors': ['NOT_FOUND']}]}}, {}, r)
        self.assertTrue(r.ok())


class TestManifestEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_manifest_consistency (Check 6)."""

    def test_contract_not_in_manifest(self):
        """Module has contract but missing from MANIFEST -> error."""
        r = LintResult()
        check_manifest_consistency({'mod-a': {}}, {'modules': {}}, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_stale_manifest_entry(self):
        """Module in MANIFEST but no contract -> warning."""
        r = LintResult()
        check_manifest_consistency({'mod-a': {}}, {'modules': {'mod-a': {}, 'ghost': {}}}, r)
        self.assertGreaterEqual(len(r.warnings), 1)

    def test_no_manifest(self):
        """None manifest -> error."""
        r = LintResult()
        check_manifest_consistency({'mod-a': {}}, None, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_manifest_modules_not_dict(self):
        """MANIFEST modules is not a dict -> error."""
        r = LintResult()
        check_manifest_consistency({'mod-a': {}}, {'modules': 'not-a-dict'}, r)
        self.assertGreaterEqual(len(r.errors), 1)


class TestStateEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_state_files (Check 7)."""

    def test_missing_state_file(self):
        """No STATE.yaml -> warning."""
        with TempProject() as tp:
            (tp.root / 'modules' / 'tm').mkdir(parents=True)
            r = LintResult()
            check_state_files(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_invalid_state_status(self):
        """STATE.yaml with bad status -> warning."""
        with TempProject() as tp:
            tp.add_file('modules/tm/STATE.yaml', 'module: tm\nstatus: purple')
            r = LintResult()
            check_state_files(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_missing_state_fields(self):
        """STATE.yaml without 'module' or 'status' -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/STATE.yaml', 'updated: 2026-01-01')
            r = LintResult()
            check_state_files(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_empty_state_file(self):
        """STATE.yaml exists but empty -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/STATE.yaml', '')
            r = LintResult()
            check_state_files(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_valid_state_passes(self):
        """Correct STATE.yaml -> no errors."""
        with TempProject() as tp:
            tp.add_file('modules/tm/STATE.yaml', 'module: tm\nstatus: green')
            r = LintResult()
            check_state_files(tp.root, {'tm': {}}, r)
            self.assertTrue(r.ok())


class TestAssumptionsEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_assumptions (Check 14)."""

    def test_missing_assumptions_file(self):
        """No ASSUMPTIONS.yaml -> warning."""
        with TempProject() as tp:
            (tp.root / 'modules' / 'tm').mkdir(parents=True)
            r = LintResult()
            check_assumptions(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_empty_assumptions_file(self):
        """ASSUMPTIONS.yaml exists but empty -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/ASSUMPTIONS.yaml', '')
            r = LintResult()
            check_assumptions(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_missing_entry_fields(self):
        """Entry missing required field (id/category/content) -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/ASSUMPTIONS.yaml',
                        'module: tm\nassumptions:\n  - category: data')
            r = LintResult()
            check_assumptions(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_duplicate_assumption_id(self):
        """Duplicate assumption IDs -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/ASSUMPTIONS.yaml',
                        'module: tm\nassumptions:\n'
                        '  - id: A1\n    category: data\n    content: "x"\n'
                        '  - id: A1\n    category: retry\n    content: "y"')
            r = LintResult()
            check_assumptions(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_long_content_warning(self):
        """Assumption content > 200 chars -> warning."""
        with TempProject() as tp:
            long_content = 'x' * 201
            tp.add_file('modules/tm/ASSUMPTIONS.yaml',
                        f'module: tm\nassumptions:\n  - id: A1\n    category: data\n    content: "{long_content}"')
            r = LintResult()
            check_assumptions(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_valid_assumptions_passes(self):
        """Well-formed ASSUMPTIONS.yaml -> no errors."""
        with TempProject() as tp:
            tp.add_file('modules/tm/ASSUMPTIONS.yaml',
                        'module: tm\nassumptions:\n  - id: A1\n    category: data\n    content: "uses PostgreSQL"')
            r = LintResult()
            check_assumptions(tp.root, {'tm': {}}, r)
            self.assertTrue(r.ok())


class TestChangelogEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_changelog (Check 15)."""

    def test_missing_changelog(self):
        """No CHANGELOG.yaml -> warning."""
        with TempProject() as tp:
            (tp.root / 'modules' / 'tm').mkdir(parents=True)
            r = LintResult()
            check_changelog(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_empty_changelog(self):
        """CHANGELOG.yaml empty -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/CHANGELOG.yaml', '')
            r = LintResult()
            check_changelog(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_missing_changes_field(self):
        """CHANGELOG.yaml without 'changes' -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/CHANGELOG.yaml', 'module: tm')
            r = LintResult()
            check_changelog(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_changes_not_list(self):
        """CHANGELOG.yaml 'changes' is string not list -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/CHANGELOG.yaml', 'module: tm\nchanges: "not a list"')
            r = LintResult()
            check_changelog(tp.root, {'tm': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_valid_changelog_passes(self):
        """Well-formed CHANGELOG.yaml -> no errors."""
        with TempProject() as tp:
            tp.add_file('modules/tm/CHANGELOG.yaml', 'module: tm\nchanges: []')
            r = LintResult()
            check_changelog(tp.root, {'tm': {}}, r)
            self.assertTrue(r.ok())


class TestManagersEdge(unittest.TestCase):
    """Dedicated trigger/pass tests for check_managers_orchestrator (Check 19)."""

    def test_scope_references_unknown_module(self):
        """SCOPE.yaml owns a module that doesn't exist -> error."""
        with TempProject() as tp:
            tp.add_file('managers/mgr1/SCOPE.yaml', 'manager: mgr1\nowns: [ghost-mod]')
            r = LintResult()
            check_managers_orchestrator(tp.root, {'real-mod': {}}, {'managers': {'mgr1': {'owns': ['ghost-mod']}}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_scope_manifest_mismatch(self):
        """SCOPE.yaml owns list differs from MANIFEST -> error."""
        with TempProject() as tp:
            tp.add_file('managers/mgr1/SCOPE.yaml', 'manager: mgr1\nowns: [mod-a, mod-b]')
            r = LintResult()
            check_managers_orchestrator(tp.root, {'mod-a': {}, 'mod-b': {}},
                                        {'managers': {'mgr1': {'owns': ['mod-a']}}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_plan_references_nonexistent_module(self):
        """Orchestrator PLAN.yaml references missing module -> error."""
        with TempProject() as tp:
            tp.add_file('orchestrator/PLAN.yaml',
                        'phases:\n  - name: phase1\n    modules: [ghost-mod]')
            r = LintResult()
            check_managers_orchestrator(tp.root, {'real-mod': {}}, {}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_scope_name_mismatch(self):
        """SCOPE.yaml manager field doesn't match directory -> error."""
        with TempProject() as tp:
            tp.add_file('managers/mgr1/SCOPE.yaml', 'manager: wrong-name\nowns: []')
            r = LintResult()
            check_managers_orchestrator(tp.root, {}, {'managers': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)


class TestVersionPinning(unittest.TestCase):
    """Dedicated trigger/pass tests for check_version_pinning (Check 21)."""

    def test_missing_pin_warns(self):
        """consumes without contract_version -> warning."""
        contracts = {'a': {'consumes': [{'module': 'b', 'interface': 'do_thing'}]}}
        all_c = {'a': contracts['a'], 'b': {'version': 1, 'provides': [{'id': 'do_thing'}]}}
        r = LintResult()
        check_version_pinning(contracts, all_c, r)
        self.assertGreaterEqual(len(r.warnings), 1)

    def test_correct_pin_passes(self):
        """Pin matches provider version -> no warnings."""
        contracts = {'a': {'consumes': [{'module': 'b', 'interface': 'do_thing', 'contract_version': 1}]}}
        all_c = {'a': contracts['a'], 'b': {'version': 1, 'provides': [{'id': 'do_thing'}]}}
        r = LintResult()
        check_version_pinning(contracts, all_c, r)
        self.assertEqual(len(r.warnings), 0)

    def test_stale_pin_warns(self):
        """Pin doesn't match provider version -> warning."""
        contracts = {'a': {'consumes': [{'module': 'b', 'interface': 'do_thing', 'contract_version': 1}]}}
        all_c = {'a': contracts['a'], 'b': {'version': 2, 'provides': [{'id': 'do_thing'}]}}
        r = LintResult()
        check_version_pinning(contracts, all_c, r)
        self.assertGreaterEqual(len(r.warnings), 1)

    def test_empty_consumes_passes(self):
        """No consumes -> no warnings."""
        r = LintResult()
        check_version_pinning({'a': {'consumes': []}}, {}, r)
        self.assertEqual(len(r.warnings), 0)


class TestStaleRequests(unittest.TestCase):
    """Dedicated trigger/pass tests for check_stale_requests (Check 22)."""

    def test_stale_open_request(self):
        """Open request older than 7 days -> warning."""
        with TempProject() as tp:
            tp.add_file('BUS/requests/r1.yaml',
                        'id: R1\nfrom: a\nto: b\nstatus: open\nrequest: help\n'
                        'created: 2020-01-01T00:00:00Z')
            r = LintResult()
            check_stale_requests(tp.root, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_fresh_request_ok(self):
        """Open request within 7 days -> no warning."""
        with TempProject() as tp:
            tp.add_file('BUS/requests/r1.yaml',
                        'id: R1\nfrom: a\nto: b\nstatus: open\nrequest: help\n'
                        'created: 2099-01-01T00:00:00Z')
            r = LintResult()
            check_stale_requests(tp.root, r)
            self.assertEqual(len(r.warnings), 0)

    def test_resolved_not_flagged(self):
        """Resolved old request -> no warning (only open/acknowledged are checked)."""
        with TempProject() as tp:
            tp.add_file('BUS/requests/r1.yaml',
                        'id: R1\nfrom: a\nto: b\nstatus: resolved\nrequest: help\n'
                        'created: 2020-01-01T00:00:00Z')
            r = LintResult()
            check_stale_requests(tp.root, r)
            self.assertEqual(len(r.warnings), 0)

    def test_stale_acknowledged_request(self):
        """Acknowledged request older than 7 days -> warning."""
        with TempProject() as tp:
            tp.add_file('BUS/requests/r1.yaml',
                        'id: R1\nfrom: a\nto: b\nstatus: acknowledged\nrequest: help\n'
                        'created: 2020-01-01T00:00:00Z')
            r = LintResult()
            check_stale_requests(tp.root, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_no_requests_dir(self):
        """No BUS/requests directory -> no errors or warnings."""
        with TempProject() as tp:
            r = LintResult()
            check_stale_requests(tp.root, r)
            self.assertTrue(r.ok())
            self.assertEqual(len(r.warnings), 0)


class TestSchemaValidation(unittest.TestCase):
    """Dedicated trigger/pass tests for check_schemas (Check 23)."""

    def test_unknown_key_warns(self):
        """CONTRACT.yaml with unknown key -> warning."""
        with TempProject() as tp:
            tp.add_file('modules/tm/CONTRACT.yaml',
                        'module: tm\nversion: 1\nstatus: draft\npurpose: test\n'
                        'provides: []\nbogus_key: hello')
            r = LintResult()
            check_schemas(tp.root, {'tm': {}}, r)
            warns = [w for w in r.warnings if 'bogus_key' in w]
            self.assertGreaterEqual(len(warns), 1)

    def test_wrong_type_warns(self):
        """CONTRACT.yaml version is string instead of int -> warning."""
        with TempProject() as tp:
            tp.add_file('modules/tm/CONTRACT.yaml',
                        'module: tm\nversion: "one"\nstatus: draft\npurpose: test\nprovides: []')
            r = LintResult()
            check_schemas(tp.root, {'tm': {}}, r)
            warns = [w for w in r.warnings if 'version' in w and 'int' in w]
            self.assertGreaterEqual(len(warns), 1)

    def test_valid_schema_passes(self):
        """Well-formed CONTRACT.yaml -> no schema warnings."""
        with TempProject() as tp:
            tp.add_file('modules/tm/CONTRACT.yaml',
                        'module: tm\nversion: 1\nstatus: draft\npurpose: test\nprovides: []')
            r = LintResult()
            check_schemas(tp.root, {'tm': {}}, r)
            schema_warns = [w for w in r.warnings if 'unknown key' in w or 'should be' in w]
            self.assertEqual(len(schema_warns), 0)

    def test_state_unknown_key_warns(self):
        """STATE.yaml with unknown key -> warning."""
        with TempProject() as tp:
            tp.add_file('modules/tm/STATE.yaml',
                        'module: tm\nstatus: green\nfoo_bar: baz')
            r = LintResult()
            check_schemas(tp.root, {'tm': {}}, r)
            warns = [w for w in r.warnings if 'foo_bar' in w]
            self.assertGreaterEqual(len(warns), 1)

    def test_memory_unknown_key_warns(self):
        """MEMORY.yaml with unknown key -> warning."""
        with TempProject() as tp:
            tp.add_file('modules/tm/MEMORY.yaml',
                        'module: tm\nentries: []\nwhatever: 42')
            r = LintResult()
            check_schemas(tp.root, {'tm': {}}, r)
            warns = [w for w in r.warnings if 'whatever' in w]
            self.assertGreaterEqual(len(warns), 1)


class TestMalformedInput(unittest.TestCase):
    """Edge case tests for malformed or empty inputs."""

    def test_malformed_yaml_parse(self):
        """Malformed YAML returns parse error dict."""
        result = parse_yaml_file('/nonexistent/path/file.yaml')
        self.assertIsNone(result)

    def test_empty_provides_structure(self):
        """Contract with provides: [] passes structure check (just warns no invariants)."""
        r = LintResult()
        check_contract_structure({'tm': {'module': 'tm', 'version': 1, 'status': 'draft',
                                          'purpose': 'test', 'provides': []}}, r)
        self.assertTrue(r.ok())

    def test_consumes_not_list_ignored(self):
        """consumes as string instead of list -> cross-ref check skips gracefully."""
        r = LintResult()
        check_cross_references({'a': {'consumes': 'not-a-list'}}, {'a': {}}, r)
        self.assertTrue(r.ok())

    def test_provides_entry_not_dict(self):
        """provides entry that is a string not dict -> error."""
        r = LintResult()
        check_contract_structure({'tm': {'module': 'tm', 'version': 1, 'status': 'draft',
                                          'purpose': 'test', 'provides': ['just-a-string']}}, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_none_conventions_for_naming(self):
        """None conventions for naming check -> no crash."""
        r = LintResult()
        check_naming_conventions({'good-mod': {'provides': [{'id': 'do_thing', 'errors': ['ERR']}]}}, None, r)
        self.assertTrue(r.ok())

    def test_none_conventions_for_granularity(self):
        """None conventions for granularity -> uses defaults, no crash."""
        r = LintResult()
        check_granularity({'m': {'provides': [{'id': f'f{i}'} for i in range(5)], 'status': 'stable'}}, None, r)
        self.assertTrue(r.ok())

    def test_none_conventions_for_memory(self):
        """None conventions for memory check -> uses defaults, no crash."""
        with TempProject() as tp:
            tp.add_file('modules/tm/MEMORY.yaml', 'module: tm\nentries: []')
            r = LintResult()
            check_memory_files(tp.root, {'tm': {}}, None, r)
            self.assertTrue(r.ok())


class TestContractStructureExtra(unittest.TestCase):
    """Additional edge cases for check_contract_structure (Check 5)."""

    def test_invalid_status_warns(self):
        """Unknown status value -> warning."""
        r = LintResult()
        check_contract_structure({'m': {'module': 'm', 'version': 1, 'status': 'banana',
                                        'purpose': 'test', 'provides': []}}, r)
        self.assertGreaterEqual(len(r.warnings), 1)

    def test_module_name_mismatch(self):
        """module field doesn't match directory name -> error."""
        r = LintResult()
        check_contract_structure({'dir-name': {'module': 'wrong-name', 'version': 1,
                                                'status': 'draft', 'purpose': 'test',
                                                'provides': []}}, r)
        self.assertGreaterEqual(len(r.errors), 1)

    def test_duplicate_interface_id(self):
        """Two interfaces with same id -> error."""
        r = LintResult()
        check_contract_structure({'m': {'module': 'm', 'version': 1, 'status': 'draft',
                                        'purpose': 'test',
                                        'provides': [
                                            {'id': 'do_thing', 'input': {}, 'output': {}},
                                            {'id': 'do_thing', 'input': {}, 'output': {}},
                                        ]}}, r)
        errs = [e for e in r.errors if 'Duplicate' in e]
        self.assertGreaterEqual(len(errs), 1)

    def test_missing_interface_field(self):
        """Interface missing 'input' -> error."""
        r = LintResult()
        check_contract_structure({'m': {'module': 'm', 'version': 1, 'status': 'draft',
                                        'purpose': 'test',
                                        'provides': [{'id': 'func', 'output': {}}]}}, r)
        errs = [e for e in r.errors if 'input' in e]
        self.assertGreaterEqual(len(errs), 1)


class TestDomainModuleChecks(unittest.TestCase):
    """Verify per-module checks work with domain layout (domains/<domain>/<module>)."""

    def test_state_check_finds_domain_module(self):
        """check_state_files works for modules under domains/."""
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', 'module: api')
            tp.add_file('domains/backend/api/STATE.yaml', 'module: api\nstatus: green')
            paths = discover_modules(tp.root)
            r = LintResult()
            check_state_files(tp.root, {'api': {}}, r, module_paths=paths)
            self.assertTrue(r.ok())

    def test_memory_check_finds_domain_module(self):
        """check_memory_files works for modules under domains/."""
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', 'module: api')
            tp.add_file('domains/backend/api/MEMORY.yaml', 'module: api\nentries: []')
            paths = discover_modules(tp.root)
            r = LintResult()
            check_memory_files(tp.root, {'api': {}}, {}, r, module_paths=paths)
            self.assertTrue(r.ok())

    def test_tests_check_finds_domain_module(self):
        """check_test_files works for modules under domains/."""
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', 'module: api')
            tp.add_file('domains/backend/api/TESTS.yaml',
                        'module: api\ntests:\n  - interface: do_thing\n    case: basic\n    expect: {}')
            paths = discover_modules(tp.root)
            r = LintResult()
            check_test_files(tp.root, {'api': {'provides': [{'id': 'do_thing'}]}}, r, module_paths=paths)
            self.assertTrue(r.ok())

    def test_assumptions_check_finds_domain_module(self):
        """check_assumptions works for modules under domains/."""
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', 'module: api')
            tp.add_file('domains/backend/api/ASSUMPTIONS.yaml',
                        'module: api\nassumptions:\n  - id: A1\n    category: data\n    content: "uses postgres"')
            paths = discover_modules(tp.root)
            r = LintResult()
            check_assumptions(tp.root, {'api': {}}, r, module_paths=paths)
            self.assertTrue(r.ok())

    def test_changelog_check_finds_domain_module(self):
        """check_changelog works for modules under domains/."""
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', 'module: api')
            tp.add_file('domains/backend/api/CHANGELOG.yaml', 'module: api\nchanges: []')
            paths = discover_modules(tp.root)
            r = LintResult()
            check_changelog(tp.root, {'api': {}}, r, module_paths=paths)
            self.assertTrue(r.ok())

    def test_replacement_check_finds_domain_module(self):
        """check_replacement_ready works for modules under domains/."""
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api', 'module: api')
            for f in ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml',
                       'CHANGELOG.yaml', 'TESTS.yaml', 'ASSUMPTIONS.yaml']:
                tp.add_file(f'domains/backend/api/{f}', 'module: api')
            paths = discover_modules(tp.root)
            r = LintResult()
            check_replacement_ready(tp.root, {'api': {'status': 'stable'}}, r, module_paths=paths)
            self.assertEqual(len(r.warnings), 0)


class TestBusEdgeCases(unittest.TestCase):
    """Edge cases for BUS validation (Check 17)."""

    def test_invalid_delta_type(self):
        """Delta with unknown type -> error."""
        with TempProject() as tp:
            tp.add_file('BUS/deltas/d.yaml',
                        'source: mod-a\ntimestamp: 2026-01-01T00:00:00Z\ntype: unknown_type')
            tp.add_file('BUS/requests/.gitkeep', '')
            r = LintResult()
            check_bus(tp.root, {'mod-a': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_request_missing_required_fields(self):
        """Request missing required fields -> errors."""
        with TempProject() as tp:
            tp.add_file('BUS/deltas/.gitkeep', '')
            tp.add_file('BUS/requests/r1.yaml', 'id: R1')
            r = LintResult()
            check_bus(tp.root, {}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_invalid_request_status(self):
        """Request with unknown status -> error."""
        with TempProject() as tp:
            tp.add_file('BUS/deltas/.gitkeep', '')
            tp.add_file('BUS/requests/r1.yaml',
                        'id: R1\nfrom: a\nto: b\nstatus: magic\nrequest: stuff')
            r = LintResult()
            check_bus(tp.root, {'a': {}, 'b': {}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_no_bus_dir_passes(self):
        """No BUS directory at all -> no errors."""
        with TempProject() as tp:
            r = LintResult()
            check_bus(tp.root, {'mod-a': {}}, r)
            self.assertTrue(r.ok())


class TestMemoryEdgeCases(unittest.TestCase):
    """Additional edge cases for check_memory_files (Check 8)."""

    def test_entry_not_dict(self):
        """MEMORY.yaml entry is string not dict -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/MEMORY.yaml',
                        'module: tm\nentries:\n  - "just a string"')
            r = LintResult()
            check_memory_files(tp.root, {'tm': {}},
                               {'memory': {'max_entries': 20, 'max_content_chars': 100,
                                           'valid_types': ['decision']}}, r)
            self.assertGreaterEqual(len(r.errors), 1)

    def test_invalid_entry_type(self):
        """MEMORY.yaml entry with unknown type -> warning."""
        with TempProject() as tp:
            tp.add_file('modules/tm/MEMORY.yaml',
                        'module: tm\nentries:\n  - type: banana\n    content: "ok"')
            r = LintResult()
            check_memory_files(tp.root, {'tm': {}},
                               {'memory': {'max_entries': 20, 'max_content_chars': 100,
                                           'valid_types': ['decision']}}, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_content_too_long(self):
        """MEMORY.yaml entry content > max_content_chars -> warning."""
        with TempProject() as tp:
            long_content = 'x' * 101
            tp.add_file('modules/tm/MEMORY.yaml',
                        f'module: tm\nentries:\n  - type: decision\n    content: "{long_content}"')
            r = LintResult()
            check_memory_files(tp.root, {'tm': {}},
                               {'memory': {'max_entries': 20, 'max_content_chars': 100,
                                           'valid_types': ['decision']}}, r)
            self.assertGreaterEqual(len(r.warnings), 1)

    def test_module_name_mismatch(self):
        """MEMORY.yaml module field doesn't match dir -> error."""
        with TempProject() as tp:
            tp.add_file('modules/tm/MEMORY.yaml', 'module: wrong-name\nentries: []')
            r = LintResult()
            check_memory_files(tp.root, {'tm': {}}, {}, r)
            self.assertGreaterEqual(len(r.errors), 1)


if __name__ == '__main__':
    unittest.main()
