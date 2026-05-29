#!/usr/bin/env python3
"""Regression tests for confirmed bugs from the 2026-05-28 bug hunt.

Each test reproduces the exact failure from the bug report to prevent
regressions. Run with: python3 -m unittest tools.test_bug_regressions
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_contracts import parse_yaml_file, parse_yaml
from claims import _save_claims, _load_claims

TOOLS_DIR = Path(__file__).parent


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

    def add_file(self, relpath, content):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def setup_conventions(self, version=3):
        self.add_file('CONVENTIONS.yaml',
            f"conventions_version: {version}\n"
            "naming:\n  modules: kebab-case\n  interfaces: snake_case\n"
            "  errors: SCREAMING_SNAKE_CASE\n"
            "token_thresholds:\n  contract_max: 500\n  recovery_max: 800\n")

    def setup_manifest(self, project='test', modules=None, managers=None):
        lines = [f"project: {project}", "version: 1", "", "modules:"]
        for name, status in (modules or {}).items():
            lines.append(f"  {name}: {{ status: {status} }}")
        lines.append("")
        lines.append("managers:")
        if managers:
            for name, owns in managers.items():
                owns_str = ', '.join(owns)
                lines.append(f"  {name}: {{ owns: [{owns_str}] }}")
        else:
            lines.append("  {}")
        lines.append("")
        lines.append("orchestrator: active")
        self.add_file('MANIFEST.yaml', '\n'.join(lines) + '\n')

    def setup_graph(self, modules=None):
        lines = ["version: 1", "", "modules:"]
        for name, data in (modules or {}).items():
            consumes = data.get('consumes', [])
            consumed_by = data.get('consumed_by', [])
            c = ', '.join(consumes) if consumes else ''
            cb = ', '.join(consumed_by) if consumed_by else ''
            lines.append(f"  {name}:")
            lines.append(f"    consumes: [{c}]")
            lines.append(f"    consumed_by: [{cb}]")
        self.add_file('GRAPH.yaml', '\n'.join(lines) + '\n')


MINIMAL_CONTRACT = (
    "module: {name}\nversion: 1\nstatus: draft\ntype: regular\n"
    'purpose: "test"\nprovides:\n'
    "  - id: get_item\n    input: {{ id: uuid }}\n    output: {{ data: object }}\n"
    "    errors: [NOT_FOUND]\n    invariants: []\nconsumes: []\n"
)


# ---------------------------------------------------------------------------
# BUG-001: gen_tests.py --append destroys existing tests
# ---------------------------------------------------------------------------

class TestBug001AppendPreservesExisting(unittest.TestCase):

    def test_append_merges_with_existing_tests(self):
        """--append must keep existing tests and add new ones."""
        from gen_tests import generate_tests, format_tests_yaml
        with TempProject() as tp:
            contract = (
                "module: svc\nversion: 1\nstatus: draft\ntype: regular\n"
                'purpose: "test"\nprovides:\n'
                "  - id: alpha\n    input: { x: string }\n    output: { y: string }\n"
                "    errors: []\n"
                "  - id: beta\n    input: { x: string }\n    output: { y: string }\n"
                "    errors: []\n"
                "  - id: gamma\n    input: { x: string }\n    output: { y: string }\n"
                "    errors: []\n"
                "consumes: []\n"
            )
            mod_dir = tp.add_module('svc', contract)

            initial_tests = generate_tests(tp.root, 'svc')
            initial_content = format_tests_yaml('svc', initial_tests)
            tests_path = mod_dir / 'TESTS.yaml'
            tests_path.write_text(initial_content)
            initial_count = len(initial_tests)
            self.assertEqual(initial_count, 3)

            contract2 = contract.replace(
                "consumes: []",
                "  - id: delta\n    input: { x: string }\n    output: { y: string }\n"
                "    errors: []\nconsumes: []"
            )
            (mod_dir / 'CONTRACT.yaml').write_text(contract2)

            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'gen_tests.py'), 'svc',
                 '--append', '--output', str(tests_path), '--path', str(tp.root)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)

            final = parse_yaml_file(str(tests_path))
            final_tests = final.get('tests', [])
            self.assertEqual(len(final_tests), 4,
                             f"Expected 3 original + 1 new = 4, got {len(final_tests)}")
            ifaces = [t['interface'] for t in final_tests if isinstance(t, dict)]
            self.assertIn('alpha', ifaces)
            self.assertIn('delta', ifaces)


# ---------------------------------------------------------------------------
# BUG-002: claims.py unquoted YAML values cause corruption
# ---------------------------------------------------------------------------

class TestBug002ClaimsQuoting(unittest.TestCase):

    def test_special_chars_in_by_field(self):
        """Claims with YAML-special characters must round-trip correctly."""

        with TempProject() as tp:
            claims = {
                'test-mod': {
                    'by': 'agent: admin',
                    'branch': 'feature/my-branch',
                    'since': '2026-01-01T00:00:00Z',
                }
            }
            _save_claims(tp.root, claims)
            loaded = _load_claims(tp.root)
            self.assertIn('test-mod', loaded)
            self.assertEqual(loaded['test-mod']['by'], 'agent: admin')

    def test_yaml_boolean_word_in_by(self):
        """Claim by 'yes' must stay as string, not become boolean True."""

        with TempProject() as tp:
            claims = {'mod': {'by': 'yes', 'branch': 'main', 'since': '2026-01-01T00:00:00Z'}}
            _save_claims(tp.root, claims)
            loaded = _load_claims(tp.root)
            self.assertEqual(loaded['mod']['by'], 'yes')
            self.assertIsInstance(loaded['mod']['by'], str)


# ---------------------------------------------------------------------------
# BUG-003: rename_project.py unbounded str.replace
# ---------------------------------------------------------------------------

class TestBug003RenameWordBoundary(unittest.TestCase):

    def test_no_substring_replacement(self):
        """Renaming 'app' to 'platform' must not affect module 'app-auth'."""
        with TempProject() as tp:
            tp.add_file('MANIFEST.yaml',
                "project: app\nversion: 1\n\nmodules:\n  app-auth: { status: draft }\n\n"
                "managers: {}\n\norchestrator: active\n")
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'rename_project.py'), 'platform'],
                capture_output=True, text=True, cwd=str(tp.root))
            content = (tp.root / 'MANIFEST.yaml').read_text()
            self.assertIn('project: platform', content)
            self.assertIn('app-auth', content,
                           "Module name 'app-auth' was corrupted by substring replace")
            self.assertNotIn('platform-auth', content)


# ---------------------------------------------------------------------------
# BUG-004: contract_diff.py silently drops consumes changes
# ---------------------------------------------------------------------------

class TestBug004ConsumesDeltasGenerated(unittest.TestCase):

    def test_consumes_only_change_produces_deltas(self):
        """Changes only in consumes section must generate delta entries."""
        from contract_diff import generate_deltas
        with TempProject() as tp:
            tp.setup_manifest()
            tp.setup_graph()
            old = {
                'version': 1,
                'provides': [{'id': 'get', 'input': {}, 'output': {}, 'errors': []}],
                'consumes': [],
            }
            new = {
                'version': 1,
                'provides': [{'id': 'get', 'input': {}, 'output': {}, 'errors': []}],
                'consumes': [{'module': 'other', 'interface': 'fetch'}],
            }
            summary, deltas = generate_deltas('test-mod', old, new, tp.root)
            self.assertIsNotNone(summary, "consumes-only change returned None summary")
            self.assertGreater(len(deltas), 0, "No deltas generated for consumes change")
            self.assertGreater(summary.get('deps_added', 0), 0)


# ---------------------------------------------------------------------------
# BUG-005: plan_migration.py wrong version pin for transitive consumers
# ---------------------------------------------------------------------------

class TestBug005TransitivePinCorrectness(unittest.TestCase):

    def test_transitive_consumer_has_no_direct_pin(self):
        """Transitive consumers must NOT show the intermediate module's pin."""
        from plan_migration import build_migration_plan
        with TempProject() as tp:
            tp.add_module('mod-a', MINIMAL_CONTRACT.format(name='mod-a'))
            tp.add_module('mod-b',
                "module: mod-b\nversion: 1\nstatus: draft\ntype: regular\n"
                'purpose: "test"\nprovides:\n'
                "  - id: do_thing\n    input: {}\n    output: {}\n    errors: []\n"
                "consumes:\n  - module: mod-a\n    interface: get_item\n"
                "    required: true\n    contract_version: 1\n")
            tp.add_module('mod-c',
                "module: mod-c\nversion: 1\nstatus: draft\ntype: regular\n"
                'purpose: "test"\nprovides: []\n'
                "consumes:\n  - module: mod-b\n    interface: do_thing\n"
                "    required: true\n    contract_version: 3\n")
            tp.setup_manifest(modules={'mod-a': 'draft', 'mod-b': 'draft', 'mod-c': 'draft'})
            tp.setup_graph(modules={
                'mod-a': {'consumed_by': ['mod-b']},
                'mod-b': {'consumes': ['mod-a'], 'consumed_by': ['mod-c']},
                'mod-c': {'consumes': ['mod-b']},
            })
            plan, err = build_migration_plan(tp.root, 'mod-a', 2)
            self.assertIsNone(err)
            transitive = plan.get('transitive_consumers', [])
            for c in transitive:
                if c['module'] == 'mod-c':
                    self.assertIsNone(c['pinned_version'],
                        f"Transitive consumer mod-c should have pinned_version=None, "
                        f"got {c['pinned_version']}")


