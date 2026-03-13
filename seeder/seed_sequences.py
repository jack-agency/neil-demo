#!/usr/bin/env python3
"""
seed_sequences.py — Génération des séances pour toutes les formations.

Version dynamique : lit toutes les données (centres, salles, calendriers,
formations, groupes, intervenants) depuis le manifest.

Pour chaque formation, crée des séances (sequences) programmées pour que chaque
classe effectue tous les modules, ventilés sur la durée de chaque formation
(dates accessible_from → accessible_to récupérées depuis l'API).

Contraintes respectées :
  - Dates réelles de chaque formation (accessible_from / accessible_to)
  - Horaires d'ouverture des centres (lun-ven variable, sam variable)
  - Calendriers de contraintes (vacances scolaires, jours fériés)
  - Pas de conflit de salle (une salle = une séance à la fois)
  - Pas de conflit d'intervenant (un enseignant = une séance à la fois)
  - 1-2 intervenants par séance
  - Modules ventilés sur toute la durée de la formation
"""

import requests
import json
import sys
import os
from datetime import datetime, timedelta, date, time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)

SEQ_BATCH_SIZE = int(os.environ.get("NEIL_SEQ_BATCH_SIZE", "30"))


# ============================================================================
# Build mappings from manifest
# ============================================================================

def build_rooms_by_center(manifest):
    """Build {center_id: [{id, name, capacity}, ...]} from manifest."""
    rooms_by_center = {}
    infra = manifest.get("infrastructure", {})
    rooms = infra.get("rooms", {})
    for room_id_str, room_data in rooms.items():
        center_id = room_data["center_id"]
        rooms_by_center.setdefault(center_id, []).append({
            "id": int(room_id_str),
            "name": room_data.get("name", f"Salle {room_id_str}"),
            "capacity": room_data.get("capacity", 30),
        })
    return rooms_by_center


def build_center_hours(manifest):
    """Build {center_id: {weekday: (open_sec, close_sec), ...}} from manifest."""
    center_hours = {}
    infra = manifest.get("infrastructure", {})
    centers = infra.get("centers", {})
    for center_id_str, center_data in centers.items():
        cid = int(center_id_str)
        hours = center_data.get("hours", {})
        center_hours[cid] = {}
        for day_str, times in hours.items():
            day = int(day_str)
            if isinstance(times, dict):
                center_hours[cid][day] = (times.get("open", 28800), times.get("close", 70200))
            elif isinstance(times, list) and len(times) == 2:
                center_hours[cid][day] = (times[0], times[1])
    return center_hours


def build_formation_center_map(manifest):
    """Build {formation_id: center_id} from manifest."""
    fm_center = {}
    for fm_key, fm_data in manifest.get("formations", {}).items():
        fid = fm_data["id"]
        fm_center[fid] = fm_data.get("primary_center_id")
    return fm_center


def build_managers_list(manifest):
    """Build (teachers_list, other_allowed_list) from manifest."""
    employees = manifest.get("employees", {})
    managers_ids = employees.get("managers_ids", [])
    teachers_ids = employees.get("teachers_ids", [])

    # Teachers are also managers; other_allowed are managers who aren't teachers
    teachers_set = set(teachers_ids)
    teachers = list(teachers_ids)
    other_allowed = [m for m in managers_ids if m not in teachers_set]

    return teachers, other_allowed


def build_calendar_center_map(manifest):
    """Build {calendar_id: center_id} from manifest calendars."""
    cal_center = {}
    for cal_key, cal_data in manifest.get("calendars", {}).items():
        cal_id = cal_data.get("id")
        center_id = cal_data.get("center_id")
        if cal_id and center_id:
            cal_center[cal_id] = center_id
    return cal_center


# ============================================================================
# Chargement des contraintes (vacances & fériés)
# ============================================================================

