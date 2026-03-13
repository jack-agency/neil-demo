#!/usr/bin/env python3
"""
seed_formulas.py — Création dynamique des formations, formules, étapes, échéanciers,
                   remises et frais exceptionnels pour Neil ERP.

Lit seed_config.json + seed_manifest.json (infrastructure).
Crée les formations et formules, puis complète le manifest.

Remplace seed_formulas.sh (anciennement bash, maintenant Python + config-driven).
"""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, api_get, api_post, api_patch,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
)


# ============================================================================
# Helpers
# ============================================================================

def create_formation(name, faculties, levels, year_from, year_to, date_from, date_to,
                     duration_sec, capacity, base, headers):
    """Crée une formation. Retourne l'ID ou None."""
    payload = {
        "name": name,
        "is_active": True,
        "faculties": faculties,
        "levels": levels,
        "year_from": year_from,
        "year_to": year_to,
        "mod_setup": "teaching_units",
        "sequence_managers": ["modules"],
        "accessible_from": f"{date_from}T00:00:00.000Z",
        "accessible_to": f"{date_to}T23:59:59.000Z",
        "duration": duration_sec,
        "capacity": capacity,
        "tags": [],
    }
    result = api_post("/formations", payload, base=base, headers=headers)
    if result:
        return result.get("id")
    return None


def create_formula(name, faculty_id, company_id, year_from, year_to, date_from, date_to,
                   levels, price, is_salable, base, headers):
    """Crée une formule avec 2 étapes par défaut (sera PATCHé ensuite). Retourne l'ID."""
    payload = {
        "name": name,
        "faculty_id": faculty_id,
        "company_id": company_id,
        "year_from": year_from,
        "year_to": year_to,
        "accessible_from": f"{date_from}T00:00:00.000Z",
        "accessible_to": f"{date_to}T23:59:59.000Z",
        "levels": levels,
        "tags": [],
        "is_active": True,
        "is_salable": is_salable,
        "price": price,
        "steps": [
            {"name": "Candidature", "is_subscription": False, "order": 1},
            {"name": "Inscription", "is_subscription": True, "order": 2},
        ],
    }
    result = api_post("/formulas", payload, base=base, headers=headers)
    if result:
        return result.get("id")
    return None


def patch_steps(formula_id, steps_config, base, headers):
    """Met à jour les étapes d'inscription d'une formule."""
    steps = []
    n = len(steps_config)

    for i, step in enumerate(steps_config):
        s = {
            "name": step["name"],
            "is_subscription": (i == n - 1),  # Last step is subscription
            "order": i + 1,
        }

        # Description
        if "description" in step:
            s["description"] = step["description"]

        # Charge (frais)
        if "charge_cents" in step:
            s["has_charge"] = True
            s["charge"] = step["charge_cents"]
            s["charge_label"] = step.get("charge_label", "Frais")
            s["charge_is_deductible"] = step.get("charge_deductible", True)
            s["charge_is_due"] = True

        # Commission
        if step.get("commission"):
            s["commission"] = True

        # Advance (acompte)
        if "advance_cents" in step and i < n - 1:  # Last step can't have advance
            s["has_advance"] = True
            s["advance"] = step["advance_cents"]
            s["advance_label"] = step.get("advance_label", "Acompte")

        # Files
        if "files" in step:
            s["files"] = [{"name": f} for f in step["files"]]

        steps.append(s)

    result = api_patch(f"/formulas/{formula_id}/steps", {"steps": steps}, base=base, headers=headers)
    return result is not None


def get_step_ids(formula_id, base, headers):
    """Récupère les IDs des étapes d'une formule, ordonnés."""
    data = api_get(f"/formulas/{formula_id}", base=base, headers=headers)
    if not data:
        return []
    steps = sorted(data.get("steps", []), key=lambda s: s["order"])
    return [s["id"] for s in steps]


def add_set(formula_id, name, min_val, max_val, order, formation_ids, base, headers):
    """Ajoute un set de formations à une formule."""
    to_patch = [{"formation_id": fid} for fid in formation_ids]
    payload = {
        "name": name,
        "min": min_val,
        "max": max_val,
        "order": order,
        "formations": {"to_patch": to_patch},
    }
    result = api_post(f"/formulas/{formula_id}/sets", payload, base=base, headers=headers)
    if result:
        return result.get("id")
    return None


