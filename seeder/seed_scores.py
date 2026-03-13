#!/usr/bin/env python3
"""
seed_scores.py — Génération des relevés de notes et notes composées pour toutes les formations.

Version dynamique : lit les formations et groupes depuis le manifest,
génère des templates de score par thème.

Pour chaque formation, crée :
  - Des relevés de notes (scores) sur des modules spécifiques de chaque sous-UE
  - Une note composée par sous-UE agrégeant les relevés avec coefficients
  - Publie tous les scores

Notes générées avec distribution gaussienne réaliste (moy ~11-13/20, σ ~2.5-3.5).
"""

import requests
import json
import sys
import random
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, api_get, api_post, api_patch,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
)


# ============================================================================
# Score templates by theme
# ============================================================================

SCORE_TEMPLATES_BY_THEME = {
    "sciences_generales": {
        "score_templates": [
            {"name": "Contrôle continu — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Examen — {sub_ue}", "coeff": 2, "date_offset_months": 5},
        ],
        "extra_template": {"name": "Partiel — {sub_ue}", "coeff": 1, "date_offset_months": 4},
        "extra_threshold": 30,
    },
    "sciences_prepa": {
        "score_templates": [
            {"name": "Devoir surveillé — {sub_ue}", "coeff": 1, "date_offset_months": 2},
            {"name": "Contrôle — {sub_ue}", "coeff": 2, "date_offset_months": 5},
        ],
        "extra_template": {"name": "Oral blanc — {sub_ue}", "coeff": 1, "date_offset_months": 6},
        "extra_threshold": 11,
    },
    "sciences_stage": {
        "score_templates": [
            {"name": "Rapport de stage — {sub_ue}", "coeff": 2, "date_offset_months": 7},
            {"name": "Soutenance — {sub_ue}", "coeff": 1, "date_offset_months": 8},
        ],
    },
    "arts_theorie": {
        "score_templates": [
            {"name": "Dissertation — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Examen — {sub_ue}", "coeff": 2, "date_offset_months": 5},
        ],
        "extra_template": {"name": "Exposé oral — {sub_ue}", "coeff": 1, "date_offset_months": 6},
        "extra_threshold": 16,
    },
    "arts_pratique": {
        "score_templates": [
            {"name": "Évaluation pratique — {sub_ue}", "coeff": 2, "date_offset_months": 5},
            {"name": "Portfolio — {sub_ue}", "coeff": 1, "date_offset_months": 7},
        ],
    },
    "arts_master": {
        "score_templates": [
            {"name": "Projet — {sub_ue}", "coeff": 2, "date_offset_months": 5},
            {"name": "Jury — {sub_ue}", "coeff": 2, "date_offset_months": 7},
        ],
        "extra_template": {"name": "Essai critique — {sub_ue}", "coeff": 1, "date_offset_months": 4},
        "extra_threshold": 15,
    },
    "arts_workshop": {
        "score_templates": [
            {"name": "Présentation — {sub_ue}", "coeff": 1, "date_offset_months": 6},
            {"name": "Évaluation par les pairs — {sub_ue}", "coeff": 1, "date_offset_months": 7},
        ],
    },
    "arts_stage": {
        "score_templates": [
            {"name": "Rapport de recherche — {sub_ue}", "coeff": 2, "date_offset_months": 7},
            {"name": "Soutenance — {sub_ue}", "coeff": 1, "date_offset_months": 8},
        ],
    },
    # ── Poudlard themes ──
    "poudlard_tronc": {
        "score_templates": [
            {"name": "Contrôle de baguette — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Examen BUSE — {sub_ue}", "coeff": 2, "date_offset_months": 6},
        ],
        "extra_template": {"name": "Épreuve pratique — {sub_ue}", "coeff": 1, "date_offset_months": 5},
        "extra_threshold": 25,
    },
    "poudlard_aspic": {
        "score_templates": [
            {"name": "Devoir sur parchemin — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Examen ASPIC — {sub_ue}", "coeff": 2, "date_offset_months": 6},
        ],
        "extra_template": {"name": "Épreuve pratique ASPIC — {sub_ue}", "coeff": 1, "date_offset_months": 7},
        "extra_threshold": 15,
    },
    "poudlard_master": {
        "score_templates": [
            {"name": "Projet de recherche — {sub_ue}", "coeff": 2, "date_offset_months": 5},
            {"name": "Jury du Ministère — {sub_ue}", "coeff": 2, "date_offset_months": 7},
        ],
        "extra_template": {"name": "Mémoire de spécialisation — {sub_ue}", "coeff": 1, "date_offset_months": 8},
        "extra_threshold": 10,
    },
    "poudlard_prepa": {
        "score_templates": [
            {"name": "Épreuve d'initiation — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Test de répartition — {sub_ue}", "coeff": 2, "date_offset_months": 6},
        ],
    },
    "poudlard_quidditch": {
        "score_templates": [
            {"name": "Épreuve de vol — {sub_ue}", "coeff": 2, "date_offset_months": 4},
            {"name": "Tournoi inter-maisons — {sub_ue}", "coeff": 1, "date_offset_months": 6},
        ],
    },
    "poudlard_stage": {
        "score_templates": [
            {"name": "Rapport de stage magique — {sub_ue}", "coeff": 2, "date_offset_months": 7},
            {"name": "Soutenance devant le jury — {sub_ue}", "coeff": 1, "date_offset_months": 8},
        ],
    },
    # ── Droit themes ──
    "droit_general": {
        "score_templates": [
            {"name": "Commentaire d'arrêt — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Examen écrit — {sub_ue}", "coeff": 2, "date_offset_months": 6},
        ],
        "extra_template": {"name": "Grand oral — {sub_ue}", "coeff": 1, "date_offset_months": 5},
        "extra_threshold": 20,
    },
    "droit_prepa": {
        "score_templates": [
            {"name": "Cas pratique — {sub_ue}", "coeff": 1, "date_offset_months": 2},
            {"name": "Galop d'essai — {sub_ue}", "coeff": 2, "date_offset_months": 5},
        ],
    },
    "droit_master": {
        "score_templates": [
            {"name": "Mémoire — {sub_ue}", "coeff": 2, "date_offset_months": 5},
            {"name": "Soutenance — {sub_ue}", "coeff": 2, "date_offset_months": 7},
        ],
        "extra_template": {"name": "Note de synthèse — {sub_ue}", "coeff": 1, "date_offset_months": 4},
        "extra_threshold": 15,
    },
    "droit_stage": {
        "score_templates": [
            {"name": "Rapport de stage — {sub_ue}", "coeff": 2, "date_offset_months": 7},
            {"name": "Soutenance de stage — {sub_ue}", "coeff": 1, "date_offset_months": 8},
        ],
    },
    # ── Ingénierie themes ──
    "ingenierie_general": {
        "score_templates": [
            {"name": "Bureau d'études — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Examen — {sub_ue}", "coeff": 2, "date_offset_months": 6},
        ],
        "extra_template": {"name": "Projet technique — {sub_ue}", "coeff": 1, "date_offset_months": 5},
        "extra_threshold": 25,
    },
    "ingenierie_prepa": {
        "score_templates": [
            {"name": "Devoir surveillé — {sub_ue}", "coeff": 1, "date_offset_months": 2},
            {"name": "Contrôle — {sub_ue}", "coeff": 2, "date_offset_months": 5},
        ],
    },
    "ingenierie_master": {
        "score_templates": [
            {"name": "Projet de fin d'études — {sub_ue}", "coeff": 2, "date_offset_months": 5},
            {"name": "Soutenance PFE — {sub_ue}", "coeff": 2, "date_offset_months": 7},
        ],
        "extra_template": {"name": "Article scientifique — {sub_ue}", "coeff": 1, "date_offset_months": 6},
        "extra_threshold": 10,
    },
    "ingenierie_stage": {
        "score_templates": [
            {"name": "Rapport de stage ingénieur — {sub_ue}", "coeff": 2, "date_offset_months": 7},
            {"name": "Soutenance — {sub_ue}", "coeff": 1, "date_offset_months": 8},
        ],
    },
    # ── Santé themes ──
    "sante_general": {
        "score_templates": [
            {"name": "QCM — {sub_ue}", "coeff": 1, "date_offset_months": 3},
            {"name": "Examen — {sub_ue}", "coeff": 2, "date_offset_months": 6},
        ],
        "extra_template": {"name": "Épreuve clinique — {sub_ue}", "coeff": 1, "date_offset_months": 5},
        "extra_threshold": 25,
    },
    "sante_prepa": {
        "score_templates": [
            {"name": "Concours blanc — {sub_ue}", "coeff": 1, "date_offset_months": 2},
            {"name": "Épreuve écrite — {sub_ue}", "coeff": 2, "date_offset_months": 5},
        ],
    },
    "sante_master": {
        "score_templates": [
            {"name": "Mémoire de recherche — {sub_ue}", "coeff": 2, "date_offset_months": 5},
            {"name": "Soutenance — {sub_ue}", "coeff": 2, "date_offset_months": 7},
        ],
        "extra_template": {"name": "Étude de cas clinique — {sub_ue}", "coeff": 1, "date_offset_months": 4},
        "extra_threshold": 12,
    },
    "sante_stage": {
        "score_templates": [
            {"name": "Rapport de stage hospitalier — {sub_ue}", "coeff": 2, "date_offset_months": 7},
            {"name": "Évaluation clinique — {sub_ue}", "coeff": 1, "date_offset_months": 8},
        ],
    },
}