def load_constraints(base, headers, cal_center_map):
    """Charge les périodes de vacances/fériés depuis l'API."""
    r = SESSION.post(f"{base}/constraints-calendar/search", headers=headers, json={"filters": {}})
    cals = r.json()

    # Mapping center_id → set of blocked dates
    blocked = defaultdict(set)

    for cal in cals:
        cal_id = cal["id"]
        center_id = cal_center_map.get(cal_id)
        if center_id is None:
            continue
        for con in cal.get("constraints", []):
            start = datetime.fromisoformat(con["start_date"][:10]).date()
            end = datetime.fromisoformat(con["end_date"][:10]).date()
            d = start
            while d <= end:
                blocked[center_id].add(d)
                d += timedelta(days=1)

    return blocked


# ============================================================================
# Génération des créneaux disponibles
# ============================================================================

def generate_daily_slots(center_id, day, blocked_dates, center_hours):
    """Génère les créneaux horaires pour un jour donné dans un centre."""
    if day in blocked_dates.get(center_id, set()):
        return []

    wd = day.weekday()  # 0=lundi
    hours = center_hours.get(center_id, {}).get(wd)
    if hours is None:
        return []

    open_sec, close_sec = hours
    start_h = (open_sec + 3599) // 3600  # Ceil to next hour
    end_h = close_sec // 3600

    slots = []
    for h in range(start_h, end_h):
        slots.append(h * 3600)

    return slots


def build_calendar(center_id, blocked_dates, start_date, end_date, center_hours):
    """Construit le calendrier complet de créneaux pour un centre et une plage de dates."""
    cal = []
    d = start_date
    while d <= end_date:
        slots = generate_daily_slots(center_id, d, blocked_dates, center_hours)
        for s in slots:
            cal.append((d, s))
        d += timedelta(days=1)
    return cal


# ============================================================================
# Planificateur
# ============================================================================

