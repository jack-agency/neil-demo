#!/usr/bin/env python3
"""
seed_parents.py — Génération des parents d'étudiants.

Version dynamique : lit les mineurs et fratries depuis le manifest.

Crée des parents réalistes pour :
  1. Tous les étudiants mineurs (nés après 01/09/2007) → 2 parents chacun
  2. Des fratries détectées dynamiquement (même nom de famille, écart d'âge ≤ 5 ans)
  3. Quelques étudiants majeurs isolés → 1 ou 2 parents
"""

import requests
import random
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, STUDENT_NAME_DATASETS,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)

COUNTRY_FR = 75

# ============================================================================
# Prénoms parents — chargés dynamiquement depuis STUDENT_NAME_DATASETS
# ============================================================================
_DEFAULT_DS = STUDENT_NAME_DATASETS["standard"]
FATHER_NAMES = _DEFAULT_DS["father_names"]
MOTHER_NAMES = _DEFAULT_DS["mother_names"]
MAIDEN_NAMES = _DEFAULT_DS["maiden_names"]


def normalize(s):
    """Normalise un nom pour l'email."""
    return (s.lower()
            .replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('ë', 'e')
            .replace('à', 'a').replace('â', 'a').replace('ä', 'a')
            .replace('î', 'i').replace('ï', 'i')
            .replace('ô', 'o').replace('ö', 'o')
            .replace('ù', 'u').replace('û', 'u').replace('ü', 'u')
            .replace('ç', 'c').replace(' ', '').replace("'", ''))


def generate_phone():
    return f"+33 6 {random.randint(10,99)} {random.randint(10,99)} {random.randint(10,99)} {random.randint(10,99)}"


def get_student_address(student):
    """Récupère l'adresse de l'étudiant pour la réutiliser."""
    addr = student.get("address", {})
    if addr:
        return {
            "address": addr.get("address", "1 rue de la Paix"),
            "city": addr.get("city", "Paris"),
            "postal_code": addr.get("postal_code", "75001"),
            "country_id": COUNTRY_FR,
        }
    return {"address": "1 rue de la Paix", "city": "Paris", "postal_code": "75001", "country_id": COUNTRY_FR}


def create_parent_for_student(student_id, parent_data, base, headers):
    """Crée un parent inline pour un étudiant. Retourne le parent_id."""
    r = SESSION.post(f"{base}/students/{student_id}/parents", headers=headers, json=parent_data)
    if r.status_code not in (200, 201):
        log_error(f"Création parent pour étudiant #{student_id}: {r.status_code} {r.text[:200]}")
        return None
    data = r.json()
    if isinstance(data, list):
        for p in data:
            if p.get("first_name") == parent_data.get("first_name") and p.get("last_name") == parent_data.get("last_name"):
                return p.get("id")
        return data[-1].get("id") if data else None
    elif isinstance(data, dict):
        if "parents" in data:
            parents = data["parents"]
            for p in parents:
                if p.get("first_name") == parent_data.get("first_name"):
                    return p.get("id")
            return parents[-1].get("id") if parents else None
        return data.get("id")
    return None


def link_parent_to_student(student_id, parent_id, base, headers):
    """Lie un parent existant à un étudiant."""
    r = SESSION.post(f"{base}/students/{student_id}/parents", headers=headers, json={"parent_id": parent_id})
    if r.status_code not in (200, 201):
        log_error(f"Liaison parent #{parent_id} → étudiant #{student_id}: {r.status_code} {r.text[:200]}")
        return False
    return True


def load_students(base, headers):
    """Charge tous les étudiants."""
    r = SESSION.post(f"{base}/students/search", headers=headers, json={"limit": 500})
    r.raise_for_status()
    data = r.json()
    students = data.get("students", data) if isinstance(data, dict) else data
    return {s["id"]: s for s in students}


def make_parent_data(first_name, last_name, student_address, email_domain="famille-neil.fr"):
    """Génère les données d'un parent."""
    email = f"{normalize(first_name)}.{normalize(last_name)}{random.randint(1,99)}@{email_domain}"
    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone_number": generate_phone(),
        "address": student_address,
    }


