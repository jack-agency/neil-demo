#!/usr/bin/env python3
"""
seed_report_cards.py — Génération des bulletins de notes pour toutes les formations.

Crée des bulletins structurés par semestre avec :
  - Structure arborescente UE > sous-UE reflétant la structure pédagogique
  - Scores du semestre assignés aux items correspondants
  - Options de notation (max, precision)
  - Publication des bulletins pour tous les étudiants

Flow API (status 0→1→2→3→publié) :
  1. POST /report-cards                              → créer le bulletin
  2. PATCH /report-cards/{id}/audience                → définir audience (formule/formation)
  3. PATCH /report-cards/{id}/audience/validate        → valider audience (→ status 1)
  4. POST /report-cards/{id}/items                    → créer items (arbre UE/sous-UE)
  5. PATCH /report-cards/{id}/items/{item_id}/scores  → assigner scores aux feuilles
  6. PATCH /report-cards/{id}/scores/validate          → valider scores (→ status 2)
  7. PATCH /report-cards/{id}/options                  → max/precision
  8. PATCH /report-cards/{id}/options/validate          → valider options (→ status 3)
  9. PATCH /report-cards/{id}/students/publish          → publier les bulletins
"""

import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
)


# ============================================================================
# Semester definitions
# ============================================================================

def get_semesters(year_start, year_end):
    """Retourne les définitions de semestres pour l'année scolaire."""
    return [
        {
            "key": "S1",
            "name": "1er semestre",
            "from": f"{year_start}-09-01",
            "to": f"{year_start}-12-31",
        },
        {
            "key": "S2",
            "name": "2nd semestre",
            "from": f"{year_end}-01-01",
            "to": f"{year_end}-06-30",
        },
    ]


# ============================================================================
# API helpers
# ============================================================================

def create_report_card(name, faculty_id, year_from, year_to, date_from, date_to, base, headers):
    """Crée un bulletin de notes."""
    r = SESSION.post(f"{base}/report-cards", headers=headers, json={
        "name": name,
        "faculty_id": faculty_id,
        "year_from": year_from,
        "year_to": year_to,
        "from": date_from,
        "to": date_to,
    })
    if r.status_code in (200, 201):
        return r.json()
    log_error(f"Création bulletin '{name}': {r.status_code} {r.text[:200]}")
    return None


