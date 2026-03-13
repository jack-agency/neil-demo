#!/usr/bin/env python3
"""
seed_groups.py — Création des ensembles de classes et classes par formation.

Version dynamique : lit les formations depuis le manifest, génère des plans
de groupes basés sur l'effectif et le thème de la formation.

Structure des groupes :
- Grandes formations (40+) : Classes CM + Groupes TD + Groupes TP
- Formations moyennes (20-40) : Classe unique + Groupes TD/Atelier
- Petites formations (<20) : Groupes spécialisés uniquement
"""
import requests
import json
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)

COLORS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#34495e", "#16a085", "#c0392b",
    "#2980b9", "#27ae60", "#d35400", "#8e44ad",
]

# ============================================================================
# Group name templates by theme
# ============================================================================

GROUP_TEMPLATES = {
    "sciences": {
        "large_cm": ["Classe A", "Classe B"],
        "td": ["TD {n}"],
        "tp": ["TP {n}"],
        "small": ["Labo {name}"],
        "small_names": ["Physique", "Chimie", "Bio", "Info"],
    },
    "arts": {
        "large_cm": ["Classe A", "Classe B"],
        "atelier": ["Atelier {name}"],
        "atelier_names": ["Dessin-Peinture", "Sculpture-Volume", "Arts numériques", "Photographie"],
        "td": ["TD {n}"],
        "tp": ["TP {n}"],
        "small": ["Projet {name}"],
        "small_names": ["Installation", "Performance", "Numérique", "Vidéo"],
        "research": ["Recherche {name}"],
        "research_names": ["Matériaux", "Image", "Son-Espace", "Corps"],
    },
    "poudlard": {
        "houses": ["Gryffondor", "Serpentard", "Serdaigle", "Poufsouffle"],
        "house_colors": ["#ae0001", "#2a623d", "#222f5b", "#ecb939"],
        "large_cm": ["Gryffondor-Serdaigle", "Poufsouffle-Serpentard"],
        "td": ["TD Maison {n}"],
        "tp": ["TP Pratique {n}"],
        "small": ["Atelier {name}"],
        "small_names": ["Sortilèges", "Potions", "Métamorphose", "Défense"],
        "set_names": {
            "main": "Maisons",
            "td": "Groupes de cours",
            "tp": "Groupes de pratique",
            "small": "Groupes spécialisés",
        },
    },
    "default": {
        "large_cm": ["Classe A", "Classe B"],
        "td": ["TD {n}"],
        "tp": ["TP {n}"],
        "small": ["Groupe {n}"],
    },
}


# ============================================================================
# API helpers
# ============================================================================

def get_formation_students(formation_id, base, headers):
    """Get all students assigned to a formation."""
    r = SESSION.get(f"{base}/formations/{formation_id}/students", headers=headers)
    data = r.json()
    return [s["id"] for s in data.get("students", [])]


def get_existing_group_sets(formation_id, base, headers):
    r = SESSION.get(f"{base}/formations/{formation_id}/groups", headers=headers)
    data = r.json()
    return data.get("groups", [])


def rename_group_set(formation_id, gs_id, name, base, headers):
    r = SESSION.patch(
        f"{base}/formations/{formation_id}/group-sets/{gs_id}",
        headers=headers,
        json={"name": name},
    )
    return r.status_code in (200, 201)


def create_group_set(formation_id, name, base, headers):
    r = SESSION.post(
        f"{base}/formations/{formation_id}/group-sets",
        headers=headers,
        json={"name": name},
    )
    data = r.json()
    return data["id"]


def create_group(formation_id, group_set_id, name, color, capacity, base, headers):
    r = SESSION.post(
        f"{base}/formations/{formation_id}/groups",
        headers=headers,
        json={"groups": {"name": name, "group_set_id": group_set_id, "color": color, "capacity": capacity}},
    )
    data = r.json()
    if isinstance(data, list) and len(data) > 0:
        return data[0]["id"]
    return None


