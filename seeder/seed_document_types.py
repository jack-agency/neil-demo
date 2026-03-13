#!/usr/bin/env python3
"""
seed_document_types.py — Création des types de documents.

Crée les types de documents à partir des templates DOCUMENT_TYPE_TEMPLATES
définis dans seed_lib.py. Chaque type a des permissions de visibilité
(étudiants, impression, partage externe) et des bibliothèques associées.

Prérequis : aucun (pas de dépendance manifest).
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seed_lib import (
    load_config, load_manifest, save_manifest,
    log_ok, log_info, log_warn, log_error, log_section,
    DOCUMENT_TYPE_TEMPLATES, SESSION,
)

# ============================================================================
# API helpers
# ============================================================================

def get_document_types(base, headers):
    r = SESSION.get(f"{base}/documents/types", headers=headers, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data if isinstance(data, list) else data.get("data", data.get("document_types", []))
    return []

def create_document_type(tpl, base, headers):
    body = {
        "name": tpl["name"],
        "description": tpl["description"],
        "authz_for_students": tpl.get("authz_for_students", 0),
        "authz_for_print": tpl.get("authz_for_print", 1),
        "authz_for_external_share": tpl.get("authz_for_external_share", 0),
        "download_only": tpl.get("download_only", 0),
        "order": tpl.get("order", 1),
        "year_is_set": tpl.get("year_is_set", 1),
    }
    r = SESSION.post(f"{base}/documents/types", headers=headers, json=body, timeout=30)
    if r.status_code in (200, 201):
        data = r.json()
        dt_id = data.get("id")

        # Set libraries — API expects {"libraries": ["pedagogy", "student", ...]}
        libraries = tpl.get("libraries", {})
        if libraries and dt_id:
            lib_list = [k for k, v in libraries.items() if v]
            lr = SESSION.patch(
                f"{base}/documents/types/{dt_id}/libraries",
                headers=headers,
                json={"libraries": lib_list},
                timeout=30,
            )
            if lr.status_code not in (200, 201, 204):
                log_warn(f"PATCH libraries pour '{tpl['name']}' → {lr.status_code}")

        return data
    elif r.status_code == 409:
        # Already exists — find by name
        existing = get_document_types(base, headers)
        for dt in existing:
            if dt.get("name", "").lower() == tpl["name"].lower():
                return dt
        log_warn(f"409 pour type '{tpl['name']}' mais introuvable")
        return None
    else:
        log_error(f"POST /documents/types → {r.status_code}: {r.text[:200]}")
        return None

# ============================================================================
# Main
# ============================================================================

def seed_document_types():
    config = load_config()
    base = config["api"]["base_url"].rstrip("/")
    headers = {
        "X-Lucius-Api-Key": config["api"]["key"],
        "Content-Type": "application/json",
    }

    print()
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print("\033[0;36m   NEIL ERP — Types de documents\033[0m")
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print()

    log_info(f"{len(DOCUMENT_TYPE_TEMPLATES)} types de documents à créer")

    # Check existing
    existing = get_document_types(base, headers)
    existing_names = {dt.get("name", "").lower() for dt in existing}
    log_info(f"{len(existing)} types existants")

    log_section("CRÉATION DES TYPES DE DOCUMENTS")

    total_created = 0
    total_existing = 0
    dt_ids = {}

    for tpl in DOCUMENT_TYPE_TEMPLATES:
        if tpl["name"].lower() in existing_names:
            # Already exists
            for dt in existing:
                if dt.get("name", "").lower() == tpl["name"].lower():
                    dt_ids[tpl["name"]] = dt["id"]
                    break
            total_existing += 1
            continue

        dt = create_document_type(tpl, base, headers)
        if dt:
            dt_ids[tpl["name"]] = dt["id"]
            total_created += 1
            libs = list(tpl.get("libraries", {}).keys())
            log_ok(f"  {tpl['name']} (ID:{dt['id']}) — libs: {', '.join(libs)}")

    # Summary
    print()
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print("\033[0;36m   TYPES DE DOCUMENTS TERMINÉS\033[0m")
    print("\033[0;36m══════════════════════════════════════════════════════════════════\033[0m")
    print()
    print(f"  {total_created} types créés")
    print(f"  {total_existing} déjà existants")
    print()

    # Save to manifest
    manifest = load_manifest()
    manifest["document_types"] = {
        "total_created": total_created,
        "total_existing": total_existing,
        "type_ids": dt_ids,
    }
    if "seed_document_types" not in manifest.get("meta", {}).get("steps_completed", []):
        manifest.setdefault("meta", {}).setdefault("steps_completed", []).append("seed_document_types")
    save_manifest(manifest)


if __name__ == "__main__":
    seed_document_types()
