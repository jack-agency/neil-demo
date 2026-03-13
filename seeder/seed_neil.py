#!/usr/bin/env python3
"""
seed_neil.py — Création dynamique de l'infrastructure Neil ERP.

Lit seed_config.json → crée écoles, campus, centres, salles, niveaux.
Écrit les IDs créés dans seed_manifest.json.

Remplace seed_neil.sh (anciennement bash, maintenant Python + config-driven).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete,
    get_api_config, api_get, api_post, api_patch, api_post_safe,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
    ROOM_POOLS, ROOM_FAMOUS_NAMES, CENTER_HOURS_TEMPLATES, HOURS_ROTATION,
    get_calendar_constraints,
)

COUNTRY_FR = 75


# ============================================================================
# Helpers — create or get
# ============================================================================

def create_school_or_get(name, short_name, first_faculty_name, base, headers):
    """Crée une école + 1er campus, ou récupère les IDs existants."""
    log_info(f"Création école '{name}' + campus '{first_faculty_name}'...")
    payload = {"name": name, "short_name": short_name, "faculty": {"name": first_faculty_name}}
    code, body = api_post_safe("/schools", payload, base=base, headers=headers)

    if code in (200, 201):
        sid = body["id"]
        fid = body["faculty"]["id"]
        log_ok(f"École '{name}' (ID:{sid}) + Campus '{first_faculty_name}' (ID:{fid})")
        return sid, fid
    elif code == 409:
        log_warn(f"École '{name}' existe déjà — récupération des IDs...")
        schools = api_get("/schools", base=base, headers=headers) or []
        sid = next((s["id"] for s in schools if s["name"] == name), None)
        faculties = api_get("/faculties", base=base, headers=headers) or []
        fid = next((f["id"] for f in faculties if f["name"] == first_faculty_name), None)
        log_ok(f"École '{name}' (ID:{sid}) + Campus '{first_faculty_name}' (ID:{fid}) [existants]")
        return sid, fid
    else:
        log_error(f"HTTP {code} — POST /schools: {body}")
        sys.exit(1)


def create_faculty_or_get(name, school_id, base, headers):
    """Crée un campus ou récupère l'ID existant."""
    log_info(f"  Création campus '{name}'...")
    payload = {"name": name, "school_id": school_id}
    code, body = api_post_safe("/faculties", payload, base=base, headers=headers)

    if code in (200, 201):
        fid = body["id"]
        log_ok(f"  Campus '{name}' (ID:{fid})")
        return fid
    elif code == 409:
        log_warn(f"  Campus '{name}' existe déjà — récupération...")
        faculties = api_get("/faculties", base=base, headers=headers) or []
        fid = next((f["id"] for f in faculties if f["name"] == name), None)
        log_ok(f"  Campus '{name}' (ID:{fid}) [existant]")
        return fid
    else:
        log_error(f"HTTP {code} — POST /faculties: {body}")
        sys.exit(1)


def create_center_or_get(name, color, addr, city, postal, base, headers):
    """Crée un centre ou récupère l'ID existant."""
    log_info(f"  Création centre '{name}' ({city})...")
    payload = {
        "name": name, "color": color,
        "address": {"address": addr, "city": city, "postal_code": postal, "country_id": COUNTRY_FR},
    }
    code, body = api_post_safe("/centers", payload, base=base, headers=headers)

    if code in (200, 201):
        cid = body["id"]
        log_ok(f"  Centre '{name}' (ID:{cid})")
        return cid
    elif code == 409:
        log_warn(f"  Centre '{name}' existe déjà — récupération...")
        centers = api_get("/centers", base=base, headers=headers) or []
        cid = next((c["id"] for c in centers if c["name"] == name), None)
        log_ok(f"  Centre '{name}' (ID:{cid}) [existant]")
        return cid
    else:
        log_error(f"HTTP {code} — POST /centers: {body}")
        sys.exit(1)


