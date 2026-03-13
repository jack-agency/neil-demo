#!/usr/bin/env python3
"""
seed_payments.py — Génération des échéanciers de paiement pour toutes les inscriptions.

Version dynamique : lit les formules et mineurs depuis le manifest.

Crée des échéanciers réalistes pour chaque inscription étudiante :
  - Inscrits définitivement → échéancier complet basé sur un template de la formule
  - Étapes intermédiaires → charges/avances des étapes traversées (payées)
  - 1ère étape (candidature) → frais de dossier à venir

Montants ajustés selon les remises appliquées. Méthode de paiement = prélèvement
quand un IBAN existe, sinon non renseigné.
"""

import requests
import random
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)

# TODAY est recalculé dynamiquement dans seed_payments() à partir de l'année scolaire
TODAY = datetime(2026, 2, 24)  # Valeur par défaut, écrasée au runtime

# Distribution des templates (par nom partiel → poids)
TEMPLATE_WEIGHTS = {
    "comptant": 12,
    "unique": 12,
    "2 fois": 8,
    "2x": 8,
    "3 fois": 35,
    "3x": 35,
    "semestriel": 10,
    "5 fois": 15,
    "5x": 15,
    "5 mens": 15,
    "6 mens": 15,
    "8 mens": 20,
    "10 mens": 25,
    "annuel": 8,
    "anticipé": 5,
    "anticipe": 5,
    "trimestriel": 10,
}


def get_template_weight(template_name):
    """Retourne un poids pour le template basé sur son nom."""
    name_lower = template_name.lower()
    for pattern, weight in TEMPLATE_WEIGHTS.items():
        if pattern in name_lower:
            return weight
    return 10


# ============================================================================
# API helpers
# ============================================================================

def _api_get(path, base, headers):
    r = SESSION.get(f"{base}{path}", headers=headers)
    if r.status_code != 200:
        return None
    return r.json()


def _api_post(path, data, base, headers):
    r = SESSION.post(f"{base}{path}", headers=headers, json=data)
    if r.status_code not in (200, 201):
        return None
    return r.json()


def choose_weighted_template(templates):
    """Choisit un template avec pondération réaliste."""
    if not templates:
        return None
    weights = [get_template_weight(t["name"]) for t in templates]
    return random.choices(templates, weights=weights, k=1)[0]


def adjust_amounts(template_payments, total_due, formula_price):
    """Ajuste les montants du template proportionnellement au total_due."""
    if formula_price == 0 or total_due == 0:
        return []

    ratio = total_due / formula_price
    adjusted = []
    total_so_far = 0

    for i, p in enumerate(template_payments):
        if i == len(template_payments) - 1:
            amount = total_due - total_so_far
        else:
            amount = round(p["amount"] * ratio)
            amount = round(amount / 100) * 100

        if amount <= 0:
            continue

        total_so_far += amount
        adjusted.append({
            "name": p["label"],
            "amount": amount,
            "due_date": p["due_date"],
            "type": p.get("charge_type", "payment"),
        })

    return adjusted


def is_past_date(date_str):
    """Vérifie si une date est dans le passé."""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+00:00", ""))
        return dt < TODAY
    except (ValueError, TypeError):
        return False


# ============================================================================
# Load data from manifest + API
# ============================================================================

def load_formulas(manifest, base, headers):
    """Charge les détails de chaque formule depuis le manifest et l'API."""
    formulas = {}
    formula_ids = set()

    for fm_key, fm_data in manifest.get("formulas", {}).items():
        formula_ids.add(fm_data["id"])

    for fid in sorted(formula_ids):
        data = _api_get(f"/formulas/{fid}", base, headers)
        if data:
            formulas[fid] = {
                "id": fid,
                "name": data.get("name", f"Formule {fid}"),
                "price": data.get("price", {}).get("price", 0) if isinstance(data.get("price"), dict) else 0,
                "schedule_templates": data.get("schedule_templates", []),
                "steps": data.get("steps", []),
            }
            log_info(f"  FM{fid}: {formulas[fid]['name']} — "
                     f"{len(formulas[fid]['schedule_templates'])} templates, "
                     f"{len(formulas[fid]['steps'])} steps")
    return formulas


def load_students(base, headers):
    """Charge tous les étudiants."""
    r = SESSION.post(f"{base}/students/search", headers=headers, json={"limit": 500})
    r.raise_for_status()
    data = r.json()
    students = data if isinstance(data, list) else data.get("students", data.get("data", []))
    return {s["id"]: s for s in students}