def create_family(students_dict, student_ids, family_name, father_first, mother_first, mother_last, base, headers, email_domain="famille-neil.fr"):
    """Crée un père et une mère pour une famille, et les lie à tous les enfants."""
    first_student_id = student_ids[0]
    first_student = students_dict.get(first_student_id)
    if not first_student:
        log_warn(f"Étudiant #{first_student_id} introuvable — skip famille {family_name}")
        return 0, []

    addr = get_student_address(first_student)
    created = 0
    parent_ids = []

    father_data = make_parent_data(father_first, family_name, addr, email_domain=email_domain)
    father_id = create_parent_for_student(first_student_id, father_data, base, headers)
    if father_id:
        created += 1
        parent_ids.append(father_id)
        log_info(f"    Père: {father_first} {family_name} (#{father_id}) → étudiant #{first_student_id}")

    mother_data = make_parent_data(mother_first, mother_last, addr, email_domain=email_domain)
    mother_id = create_parent_for_student(first_student_id, mother_data, base, headers)
    if mother_id:
        created += 1
        parent_ids.append(mother_id)
        log_info(f"    Mère: {mother_first} {mother_last} (#{mother_id}) → étudiant #{first_student_id}")

    for sid in student_ids[1:]:
        if father_id:
            ok = link_parent_to_student(sid, father_id, base, headers)
            if ok:
                log_info(f"    Père #{father_id} lié → étudiant #{sid}")
        if mother_id:
            ok = link_parent_to_student(sid, mother_id, base, headers)
            if ok:
                log_info(f"    Mère #{mother_id} liée → étudiant #{sid}")

    return created, parent_ids


# ============================================================================
# Détection dynamique des fratries
# ============================================================================

def detect_fratries(students_dict, minor_ids):
    """
    Détecte les fratries : même nom de famille + écart d'âge ≤ 5 ans.
    Retourne {family_name: [student_ids]} pour les fratries de ≥ 2 membres.
    """
    by_name = {}
    for sid, s in students_dict.items():
        last_name = s.get("last_name", "")
        if last_name:
            by_name.setdefault(last_name, []).append(s)

    fratries = {}
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        # Check age gap ≤ 5 years
        group.sort(key=lambda s: s.get("birth_date", ""))
        valid = []
        for s in group:
            bd = s.get("birth_date", "")
            if not bd:
                continue
            year = int(bd[:4])
            # Check if within 5 years of any member already in the list
            if not valid:
                valid.append(s)
            else:
                first_year = int(valid[0].get("birth_date", "2000")[:4])
                if abs(year - first_year) <= 5:
                    valid.append(s)
        if len(valid) >= 2:
            fratries[name] = [s["id"] for s in valid]

    return fratries


def select_extra_students(students_dict, minor_ids, fratrie_student_ids, count=15, single_parent_pct=0.33):
    """
    Sélectionne des étudiants majeurs isolés pour leur ajouter des parents.
    """
    excluded = set(minor_ids) | fratrie_student_ids
    candidates = []
    for sid, s in students_dict.items():
        if sid not in excluded:
            bd = s.get("birth_date", "")
            if bd:
                year = int(bd[:4])
                if 1998 <= year <= 2006:
                    candidates.append(sid)

    candidates.sort()
    selected = candidates[:count]
    n_single = int(len(selected) * single_parent_pct)
    single_parent_ids = set(selected[:n_single])
    return selected, single_parent_ids


# ============================================================================
# Main
# ============================================================================