def add_discount(formula_id, name, amount_cents, base, headers):
    """Ajoute une remise fixe."""
    payload = {"name": name, "type": "fixed", "amount": amount_cents}
    result = api_post(f"/formulas/{formula_id}/discounts", payload, base=base, headers=headers)
    if result:
        return result.get("id")
    return None


def add_charge(formula_id, name, amount_cents, base, headers):
    """Ajoute un frais exceptionnel."""
    payload = {"name": name, "type": "fixed", "amount": amount_cents}
    result = api_post(f"/formulas/{formula_id}/charges", payload, base=base, headers=headers)
    if result:
        return result.get("id")
    return None


def generate_schedule_templates(schedules, price_cents, subscription_step_id, year_from=2025):
    """Génère les templates d'échéancier basés sur les types demandés.

    year_from: année de rentrée (ex: 2025 pour l'année scolaire 2025-2026).
    """
    year_to = year_from + 1
    templates = []

    for sched in schedules:
        if sched == "comptant" or sched == "unique":
            templates.append({
                "name": "Paiement comptant",
                "steps": {
                    str(subscription_step_id): [{
                        "due_date": f"{year_from}-09-15T00:00:00.000Z",
                        "label": "Solde intégral",
                        "amount": price_cents,
                        "charge_type": "payment",
                    }],
                },
            })

        elif sched == "2x":
            half = price_cents // 2
            templates.append({
                "name": "Paiement en 2 fois",
                "steps": {
                    str(subscription_step_id): [
                        {"due_date": f"{year_from}-09-15T00:00:00.000Z", "label": "1er versement", "amount": half, "charge_type": "payment"},
                        {"due_date": f"{year_to}-01-15T00:00:00.000Z", "label": "2e versement", "amount": price_cents - half, "charge_type": "payment"},
                    ],
                },
            })

        elif sched == "3x":
            third = price_cents // 3
            remainder = price_cents - 2 * third
            templates.append({
                "name": "Paiement en 3 fois",
                "steps": {
                    str(subscription_step_id): [
                        {"due_date": f"{year_from}-09-15T00:00:00.000Z", "label": "1er versement", "amount": third, "charge_type": "payment"},
                        {"due_date": f"{year_from}-12-15T00:00:00.000Z", "label": "2e versement", "amount": third, "charge_type": "payment"},
                        {"due_date": f"{year_to}-03-15T00:00:00.000Z", "label": "3e versement", "amount": remainder, "charge_type": "payment"},
                    ],
                },
            })

        elif "mensualites" in sched or "mens" in sched:
            # Extract number: "10_mensualites" → 10, "8_mensualites" → 8
            n = int("".join(c for c in sched if c.isdigit()) or "10")
            monthly = price_cents // n
            last = price_cents - (n - 1) * monthly
            items = []
            months = ["09", "10", "11", "12", "01", "02", "03", "04", "05", "06"]
            years = [year_from] * 4 + [year_to] * 6
            for i in range(n):
                m_idx = i % len(months)
                year = years[m_idx] if m_idx < len(years) else year_to
                amount = last if i == n - 1 else monthly
                items.append({
                    "due_date": f"{year}-{months[m_idx]}-15T00:00:00.000Z",
                    "label": f"Mensualité {i + 1}",
                    "amount": amount,
                    "charge_type": "payment",
                })
            templates.append({
                "name": f"{n} mensualités",
                "steps": {str(subscription_step_id): items},
            })

    return templates


# ============================================================================
# Main
# ============================================================================