def load_student_ibans(students, base, headers):
    """Charge les IBANs actifs de tous les étudiants."""
    ibans = {}
    for sid in students:
        r = _api_get(f"/students/{sid}/ibans", base, headers)
        if r:
            iban_list = r.get("ibans", r) if isinstance(r, dict) else r
            if isinstance(iban_list, list):
                for iban in iban_list:
                    if iban.get("is_active", 0):
                        ibans[sid] = iban.get("id")
                        break
    return ibans


def get_student_enrollments(student_id, base, headers):
    """Charge les inscriptions d'un étudiant."""
    data = _api_get(f"/students/{student_id}/formulas", base, headers)
    if not data:
        return []
    if isinstance(data, dict):
        return data.get("formulas", [data])
    return data if isinstance(data, list) else []


def get_enrollment_detail(student_id, sf_id, base, headers):
    """Charge le détail d'une inscription."""
    return _api_get(f"/students/{student_id}/formulas/{sf_id}", base, headers)


def get_payment_schedule(student_id, sf_id, base, headers):
    """Charge l'échéancier existant."""
    return _api_get(f"/students/{student_id}/formulas/{sf_id}/payments", base, headers)


def create_payment(student_id, sf_id, payment_data, base, headers):
    """Crée une échéance de paiement."""
    return _api_post(f"/students/{student_id}/formulas/{sf_id}/payments", payment_data, base, headers)


# ============================================================================
# Enrollment processing
# ============================================================================

def process_complete_enrollment(student_id, sf_id, formula_data, schedule_data, iban_id, base, headers):
    """Crée l'échéancier pour un étudiant inscrit définitivement."""
    totals = schedule_data.get("payment_schedule", {}).get("totals", {})
    total_due = totals.get("total_due", 0)
    formula_price = totals.get("formula_price", 0)

    if total_due <= 0:
        return 0

    templates = formula_data.get("schedule_templates", [])
    if not templates:
        return 0

    template = choose_weighted_template(templates)
    if not template:
        return 0

    # Extraire les paiements du template (clé = step ID d'inscription)
    subscription_step_id = None
    for step in formula_data.get("steps", []):
        if step.get("is_subscription"):
            subscription_step_id = str(step["id"])
            break

    if not subscription_step_id:
        return 0

    template_payments = template.get("steps", {}).get(subscription_step_id, [])
    if not template_payments:
        return 0

    adjusted = adjust_amounts(template_payments, total_due, formula_price)
    if not adjusted:
        return 0

    count = 0
    for payment in adjusted:
        payload = {
            "due_date": payment["due_date"],
            "name": payment["name"],
            "amount": payment["amount"],
            "type": payment["type"],
        }

        if iban_id:
            payload["payment_method"] = "debit"
            payload["iban_id"] = iban_id

        if is_past_date(payment["due_date"]):
            payload["payment_status"] = "success"

        result = create_payment(student_id, sf_id, payload, base, headers)
        if result:
            count += 1

    return count


def process_intermediate_enrollment(student_id, sf_id, enrollment_detail, iban_id, base, headers):
    """Crée les paiements pour les étapes traversées (charges + avances)."""
    current_step_id = enrollment_detail.get("formula_step_id")
    steps = enrollment_detail.get("steps", [])

    count = 0
    for step in steps:
        step_id = step["id"]
        step_order = step.get("order", 0)

        current_order = 0
        for s in steps:
            if s["id"] == current_step_id:
                current_order = s.get("order", 0)
                break

        if step_order > current_order:
            continue

        # Charge de l'étape
        if step.get("has_charge") and step.get("charge"):
            payload = {
                "due_date": "2025-07-01T00:00:00.000Z",
                "name": step.get("charge_label", "Frais"),
                "amount": step["charge"],
                "type": "payment",
            }
            if iban_id:
                payload["payment_method"] = "debit"
                payload["iban_id"] = iban_id
            if step_order < current_order:
                payload["payment_status"] = "success"

            result = create_payment(student_id, sf_id, payload, base, headers)
            if result:
                count += 1

        # Avance de l'étape
        if step.get("has_advance") and step.get("advance"):
            payload = {
                "due_date": "2025-08-01T00:00:00.000Z",
                "name": step.get("advance_label", "Avance"),
                "amount": step["advance"],
                "type": "payment",
            }
            if iban_id:
                payload["payment_method"] = "debit"
                payload["iban_id"] = iban_id
            if step_order < current_order:
                payload["payment_status"] = "success"

            result = create_payment(student_id, sf_id, payload, base, headers)
            if result:
                count += 1

    return count


