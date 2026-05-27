# Domain Scaling — Implementation Plan

**Purpose:** This document is the spec for adding domain scaling to ANMA.
Claude Code reads this and implements. No architectural decisions needed —
everything is specified here.

**Baseline (verified 2026-05-27):**
- 91/91 tests passing
- Linter: 0 errors, 0 warnings (including --strict)
- conventions_version: 2
- 31 Python files total (26 tools + 2 checks + 3 benchmark)

---

## 1. Directory Layout

Flat layout (existing, always supported):

```
project-root/
├── modules/
│   └── <module>/
│       └── CONTRACT.yaml ...
```

Domain layout (new, optional):

```
project-root/
├── domains/
│   └── <domain>/
│       ├── GATEWAY.yaml
│       └── <module>/
│           └── CONTRACT.yaml ...
```

Both can coexist. A project can have some modules flat and some in domains.
Detection is automatic — no config flag needed.

Domain names follow kebab-case (same as modules).

---

## 2. New Shared Utility: `tools/discover.py`

Create a new file `tools/discover.py` with three functions.
**All 24 affected tools import from this file.**

```python
#!/usr/bin/env python3
"""Module and domain discovery for ANMA projects.

Single source of truth for finding modules across flat and domain layouts.
Every tool that needs module paths imports from here.
"""

from pathlib import Path


def discover_modules(root):
    """Find all modules. Returns {module_name: Path}.

    Scans both flat (modules/) and domain (domains/<domain>/) layouts.
    Raises ValueError if duplicate module names found across locations.
    """
    root = Path(root)
    found = {}
    dupes = []

    # Flat layout: modules/<module>/
    modules_dir = root / 'modules'
    if modules_dir.is_dir():
        for d in sorted(modules_dir.iterdir()):
            if d.is_dir() and (d / 'CONTRACT.yaml').exists():
                found[d.name] = d

    # Domain layout: domains/<domain>/<module>/
    domains_dir = root / 'domains'
    if domains_dir.is_dir():
        for domain_dir in sorted(domains_dir.iterdir()):
            if not domain_dir.is_dir() or domain_dir.name.startswith('.'):
                continue
            # Skip GATEWAY.yaml and non-directory entries
            for d in sorted(domain_dir.iterdir()):
                if d.is_dir() and (d / 'CONTRACT.yaml').exists():
                    if d.name in found:
                        dupes.append(
                            f"'{d.name}' in both {found[d.name]} and {d}")
                    else:
                        found[d.name] = d

    if dupes:
        raise ValueError('Duplicate module names: ' + '; '.join(dupes))

    return found


def get_module_domain(root, module_path):
    """Infer domain from filesystem path. Returns domain name or None.

    A module is in a domain if its path is root/domains/<domain>/<module>.
    Flat modules (root/modules/<module>) return None.
    """
    root = Path(root)
    try:
        rel = Path(module_path).relative_to(root / 'domains')
        return rel.parts[0] if len(rel.parts) >= 2 else None
    except ValueError:
        return None


def discover_domains(root):
    """Find all domains. Returns {domain_name: {'modules': [names], 'gateway': Path|None}}.

    Only scans domains/ directory. Returns empty dict for flat-only projects.
    """
    root = Path(root)
    domains = {}
    domains_dir = root / 'domains'
    if not domains_dir.is_dir():
        return domains

    for domain_dir in sorted(domains_dir.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith('.'):
            continue
        mods = []
        for d in sorted(domain_dir.iterdir()):
            if d.is_dir() and (d / 'CONTRACT.yaml').exists():
                mods.append(d.name)
        gateway = domain_dir / 'GATEWAY.yaml'
        domains[domain_dir.name] = {
            'modules': mods,
            'gateway': gateway if gateway.exists() else None,
        }

    return domains
```

---

## 3. GATEWAY.yaml Spec

Lives at `domains/<domain>/GATEWAY.yaml`. Defines which interfaces are
exported (visible to modules in other domains).

