#!/usr/bin/env python3
"""
seed_teaching_units.py — Création des UE, sous-UE et modules (cours) pour chaque formation.

Version dynamique : lit les thèmes depuis seed_config.json et les IDs de formations
depuis seed_manifest.json. Chaque module = 1 cours de 1h, 2h ou 4h.
Le total des heures de modules couvre la durée prévue de la formation.
"""
import requests
import json
import sys
import math
import os
import copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, api_get, api_post, api_patch, api_delete,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
    THEME_DEFINITIONS, SESSION,
)

# ============================================================================
# API helpers
# ============================================================================

def get_modules(fid, base, headers):
    r = SESSION.get(f"{base}/formations/{fid}/modules", headers=headers, timeout=30)
    return r.json()

def delete_module(fid, module_id, base, headers):
    r = SESSION.delete(f"{base}/formations/{fid}/modules/{module_id}", headers=headers, timeout=30)
    return r.status_code

def delete_ue(fid, node_id, base, headers):
    r = SESSION.delete(f"{base}/formations/{fid}/teaching-units/{node_id}", headers=headers, timeout=30)
    return r.status_code

def get_default_ue(fid, base, headers):
    """Récupère l'UE par défaut d'une formation (créée automatiquement par Neil)."""
    r = SESSION.get(f"{base}/formations/{fid}/modules", headers=headers, timeout=30)
    nodes = r.json().get("nodes", [])
    for n in nodes:
        if n.get("unit") and "défaut" in n["unit"].lower():
            return n["id"]
    return None

def rename_ue(fid, node_id, name, order, base, headers):
    r = SESSION.patch(
        f"{base}/formations/{fid}/teaching-units/{node_id}",
        headers=headers,
        json={"unit": name, "order": order},
        timeout=30,
    )
    return r.status_code in (200, 201)

def create_ue(fid, name, order, parent_node_id=None, base=None, headers=None):
    body = {"unit": name, "order": order}
    if parent_node_id is not None:
        body["parent_node_id"] = parent_node_id
    r = SESSION.post(f"{base}/formations/{fid}/teaching-units", headers=headers, json=body, timeout=30)
    data = r.json()
    return data["node"]["id"]

def create_module(fid, parent_node_id, name, order, base, headers):
    body = {
        "modules": {"name": name},
        "parent_node_id": parent_node_id,
        "order": order,
        "is_active": True,
    }
    r = SESSION.post(f"{base}/formations/{fid}/modules", headers=headers, json=body, timeout=30)
    data = r.json()
    if isinstance(data, list) and len(data) > 0:
        return data[0]["id"]
    elif isinstance(data, dict) and "id" in data:
        return data["id"]
    return None

def set_module_duration(fid, module_id, duration_seconds, base, headers):
    SESSION.patch(
        f"{base}/formations/{fid}/modules/{module_id}",
        headers=headers,
        json={"default_duration": duration_seconds},
        timeout=30,
    )


# ============================================================================
# Cleanup
# ============================================================================

def cleanup_formation(fid, base, headers):
    data = get_modules(fid, base, headers)
    modules = data.get("modules", [])
    nodes = data.get("nodes", [])

    for m in modules:
        delete_module(fid, m["id"], base, headers)
    log_info(f"  Supprimé {len(modules)} modules")

    for _ in range(5):
        data = get_modules(fid, base, headers)
        nodes = data.get("nodes", [])
        ue_nodes = [n for n in nodes if n.get("unit") and "défaut" not in n["unit"].lower()]
        if not ue_nodes:
            break
        ue_nodes.sort(key=lambda n: len((n.get("path") or "").split("/")), reverse=True)
        for n in ue_nodes:
            delete_ue(fid, n["id"], base, headers)

    log_ok(f"  Cleanup terminé")


# ============================================================================
# Hour distribution and module generation (same algorithm as before)
# ============================================================================