class Scheduler:
    """Planificateur de séances sans conflits."""

    def __init__(self, blocked_dates, center_hours, rooms_by_center, teachers, other_allowed):
        self.blocked_dates = blocked_dates
        self.center_hours = center_hours
        self.rooms_by_center = rooms_by_center
        self.teachers = teachers
        self.other_allowed = other_allowed
        self.all_managers = teachers + other_allowed

        # Tracking des occupations pour détecter les conflits
        self.room_busy = defaultdict(list)
        self.teacher_busy = defaultdict(list)
        # Calendriers pré-calculés par centre
        self.calendars = {}
        # Teacher assignment counter for round-robin
        self.teacher_counter = 0

    def get_calendar(self, center_id, start_date, end_date):
        key = (center_id, start_date, end_date)
        if key not in self.calendars:
            self.calendars[key] = build_calendar(
                center_id, self.blocked_dates, start_date, end_date, self.center_hours
            )
        return self.calendars[key]

    def is_slot_free(self, entity_busy_list, day, start_sec, duration_sec):
        """Vérifie qu'un créneau est libre (pas de chevauchement)."""
        end_sec = start_sec + duration_sec
        for (bd, bs, bd_dur) in entity_busy_list:
            if bd != day:
                continue
            be = bs + bd_dur
            if start_sec < be and end_sec > bs:
                return False
        return True

    def book_slot(self, entity_busy_list, day, start_sec, duration_sec):
        """Réserve un créneau."""
        entity_busy_list.append((day, start_sec, duration_sec))

    def pick_teachers(self, center_id, day, start_sec, duration_sec, count=1):
        """Choisit count enseignants disponibles (round-robin)."""
        chosen = []
        pool = self.teachers.copy()
        if not pool:
            pool = self.all_managers.copy()
        if not pool:
            return chosen

        start_idx = self.teacher_counter % len(pool)
        for i in range(len(pool)):
            t = pool[(start_idx + i) % len(pool)]
            if self.is_slot_free(self.teacher_busy[t], day, start_sec, duration_sec):
                chosen.append(t)
                if len(chosen) >= count:
                    break
        if len(chosen) < count:
            for t in self.other_allowed:
                if t not in chosen and self.is_slot_free(self.teacher_busy[t], day, start_sec, duration_sec):
                    chosen.append(t)
                    if len(chosen) >= count:
                        break
        self.teacher_counter += 1
        return chosen

    def schedule_formation(self, fid, modules, group_sets_with_groups, center_id, start_date, end_date):
        """Planifie toutes les séances d'une formation, réparties uniformément sur toute la période."""
        sequences = []
        rooms = self.rooms_by_center.get(center_id, [])
        if not rooms:
            log_warn(f"Pas de salles pour le centre {center_id}")
            return sequences

        # Identifier les groupes principaux et sous-groupes
        main_gs = None
        sub_groups = []

        for gs_id, gs_name, groups in group_sets_with_groups:
            if not main_gs:
                main_gs = (gs_id, gs_name, groups)
            else:
                sub_groups.append((gs_id, gs_name, groups))

        if not main_gs:
            log_warn(f"Pas de groupes pour F{fid}, skip")
            return sequences

        # Catégoriser les sous-groupes (TD, TP)
        td_groups = None
        tp_groups = None
        for gs_id, gs_name, groups in sub_groups:
            name_lower = gs_name.lower()
            if "td" in name_lower:
                td_groups = (gs_id, groups)
            elif "tp" in name_lower:
                tp_groups = (gs_id, groups)

        main_gs_id, main_gs_name, main_groups = main_gs

        # ── Phase 1 : Collecter toutes les paires (module, audience) ──
        pairs = []
        for mod in modules:
            mod_type = mod.get("module_type_id")

            # TD/TP avec sous-groupes dédiés → 1 séance par sous-groupe
            # Tout le reste → 1 séance pour tout l'ensemble de groupes
            if mod_type == 4 and td_groups:
                target_gs_id, target_groups = td_groups
            elif mod_type == 5 and tp_groups:
                target_gs_id, target_groups = tp_groups
            else:
                target_gs_id = main_gs_id
                target_groups = [{"id": main_gs_id, "is_set": True}]

            if not target_groups:
                target_groups = [{"id": main_gs_id, "is_set": True}]

            for grp in target_groups:
                if grp.get("is_set"):
                    audience = {"groups": {str(grp["id"]): True}}
                else:
                    audience = {"groups": {str(target_gs_id): {str(grp["id"]): True}}}
                pairs.append((mod, audience))

        # ── Phase 2 : Distribuer uniformément sur le calendrier ──
        cal = self.get_calendar(center_id, start_date, end_date)
        if not cal:
            log_warn(f"Calendrier vide pour centre {center_id}")
            return sequences

        n_pairs = len(pairs)

        for i, (mod, audience) in enumerate(pairs):
            mod_id = mod["id"]
            mod_name = mod["name"]
            mod_dur = mod.get("default_duration", 3600)
            mod_type = mod.get("module_type_id")

            # Position cible : répartition uniforme sur toute la période
            target_idx = int(i * len(cal) / n_pairs) if n_pairs > 0 else 0

            room = self._pick_room(rooms, mod_type, mod_name)
            slot = None
            teachers = []
            max_scan = min(len(cal) - target_idx, 5000)

            # Scanner depuis la position cible (salle préférée)
            for offset in range(max_scan):
                idx = target_idx + offset
                if idx >= len(cal):
                    break
                day, start_sec = cal[idx]
                wd = day.weekday()
                hours = self.center_hours.get(center_id, {}).get(wd)
                if hours is None:
                    continue
                _, close_sec = hours
                if start_sec + mod_dur > close_sec:
                    continue
                if not self.is_slot_free(self.room_busy[room["id"]], day, start_sec, mod_dur):
                    continue
                num_teachers = 2 if mod_dur >= 7200 else 1
                teachers = self.pick_teachers(center_id, day, start_sec, mod_dur, count=num_teachers)
                if teachers:
                    slot = (day, start_sec)
                    break

            # Fallback : essayer les autres salles depuis la même position cible
            if slot is None:
                for alt_room in rooms:
                    if alt_room["id"] == room["id"]:
                        continue
                    for offset in range(max_scan):
                        idx = target_idx + offset
                        if idx >= len(cal):
                            break
                        day, start_sec = cal[idx]
                        wd = day.weekday()
                        hours = self.center_hours.get(center_id, {}).get(wd)
                        if hours is None:
                            continue
                        _, close_sec = hours
                        if start_sec + mod_dur > close_sec:
                            continue
                        if not self.is_slot_free(self.room_busy[alt_room["id"]], day, start_sec, mod_dur):
                            continue
                        num_teachers = 2 if mod_dur >= 7200 else 1
                        teachers = self.pick_teachers(center_id, day, start_sec, mod_dur, count=num_teachers)
                        if teachers:
                            slot = (day, start_sec)
                            room = alt_room
                            break
                    if slot:
                        break

            if slot is None:
                continue

            day, start_sec = slot
            self.book_slot(self.room_busy[room["id"]], day, start_sec, mod_dur)
            for t in teachers:
                self.book_slot(self.teacher_busy[t], day, start_sec, mod_dur)

            h = start_sec // 3600
            m = (start_sec % 3600) // 60
            start_dt = datetime.combine(day, time(h, m))
            start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            sequences.append({
                "formation_module_id": mod_id,
                "access_mode": "presential",
                "duration": mod_dur,
                "start_date": start_iso,
                "room_id": room["id"],
                "audience": audience,
                "managers": teachers,
            })

        return sequences

    def _pick_room(self, rooms, mod_type, mod_name):
        """Choisit la salle la plus appropriée selon le type de module."""
        name_lower = (mod_name or "").lower()

        preferred = []
        fallback = []

        for r in rooms:
            rname = r["name"].lower()
            if mod_type in (3, 10):  # CM, Séminaire → grandes salles
                if any(k in rname for k in ["amphi", "conférence", "exposition", "lumière"]):
                    preferred.append(r)
                else:
                    fallback.append(r)
            elif mod_type == 4:  # TD → salles de TD
                if any(k in rname for k in ["td", "ampère", "pagnol", "cézanne", "cours"]):
                    preferred.append(r)
                else:
                    fallback.append(r)
            elif mod_type == 5:  # TP → labos
                if any(k in rname for k in ["labo", "informatique", "physique", "simulation"]):
                    preferred.append(r)
                else:
                    fallback.append(r)
            elif mod_type == 6:  # Atelier → ateliers/studios
                if any(k in rname for k in ["atelier", "studio", "danse"]):
                    preferred.append(r)
                else:
                    fallback.append(r)
            else:
                fallback.append(r)

        candidates = preferred if preferred else fallback if fallback else rooms
        idx = hash((mod_type, mod_name)) % len(candidates)
        return candidates[idx]


