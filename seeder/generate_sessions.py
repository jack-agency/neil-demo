#!/usr/bin/env python3
"""
generate_sessions.py — Générateur de séances léger pour la démo Neil.

Découvre les formations et modules via l'API (ou le manifest),
vérifie les séances existantes sur la plage demandée,
et génère les manquantes avec des intervenants aléatoires.

Usage :
    python3 generate_sessions.py --start 2025-09-01 --end 2026-06-30
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta, date, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config,
    load_manifest,
    get_api_config,
    log_info,
    log_ok,
    log_warn,
    log_error,
    log_section,
    log_banner,
)

BATCH_SIZE = 30


def progress(pct):
    """Émet un hint de progression pour le serveur Flask."""
    print(f"PROGRESS:{int(pct)}", flush=True)


# ═══════════════════════════════════════════════════════════════════
# Découverte des données
# ═══════════════════════════════════════════════════════════════════

def discover_formations(base, headers, manifest):
    """Récupère la liste des formations (manifest puis API)."""
    fm_map = manifest.get("formations", {})
    if fm_map:
        log_info("Source formations : manifest")
        return [{"id": v["id"], "name": v.get("name", "")} for v in fm_map.values()]

    # Fallback API
    log_info("Source formations : API search")
    try:
        r = SESSION.post(
            f"{base}/formations/search",
            headers=headers,
            json={"filters": {}},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("formations", data.get("results", []))
    except Exception as e:
        log_warn(f"Recherche formations échouée : {e}")
    return []


def discover_rooms(base, headers, manifest):
    """Récupère la liste des salles (manifest puis API)."""
    rooms_data = manifest.get("infrastructure", {}).get("rooms", {})
    if rooms_data:
        log_info("Source salles : manifest")
        return [
            {"id": int(rid), "name": r.get("name", ""), "center_id": r.get("center_id")}
            for rid, r in rooms_data.items()
        ]

    # Fallback : recherche par centres du manifest
    centers_data = manifest.get("infrastructure", {}).get("centers", {})
    if centers_data:
        rooms = []
        for cid_str in centers_data:
            try:
                r = SESSION.get(f"{base}/centers/{cid_str}", headers=headers, timeout=10)
                if r.status_code == 200:
                    center = r.json()
                    for room in center.get("rooms", []):
                        rooms.append({"id": room["id"], "name": room.get("name", "")})
            except Exception:
                pass
        if rooms:
            log_info(f"Source salles : API centers ({len(rooms)} salles)")
            return rooms

    # Dernier fallback
    try:
        r = SESSION.post(
            f"{base}/rooms/search",
            headers=headers,
            json={"filters": {}},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            result = data if isinstance(data, list) else data.get("rooms", data.get("results", []))
            if result:
                log_info("Source salles : API search")
                return result
    except Exception:
        pass
    return []


def discover_employees(base, headers, manifest):
    """Récupère les IDs des intervenants (manifest puis API)."""
    emp = manifest.get("employees", {})
    teachers = emp.get("teachers_ids", [])
    managers = emp.get("managers_ids", [])
    if teachers or managers:
        log_info("Source intervenants : manifest")
        return list(dict.fromkeys(teachers + managers))  # dedupe, preserve order

    # Fallback API
    try:
        r = SESSION.post(
            f"{base}/employees/search",
            headers=headers,
            json={"filters": {}},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            emps = data if isinstance(data, list) else data.get("employees", data.get("results", []))
            ids = [e["id"] for e in emps if isinstance(e, dict) and "id" in e]
            if ids:
                log_info("Source intervenants : API search")
                return ids
    except Exception:
        pass
    return []


# ═══════════════════════════════════════════════════════════════════
# Modules, groupes, séances existantes
# ═══════════════════════════════════════════════════════════════════

def get_modules(fid, base, headers):
    """Récupère les modules d'une formation."""
    r = SESSION.get(f"{base}/formations/{fid}/modules", headers=headers, timeout=15)
    if r.status_code == 200:
        data = r.json()
        return data.get("modules", []) if isinstance(data, dict) else data
    return []


def get_groups(fid, base, headers):
    """Récupère les groupes d'une formation (pour l'audience)."""
    r = SESSION.get(f"{base}/formations/{fid}/groups", headers=headers, timeout=10)
    if r.status_code == 200:
        data = r.json()
        return data.get("groups", []) if isinstance(data, dict) else data
    return []



# ═══════════════════════════════════════════════════════════════════
# Génération des séances
# ═══════════════════════════════════════════════════════════════════