# ---------------------------------------------------------------------------
# BUG-006: new_module.py command injection via os.system
# ---------------------------------------------------------------------------

class TestBug006NoOsSystem(unittest.TestCase):

    def test_no_os_system_calls(self):
        """new_module.py must not use os.system (command injection risk)."""
        source = (TOOLS_DIR / 'new_module.py').read_text()
        self.assertNotIn('os.system(', source,
                          "os.system found in new_module.py — use subprocess.run instead")


# ---------------------------------------------------------------------------
# BUG-007: sync_all.py drops list-format manager ownership
# ---------------------------------------------------------------------------

class TestBug007ListFormatManagers(unittest.TestCase):

    def test_list_format_managers_preserved(self):
        """Managers stored as lists must be preserved after sync_all rebuild."""
        with TempProject() as tp:
            tp.setup_conventions()
            tp.add_module('mod-a', MINIMAL_CONTRACT.format(name='mod-a'))
            tp.add_module('mod-b', MINIMAL_CONTRACT.format(name='mod-b'))
            tp.add_file('MANIFEST.yaml',
                "project: test\nversion: 1\n\nmodules:\n"
                "  mod-a: { status: draft }\n  mod-b: { status: draft }\n\n"
                "managers:\n  my-mgr: [mod-a, mod-b]\n\norchestrator: active\n")
            tp.setup_graph(modules={
                'mod-a': {}, 'mod-b': {},
            })
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'sync_all.py'), '--path', str(tp.root)],
                capture_output=True, text=True)
            manifest = parse_yaml_file(str(tp.root / 'MANIFEST.yaml'))
            mgr = manifest.get('managers', {}).get('my-mgr', {})
            if isinstance(mgr, dict):
                owns = mgr.get('owns', [])
            elif isinstance(mgr, list):
                owns = mgr
            else:
                owns = []
            self.assertIn('mod-a', owns,
                          f"mod-a lost from manager after sync. Manager data: {mgr}")
            self.assertIn('mod-b', owns,
                          f"mod-b lost from manager after sync. Manager data: {mgr}")