def distribute_hours(ues_definition, target_hours):
    """
    Distribue les heures proportionnellement entre UEs → sous-UEs → modules.
    ues_definition: list of UE dicts with sub_ues, each with courses and weight.
    """
    total_weight = 0
    for ue in ues_definition:
        for sub in ue["sub_ues"]:
            total_weight += sub["weight"]

    if total_weight == 0:
        return ues_definition

    result = []
    assigned_total = 0
    all_subs = []

    for ue in ues_definition:
        ue_result = {"name": ue["name"], "sub_ues": []}
        for sub in ue["sub_ues"]:
            sub_hours = round(target_hours * sub["weight"] / total_weight)
            sub_hours = max(sub_hours, len(sub["courses"]))
            all_subs.append((ue_result, sub, sub_hours))
            assigned_total += sub_hours
        result.append(ue_result)

    # Adjust to match target exactly
    diff = target_hours - assigned_total
    all_subs.sort(key=lambda x: x[2], reverse=True)
    i = 0
    while diff != 0:
        step = 2 if abs(diff) > len(all_subs) else (1 if diff > 0 else -1)
        if diff > 0:
            idx = i % len(all_subs)
            all_subs[idx] = (all_subs[idx][0], all_subs[idx][1], all_subs[idx][2] + step)
            diff -= step
        else:
            idx = i % len(all_subs)
            if all_subs[idx][2] > len(all_subs[idx][1]["courses"]):
                all_subs[idx] = (all_subs[idx][0], all_subs[idx][1], all_subs[idx][2] - 1)
                diff += 1
        i += 1
        if i > 1000:
            break

    # Generate modules for each sub-UE
    for ue_result, sub, sub_hours in all_subs:
        modules = generate_modules(sub["courses"], sub_hours)
        sub_result = {"name": sub["name"], "modules": modules}
        ue_result["sub_ues"].append(sub_result)

    return result


def generate_modules(courses, target_hours):
    """
    Génère des modules de 1h, 2h ou 4h pour remplir le total d'heures.
    """
    n_courses = len(courses)
    if n_courses == 0:
        return []

    base_per_course = target_hours // n_courses
    remainder = target_hours % n_courses

    modules = []
    for i, course in enumerate(courses):
        course_hours = base_per_course + (1 if i < remainder else 0)
        if course_hours <= 0:
            continue

        sessions = []
        remaining = course_hours
        session_num = 1

        while remaining > 0:
            if remaining >= 4:
                h = 4
            elif remaining >= 2:
                h = 2
            else:
                h = 1
            sessions.append((session_num, h))
            remaining -= h
            session_num += 1

        if len(sessions) == 1:
            modules.append((course, sessions[0][1]))
        else:
            lower = course.lower()
            if lower.startswith("tp "):
                label = "TP"
            elif lower.startswith("td "):
                label = "TD"
            elif lower.startswith("projet"):
                label = "Projet"
            elif lower.startswith("atelier"):
                label = "Atelier"
            elif lower.startswith("stage") or lower.startswith("résidence"):
                label = "Journée"
            elif lower.startswith("concours"):
                label = "Session"
            elif lower.startswith("colles"):
                label = "Colle"
            else:
                label = "Cours"
            for num, h in sessions:
                modules.append((f"{course} — {label} {num}", h))

    return modules


# ============================================================================
# Build structures from config themes
# ============================================================================

def build_structures_from_config(config, manifest):
    """
    Construit les structures d'UE/sous-UE/cours pour chaque formation,
    en lisant les thèmes depuis la config et les IDs depuis le manifest.
    """
    structures = {}  # formation_id -> ues_definition
    hours_map = {}   # formation_id -> target_hours

    themes = config.get("teaching_units", {}).get("themes", {})

    for fm_key, fm_data in manifest.get("formations", {}).items():
        fid = fm_data["id"]
        hours = fm_data["hours"]
        theme_key = fm_data.get("theme", "")

        if theme_key not in themes:
            log_warn(f"Thème '{theme_key}' non trouvé pour la formation '{fm_data['name']}' (F{fid})")
            continue

        theme = themes[theme_key]

        # Deep copy the UE definitions so we can modify weights
        ues = copy.deepcopy(theme["ues"])

        # Add "UE" prefix if not already present
        for ue_order, ue in enumerate(ues, 1):
            if not ue["name"].startswith("UE"):
                ue["name"] = f"UE{ue_order} — {ue['name']}"

        structures[fid] = ues
        hours_map[fid] = hours

    return structures, hours_map


# ============================================================================
# Verify & build
# ============================================================================

def verify_and_build(structures, hours_map):
    """Distribute hours and verify totals match targets."""
    result = {}
    log_section("VÉRIFICATION DES HEURES")
    all_ok = True

    for fid in sorted(structures.keys()):
        target = hours_map[fid]
        distributed = distribute_hours(structures[fid], target)
        total = sum(h for ue in distributed for sub in ue["sub_ues"] for _, h in sub["modules"])
        status = "OK" if total == target else f"ERREUR ({total}h)"
        if total != target:
            all_ok = False
        log_info(f"  F{fid}: {total}h / {target}h — {status}")

        n_modules = sum(len(sub["modules"]) for ue in distributed for sub in ue["sub_ues"])
        n_sub_ues = sum(len(ue["sub_ues"]) for ue in distributed)
        n_ues = len(distributed)
        log_info(f"         {n_ues} UEs, {n_sub_ues} sous-UEs, {n_modules} modules")

        result[fid] = distributed

    print()
    return result, all_ok


