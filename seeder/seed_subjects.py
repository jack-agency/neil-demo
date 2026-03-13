#!/usr/bin/env python3
"""
seed_subjects.py — Création des matières et sous-matières.

Crée les matières (subjects) et sous-matières (subsubjects) à partir des
templates SUBJECT_TEMPLATES + SUBJECT_TRANSVERSAL définis dans seed_lib.py.

Les matières sont filtrées par les thèmes des écoles présentes dans la config.
Les matières transversales sont toujours ajoutées.

Prérequis : aucun (pas de dépendance manifest).
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seed_lib import (
    load_config, load_manifest, save_manifest,
    log_ok, log_info, log_warn, log_error, log_section,
    SUBJECT_TEMPLATES, SUBJECT_TRANSVERSAL, SESSION,
)

# ============================================================================
# API helpers
# ============================================================================

def get_subjects(base, headers):
    r = SESSION.get(f"{base}/subjects", headers=headers, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data if isinstance(data, list) else data.get("data", data.get("subjects", []))
    return []

def get_subsubjects(base, headers):
    r = SESSION.get(f"{base}/subsubjects", headers=headers, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data if isinstance(data, list) else data.get("data", data.get("subsubjects", []))
    return []

def create_subject(name, description, order, base, headers):
    body = {"name": name, "description": description, "order": order}
    r = SESSION.post(f"{base}/subjects", headers=headers, json=body, timeout=30)
    if r.status_code in (200, 201):
        data = r.json()
        return data
    elif r.status_code == 409:
        # Already exists — find by name
        existing = get_subjects(base, headers)
        for s in existing:
            if s.get("name", "").lower() == name.lower():
                return s
        log_warn(f"409 pour matière '{name}' mais introuvable")
        return None
    else:
        log_error(f"POST /subjects → {r.status_code}: {r.text[:200]}")
        return None

def create_subsubject(name, description, subject_id, order, base, headers):
    body = {"name": name, "description": description, "subject_id": subject_id, "order": order}
    r = SESSION.post(f"{base}/subsubjects", headers=headers, json=body, timeout=30)
    if r.status_code in (200, 201):
        return r.json()
    elif r.status_code == 409:
        existing = get_subsubjects(base, headers)
        for ss in existing:
            if ss.get("name", "").lower() == name.lower() and ss.get("subject_id") == subject_id:
                return ss
        log_warn(f"409 pour sous-matière '{name}' mais introuvable")
        return None
    else:
        log_error(f"POST /subsubjects → {r.status_code}: {r.text[:200]}")
        return None

# ============================================================================
# Main
# ============================================================================

def seed_subjects():
    config = load_config()
    base = config["api"]["base_url"].rstrip("/")
    headers = {
        "X-Lucius-Api-Key": config["api"]["key"],
        "Content-Type": "application/json",
    }

    # Determine themes from schools in config
    themes = set()
    for school in config.get("schools", []):
        themes.add(school.get("theme", "sciences"))

    print()
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print("\033[0;36m   NEIL ERP — Matières et sous-matières\033[0m")
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print()

    # Build the list of subjects to create
    subjects_to_create = []

    # Theme-specific subjects
    for theme in sorted(themes):
        tpl_list = SUBJECT_TEMPLATES.get(theme, [])
        for s in tpl_list:
            subjects_to_create.append(s)

    # Transversal subjects (always added)
    for s in SUBJECT_TRANSVERSAL:
        # Check not already present (by name)
        existing_names = {x["name"] for x in subjects_to_create}
        if s["name"] not in existing_names:
            subjects_to_create.append(s)

    log_info(f"Thèmes détectés : {', '.join(sorted(themes))}")
    log_info(f"{len(subjects_to_create)} matières à créer")

    # Create subjects and sub-subjects
    log_section("CRÉATION DES MATIÈRES")

    total_subjects = 0
    total_sub = 0
    subject_ids = {}
    subsubject_ids = {}

    for order, s_tpl in enumerate(subjects_to_create, start=1):
        subject = create_subject(s_tpl["name"], s_tpl["description"], order, base, headers)
        if not subject:
            continue

        s_id = subject["id"]
        subject_ids[s_tpl["name"]] = s_id
        total_subjects += 1

        # Create sub-subjects
        subs = s_tpl.get("sub", [])
        for sub_order, ss_tpl in enumerate(subs, start=1):
            ss = create_subsubject(ss_tpl["name"], ss_tpl["description"], s_id, sub_order, base, headers)
            if ss:
                subsubject_ids[f"{s_tpl['name']}/{ss_tpl['name']}"] = ss["id"]
                total_sub += 1

        log_ok(f"  {s_tpl['name']} (ID:{s_id}) — {len(subs)} sous-matières")

    # Summary
    print()
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print("\033[0;36m   MATIÈRES TERMINÉES\033[0m")
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print()
    print(f"  {total_subjects} matières créées")
    print(f"  {total_sub} sous-matières créées")
    print()

    # Save to manifest
    manifest = load_manifest()
    manifest["subjects"] = {
        "total_subjects": total_subjects,
        "total_subsubjects": total_sub,
        "subject_ids": subject_ids,
    }
    if "seed_subjects" not in manifest.get("meta", {}).get("steps_completed", []):
        manifest.setdefault("meta", {}).setdefault("steps_completed", []).append("seed_subjects")
    save_manifest(manifest)


if __name__ == "__main__":
    seed_subjects()