# ---------------------------------------------------------------------------
# BUG-008: verify_contract.py silent failure on malformed YAML
# ---------------------------------------------------------------------------

class TestBug008MalformedTestsYaml(unittest.TestCase):

    def test_malformed_tests_yaml_exits_nonzero(self):
        """verify_contract.py must fail loudly on malformed TESTS.yaml."""
        with TempProject() as tp:
            mod_dir = tp.add_module('bad-mod', MINIMAL_CONTRACT.format(name='bad-mod'))
            (mod_dir / 'TESTS.yaml').write_text("{{{{invalid yaml::::")
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'verify_contract.py'),
                 'bad-mod', '--plan', '--path', str(tp.root)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0,
                                "verify_contract.py should exit non-zero on malformed TESTS.yaml")


# ---------------------------------------------------------------------------
# BUG-009: remove_module.py substring BUS matching
# ---------------------------------------------------------------------------

class TestBug009ExactBusMatching(unittest.TestCase):

    def test_bus_cleanup_uses_exact_match(self):
        """Removing 'auth' must not delete BUS files for 'user-auth'."""
        from remove_module import clean_bus
        with TempProject() as tp:
            tp.add_file('BUS/deltas/user-auth-delta.yaml',
                "source: user-auth\ntimestamp: 2026-01-01\ntype: interface_added\n")
            tp.add_file('BUS/deltas/auth-delta.yaml',
                "source: auth\ntimestamp: 2026-01-01\ntype: interface_added\n")
            clean_bus(tp.root, 'auth')
            self.assertTrue((tp.root / 'BUS/deltas/user-auth-delta.yaml').exists(),
                            "BUS file for user-auth was incorrectly deleted when removing auth")
            self.assertFalse((tp.root / 'BUS/deltas/auth-delta.yaml').exists(),
                             "BUS file for auth should have been deleted")