def set_audience(rc_id, formula_id, set_id, formation_id, base, headers):
    """Configure l'audience d'un bulletin."""
    r = SESSION.patch(f"{base}/report-cards/{rc_id}/audience", headers=headers, json={
        "audience": {
            "formula_id": formula_id,
            "formula_formation_set_id": set_id,
            "formation_id": formation_id,
        }
    })
    if r.status_code != 200:
        log_error(f"Audience bulletin {rc_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


def validate_audience(rc_id, base, headers):
    """Valide l'audience → status 1."""
    r = SESSION.patch(f"{base}/report-cards/{rc_id}/audience/validate", headers=headers, json={})
    if r.status_code != 200:
        log_error(f"Validation audience {rc_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


def get_score_suggestions(rc_id, base, headers):
    """Récupère les scores disponibles pour ce bulletin."""
    r = SESSION.get(f"{base}/report-cards/{rc_id}/scores/suggestions", headers=headers)
    if r.status_code == 200:
        return r.json().get("scores", [])
    return []


def create_item(rc_id, name, coefficient, parent_item_id, base, headers):
    """Crée un item dans le bulletin."""
    r = SESSION.post(f"{base}/report-cards/{rc_id}/items", headers=headers, json={
        "name": name,
        "coefficient": coefficient,
        "parent_item_id": parent_item_id,
    })
    if r.status_code in (200, 201):
        items = r.json().get("items", [])
        # Retourner l'item enfant créé
        children = [i for i in items if i["parent_item_id"] == parent_item_id]
        if children:
            return children[-1]  # Le dernier créé
        # Si pas de parent, retourner le dernier item
        return items[-1] if items else None
    log_error(f"Création item '{name}': {r.status_code} {r.text[:200]}")
    return None


def assign_scores_to_item(rc_id, item_id, score_assignments, base, headers):
    """Assigne des scores à un item feuille.

    score_assignments: [{"score_id": N, "coefficient": N}, ...]
    """
    r = SESSION.patch(
        f"{base}/report-cards/{rc_id}/items/{item_id}/scores",
        headers=headers,
        json={"scores": score_assignments},
    )
    if r.status_code != 200:
        log_error(f"Assignation scores item {item_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


def validate_scores(rc_id, base, headers):
    """Valide les scores → status 2."""
    r = SESSION.patch(f"{base}/report-cards/{rc_id}/scores/validate", headers=headers, json={})
    if r.status_code != 200:
        log_error(f"Validation scores {rc_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


def set_options(rc_id, max_score, precision, base, headers):
    """Configure les options de notation."""
    r = SESSION.patch(f"{base}/report-cards/{rc_id}/options", headers=headers, json={
        "max": max_score,
        "precision": precision,
        "include_audience": True,
        "include_groups": True,
        "include_overall_average": True,
        "include_ranking": True,
        "include_median": True,
        "include_chart": True,
    })
    if r.status_code != 200:
        log_error(f"Options bulletin {rc_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


def validate_options(rc_id, base, headers):
    """Valide les options → status 3."""
    r = SESSION.patch(f"{base}/report-cards/{rc_id}/options/validate", headers=headers, json={})
    if r.status_code != 200:
        log_error(f"Validation options {rc_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


def get_students_list(rc_id, base, headers):
    """Récupère la liste des étudiants du bulletin."""
    r = SESSION.get(f"{base}/report-cards/{rc_id}/students", headers=headers)
    if r.status_code == 200:
        return r.json()
    return []


def publish_students(rc_id, student_ids, base, headers):
    """Publie les bulletins pour les étudiants donnés."""
    r = SESSION.patch(f"{base}/report-cards/{rc_id}/students/publish", headers=headers, json={
        "ids": student_ids,
    })
    if r.status_code != 200:
        log_error(f"Publication {rc_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


# ============================================================================
# Build report card structure
# ============================================================================

def get_formation_structure(fid, base, headers):
    """Charge les nodes et extrait UEs, sub-UEs, modules."""
    r = SESSION.get(f"{base}/formations/{fid}/nodes", headers=headers)
    if r.status_code != 200:
        return [], [], []
    nodes = r.json()
    ues = [n for n in nodes if n["parent_node_id"] is None and n["module_id"] is None]
    sub_ues = [n for n in nodes if n["parent_node_id"] is not None and n["module_id"] is None]
    modules = [n for n in nodes if n["module_id"] is not None]
    return ues, sub_ues, modules


def build_report_card_items(rc_id, suggestions, fid, base, headers):
    """Construit la structure arborescente du bulletin à partir des suggestions.

    Crée les items UE > sous-UE et assigne les scores aux sous-UEs correspondantes.
    Retourne le nombre total de scores assignés.
    """
    if not suggestions:
        return 0

    # Charger la structure pédagogique
    ues, sub_ues, modules = get_formation_structure(fid, base, headers)

    # Indexer les sub-UEs par node_id
    sub_ue_by_id = {s["id"]: s for s in sub_ues}

    # Indexer les UEs par node_id
    ue_by_id = {u["id"]: u for u in ues}

    # Grouper les scores par sub-UE (via module.parent_node_id)
    scores_by_sub_ue = {}
    for s in suggestions:
        module = s.get("module")
        if not module:
            continue  # Skip compound scores (no module)
        parent_node_id = module.get("parent_node_id")
        if parent_node_id:
            if parent_node_id not in scores_by_sub_ue:
                scores_by_sub_ue[parent_node_id] = []
            scores_by_sub_ue[parent_node_id].append(s)

    # Grouper les sub-UEs par UE parente
    sub_ues_by_ue = {}
    for sub_ue in sub_ues:
        parent = sub_ue["parent_node_id"]
        if parent not in sub_ues_by_ue:
            sub_ues_by_ue[parent] = []
        sub_ues_by_ue[parent].append(sub_ue)

    total_assigned = 0

    # Créer les items pour chaque UE qui a des scores
    for ue in sorted(ues, key=lambda u: u.get("order") or 0):
        ue_id = ue["id"]
        ue_name = ue["unit"]

        # Vérifier que cette UE a des scores via ses sub-UEs
        ue_sub_ues = sub_ues_by_ue.get(ue_id, [])
        has_scores = any(s["id"] in scores_by_sub_ue for s in ue_sub_ues)
        if not has_scores:
            continue

        # Créer l'item UE
        ue_item = create_item(rc_id, ue_name, 1, None, base, headers)
        if not ue_item:
            continue

        ue_item_id = ue_item["id"]

        # Créer les sous-items pour chaque sub-UE
        for sub_ue in sorted(ue_sub_ues, key=lambda s: s.get("order") or 0):
            sub_ue_id = sub_ue["id"]
            sub_ue_name = sub_ue["unit"]
            sub_scores = scores_by_sub_ue.get(sub_ue_id, [])

            if not sub_scores:
                continue

            # Créer l'item sous-UE
            sub_item = create_item(rc_id, sub_ue_name, 1, ue_item_id, base, headers)
            if not sub_item:
                continue

            # Assigner les scores
            assignments = [{"score_id": s["id"], "coefficient": 1} for s in sub_scores]
            ok = assign_scores_to_item(rc_id, sub_item["id"], assignments, base, headers)
            if ok:
                total_assigned += len(assignments)
                log_info(f"      {sub_ue_name}: {len(assignments)} scores")

    return total_assigned


# ============================================================================
# Process one formation
# ============================================================================

def process_formation_bulletin(
    formation_key, formation_data, formula_data, semester,
    year_start, year_end, base, headers
):
    """Crée un bulletin complet pour une formation × semestre.

    Returns:
        dict | None: {rc_id, name, scores_count, students_published} ou None si skip.
    """
    fid = formation_data["id"]
    fm_name = formation_data["name"]
    faculty_ids = formation_data.get("faculty_ids", [])
    if not faculty_ids:
        return None

    faculty_id = faculty_ids[0]

    # Trouver le set qui contient cette formation
    formula_id = formula_data["id"]
    set_id = None
    for s in formula_data.get("sets", []):
        if formation_key in s.get("formation_keys", []):
            set_id = s["set_id"]
            break

    if set_id is None:
        log_warn(f"  Pas de set pour {fm_name} dans la formule {formula_id}")
        return None

    # Nom du bulletin (max 64 chars API)
    bulletin_name = f"Bulletin {semester['name']} — {fm_name}"
    if len(bulletin_name) > 64:
        # Tronquer le nom de la formation pour respecter la limite
        prefix = f"Bulletin {semester['key']} — "
        max_fm = 64 - len(prefix)
        bulletin_name = prefix + fm_name[:max_fm - 1] + "…"

    # Créer le bulletin
    rc = create_report_card(
        bulletin_name, faculty_id,
        year_start, year_end,
        semester["from"], semester["to"],
        base, headers,
    )
    if not rc:
        return None

    rc_id = rc["id"]
    log_info(f"  Bulletin {rc_id}: {bulletin_name}")

    # Configurer l'audience
    if not set_audience(rc_id, formula_id, set_id, fid, base, headers):
        return None

    if not validate_audience(rc_id, base, headers):
        return None

    # Récupérer les suggestions de scores
    suggestions = get_score_suggestions(rc_id, base, headers)
    if not suggestions:
        log_warn(f"    Aucun score disponible pour ce semestre")
        # Supprimer le bulletin vide
        SESSION.delete(f"{base}/report-cards/{rc_id}", headers=headers)
        return None

    log_info(f"    {len(suggestions)} scores disponibles")

    # Construire la structure d'items et assigner les scores
    scores_assigned = build_report_card_items(rc_id, suggestions, fid, base, headers)

    if scores_assigned == 0:
        log_warn(f"    Aucun score assigné — bulletin supprimé")
        SESSION.delete(f"{base}/report-cards/{rc_id}", headers=headers)
        return None

    # Valider les scores
    if not validate_scores(rc_id, base, headers):
        return None

    # Configurer les options (notes sur 2000 = /20.00, precision 2 décimales)
    if not set_options(rc_id, 2000, 2, base, headers):
        return None

    # Valider les options
    if not validate_options(rc_id, base, headers):
        return None

    # Publier pour tous les étudiants
    # L'API retourne des objets {id: N, student: {id: M, ...}, is_published: 0}
    # Le publish attend les student.id (pas l'id du bulletin individuel)
    students = get_students_list(rc_id, base, headers)
    student_ids = []
    if isinstance(students, list):
        for s in students:
            sid = s.get("student", {}).get("id") if isinstance(s, dict) else None
            if sid:
                student_ids.append(sid)

    published = 0
    if student_ids:
        if publish_students(rc_id, student_ids, base, headers):
            published = len(student_ids)
            log_ok(f"    Publié pour {published} étudiants")

    return {
        "rc_id": rc_id,
        "name": bulletin_name,
        "scores_count": scores_assigned,
        "students_published": published,
    }


# ============================================================================
# Main
# ============================================================================

def seed_report_cards():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_scores")
    require_step(manifest, "seed_groups")

    # Check if report cards are enabled
    include_report_cards = config.get("seeder", {}).get("include_report_cards", True)
    if not include_report_cards:
        log_banner("NEIL ERP — Bulletins de notes (DÉSACTIVÉ)")
        log_info("Génération des bulletins désactivée dans la config (seeder.include_report_cards = false)")
        manifest["report_cards"] = {"total": 0, "published_students": 0, "bulletin_ids": [], "skipped": True}
        mark_step_complete(manifest, "seed_report_cards")
        save_manifest(manifest)
        return

    log_banner("NEIL ERP — Bulletins de notes")

    # Parse academic year
    academic_year = config.get("meta", {}).get("academic_year", "2025-2026")
    parts = academic_year.split("-")
    year_start = int(parts[0])
    year_end = int(parts[1]) if len(parts) > 1 else year_start + 1

    semesters = get_semesters(year_start, year_end)
    log_info(f"Année scolaire : {academic_year}")
    log_info(f"Semestres : {', '.join(s['name'] for s in semesters)}")

    # Cleanup existing report cards (dépublier avant suppression)
    log_section("NETTOYAGE")
    existing = SESSION.post(f"{base}/report-cards/search", headers=headers, json={"filters": {}})
    if existing.status_code == 200:
        cards = existing.json()
        if isinstance(cards, list) and cards:
            for card in cards:
                rc_id = card["id"]
                status = card.get("status", 0)
                # Dépublier les étudiants
                students_r = SESSION.get(f"{base}/report-cards/{rc_id}/students", headers=headers)
                if students_r.status_code == 200:
                    students = students_r.json()
                    if isinstance(students, list):
                        pub_ids = [
                            s.get("student", {}).get("id")
                            for s in students
                            if s.get("is_published") == 1 and s.get("student", {}).get("id")
                        ]
                        if pub_ids:
                            SESSION.patch(f"{base}/report-cards/{rc_id}/students/unpublish",
                                          headers=headers, json={"ids": pub_ids})
                # Remonter le statut (3→2→1→0)
                if status >= 3:
                    SESSION.delete(f"{base}/report-cards/{rc_id}/options", headers=headers)
                if status >= 2:
                    SESSION.delete(f"{base}/report-cards/{rc_id}/scores", headers=headers)
                if status >= 1:
                    SESSION.delete(f"{base}/report-cards/{rc_id}/audience", headers=headers)
                # Supprimer
                SESSION.delete(f"{base}/report-cards/{rc_id}", headers=headers)
            log_info(f"{len(cards)} bulletin(s) supprimé(s)")
        else:
            log_info("Aucun bulletin existant")
    else:
        log_info("Aucun bulletin existant")

    # Build formation → formula mapping
    formations = manifest.get("formations", {})
    formulas = manifest.get("formulas", {})
    groups = manifest.get("groups", {})

    # Map formation_key → formula_data
    formation_to_formula = {}
    for fml_key, fml_data in formulas.items():
        for s in fml_data.get("sets", []):
            for fk in s.get("formation_keys", []):
                formation_to_formula[fk] = fml_data

    # Filter formations that have groups (= have enrolled students)
    formations_with_groups = {
        fk: fd for fk, fd in formations.items()
        if fk in groups and groups[fk].get("main_group_ids")
    }

    log_info(f"{len(formations_with_groups)} formation(s) avec groupes (étudiants inscrits)")
    if not formations_with_groups:
        log_warn("Aucune formation avec des étudiants inscrits — abandon")
        manifest["report_cards"] = {"total": 0, "published": 0}
        mark_step_complete(manifest, "seed_report_cards")
        save_manifest(manifest)
        return

    # Create bulletins
    log_section("CRÉATION DES BULLETINS")
    total_created = 0
    total_published = 0
    bulletin_ids = []

    for semester in semesters:
        log_info(f"\n--- {semester['name']} ({semester['from']} → {semester['to']}) ---")

        for fk in sorted(formations_with_groups.keys()):
            fd = formations_with_groups[fk]
            fml = formation_to_formula.get(fk)
            if not fml:
                log_warn(f"  {fd['name']}: pas de formule associée, skip")
                continue

            result = process_formation_bulletin(
                fk, fd, fml, semester,
                year_start, year_end, base, headers,
            )
            if result:
                total_created += 1
                total_published += result["students_published"]
                bulletin_ids.append(result["rc_id"])

    # Store in manifest
    manifest["report_cards"] = {
        "total": total_created,
        "published_students": total_published,
        "bulletin_ids": bulletin_ids,
    }
    mark_step_complete(manifest, "seed_report_cards")
    save_manifest(manifest)

    log_banner("BULLETINS DE NOTES TERMINÉS")
    print(f"  {total_created} bulletin(s) créé(s)")
    print(f"  {total_published} bulletin(s) étudiant publiés")
    print()


if __name__ == "__main__":
    seed_report_cards()