```yaml
domain: backend
version: 1

exports:
  - module: user-auth
    interfaces: [verify_token, get_user]
  - module: payments
    interfaces: [process_payment, refund]
```

**Rules:**
- Every module listed in `exports` must exist in this domain
- Every interface listed must appear in that module's `provides`
- Cross-domain `consumes` entries must reference exported interfaces
- Flat modules consuming domain modules must also use exported interfaces
- Within a domain, modules can freely consume each other (no gateway needed)
- Flat modules consuming other flat modules have no gateway restrictions

---

## 4. CONVENTIONS.yaml Additions

**Append-only policy applies.** Add new sections, don't modify existing.
Bump `conventions_version` from 2 to 3.

Add after `dependency_rules:`:

```yaml
domain_scaling:
  layout_modes: [flat, domain, mixed]
  detection: "automatic — if domains/ exists, scan it; modules/ always scanned"
  naming:
    domains: kebab-case
  rules:
    - "Module names must be globally unique across all domains and flat modules"
    - "Cross-domain consumes must reference interfaces listed in target domain's GATEWAY.yaml"
    - "Flat modules consuming domain modules must also use exported interfaces"
    - "Within a domain, modules consume each other freely (no gateway needed)"
    - "Flat-to-flat consumption has no gateway restrictions"
    - "GATEWAY.yaml is required for any domain that exports interfaces"
  gateway_spec:
    required_fields: [domain, version, exports]
    exports_shape: "list of {module: string, interfaces: [string]}"
```

Change `conventions_version: 2` → `conventions_version: 3`.

Update all three example module contracts:
`conventions_version: 2` → `conventions_version: 3`

---

## 5. Tool Changes — Detailed

### Pattern A: Replace `root / 'modules'` scanning with `discover_modules()`

These files scan `modules/` with `iterdir()`. Replace with `discover_modules(root)`.

**File: tools/lint_contracts.py**
- Add `from discover import discover_modules, discover_domains, get_module_domain` to imports
  (`discover_domains` and `get_module_domain` are needed by `check_gateway` in Phase 3)
- Refactor `load_all_contracts(root)`:
  - Replace `modules_dir = root / 'modules'` + `iterdir()` with `discover_modules(root)`
  - Keep same return type: `{module_name: contract_dict}`
- In `main()`: call `module_paths = discover_modules(root)` AFTER the
  `if not contracts: sys.exit(1)` check, wrapped in try/except:
  ```python
  contracts = load_all_contracts(root)
  # ... load graph, conventions, manifest ...
  if not contracts:
      print("  ✗ No contracts found in modules/ or domains/ directory.\n")
      sys.exit(1)
  try:
      module_paths = discover_modules(root)
  except ValueError as e:
      print(f"  ✗ {e}")
      sys.exit(1)
  ```
  **Why this ordering?** `load_all_contracts` catches `ValueError` from
  `discover_modules` internally and returns `{}`. If `main()` called
  `discover_modules` BEFORE the empty-contracts check, the same `ValueError`
  would crash as an unhandled exception.