# Default template for unknown themes
DEFAULT_SCORE_TEMPLATE = {
    "score_templates": [
        {"name": "Contrôle — {sub_ue}", "coeff": 1, "date_offset_months": 3},
        {"name": "Examen — {sub_ue}", "coeff": 2, "date_offset_months": 6},
    ],
}


# ============================================================================
# Grade generation
# ============================================================================

def generate_grades(student_scores, mean, std, absent_rate):
    """Génère des notes réalistes pour une liste de student_scores."""
    results = []
    for ss in student_scores:
        if random.random() < absent_rate:
            results.append({"id": ss["id"], "score": None, "is_missing": 1})
        else:
            score = int(random.gauss(mean, std))
            score = max(200, min(2000, score))
            score = round(score / 50) * 50  # arrondi à 0.5 pts
            results.append({"id": ss["id"], "score": score, "is_missing": 0})
    return results


def get_score_date(start_date, offset_months, fallback_year=2026):
    """Calculate score date based on formation start + offset."""
    if not start_date:
        return f"{fallback_year}-01-15T09:00:00.000Z"
    try:
        dt = datetime.fromisoformat(start_date[:10])
        # Add months approximately
        month = dt.month + offset_months
        year = dt.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        day = min(dt.day, 28)  # Safe day
        return f"{year}-{month:02d}-{day:02d}T09:00:00.000Z"
    except (ValueError, TypeError):
        return f"{fallback_year}-01-15T09:00:00.000Z"