def assign_students_to_group(formation_id, group_id, student_ids, base, headers):
    if not student_ids:
        return True
    r = SESSION.post(
        f"{base}/formations/{formation_id}/groups/{group_id}/students",
        headers=headers,
        json={"students": [{"student_id": sid} for sid in student_ids]},
    )
    return r.status_code in (200, 201)


def split_students(student_ids, n_groups):
    """Split students evenly into n groups."""
    shuffled = list(student_ids)
    random.shuffle(shuffled)
    groups = [[] for _ in range(n_groups)]
    for i, sid in enumerate(shuffled):
        groups[i % n_groups].append(sid)
    return groups


# ============================================================================
# Dynamic group plan builder
# ============================================================================

def get_theme_category(theme):
    """Map formation theme to group template category."""
    if "poudlard" in theme:
        return "poudlard"
    elif "sciences" in theme:
        return "sciences"
    elif "arts" in theme:
        return "arts"
    return "default"


def build_group_plan(formation_students, manifest):
    """
    Build group structure per formation based on student count and theme.
    """
    plan = {}

    for fid, students in sorted(formation_students.items()):
        n = len(students)
        if n == 0:
            continue

        # Get formation theme from manifest
        theme = ""
        for fm_key, fm_data in manifest.get("formations", {}).items():
            if fm_data["id"] == fid:
                theme = fm_data.get("theme", "")
                break

        category = get_theme_category(theme)
        tpl = GROUP_TEMPLATES.get(category, GROUP_TEMPLATES["default"])

        sets = []

        # Poudlard : toujours utiliser les 4 maisons comme base
        if category == "poudlard":
            houses = tpl.get("houses", ["Gryffondor", "Serpentard", "Serdaigle", "Poufsouffle"])
            house_colors = tpl.get("house_colors", COLORS[:4])
            set_names = tpl.get("set_names", {})

            if n >= 20:
                # Maisons principales (4 groupes)
                n_houses = min(4, max(2, n // 5))
                sets.append({
                    "name": set_names.get("main", "Maisons"),
                    "groups": [{"name": houses[i], "capacity": (n // n_houses) + 2,
                                "color": house_colors[i]}
                               for i in range(n_houses)],
                })

                if n >= 30:
                    # Groupes de cours (binômes de maisons)
                    n_td = max(2, (n + 19) // 20)
                    td_pairs = ["Gryffondor-Serdaigle", "Poufsouffle-Serpentard",
                                "Gryffondor-Poufsouffle", "Serdaigle-Serpentard"]
                    sets.append({
                        "name": set_names.get("td", "Groupes de cours"),
                        "groups": [{"name": td_pairs[i % len(td_pairs)], "capacity": (n // n_td) + 2}
                                   for i in range(n_td)],
                    })

                if n >= 40:
                    # Groupes de pratique
                    n_tp = max(3, (n + 14) // 15)
                    tp_names = ["Pratique Sortilèges", "Pratique Potions",
                                "Pratique Métamorphose", "Pratique DCFM"]
                    sets.append({
                        "name": set_names.get("tp", "Groupes de pratique"),
                        "groups": [{"name": tp_names[i % len(tp_names)], "capacity": (n // n_tp) + 2}
                                   for i in range(n_tp)],
                    })
            else:
                # Petits groupes : utiliser les noms spécialisés
                small_names = tpl.get("small_names", houses[:2])
                n_groups = max(2, min(4, n // 3))
                sets.append({
                    "name": set_names.get("small", "Groupes spécialisés"),
                    "groups": [{"name": f"Atelier {small_names[i % len(small_names)]}",
                                "capacity": (n // n_groups) + 2}
                               for i in range(n_groups)],
                })

        elif n >= 40:
            # Large: CM classes + TD groups + TP groups
            sets.append({
                "name": "Classes",
                "groups": [{"name": name, "capacity": (n // 2) + 2} for name in tpl.get("large_cm", ["Classe A", "Classe B"])],
            })

            n_td = max(2, (n + 19) // 20)  # ~20 students per TD group
            td_names = [f"TD {i+1}" for i in range(n_td)]
            sets.append({
                "name": "Groupes de TD",
                "groups": [{"name": name, "capacity": (n // n_td) + 2} for name in td_names],
            })

            n_tp = max(3, (n + 14) // 15)  # ~15 students per TP group
            tp_names = [f"TP {i+1}" for i in range(n_tp)]
            sets.append({
                "name": "Groupes de TP",
                "groups": [{"name": name, "capacity": (n // n_tp) + 2} for name in tp_names],
            })

        elif n >= 20:
            # Medium: single class (or ateliers for arts) + TD groups
            if category == "arts" and "atelier" in tpl:
                # Arts: ateliers instead of classes
                atelier_names = tpl.get("atelier_names", ["Atelier A", "Atelier B", "Atelier C"])
                n_ateliers = min(len(atelier_names), max(2, (n + 14) // 15))
                sets.append({
                    "name": "Ateliers",
                    "groups": [{"name": f"Atelier {atelier_names[i]}" if i < len(atelier_names) else f"Atelier {i+1}",
                                "capacity": (n // n_ateliers) + 2}
                               for i in range(n_ateliers)],
                })
                if n >= 30:
                    n_tp = max(3, (n + 14) // 15)
                    sets.append({
                        "name": "Groupes de TP",
                        "groups": [{"name": f"TP {i+1}", "capacity": (n // n_tp) + 2} for i in range(n_tp)],
                    })
            else:
                # Single class
                fm_name = ""
                for fm_key, fm_data in manifest.get("formations", {}).items():
                    if fm_data["id"] == fid:
                        fm_name = fm_data.get("name", "")
                        break
                # Short label for the class
                if "prépa" in fm_name.lower() or "prepa" in fm_name.lower():
                    class_name = fm_name.split("—")[-1].strip() if "—" in fm_name else fm_name
                elif "master" in fm_name.lower():
                    class_name = "Master 1 " + theme.replace("_", " ").title()
                else:
                    class_name = "Promotion"
                sets.append({
                    "name": "Classe",
                    "groups": [{"name": class_name, "capacity": n + 5}],
                })

                n_td = max(2, (n + 14) // 15)
                sets.append({
                    "name": "Groupes de TD",
                    "groups": [{"name": f"TD {i+1}", "capacity": (n // n_td) + 2} for i in range(n_td)],
                })

        else:
            # Small (<20): specialized groups
            if "stage" in theme or "résidence" in theme:
                small_names = tpl.get("small_names", ["A", "B"])[:2]
                sets.append({
                    "name": "Groupes de laboratoire" if "sciences" in theme else "Groupes de recherche",
                    "groups": [{"name": f"{'Labo' if 'sciences' in theme else 'Recherche'} {small_names[i % len(small_names)]}",
                                "capacity": (n // 2) + 2}
                               for i in range(2)],
                })
            elif "workshop" in theme:
                project_names = tpl.get("small_names", ["A", "B", "C"])[:3]
                sets.append({
                    "name": "Groupes de projet",
                    "groups": [{"name": f"Projet {project_names[i % len(project_names)]}",
                                "capacity": (n // min(3, n)) + 2}
                               for i in range(min(3, max(2, n // 5)))],
                })
            else:
                n_groups = max(2, min(3, n // 5))
                sets.append({
                    "name": "Groupes",
                    "groups": [{"name": f"Groupe {i+1}", "capacity": (n // n_groups) + 2} for i in range(n_groups)],
                })

        plan[fid] = {"sets": sets}

    return plan


# ============================================================================
# Main
# ============================================================================

def seed_groups():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_enrollments")

    random.seed(config.get("meta", {}).get("random_seed", 2026) + 300)

    log_banner("NEIL ERP — Classes et groupes")

    # Fetch students for each formation
    log_section("RÉCUPÉRATION DES ÉTUDIANTS PAR FORMATION")

    formation_ids = sorted(fm["id"] for fm in manifest.get("formations", {}).values())
    if not formation_ids:
        log_error("Aucune formation dans le manifest.")
        sys.exit(1)

    formation_students = {}
    for fid in formation_ids:
        students = get_formation_students(fid, base, headers)
        formation_students[fid] = students
        log_info(f"F{fid}: {len(students)} étudiants")

    # Build group plan
    plan = build_group_plan(formation_students, manifest)
    color_idx = 0

    # Create groups
    log_section("CRÉATION DES CLASSES")
    groups_manifest = {}

    for fid in sorted(plan.keys()):
        plan_config = plan[fid]
        students = formation_students[fid]

        log_info(f"Formation {fid} ({len(students)} étudiants)")

        # Get the formation key for the manifest
        fm_key = None
        for k, v in manifest.get("formations", {}).items():
            if v["id"] == fid:
                fm_key = k
                break

        # Get existing group-sets (rename default one for first set)
        existing_gs = get_existing_group_sets(fid, base, headers)
        default_gs_id = None
        for gs in existing_gs:
            if gs["name"] == "Ensemble de classes par défaut":
                default_gs_id = gs["id"]
                break

        fm_group_data = {"main_group_ids": [], "td_group_ids": [], "tp_group_ids": [], "group_set_ids": []}

        for set_idx, gs_config in enumerate(plan_config["sets"]):
            gs_name = gs_config["name"]

            if set_idx == 0 and default_gs_id:
                rename_group_set(fid, default_gs_id, gs_name, base, headers)
                gs_id = default_gs_id
                log_info(f"  Ensemble: {gs_name} (renommé, id={gs_id})")
            else:
                gs_id = create_group_set(fid, gs_name, base, headers)
                log_info(f"  Ensemble: {gs_name} (id={gs_id})")

            fm_group_data["group_set_ids"].append(gs_id)

            n_groups = len(gs_config["groups"])
            student_splits = split_students(students, n_groups)

            for grp_idx, grp_config in enumerate(gs_config["groups"]):
                color = grp_config.get("color", COLORS[color_idx % len(COLORS)])
                color_idx += 1

                grp_id = create_group(fid, gs_id, grp_config["name"], color, grp_config["capacity"], base, headers)
                if grp_id is None:
                    log_error(f"  Création groupe {grp_config['name']} échouée")
                    continue

                grp_students = student_splits[grp_idx]
                assign_students_to_group(fid, grp_id, grp_students, base, headers)
                log_info(f"    {grp_config['name']}: {len(grp_students)} étudiants (id={grp_id})")

                # Categorize group IDs
                name_lower = grp_config["name"].lower()
                gs_name_lower = gs_name.lower()
                if "td" in name_lower or "cours" in gs_name_lower:
                    fm_group_data["td_group_ids"].append(grp_id)
                elif "tp" in name_lower or "pratique" in gs_name_lower:
                    fm_group_data["tp_group_ids"].append(grp_id)
                else:
                    fm_group_data["main_group_ids"].append(grp_id)

        if fm_key:
            groups_manifest[fm_key] = fm_group_data

    # Store in manifest
    manifest["groups"] = groups_manifest
    mark_step_complete(manifest, "seed_groups")
    save_manifest(manifest)

    # Summary
    total_sets = sum(len(c["sets"]) for c in plan.values())
    total_groups = sum(len(gs["groups"]) for c in plan.values() for gs in c["sets"])
    log_banner("CLASSES ET GROUPES TERMINÉS")
    print(f"  {len(plan)} formations")
    print(f"  {total_sets} ensembles de classes")
    print(f"  {total_groups} classes au total")
    print()


if __name__ == "__main__":
    seed_groups()
