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
        for d in modules_dir.iterdir():
            if d.is_dir() and (d / 'CONTRACT.yaml').exists():
                found[d.name] = d

    # Domain layout: domains/<domain>/<module>/
    domains_dir = root / 'domains'
    if domains_dir.is_dir():
        for domain_dir in domains_dir.iterdir():
            if not domain_dir.is_dir() or domain_dir.name.startswith('.'):
                continue
            # Skip GATEWAY.yaml and non-directory entries
            for d in domain_dir.iterdir():
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
