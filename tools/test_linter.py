#!/usr/bin/env python3
"""ANMA Linter Test Suite.

Regression tests for all 20 linter checks, the YAML parser,
and CLI behavior. Run with: python3 test_linter.py

Zero external dependencies — uses only stdlib unittest.
"""

import os
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
)

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

    def _run_check(self, fn, *args):
        r = LintResult()
        fn(*args, r)
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
        r = self._run_check(check_state_files, self.root, self.contracts)
        self.assertTrue(r.ok())

    def test_memory(self):
        r = self._run_check(check_memory_files, self.root, self.contracts, self.conv)
        self.assertTrue(r.ok())

    def test_granularity(self):
        r = self._run_check(check_granularity, self.contracts, self.conv)
        self.assertTrue(r.ok())

    def test_tests(self):
        r = self._run_check(check_test_files, self.root, self.contracts)
        self.assertTrue(r.ok())

    def test_budget(self):
        r = self._run_check(check_context_budget, self.root, self.contracts, self.conv)
        self.assertTrue(r.ok())

    def test_conventions_version(self):
        r = self._run_check(check_conventions_version, self.conv)
        self.assertTrue(r.ok())

    def test_module_types(self):
        r = self._run_check(check_module_types, self.contracts, self.conv)
        self.assertTrue(r.ok())

    def test_assumptions(self):
        r = self._run_check(check_assumptions, self.root, self.contracts)
        self.assertTrue(r.ok())

    def test_changelog(self):
        r = self._run_check(check_changelog, self.root, self.contracts)
        self.assertTrue(r.ok())

    def test_replacement(self):
        r = self._run_check(check_replacement_ready, self.root, self.contracts)
        self.assertTrue(r.ok())

    def test_bus(self):
        r = self._run_check(check_bus, self.root, self.contracts)
        self.assertTrue(r.ok())

    def test_assumption_compat(self):
        r = self._run_check(check_assumption_compatibility, self.root, self.contracts)
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
        import shutil
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
        import shutil
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


if __name__ == '__main__':
    unittest.main()
