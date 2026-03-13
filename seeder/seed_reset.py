#!/usr/bin/env python3
"""
seed_reset.py — Remise à zéro complète des données de l'ERP Neil.

Supprime TOUTES les données créées par les scripts de seed, dans l'ordre
inverse de leur création (dépendances respectées).

⚠️  NE SUPPRIME JAMAIS :
  - Les comptes de service (has_reserved=True)
  - Les comptes administrateur (is_admin=True)
  - Les profils réservés (is_reserved=True)
  - Les employés systèmes (IDs 1, 2, 3)

Ordre de suppression (inverse du pipeline de création) :
  1. Échéanciers de paiement
  1b. Employeurs
  2. Bulletins de notes
  3. Notes et notes composées
  4. Absences et retards (remise à "présent")
  5. Séances
  6. Classes et groupes
  7. Inscriptions aux formules
  8. IBANs (étudiants + parents)
  9. Parents
  10. Étudiants
  11. Employés (suppression ou désactivation + retrait profils)
  12. Profils utilisateurs
  13. Modules et UE (teaching units)
  14. Types de modules
  15. Types de documents
  16. Matières et sous-matières
  17. Calendriers de contraintes (avant formations car le search filtre par chevauchement)
  18. Diplômes (degrés) — unlink des formules, suppression certifications, puis diplômes
  19. Formations et formules (avec nettoyage des pièces justificatives)
  20. Infrastructure (salles, centres, campus, niveaux, sociétés, écoles)

Usage : python3 seed_reset.py
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    load_config, load_manifest, save_manifest,
    get_api_config, api_get, api_delete,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)


# ============================================================================
# Session avec retry automatique (gère les connexions coupées par le serveur)
# ============================================================================

def make_session():
    """Crée un requests.Session avec retry automatique sur erreurs réseau."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,         # 1s, 2s, 4s, 8s, 16s
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "POST", "PATCH", "DELETE"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=1, pool_connections=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = make_session()


# ============================================================================
# Safe API helpers (ne plante pas en cas d'erreur)
# ============================================================================

def safe_delete(path, base, headers, data=None, label=""):
    """DELETE qui retourne True/False sans exit."""
    try:
        if data:
            r = SESSION.delete(f"{base}{path}", headers=headers, json=data, timeout=30)
        else:
            r = SESSION.delete(f"{base}{path}", headers=headers, timeout=30)
        if r.status_code in (200, 201, 204):
            return True
        if r.status_code == 404:
            return True  # déjà supprimé
        if label:
            log_warn(f"DELETE {path} → {r.status_code} ({label})")
        return False
    except Exception as e:
        if label:
            log_warn(f"DELETE {path} → exception: {e} ({label})")
        return False