def create_room(name, center_id, capacity, base, headers):
    """Crée une salle ou skip si elle existe déjà."""
    log_info(f"    + Salle '{name}' ({capacity} places)...")
    payload = {"name": name, "center_id": center_id, "capacity": capacity}
    code, body = api_post_safe("/rooms", payload, base=base, headers=headers)

    if code in (200, 201):
        rid = body["id"]
        log_ok(f"    Salle '{name}' (ID:{rid})")
        return rid
    elif code == 409:
        log_warn(f"    Salle '{name}' existe déjà — skip")
        # Try to find existing room
        rooms = api_get(f"/centers/{center_id}/rooms", base=base, headers=headers)
        if rooms and isinstance(rooms, list):
            for r in rooms:
                if r.get("name") == name:
                    return r["id"]
        # Fallback: get all rooms
        all_rooms = api_get("/rooms", base=base, headers=headers) or []
        if isinstance(all_rooms, list):
            for r in all_rooms:
                if r.get("name") == name:
                    return r["id"]
        return 0
    else:
        log_error(f"HTTP {code} — POST /rooms: {body}")
        return 0


def link_faculty_to_centers(faculty_id, center_ids, base, headers):
    """Lie un campus à des centres d'activité."""
    centers_payload = [{"center_id": cid} for cid in center_ids]
    log_info(f"  Liaison campus ID:{faculty_id} → centres {center_ids}...")
    result = api_post(f"/faculties/{faculty_id}/centers", {"centers": centers_payload}, base=base, headers=headers)
    if result is not None:
        log_ok(f"  Campus ID:{faculty_id} lié aux centres {center_ids}")
    return result is not None


def create_or_get_levels(level_names, base, headers):
    """Récupère ou crée les niveaux. Retourne {level_name: level_id}."""
    existing = api_get("/levels", base=base, headers=headers) or []
    existing_map = {}
    if isinstance(existing, list):
        for lvl in existing:
            existing_map[lvl["name"]] = lvl["id"]

    result = {}
    for name in level_names:
        if name in existing_map:
            result[name] = existing_map[name]
            log_ok(f"  Niveau '{name}' (ID:{result[name]}) [existant]")
        else:
            data = api_post("/levels", {"name": name}, base=base, headers=headers)
            if data:
                result[name] = data["id"]
                log_ok(f"  Niveau '{name}' (ID:{result[name]})")
    return result


# ============================================================================
# Helpers — config
# ============================================================================

def config_campus_center_keys(config, campus_key):
    """Return center_keys assigned to a campus in the config."""
    for c in config.get("campuses", []):
        if c["key"] == campus_key:
            return c.get("center_keys", [])
    return []


# ============================================================================
# Générateur de noms de salles
# ============================================================================

def generate_rooms_for_center(theme, campus_idx, config_rooms_per_campus, capacity_range, center_label=""):
    """Génère la liste de salles pour un centre basé sur le thème.

    center_label: si fourni et campus_idx > 0, ajouté au nom pour les rendre uniques.
    """
    pool = ROOM_POOLS.get(theme, ROOM_POOLS["sciences"])
    names = ROOM_FAMOUS_NAMES.get(theme, ROOM_FAMOUS_NAMES["sciences"])

    rooms = []
    # Offset counters by campus_idx to get unique names per center
    name_counters = {k: campus_idx for k in names}

    for i, (name_tpl, base_cap) in enumerate(pool):
        if i >= config_rooms_per_campus:
            break

        # Resolve name placeholders
        room_name = name_tpl
        for placeholder, name_list in names.items():
            if "{" + placeholder + "}" in room_name:
                idx = name_counters[placeholder] % len(name_list)
                room_name = room_name.replace("{" + placeholder + "}", name_list[idx])
                name_counters[placeholder] = idx + 1

        # Ajouter le label du centre si multi-campus pour rendre les noms uniques
        if campus_idx > 0 and center_label:
            room_name = f"{room_name} — {center_label}"

        # Adjust capacity within range
        cap = min(max(base_cap, capacity_range[0]), capacity_range[1])
        rooms.append({"name": room_name, "capacity": cap})

    return rooms


# ============================================================================
# Main
# ============================================================================

