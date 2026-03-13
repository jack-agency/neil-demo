#!/usr/bin/env python3
"""
fix_formation_assignments.py — Affecte les étudiants aux formations pour toutes
les inscriptions existantes qui n'ont pas encore de formations assignées.

À exécuter une seule fois pour corriger les inscriptions créées avant que
seed_enrollments.py ne gère l'affectation aux formations.
"""
import requests
import json
import random
import sys

API = "https://neil-claude.erp.neil.app/api"
HEADERS = {
    "X-Lucius-Api-Key": "LoYrwWXSNbqY/PFKRv4l2rCV.X3YF1HYVqBVcNeaOQnMmN52EyhLXNmzKNNl1Z+7ViFN31AxZT+ja9RqED7SlQIww",
    "Content-Type": "application/json",
}

random.seed(42)

# Formula sets configuration
FORMULA_SETS = {
    2: [{"set_id": 1, "formations": [10], "min": 1, "max": 1}],
    3: [
        {"set_id": 2, "formations": [11], "min": 1, "max": 1},
        {"set_id": 3, "formations": [12], "min": 1, "max": 1},
    ],
    4: [{"set_id": 4, "formations": [13], "min": 1, "max": 1}],
    5: [
        {"set_id": 5, "formations": [14], "min": 1, "max": 1},
        {"set_id": 6, "formations": [15], "min": 1, "max": 1},
    ],
    6: [
        {"set_id": 7, "formations": [16], "min": 1, "max": 1},
        {"set_id": 8, "formations": [17, 18], "min": 1, "max": 2},
    ],
}


def build_sets_payload(formula_id):
    """Build sets payload for a formula, with random choice for optional sets."""
    sets_config = FORMULA_SETS[formula_id]
    payload = []
    for s in sets_config:
        if s["min"] == s["max"] == 1 and len(s["formations"]) == 1:
            payload.append({"set_id": s["set_id"], "formations": s["formations"]})
        elif s["max"] > 1 and len(s["formations"]) > 1:
            if random.random() < 0.60:
                payload.append({"set_id": s["set_id"], "formations": s["formations"]})
            else:
                chosen = [random.choice(s["formations"])]
                payload.append({"set_id": s["set_id"], "formations": chosen})
        else:
            payload.append({"set_id": s["set_id"], "formations": s["formations"]})
    return payload


def get_all_students():
    r = requests.post(f"{API}/students/search", headers=HEADERS, json={"limit": 300})
    data = r.json()
    return data if isinstance(data, list) else data.get("data", data.get("students", []))


def get_student_formulas(student_id):
    """Get all formula enrollments for a student.
    Returns list of {formula_id, student_formula_id, ...}
    Note: response uses 'id' for formula_id and 'student_formula_id' for sf_id.
    """
    r = requests.get(f"{API}/students/{student_id}/formulas", headers=HEADERS)
    data = r.json()
    return data.get("formulas", [])


def get_student_formations(student_id):
    """Get formations already assigned to a student."""
    r = requests.get(f"{API}/students/{student_id}/formations", headers=HEADERS)
    data = r.json()
    return data.get("formations", [])


def assign_formations(student_id, sf_id, formula_id):
    """Assign formations to a student_formula."""
    payload = build_sets_payload(formula_id)
    r = requests.patch(
        f"{API}/students/{student_id}/formulas/{sf_id}",
        headers=HEADERS,
        json={"sets": payload},
    )
    return r.status_code in (200, 201)


def main():
    print("=== Récupération des étudiants ===")
    students = get_all_students()
    print(f"  {len(students)} étudiants")

    total = 0
    fixed = 0
    skipped = 0
    errors = 0

    for i, student in enumerate(students):
        sid = student["id"]
        formulas = get_student_formulas(sid)

        # Check if student already has formations assigned
        existing_formations = get_student_formations(sid)
        existing_fm_ids = {f.get("formula", {}).get("id") for f in existing_formations if f.get("formula")}

        for sf in formulas:
            sf_id = sf["student_formula_id"]
            fm_id = sf["id"]  # 'id' is the formula_id in this response

            if fm_id not in FORMULA_SETS:
                continue

            total += 1

            # Check if this formula's formations are already assigned
            if fm_id in existing_fm_ids:
                skipped += 1
            else:
                ok = assign_formations(sid, sf_id, fm_id)
                if ok:
                    fixed += 1
                else:
                    errors += 1

        bar = "█" * ((i + 1) * 40 // len(students)) + "░" * (40 - (i + 1) * 40 // len(students))
        sys.stdout.write(f"\r  [{bar}] {i + 1}/{len(students)} — {fixed} corrigés, {skipped} déjà OK")
        sys.stdout.flush()

    print()
    print()
    print("=== RÉSUMÉ ===")
    print(f"  {total} inscriptions examinées")
    print(f"  {fixed} formations assignées")
    print(f"  {skipped} déjà correctes")
    print(f"  {errors} erreurs")

    # Verify: check formation student counts
    print()
    print("=== VÉRIFICATION ===")
    for fid in range(10, 19):
        r = requests.get(f"{API}/formations/{fid}", headers=HEADERS)
        d = r.json()
        print(f"  F{fid} ({d['name'][:40]}): {d.get('students_count', '?')} étudiants")

    print()
    print("=== DONE ===")


if __name__ == "__main__":
    main()
