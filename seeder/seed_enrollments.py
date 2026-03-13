#!/usr/bin/env python3
"""
seed_enrollments.py — Inscription des étudiants aux formules.

Version dynamique : lit les formules, steps, discounts et sets depuis le manifest.

Répartition :
- Majorité inscrite définitivement (dernière étape = is_subscription)
- Reste réparti sur les étapes intermédiaires
- Certains inscrits avec réduction, d'autres sans

Affectation aux formations :
- Chaque formule a des sets liant vers des formations
- Sets obligatoires (min=max=1) : toutes les formations du set
- Sets optionnels (min<max) : choix aléatoire réaliste (~60% max, ~40% une seule)
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

# ============================================================================
# API helpers
# ============================================================================

def get_all_students(base, headers):
    r = SESSION.post(f"{base}/students/search", headers=headers, json={"limit": 500})
    data = r.json()
    return data if isinstance(data, list) else data.get("data", data.get("students", []))


def enroll_student(student_id, formula_id, base, headers):
    """Enroll student in formula. Returns student_formula_id or None."""
    r = SESSION.post(
        f"{base}/students/{student_id}/formulas",
        headers=headers,
        json={"formulas": {"formula_id": formula_id}},
    )
    data = r.json()
    if "error" in data:
        return None
    formulas = data.get("formulas", [])
    if formulas:
        return max(f["student_formula_id"] for f in formulas)
    return None


def advance_step(student_id, sf_id, step_id, base, headers):
    """Advance student formula to given step."""
    r = SESSION.patch(
        f"{base}/students/{student_id}/formulas/{sf_id}",
        headers=headers,
        json={"step": {"formula_step_id": step_id}},
    )
    return r.status_code in (200, 201)


def add_discount(student_id, sf_id, formula_discount_id, base, headers):
    """Add a discount to student formula."""
    r = SESSION.patch(
        f"{base}/students/{student_id}/formulas/{sf_id}",
        headers=headers,
        json={"discounts": [{"formula_discount_id": formula_discount_id}]},
    )
    return r.status_code in (200, 201)


def assign_formations(student_id, sf_id, formula_data, base, headers):
    """Assign student to formations based on formula sets."""
    sets_payload = []
    for s in formula_data.get("sets", []):
        set_id = s["set_id"]
        formation_ids = s["formation_ids"]
        min_count = s.get("min", 1)
        max_count = s.get("max", 1)

        if min_count == max_count == 1 and len(formation_ids) == 1:
            sets_payload.append({"set_id": set_id, "formations": formation_ids})
        elif max_count > 1 and len(formation_ids) > 1:
            if random.random() < 0.60:
                sets_payload.append({"set_id": set_id, "formations": formation_ids})
            else:
                chosen = [random.choice(formation_ids)]
                sets_payload.append({"set_id": set_id, "formations": chosen})
        else:
            sets_payload.append({"set_id": set_id, "formations": formation_ids})

    r = SESSION.patch(
        f"{base}/students/{student_id}/formulas/{sf_id}",
        headers=headers,
        json={"sets": sets_payload},
    )
    return r.status_code in (200, 201)


# ============================================================================
# Build formula data from manifest
# ============================================================================

def build_formulas_from_manifest(manifest):
    """
    Build FORMULAS dict and SCHOOL_FORMULAS from manifest.
    Returns: (formulas_by_id, formulas_by_school_key)
    """
    formulas_by_id = {}
    formulas_by_school = {}  # school_key -> [formula_data]

    for fm_key, fm_data in manifest.get("formulas", {}).items():
        fm_id = fm_data["id"]
        school_key = fm_data.get("school_key", "")
        raw_steps = fm_data.get("steps", [])
        step_ids = [s["id"] if isinstance(s, dict) else s for s in raw_steps]
        raw_discounts = fm_data.get("discounts", [])
        discount_ids = [d["id"] if isinstance(d, dict) else d for d in raw_discounts]

        sets = []
        for s in fm_data.get("sets", []):
            sets.append({
                "set_id": s["set_id"],
                "formation_ids": s.get("formation_ids", s.get("formations", [])),
                "min": s.get("min", 1),
                "max": s.get("max", 1),
            })

        formula_data = {
            "id": fm_id,
            "key": fm_key,
            "name": fm_data.get("name", fm_key),
            "school_key": school_key,
            "steps": step_ids,
            "discounts": discount_ids,
            "sets": sets,
        }

        formulas_by_id[fm_id] = formula_data
        formulas_by_school.setdefault(school_key, []).append(formula_data)

    return formulas_by_id, formulas_by_school


# ============================================================================
# Main enrollment logic
# ============================================================================

def seed_enrollments():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_formulas")
    require_step(manifest, "seed_students")

    random_seed = config.get("meta", {}).get("random_seed", 2026)
    random.seed(random_seed + 200)

    log_banner("NEIL ERP — Inscriptions aux formules")

    # Build formula data from manifest
    formulas_by_id, formulas_by_school = build_formulas_from_manifest(manifest)

    if not formulas_by_id:
        log_error("Aucune formule trouvée dans le manifest.")
        sys.exit(1)

    log_info(f"{len(formulas_by_id)} formules trouvées dans le manifest")
    for fm in formulas_by_id.values():
        log_info(f"  FM{fm['id']}: {fm['name']} ({len(fm['steps'])} étapes, {len(fm['discounts'])} réductions)")

    # Get students
    log_section("RÉCUPÉRATION DES ÉTUDIANTS")
    students = get_all_students(base, headers)
    log_info(f"{len(students)} étudiants trouvés")

    # Get school IDs from manifest
    school_id_to_key = {}
    for sk, sd in manifest.get("infrastructure", {}).get("schools", {}).items():
        school_id_to_key[sd["id"]] = sk

    # Categorize students by school
    students_by_school = {}  # school_key -> [students]
    double_cursus = []

    for s in students:
        schools = s.get("schools", [])
        school_keys = [school_id_to_key.get(sid) for sid in schools if sid in school_id_to_key]
        school_keys = [k for k in school_keys if k]

        if len(school_keys) >= 2:
            double_cursus.append(s)
        elif len(school_keys) == 1:
            students_by_school.setdefault(school_keys[0], []).append(s)

    for sk, sts in students_by_school.items():
        log_info(f"  {sk}: {len(sts)} étudiants")
    log_info(f"  Double cursus: {len(double_cursus)} étudiants")

    # Enrollment config
    enrolled_pct = config.get("seeder", {}).get("enrolled_pct", 100) / 100.0
    final_pct = config.get("enrollments", {}).get("final_pct", 65) / 100.0
    discount_pct = config.get("enrollments", {}).get("discount_pct", 30) / 100.0
    log_info(f"Config inscriptions : {enrolled_pct*100:.0f}% inscrits, "
             f"{final_pct*100:.0f}% définitifs, {discount_pct*100:.0f}% avec remise")
    intermediate_limit = final_pct + (1.0 - final_pct) * 0.57

    stats = {
        "total_enrollments": 0,
        "by_formula": {},
        "by_step": {},
        "with_discount": 0,
        "without_discount": 0,
    }

    def do_enroll(student, formula_data, step_idx, apply_disc):
        """Enroll one student in one formula."""
        sid = student["id"]
        fm_id = formula_data["id"]
        steps = formula_data["steps"]
        target_step = steps[step_idx]

        sf_id = enroll_student(sid, fm_id, base, headers)
        if sf_id is None:
            return False

        assign_formations(sid, sf_id, formula_data, base, headers)

        for idx in range(1, step_idx + 1):
            advance_step(sid, sf_id, steps[idx], base, headers)

        if apply_disc and formula_data["discounts"]:
            discount_id = random.choice(formula_data["discounts"])
            add_discount(sid, sf_id, discount_id, base, headers)
            stats["with_discount"] += 1
        else:
            stats["without_discount"] += 1

        stats["total_enrollments"] += 1
        fm_name = formula_data["name"]
        stats["by_formula"][fm_name] = stats["by_formula"].get(fm_name, 0) + 1
        step_name = f"Étape {step_idx + 1}/{len(steps)}"
        if step_idx == len(steps) - 1:
            step_name = "Inscrit définitivement"
        stats["by_step"][step_name] = stats["by_step"].get(step_name, 0) + 1

        return True

    def assign_step_and_discount(n_students, formula_data):
        assignments = []
        n_steps = len(formula_data["steps"])
        for i in range(n_students):
            r = random.random()
            if r < final_pct:
                step_idx = n_steps - 1
            elif r < intermediate_limit:
                if n_steps > 2:
                    step_idx = random.randint(1, n_steps - 2)
                else:
                    step_idx = 0
            else:
                step_idx = 0
            has_disc = random.random() < discount_pct
            assignments.append((step_idx, has_disc))
        return assignments

    # ── Enroll by school ──
    for school_key, school_students in sorted(students_by_school.items()):
        school_formulas = formulas_by_school.get(school_key, [])
        if not school_formulas:
            log_warn(f"Pas de formule pour l'école '{school_key}' — skip")
            continue

        log_section(f"INSCRIPTION {school_key.upper()}")
        random.shuffle(school_students)
        # Only enroll enrolled_pct% of students
        n_total = len(school_students)
        n = max(1, int(n_total * enrolled_pct))
        if n < n_total:
            log_info(f"  {n}/{n_total} étudiants sélectionnés ({enrolled_pct*100:.0f}%)")

        # Distribute students across formulas
        # Weights: roughly proportional, first formula gets ~50%, rest split evenly
        n_formulas = len(school_formulas)
        if n_formulas == 1:
            distribution = [n]
        elif n_formulas == 2:
            n1 = int(n * 0.60)
            distribution = [n1, n - n1]
        elif n_formulas == 3:
            n1 = int(n * 0.50)
            n2 = int(n * 0.30)
            distribution = [n1, n2, n - n1 - n2]
        else:
            # Even split with first getting more
            base_n = n // n_formulas
            distribution = [base_n + (n % n_formulas)] + [base_n] * (n_formulas - 1)

        offset = 0
        enrolled = 0
        for fm_data, count in zip(school_formulas, distribution):
            group = school_students[offset:offset + count]
            offset += count
            assignments = assign_step_and_discount(len(group), fm_data)
            for student, (step_idx, has_disc) in zip(group, assignments):
                do_enroll(student, fm_data, step_idx, has_disc)
                enrolled += 1
                progress_bar(enrolled, n, school_key)
        print()

    # ── Double cursus ──
    if double_cursus:
        log_section("INSCRIPTION DOUBLE CURSUS")
        all_school_keys = list(formulas_by_school.keys())

        enrolled = 0
        for student in double_cursus:
            for sk in all_school_keys:
                school_formulas = formulas_by_school.get(sk, [])
                if not school_formulas:
                    continue
                fm = random.choice(school_formulas)
                step_idx_final = len(fm["steps"]) - 1
                if random.random() < 0.80:
                    step_idx = step_idx_final
                else:
                    step_idx = random.randint(0, step_idx_final - 1) if step_idx_final > 0 else 0
                has_disc = random.random() < 0.25
                do_enroll(student, fm, step_idx, has_disc)
            enrolled += 1
            progress_bar(enrolled, len(double_cursus), "double cursus")
        print()

    # Store in manifest
    manifest["enrollments"] = {
        "total": stats["total_enrollments"],
        "with_discount": stats["with_discount"],
        "without_discount": stats["without_discount"],
        "by_formula": stats["by_formula"],
    }
    mark_step_complete(manifest, "seed_enrollments")
    save_manifest(manifest)

    # Summary
    log_banner("INSCRIPTIONS TERMINÉES")
    print(f"  {stats['total_enrollments']} inscriptions au total")
    print()
    print("  Par formule :")
    for fm_name, count in sorted(stats["by_formula"].items()):
        print(f"    {fm_name}: {count}")
    print()
    print("  Par étape :")
    for step, count in sorted(stats["by_step"].items()):
        print(f"    {step}: {count}")
    print()
    print(f"  Avec réduction : {stats['with_discount']}")
    print(f"  Sans réduction : {stats['without_discount']}")
    print()


if __name__ == "__main__":
    seed_enrollments()