# ---------------------------------------------------------------------------
# BUG-010: check_conventions_pin.py iterates all_contracts
# ---------------------------------------------------------------------------

class TestBug010FilteredLintScope(unittest.TestCase):

    def test_plugin_respects_module_filter(self):
        """check_conventions_pin must only report for filtered modules."""
        from checks.check_conventions_pin import run
        with TempProject() as tp:
            tp.setup_conventions(version=3)
            filtered = {'target': {'conventions_version': 2}}
            all_c = {
                'target': {'conventions_version': 2},
                'other': {'conventions_version': 1},
            }
            conv = {'conventions_version': 3}

            result = type('R', (), {
                'warnings': [],
                'warning': lambda self, mod, msg: self.warnings.append((mod, msg)),
            })()

            run(tp.root, filtered, all_c, conv, None, result)
            warned_mods = [w[0] for w in result.warnings]
            self.assertIn('target', warned_mods)
            self.assertNotIn('other', warned_mods,
                             "Plugin reported warnings for 'other' which was not in filtered set")


# ---------------------------------------------------------------------------
# BUG-011: check_principles.py crash on None token_thresholds
# ---------------------------------------------------------------------------

class TestBug011NoneTokenThresholds(unittest.TestCase):

    def test_p2_handles_none_token_thresholds(self):
        """P2 check must not crash when token_thresholds is None."""
        from checks.check_principles import check_p2_tokens_are_bottleneck

        result = type('R', (), {
            'warnings': [],
            'warning': lambda self, mod, msg: self.warnings.append((mod, msg)),
        })()

        conventions = {'token_thresholds': None}
        try:
            check_p2_tokens_are_bottleneck(
                Path('/nonexistent'), {}, result, conventions=conventions)
        except AttributeError:
            self.fail("check_p2 crashed on None token_thresholds")

    def test_p6_handles_none_token_thresholds(self):
        """P6 check must not crash when token_thresholds is None."""
        from checks.check_principles import check_p6_recovery_is_cheap

        result = type('R', (), {
            'warnings': [],
            'warning': lambda self, mod, msg: self.warnings.append((mod, msg)),
        })()

        conventions = {'token_thresholds': None}
        try:
            check_p6_recovery_is_cheap(
                Path('/nonexistent'), {}, result, conventions=conventions)
        except AttributeError:
            self.fail("check_p6 crashed on None token_thresholds")