# ============================================================================
# Build formation configs from manifest
# ============================================================================

def build_formations_config(manifest, base, headers, year_start=2025, year_end=2026):
    """Build score config for each formation from manifest."""
    configs = {}

    for fm_key, fm_data in manifest.get("formations", {}).items():
        fid = fm_data["id"]
        theme = fm_data.get("theme", "")

        # Get score templates for this theme
        tpl = SCORE_TEMPLATES_BY_THEME.get(theme, DEFAULT_SCORE_TEMPLATE)

        # Get main group IDs from manifest
        grp_data = manifest.get("groups", {}).get(fm_key, {})
        main_group_ids = grp_data.get("main_group_ids", [])

        if not main_group_ids:
            # Fallback: use all non-TD, non-TP groups
            all_groups = grp_data.get("main_group_ids", []) + grp_data.get("td_group_ids", []) + grp_data.get("tp_group_ids", [])
            if all_groups:
                main_group_ids = all_groups[:3]  # Limit

        # Get formation start date
        f_detail = SESSION.get(f"{base}/formations/{fid}", headers=headers).json()
        start_date = f_detail.get("accessible_from", f"{year_start}-09-01")

        # Build concrete templates with dates
        score_templates = []
        for st in tpl.get("score_templates", []):
            score_templates.append({
                "name": st["name"],
                "coeff": st["coeff"],
                "date": get_score_date(start_date, st["date_offset_months"], fallback_year=year_end),
            })

        extra = tpl.get("extra_template")
        extra_template = None
        if extra:
            extra_template = {
                "name": extra["name"],
                "coeff": extra["coeff"],
                "date": get_score_date(start_date, extra["date_offset_months"], fallback_year=year_end),
            }

        configs[fid] = {
            "name": fm_data.get("name", f"Formation {fid}"),
            "theme": theme,
            "main_groups": main_group_ids,
            "score_templates": score_templates,
            "extra_template": extra_template,
            "extra_threshold": tpl.get("extra_threshold", 999),
        }

    return configs


# ============================================================================
# Formation structure
# ============================================================================