- Add `module_paths=None` as OPTIONAL KEYWORD ARG to these 9 check functions.
  **Keep `root` as first parameter — do NOT change existing positional args.**
  This ensures all 55 existing test calls (which don't pass module_paths) still work.
  Each function adds this fallback at the top:
  ```python
  if module_paths is None:
      module_paths = discover_modules(root)
  ```
  The 9 functions and their new signatures:
  - `check_state_files(root, contracts, result, module_paths=None)`
  - `check_memory_files(root, contracts, conventions, result, module_paths=None)`
  - `check_test_files(root, contracts, result, module_paths=None)`
  - `check_context_budget(root, contracts, conventions, result, module_paths=None)`
  - `check_assumptions(root, contracts, result, module_paths=None)`
  - `check_changelog(root, contracts, result, module_paths=None)`
  - `check_replacement_ready(root, contracts, result, module_paths=None)`
  - `check_assumption_compatibility(root, all_contracts, result, module_paths=None)`
  - `check_schemas(root, contracts, result, module_paths=None)`
- Inside each: replace `root / 'modules' / mod_name` using `.get()` fallback:
  ```python
  # WRONG — causes KeyError in 7 tests where modules lack CONTRACT.yaml:
  filepath = module_paths[mod_name] / 'STATE.yaml'

  # CORRECT — falls back to old path for edge cases:
  mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
  filepath = mod_dir / 'STATE.yaml'
  ```
  **Why .get()?** Tests like TestAssumptionCompatibility create module dirs
  with only ASSUMPTIONS.yaml (no CONTRACT.yaml). `discover_modules()` only
  finds dirs with CONTRACT.yaml, so these aren't in `module_paths`.
  The `.get()` fallback preserves the old behavior for these edge cases
  while routing domain modules (which always have CONTRACT.yaml) correctly.
  Verified: 91/91 tests pass with `.get()`, 87/91 fail with direct `[]`.
- `check_context_budget` keeps `root` for shared file paths (`root / 'CONVENTIONS.yaml'` etc.)
  AND uses `module_paths` for module files. Uses `len(module_paths)` for count.
- In `main()`: pass `module_paths=module_paths` as keyword arg to each:
  ```python
  check_state_files(root, contracts, result, module_paths=module_paths)
  ```
- Plugin check interface: add `module_paths=module_paths` to kwargs in plugin runner

**File: tools/sync_all.py**
- Add `from discover import discover_modules, get_module_domain`
  (`get_module_domain` needed in Phase 3 to populate MANIFEST domain field)
- Replace `modules_dir = root / 'modules'` + `iterdir()` with `discover_modules(root)`
- Iterate directly: `for mod_name, mod_dir in module_paths.items():`
  (no `.get()` needed — iterating the dict guarantees valid entries)

**File: tools/import_contracts.py**
- Add `from discover import discover_modules`
- Add `--domain` optional argument
- If `--domain` specified: create under `root / 'domains' / domain / module_name`
- If no domain: create under `root / 'modules' / module_name` (current behavior)
- Replace existing-module check: use `discover_modules(root)` instead of scanning `modules_dir`

**File: tools/init_project.py**
- Add `from discover import discover_modules`
- Clear both `modules/` and `domains/` directories when initializing
- Use `discover_modules(root)` to report what was cleared

**File: tools/new_module.py**
- Add `from discover import discover_modules`
- Add `--domain` optional argument
- If `--domain` specified: create under `root / 'domains' / domain / name`
- If no domain: create under `root / 'modules' / name` (current behavior)
- Dependency check: use `discover_modules(root)` to find consumed modules

**File: tools/benchmark/measure_tokens.py**
- Add to imports (benchmark tools are in a subdirectory — need parent path):
  ```python
  sys.path.insert(0, str(Path(__file__).parent.parent))
  from discover import discover_modules
  ```
- Replace `modules_dir = project_dir / "modules"` + `iterdir()` with `discover_modules(project_dir)`

**File: tools/benchmark/eval_degradation.py**
- Add same sys.path fix as measure_tokens.py
- In `select_test_modules`: use `discover_modules(pd)` instead of `pd / "modules"` scan

**File: tools/benchmark/generate_archetypes.py**
- Keep as-is for now — it generates synthetic projects that use flat layout
- Add TODO comment: "Generate domain-layout archetypes in future"

### Pattern B: Replace `root / 'modules' / mod_name` lookups with `module_paths.get()`

These files don't scan directories but construct paths for specific modules.
They need `module_paths` from `discover_modules()`.

**Use the same `.get()` fallback as Pattern A:**
```python
module_paths = discover_modules(root)
mod_dir = module_paths.get(mod_name, root / 'modules' / mod_name)
```
This prevents `KeyError` if a module name comes from CLI args or a stale manifest.

**File: tools/compat_matrix.py**
- Add `from discover import discover_modules`
- Call `module_paths = discover_modules(root)` in main
- Replace `root / 'modules' / mod_name / 'ASSUMPTIONS.yaml'`
  → `module_paths.get(mod_name, root / 'modules' / mod_name) / 'ASSUMPTIONS.yaml'`

**File: tools/contract_diff.py**
- Add `from discover import discover_modules`
- In `snapshot()`: use `module_paths.get(module, root / 'modules' / module)` instead of `root / 'modules' / module`
- In `write_deltas()`: same pattern for CHANGELOG.yaml path

**File: tools/dashboard.py**
- Add `from discover import discover_modules`
- Call `module_paths = discover_modules(root)` in main
- Replace all 7 instances of `root / 'modules' / mod_name / <file>`
  → `module_paths.get(mod_name, root / 'modules' / mod_name) / <file>`

**File: tools/gen_claude_md.py**
- Add `from discover import discover_modules`
- In `generate_module_claude_md`: use module_paths for contract path
- In main: use module_paths for `--module` directory check

**File: tools/gen_contract.py**
- Add `from discover import discover_modules`
- Replace `root / 'modules' / dep / 'CONTRACT.yaml'`
  → `module_paths.get(dep, root / "modules" / dep) / 'CONTRACT.yaml'`

**File: tools/gen_tests.py**
- Add `from discover import discover_modules`
- Replace `root / 'modules' / module_name / 'CONTRACT.yaml'`
  → `module_paths.get(module_name, root / "modules" / module_name) / 'CONTRACT.yaml'`
- Replace existing tests path similarly

**File: tools/graph_viz.py**
- Add `from discover import discover_modules`
- Replace `root / 'modules' / mod_name / 'CONTRACT.yaml'`
  → `module_paths.get(mod_name, root / "modules" / mod_name) / 'CONTRACT.yaml'`

**File: tools/remove_module.py**
- Add `from discover import discover_modules`
- Replace `root / 'modules' / name` → `module_paths.get(name)`
- Handle KeyError: "Module not found"

**File: tools/verify_contract.py**
- Add `from discover import discover_modules`
- Replace both `root / 'modules' / ...` references with module_paths lookups

**File: tools/smoke_test.py**
- Uses `new_module.py` to create modules (which handles paths internally)
- Replace `proj / 'modules' / mod / f` existence checks:
  use `discover_modules(proj)` to get paths, then check from there
- Hardcoded module names ('database-core', 'user-service', 'auth-handler')
  stay flat — smoke test verifies flat layout works

### Pattern C: Check files (plugin interface)

**IMPORTANT:** The plugin runner in `lint_contracts.py` passes kwargs to `run()`.
Adding `module_paths=module_paths` to the call BREAKS any plugin without
`**kwargs` in its signature. Both existing plugins must be updated.

**CRITICAL: Without the full Pattern C update, domain modules are silently
skipped by principle checks.** P1-P7 look for files at `modules/<name>/`
which doesn't exist for domain modules. They silently return "no issues"
instead of catching violations. Verified by adding `nginx` (P1 violation)
to a domain module — P1 missed it until paths were fixed.

**File: checks/check_principles.py** (5 functions need changes)
- Add `from pathlib import Path` at top
- Change `run()` signature to include `**kwargs`
- In `run()`: extract `module_paths = kwargs.get('module_paths') or {}`
  (fallback to `discover_modules(root)` if not provided — add import with try/except)
- Pass `module_paths` to each of the 5 check_pN functions that use paths:
  ```python
  check_p1_contracts_over_code(root, contracts, result, module_paths)
  check_p2_tokens_are_bottleneck(root, contracts, result, conventions, module_paths)
  check_p3_state_is_explicit(root, contracts, result, module_paths)
  check_p6_recovery_is_cheap(root, contracts, result, conventions, module_paths)
  check_p7_replacement_over_continuity(root, contracts, result, module_paths)
  ```
- Add `module_paths=None` parameter to each of those 5 function signatures
- Add fallback `if module_paths is None: module_paths = {}` in each
- Replace all 5 instances of `root / 'modules' / mod_name` with
  `module_paths.get(mod_name, root / 'modules' / mod_name)`
- P4 and P5 are unchanged (don't use filesystem module paths)

**File: checks/check_conventions_pin.py**
- Change signature: `def run(root, contracts, all_contracts, conventions, manifest, result, **kwargs):`
- No other changes (doesn't use module_paths, but `**kwargs` prevents crash)

### Pattern D: Schema-level changes (only if MANIFEST/GRAPH schemas change)

**File: tools/yaml_editor.py**
- Add optional `domain` field to manifest module entries
- `manifest_add_module`: accept optional `domain` param
- `manifest_remove_module`: find module regardless of domain field
- `graph_add_module` / `graph_remove_module`: no schema change needed

**File: tools/gen_graph.py**
- No change to output schema — graph stays flat `modules:`
- But: add optional `domain` metadata comment per module for readability

**File: tools/impact.py**
- No code changes — reads `graph['modules']` which stays flat

**File: tools/plan_migration.py**
- No code changes — reads `graph['modules']` which stays flat

### Pattern E: Test files

**File: tools/test_linter.py**
- `TempProject.add_module()` stays as-is (creates flat layout — backward compat)
- Add `TempProject.add_domain_module(domain, name, contract_text)`:
  creates `root / 'domains' / domain / name / CONTRACT.yaml`
- Add `TempProject.add_gateway(domain, gateway_text)`:
  creates `root / 'domains' / domain / GATEWAY.yaml`
- **ZERO changes to existing test calls.** The `module_paths=None` default
  means existing calls like `check_state_files(tp.root, contracts, r)` and
  `_run_check(check_state_files, self.root, self.contracts)` still work —
  each function falls back to `discover_modules(root)` internally.
- Add new test class `TestDomainScaling` with tests:
  - `test_flat_layout_still_works` — existing modules found
  - `test_domain_layout_discovered` — domain modules found
  - `test_mixed_layout` — both found
  - `test_duplicate_module_name_rejected` — ValueError raised
  - `test_gateway_exports_validated` — linter catches unexported cross-domain deps
  - `test_within_domain_no_gateway_needed` — intra-domain deps OK without gateway
  - `test_flat_modules_no_gateway_needed` — flat modules unrestricted
- Add new test class `TestDiscoverModules` with unit tests for discover.py functions

---

## 6. New Linter Check: `check_gateway`

Add to `lint_contracts.py` after `check_schemas`:

```python
def check_gateway(root, contracts, all_contracts, module_paths, result):
    """Check 24: Gateway validation for domain scaling."""
    print("── Check 24: Gateway validation ──")

    domains = discover_domains(root)
    if not domains:
        return  # No domains, nothing to check

    # Build domain lookup: {module_name: domain_name}
    domain_lookup = {}
    for dname, info in domains.items():
        for mod in info['modules']:
            domain_lookup[mod] = dname

    # Build exports lookup: {domain: {module: set(interfaces)}}
    exports = {}
    for dname, info in domains.items():
        if info['gateway'] is None:
            continue
        gw = parse_yaml_file(str(info['gateway']))
        if not gw or not isinstance(gw, dict):
            result.error(f"domain/{dname}", "GATEWAY.yaml is empty or malformed")
            continue
        exports[dname] = {}
        for entry in gw.get('exports', []):
            if isinstance(entry, dict):
                mod = entry.get('module', '')
                ifaces = entry.get('interfaces', [])
                exports[dname][mod] = set(ifaces) if isinstance(ifaces, list) else set()

    # Validate cross-domain consumes (only for FILTERED contracts)
    for mod_name, contract in contracts.items():
        mod_domain = domain_lookup.get(mod_name)  # None if flat
        for dep in contract.get('consumes', []) or []:
            if not isinstance(dep, dict):
                continue
            dep_module = dep.get('module', '')
            dep_interface = dep.get('interface', '')
            dep_domain = domain_lookup.get(dep_module)

            # Skip if provider is flat (no gateway to enforce)
            if dep_domain is None:
                continue
            # Skip if same domain (intra-domain, no gateway needed)
            if mod_domain == dep_domain:
                continue

            # Cross-domain OR flat→domain: check gateway
            if dep_domain not in exports:
                result.error(mod_name,
                    f"consumes {dep_module}.{dep_interface} from domain "
                    f"'{dep_domain}' but '{dep_domain}' has no GATEWAY.yaml")
            elif dep_module not in exports[dep_domain]:
                result.error(mod_name,
                    f"consumes {dep_module}.{dep_interface} but "
                    f"'{dep_module}' is not exported in {dep_domain}/GATEWAY.yaml")
            elif dep_interface not in exports[dep_domain].get(dep_module, set()):
                result.error(mod_name,
                    f"consumes {dep_module}.{dep_interface} but "
                    f"'{dep_interface}' is not exported in {dep_domain}/GATEWAY.yaml")

    # Validate gateway references
    for dname, dexports in exports.items():
        for mod, ifaces in dexports.items():
            if mod not in all_contracts:
                result.error(f"domain/{dname}",
                    f"GATEWAY.yaml exports '{mod}' but module doesn't exist")
            else:
                provides = {p['id'] for p in all_contracts[mod].get('provides', [])
                           if isinstance(p, dict) and 'id' in p}
                for iface in ifaces:
                    if iface not in provides:
                        result.error(f"domain/{dname}",
                            f"GATEWAY.yaml exports {mod}.{iface} "
                            f"but interface doesn't exist in contract")
```

Add call in `main()` after `check_schemas`:
```python
check_gateway(root, contracts, all_contracts, module_paths, result)
```

---

## 7. MANIFEST.yaml — Optional Domain Field

Add optional `domain` field to module entries. Flat modules omit it.
`yaml_editor.manifest_add_module` accepts optional `domain` kwarg.

Example after scaling:
```yaml
modules:
  shared-config: { status: stable, owner: infra-manager }
  user-auth:     { status: stable, owner: backend-manager, domain: backend }
  payments:      { status: draft,  owner: backend-manager, domain: backend }
  web-ui:        { status: draft,  owner: frontend-manager, domain: frontend }
```

`sync_all.py` populates domain field by calling `get_module_domain()` on each
module path.

GRAPH.yaml stays flat — no schema change. Cross-domain info is derived by
combining GRAPH + MANIFEST domain fields.

---

## 8. Documentation Updates

### CLAUDE.md

Add after "Context loading order" section:

```markdown
## Domain scaling (projects with 8+ modules)

For larger projects, modules can be grouped into domains:

    domains/<domain>/<module>/CONTRACT.yaml ...

Each domain has a GATEWAY.yaml that declares which interfaces are visible
to other domains. Within a domain, modules consume each other freely.

Flat modules (`modules/`) and domain modules (`domains/`) can coexist.
Module names must be globally unique.

Context loading order for domain projects adds one step:
1. CONVENTIONS.yaml
2. MANIFEST.yaml (includes domain field per module)
3. GRAPH.yaml
4. **GATEWAY.yaml** (if module is in a domain)
5. CONTRACT.yaml
6. STATE.yaml
7. MEMORY.yaml
```

Update `import_contracts.py` workflow to mention `--domain` flag.

### docs/ARCHITECTURE.md

Add domain layout to file hierarchy diagram.
Add "Domain Scaling" section explaining GATEWAY.yaml.

### README.md

Add domain layout to project structure section.
Mention domain scaling in "When to Use ANMA" (8+ modules).

### docs/QUICKSTART.md

No change needed — quickstart stays flat for simplicity.

---

## 9. Implementation Order

**Phase 1: Foundation (do first, everything depends on this)**
1. Create `tools/discover.py`
2. Write tests for `discover_modules`, `get_module_domain`, `discover_domains`
3. Run 91 existing tests — must still pass (discover.py is additive)

**Phase 2: Core refactor (mechanical, one file at a time)**
4. Refactor `load_all_contracts` in `lint_contracts.py` to use `discover_modules`
5. Run 91 tests — must pass (return type unchanged, no test calls affected)
6. Add `module_paths=None` keyword arg to 9 linter check functions
7. Update `main()` to pass `module_paths=module_paths` to each
8. Run 91 tests — must pass (existing calls don't pass module_paths → default works)
9. Update `checks/check_principles.py` (full Pattern C: **kwargs + module_paths
   param on 5 functions + .get() path replacements) and `checks/check_conventions_pin.py`
   (just **kwargs). **Do not defer the path replacements** — without them, domain
   modules are silently unvalidated by P1-P7.
10. Run tests — must pass
11. Update remaining tools one at a time (Patterns A and B):
    `sync_all` → `dashboard` → `compat_matrix` → `contract_diff` →
    `gen_claude_md` → `gen_contract` → `gen_tests` → `graph_viz` →
    `remove_module` → `verify_contract` → `smoke_test` →
    `import_contracts` → `new_module`
    (import_contracts and new_module last — they get --domain flag in Phase 3)
12. Run tests after each file — must pass

**Phase 3: Domain features (new functionality)**
13. Add `check_gateway` to lint_contracts.py
14. Add `--domain` flag to `import_contracts.py` and `new_module.py`
15. Update `yaml_editor.py` (optional domain field)
16. Update `sync_all.py` (populate domain field)
17. Update `init_project.py` (clear domains/ too)
18. Add `TestDomainScaling` test class
19. Run full test suite

**Phase 4: Benchmark tools**
20. Update `measure_tokens.py` and `eval_degradation.py`
21. Add TODO to `generate_archetypes.py`

**Phase 5: Documentation**
22. Update CONVENTIONS.yaml (append domain_scaling section, bump to v3)
23. Update example CONTRACT.yaml files (conventions_version: 3)
24. Update CLAUDE.md, ARCHITECTURE.md, README.md
25. Run linter --strict — must pass

**Phase 6: Validation**
26. Create test project: 20+ modules across 3-4 domains + some flat
27. Run linter, sync_all, dashboard, smoke_test against it
28. Verify cross-domain gateway enforcement works
29. Run full test suite one final time

---

## 10. Test Project Spec (Phase 6)

Create `test-domain-project/` with:

**Flat modules (in modules/):**
- `shared-config` (infrastructure, frozen)
- `logging` (infrastructure, frozen)

**Domain: backend (4 modules):**
- `user-auth` — provides: register, login, verify_token
- `payments` — provides: process_payment, refund, get_history
- `orders` — provides: create_order, get_order, cancel_order; consumes: payments, user-auth
- `inventory` — provides: check_stock, reserve_item, release_item

**Domain: frontend (3 modules):**
- `web-ui` — consumes: backend/user-auth (verify_token), backend/orders (create_order)
- `admin-panel` — consumes: backend/orders, backend/inventory, backend/payments
- `notifications-ui` — consumes: notification-service

**Domain: messaging (2 modules):**
- `notification-service` — provides: send_notification, get_preferences
- `email-templates` — provides: render_template, list_templates

**backend/GATEWAY.yaml exports:**
- user-auth: [verify_token]
- payments: [process_payment]
- orders: [create_order, get_order]

**messaging/GATEWAY.yaml exports:**
- notification-service: [send_notification]

This gives us: 11 modules, 3 domains, 2 flat, multiple cross-domain deps,
gateway enforcement scenarios.

---

## 11. Risk Checklist

- [ ] `discover_modules()` returns same modules as old `load_all_contracts` scanning for flat projects
- [ ] `load_all_contracts` return type unchanged: `{str: dict}`
- [ ] All 91 existing tests pass after Phase 2 with ZERO test changes
- [ ] 9 linter check signatures use `module_paths=None` default (backward compatible)
- [ ] All path lookups use `.get(mod_name, root / 'modules' / mod_name)` NOT `[mod_name]`
      (direct `[]` causes KeyError in 7 tests where modules lack CONTRACT.yaml)
- [ ] `check_context_budget` keeps `root` param for shared file paths
- [ ] CONVENTIONS.yaml append-only policy respected (new section, no edits to existing rules)
- [ ] `conventions_version` bump causes warnings only (not errors) on old contracts
- [ ] `--strict` linter passes after updating example contracts to v3
- [ ] Flat-only projects work identically (no domains/ directory = no domain behavior)
- [ ] Module names unique across flat + all domains (enforced by discover_modules)
- [ ] Plugin check interface extended with `module_paths` kwarg (backward compatible via **kwargs)
- [ ] Both existing plugins updated with `**kwargs` in `run()` signature
- [ ] `discover_modules` ValueError handled in main() — called AFTER if-not-contracts check
- [ ] check_principles.py: all 5 check_pN functions receive and use module_paths
      (without this, domain modules silently pass all principle checks — verified)
- [ ] smoke_test.py still creates and validates flat layout

---

## 12. Files Changed Summary

| # | File | Change Type | Pattern |
|---|------|-------------|---------|
| 1 | tools/discover.py | **NEW** | Utility |
| 2 | tools/lint_contracts.py | Refactor | A (scan→discover) + new check |
| 3 | tools/sync_all.py | Refactor | A |
| 4 | tools/import_contracts.py | Refactor + feature | A + --domain flag |
| 5 | tools/init_project.py | Refactor | A |
| 6 | tools/new_module.py | Refactor + feature | A + --domain flag |
| 7 | tools/compat_matrix.py | Refactor | B (path lookup) |
| 8 | tools/contract_diff.py | Refactor | B |
| 9 | tools/dashboard.py | Refactor | B |
| 10 | tools/gen_claude_md.py | Refactor | B |
| 11 | tools/gen_contract.py | Refactor | B |
| 12 | tools/gen_tests.py | Refactor | B |
| 13 | tools/graph_viz.py | Refactor | B |
| 14 | tools/remove_module.py | Refactor | B |
| 15 | tools/verify_contract.py | Refactor | B |
| 16 | tools/smoke_test.py | Refactor | B |
| 17 | tools/yaml_editor.py | Schema | D (optional domain field) |
| 18 | tools/gen_graph.py | Minor | D (comment only) |
| 19 | tools/impact.py | None | D (reads flat graph) |
| 20 | tools/plan_migration.py | None | D (reads flat graph) |
| 21 | tools/test_linter.py | Tests | E (new test classes, zero existing test changes) |
| 22 | checks/check_principles.py | Refactor | C (accept module_paths + **kwargs) |
| 23 | checks/check_conventions_pin.py | Minor | C (add **kwargs to prevent crash) |
| 24 | tools/benchmark/measure_tokens.py | Refactor | A |
| 25 | tools/benchmark/eval_degradation.py | Refactor | A |
| 26 | tools/benchmark/generate_archetypes.py | TODO | Comment only |
| 27 | CONVENTIONS.yaml | Append | New domain_scaling section, v3 |
| 28 | CLAUDE.md | Docs | Domain scaling section |
| 29 | docs/ARCHITECTURE.md | Docs | Updated hierarchy + section |
| 30 | README.md | Docs | Updated structure section |
| 31 | modules/*/CONTRACT.yaml | Pin | conventions_version: 3 |
