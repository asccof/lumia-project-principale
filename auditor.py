# auditor.py
import os, re, inspect
from collections import defaultdict
from flask import current_app as app
from flask.cli import with_appcontext
import click

_URLFOR_RE = re.compile(r"""url_for\(\s*['"]([a-zA-Z_][a-zA-Z0-9_]*)['"]""")

def _iter_template_files(base):
    for root, _, files in os.walk(base):
        for f in files:
            if f.endswith((".html", ".jinja", ".j2")):
                yield os.path.join(root, f)

def _scan_templates(template_dir):
    used = set()
    locations = defaultdict(set)
    for p in _iter_template_files(template_dir):
        try:
            txt = open(p, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in _URLFOR_RE.finditer(txt):
            ep = m.group(1)
            used.add(ep)
            locations[ep].add(os.path.relpath(p))
    return used, locations

@click.command("audit")
@with_appcontext
def audit():
    """
    Audit clair et net:
    - Endpoints manquants (appelés dans les templates mais absents)
    - Collisions de règles (même URL+methods -> endpoints différents)
    - Fonctions exposées sous plusieurs endpoints (soupçon de doublons)
    - Endpoints jamais utilisés dans les templates
    """
    proj = os.path.dirname(os.path.abspath(app.root_path))
    tpl_dir = os.path.join(app.root_path, "templates")

    print("=== AUDIT ROUTES & TEMPLATES ===")
    print(f"- templates dir: {tpl_dir}")

    # 1) endpoints réellement enregistrés
    endpoints = set(app.view_functions.keys())
    print(f"- endpoints enregistrés: {len(endpoints)}")

    # 2) cartes rule -> endpoints pour détecter collisions
    rule_map = defaultdict(list)
    for rule in app.url_map.iter_rules():
        rule_map[(rule.rule, tuple(sorted(rule.methods or [])))].append(rule.endpoint)

    collisions = []
    for (rule, methods), eps in rule_map.items():
        if len(set(eps)) > 1:
            collisions.append((rule, sorted(set(methods)), sorted(set(eps))))

    # 3) mêmes fonctions python exposées sous plusieurs endpoints
    func_to_eps = defaultdict(list)
    for ep, fn in app.view_functions.items():
        func_to_eps[fn].append(ep)
    multi = {fn: eps for fn, eps in func_to_eps.items() if len(eps) > 1}

    # 4) endpoints utilisés par les templates
    used, where = _scan_templates(tpl_dir)

    missing = sorted([ep for ep in used if ep not in endpoints])
    unused  = sorted([ep for ep in endpoints if ep not in used and not ep.startswith(("static",))])

    # 5) rendu clair
    def _section(title):
        print("\n" + title)
        print("-" * len(title))

    _section("A. Endpoints APPELÉS dans les templates mais INEXISTANTS")
    if missing:
        for ep in missing:
            files = ", ".join(sorted(list(where.get(ep, [])))[:5])
            more = "" if len(where.get(ep, [])) <= 5 else " ..."
            print(f"  ! {ep:<30} (vu dans: {files}{more})")
    else:
        print("  OK — aucun endpoint manquant.")

    _section("B. Collisions de règles (même URL+methods -> endpoints différents)")
    if collisions:
        for rule, methods, eps in collisions:
            print(f"  ! {rule} {methods} -> {eps}")
    else:
        print("  OK — aucune collision.")

    _section("C. Fonctions exposées sous plusieurs endpoints (doublons possibles)")
    if multi:
        for fn, eps in multi.items():
            name = getattr(fn, "__name__", str(fn))
            file = inspect.getsourcefile(fn) or "<?>"
            print(f"  ? {name} ({file}): {eps}")
    else:
        print("  OK — aucun doublon de fonction exposée.")

    _section("D. Endpoints JAMAIS appelés depuis les templates")
    if unused:
        for ep in unused:
            print(f"  · {ep}")
    else:
        print("  OK — tous les endpoints sont utilisés (ou usage programmatique seulement).")

    print("\nRésumé:")
    print(f"  Manquants: {len(missing)}  |  Collisions: {len(collisions)}  |  Doublons-fn: {len(multi)}  |  Inusités: {len(unused)}")