# ============================================================================
# Chargement des données API
# ============================================================================

def load_formation_data(fid, base, headers, manifest):
    """Charge les modules et groupes d'une formation."""
    # Modules
    r = SESSION.get(f"{base}/formations/{fid}/modules", headers=headers)
    data = r.json()
    modules = data.get("modules", []) if isinstance(data, dict) else []

    # Groupes — reconstruit depuis l'API et le manifest
    r2 = SESSION.get(f"{base}/formations/{fid}/groups", headers=headers)
    groups_data = r2.json() if r2.status_code == 200 and r2.text else {}
    raw_groups = groups_data.get("groups", []) if isinstance(groups_data, dict) else []

    # Get group set IDs from manifest
    fm_key = None
    for k, v in manifest.get("formations", {}).items():
        if v["id"] == fid:
            fm_key = k
            break

    group_manifest = manifest.get("groups", {}).get(fm_key, {}) if fm_key else {}
    gs_ids = set(group_manifest.get("group_set_ids", []))

    # All known group IDs
    all_group_ids = set()
    for key in ["main_group_ids", "td_group_ids", "tp_group_ids"]:
        all_group_ids.update(group_manifest.get(key, []))

    # Reconstruct hierarchy
    group_sets_with_groups = []
    current_gs = None

    for g in raw_groups:
        gid = g["id"]
        if gid in gs_ids:
            current_gs = (gid, g["name"], [])
            group_sets_with_groups.append(current_gs)
        elif current_gs is not None:
            current_gs[2].append({"id": gid, "name": g.get("name", "")})

    # Fallback: if manifest doesn't have group_set_ids, try heuristic
    if not group_sets_with_groups and raw_groups:
        # Try to detect group-sets vs groups by checking if they have children
        # Group-sets are containers, groups are leaf nodes
        # Heuristic: items without a group_set_id field, or those that have no
        # matching parent, are likely group-sets
        for g in raw_groups:
            gid = g["id"]
            if gid in all_group_ids:
                if current_gs is not None:
                    current_gs[2].append({"id": gid, "name": g.get("name", "")})
            else:
                current_gs = (gid, g["name"], [])
                group_sets_with_groups.append(current_gs)

    return modules, group_sets_with_groups


