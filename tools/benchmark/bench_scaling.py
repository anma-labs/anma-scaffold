#!/usr/bin/env python3
"""ANMA Full Feature Benchmark — verifies domain scaling, multi-agent claims,
and incremental sync with real numbers.

Usage:
    python3 tools/benchmark/bench_scaling.py
    python3 tools/benchmark/bench_scaling.py --sizes 10,50,100,200,300
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.parent
PROJECT_ROOT = TOOLS_DIR.parent

sys.path.insert(0, str(TOOLS_DIR))
from discover import discover_modules, discover_domains, get_module_domain
from claims import add_claim, get_claim, release_claim, _load_claims, _save_claims
from lint_contracts import parse_yaml_file

py = sys.executable
passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✓ {name}")
        passed += 1
    else:
        print(f"  ✗ {name} — {detail}")
        failed += 1


def timed(cmd, cwd):
    start = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    return time.perf_counter() - start, r.returncode, r.stdout


def create_project(root, nm, nd):
    root = Path(root)
    shutil.copy2(str(PROJECT_ROOT / 'CONVENTIONS.yaml'), str(root / 'CONVENTIONS.yaml'))
    for d in ['BUS/deltas', 'BUS/requests', 'checks']:
        (root / d).mkdir(parents=True, exist_ok=True)

    all_mods = []
    doms = [f"dom-{i}" for i in range(nd)]
    mods_per = nm // nd
    extra = nm % nd

    for di, dom in enumerate(doms):
        count = mods_per + (1 if di < extra else 0)
        exports = []
        for mi in range(count):
            mod = f"{dom}-m{mi}"
            all_mods.append(mod)
            d = root / 'domains' / dom / mod
            d.mkdir(parents=True, exist_ok=True)

            consumes = "consumes: []"
            if mi == 0 and di > 0:
                consumes = (f"consumes:\n  - module: {doms[di-1]}-m0\n"
                            f"    interface: get\n    required: true\n    contract_version: 1")
            elif mi > 0:
                consumes = (f"consumes:\n  - module: {dom}-m{mi-1}\n"
                            f"    interface: get\n    required: true\n    contract_version: 1")

            (d / 'CONTRACT.yaml').write_text(
                f"module: {mod}\nversion: 1\nconventions_version: 3\nstatus: stable\n"
                f"type: regular\npurpose: Module {mi} in {dom}\nprovides:\n"
                f"  - id: get\n    input: {{ k: string }}\n    output: {{ v: string }}\n"
                f"    errors: [NOT_FOUND]\n    invariants: [returns value for key]\n"
                f"  - id: put\n    input: {{ k: string, v: string }}\n    output: {{ ok: boolean }}\n"
                f"    errors: [WRITE_ERR]\n    invariants: [stores value for key]\n"
                f"  - id: health\n    input: {{}}\n    output: {{ up: boolean }}\n"
                f"    errors: []\n    invariants: [returns health status]\n"
                f"{consumes}\ncontract_rules:\n  adding_interface: allowed\n"
                f"  modifying_interface: notify\n  removing_interface: breaking\n")
            (d / 'STATE.yaml').write_text(
                f"module: {mod}\nstatus: green\nupdated: 2026-05-28T00:00:00Z\ncurrent_work: none\n")
            (d / 'MEMORY.yaml').write_text(f"module: {mod}\nentries: []\n")
            (d / 'CHANGELOG.yaml').write_text(f"module: {mod}\nchanges: []\n")
            (d / 'ASSUMPTIONS.yaml').write_text(f"module: {mod}\nassumptions: []\n")
            (d / 'TESTS.yaml').write_text(
                f"module: {mod}\ntests:\n"
                f"  - interface: get\n    case: get value\n    input: {{ k: x }}\n    expect: {{ v: y }}\n"
                f"  - interface: put\n    case: store value\n    input: {{ k: x, v: y }}\n    expect: {{ ok: true }}\n"
                f"  - interface: health\n    case: check health\n    input: {{}}\n    expect: {{ up: true }}\n")
            if mi == 0:
                exports.append(f"  - module: {mod}\n    interfaces: [get]")

        (root / 'domains' / dom / 'GATEWAY.yaml').write_text(
            f"domain: {dom}\nversion: 1\nexports:\n" + "\n".join(exports) + "\n")

    mgrs = {}
    mi = 0
    for mod in all_mods:
        mgr = f"mgr-{mi}"
        if mgr not in mgrs:
            mgrs[mgr] = []
        mgrs[mgr].append(mod)
        if len(mgrs[mgr]) >= 7:
            mi += 1

    lines = ["project: bench\nversion: 1\nupdated: 2026-05-28T00:00:00Z\n\nmodules:\n"]
    for mod in all_mods:
        mgr = [k for k, v in mgrs.items() if mod in v][0]
        lines.append(f"  {mod}: {{ status: stable, owner: {mgr} }}\n")
    lines.append("\nmanagers:\n")
    for mgr, mlist in mgrs.items():
        lines.append(f"  {mgr}: {{ owns: [{', '.join(mlist)}] }}\n")
    lines.append("\norchestrator: active\n")
    (root / 'MANIFEST.yaml').write_text(''.join(lines))

    # Generate correct GRAPH from contracts
    subprocess.run([py, str(TOOLS_DIR / 'gen_graph.py'), '--path', str(root)],
                   capture_output=True)

    return all_mods


def run_benchmark(sizes):
    global passed, failed
    passed = 0
    failed = 0

    print("=" * 78)
    print("ANMA FULL FEATURE BENCHMARK")
    print("=" * 78)

    # ── PART 1 ──
    print("\n── PART 1: DOMAIN SCALING ──\n")

    for nm in sizes:
        nd = max(2, nm // 10)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods = create_project(root, nm, nd)

            start = time.perf_counter()
            found = discover_modules(root)
            t_disc = time.perf_counter() - start
            check(f"{nm:>3} modules: discover finds all ({t_disc:.3f}s)",
                  len(found) == nm, f"found {len(found)}")

            domains = discover_domains(root)
            check(f"{nm:>3} modules: {nd} domains detected", len(domains) == nd)

            first = mods[0]
            dom_name = first.rsplit('-m', 1)[0]
            check(f"{nm:>3} modules: domain inference",
                  get_module_domain(root, found[first]) == dom_name)

            t_lint, rc, stdout = timed(
                [py, str(TOOLS_DIR / 'lint_contracts.py'), str(root)], root)
            check(f"{nm:>3} modules: linter + gateway pass ({t_lint:.1f}s)", rc == 0,
                  [l for l in stdout.split('\n') if 'ERROR' in l][:2])

            if nd > 1:
                gw = root / 'domains' / 'dom-0' / 'GATEWAY.yaml'
                gw.write_text("domain: dom-0\nversion: 1\nexports: []\n")
                _, rc2, stdout2 = timed(
                    [py, str(TOOLS_DIR / 'lint_contracts.py'), str(root)], root)
                check(f"{nm:>3} modules: gateway rejects unexported dep",
                      rc2 != 0 and "not exported" in stdout2)
        print()

    # ── PART 2 ──
    print("── PART 2: MULTI-AGENT CLAIMS ──\n")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_project(root, 20, 3)
        mods_20 = list(discover_modules(root).keys())

        start = time.perf_counter()
        for mod in mods_20[:5]:
            add_claim(root, mod, by='agent-a', branch='feat/a')
        t_c = time.perf_counter() - start
        check(f"Claim 5 modules ({t_c*1000:.0f}ms)", len(_load_claims(root)) == 5)

        ok, msg = add_claim(root, mods_20[0], by='agent-b', branch='feat/b')
        check("Conflict rejected", not ok and 'agent-a' in msg)

        ok, _ = add_claim(root, mods_20[0], by='agent-a', branch='feat/a-v2')
        check("Same-user re-claim", ok)

        info = get_claim(root, mods_20[0])
        check("get_claim correct owner", info and info['by'] == 'agent-a')

        ok, _ = release_claim(root, mods_20[0])
        check("Release works", ok and get_claim(root, mods_20[0]) is None)

        ok, _ = release_claim(root, 'nonexistent')
        check("Release nonexistent (no error)", ok)

        _save_claims(root, {})
        start = time.perf_counter()
        for i in range(50):
            add_claim(root, f"mod-{i}", by='bench', branch='test')
        t_50 = time.perf_counter() - start
        check(f"Claim 50 modules ({t_50:.2f}s)", len(_load_claims(root)) == 50)

        _save_claims(root, {})
        check("Clear all", _load_claims(root) == {})

        add_claim(root, 'test', by='user', branch='main')
        data = parse_yaml_file(str(root / '.anma' / 'claims.yaml'))
        check("YAML round-trip", data and 'claims' in data and 'test' in data['claims'])

    print()

    # ── PART 3 ──
    print("── PART 3: INCREMENTAL SYNC ──\n")
    print(f"  {'Modules':>7}  {'Full':>8}  {'Skip':>8}  {'1-chg':>8}  {'Speedup':>8}")
    print("  " + "-" * 45)

    for nm in sizes:
        nd = max(2, nm // 10)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods = create_project(root, nm, nd)

            t_full, _, _ = timed(
                [py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root), '--force'], root)

            t_skip, _, stdout = timed(
                [py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root)], root)
            skipped = stdout.count('unchanged')
            check(f"{nm:>3} modules: {skipped}/{nm} skipped (unchanged)",
                  skipped >= nm - 1)

            first = mods[0]
            dom = first.rsplit('-m', 1)[0]
            c = root / 'domains' / dom / first / 'CONTRACT.yaml'
            c.write_text(c.read_text() + "\n# changed\n")
            t_1chg, _, stdout = timed(
                [py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root)], root)
            regen = stdout.count('Regenerated')
            check(f"{nm:>3} modules: {regen} regenerated after 1 change", regen <= 3)

            speedup = t_full / t_skip if t_skip > 0.001 else 0
            print(f"  {nm:>7}  {t_full:>7.1f}s  {t_skip:>7.1f}s  {t_1chg:>7.1f}s  {speedup:>7.1f}x")

    print()

    # Tool hash detection
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_project(root, 10, 2)
        timed([py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root), '--force'], root)
        timed([py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root)], root)
        gt = TOOLS_DIR / 'gen_tests.py'
        orig = gt.read_text()
        gt.write_text(orig + "\n# bench\n")
        _, _, stdout = timed([py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root)], root)
        gt.write_text(orig)
        check("Tool change triggers full regen", "gen_tests.py changed" in stdout)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_project(root, 10, 2)
        timed([py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root)], root)
        _, _, stdout = timed(
            [py, str(TOOLS_DIR / 'sync_all.py'), '--path', str(root), '--force'], root)
        check(f"--force overrides skip ({stdout.count('Regenerated')} regenerated)",
              stdout.count('Regenerated') >= 10)

    # ── SUMMARY ──
    print()
    print("=" * 78)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("ALL FEATURES VERIFIED ✓")
    else:
        print(f"{failed} FAILURE(S)")
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser(description='ANMA Full Feature Benchmark')
    parser.add_argument('--sizes', default='10,50,100,200',
                        help='Comma-separated module counts (default: 10,50,100,200)')
    args = parser.parse_args()
    sizes = [int(s.strip()) for s in args.sizes.split(',')]
    run_benchmark(sizes)


if __name__ == '__main__':
    main()