# ============================================================================
# Main
# ============================================================================

def seed_payments():
    global TODAY

    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_enrollments")
    require_step(manifest, "seed_ibans")

    # Dynamic TODAY based on academic year (mid-February of year_end)
    academic_year = config.get("meta", {}).get("academic_year", "2025-2026")
    _ay_parts = academic_year.split("-")
    _ay_end = int(_ay_parts[1]) if len(_ay_parts) > 1 else int(_ay_parts[0]) + 1
    TODAY = datetime(_ay_end, 2, 24)

    random_seed = config.get("meta", {}).get("random_seed", 2026)
    random.seed(random_seed + 500)

    log_banner("NEIL ERP — Échéanciers de paiement")

    # Load formulas
    log_section("CHARGEMENT DES FORMULES")
    formulas = load_formulas(manifest, base, headers)

    # Load students
    log_section("CHARGEMENT DES ÉTUDIANTS")
    students = load_students(base, headers)
    log_info(f"{len(students)} étudiants chargés")

    # Load IBANs
    log_section("CHARGEMENT DES IBANS")
    student_ibans = load_student_ibans(students, base, headers)
    log_info(f"{len(student_ibans)} étudiants avec IBAN")

    # Process enrollments
    log_section("CRÉATION DES ÉCHÉANCIERS")

    total_payments = 0
    total_complete = 0
    total_intermediate = 0
    total_first_step = 0
    total_skipped = 0
    enrollment_count = 0

    student_ids = sorted(students.keys())
    for idx, sid in enumerate(student_ids):
        enrollments = get_student_enrollments(sid, base, headers)
        if not enrollments:
            continue

        for enrollment in enrollments:
            formula_id = enrollment.get("id")
            sf_id = enrollment.get("student_formula_id")
            is_complete = enrollment.get("is_complete", 0)
            formula_step_id = enrollment.get("formula_step_id")

            if not sf_id or not formula_id:
                continue

            enrollment_count += 1

            # Vérifier les paiements existants
            schedule = get_payment_schedule(sid, sf_id, base, headers)
            if schedule:
                existing = schedule.get("payment_schedule", {}).get("list", [])
                if existing:
                    total_skipped += 1
                    continue

            iban_id = student_ibans.get(sid)

            formula_data = formulas.get(formula_id)
            if not formula_data:
                continue

            if is_complete:
                n = process_complete_enrollment(sid, sf_id, formula_data, schedule, iban_id, base, headers)
                total_payments += n
                total_complete += 1
                if n > 0:
                    student_name = f"{students[sid]['first_name']} {students[sid]['last_name']}"
                    log_info(f"#{sid} {student_name} (FM{formula_id}, sf={sf_id}) → {n} échéances")
            else:
                detail = get_enrollment_detail(sid, sf_id, base, headers)
                if detail:
                    steps = detail.get("steps", [])
                    first_step_id = steps[0]["id"] if steps else None

                    n = process_intermediate_enrollment(sid, sf_id, detail, iban_id, base, headers)
                    total_payments += n

                    if formula_step_id == first_step_id:
                        total_first_step += 1
                    else:
                        total_intermediate += 1

                    if n > 0:
                        student_name = f"{students[sid]['first_name']} {students[sid]['last_name']}"
                        step_name = detail.get("step", {}).get("name", "?")
                        log_info(f"#{sid} {student_name} (FM{formula_id}, étape: {step_name}) → {n} paiement(s)")

        progress_bar(idx + 1, len(student_ids), "étudiants")

    print()

    # Store in manifest
    manifest["payments"] = {
        "total_payments": total_payments,
        "complete_enrollments": total_complete,
        "intermediate_enrollments": total_intermediate,
        "first_step_enrollments": total_first_step,
        "skipped": total_skipped,
    }
    mark_step_complete(manifest, "seed_payments")
    save_manifest(manifest)

    # Summary
    log_banner("ÉCHÉANCIERS TERMINÉS")
    print(f"  {total_payments} échéances créées")
    print(f"  - {total_complete} inscriptions définitives (échéancier complet)")
    print(f"  - {total_intermediate} inscriptions intermédiaires (charges/avances)")
    print(f"  - {total_first_step} inscriptions 1ère étape (frais dossier)")
    print(f"  - {total_skipped} inscriptions ignorées (déjà des paiements)")
    print(f"  - {enrollment_count} inscriptions traitées au total")
    print()


if __name__ == "__main__":
    seed_payments()