# ============================================================================
# Envoi batch à l'API
# ============================================================================

def send_sequences_batch(fid, sequences, base, headers, batch_size=None):
    if batch_size is None:
        batch_size = SEQ_BATCH_SIZE
    total = len(sequences)
    created = 0
    errors = 0
    created_ids = []

    for i in range(0, total, batch_size):
        batch = sequences[i:i + batch_size]
        r = SESSION.post(
            f"{base}/formations/{fid}/sequences",
            headers=headers,
            json={"sequences": batch},
        )
        if r.status_code in (200, 201):
            result = r.json()
            if isinstance(result, list):
                created += len(result)
                for seq in result:
                    if isinstance(seq, dict) and "id" in seq:
                        created_ids.append(seq["id"])
            else:
                created += len(batch)
        else:
            errors += len(batch)
            err_text = r.text[:200] if r.text else "?"
            log_error(f"Batch {i//batch_size + 1}: HTTP {r.status_code} — {err_text}")

    return created, errors, created_ids


def cleanup_sequences(base, headers, manifest):
    """Supprime toutes les séances existantes (dépublie puis supprime)."""
    formation_ids = sorted(fm["id"] for fm in manifest.get("formations", {}).values())
    total_deleted = 0

    for fid in formation_ids:
        r = SESSION.get(f"{base}/formations/{fid}/modules", headers=headers)
        data = r.json() if r.status_code == 200 else {}
        modules = data.get("modules", []) if isinstance(data, dict) else []
        seq_ids = []
        for m in modules:
            if m.get("sequences_count", 0) > 0:
                r2 = SESSION.get(f"{base}/formations/{fid}/modules/{m['id']}/sequences", headers=headers)
                if r2.status_code == 200 and r2.text:
                    seqs = r2.json()
                    if isinstance(seqs, list):
                        seq_ids.extend([s["id"] for s in seqs])
                    elif isinstance(seqs, dict) and "sequences" in seqs:
                        seq_ids.extend([s["id"] for s in seqs["sequences"]])

        if seq_ids:
            # Dépublier d'abord (les séances publiées ne peuvent pas être supprimées)
            for i in range(0, len(seq_ids), 100):
                batch = seq_ids[i:i + 100]
                SESSION.patch(
                    f"{base}/formations/{fid}/sequences/unpublish",
                    headers=headers,
                    json={"ids": batch},
                )
            # Puis supprimer
            for i in range(0, len(seq_ids), 100):
                batch = seq_ids[i:i + 100]
                SESSION.delete(
                    f"{base}/formations/{fid}/sequences",
                    headers=headers,
                    json={"ids": batch},
                )
            total_deleted += len(seq_ids)
            log_info(f"F{fid}: {len(seq_ids)} séances supprimées")

    if total_deleted:
        log_info(f"Total: {total_deleted} séances supprimées")
    else:
        log_info("Aucune séance existante")


# ============================================================================
# Main
# ============================================================================