def seed_formulas_and_formations():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_neil")

    log_banner("NEIL ERP — Formations & Formules")

    infra = manifest["infrastructure"]
    levels_map = infra.get("levels", {})
    faculties_map = infra.get("faculties", {})
    companies_map = infra.get("companies", {})

    manifest["formations"] = {}
    manifest["formulas"] = {}
    manifest["degrees"] = {}

    # Determine academic year
    meta = config.get("meta", {})
    academic_year = meta.get("academic_year", "2025-2026")
    parts = academic_year.split("-")
    year_from = int(parts[0])
    year_to = int(parts[1]) if len(parts) > 1 else year_from + 1

    # ═══════════════════════════════════════════════════════════════════════
    # 1. FORMATIONS
    # ═══════════════════════════════════════════════════════════════════════
    log_section("ÉTAPE 1 : Formations")

    for fm in config.get("formations", []):
        fm_key = fm["key"]
        fm_name = fm["name"]
        school_key = fm["school_key"]
        hours = fm["hours"]
        duration_sec = hours * 3600
        capacity = fm.get("capacity", 60)
        year_span = fm.get("year_span", 1)

        # Resolve campus keys to faculty IDs
        campus_keys = fm.get("campus_keys", [])
        faculty_ids = []
        for ck in campus_keys:
            fac = faculties_map.get(ck, {})
            fid = fac.get("id")
            if fid:
                faculty_ids.append(fid)
        if not faculty_ids:
            log_warn(f"Aucun campus trouvé pour la formation '{fm_name}' — skip")
            continue

        # Resolve level names to IDs
        level_names = fm.get("levels", [])
        level_ids = [levels_map[ln] for ln in level_names if ln in levels_map]

        # Formation dates
        fm_year_from = year_from
        fm_year_to = year_from + year_span

        # Trimester handling
        if fm.get("trimester") == 1:
            date_from = f"{year_from}-09-01"
            date_to = f"{year_from}-12-20"
        elif fm.get("trimester") == 2:
            date_from = f"{year_from + 1}-01-06"
            date_to = f"{year_from + 1}-03-28"
        else:
            date_from = f"{year_from}-09-01"
            date_to = f"{fm_year_to}-06-30"

        fid = create_formation(
            fm_name, faculty_ids, level_ids,
            fm_year_from, fm_year_to,
            date_from, date_to,
            duration_sec, capacity,
            base, headers,
        )

        if fid:
            log_ok(f"Formation '{fm_name}' (ID:{fid}) — {hours}h")
            manifest["formations"][fm_key] = {
                "id": fid,
                "name": fm_name,
                "school_key": school_key,
                "hours": hours,
                "theme": fm.get("theme", ""),
                "primary_center_id": faculties_map.get(campus_keys[0], {}).get("center_id") if campus_keys else None,
                "faculty_ids": faculty_ids,
                "level_ids": level_ids,
            }
        else:
            log_error(f"Échec création formation '{fm_name}'")

    print()

    # ═══════════════════════════════════════════════════════════════════════
    # 2. DIPLÔMES (avant les formules pour pouvoir les lier)
    # ═══════════════════════════════════════════════════════════════════════
    log_section("ÉTAPE 2 : Diplômes")

    schools_map = infra.get("schools", {})

    for fml in config.get("formulas", []):
        degree_config = fml.get("degree")
        if not degree_config:
            continue

        fml_key = fml["key"]
        school_key = fml["school_key"]
        school_id = schools_map.get(school_key, {}).get("id")
        if not school_id:
            log_warn(f"Pas d'école trouvée pour le diplôme de '{fml_key}' — skip")
            continue

        # Resolve primary faculty_id (first campus of school)
        school_campuses = [ck for ck, fac in faculties_map.items() if fac.get("school_key") == school_key]
        primary_fac_id = faculties_map[school_campuses[0]]["id"] if school_campuses else None

        degree_name = degree_config["name"]
        degree_official = degree_config["official_name"]
        degree_payload = {
            "school_id": school_id,
            "degree_level_id": degree_config["degree_level_id"],
            "name": degree_name[:64],
            "official_name": degree_official[:64],
        }
        if primary_fac_id:
            degree_payload["faculty_id"] = primary_fac_id
        if "code" in degree_config:
            degree_payload["code"] = degree_config["code"][:8].ljust(8, "0")

        degree_result = api_post("/degrees", degree_payload, base=base, headers=headers)
        if not degree_result:
            log_warn(f"Échec création diplôme '{degree_name}' pour formule '{fml_key}'")
            continue

        degree_id = degree_result.get("id")
        log_ok(f"Diplôme '{degree_name}' (ID:{degree_id})")

        # Create certification
        cert_payload = {
            "start_date": f"{year_from}-09-01T00:00:00.000Z",
            "end_date": f"{year_from + 3}-08-31T23:59:59.000Z",
        }
        if "rncp_level" in degree_config:
            cert_payload["rncp_level"] = degree_config["rncp_level"]

        cert_result = api_post(f"/degrees/{degree_id}/certifications", cert_payload, base=base, headers=headers)
        cert_id = None
        if cert_result:
            cert_id = cert_result.get("id")
            log_info(f"  Certification (ID:{cert_id}) — RNCP niveau {degree_config.get('rncp_level', '?')}")

        # Store in manifest keyed by formula_key
        manifest["degrees"][fml_key] = {
            "degree_id": degree_id,
            "certification_id": cert_id,
            "name": degree_name,
        }

    n_degrees = len(manifest["degrees"])
    if n_degrees:
        log_ok(f"{n_degrees} diplôme(s) créé(s)")
    else:
        log_info("Aucun diplôme configuré")
    print()

    # ═══════════════════════════════════════════════════════════════════════
    # 3. FORMULES + SETS
    # ═══════════════════════════════════════════════════════════════════════
    log_section("ÉTAPE 3 : Formules & Sets de formations")

    for fml in config.get("formulas", []):
        fml_key = fml["key"]
        fml_name = fml["name"]
        school_key = fml["school_key"]
        company_key = fml.get("company_key", "")
        price = fml["price_cents"]
        year_span = fml.get("year_span", 1)
        is_salable = fml.get("is_salable", False)

        # Resolve faculty ID (use first campus of school)
        school_campuses = [ck for ck, fac in faculties_map.items() if fac.get("school_key") == school_key]
        if not school_campuses:
            log_warn(f"Pas de campus pour la formule '{fml_name}' — skip")
            continue
        primary_fac_id = faculties_map[school_campuses[0]]["id"]

        # Resolve company ID
        comp = companies_map.get(company_key, {})
        company_id = comp.get("id", 1)

        # Resolve levels
        level_names = fml.get("levels", [])
        level_ids = [levels_map[ln] for ln in level_names if ln in levels_map]

        fml_year_from = year_from
        fml_year_to = year_from + year_span
        date_from = f"{year_from}-06-01"
        date_to = f"{fml_year_to}-06-30"

        formula_id = create_formula(
            fml_name, primary_fac_id, company_id,
            fml_year_from, fml_year_to,
            date_from, date_to,
            level_ids, price, is_salable,
            base, headers,
        )

        if not formula_id:
            log_error(f"Échec création formule '{fml_name}'")
            continue

        log_ok(f"Formule '{fml_name}' (ID:{formula_id}) — {price/100:.0f}€")

        # ── Sets obligatoires (1 formation ou plus) ──
        set_order = 1
        sets_data = []

        # Regular (mandatory) formation keys
        formation_keys = fml.get("formation_keys", [])
        if formation_keys:
            # Check if multiple formations should go in separate sets or one
            for fk in formation_keys:
                fm_data = manifest["formations"].get(fk, {})
                fm_id = fm_data.get("id")
                if fm_id:
                    set_name = fm_data.get("name", fk)
                    set_id = add_set(formula_id, set_name, 1, 1, set_order, [fm_id], base, headers)
                    if set_id:
                        sets_data.append({
                            "set_id": set_id,
                            "formations": [fm_id],
                            "formation_keys": [fk],
                            "min": 1,
                            "max": 1,
                        })
                        log_info(f"  Set '{set_name}' (ID:{set_id}) — obligatoire")
                    set_order += 1

        # Optional formation keys
        if "optional_formation_keys" in fml:
            opt_keys = fml["optional_formation_keys"]
            opt_fm_ids = []
            for fk in opt_keys:
                fm_data = manifest["formations"].get(fk, {})
                fm_id = fm_data.get("id")
                if fm_id:
                    opt_fm_ids.append(fm_id)

            if opt_fm_ids:
                opt_min = fml.get("option_min", 1)
                opt_max = fml.get("option_max", len(opt_fm_ids))
                set_id = add_set(formula_id, "Options", opt_min, opt_max, set_order, opt_fm_ids, base, headers)
                if set_id:
                    sets_data.append({
                        "set_id": set_id,
                        "formations": opt_fm_ids,
                        "formation_keys": opt_keys,
                        "min": opt_min,
                        "max": opt_max,
                    })
                    log_info(f"  Set 'Options' (ID:{set_id}) — min:{opt_min} max:{opt_max}")

        # ── Steps ──
        steps_config = fml.get("steps", [])
        if steps_config:
            ok = patch_steps(formula_id, steps_config, base, headers)
            if ok:
                log_info(f"  {len(steps_config)} étapes configurées")
            else:
                log_warn(f"  Échec configuration des étapes")

        # Get step IDs
        step_ids = get_step_ids(formula_id, base, headers)

        # ── Schedule templates ──
        schedules = fml.get("schedules", ["comptant"])
        if step_ids:
            sub_step_id = step_ids[-1]  # Last step = subscription
            templates = generate_schedule_templates(schedules, price, sub_step_id, year_from=year_from)
            if templates:
                result = api_patch(
                    f"/formulas/{formula_id}",
                    {"schedule_templates": templates},
                    base=base, headers=headers,
                )
                if result is not None:
                    log_info(f"  {len(templates)} échéanciers configurés")

        # ── Discounts ──
        discount_ids = []
        for disc in fml.get("discounts", []):
            disc_name = disc["name"]
            if "amount_cents" in disc:
                amount = disc["amount_cents"]
            elif "amount_pct" in disc:
                amount = int(price * disc["amount_pct"] / 100)
            else:
                amount = 0
            did = add_discount(formula_id, disc_name, amount, base, headers)
            if did:
                discount_ids.append(did)
                log_info(f"  Remise '{disc_name}' (ID:{did}) — {amount/100:.0f}€")

        # ── Charges ──
        charge_ids = []
        for ch in fml.get("charges", []):
            ch_name = ch["name"]
            amount = ch.get("amount_cents", 0)
            chid = add_charge(formula_id, ch_name, amount, base, headers)
            if chid:
                charge_ids.append(chid)
                log_info(f"  Frais '{ch_name}' (ID:{chid}) — {amount/100:.0f}€")

        # ── Link degree (pre-created in ÉTAPE 2) ──
        degree_data = manifest["degrees"].get(fml_key)
        if degree_data:
            link_payload = {"degree_id": degree_data["degree_id"]}
            if degree_data.get("certification_id"):
                link_payload["degree_certification_id"] = degree_data["certification_id"]
            result = api_patch(f"/formulas/{formula_id}", link_payload, base=base, headers=headers)
            if result is not None:
                log_info(f"  Formule ↔ Diplôme '{degree_data['name']}' liés")
            else:
                log_warn(f"  Échec liaison diplôme '{degree_data['name']}'")

        # ── Store in manifest ──
        manifest["formulas"][fml_key] = {
            "id": formula_id,
            "name": fml_name,
            "school_key": school_key,
            "price": price,
            "steps": step_ids,
            "discounts": discount_ids,
            "charges": charge_ids,
            "sets": sets_data,
        }
        if degree_data:
            manifest["formulas"][fml_key]["degree"] = degree_data

        print()

    # ── LIAISON CALENDRIERS ↔ FORMATIONS ──
    calendars = manifest.get("calendars", {})
    if calendars:
        log_section("LIAISON CALENDRIERS ↔ FORMATIONS")

        # Build faculty_id → calendar_id mapping
        fac_to_cal = {}  # faculty_id -> calendar_id
        for cal_key, cal_data in calendars.items():
            fac_id = cal_data.get("faculty_id")
            cal_id = cal_data.get("id")
            if fac_id and cal_id:
                fac_to_cal[fac_id] = cal_id

        linked = 0
        for fm_key, fm_data in manifest.get("formations", {}).items():
            fm_id = fm_data["id"]
            fm_faculty_ids = fm_data.get("faculty_ids", [])

            for fac_id in fm_faculty_ids:
                cal_id = fac_to_cal.get(fac_id)
                if cal_id:
                    result = api_patch(
                        f"/formations/{fm_id}/constraints-calendars",
                        {"faculty_id": fac_id, "calendar_ids": [cal_id]},
                        base=base, headers=headers,
                    )
                    if result is not None:
                        linked += 1

        log_ok(f"{linked} liaisons calendrier ↔ formation")
        print()
    else:
        log_warn("Pas de calendriers dans le manifest — skip liaison")

    # ── FINALISATION ──
    mark_step_complete(manifest, "seed_formulas")
    save_manifest(manifest)

    # ── RÉSUMÉ ──
    log_banner("FORMATIONS & FORMULES TERMINÉES")
    n_formations = len(manifest["formations"])
    n_formulas = len(manifest["formulas"])
    total_sets = sum(len(f.get("sets", [])) for f in manifest["formulas"].values())
    total_steps = sum(len(f.get("steps", [])) for f in manifest["formulas"].values())
    total_discounts = sum(len(f.get("discounts", [])) for f in manifest["formulas"].values())
    total_charges = sum(len(f.get("charges", [])) for f in manifest["formulas"].values())
    total_degrees = len(manifest.get("degrees", {}))
    total_linked = sum(1 for f in manifest["formulas"].values() if f.get("degree"))

    print(f"  {n_formations} formations créées")
    print(f"  {n_formulas} formules créées")
    print(f"  {total_sets} sets de formations")
    print(f"  {total_steps} étapes d'inscription")
    print(f"  {total_discounts} remises")
    print(f"  {total_charges} frais exceptionnels")
    if total_degrees:
        print(f"  {total_degrees} diplôme(s) créé(s), {total_linked} lié(s) à une formule")
    print()


if __name__ == "__main__":
    seed_formulas_and_formations()