# ============================================================================
# Seed
# ============================================================================

def seed_formation(fid, ues, base, headers):
    log_info(f"Formation {fid}")
    module_count = 0
    total_hours = 0

    default_ue_id = get_default_ue(fid, base, headers)

    for ue_order, ue in enumerate(ues, 1):
        if ue_order == 1 and default_ue_id:
            rename_ue(fid, default_ue_id, ue["name"], ue_order, base, headers)
            ue_node_id = default_ue_id
            log_info(f"  UE: {ue['name']} (node={ue_node_id}) [renommée]")
        else:
            ue_node_id = create_ue(fid, ue["name"], ue_order, base=base, headers=headers)
            log_info(f"  UE: {ue['name']} (node={ue_node_id})")

        for sub_order, sub in enumerate(ue["sub_ues"], 1):
            sub_node_id = create_ue(fid, sub["name"], sub_order, parent_node_id=ue_node_id, base=base, headers=headers)
            sub_hours = sum(h for _, h in sub["modules"])
            log_info(f"    Sous-UE: {sub['name']} ({sub_hours}h, {len(sub['modules'])} mod, node={sub_node_id})")

            for mod_order, (mod_name, mod_hours) in enumerate(sub["modules"], 1):
                mod_id = create_module(fid, sub_node_id, mod_name, mod_order, base, headers)
                if mod_id:
                    set_module_duration(fid, mod_id, mod_hours * 3600, base, headers)
                    module_count += 1
                    total_hours += mod_hours

    log_ok(f"  → {module_count} modules = {total_hours}h")
    print()


# ============================================================================
# Main
# ============================================================================

def seed_teaching_units():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_formulas")

    log_banner("NEIL ERP — Unités d'enseignement & Modules")

    structures, hours_map = build_structures_from_config(config, manifest)

    if not structures:
        log_error("Aucune formation avec thème trouvée. Vérifiez la config et le manifest.")
        sys.exit(1)

    distributed, ok = verify_and_build(structures, hours_map)

    if not ok:
        log_error("Les heures ne correspondent pas.")
        sys.exit(1)

    # Apply module_coverage_pct — trim modules if < 100%
    module_coverage_pct = config.get("seeder", {}).get("module_coverage_pct", 100)
    if module_coverage_pct < 100:
        import math as _math
        for fid, ues in distributed.items():
            for ue in ues:
                for sub in ue["sub_ues"]:
                    n = len(sub["modules"])
                    keep = max(1, _math.ceil(n * module_coverage_pct / 100))
                    sub["modules"] = sub["modules"][:keep]
        log_info(f"Couverture modules : {module_coverage_pct}% (modules réduits)")

    # Cleanup
    log_section("CLEANUP")
    for fid in sorted(distributed.keys()):
        log_info(f"Formation {fid}:")
        cleanup_formation(fid, base, headers)
    print()

    # Seed
    log_section("CRÉATION")
    for fid in sorted(distributed.keys()):
        seed_formation(fid, distributed[fid], base, headers)

    # Summary
    total_modules = sum(
        len(sub["modules"])
        for ues in distributed.values()
        for ue in ues for sub in ue["sub_ues"]
    )
    total_sub_ues = sum(
        len(ue["sub_ues"])
        for ues in distributed.values()
        for ue in ues
    )
    total_ues = sum(len(ues) for ues in distributed.values())
    total_hours = sum(
        h for ues in distributed.values()
        for ue in ues for sub in ue["sub_ues"]
        for _, h in sub["modules"]
    )

    # Store in manifest
    manifest["teaching_units"] = {
        "total_ues": total_ues,
        "total_sub_ues": total_sub_ues,
        "total_modules": total_modules,
        "total_hours": total_hours,
    }
    mark_step_complete(manifest, "seed_teaching_units")
    save_manifest(manifest)

    log_banner("UE & MODULES TERMINÉS")
    print(f"  {len(distributed)} formations")
    print(f"  {total_ues} UEs")
    print(f"  {total_sub_ues} sous-UEs")
    print(f"  {total_modules} modules (cours)")
    print(f"  {total_hours}h au total")
    print()


if __name__ == "__main__":
    seed_teaching_units()
