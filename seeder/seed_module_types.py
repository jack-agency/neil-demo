#!/usr/bin/env python3
"""
seed_module_types.py — Création des types de modules pédagogiques pour chaque formation,
puis assignation automatique à chaque module en fonction de son nom.

Version dynamique : lit les IDs de formations depuis seed_manifest.json.
"""

import requests
import json
import sys
import re
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
)

# ============================================================================
# Types de modules — définis une fois, créés dans chaque formation
# ============================================================================

MODULE_TYPES = [
    "Cours magistral",
    "Travaux dirigés",
    "Travaux pratiques",
    "Atelier",
    "Projet",
    "Stage / Résidence",
    "Examen / Concours",
    "Séminaire / Conférence",
    "Soutenance / Restitution",
]

# ============================================================================
# Règles d'assignation : patterns → type
# ============================================================================

ASSIGNMENT_RULES = [
    (r"(?i)\b(soutenance|restitution|jury|vernissage|bilan)\b", "Soutenance / Restitution"),
    (r"(?i)\b(examen|concours blanc|concours|évaluation|colle[s]?)\b", "Examen / Concours"),
    (r"(?i)\b(séminaire|conférence[s]?|invité[s]?)\b", "Séminaire / Conférence"),
    (r"(?i)\b(stage|résidence|convention|cahier de laboratoire|rapport de stage|journal de recherche)\b", "Stage / Résidence"),
    (r"(?i)\bTP\b", "Travaux pratiques"),
    (r"(?i)\bTD\b", "Travaux dirigés"),
    (r"(?i)\b(atelier|workshop|accrochage|installation in situ|land art)\b", "Atelier"),
    (r"(?i)\b(projet|portfolio|poster scientifique|catalogue|documentation du processus|brief)\b", "Projet"),
    (r"(?i)\b(insertion professionnelle|connaissance de l.entreprise|droit du travail|réseaux professionnels|CV artistique|préparation exposition|rencontres professionnelles|médiation)\b", "Stage / Résidence"),
]


def get_type_name(module_name):
    for pattern, type_name in ASSIGNMENT_RULES:
        if re.search(pattern, module_name):
            return type_name
    return "Cours magistral"


# ============================================================================
# API helpers
# ============================================================================

def get_module_types(fid, base, headers):
    r = SESSION.get(f"{base}/formations/{fid}/module-types", headers=headers)
    return r.json().get("module_types", [])

def create_module_type(fid, name, base, headers):
    r = SESSION.post(f"{base}/formations/{fid}/module-types", headers=headers, json={"name": name})
    if r.status_code in (200, 201):
        return r.json()["id"]
    elif r.status_code == 409:
        existing = get_module_types(fid, base, headers)
        for mt in existing:
            if mt["name"] == name:
                return mt["id"]
    log_error(f"Création type '{name}' pour F{fid}: {r.status_code} {r.text[:200]}")
    return None

def delete_module_type(fid, type_id, base, headers):
    r = SESSION.delete(f"{base}/formations/{fid}/module-types/{type_id}", headers=headers)
    return r.status_code

def get_modules(fid, base, headers):
    r = SESSION.get(f"{base}/formations/{fid}/modules", headers=headers)
    return r.json().get("modules", [])

def assign_module_type(fid, module_id, type_id, base, headers):
    r = SESSION.patch(f"{base}/formations/{fid}/modules/{module_id}", headers=headers, json={"module_type_id": type_id})
    return r.status_code in (200, 201)


# ============================================================================
# Main
# ============================================================================

def seed_module_types():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_formulas")
    require_step(manifest, "seed_teaching_units")

    log_banner("NEIL ERP — Types de modules pédagogiques")

    # Get formation IDs from manifest
    formation_ids = sorted(fm["id"] for fm in manifest.get("formations", {}).values())
    if not formation_ids:
        log_error("Aucune formation dans le manifest.")
        sys.exit(1)

    log_info(f"{len(formation_ids)} formations trouvées dans le manifest")

    # Cleanup
    log_section("CLEANUP")
    for fid in formation_ids:
        types = get_module_types(fid, base, headers)
        if types:
            modules = get_modules(fid, base, headers)
            for m in modules:
                if m.get("module_type_id") is not None:
                    assign_module_type(fid, m["id"], None, base, headers)
            for t in types:
                delete_module_type(fid, t["id"], base, headers)
            log_info(f"  F{fid}: {len(types)} types supprimés, {len(modules)} modules reset")
        else:
            log_info(f"  F{fid}: aucun type existant")
    print()

    # Create types
    log_section("CRÉATION DES TYPES DE MODULES")
    type_map = {}
    for fid in formation_ids:
        type_map[fid] = {}
        created = 0
        for type_name in MODULE_TYPES:
            type_id = create_module_type(fid, type_name, base, headers)
            if type_id:
                type_map[fid][type_name] = type_id
                created += 1
        log_info(f"  F{fid}: {created} types créés")
    print()

    # Assign types
    log_section("ASSIGNATION DES TYPES AUX MODULES")
    total_assigned = 0
    total_modules = 0
    stats = {}

    for fid in formation_ids:
        modules = get_modules(fid, base, headers)
        assigned = 0
        formation_stats = {}

        for m in modules:
            type_name = get_type_name(m["name"])
            type_id = type_map.get(fid, {}).get(type_name)
            if type_id:
                ok = assign_module_type(fid, m["id"], type_id, base, headers)
                if ok:
                    assigned += 1
                    formation_stats[type_name] = formation_stats.get(type_name, 0) + 1
                    stats[type_name] = stats.get(type_name, 0) + 1

        total_assigned += assigned
        total_modules += len(modules)

        detail = ", ".join(f"{k}: {v}" for k, v in sorted(formation_stats.items(), key=lambda x: -x[1]))
        log_info(f"  F{fid} ({len(modules)} modules): {assigned} assignés — {detail}")

    print()

    # Store in manifest
    mark_step_complete(manifest, "seed_module_types")
    save_manifest(manifest)

    log_banner("TYPES DE MODULES TERMINÉS")
    print(f"  {len(formation_ids)} formations")
    print(f"  {len(MODULE_TYPES)} types créés par formation ({len(MODULE_TYPES) * len(formation_ids)} au total)")
    print(f"  {total_assigned}/{total_modules} modules assignés")
    print()
    print("  Répartition globale :")
    for type_name, count in sorted(stats.items(), key=lambda x: -x[1]):
        pct = count / total_modules * 100 if total_modules else 0
        bar = "█" * int(pct / 2)
        print(f"    {type_name:30s} {count:4d} ({pct:4.1f}%) {bar}")
    print()


if __name__ == "__main__":
    seed_module_types()