def safe_get(path, base, headers):
    """GET qui retourne le JSON ou None."""
    try:
        r = SESSION.get(f"{base}{path}", headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def safe_post(path, data, base, headers):
    """POST qui retourne le JSON ou None."""
    try:
        r = SESSION.post(f"{base}{path}", headers=headers, json=data, timeout=30)
        if r.status_code in (200, 201):
            return r.json()
        return None
    except Exception:
        return None


def safe_patch(path, data, base, headers):
    """PATCH qui retourne True/False."""
    try:
        r = SESSION.patch(f"{base}{path}", headers=headers, json=data, timeout=30)
        return r.status_code in (200, 201, 204)
    except Exception:
        return False


# ============================================================================
# Étape 1 : Échéanciers de paiement
# ============================================================================

def get_all_students(base, headers):
    """Récupère tous les étudiants via POST /students/search."""
    students = safe_post("/students/search", {"limit": 2000}, base, headers)
    if not students:
        return []
    if isinstance(students, dict):
        return students.get("data", students.get("students", []))
    if isinstance(students, list):
        return students
    return []


def get_student_formulas(sid, base, headers):
    """Récupère les inscriptions d'un étudiant."""
    formulas = safe_get(f"/students/{sid}/formulas", base, headers)
    if not formulas:
        return []
    if isinstance(formulas, dict):
        return formulas.get("formulas", [])
    if isinstance(formulas, list):
        return formulas
    return []


def get_formula_payments(sid, sf_id, base, headers):
    """Récupère les paiements d'une inscription. Retourne une liste plate."""
    pay_data = safe_get(f"/students/{sid}/formulas/{sf_id}/payments", base, headers)
    if not pay_data:
        return []
    # API returns {payment_schedule: {list: [...], totals: {...}}}
    if isinstance(pay_data, dict):
        schedule = pay_data.get("payment_schedule", pay_data)
        if isinstance(schedule, dict):
            return schedule.get("list", schedule.get("payments", schedule.get("data", [])))
    if isinstance(pay_data, list):
        return pay_data
    return []


def reset_payments(base, headers):
    log_section("1/20 — ÉCHÉANCIERS DE PAIEMENT")
    students = get_all_students(base, headers)
    if not students:
        log_info("Aucun étudiant trouvé")
        return 0

    total_deleted = 0
    total_failed = 0
    for i, stu in enumerate(students):
        sid = stu["id"]
        formulas = get_student_formulas(sid, base, headers)
        for sf in formulas:
            sf_id = sf.get("student_formula_id") or sf.get("id")
            if not sf_id:
                continue
            payments = get_formula_payments(sid, sf_id, base, headers)
            for pay in payments:
                pay_id = pay.get("id")
                if not pay_id:
                    continue
                status = pay.get("payment_status", "")
                if status == "upcoming":
                    # Upcoming payments can be deleted directly
                    ok = safe_delete(f"/accounting/payments/{pay_id}", base, headers, label=f"paiement {pay_id}")
                    if ok:
                        total_deleted += 1
                elif status in ("success", "regularized"):
                    # Success/regularized payments must be set to "failed" first
                    # They can't be deleted, but setting to "failed" unblocks enrollment deletion
                    ok = safe_patch(f"/accounting/payments/{pay_id}", {"payment_status": "failed"}, base, headers)
                    if ok:
                        total_failed += 1
                # "failed" payments: nothing to do, they already unblock enrollment deletion
        if (i + 1) % 50 == 0:
            progress_bar(i + 1, len(students), "étudiants traités")

    if len(students) >= 50:
        print()
    log_ok(f"{total_deleted} paiements supprimés + {total_failed} paiements passés en 'failed'")
    return total_deleted + total_failed


# ============================================================================
# Étape 2 : Bulletins de notes
# ============================================================================

def reset_report_cards(base, headers):
    log_section("2/20 — BULLETINS DE NOTES")
    existing = SESSION.post(f"{base}/report-cards/search", headers=headers, json={"filters": {}})
    total = 0
    if existing.status_code == 200:
        cards = existing.json()
        if isinstance(cards, list):
            for card in cards:
                rc_id = card["id"]
                status = card.get("status", 0)

                # 1) Dépublier tous les étudiants publiés
                students_r = SESSION.get(f"{base}/report-cards/{rc_id}/students", headers=headers)
                if students_r.status_code == 200:
                    students = students_r.json()
                    if isinstance(students, list):
                        published_ids = [
                            s.get("student", {}).get("id")
                            for s in students
                            if s.get("is_published") == 1 and s.get("student", {}).get("id")
                        ]
                        if published_ids:
                            SESSION.patch(
                                f"{base}/report-cards/{rc_id}/students/unpublish",
                                headers=headers,
                                json={"ids": published_ids},
                            )

                # 2) Remonter le statut étape par étape (3→2→1→0)
                if status >= 3:
                    SESSION.delete(f"{base}/report-cards/{rc_id}/options", headers=headers)
                if status >= 2:
                    SESSION.delete(f"{base}/report-cards/{rc_id}/scores", headers=headers)
                if status >= 1:
                    SESSION.delete(f"{base}/report-cards/{rc_id}/audience", headers=headers)

                # 3) Supprimer le bulletin
                r = SESSION.delete(f"{base}/report-cards/{rc_id}", headers=headers)
                if r.status_code in (200, 204):
                    total += 1
                else:
                    log_warn(f"  Bulletin {rc_id} non supprimé (status={r.status_code})")
    log_ok(f"{total} bulletin(s) supprimé(s)")
    return total


# ============================================================================
# Étape 3 : Notes et notes composées
# ============================================================================

def reset_scores(base, headers):
    log_section("3/20 — NOTES ET NOTES COMPOSÉES")
    # Get all formations
    formations = get_all_formations(base, headers)
    if not formations:
        log_info("Aucune formation trouvée")
        return 0

    total_scores = 0
    total_compound = 0

    for fm in formations:
        fid = fm["id"]
        # Delete compound scores first
        compounds = safe_get(f"/formations/{fid}/compound-scores", base, headers)
        if compounds:
            if isinstance(compounds, dict):
                compounds = compounds.get("compound_scores", compounds.get("data", []))
            for cs in compounds:
                ok = safe_delete(f"/formations/{fid}/compound-scores/{cs['id']}", base, headers, label=f"compound {cs['id']}")
                if ok:
                    total_compound += 1

        # Delete regular scores
        scores = safe_get(f"/formations/{fid}/scores", base, headers)
        if scores:
            if isinstance(scores, dict):
                scores = scores.get("scores", scores.get("data", []))
            for sc in scores:
                ok = safe_delete(f"/formations/{fid}/scores/{sc['id']}", base, headers, label=f"score {sc['id']}")
                if ok:
                    total_scores += 1

    log_ok(f"{total_scores} notes + {total_compound} notes composées supprimées")
    return total_scores + total_compound


# ============================================================================
# Étape 4 : Absences et retards
# ============================================================================

def reset_absences(base, headers):
    """Skip — les absences sont supprimées automatiquement avec les séances (étape 5)."""
    log_section("4/20 — ABSENCES ET RETARDS")
    log_info("Supprimées avec les séances (étape suivante)")
    return 0


# ============================================================================
# Étape 5 : Séances
# ============================================================================

def reset_sequences(base, headers):
    log_section("5/20 — SÉANCES")
    formations = get_all_formations(base, headers)
    if not formations:
        log_info("Aucune formation trouvée")
        return 0

    total_deleted = 0
    for fm in formations:
        fid = fm["id"]
        data = safe_get(f"/formations/{fid}/modules", base, headers)
        if not data:
            continue
        modules = data.get("modules", []) if isinstance(data, dict) else []
        seq_ids = []
        for m in modules:
            if m.get("sequences_count", 0) > 0:
                seqs = safe_get(f"/formations/{fid}/modules/{m['id']}/sequences", base, headers)
                if seqs:
                    if isinstance(seqs, list):
                        seq_ids.extend([s["id"] for s in seqs])
                    elif isinstance(seqs, dict) and "sequences" in seqs:
                        seq_ids.extend([s["id"] for s in seqs["sequences"]])

        if seq_ids:
            # 1. Dépublier par batch (obligatoire avant suppression)
            for i in range(0, len(seq_ids), 100):
                batch = seq_ids[i:i + 100]
                safe_patch(f"/formations/{fid}/sequences/unpublish", {"ids": batch}, base, headers)

            # 2. Supprimer par batch
            for i in range(0, len(seq_ids), 100):
                batch = seq_ids[i:i + 100]
                safe_delete(f"/formations/{fid}/sequences", base, headers, data={"ids": batch}, label=f"F{fid} batch")
            total_deleted += len(seq_ids)
            log_info(f"F{fid}: {len(seq_ids)} séances dépubliées + supprimées")

    log_ok(f"{total_deleted} séances supprimées")
    return total_deleted


# ============================================================================
# Étape 6 : Classes et groupes
# ============================================================================

def reset_groups(base, headers):
    log_section("6/20 — CLASSES ET GROUPES")
    formations = get_all_formations(base, headers)
    if not formations:
        log_info("Aucune formation trouvée")
        return 0

    total_groups = 0
    total_sets = 0

    for fm in formations:
        fid = fm["id"]
        data = safe_get(f"/formations/{fid}/groups", base, headers)
        if not data:
            continue

        # API returns {"groups": [...]} — a flat array mixing group-sets and groups.
        # Group-sets do NOT have "group_set_id", groups DO have "group_set_id".
        items = data.get("groups", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        groups = [g for g in items if g.get("group_set_id")]  # actual groups
        group_sets = [g for g in items if not g.get("group_set_id")]  # group-sets

        # Delete groups first (they belong to group-sets)
        for g in groups:
            gid = g["id"]
            ok = safe_delete(f"/formations/{fid}/groups/{gid}", base, headers, label=f"groupe {g.get('name', gid)}")
            if ok:
                total_groups += 1

        # Then delete non-default group-sets
        for gs in group_sets:
            gs_id = gs["id"]
            # Skip the default group-set (usually the first one or the one with lowest order)
            # We can't always tell which is default, so we try and accept failures
            ok = safe_delete(f"/formations/{fid}/group-sets/{gs_id}", base, headers, label=f"ensemble {gs.get('name', gs_id)}")
            if ok:
                total_sets += 1

    log_ok(f"{total_groups} groupes + {total_sets} ensembles supprimés")
    return total_groups + total_sets


# ============================================================================
# Étape 7 : Inscriptions aux formules
# ============================================================================

def reset_enrollments(base, headers):
    log_section("7/20 — INSCRIPTIONS AUX FORMULES")
    students = get_all_students(base, headers)
    if not students:
        log_info("Aucun étudiant trouvé")
        return 0

    total_deleted = 0
    total_cancelled = 0
    for i, stu in enumerate(students):
        sid = stu["id"]
        formulas = get_student_formulas(sid, base, headers)
        for sf in formulas:
            sf_id = sf.get("student_formula_id") or sf.get("id")
            if not sf_id:
                continue
            # Try direct delete first
            ok = safe_delete(f"/students/{sid}/formulas/{sf_id}", base, headers)
            if ok:
                total_deleted += 1
                continue
            # If 409, cancel the enrollment first (sets payments to 0 and marks cancelled)
            safe_patch(f"/students/{sid}/formulas/{sf_id}/cancel",
                       {"canceled_date": "2025-01-01", "canceled_price": 0}, base, headers)
            total_cancelled += 1
            # Retry delete
            ok = safe_delete(f"/students/{sid}/formulas/{sf_id}", base, headers, label=f"inscription {sf_id} (after cancel)")
            if ok:
                total_deleted += 1
        if (i + 1) % 50 == 0:
            progress_bar(i + 1, len(students), "étudiants traités")

    if len(students) >= 50:
        print()
    log_ok(f"{total_deleted} inscriptions supprimées ({total_cancelled} annulées au préalable)")
    return total_deleted


# ============================================================================
# Étape 8 : IBANs
# ============================================================================

def get_all_parents(base, headers):
    """Récupère tous les parents via POST /parents/search."""
    parents = safe_post("/parents/search", {"limit": 2000}, base, headers)
    if not parents:
        return []
    if isinstance(parents, dict):
        return parents.get("data", parents.get("parents", []))
    if isinstance(parents, list):
        return parents
    return []


def reset_ibans(base, headers):
    log_section("8/20 — IBANs")
    total_deleted = 0

    # Student IBANs
    students = get_all_students(base, headers)
    for stu in students:
        sid = stu["id"]
        ibans = safe_get(f"/students/{sid}/ibans", base, headers)
        if not ibans:
            continue
        if isinstance(ibans, dict):
            ibans = ibans.get("ibans", ibans.get("data", []))
        if isinstance(ibans, list):
            for iban in ibans:
                iban_id = iban.get("id")
                if iban_id:
                    ok = safe_delete(f"/students/{sid}/ibans/{iban_id}", base, headers, label=f"IBAN étudiant {iban_id}")
                    if ok:
                        total_deleted += 1

    # Parent IBANs
    parents = get_all_parents(base, headers)
    for parent in parents:
        pid = parent["id"]
        ibans = safe_get(f"/parents/{pid}/ibans", base, headers)
        if not ibans:
            continue
        if isinstance(ibans, dict):
            ibans = ibans.get("ibans", ibans.get("data", []))
        if isinstance(ibans, list):
            for iban in ibans:
                iban_id = iban.get("id")
                if iban_id:
                    ok = safe_delete(f"/parents/{pid}/ibans/{iban_id}", base, headers, label=f"IBAN parent {iban_id}")
                    if ok:
                        total_deleted += 1

    log_ok(f"{total_deleted} IBANs supprimés")
    return total_deleted


# ============================================================================
# Étape 9 : Parents
# ============================================================================

def reset_parents(base, headers):
    log_section("9/20 — PARENTS")
    parents = get_all_parents(base, headers)
    if not parents:
        log_info("Aucun parent trouvé")
        return 0

    total_deleted = 0
    for p in parents:
        pid = p["id"]
        ok = safe_delete(f"/parents/{pid}", base, headers, label=f"parent {pid}")
        if ok:
            total_deleted += 1

    log_ok(f"{total_deleted} parents supprimés")
    return total_deleted


# ============================================================================
# Étape 10 : Étudiants
# ============================================================================

def reset_students(base, headers):
    log_section("10/20 — ÉTUDIANTS")
    students = get_all_students(base, headers)

    # Also scan by ID to catch orphan students not returned by search
    search_ids = {s["id"] for s in students}
    orphans = []
    miss_streak = 0
    for sid in range(1, 1000):
        if sid in search_ids:
            miss_streak = 0
            continue
        stu = safe_get(f"/students/{sid}", base, headers)
        if stu:
            orphans.append(stu)
            miss_streak = 0
        else:
            miss_streak += 1
            if miss_streak > 50:
                break

    if orphans:
        log_info(f"{len(orphans)} étudiants orphelins trouvés par scan (non retournés par search)")
        students.extend(orphans)

    if not students:
        log_info("Aucun étudiant trouvé")
        return 0

    log_info(f"{len(students)} étudiants à supprimer")

    total_deleted = 0
    for i, stu in enumerate(students):
        sid = stu["id"]
        ok = safe_delete(f"/students/{sid}", base, headers, label=f"étudiant {sid}")
        if ok:
            total_deleted += 1
        if (i + 1) % 50 == 0:
            progress_bar(i + 1, len(students), "étudiants supprimés")

    if len(students) >= 50:
        print()
    log_ok(f"{total_deleted} étudiants supprimés")
    return total_deleted


# ============================================================================
# Étape 11 : Employés (suppression ou désactivation + retrait profils)
# ============================================================================

RESERVED_EMPLOYEE_IDS = {1, 2, 3}

def scan_all_employees(base, headers, max_id=500):
    """Scan employee IDs to find all employees, including deactivated ones.

    POST /employees/search doesn't return deactivated employees,
    so we must scan individual IDs via GET /employees/{id}.
    """
    employees = []
    miss_streak = 0
    for eid in range(1, max_id + 1):
        emp = safe_get(f"/employees/{eid}", base, headers)
        if emp:
            employees.append(emp)
            miss_streak = 0
        else:
            miss_streak += 1
            if miss_streak > 30:
                break
    return employees


def reset_employees(base, headers):
    log_section("11/20 — EMPLOYÉS")
    # Scan all employees by ID (search endpoint doesn't return deactivated ones)
    employees = scan_all_employees(base, headers)
    if not employees:
        log_info("Aucun employé trouvé")
        return 0

    log_info(f"{len(employees)} employés trouvés (y compris désactivés)")

    total_deleted = 0
    total_deactivated = 0
    total_profiles_removed = 0

    for emp in employees:
        eid = emp["id"]

        # Skip reserved & admin accounts
        if eid in RESERVED_EMPLOYEE_IDS:
            log_info(f"  ⏭️  Employé {eid} ({emp.get('first_name', '')} {emp.get('last_name', '')}) — réservé (skip)")
            continue
        if emp.get("has_reserved") or emp.get("is_admin"):
            log_info(f"  ⏭️  Employé {eid} ({emp.get('first_name', '')} {emp.get('last_name', '')}) — admin/réservé (skip)")
            continue

        # Remove profile assignments first
        profiles = safe_get(f"/employees/{eid}/profiles", base, headers)
        if profiles:
            if isinstance(profiles, dict):
                profiles = profiles.get("data", profiles.get("profiles", []))
            for p in profiles:
                ep_id = p.get("employee_profile_id")
                if ep_id:
                    safe_delete(f"/employees/{eid}/profiles/{ep_id}", base, headers, label=f"profil employé {ep_id}")
                    total_profiles_removed += 1

        # Try DELETE
        ok = safe_delete(f"/employees/{eid}", base, headers)
        if ok:
            total_deleted += 1
            continue

        # Deactivate first, then retry DELETE (API bug: DELETE on active employee → 500)
        safe_patch(f"/employees/{eid}/deactivate", {}, base, headers)
        ok = safe_delete(f"/employees/{eid}", base, headers)
        if ok:
            total_deleted += 1
            continue

        total_deactivated += 1

    log_ok(f"{total_deleted} employés supprimés, {total_deactivated} désactivés (fallback), {total_profiles_removed} profils retirés")
    return total_deleted + total_deactivated


# ============================================================================
# Étape 12 : Profils utilisateurs
# ============================================================================

def reset_profiles(base, headers):
    log_section("12/20 — PROFILS UTILISATEURS")
    profiles = safe_get("/profiles", base, headers)
    if not profiles:
        log_info("Aucun profil trouvé")
        return 0

    if isinstance(profiles, dict):
        profiles = profiles.get("data", profiles.get("profiles", []))

    total_deleted = 0
    for p in profiles:
        pid = p["id"]
        # Never delete reserved or admin profiles
        if p.get("is_reserved") or p.get("is_admin"):
            log_info(f"  ⏭️  Profil '{p.get('name', pid)}' — réservé/admin (skip)")
            continue
        ok = safe_delete(f"/profiles/{pid}", base, headers, label=f"profil {p.get('name', pid)}")
        if ok:
            total_deleted += 1

    log_ok(f"{total_deleted} profils supprimés")
    return total_deleted


# ============================================================================
# Étape 13 : Modules et UE (Teaching Units)
# ============================================================================

def reset_teaching_units(base, headers):
    log_section("13/20 — MODULES ET UNITÉS D'ENSEIGNEMENT")
    formations = get_all_formations(base, headers)
    if not formations:
        log_info("Aucune formation trouvée")
        return 0

    total_modules = 0
    total_ues = 0

    for fm in formations:
        fid = fm["id"]
        data = safe_get(f"/formations/{fid}/modules", base, headers)
        if not data:
            continue

        modules = data.get("modules", []) if isinstance(data, dict) else []
        nodes = data.get("nodes", []) if isinstance(data, dict) else []

        # Delete all modules first
        for m in modules:
            ok = safe_delete(f"/formations/{fid}/modules/{m['id']}", base, headers, label=f"module {m['id']}")
            if ok:
                total_modules += 1

        # Delete UEs bottom-up (deepest first), skip the default UE
        for _ in range(5):
            data = safe_get(f"/formations/{fid}/modules", base, headers)
            if not data:
                break
            nodes = data.get("nodes", []) if isinstance(data, dict) else []
            ue_nodes = [n for n in nodes if n.get("unit") and "défaut" not in n["unit"].lower()]
            if not ue_nodes:
                break
            ue_nodes.sort(key=lambda n: len((n.get("path") or "").split("/")), reverse=True)
            for n in ue_nodes:
                ok = safe_delete(f"/formations/{fid}/teaching-units/{n['id']}", base, headers, label=f"UE {n.get('unit', n['id'])}")
                if ok:
                    total_ues += 1

    log_ok(f"{total_modules} modules + {total_ues} UEs supprimés")
    return total_modules + total_ues


# ============================================================================
# Étape 14 : Types de modules
# ============================================================================

def reset_module_types(base, headers):
    log_section("14/20 — TYPES DE MODULES")
    formations = get_all_formations(base, headers)
    if not formations:
        log_info("Aucune formation trouvée")
        return 0

    total_deleted = 0
    for fm in formations:
        fid = fm["id"]
        data = safe_get(f"/formations/{fid}/module-types", base, headers)
        if not data:
            continue

        types = data.get("module_types", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        # First reset module assignments for each type
        modules_data = safe_get(f"/formations/{fid}/modules", base, headers)
        if modules_data:
            modules = modules_data.get("modules", []) if isinstance(modules_data, dict) else []
            for m in modules:
                if m.get("module_type_id"):
                    safe_patch(f"/formations/{fid}/modules/{m['id']}", {"module_type_id": None}, base, headers)

        # Then delete types
        for t in types:
            tid = t.get("id")
            if tid:
                ok = safe_delete(f"/formations/{fid}/module-types/{tid}", base, headers, label=f"type {t.get('name', tid)}")
                if ok:
                    total_deleted += 1

    log_ok(f"{total_deleted} types de modules supprimés")
    return total_deleted


# ============================================================================
# Étape 15 : Types de documents
# ============================================================================

def reset_document_types(base, headers):
    log_section("15/20 — TYPES DE DOCUMENTS")
    data = safe_get("/documents/types", base, headers)
    if not data:
        log_info("Aucun type de document trouvé")
        return 0

    doc_types = data if isinstance(data, list) else data.get("data", data.get("document_types", []))

    total_deleted = 0
    total_skipped = 0
    for dt in doc_types:
        dt_id = dt.get("id")
        if not dt_id:
            continue
        # Skip non-deletable (built-in) types
        if not dt.get("deletable", True):
            total_skipped += 1
            continue
        ok = safe_delete(f"/documents/types/{dt_id}", base, headers, label=f"type doc {dt.get('name', dt_id)}")
        if ok:
            total_deleted += 1

    if total_skipped:
        log_info(f"{total_skipped} types non supprimables (built-in) conservés")
    log_ok(f"{total_deleted} types de documents supprimés")
    return total_deleted


# ============================================================================
# Étape 16 : Matières et sous-matières
# ============================================================================

def reset_subjects(base, headers):
    log_section("16/20 — MATIÈRES ET SOUS-MATIÈRES")

    # Delete sub-subjects first (they reference subjects via subject_id)
    total_sub = 0
    subsubjects = safe_get("/subsubjects", base, headers)
    if subsubjects:
        items = subsubjects if isinstance(subsubjects, list) else subsubjects.get("data", subsubjects.get("subsubjects", []))
        for ss in items:
            ss_id = ss.get("id")
            if ss_id:
                ok = safe_delete(f"/subsubjects/{ss_id}", base, headers, label=f"sous-matière {ss.get('name', ss_id)}")
                if ok:
                    total_sub += 1

    # Then delete subjects
    total_sub_main = 0
    subjects = safe_get("/subjects", base, headers)
    if subjects:
        items = subjects if isinstance(subjects, list) else subjects.get("data", subjects.get("subjects", []))
        for s in items:
            s_id = s.get("id")
            if s_id:
                ok = safe_delete(f"/subjects/{s_id}", base, headers, label=f"matière {s.get('name', s_id)}")
                if ok:
                    total_sub_main += 1

    log_ok(f"{total_sub_main} matières + {total_sub} sous-matières supprimées")
    return total_sub_main + total_sub


# ============================================================================
# Étape 17 : Calendriers de contraintes (AVANT formations car le search
#             filtre par chevauchement de dates avec les formations existantes)
# ============================================================================

def reset_calendars(base, headers):
    log_section("17/20 — CALENDRIERS DE CONTRAINTES")
    calendars = safe_post("/constraints-calendar/search", {"filters": {}}, base, headers)

    # Fallback: also check manifest for calendar IDs not returned by search
    seen_ids = set()
    if calendars:
        if isinstance(calendars, dict):
            calendars = calendars.get("data", calendars.get("calendars", []))
        seen_ids = {c.get("id") for c in calendars if c.get("id")}
    else:
        calendars = []

    # Add calendars from manifest as fallback
    try:
        manifest = load_manifest()
        for campus_key, cal_data in manifest.get("calendars", {}).items():
            cal_id = cal_data.get("id")
            if cal_id and cal_id not in seen_ids:
                calendars.append({"id": cal_id, "name": cal_data.get("name", f"manifest:{campus_key}")})
                seen_ids.add(cal_id)
    except Exception:
        pass

    # Also scan by ID as last resort (IDs are usually low numbers)
    miss_streak = 0
    for cid in range(1, 200):
        if cid in seen_ids:
            miss_streak = 0
            continue
        cal = safe_get(f"/constraints-calendar/{cid}", base, headers)
        if cal:
            calendars.append(cal)
            seen_ids.add(cid)
            miss_streak = 0
        else:
            miss_streak += 1
            if miss_streak > 20:
                break

    if not calendars:
        log_info("Aucun calendrier trouvé")
        return 0

    total_deleted = 0
    for cal in calendars:
        cid = cal.get("id")
        if cid:
            ok = safe_delete(f"/constraints-calendar/{cid}", base, headers, label=f"calendrier {cal.get('name', cid)}")
            if ok:
                total_deleted += 1
            else:
                log_warn(f"  Calendrier {cid} non supprimable (bug API connu si pas de faculties)")

    log_ok(f"{total_deleted} calendriers supprimés")
    return total_deleted


# ============================================================================
# Étape 18 : Diplômes (degrees)
# ============================================================================

def reset_degrees(base, headers):
    log_section("18/20 — DIPLÔMES")

    # 1. Find all degrees via search
    degrees = safe_post("/degrees/search", {"filters": {}}, base, headers)
    if not degrees:
        # Fallback: try GET /degrees
        degrees = safe_get("/degrees", base, headers)
    if not degrees:
        log_info("Aucun diplôme trouvé")
        return 0

    if isinstance(degrees, dict):
        degrees = degrees.get("data", degrees.get("degrees", []))

    if not degrees:
        log_info("Aucun diplôme trouvé")
        return 0

    # 2. Unlink degrees from formulas first
    formulas = safe_get("/formulas", base, headers)
    if formulas:
        if isinstance(formulas, dict):
            formulas = formulas.get("data", formulas.get("formulas", []))
        for f in formulas:
            fid = f.get("id")
            if fid and f.get("degree_id"):
                safe_patch(f"/formulas/{fid}", {"degree_id": None, "degree_certification_id": None}, base, headers)

    # 3. Delete certifications then degrees
    total_deleted = 0
    total_certs = 0
    for deg in degrees:
        did = deg.get("id")
        if not did:
            continue

        # Delete certifications
        certs = deg.get("certifications", [])
        if not certs:
            # Try fetching certifications
            deg_detail = safe_get(f"/degrees/{did}", base, headers)
            if deg_detail:
                certs = deg_detail.get("certifications", [])

        for cert in certs:
            cid = cert.get("id")
            if cid:
                ok = safe_delete(f"/degrees/{did}/certifications/{cid}", base, headers, label=f"cert {cid}")
                if ok:
                    total_certs += 1

        # Delete degree
        ok = safe_delete(f"/degrees/{did}", base, headers, label=f"diplôme {deg.get('name', did)}")
        if ok:
            total_deleted += 1

    log_ok(f"{total_deleted} diplômes + {total_certs} certifications supprimés")
    return total_deleted


# ============================================================================
# Étape 19 : Formations et formules (avec nettoyage des pièces justificatives)
# ============================================================================

def reset_formations_formulas(base, headers):
    log_section("19/20 — FORMATIONS ET FORMULES")

    # Delete formulas first (they reference formations)
    formulas = safe_get("/formulas", base, headers)
    total_formulas = 0
    total_files_cleaned = 0
    if formulas:
        if isinstance(formulas, dict):
            formulas = formulas.get("data", formulas.get("formulas", []))
        for f in formulas:
            fid = f.get("id")
            if not fid:
                continue

            # Clean step files (pièces justificatives) before deleting formula
            steps = f.get("steps", [])
            if steps:
                has_files = any(s.get("files") for s in steps)
                if has_files:
                    cleaned_steps = []
                    for s in sorted(steps, key=lambda x: x.get("order", 0)):
                        cleaned_steps.append({
                            "name": s["name"],
                            "order": s.get("order", 1),
                            "is_subscription": s.get("is_subscription", False),
                            "files": [],  # Clear all files
                        })
                    ok = safe_patch(f"/formulas/{fid}/steps", {"steps": cleaned_steps}, base, headers)
                    if ok:
                        total_files_cleaned += 1

            ok = safe_delete(f"/formulas/{fid}", base, headers, label=f"formule {f.get('name', fid)}")
            if ok:
                total_formulas += 1

    # Delete formations
    formations = get_all_formations(base, headers)
    total_formations = 0
    if formations:
        for fm in formations:
            fid = fm["id"]
            ok = safe_delete(f"/formations/{fid}", base, headers, label=f"formation {fm.get('name', fid)}")
            if ok:
                total_formations += 1

    if total_files_cleaned:
        log_info(f"{total_files_cleaned} formules nettoyées (pièces justificatives)")
    log_ok(f"{total_formulas} formules + {total_formations} formations supprimées")
    return total_formulas + total_formations


# ============================================================================
# Étape 20 : Infrastructure (salles, centres, campus, niveaux, sociétés, écoles)
# ============================================================================

def reset_infrastructure(base, headers):
    log_section("20/20 — INFRASTRUCTURE")
    stats = {"rooms": 0, "centers": 0, "faculties": 0, "levels": 0, "companies": 0, "schools": 0}

    # Rooms
    rooms = safe_get("/rooms", base, headers)
    if rooms:
        if isinstance(rooms, dict):
            rooms = rooms.get("data", rooms.get("rooms", []))
        for r in rooms:
            rid = r.get("id")
            if rid:
                ok = safe_delete(f"/rooms/{rid}", base, headers, label=f"salle {r.get('name', rid)}")
                if ok:
                    stats["rooms"] += 1

    # Centers
    centers = safe_get("/centers", base, headers)
    if centers:
        if isinstance(centers, dict):
            centers = centers.get("data", centers.get("centers", []))
        for c in centers:
            cid = c.get("id")
            if cid:
                ok = safe_delete(f"/centers/{cid}", base, headers, label=f"centre {c.get('name', cid)}")
                if ok:
                    stats["centers"] += 1

    # Faculties (campuses) — API prevents deleting the last faculty of a school
    faculties = safe_get("/faculties", base, headers)
    if faculties:
        if isinstance(faculties, dict):
            faculties = faculties.get("data", faculties.get("faculties", []))
        for f in faculties:
            fid = f.get("id")
            if fid:
                ok = safe_delete(f"/faculties/{fid}", base, headers)
                if ok:
                    stats["faculties"] += 1
                else:
                    log_info(f"  Campus {fid} ({f.get('name', '')}) non supprimable (dernier campus d'une école)")

    # Levels
    levels = safe_get("/levels", base, headers)
    if levels:
        if isinstance(levels, dict):
            levels = levels.get("data", levels.get("levels", []))
        for lv in levels:
            lid = lv.get("id")
            if lid:
                ok = safe_delete(f"/levels/{lid}", base, headers, label=f"niveau {lv.get('name', lid)}")
                if ok:
                    stats["levels"] += 1

    # Companies
    companies = safe_get("/companies", base, headers)
    if companies:
        if isinstance(companies, dict):
            companies = companies.get("data", companies.get("companies", []))
        for c in companies:
            cid = c.get("id")
            if cid:
                ok = safe_delete(f"/companies/{cid}", base, headers, label=f"société {c.get('name', cid)}")
                if ok:
                    stats["companies"] += 1

    # Schools (last — everything else depends on them)
    # API prevents deleting a school if it still has faculties (last faculty can't be deleted)
    schools = safe_get("/schools", base, headers)
    if schools:
        if isinstance(schools, dict):
            schools = schools.get("data", schools.get("schools", []))
        for s in schools:
            sid = s.get("id")
            if sid:
                ok = safe_delete(f"/schools/{sid}", base, headers)
                if ok:
                    stats["schools"] += 1
                else:
                    log_info(f"  École {sid} ({s.get('name', '')}) non supprimable (API conserve la dernière école+campus)")

    for entity, count in stats.items():
        if count:
            log_ok(f"  {count} {entity} supprimé(s)")

    total = sum(stats.values())
    log_ok(f"{total} éléments d'infrastructure supprimés")
    return total


# ============================================================================
# Helpers
# ============================================================================

def get_all_formations(base, headers):
    """Récupère toutes les formations. Essaie GET /formations d'abord, fallback POST /formations/search."""
    data = safe_get("/formations", base, headers)
    if data:
        if isinstance(data, dict):
            return data.get("data", data.get("formations", []))
        if isinstance(data, list):
            return data

    # Fallback search
    data = safe_post("/formations/search", {"filters": {}}, base, headers)
    if data:
        if isinstance(data, dict):
            return data.get("data", data.get("formations", []))
        if isinstance(data, list):
            return data
    return []


# ============================================================================
# Manifest reset
# ============================================================================

def reset_employers(base, headers):
    log_section("EMPLOYEURS")
    # Search all employers
    r = SESSION.post(f"{base}/employers/search", headers=headers, json={"filters": {}})
    total = 0
    if r.status_code == 200:
        data = r.json()
        employers = data if isinstance(data, list) else data.get("data", data.get("employers", []))
        for emp in employers:
            eid = emp.get("id")
            if not eid:
                continue
            ok = safe_delete(f"/employers/{eid}", base, headers, label=f"employeur {eid}")
            if ok:
                total += 1
    log_ok(f"{total} employeur(s) supprimé(s)")
    return total


def reset_manifest():
    """Remet le manifest à zéro."""
    empty_manifest = {"meta": {"steps_completed": []}}
    save_manifest(empty_manifest)
    log_ok("Manifest remis à zéro")


# ============================================================================
# Main
# ============================================================================

def seed_reset():
    config = load_config()
    base, headers = get_api_config(config)

    log_banner("NEIL ERP — REMISE À ZÉRO COMPLÈTE")
    print("  ⚠️  Ce script supprime TOUTES les données de seed.")
    print("  ✅ Les comptes de service et administrateur sont préservés.")
    print("  ✅ Les profils réservés (is_reserved, is_admin) sont préservés.")
    print()

    t0 = time.time()
    summary = {}

    # Exécuter chaque étape de suppression dans l'ordre inverse
    summary["payments"] = reset_payments(base, headers)
    summary["employers"] = reset_employers(base, headers)
    summary["report_cards"] = reset_report_cards(base, headers)
    summary["scores"] = reset_scores(base, headers)
    summary["absences"] = reset_absences(base, headers)
    summary["sequences"] = reset_sequences(base, headers)
    summary["groups"] = reset_groups(base, headers)
    summary["enrollments"] = reset_enrollments(base, headers)
    summary["ibans"] = reset_ibans(base, headers)
    summary["parents"] = reset_parents(base, headers)
    summary["students"] = reset_students(base, headers)
    summary["employees"] = reset_employees(base, headers)
    summary["profiles"] = reset_profiles(base, headers)
    summary["teaching_units"] = reset_teaching_units(base, headers)
    summary["module_types"] = reset_module_types(base, headers)
    summary["document_types"] = reset_document_types(base, headers)
    summary["subjects"] = reset_subjects(base, headers)
    summary["calendars"] = reset_calendars(base, headers)          # Avant formations (search filtre par chevauchement)
    summary["degrees"] = reset_degrees(base, headers)              # Avant formations (formules référencent les diplômes)
    summary["formations"] = reset_formations_formulas(base, headers)
    summary["infrastructure"] = reset_infrastructure(base, headers)

    # Reset manifest
    log_section("MANIFEST")
    reset_manifest()

    elapsed = time.time() - t0
    total = sum(summary.values())

    log_banner("REMISE À ZÉRO TERMINÉE")
    print(f"  ⏱️  Durée : {elapsed:.1f}s")
    print(f"  🗑️  {total} éléments supprimés au total")
    print()
    print("  Détail :")
    labels = {
        "payments": "Échéanciers",
        "employers": "Employeurs",
        "report_cards": "Bulletins de notes",
        "scores": "Notes",
        "absences": "Absences & Retards",
        "sequences": "Séances",
        "groups": "Groupes",
        "enrollments": "Inscriptions",
        "ibans": "IBANs",
        "parents": "Parents",
        "students": "Étudiants",
        "employees": "Employés",
        "profiles": "Profils",
        "teaching_units": "Modules + UEs",
        "module_types": "Types de modules",
        "document_types": "Types de documents",
        "subjects": "Matières + Sous-matières",
        "calendars": "Calendriers",
        "degrees": "Diplômes",
        "formations": "Formations + Formules",
        "infrastructure": "Infrastructure",
    }
    for key, label in labels.items():
        count = summary.get(key, 0)
        check = "✅" if count > 0 else "⚪"
        print(f"    {check} {label:.<40} {count}")
    print()
    print("  L'ERP est prêt pour un nouveau seed. Lancez le pipeline complet.")
    print()


if __name__ == "__main__":
    seed_reset()
