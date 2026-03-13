#!/usr/bin/env python3
"""
seed_ibans.py — Génération d'IBANs pour étudiants majeurs et parents.

Version dynamique : lit les mineurs depuis le manifest.

Crée un IBAN français valide pour :
  - Tous les étudiants majeurs
  - Tous les parents

Les IBAN sont au format FR76 + 23 chiffres, avec BIC de banques françaises réalistes.
Chaque IBAN est unique et a un mandat SEPA daté de la rentrée 2025.
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
    get_api_config,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)

# Banques françaises réalistes (BIC + code banque pour IBAN)
BANKS = [
    {"bic": "BNPAFRPP", "code_banque": "30004", "code_guichet": "00001", "name": "BNP Paribas"},
    {"bic": "SOGEFRPP", "code_banque": "30003", "code_guichet": "00001", "name": "Société Générale"},
    {"bic": "CRLYFRPP", "code_banque": "30002", "code_guichet": "00001", "name": "LCL"},
    {"bic": "CEPAFRPP", "code_banque": "18206", "code_guichet": "00001", "name": "Caisse d'Épargne"},
    {"bic": "CMCIFRPP", "code_banque": "10278", "code_guichet": "00001", "name": "CIC"},
    {"bic": "AGRIFRPP", "code_banque": "30006", "code_guichet": "00001", "name": "Crédit Agricole"},
    {"bic": "CCBPFRPP", "code_banque": "10907", "code_guichet": "00001", "name": "Banque Populaire"},
    {"bic": "CMCIFR2A", "code_banque": "10096", "code_guichet": "00001", "name": "Crédit Mutuel"},
    {"bic": "BFCOFRPP", "code_banque": "14707", "code_guichet": "00001", "name": "La Banque Postale"},
    {"bic": "BOUSFRPP", "code_banque": "20041", "code_guichet": "00001", "name": "Boursorama"},
]


def generate_french_iban(bank):
    """Génère un IBAN français valide (FR + 2 check digits + 23 chars BBAN)."""
    code_banque = bank["code_banque"]
    code_guichet = bank["code_guichet"]
    num_compte = f"{random.randint(0, 99999999999):011d}"

    # Clé RIB
    bban_numeric = int(code_banque) * 89 + int(code_guichet) * 15 + int(num_compte) * 3
    cle_rib = 97 - (bban_numeric % 97)

    bban = f"{code_banque}{code_guichet}{num_compte}{cle_rib:02d}"

    # IBAN check digits
    check_base = int(bban + "152700")
    check_digits = 98 - (check_base % 97)

    iban = f"FR{check_digits:02d}{bban}"
    return iban


# ============================================================================
# Main
# ============================================================================

def seed_ibans():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_students")

    random.seed(config.get("meta", {}).get("random_seed", 2026) + 100)  # offset to avoid same sequence as other scripts

    log_banner("NEIL ERP — IBANs pour étudiants et parents")

    # Get minor IDs from manifest
    minor_ids = set(manifest.get("students", {}).get("minor_ids", []))
    log_info(f"{len(minor_ids)} mineurs identifiés (pas d'IBAN)")

    # ================================================================
    # 1. Charger les étudiants
    # ================================================================
    r = SESSION.post(f"{base}/students/search", headers=headers, json={"limit": 500})
    r.raise_for_status()
    data = r.json()
    students = data.get("students", data) if isinstance(data, dict) else data
    adults = [s for s in students if s["id"] not in minor_ids]
    log_info(f"{len(students)} étudiants chargés ({len(adults)} majeurs, {len(minor_ids)} mineurs)")

    # ================================================================
    # 2. Charger les parents
    # ================================================================
    r = SESSION.post(f"{base}/parents/search", headers=headers, json={"limit": 500})
    r.raise_for_status()
    parents_data = r.json()
    parents = parents_data if isinstance(parents_data, list) else parents_data.get("parents", [])
    log_info(f"{len(parents)} parents chargés")

    # ================================================================
    # 3. Vérifier les IBANs existants (échantillon)
    # ================================================================
    if adults:
        sample_id = adults[0]["id"]
        r = SESSION.get(f"{base}/students/{sample_id}/ibans", headers=headers)
        if r.status_code == 200:
            existing = r.json()
            if isinstance(existing, dict):
                existing = existing.get("ibans", [])
            if isinstance(existing, list) and existing:
                log_warn(f"Des IBANs existent déjà (étudiant #{sample_id} a {len(existing)} IBAN(s))")
                log_info("Le script va vérifier et ajouter uniquement les manquants.")

    # ================================================================
    # 4. IBAN pour étudiants majeurs
    # ================================================================
    log_section("IBANS DES ÉTUDIANTS MAJEURS")

    student_count = 0
    student_skipped = 0
    for i, student in enumerate(adults):
        sid = student["id"]

        # Vérifier si l'étudiant a déjà un IBAN
        r = SESSION.get(f"{base}/students/{sid}/ibans", headers=headers)
        if r.status_code == 200:
            existing = r.json()
            if isinstance(existing, dict):
                existing = existing.get("ibans", [])
            if isinstance(existing, list) and existing:
                student_skipped += 1
                progress_bar(i + 1, len(adults), "étudiants")
                continue

        bank = random.choice(BANKS)
        iban = generate_french_iban(bank)
        owner = f"{student['first_name']} {student['last_name']}"

        r2 = SESSION.post(f"{base}/students/{sid}/ibans", headers=headers, json={
            "owner": owner,
            "iban": iban,
            "bic": bank["bic"],
            "mandate_date": "2025-09-01T10:00:00.000Z",
        })

        if r2.status_code in (200, 201):
            student_count += 1

        progress_bar(i + 1, len(adults), "étudiants")

    print()
    log_ok(f"{student_count} IBANs créés ({student_skipped} déjà existants)")

    # ================================================================
    # 5. IBAN pour parents
    # ================================================================
    log_section("IBANS DES PARENTS")

    parent_count = 0
    parent_skipped = 0
    for i, parent in enumerate(parents):
        pid = parent["id"]

        # Vérifier si le parent a déjà un IBAN
        r = SESSION.get(f"{base}/parents/{pid}/ibans", headers=headers)
        if r.status_code == 200:
            existing = r.json()
            if isinstance(existing, dict):
                existing = existing.get("ibans", [])
            if isinstance(existing, list) and existing:
                parent_skipped += 1
                progress_bar(i + 1, len(parents), "parents")
                continue

        bank = random.choice(BANKS)
        iban = generate_french_iban(bank)
        owner = f"{parent['first_name']} {parent['last_name']}"

        r2 = SESSION.post(f"{base}/parents/{pid}/ibans", headers=headers, json={
            "owner": owner,
            "iban": iban,
            "bic": bank["bic"],
            "mandate_date": "2025-09-01T10:00:00.000Z",
        })

        if r2.status_code in (200, 201):
            parent_count += 1

        progress_bar(i + 1, len(parents), "parents")

    print()
    log_ok(f"{parent_count} IBANs créés ({parent_skipped} déjà existants)")

    # ================================================================
    # Store in manifest
    # ================================================================
    manifest["ibans"] = {
        "student_ibans": student_count,
        "parent_ibans": parent_count,
        "total": student_count + parent_count,
    }
    mark_step_complete(manifest, "seed_ibans")
    save_manifest(manifest)

    # ================================================================
    # Récapitulatif
    # ================================================================
    log_banner("IBANS TERMINÉS")
    print(f"  {student_count + parent_count} IBANs créés")
    print(f"  {student_count} étudiants majeurs")
    print(f"  {parent_count} parents")
    print(f"  {len(minor_ids)} étudiants mineurs sans IBAN (parents paient)")
    print()


if __name__ == "__main__":
    seed_ibans()