def build_sequences(modules, groups, rooms, employees, start_d, end_d):
    """Construit les payloads de séances réparties sur la période."""
    if not modules:
        return []

    total_days = (end_d - start_d).days
    if total_days <= 0:
        return []

    # Audience : premier groupe trouvé (group-set)
    audience = {}
    if groups:
        audience = {"groups": {str(groups[0]["id"]): True}}

    sequences = []
    n = len(modules)

    for i, mod in enumerate(modules):
        # Répartition uniforme sur la période
        day_offset = int(i * total_days / n) if n > 0 else 0
        seq_date = start_d + timedelta(days=day_offset)

        # Sauter les week-ends
        while seq_date.weekday() >= 5:
            seq_date += timedelta(days=1)
        if seq_date > end_d:
            seq_date = end_d
            while seq_date.weekday() >= 5:
                seq_date -= timedelta(days=1)

        # Heure aléatoire entre 8h et 16h
        hour = random.randint(8, 16)
        start_iso = datetime.combine(seq_date, time(hour, 0)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

        duration = mod.get("default_duration") or 3600

        seq = {
            "formation_module_id": mod["id"],
            "access_mode": "presential",
            "duration": duration,
            "start_date": start_iso,
        }

        if rooms:
            seq["room_id"] = random.choice(rooms)["id"]
        if audience:
            seq["audience"] = audience

        sequences.append(seq)

    return sequences


def send_and_publish(fid, sequences, base, headers):
    """Envoie les séances par batch puis les publie."""
    total = len(sequences)
    created = 0
    all_ids = []

    for i in range(0, total, BATCH_SIZE):
        batch = sequences[i : i + BATCH_SIZE]
        try:
            r = SESSION.post(
                f"{base}/formations/{fid}/sequences",
                headers=headers,
                json={"sequences": batch},
                timeout=30,
            )
            if r.status_code in (200, 201):
                result = r.json()
                if isinstance(result, list):
                    created += len(result)
                    all_ids.extend(
                        s["id"] for s in result if isinstance(s, dict) and "id" in s
                    )
                else:
                    created += len(batch)
            else:
                log_error(f"  Batch HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log_error(f"  Batch exception: {e}")

    # Publication
    if all_ids:
        for i in range(0, len(all_ids), 100):
            batch = all_ids[i : i + 100]
            try:
                SESSION.patch(
                    f"{base}/formations/{fid}/sequences/publish",
                    headers=headers,
                    json={"ids": batch},
                    timeout=15,
                )
            except Exception:
                pass

    return created


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Générateur de séances Neil")
    parser.add_argument("--start", required=True, help="Date début YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Date fin YYYY-MM-DD")
    args = parser.parse_args()

    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)

    config = load_config()
    base, headers = get_api_config(config)
    manifest = load_manifest()

    log_banner("NEIL — Générateur de séances")
    log_info(f"Période : {start_d} → {end_d}")
    log_info(f"API : {base}")
    progress(0)

    # ── Découverte ─────────────────────────────────────────────
    log_section("DÉCOUVERTE")
    formations = discover_formations(base, headers, manifest)
    rooms = discover_rooms(base, headers, manifest)
    employees = discover_employees(base, headers, manifest)

    log_info(f"{len(formations)} formations")
    log_info(f"{len(rooms)} salles")
    log_info(f"{len(employees)} intervenants")

    if not formations:
        log_error("Aucune formation trouvée — vérifiez la configuration API")
        sys.exit(1)

    if not rooms:
        log_warn("Aucune salle trouvée — les séances seront créées sans salle")
    if not employees:
        log_warn("Aucun intervenant — les séances seront créées sans intervenant")

    progress(10)

    # ── Génération par formation ───────────────────────────────
    log_section("GÉNÉRATION DES SÉANCES")
    grand_total = 0
    n_formations = len(formations)

    for i, fm in enumerate(formations):
        fid = fm["id"]
        fname = fm.get("name", f"Formation {fid}")
        pct = 10 + int(((i + 1) / n_formations) * 85)

        modules = get_modules(fid, base, headers)
        if not modules:
            log_warn(f"  {fname}: aucun module — skip")
            progress(pct)
            continue

        log_info(f"  {fname}: {len(modules)} modules — génération des séances…")

        # Groupes pour l'audience
        groups = get_groups(fid, base, headers)

        # Construire et envoyer
        seqs = build_sequences(modules, groups, rooms, employees, start_d, end_d)
        if seqs:
            created = send_and_publish(fid, seqs, base, headers)
            grand_total += created
            log_ok(f"  {fname}: {created} séances créées et publiées")
        else:
            log_warn(f"  {fname}: rien à générer")

        progress(pct)

    progress(100)
    log_banner(f"TERMINÉ — {grand_total} séances créées")


if __name__ == "__main__":
    main()