# ---------------------------------------------------------------------------
# BUG-012: gen_claude_md.py hardcodes modules/ path for domain modules
# ---------------------------------------------------------------------------

class TestBug012DomainModulePaths(unittest.TestCase):

    def test_domain_module_uses_correct_path(self):
        """Generated CLAUDE.md must use domains/ path, not modules/."""
        from gen_claude_md import generate_module_claude_md
        with TempProject() as tp:
            tp.add_domain_module('backend', 'api',
                "module: api\nversion: 1\nstatus: draft\ntype: regular\n"
                'purpose: "test"\nprovides: []\nconsumes: []\n')
            tp.setup_conventions()
            tp.setup_manifest(modules={'api': 'draft'})
            tp.setup_graph(modules={'api': {}})
            content = generate_module_claude_md(tp.root, 'api')
            self.assertIn('domains/backend/api/CONTRACT.yaml', content,
                          "Domain module CLAUDE.md should reference domains/ path")
            self.assertNotIn('modules/api/CONTRACT.yaml', content,
                             "Domain module CLAUDE.md incorrectly uses modules/ path")


# ---------------------------------------------------------------------------
# BUG-013: import_contracts.py shows stdout instead of stderr
# ---------------------------------------------------------------------------

class TestBug013StderrOnFailure(unittest.TestCase):

    def test_source_uses_stderr_or_stdout(self):
        """import_contracts.py must prefer stderr over stdout for error display."""
        source = (TOOLS_DIR / 'import_contracts.py').read_text()
        self.assertIn('result.stderr or result.stdout', source,
                       "import_contracts.py should prefer stderr for error output")
        self.assertNotIn("result.stdout[-500:]", source,
                          "import_contracts.py still uses only stdout for errors")


# ---------------------------------------------------------------------------
# BUG-014: sync_all.py stub TESTS.yaml prevents regeneration
# ---------------------------------------------------------------------------

class TestBug014StubRegeneration(unittest.TestCase):

    def test_deleted_tests_yaml_regenerated(self):
        """Deleted TESTS.yaml must be regenerated even if contract hash matches."""
        with TempProject() as tp:
            tp.setup_conventions()
            contract = MINIMAL_CONTRACT.format(name='svc')
            mod_dir = tp.add_module('svc', contract)
            tp.setup_manifest(modules={'svc': 'draft'})
            tp.setup_graph(modules={'svc': {}})

            result1 = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'sync_all.py'), '--path', str(tp.root)],
                capture_output=True, text=True)
            tests_path = mod_dir / 'TESTS.yaml'
            self.assertTrue(tests_path.exists())
            original = parse_yaml_file(str(tests_path))
            original_tests = original.get('tests', []) if original else []

            if not original_tests:
                return

            tests_path.unlink()

            result2 = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'sync_all.py'), '--path', str(tp.root)],
                capture_output=True, text=True)
            self.assertTrue(tests_path.exists(), "TESTS.yaml was not recreated")
            regenerated = parse_yaml_file(str(tests_path))
            regen_tests = regenerated.get('tests', []) if regenerated else []
            self.assertGreater(len(regen_tests), 0,
                               "Regenerated TESTS.yaml is empty stub instead of proper tests")


# ---------------------------------------------------------------------------
# BUG-015: gen_contract.py purpose with quotes breaks YAML
# ---------------------------------------------------------------------------

class TestBug015PurposeQuoteEscaping(unittest.TestCase):

    def test_purpose_with_double_quotes(self):
        """Purpose containing double quotes must produce valid YAML."""
        from gen_contract import generate_contract
        content, _ = generate_contract(
            'test-mod', 'Handle "auth" flows', [], 'regular')
        parsed = parse_yaml(content)
        self.assertIsNotNone(parsed, "Generated contract is not valid YAML")
        self.assertIn('auth', parsed.get('purpose', ''))