def seed_infrastructure():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    log_banner("NEIL ERP — Infrastructure (écoles, campus, centres, salles)")

    # Prepare manifest sections
    manifest["infrastructure"] = {
        "schools": {},
        "faculties": {},
        "companies": {},
        "levels": {},
        "centers": {},
        "rooms": {},
    }

    # ── ÉTAPE 1 : Niveaux ──
    log_section("ÉTAPE 1 : Niveaux")
    levels = create_or_get_levels(config.get("levels", []), base, headers)
    manifest["infrastructure"]["levels"] = levels

    # ── ÉTAPE 2 : Écoles & Campus ──
    log_section("ÉTAPE 2 : Écoles & Campus")

    # Group campuses by school
    campuses_by_school = {}
    for campus in config.get("campuses", []):
        sk = campus["school_key"]
        campuses_by_school.setdefault(sk, []).append(campus)

    for school in config.get("schools", []):
        school_key = school["key"]
        school_campuses = campuses_by_school.get(school_key, [])
        if not school_campuses:
            log_warn(f"Pas de campus pour l'école '{school['name']}'")
            continue

        # Create school + first campus
        first_campus = school_campuses[0]
        school_id, first_fac_id = create_school_or_get(
            school["name"], school["short"], first_campus["name"],
            base, headers,
        )

        manifest["infrastructure"]["schools"][school_key] = {
            "id": school_id,
            "name": school["name"],
            "short": school["short"],
            "theme": school.get("theme", "sciences"),
        }
        manifest["infrastructure"]["faculties"][first_campus["key"]] = {
            "id": first_fac_id,
            "school_key": school_key,
            "name": first_campus["name"],
            "city": first_campus.get("city", ""),
        }

        # Additional campuses
        for campus in school_campuses[1:]:
            fac_id = create_faculty_or_get(campus["name"], school_id, base, headers)
            manifest["infrastructure"]["faculties"][campus["key"]] = {
                "id": fac_id,
                "school_key": school_key,
                "name": campus["name"],
                "city": campus.get("city", ""),
            }

        print()

    # ── ÉTAPE 3 : Sociétés ──
    log_section("ÉTAPE 3 : Sociétés")
    # SIREN/NAF fictifs par index (obligatoires pour l'API)
    SIREN_POOL = ["123456789", "987654321", "456789123", "321654987", "654987321"]
    NAF_POOL = ["8542Z", "8541Z", "8559A", "8559B", "8520Z"]

    for ci, comp in enumerate(config.get("companies", [])):
        log_info(f"  Société '{comp['name']}'...")
        manifest["infrastructure"]["companies"][comp["key"]] = {
            "name": comp["name"],
            "school_keys": comp.get("school_keys", []),
        }
        # Try to find existing company by name
        companies = api_get("/companies", base=base, headers=headers)
        found = False
        if isinstance(companies, list):
            for c in companies:
                if c.get("name") == comp["name"]:
                    manifest["infrastructure"]["companies"][comp["key"]]["id"] = c["id"]
                    log_ok(f"  Société '{comp['name']}' (ID:{c['id']}) [existante]")
                    found = True
                    break
        if not found:
            # Resolve school_ids for linking
            school_ids = []
            for sk in comp.get("school_keys", []):
                sid = manifest["infrastructure"]["schools"].get(sk, {}).get("id")
                if sid:
                    school_ids.append(sid)
            # Get campus address as company address (from linked center or campus city)
            campus_cfg = next((cp for cp in config.get("campuses", []) if cp["school_key"] in comp.get("school_keys", [])), None)
            company_addr = "1 rue de l'Université"
            company_city = "Paris"
            company_postal = "75001"
            if campus_cfg:
                company_city = campus_cfg.get("city", "Paris")
                company_postal = campus_cfg.get("postal", "75001")
                # Try to get address from the first linked center
                center_keys = campus_cfg.get("center_keys", [])
                center_defs = config.get("centers", {}).get("definitions", [])
                for cdef in center_defs:
                    if cdef["key"] in center_keys:
                        company_addr = cdef.get("addr", company_addr)
                        break
                else:
                    company_addr = f"1 rue de l'Université, {company_city}"
            addr = {
                "address": company_addr,
                "city": company_city,
                "postal_code": company_postal,
                "country_id": COUNTRY_FR,
            }
            payload = {
                "name": comp["name"],
                "siren": SIREN_POOL[ci % len(SIREN_POOL)],
                "naf": NAF_POOL[ci % len(NAF_POOL)],
                "address": addr,
                "school_ids": school_ids,
            }
            result = api_post("/companies", payload, base=base, headers=headers)
            if result:
                manifest["infrastructure"]["companies"][comp["key"]]["id"] = result["id"]
                log_ok(f"  Société '{comp['name']}' (ID:{result['id']})")
            else:
                log_warn(f"  Société '{comp['name']}' — impossible de créer")

    print()

    # ── ÉTAPE 4 : Centres d'activité & Salles ──
    log_section("ÉTAPE 4 : Centres d'activité & Salles")

    rooms_per_campus = config.get("centers", {}).get("rooms_per_campus", 4)
    capacity_range = config.get("centers", {}).get("capacity_range", [15, 120])
    center_defs = config.get("centers", {}).get("definitions", [])

    # Map center_key → created center_id
    center_key_to_id = {}

    if center_defs:
        # New config format: centers are defined independently
        for _ci, cdef in enumerate(center_defs):
            center_name = cdef["name"]
            center_color = cdef.get("color", "#607D8B")
            center_addr = cdef.get("addr", "1 rue Principale")
            center_city = cdef.get("city", "Paris")
            center_postal = cdef.get("postal", "75001")

            print(f"\n  ── {center_name} ──")

            center_id = create_center_or_get(
                center_name, center_color, center_addr, center_city, center_postal,
                base, headers,
            )
            center_key_to_id[cdef["key"]] = center_id

            manifest["infrastructure"]["centers"][str(center_id)] = {
                "name": center_name,
                "center_key": cdef["key"],
                "city": center_city,
            }

            # Create rooms
            room_defs = cdef.get("rooms", [])
            if not room_defs:
                school_theme = "sciences"  # fallback
                room_defs = generate_rooms_for_center(school_theme, _ci, rooms_per_campus, capacity_range, center_label=center_city)
            room_ids = []
            for rd in room_defs:
                rid = create_room(rd["name"], center_id, rd["capacity"], base, headers)
                if rid and rid > 0:
                    room_ids.append(rid)
                    manifest["infrastructure"]["rooms"][str(rid)] = {
                        "name": rd["name"],
                        "center_id": center_id,
                        "capacity": rd["capacity"],
                    }

            manifest["infrastructure"]["centers"][str(center_id)]["room_ids"] = room_ids

            # Set opening hours
            hours_template_key = cdef.get("hours_template")
            if hours_template_key and hours_template_key in CENTER_HOURS_TEMPLATES:
                hours_data = CENTER_HOURS_TEMPLATES[hours_template_key]
            else:
                hours_data = CENTER_HOURS_TEMPLATES[HOURS_ROTATION[0]]
            result = api_patch(f"/centers/{center_id}", {"openings_schedule": hours_data}, base=base, headers=headers)
            if result is not None:
                log_ok(f"  Horaires : {hours_template_key}")
            manifest["infrastructure"]["centers"][str(center_id)]["hours"] = hours_data

    else:
        # Legacy config format: one center per campus (backward compatibility)
        hours_idx = 0
        for _ci, campus in enumerate(config.get("campuses", [])):
            campus_key = campus["key"]
            school_key = campus["school_key"]
            school_theme = next(
                (s.get("theme", "sciences") for s in config["schools"] if s["key"] == school_key),
                "sciences",
            )

            center_name = campus.get("center_name", f"Centre {campus['name']}")
            center_color = campus.get("center_color", "#607D8B")
            center_addr = campus.get("center_addr", "1 rue Principale")
            center_city = campus.get("city", "Paris")
            center_postal = campus.get("postal", "75001")

            print(f"\n  ── {center_name} ──")

            center_id = create_center_or_get(
                center_name, center_color, center_addr, center_city, center_postal,
                base, headers,
            )

            manifest["infrastructure"]["centers"][str(center_id)] = {
                "name": center_name,
                "campus_key": campus_key,
                "city": center_city,
            }

            fac_entry = manifest["infrastructure"]["faculties"].get(campus_key, {})
            fac_entry["center_id"] = center_id
            manifest["infrastructure"]["faculties"][campus_key] = fac_entry

            if campus.get("rooms"):
                room_defs = campus["rooms"]
            else:
                room_defs = generate_rooms_for_center(school_theme, _ci, rooms_per_campus, capacity_range, center_label=center_city)
            room_ids = []
            for rd in room_defs:
                rid = create_room(rd["name"], center_id, rd["capacity"], base, headers)
                if rid and rid > 0:
                    room_ids.append(rid)
                    manifest["infrastructure"]["rooms"][str(rid)] = {
                        "name": rd["name"],
                        "center_id": center_id,
                        "capacity": rd["capacity"],
                    }
            fac_entry["room_ids"] = room_ids

            hours_template_key = campus.get("hours_template")
            if hours_template_key and hours_template_key in CENTER_HOURS_TEMPLATES:
                hours_data = CENTER_HOURS_TEMPLATES[hours_template_key]
            else:
                hours_template_key = HOURS_ROTATION[hours_idx % len(HOURS_ROTATION)]
                hours_data = CENTER_HOURS_TEMPLATES[hours_template_key]
            result = api_patch(f"/centers/{center_id}", {"openings_schedule": hours_data}, base=base, headers=headers)
            if result is not None:
                log_ok(f"  Horaires : {hours_template_key}")
            manifest["infrastructure"]["centers"][str(center_id)]["hours"] = hours_data
            hours_idx += 1

    print()

    # ── ÉTAPE 5 : Liaison Campus ↔ Centres ──
    log_section("ÉTAPE 5 : Liaison Campus ↔ Centres")

    all_faculties = manifest["infrastructure"]["faculties"]

    if center_defs:
        # New format: use center_keys from campus config
        for campus in config.get("campuses", []):
            campus_key = campus["key"]
            fac_data = all_faculties.get(campus_key, {})
            fac_id = fac_data.get("id")
            if not fac_id:
                continue

            assigned_center_keys = campus.get("center_keys", [])
            center_ids_to_link = [center_key_to_id[ck] for ck in assigned_center_keys if ck in center_key_to_id]

            # Also link all centers from same school for shared access
            school_key = campus.get("school_key", fac_data.get("school_key", ""))
            school_campus_keys = [c["key"] for c in config["campuses"] if c.get("school_key") == school_key]
            for other_ck in school_campus_keys:
                for center_key in config_campus_center_keys(config, other_ck):
                    cid = center_key_to_id.get(center_key)
                    if cid and cid not in center_ids_to_link:
                        center_ids_to_link.append(cid)

            if center_ids_to_link:
                link_faculty_to_centers(fac_id, center_ids_to_link, base, headers)
                # Store first center as primary for downstream compatibility
                fac_data["center_id"] = center_ids_to_link[0]
                fac_data["room_ids"] = []
                for cid in center_ids_to_link:
                    cid_str = str(cid)
                    if cid_str in manifest["infrastructure"]["centers"]:
                        fac_data["room_ids"].extend(
                            manifest["infrastructure"]["centers"][cid_str].get("room_ids", [])
                        )
    else:
        # Legacy format
        school_centers = {}
        for fac_key, fac_data in all_faculties.items():
            sk = fac_data.get("school_key", "")
            cid = fac_data.get("center_id")
            if cid:
                school_centers.setdefault(sk, []).append(cid)

        for fac_key, fac_data in all_faculties.items():
            fac_id = fac_data.get("id")
            if not fac_id:
                continue
            own_center = fac_data.get("center_id")
            school_key = fac_data.get("school_key", "")
            center_ids_to_link = [own_center] if own_center else []
            all_school_centers = school_centers.get(school_key, [])
            for cid in all_school_centers:
                if cid != own_center and cid not in center_ids_to_link:
                    center_ids_to_link.append(cid)
            if center_ids_to_link:
                link_faculty_to_centers(fac_id, center_ids_to_link, base, headers)

    print()

    # ── ÉTAPE 6 : Calendriers de contraintes ──
    log_section("ÉTAPE 6 : Calendriers de contraintes (vacances & fériés)")

    include_calendars = config.get("seeder", {}).get("include_calendars", True)
    manifest["calendars"] = {}

    if not include_calendars:
        log_warn("Calendriers de contraintes désactivés (include_calendars=false)")
    else:
        # Search for existing calendars to avoid duplicates
        existing_cals = []
        try:
            r = SESSION.post(f"{base}/constraints-calendar/search", headers=headers, json={"filters": {}})
            if r.status_code == 200:
                existing_cals = r.json()
        except Exception:
            pass
        existing_cal_names = {c.get("name", ""): c for c in existing_cals}

        for campus in config.get("campuses", []):
            campus_key = campus["key"]
            zone = campus.get("zone", "C")
            fac_data = manifest["infrastructure"]["faculties"].get(campus_key, {})
            fac_id = fac_data.get("id")
            center_id = fac_data.get("center_id")
            city = fac_data.get("city", campus.get("city", ""))

            if not fac_id:
                log_warn(f"  Campus '{campus_key}' sans ID de faculty — skip calendrier")
                continue

            cal_name = f"Zone {zone} — {city}"
            # Parse academic year for dynamic calendar generation
            academic_year = config.get("meta", {}).get("academic_year", "2025-2026")
            _ay_parts = academic_year.split("-")
            _ay_start = int(_ay_parts[0])
            _ay_end = int(_ay_parts[1]) if len(_ay_parts) > 1 else _ay_start + 1
            constraints = get_calendar_constraints(zone, year_start=_ay_start, year_end=_ay_end)

            # Check if calendar already exists
            if cal_name in existing_cal_names:
                cal = existing_cal_names[cal_name]
                cal_id = cal["id"]
                log_ok(f"  '{cal_name}' (ID:{cal_id}) [existant]")
            else:
                log_info(f"  Création calendrier '{cal_name}' (zone {zone}, {len(constraints)} contraintes)...")
                payload = {
                    "name": cal_name,
                    "faculties": [fac_id],
                    "constraints": constraints,
                }
                result = api_post("/constraints-calendar", payload, base=base, headers=headers)
                if result:
                    cal_id = result["id"]
                    log_ok(f"  '{cal_name}' (ID:{cal_id})")
                else:
                    log_error(f"  Création calendrier '{cal_name}' échouée")
                    continue

            manifest["calendars"][campus_key] = {
                "id": cal_id,
                "name": cal_name,
                "zone": zone,
                "center_id": center_id,
                "faculty_id": fac_id,
                "n_constraints": len(constraints),
            }

    print()

    # ── FINALISATION ──
    mark_step_complete(manifest, "seed_neil")
    save_manifest(manifest)

    # ── RÉSUMÉ ──
    log_banner("INFRASTRUCTURE TERMINÉE")
    n_schools = len(manifest["infrastructure"]["schools"])
    n_faculties = len(manifest["infrastructure"]["faculties"])
    n_centers = len(manifest["infrastructure"]["centers"])
    n_rooms = len(manifest["infrastructure"]["rooms"])
    n_levels = len(manifest["infrastructure"]["levels"])
    n_companies = len(manifest["infrastructure"]["companies"])
    n_calendars = len(manifest["calendars"])

    print(f"  {n_schools} écoles")
    print(f"  {n_faculties} campus")
    print(f"  {n_centers} centres d'activité")
    print(f"  {n_rooms} salles")
    print(f"  {n_levels} niveaux")
    print(f"  {n_companies} sociétés")
    print(f"  {n_calendars} calendriers de contraintes")
    print()


if __name__ == "__main__":
    seed_infrastructure()
