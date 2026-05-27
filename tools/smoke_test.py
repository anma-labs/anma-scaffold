#!/usr/bin/env python3
"""ANMA End-to-End Smoke Test.

Creates a fresh temporary project from scratch, scaffolds modules with
cross-dependencies, runs every tool, and verifies they work together.
Catches integration regressions that unit tests miss.

Usage:
    python3 smoke_test.py           # Run full smoke test
    python3 smoke_test.py -v        # Verbose output

Zero external dependencies.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from discover import discover_modules

SCAFFOLD_ROOT = Path(__file__).parent


def _module_files_present(proj, module, required):
    try:
        module_paths = discover_modules(proj)
    except ValueError:
        module_paths = {}
    mod_dir = module_paths.get(module, proj / 'modules' / module)
    return all((mod_dir / f).exists() for f in required), mod_dir
VERBOSE = '-v' in sys.argv or '--verbose' in sys.argv


def run(cmd, cwd, expect_exit=0, capture=True):
    """Run a command and verify exit code."""
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=capture,
        text=True, timeout=30)
    if result.returncode != expect_exit:
        print(f"  FAIL: {' '.join(cmd)}")
        print(f"    Expected exit {expect_exit}, got {result.returncode}")
        if result.stdout:
            print(f"    stdout: {result.stdout[:500]}")
        if result.stderr:
            print(f"    stderr: {result.stderr[:500]}")
        return False
    if VERBOSE:
        print(f"    $ {' '.join(cmd)} → exit {result.returncode}")
    return result


def copy_scaffold(dest):
    """Copy scaffold infrastructure files (no modules) to dest."""
    # Copy scripts
    for f in ['lint_contracts.py', 'new_module.py', 'gen_claude_md.py',
              'gen_graph.py', 'graph_viz.py', 'verify_contract.py',
              'compat_matrix.py', 'bus_archive.py', 'test_linter.py',
              'yaml_editor.py', 'session_log.py', 'new_manager.py',
              'remove_module.py', 'rename_project.py', 'gen_contract.py',
              'gen_product_spec.py', 'dashboard.py', 'plan_migration.py',
              'anma.py', 'gen_tests.py', 'impact.py', 'contract_diff.py']:
        src = SCAFFOLD_ROOT / f
        if src.exists():
            shutil.copy2(str(src), str(dest / f))

    # Copy CONVENTIONS
    shutil.copy2(str(SCAFFOLD_ROOT / 'CONVENTIONS.yaml'), str(dest / 'CONVENTIONS.yaml'))

    # Create empty project structure
    (dest / 'BUS' / 'contracts').mkdir(parents=True)
    (dest / 'BUS' / 'deltas').mkdir(parents=True)
    (dest / 'BUS' / 'requests').mkdir(parents=True)
    (dest / 'orchestrator').mkdir(parents=True)
    (dest / 'checks').mkdir(parents=True)

    # Minimal MANIFEST
    (dest / 'MANIFEST.yaml').write_text(
        "project: smoke-test\nversion: 0.1.0\n"
        "updated: 2026-05-21T00:00:00Z\n\n"
        "modules: {}\n\n"
        "managers:\n  test-manager: { owns: [] }\n\n"
        "orchestrator: active\n")

    # Minimal GRAPH
    (dest / 'GRAPH.yaml').write_text(
        "version: 1\nupdated: 2026-05-21T00:00:00Z\n\nmodules: {}\n")

    # Manager
    mgr = dest / 'managers' / 'test-manager'
    mgr.mkdir(parents=True)
    (mgr / 'SCOPE.yaml').write_text(
        "manager: test-manager\nowns: []\n"
        "responsibilities: []\nreads: []\nwrites: []\n")
    (mgr / 'STRATEGY.yaml').write_text("manager: test-manager\nplan: []\n")
    (mgr / 'INBOX.yaml').write_text("manager: test-manager\nitems: []\n")

    # Orchestrator
    (dest / 'orchestrator' / 'PLAN.yaml').write_text("phases: []\n")
    (dest / 'orchestrator' / 'QUEUE.yaml').write_text("items: []\n")
    (dest / 'orchestrator' / 'RULES.yaml').write_text(
        "role: orchestrator\nreads: []\nresponsibilities: []\n")


def main():
    passed = 0
    failed = 0

    def check(name, condition):
        nonlocal passed, failed
        if condition:
            passed += 1
            if VERBOSE:
                print(f"  PASS: {name}")
        else:
            failed += 1
            print(f"  FAIL: {name}")

    print("\nANMA End-to-End Smoke Test")
    print("=" * 50)

    with tempfile.TemporaryDirectory() as tmpdir:
        proj = Path(tmpdir) / 'project'
        proj.mkdir()
        py = sys.executable

        # --- Phase 1: Bootstrap ---
        print("\n── Phase 1: Bootstrap empty project ──")
        copy_scaffold(proj)

        # Empty project has no modules — linter exits 1, which is correct
        r = run([py, 'lint_contracts.py'], proj, expect_exit=1)
        check("empty project: linter exits 1 (no modules)", r and r.returncode == 1)

        # --- Phase 2: Scaffold 3 modules ---
        print("\n── Phase 2: Scaffold modules ──")

        r = run([py, 'new_module.py', 'database-core',
                 '--type', 'regular', '--manager', 'test-manager',
                 '--purpose', 'Core database access layer'], proj)
        check("scaffold database-core", r and r.returncode == 0)

        r = run([py, 'new_module.py', 'user-service',
                 '--manager', 'test-manager', '--consumes', 'database-core',
                 '--purpose', 'User management service'], proj)
        check("scaffold user-service (depends on database-core)", r and r.returncode == 0)

        r = run([py, 'new_module.py', 'auth-handler',
                 '--manager', 'test-manager', '--consumes', 'user-service',
                 '--purpose', 'Authentication and session management'], proj)
        check("scaffold auth-handler (depends on user-service)", r and r.returncode == 0)

        # Verify files created
        required_module_files = ['CONTRACT.yaml', 'STATE.yaml', 'MEMORY.yaml',
                                 'CHANGELOG.yaml', 'TESTS.yaml', 'ASSUMPTIONS.yaml']
        for mod in ['database-core', 'user-service', 'auth-handler']:
            try:
                module_paths = discover_modules(proj)
            except ValueError:
                module_paths = {}
            mod_dir = module_paths.get(mod, proj / 'modules' / mod)
            for f in required_module_files:
                check(f"{mod}/{f} exists", (mod_dir / f).exists())

        # --- Phase 3: Verify GRAPH consistency ---
        print("\n── Phase 3: Graph consistency ──")

        # Graph may be stale after scaffolding — expected
        r2 = run([py, 'gen_graph.py'], proj)
        check("gen_graph.py runs", r2 and r2.returncode == 0)

        r3 = run([py, 'gen_graph.py', '--check'], proj)
        check("graph up to date after regeneration", r3 and r3.returncode == 0)

        # --- Phase 4: Linter ---
        print("\n── Phase 4: Linter with 3 modules ──")

        # Scaffolded modules have interface: TBD — linter correctly flags these
        # Verify linter runs and errors are only TBD-related
        r = run([py, 'lint_contracts.py'], proj, expect_exit=1)
        check("linter runs (exits 1 from TBD placeholders)",
              r and r.returncode == 1)
        check("errors are TBD-related",
              r and 'TBD' in r.stdout)

        r = run([py, 'lint_contracts.py', '--module', 'database-core'], proj)
        check("--module filter on module with no deps", r and r.returncode == 0)

        # --- Phase 5: Graph visualization ---
        print("\n── Phase 5: Graph visualization ──")

        r = run([py, 'graph_viz.py'], proj)
        check("graph_viz produces output", r and r.returncode == 0 and 'graph TD' in r.stdout)
        check("graph has all 3 modules",
              r and 'database-core' in r.stdout
              and 'user-service' in r.stdout
              and 'auth-handler' in r.stdout)
        check("graph has dependency edges",
              r and 'user-service --> database-core' in r.stdout
              and 'auth-handler --> user-service' in r.stdout)

        # --- Phase 6: CLAUDE.md generation ---
        print("\n── Phase 6: CLAUDE.md generation ──")

        r = run([py, 'gen_claude_md.py'], proj)
        check("project CLAUDE.md generated", r and r.returncode == 0)
        check("CLAUDE.md exists", (proj / 'CLAUDE.md').exists())

        r = run([py, 'gen_claude_md.py', '--module', 'user-service'], proj)
        check("module CLAUDE.md generated", r and r.returncode == 0)
        try:
            mod_paths = discover_modules(proj)
        except ValueError:
            mod_paths = {}
        us_dir = mod_paths.get('user-service', proj / 'modules' / 'user-service')
        check("module CLAUDE.md exists", (us_dir / 'CLAUDE.md').exists())

        # --- Phase 7: Compatibility matrix ---
        print("\n── Phase 7: Compatibility matrix ──")

        r = run([py, 'compat_matrix.py'], proj)
        check("compat_matrix runs", r and r.returncode == 0)
        check("matrix shows all modules",
              r and 'database-core' in r.stdout and 'user-service' in r.stdout)

        r = run([py, 'compat_matrix.py', '--json'], proj)
        check("JSON mode works", r and r.returncode == 0)
        try:
            data = json.loads(r.stdout)
            check("JSON is valid", True)
            check("JSON has edges", 'edges' in data)
            check("JSON has modules", 'modules' in data)
        except (json.JSONDecodeError, AttributeError):
            check("JSON is valid", False)
            check("JSON has edges", False)
            check("JSON has modules", False)

        # --- Phase 8: Contract verification ---
        print("\n── Phase 8: Contract verification ──")

        r = run([py, 'verify_contract.py', 'database-core', '--plan'], proj)
        check("verify_contract --plan runs", r and r.returncode == 0)

        r = run([py, 'verify_contract.py', 'user-service'], proj)
        check("verify_contract default mode", r and r.returncode == 0)

        # --- Phase 9: BUS lifecycle ---
        print("\n── Phase 9: BUS lifecycle ──")

        r = run([py, 'bus_archive.py', '--dry-run'], proj)
        check("bus_archive --dry-run runs", r and r.returncode == 0)

        # --- Phase 10: Plugin system ---
        print("\n── Phase 10: Plugin system ──")

        (proj / 'checks' / 'check_smoke.py').write_text(
            "def run(root, contracts, all_contracts, conventions, manifest, result, **kwargs):\n"
            "    result.warning('smoke', 'plugin executed')\n")
        # Linter may exit 1 due to TBD errors, but plugin should still load
        r = run([py, 'lint_contracts.py'], proj, expect_exit=1)
        check("plugin loaded and ran",
              r and 'Plugin: check_smoke' in r.stdout)
        check("plugin warning present",
              r and 'plugin executed' in r.stdout)
        (proj / 'checks' / 'check_smoke.py').unlink()

        # --- Phase 11: Error handling ---
        print("\n── Phase 11: Error handling ──")

        r = run([py, 'new_module.py', 'BadName'], proj, expect_exit=1)
        check("bad module name rejected", r and r.returncode == 1)

        r = run([py, 'new_module.py', 'database-core'], proj, expect_exit=1)
        check("duplicate module rejected", r and r.returncode == 1)

        r = run([py, 'verify_contract.py', 'nonexistent'], proj, expect_exit=1)
        check("nonexistent module rejected", r and r.returncode == 1)

        # --- Phase 12: Manager scaffolding ---
        print("\n── Phase 12: Manager scaffolding ──")

        r = run([py, 'new_manager.py', 'api-manager'], proj)
        check("new_manager creates manager", r and r.returncode == 0)
        check("SCOPE.yaml created",
              (proj / 'managers' / 'api-manager' / 'SCOPE.yaml').exists())
        check("STRATEGY.yaml created",
              (proj / 'managers' / 'api-manager' / 'STRATEGY.yaml').exists())
        check("INBOX.yaml created",
              (proj / 'managers' / 'api-manager' / 'INBOX.yaml').exists())

        r = run([py, 'new_manager.py', 'api-manager'], proj, expect_exit=1)
        check("duplicate manager rejected", r and r.returncode == 1)

        r = run([py, 'new_manager.py', 'BadManager'], proj, expect_exit=1)
        check("bad manager name rejected", r and r.returncode == 1)

        # --- Phase 13: Contract template generator ---
        print("\n── Phase 13: Contract template generator ──")

        r = run([py, 'gen_contract.py', 'test-store', '--purpose', 'Data storage'], proj)
        check("gen_contract stdout", r and r.returncode == 0 and 'provides:' in r.stdout)
        check("gen_contract detects crud pattern",
              r and 'crud' in r.stderr)

        r = run([py, 'gen_contract.py', 'auth-svc', '--purpose', 'Authentication'], proj)
        check("gen_contract detects auth pattern",
              r and 'auth' in r.stderr)

        r = run([py, 'gen_contract.py', 'test-store', '--purpose', 'Storage',
                 '--output', str(proj / 'modules' / 'database-core' / 'CONTRACT.yaml')], proj)
        check("gen_contract --output writes file", r and r.returncode == 0)

        # --- Phase 14: Product spec generator ---
        print("\n── Phase 14: Product spec generator ──")

        r = run([py, 'gen_product_spec.py'], proj)
        check("gen_product_spec runs", r and r.returncode == 0)
        check("spec has module headers",
              r and '## database-core' in r.stdout)

        r = run([py, 'gen_product_spec.py', '--module', 'database-core'], proj)
        check("gen_product_spec --module filter",
              r and r.returncode == 0 and '## database-core' in r.stdout)

        # --- Phase 15: Project rename ---
        print("\n── Phase 15: Project rename ──")

        r = run([py, 'rename_project.py', 'renamed-project'], proj)
        check("rename runs", r and r.returncode == 0)
        manifest_txt = (proj / 'MANIFEST.yaml').read_text()
        check("MANIFEST has new name", 'renamed-project' in manifest_txt)

        r = run([py, 'rename_project.py', 'smoke-test'], proj)
        check("rename back", r and r.returncode == 0)

        r = run([py, 'rename_project.py', 'Bad Name'], proj, expect_exit=1)
        check("bad project name rejected", r and r.returncode == 1)

        # --- Phase 16: Module removal ---
        print("\n── Phase 16: Module removal ──")

        # user-service consumes database-core, so database-core should be refused
        r = run([py, 'remove_module.py', 'database-core', '--confirm'], proj, expect_exit=1)
        check("remove consumed module refused", r and r.returncode == 1)

        r = run([py, 'remove_module.py', 'database-core'], proj, expect_exit=1)
        check("remove without --confirm refused", r and r.returncode == 1)

        # auth-handler is not consumed by anyone
        r = run([py, 'remove_module.py', 'auth-handler', '--confirm'], proj)
        try:
            after_paths = discover_modules(proj)
        except ValueError:
            after_paths = {}
        check("remove unconsumed module",
              r and r.returncode == 0 and 'auth-handler' not in after_paths)

        # --- Phase 17: Final consistency ---
        print("\n── Phase 17: Final consistency ──")

        # Regenerate graph and verify
        run([py, 'gen_graph.py'], proj)
        r = run([py, 'gen_graph.py', '--check'], proj)
        check("graph consistent after all changes", r and r.returncode == 0)

        # Final lint
        # Remove generated CLAUDE.md files first (not part of lint)
        for cmd_file in proj.rglob('CLAUDE.md'):
            cmd_file.unlink()

        # Final lint — TBD placeholders cause errors, which is correct
        r = run([py, 'lint_contracts.py'], proj, expect_exit=1)
        check("final lint runs (TBD errors expected)", r and r.returncode == 1)

        # --- Phase 18: Getting Started integration test ---
        print("\n── Phase 18: Getting Started walkthrough ──")

        # Full scaffold copy (needs existing modules to remove)
        gs = Path(tempfile.mkdtemp(prefix='anma_gs_'))
        # Copy everything from scaffold root
        for item in SCAFFOLD_ROOT.iterdir():
            if item.name.startswith('__') or item.name.endswith('.pyc'):
                continue
            if item.is_dir():
                shutil.copytree(str(item), str(gs / item.name))
            else:
                shutil.copy2(str(item), str(gs / item.name))

        # Step 1: Rename
        r = run([py, 'rename_project.py', 'my-app'], gs)
        check("GS: rename project", r and r.returncode == 0)

        # Step 2: Remove example modules + old manager
        r = run([py, 'remove_module.py', 'auth-service', '--confirm'], gs)
        check("GS: remove auth-service", r and r.returncode == 0)
        r = run([py, 'remove_module.py', 'user-store', '--confirm'], gs)
        check("GS: remove user-store", r and r.returncode == 0)
        mgr_dir = gs / 'managers' / 'backend-manager'
        if mgr_dir.exists():
            shutil.rmtree(mgr_dir)
        # Clean MANIFEST
        mf = gs / 'MANIFEST.yaml'
        mf.write_text('\n'.join(
            l for l in mf.read_text().split('\n')
            if 'backend-manager' not in l))

        # Step 3: Reset orchestrator plan
        (gs / 'orchestrator' / 'PLAN.yaml').write_text(
            'updated: 2026-01-01T00:00:00Z\n\nphases: []\n')

        # Step 4: Create managers
        r = run([py, 'new_manager.py', 'core-manager'], gs)
        check("GS: create core-manager", r and r.returncode == 0)
        r = run([py, 'new_manager.py', 'api-manager'], gs)
        check("GS: create api-manager", r and r.returncode == 0)

        # Step 5: Scaffold modules
        r = run([py, 'new_module.py', 'user-store',
                 '--manager', 'core-manager', '--purpose', 'User data'], gs)
        check("GS: scaffold user-store", r and r.returncode == 0)
        r = run([py, 'new_module.py', 'auth-svc',
                 '--manager', 'core-manager', '--consumes', 'user-store',
                 '--purpose', 'Auth'], gs)
        check("GS: scaffold auth-svc", r and r.returncode == 0)

        # Step 6: Generate contract
        r = run([py, 'gen_contract.py', 'user-store',
                 '--purpose', 'User data storage',
                 '--output', str(gs / 'modules' / 'user-store' / 'CONTRACT.yaml')], gs)
        check("GS: gen_contract", r and r.returncode == 0)

        # Step 7: Generate graph
        r = run([py, 'gen_graph.py'], gs)
        check("GS: gen_graph", r and r.returncode == 0)

        # Step 8: Lint — expect 1 error (auth-svc TBD), 0 schema warnings
        r = run([py, 'lint_contracts.py'], gs, expect_exit=1)
        check("GS: lint runs", r and r.returncode == 1)
        check("GS: only TBD errors",
              r and 'TBD' in r.stdout and 'unknown key' not in r.stdout)

        # Step 10: Generate CLAUDE.md
        r = run([py, 'gen_claude_md.py'], gs)
        check("GS: gen_claude_md", r and r.returncode == 0)

        shutil.rmtree(gs)

    # --- Summary ---
    print("\n" + "=" * 50)
    total = passed + failed
    print(f"  {passed} passed, {failed} failed out of {total}")
    if failed == 0:
        print("  ALL SMOKE TESTS PASSED")
    else:
        print("  FAILURES DETECTED")
    sys.exit(1 if failed > 0 else 0)


if __name__ == '__main__':
    main()