# ---------------------------------------------------------------------------
# BUG-016: yaml_editor.py scope_add_module fails silently
# ---------------------------------------------------------------------------

class TestBug016ScopeAddWithoutOwnsLine(unittest.TestCase):

    def test_add_module_to_scope_without_owns_line(self):
        """scope_add_module must work even if SCOPE.yaml has no owns: line."""
        from yaml_editor import scope_add_module
        with TempProject() as tp:
            tp.add_file('managers/mgr/SCOPE.yaml',
                "manager: mgr\nresponsibilities:\n  - manage stuff\n")
            result = scope_add_module(tp.root, 'mgr', 'new-mod')
            self.assertTrue(result)
            content = (tp.root / 'managers/mgr/SCOPE.yaml').read_text()
            self.assertIn('new-mod', content,
                          "Module was not actually added to SCOPE.yaml")


# ---------------------------------------------------------------------------
# BUG-017: new_manager.py no rollback on MANIFEST failure
# ---------------------------------------------------------------------------

class TestBug017ManagerRollbackOnFailure(unittest.TestCase):

    def test_duplicate_manager_exits_nonzero(self):
        """Creating a duplicate manager must exit non-zero and not leave orphan dir."""
        with TempProject() as tp:
            tp.setup_manifest(managers={'existing-mgr': []})
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'new_manager.py'), 'existing-mgr'],
                capture_output=True, text=True, cwd=str(tp.root))
            self.assertNotEqual(result.returncode, 0,
                                "new_manager.py should exit non-zero on duplicate manager")
            mgr_dir = tp.root / 'managers' / 'existing-mgr'
            self.assertFalse(mgr_dir.exists(),
                             "Orphan manager directory should be cleaned up on failure")


# ---------------------------------------------------------------------------
# SEC-001: import_contracts.py path traversal via malicious module: field
# ---------------------------------------------------------------------------

class TestSec001ImportPathTraversal(unittest.TestCase):

    def test_traversal_in_yaml_module_field_rejected(self):
        """A CONTRACT.yaml with module: '../../tmp/evil' must be rejected."""
        from import_contracts import import_contract
        with TempProject() as tp:
            tp.setup_conventions()
            tp.setup_manifest()
            malicious = tp.add_file('evil.yaml',
                'module: "../../tmp/evil"\nversion: 1\nstatus: draft\n'
                'type: regular\npurpose: "pwn"\nprovides: []\nconsumes: []\n')
            result = import_contract(malicious, tp.root)
            self.assertFalse(result, "Import should reject traversal in module name")
            self.assertFalse((tp.root / '../../tmp/evil').exists())

    def test_traversal_in_domain_arg_rejected(self):
        """--domain with '../' must be rejected."""
        from import_contracts import import_contract
        with TempProject() as tp:
            tp.setup_conventions()
            tp.setup_manifest()
            contract = tp.add_file('my-mod-CONTRACT.yaml',
                'module: my-mod\nversion: 1\nstatus: draft\n'
                'type: regular\npurpose: "test"\nprovides: []\nconsumes: []\n')
            result = import_contract(contract, tp.root, domain='../../tmp/evil')
            self.assertFalse(result, "Import should reject traversal in domain")

    def test_valid_kebab_module_accepted(self):
        """A valid kebab-case module name must still be accepted."""
        from import_contracts import import_contract
        with TempProject() as tp:
            tp.setup_conventions()
            tp.setup_manifest()
            contract = tp.add_file('my-mod-CONTRACT.yaml',
                'module: my-mod\nversion: 1\nstatus: draft\n'
                'type: regular\npurpose: "test"\nprovides: []\nconsumes: []\n')
            result = import_contract(contract, tp.root)
            self.assertTrue(result)
            self.assertTrue((tp.root / 'modules' / 'my-mod' / 'CONTRACT.yaml').exists())