def seed_sequences():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_groups")
    require_step(manifest, "seed_users")
    require_step(manifest, "seed_teaching_units")

    log_banner("NEIL ERP — Séances (sequences)")

    # Parse academic year for fallback dates
    academic_year = config.get("meta", {}).get("academic_year", "2025-2026")
    _ay_parts = academic_year.split("-")
    _ay_start = int(_ay_parts[0])
    _ay_end = int(_ay_parts[1]) if len(_ay_parts) > 1 else _ay_start + 1

    # Build mappings from manifest
    rooms_by_center = build_rooms_by_center(manifest)
    center_hours = build_center_hours(manifest)
    fm_center_map = build_formation_center_map(manifest)
    teachers, other_allowed = build_managers_list(manifest)
    cal_center_map = build_calendar_center_map(manifest)

    log_info(f"{sum(len(r) for r in rooms_by_center.values())} salles dans {len(rooms_by_center)} centres")
    log_info(f"{len(teachers)} enseignants + {len(other_allowed)} autres intervenants autorisés")

    # Nettoyage
    log_section("NETTOYAGE")
    cleanup_sequences(base, headers, manifest)

    # Charger contraintes
    log_section("CHARGEMENT DES CONTRAINTES")
    blocked = load_constraints(base, headers, cal_center_map)
    for cid, dates in sorted(blocked.items()):
        log_info(f"Centre {cid}: {len(dates)} jours bloqués")

    # ================================================================
    # Affectation des enseignants aux formations, modules et groupes
    # ================================================================
    log_section("AFFECTATION DES ENSEIGNANTS")

    teacher_profile_ids = manifest.get("employees", {}).get("teacher_profile_ids", [])
    manager_profile_ids = manifest.get("employees", {}).get("manager_profile_ids", [])
    all_profile_ids = list(dict.fromkeys(manager_profile_ids + teacher_profile_ids))  # dedupe, preserve order

    assign_stats = {"formations": 0, "modules": 0, "groups": 0}

    if not all_profile_ids:
        log_warn("Aucun employee_profile_id dans le manifest — skip affectation")
    else:
        log_info(f"{len(teacher_profile_ids)} profils enseignants, {len(all_profile_ids)} profils total")

        formation_ids_sorted = sorted(fm["id"] for fm in manifest.get("formations", {}).values())
        tp_idx = 0  # round-robin teacher profile index

        for fid in formation_ids_sorted:
            # --- 1. Formation managers ---
            # Pick 2-3 teacher profiles per formation (round-robin)
            n_fm_managers = min(3, len(all_profile_ids))
            fm_managers = []
            for _ in range(n_fm_managers):
                fm_managers.append(all_profile_ids[tp_idx % len(all_profile_ids)])
                tp_idx += 1

            r = SESSION.post(
                f"{base}/formations/{fid}/managers",
                headers=headers,
                json={"managers": fm_managers},
            )
            if r.status_code in (200, 201):
                log_ok(f"F{fid}: {len(fm_managers)} managers affectés à la formation")
                assign_stats["formations"] += 1
            else:
                log_warn(f"F{fid}: affectation formation managers HTTP {r.status_code}")

            # --- 2. Module managers ---
            r_mod = SESSION.get(f"{base}/formations/{fid}/modules", headers=headers)
            mod_data = r_mod.json() if r_mod.status_code == 200 else {}
            modules_list = mod_data.get("modules", []) if isinstance(mod_data, dict) else []

            mod_assigned = 0
            for mod in modules_list:
                mid = mod["id"]
                # 1 teacher profile per module (round-robin)
                prof_id = teacher_profile_ids[tp_idx % len(teacher_profile_ids)] if teacher_profile_ids else all_profile_ids[tp_idx % len(all_profile_ids)]
                tp_idx += 1

                r_m = SESSION.patch(
                    f"{base}/formations/{fid}/modules/{mid}",
                    headers=headers,
                    json={"managers": {"add": [prof_id]}},
                )
                if r_m.status_code in (200, 201):
                    mod_assigned += 1

            assign_stats["modules"] += mod_assigned
            if modules_list:
                log_ok(f"F{fid}: {mod_assigned}/{len(modules_list)} modules avec enseignant")

            # --- 3. Group managers ---
            fm_key = None
            for k, v in manifest.get("formations", {}).items():
                if v["id"] == fid:
                    fm_key = k
                    break

            grp_manifest = manifest.get("groups", {}).get(fm_key, {}) if fm_key else {}
            all_grp_ids = []
            for key in ["main_group_ids", "td_group_ids", "tp_group_ids"]:
                all_grp_ids.extend(grp_manifest.get(key, []))

            grp_assigned = 0
            for gid in all_grp_ids:
                # 1-2 teacher profiles per group
                n_grp = min(2, len(teacher_profile_ids)) if teacher_profile_ids else 1
                grp_profs = []
                pool = teacher_profile_ids if teacher_profile_ids else all_profile_ids
                for _ in range(n_grp):
                    grp_profs.append(pool[tp_idx % len(pool)])
                    tp_idx += 1

                r_g = SESSION.post(
                    f"{base}/formations/{fid}/groups/{gid}/managers",
                    headers=headers,
                    json={"managers": grp_profs},
                )
                if r_g.status_code in (200, 201):
                    grp_assigned += 1

            assign_stats["groups"] += grp_assigned
            if all_grp_ids:
                log_ok(f"F{fid}: {grp_assigned}/{len(all_grp_ids)} groupes avec enseignant")

    # Planifier
    log_section("PLANIFICATION DES SÉANCES")
    sequence_coverage_pct = config.get("seeder", {}).get("sequence_coverage_pct", 100)
    if sequence_coverage_pct < 100:
        log_info(f"Couverture séances : {sequence_coverage_pct}%")
    scheduler = Scheduler(blocked, center_hours, rooms_by_center, teachers, other_allowed)

    sequence_publish_pct = config.get("seeder", {}).get("sequence_publish_pct", 100)
    if sequence_publish_pct < 100:
        log_info(f"Publication séances : {sequence_publish_pct}%")

    formation_ids = sorted(fm["id"] for fm in manifest.get("formations", {}).values())
    grand_total = 0
    grand_errors = 0
    ids_by_formation = {}  # fid -> [seq_ids]

    for fid in formation_ids:
        center_id = fm_center_map.get(fid)
        if center_id is None:
            log_warn(f"F{fid}: pas de centre principal, skip")
            continue

        # Récupérer les dates réelles de la formation
        f_detail = SESSION.get(f"{base}/formations/{fid}", headers=headers).json()
        fname = f_detail.get("name", f"Formation {fid}")
        f_start_str = f_detail.get("accessible_from")
        f_end_str = f_detail.get("accessible_to")
        if f_start_str and f_end_str:
            f_start = datetime.fromisoformat(f_start_str[:10]).date()
            f_end = datetime.fromisoformat(f_end_str[:10]).date()
        else:
            f_start = date(_ay_start, 9, 1)
            f_end = date(_ay_end, 6, 30)

        log_info(f"F{fid}: {fname}")
        log_info(f"  Période : {f_start} → {f_end}, Centre {center_id}")

        modules, group_sets = load_formation_data(fid, base, headers, manifest)
        if not modules:
            log_warn(f"  Pas de modules, skip")
            continue

        if not group_sets:
            # Fallback: create a virtual group-set
            grp_manifest = {}
            for fm_key, fm_data in manifest.get("formations", {}).items():
                if fm_data["id"] == fid:
                    grp_manifest = manifest.get("groups", {}).get(fm_key, {})
                    break
            gs_ids = grp_manifest.get("group_set_ids", [])
            if gs_ids:
                group_sets = [(gs_ids[0], "Tous", [{"id": gs_ids[0], "is_set": True}])]
            else:
                log_warn(f"  Pas de groupes, skip")
                continue

        log_info(f"  {len(modules)} modules, {len(group_sets)} group-sets")
        for gs_id, gs_name, grps in group_sets:
            gnames = ", ".join(g.get("name", f"G{g['id']}") for g in grps[:4])
            log_info(f"    GS{gs_id}: {gs_name} → [{gnames}{'...' if len(grps) > 4 else ''}]")

        sequences = scheduler.schedule_formation(fid, modules, group_sets, center_id, f_start, f_end)

        # Apply sequence_coverage_pct — trim sequences if < 100%
        if sequence_coverage_pct < 100 and sequences:
            import math as _math
            keep = max(1, _math.ceil(len(sequences) * sequence_coverage_pct / 100))
            sequences = sequences[:keep]

        log_info(f"  → {len(sequences)} séances planifiées")

        if sequences:
            created, errors, seq_ids = send_sequences_batch(fid, sequences, base, headers)
            log_ok(f"  {created} créées, {errors} erreurs")
            grand_total += created
            grand_errors += errors
            if seq_ids:
                ids_by_formation[fid] = seq_ids

    # Stats de conflits
    log_section("VÉRIFICATION")
    room_conflicts = 0
    for room_id, bookings in scheduler.room_busy.items():
        bookings_sorted = sorted(bookings, key=lambda x: (x[0], x[1]))
        for i in range(len(bookings_sorted) - 1):
            d1, s1, dur1 = bookings_sorted[i]
            d2, s2, dur2 = bookings_sorted[i + 1]
            if d1 == d2 and s1 + dur1 > s2:
                room_conflicts += 1

    teacher_conflicts = 0
    for tid, bookings in scheduler.teacher_busy.items():
        bookings_sorted = sorted(bookings, key=lambda x: (x[0], x[1]))
        for i in range(len(bookings_sorted) - 1):
            d1, s1, dur1 = bookings_sorted[i]
            d2, s2, dur2 = bookings_sorted[i + 1]
            if d1 == d2 and s1 + dur1 > s2:
                teacher_conflicts += 1

    unique_rooms = len(scheduler.room_busy)
    unique_teachers = len(scheduler.teacher_busy)

    # Publication des séances
    total_published = 0
    if sequence_publish_pct > 0 and ids_by_formation:
        log_section("PUBLICATION DES SÉANCES")
        import math as _math
        PUBLISH_BATCH = 100
        for fid, seq_ids in ids_by_formation.items():
            n_to_publish = _math.ceil(len(seq_ids) * sequence_publish_pct / 100)
            to_publish = seq_ids[:n_to_publish]
            if not to_publish:
                continue
            for i in range(0, len(to_publish), PUBLISH_BATCH):
                batch = to_publish[i:i + PUBLISH_BATCH]
                r = SESSION.patch(
                    f"{base}/formations/{fid}/sequences/publish",
                    headers=headers,
                    json={"ids": batch},
                )
                if r.status_code in (200, 204):
                    total_published += len(batch)
                else:
                    log_warn(f"  F{fid}: échec publication batch ({r.status_code})")
        log_ok(f"{total_published} séances publiées sur {grand_total}")
    elif sequence_publish_pct == 0:
        log_info("Publication désactivée (0%)")

    # Store in manifest
    manifest["sequences"] = {
        "total": grand_total,
        "published": total_published,
        "errors": grand_errors,
        "room_conflicts": room_conflicts,
        "teacher_conflicts": teacher_conflicts,
        "rooms_used": unique_rooms,
        "teachers_used": unique_teachers,
        "teacher_assignments": assign_stats,
    }
    mark_step_complete(manifest, "seed_sequences")
    save_manifest(manifest)

    # Summary
    log_banner("SÉANCES TERMINÉES")
    print(f"  {grand_total} séances créées ({grand_errors} erreurs)")
    print(f"  {total_published} séances publiées ({sequence_publish_pct}%)")
    print(f"  Conflits de salles     : {room_conflicts}")
    print(f"  Conflits d'intervenants: {teacher_conflicts}")
    print(f"  Salles utilisées       : {unique_rooms}")
    print(f"  Intervenants mobilisés : {unique_teachers}")
    print()
    print("  Affectation enseignants :")
    print(f"    Formations avec managers : {assign_stats['formations']}")
    print(f"    Modules avec enseignant  : {assign_stats['modules']}")
    print(f"    Groupes avec enseignant  : {assign_stats['groups']}")
    print()


if __name__ == "__main__":
    seed_sequences()
