#!/usr/bin/env python3
"""
seed_employers.py — Création des employeurs (entreprises partenaires) pour Neil ERP.

Lit seed_config.json + seed_manifest.json (infrastructure).
Crée les employeurs avec établissements et contacts, puis complète le manifest.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, api_post,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
    EMPLOYER_DATASETS,
)


# ============================================================================
# Main
# ============================================================================

def seed_employers():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_neil")

    log_banner("NEIL ERP — Employeurs (employers)")

    employers_config = config.get("employers", {})
    n_employers = employers_config.get("total", 10)
    dataset_key = employers_config.get("dataset", "standard")
    dataset = EMPLOYER_DATASETS.get(dataset_key, EMPLOYER_DATASETS["standard"])

    if n_employers <= 0:
        log_info("Aucun employeur à créer (total=0)")
        manifest["employers"] = {"all_ids": [], "total": 0, "locations_created": 0, "contacts_created": 0}
        mark_step_complete(manifest, "seed_employers")
        save_manifest(manifest)
        return

    log_info(f"Dataset : {dataset_key} ({len(dataset)} entreprises disponibles)")
    log_info(f"Objectif : {n_employers} employeurs")
    print()

    # ── Création ──
    log_section("CRÉATION DES EMPLOYEURS")

    created_ids = []
    total_locations = 0
    total_contacts = 0
    errors = 0

    for i in range(n_employers):
        entry = dataset[i % len(dataset)]

        # --- 1. Créer l'employeur ---
        payload = {
            "siren": entry["siren"],
            "legal_name": entry["legal_name"],
            "sector": entry.get("sector", "private"),
        }
        if entry.get("commercial_name"):
            payload["commercial_name"] = entry["commercial_name"]
        if entry.get("naf"):
            payload["naf"] = entry["naf"]
        if entry.get("employees_count"):
            payload["employees_count"] = entry["employees_count"]
        if entry.get("domain"):
            payload["site_url"] = f"https://www.{entry['domain']}"

        result = api_post("/employers", payload, base=base, headers=headers)
        if not result:
            log_warn(f"Échec création '{entry['legal_name']}'")
            errors += 1
            continue

        eid = result.get("id")
        created_ids.append(eid)
        log_ok(f"[{i+1}/{n_employers}] {entry.get('commercial_name', entry['legal_name'])} (ID:{eid})")

        # --- 2. Créer l'établissement (siège social) ---
        if entry.get("city"):
            siret = entry["siren"] + str(i + 1).zfill(5)  # SIRET = SIREN + NIC (5 digits)
            loc_payload = {
                "siret": siret,
                "name": f"Siège — {entry.get('commercial_name', entry['legal_name'])}",
                "address": {
                    "address": entry.get("address", ""),
                    "postal_code": entry.get("postal", ""),
                    "city": entry["city"],
                    "country_id": 75,  # France
                },
            }
            loc_result = api_post(f"/employers/{eid}/business-locations", loc_payload, base=base, headers=headers)
            if loc_result:
                total_locations += 1
                log_info(f"  📍 Siège : {entry['city']}")
            else:
                log_warn(f"  Échec création siège pour '{entry['legal_name']}'")

        # --- 3. Créer les contacts ---
        contacts = entry.get("contacts", [])
        for contact in contacts:
            contact_payload = {
                "first_name": contact["first_name"],
                "last_name": contact["last_name"],
                "email": contact.get("email", f"{contact['first_name'].lower()}.{contact['last_name'].lower()}@example.com"),
            }
            if contact.get("position"):
                contact_payload["position"] = contact["position"]
            if contact.get("phone_number"):
                contact_payload["phone_number"] = contact["phone_number"]

            contact_result = api_post(f"/employers/{eid}/contacts", contact_payload, base=base, headers=headers)
            if contact_result:
                total_contacts += 1
                pos = contact.get("position", "Contact")
                log_info(f"  👤 {contact['first_name']} {contact['last_name']} ({pos})")

    # ── Manifest ──
    manifest["employers"] = {
        "all_ids": created_ids,
        "total": len(created_ids),
        "locations_created": total_locations,
        "contacts_created": total_contacts,
        "dataset": dataset_key,
    }
    mark_step_complete(manifest, "seed_employers")
    save_manifest(manifest)

    # ── Summary ──
    log_banner("EMPLOYEURS TERMINÉS")
    print(f"  {len(created_ids)} employeurs créés ({errors} erreurs)")
    print(f"  {total_locations} établissements (sièges sociaux)")
    print(f"  {total_contacts} contacts")
    print(f"  Dataset : {dataset_key}")
    print()


if __name__ == "__main__":
    seed_employers()