def get_formation_structure(fid, base, headers):
    """Charge les nodes et extrait UEs, sub-UEs, modules."""
    r = SESSION.get(f"{base}/formations/{fid}/nodes", headers=headers)
    r.raise_for_status()
    nodes = r.json()
    ues = [n for n in nodes if n["parent_node_id"] is None and n["module_id"] is None]
    sub_ues = [n for n in nodes if n["parent_node_id"] is not None and n["module_id"] is None]
    modules = [n for n in nodes if n["module_id"] is not None]
    return ues, sub_ues, modules


# ============================================================================
# Process formation
# ============================================================================

def process_formation(fid, config, base, headers, score_config, year_end=2026):
    """Crée tous les scores et notes composées pour une formation."""
    mean = score_config.get("mean", 1200)
    std = score_config.get("std", 300)
    absent_rate = score_config.get("absent_rate_pct", 3) / 100.0

    log_info(f"Formation {fid}: {config['name']}")

    # Vérifier les scores existants
    existing_scores = api_get(f"/formations/{fid}/scores", base=base, headers=headers) or []
    existing_compound = api_get(f"/formations/{fid}/compound-scores", base=base, headers=headers) or []
    if existing_scores or existing_compound:
        log_warn(f"  {len(existing_scores)} scores et {len(existing_compound)} notes composées existent déjà — skip")
        return len(existing_scores), len(existing_compound)

    ues, sub_ues, all_modules = get_formation_structure(fid, base, headers)
    log_info(f"  Structure: {len(ues)} UEs, {len(sub_ues)} sub-UEs, {len(all_modules)} modules")

    groups = config["main_groups"]
    if not groups:
        log_warn(f"  Pas de groupes principaux, skip")
        return 0, 0

    templates = config["score_templates"]
    extra_tpl = config.get("extra_template")
    extra_threshold = config.get("extra_threshold", 999)

    total_scores = 0
    total_compounds = 0
    scores_to_publish = []
    compounds_to_publish = []

    for sub_ue in sub_ues:
        sub_ue_name = sub_ue["unit"]
        sub_ue_node_id = sub_ue["id"]

        sub_modules = [m for m in all_modules if m["parent_node_id"] == sub_ue_node_id]
        if not sub_modules:
            continue

        active_templates = list(templates)
        if extra_tpl and len(sub_modules) >= extra_threshold:
            active_templates.append(extra_tpl)

        # Sélectionner les modules pour chaque relevé
        selected_modules = []
        for i in range(len(active_templates)):
            idx = min(i * len(sub_modules) // len(active_templates), len(sub_modules) - 1)
            selected_modules.append(sub_modules[idx])

        created_score_ids = []

        for tpl, module_node in zip(active_templates, selected_modules):
            score_name = tpl["name"].format(sub_ue=sub_ue_name)

            for group_id in groups:
                result = api_post(f"/formations/{fid}/scores", {
                    "name": score_name,
                    "formation_node_id": module_node["id"],
                    "groups": [group_id],
                    "date": tpl["date"],
                    "max": 2000,
                    "precision": 2,
                }, base=base, headers=headers)
                if not result:
                    continue

                score_id = result["id"]
                student_scores = result.get("students_scores", [])

                if not student_scores:
                    continue

                # Varier la moyenne selon le type d'évaluation
                m = mean
                s = std
                if "Examen" in score_name or "Concours" in score_name or "Jury" in score_name:
                    m = mean - 100
                    s = std + 50
                elif "Soutenance" in score_name or "Présentation" in score_name:
                    m = mean + 100
                    s = max(100, std - 50)
                elif "Portfolio" in score_name or "Rapport" in score_name:
                    m = mean + 50
                    s = max(100, std - 20)

                grades = generate_grades(student_scores, mean=m, std=s, absent_rate=absent_rate)
                api_patch(f"/formations/{fid}/scores/{score_id}/results", {
                    "students_scores": grades
                }, base=base, headers=headers)

                scores_to_publish.append(score_id)
                created_score_ids.append((score_id, tpl["coeff"]))
                total_scores += 1
                noted = sum(1 for g in grades if g["score"] is not None)
                log_info(f"    Score {score_id}: {score_name} ({noted}/{len(grades)} notes)")

        # Créer la note composée pour cette sub-UE
        if created_score_ids and score_config.get("include_compound", True):
            compound = api_post(f"/formations/{fid}/compound-scores", {
                "name": f"Moyenne {sub_ue_name}",
                "formation_node_id": sub_ue_node_id,
                "groups": groups,
                "date": f"{year_end}-06-15T23:59:59.000Z",
                "max": 2000,
                "precision": 2,
            }, base=base, headers=headers)
            if compound:
                compound_id = compound["id"]
                for score_id, coeff in created_score_ids:
                    api_post(f"/formations/{fid}/compound-scores/{compound_id}/scores", {
                        "score_id": score_id,
                        "coefficient": coeff,
                    }, base=base, headers=headers)
                compounds_to_publish.append(compound_id)
                total_compounds += 1
                log_info(f"    Note composée {compound_id}: Moyenne {sub_ue_name} ({len(created_score_ids)} relevés)")

    # Publier tous les scores
    log_info(f"  Publication: {len(scores_to_publish)} scores + {len(compounds_to_publish)} notes composées...")
    for sid in scores_to_publish:
        api_patch(f"/formations/{fid}/scores/{sid}/publish", {}, base=base, headers=headers)
    for cid in compounds_to_publish:
        api_patch(f"/formations/{fid}/compound-scores/{cid}/publish", {}, base=base, headers=headers)

    log_ok(f"  Formation {fid} terminée: {total_scores} relevés, {total_compounds} notes composées")
    return total_scores, total_compounds


# ============================================================================
# Main
# ============================================================================

def seed_scores():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_groups")
    require_step(manifest, "seed_teaching_units")

    random_seed = config.get("meta", {}).get("random_seed", 2026)
    random.seed(random_seed + 400)

    log_banner("NEIL ERP — Relevés de notes et notes composées")

    # Parse academic year
    academic_year = config.get("meta", {}).get("academic_year", "2025-2026")
    _ay_parts = academic_year.split("-")
    _ay_end = int(_ay_parts[1]) if len(_ay_parts) > 1 else int(_ay_parts[0]) + 1

    # Score config from seed_config
    score_config = config.get("scores", {"mean": 1200, "std": 300, "absent_rate_pct": 3})
    scores_per_formation = config.get("seeder", {}).get("scores_per_formation", None)
    include_compound = config.get("seeder", {}).get("include_compound_scores", True)
    log_info(f"Config notes : moyenne={score_config.get('mean', 1200)}, "
             f"σ={score_config.get('std', 300)}, "
             f"absent={score_config.get('absent_rate_pct', 3)}%")
    if scores_per_formation is not None:
        log_info(f"Relevés par formation : {scores_per_formation}")
    if not include_compound:
        log_info("Notes composées : désactivées")

    # Build formation configs
    log_section("CONSTRUCTION DES CONFIGS PAR FORMATION")
    _ay_start = int(academic_year.split("-")[0])
    formations_config = build_formations_config(manifest, base, headers, year_start=_ay_start, year_end=_ay_end)

    # Apply scores_per_formation — limit templates
    if scores_per_formation is not None:
        for fid, fc in formations_config.items():
            if len(fc["score_templates"]) > scores_per_formation:
                fc["score_templates"] = fc["score_templates"][:scores_per_formation]

    # Apply include_compound_scores
    if not include_compound:
        for fid, fc in formations_config.items():
            fc["extra_template"] = None

    log_info(f"{len(formations_config)} formations configurées")

    for fid, fc in sorted(formations_config.items()):
        log_info(f"  F{fid}: {fc['name']} — {len(fc['main_groups'])} groupes, "
                 f"{len(fc['score_templates'])} templates ({fc['theme']})")

    # Process formations
    log_section("CRÉATION DES NOTES")
    grand_total_scores = 0
    grand_total_compounds = 0

    score_config["include_compound"] = include_compound
    for fid in sorted(formations_config.keys()):
        fc = formations_config[fid]
        s, c = process_formation(fid, fc, base, headers, score_config, year_end=_ay_end)
        grand_total_scores += s
        grand_total_compounds += c

    # Store in manifest
    manifest["scores"] = {
        "total_scores": grand_total_scores,
        "total_compounds": grand_total_compounds,
    }
    mark_step_complete(manifest, "seed_scores")
    save_manifest(manifest)

    log_banner("NOTES TERMINÉES")
    print(f"  {grand_total_scores} relevés de notes")
    print(f"  {grand_total_compounds} notes composées")
    print()


if __name__ == "__main__":
    seed_scores()