# ---------------------------------------------------------------------------
# SEC-002: new_module.py path traversal via --domain
# ---------------------------------------------------------------------------

class TestSec002NewModuleDomainTraversal(unittest.TestCase):

    def test_traversal_domain_rejected(self):
        """new_module.py --domain '../../../tmp/evil' must exit non-zero."""
        with TempProject() as tp:
            tp.setup_conventions()
            tp.setup_manifest()
            tp.setup_graph()
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'new_module.py'), 'my-mod',
                 '--domain', '../../tmp/evil', '--path', str(tp.root)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('not valid kebab-case', result.stdout + result.stderr)

    def test_valid_domain_accepted(self):
        """new_module.py --domain 'backend' must succeed."""
        with TempProject() as tp:
            tp.setup_conventions()
            tp.setup_manifest()
            tp.setup_graph()
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / 'new_module.py'), 'my-mod',
                 '--domain', 'backend', '--path', str(tp.root)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertTrue((tp.root / 'domains' / 'backend' / 'my-mod').exists())


# ---------------------------------------------------------------------------
# SEC-003: claims.py YAML injection via special characters
# ---------------------------------------------------------------------------

class TestSec003ClaimsYamlInjection(unittest.TestCase):

    def test_double_quote_in_by_roundtrips(self):
        """A 'by' field containing double quotes must survive save/load."""

        with TempProject() as tp:
            claims = {'test-mod': {
                'by': 'foo", injected: true, x: "bar',
                'branch': 'main',
                'since': '2026-01-01T00:00:00Z',
            }}
            _save_claims(tp.root, claims)
            loaded = _load_claims(tp.root)
            self.assertEqual(loaded['test-mod']['by'], 'foo", injected: true, x: "bar')

    def test_colon_in_by_roundtrips(self):
        """A 'by' field with YAML-special ':' must round-trip correctly."""

        with TempProject() as tp:
            claims = {'test-mod': {
                'by': 'agent: admin',
                'branch': 'feature/test',
                'since': '2026-01-01T00:00:00Z',
            }}
            _save_claims(tp.root, claims)
            loaded = _load_claims(tp.root)
            self.assertEqual(loaded['test-mod']['by'], 'agent: admin')

    def test_yaml_boolean_word_stays_string(self):
        """'yes' as by-field must stay string, not become boolean."""

        with TempProject() as tp:
            claims = {'mod': {'by': 'yes', 'branch': 'main', 'since': '2026-01-01T00:00:00Z'}}
            _save_claims(tp.root, claims)
            loaded = _load_claims(tp.root)
            self.assertIsInstance(loaded['mod']['by'], str)
            self.assertEqual(loaded['mod']['by'], 'yes')

    def test_newline_in_branch_roundtrips(self):
        """A branch containing newlines must not corrupt the file."""

        with TempProject() as tp:
            claims = {'test-mod': {
                'by': 'user',
                'branch': 'line1\nline2',
                'since': '2026-01-01T00:00:00Z',
            }}
            _save_claims(tp.root, claims)
            loaded = _load_claims(tp.root)
            self.assertEqual(loaded['test-mod']['branch'], 'line1\nline2')

    def test_claims_file_is_valid_yaml(self):
        """claims.yaml must always be parseable after save with adversarial input."""

        with TempProject() as tp:
            claims = {
                'mod-a': {'by': '{evil: true}', 'branch': '[1,2,3]', 'since': 'null'},
                'mod-b': {'by': '# comment', 'branch': '---', 'since': '!!python/object:os.system'},
            }
            _save_claims(tp.root, claims)
            raw = (tp.root / '.anma' / 'claims.yaml').read_text()
            import yaml
            parsed = yaml.safe_load(raw)
            self.assertIsNotNone(parsed)
            self.assertIn('mod-a', parsed.get('claims', {}))
            self.assertIn('mod-b', parsed.get('claims', {}))


if __name__ == '__main__':
    unittest.main()