def seed_parents():
    global FATHER_NAMES, MOTHER_NAMES, MAIDEN_NAMES

    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_students")

    random.seed(config.get("meta", {}).get("random_seed", 2026))

    # Load name dataset from config
    dataset_key = config.get("students", {}).get("dataset", "standard")
    ds = STUDENT_NAME_DATASETS.get(dataset_key, STUDENT_NAME_DATASETS["standard"])
    FATHER_NAMES = ds["father_names"]
    MOTHER_NAMES = ds["mother_names"]
    MAIDEN_NAMES = ds["maiden_names"]
    dataset_label = "🧙 Poudlard" if dataset_key == "poudlard" else "📚 Standard"

    log_banner("NEIL ERP — Parents d'étudiants")
    log_info(f"Dataset noms : {dataset_label} ({len(FATHER_NAMES)} pères, {len(MOTHER_NAMES)} mères, {len(MAIDEN_NAMES)} noms de jeune fille)")

    students = load_students(base, headers)
    log_info(f"{len(students)} étudiants chargés")

    # Get minor IDs from manifest
    minor_ids = set(manifest.get("students", {}).get("minor_ids", []))
    log_info(f"{len(minor_ids)} mineurs identifiés dans le manifest")

    # Check existing parents
    r = SESSION.post(f"{base}/parents/search", headers=headers, json={"limit": 10})
    existing = r.json() if r.status_code == 200 else []
    if isinstance(existing, dict):
        existing = existing.get("parents", [])
    if existing:
        log_warn(f"{len(existing)} parents existent déjà — le script va en ajouter d'autres")

    # Email domain based on dataset
    email_domain = "famille-poudlard.fr" if dataset_key == "poudlard" else "famille-neil.fr"

    total_parents = 0
    total_families = 0
    all_parent_ids = []
    father_idx = 0
    mother_idx = 0
    maiden_idx = 0

    # Detect fratries dynamically
    fratries = detect_fratries(students, minor_ids)
    log_info(f"{len(fratries)} fratries détectées")

    # ================================================================
    # 1. Étudiants mineurs sans fratrie existante
    # ================================================================
    log_section("PARENTS DES ÉTUDIANTS MINEURS")

    minors_in_fratries = set()
    for family_name, sids in fratries.items():
        for sid in sids:
            if sid in minor_ids:
                minors_in_fratries.add(sid)

    isolated_minors = minor_ids - minors_in_fratries
    for sid in sorted(isolated_minors):
        student = students.get(sid)
        if not student:
            continue
        family_name = student["last_name"]
        father_first = FATHER_NAMES[father_idx % len(FATHER_NAMES)]
        mother_first = MOTHER_NAMES[mother_idx % len(MOTHER_NAMES)]
        mother_last = MAIDEN_NAMES[maiden_idx % len(MAIDEN_NAMES)]
        father_idx += 1
        mother_idx += 1
        maiden_idx += 1

        log_info(f"Famille {family_name} (mineur #{sid}: {student['first_name']} {student['last_name']})")
        n, pids = create_family(students, [sid], family_name, father_first, mother_first, mother_last, base, headers, email_domain=email_domain)
        total_parents += n
        all_parent_ids.extend(pids)
        total_families += 1

    # ================================================================
    # 2. Fratries
    # ================================================================
    log_section("FRATRIES")

    for family_name, sids in sorted(fratries.items()):
        student_names = []
        for sid in sids:
            s = students.get(sid)
            if s:
                student_names.append(f"#{sid} {s['first_name']} ({s['birth_date'][:4]})")
        log_info(f"Fratrie {family_name}: {', '.join(student_names)}")

        father_first = FATHER_NAMES[father_idx % len(FATHER_NAMES)]
        mother_first = MOTHER_NAMES[mother_idx % len(MOTHER_NAMES)]
        mother_last = MAIDEN_NAMES[maiden_idx % len(MAIDEN_NAMES)]
        father_idx += 1
        mother_idx += 1
        maiden_idx += 1

        n, pids = create_family(students, sids, family_name, father_first, mother_first, mother_last, base, headers, email_domain=email_domain)
        total_parents += n
        all_parent_ids.extend(pids)
        total_families += 1

    # ================================================================
    # 3. Étudiants majeurs isolés
    # ================================================================
    log_section("PARENTS D'ÉTUDIANTS MAJEURS (sélection)")

    fratrie_sids = set()
    for sids in fratries.values():
        fratrie_sids.update(sids)

    extra_students, single_parent_students = select_extra_students(students, minor_ids, fratrie_sids)
    log_info(f"{len(extra_students)} étudiants majeurs sélectionnés ({len(single_parent_students)} monoparentales)")

    for sid in extra_students:
        student = students.get(sid)
        if not student:
            continue
        family_name = student["last_name"]
        is_single = sid in single_parent_students

        father_first = FATHER_NAMES[father_idx % len(FATHER_NAMES)]
        mother_first = MOTHER_NAMES[mother_idx % len(MOTHER_NAMES)]
        mother_last = MAIDEN_NAMES[maiden_idx % len(MAIDEN_NAMES)]
        father_idx += 1
        mother_idx += 1
        maiden_idx += 1

        label = "monoparentale" if is_single else "complète"
        log_info(f"Famille {family_name} ({label}) — #{sid}: {student['first_name']} {student['last_name']} ({student['birth_date'][:4]})")

        addr = get_student_address(student)

        if is_single:
            if random.random() < 0.5:
                parent_data = make_parent_data(father_first, family_name, addr, email_domain=email_domain)
            else:
                parent_data = make_parent_data(mother_first, mother_last, addr, email_domain=email_domain)
            pid = create_parent_for_student(sid, parent_data, base, headers)
            if pid:
                total_parents += 1
                all_parent_ids.append(pid)
                log_ok(f"  Parent: {parent_data['first_name']} {parent_data['last_name']} (#{pid})")
        else:
            n, pids = create_family(students, [sid], family_name, father_first, mother_first, mother_last, base, headers, email_domain=email_domain)
            total_parents += n
            all_parent_ids.extend(pids)

        total_families += 1

    # ================================================================
    # Store in manifest
    # ================================================================
    manifest["parents"] = {
        "total": total_parents,
        "families": total_families,
        "fratries": len(fratries),
        "parent_ids": all_parent_ids,
    }
    mark_step_complete(manifest, "seed_parents")
    save_manifest(manifest)

    # ================================================================
    # Récapitulatif
    # ================================================================
    log_banner("PARENTS TERMINÉS")
    print(f"  {total_parents} parents créés pour {total_families} familles")
    print(f"  {len(isolated_minors)} familles de mineurs isolés")
    print(f"  {len(fratries)} fratries ({sum(len(v) for v in fratries.values())} étudiants)")
    print(f"  {len(extra_students)} étudiants majeurs avec parents")
    print()


if __name__ == "__main__":
    seed_parents()
