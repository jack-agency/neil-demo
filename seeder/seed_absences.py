#!/usr/bin/env python3
"""
seed_absences.py — Génération des absences et retards sur les séances.

Utilise l'endpoint PATCH /formations/{fid}/sequences/{seqId}/attendance-list
pour enregistrer des absences et retards réalistes sur les séances existantes.

Dépend de : seed_sequences (les séances doivent exister).
"""

import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, api_get, api_patch,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)

# ============================================================================
# Configuration
# ============================================================================

# Pondération des motifs d'absence (slug → poids relatif)
ABSENCE_SLUG_WEIGHTS = [
    ("sick_leave", 30),
    ("no_reason", 20),
    ("transportation_problem", 15),
    ("family_reason", 15),
    ("medical_appointment", 10),
    ("other", 5),
    ("extented_vacation", 3),
    ("administrative_meeting", 2),
]

# Retards en secondes : (min, max)
DELAY_RANGE = (300, 1800)  # 5 min — 30 min


def pick_absence_slug(rng):
    """Choisit un motif d'absence selon les poids."""
    slugs, weights = zip(*ABSENCE_SLUG_WEIGHTS)
    return rng.choices(slugs, weights=weights, k=1)[0]


ABSENCE_COMMENTS = {
    "sick_leave": ["Certificat médical fourni", "Maladie", "Indisponible pour raison de santé", ""],
    "no_reason": ["", "", "", ""],
    "transportation_problem": ["Retard de train", "Panne de métro", "Grève des transports", "Embouteillage"],
    "family_reason": ["Raison familiale", "Événement familial", "Obligation familiale", ""],
    "medical_appointment": ["RDV médical", "Consultation spécialiste", "Examen médical", ""],
    "extented_vacation": ["Absence prolongée", "Départ anticipé en vacances", ""],
    "administrative_meeting": ["Convocation administrative", "Rendez-vous administratif", ""],
    "other": ["", "Absence signalée", "Motif personnel", ""],
}

DELAY_COMMENTS = [
    "Retard de transport", "Réveil tardif", "Embouteillage",
    "Problème de transport", "Retard bus/tram", "",
    "", "", "",
]


# ============================================================================
# Helpers
# ============================================================================

def get_formation_sequences(fid, base, headers):
    """Récupère toutes les séances d'une formation via ses modules."""
    modules_data = api_get(f"/formations/{fid}/modules", base=base, headers=headers)
    if not modules_data:
        return []

    modules = modules_data.get("modules", []) if isinstance(modules_data, dict) else []

    sequences = []
    for m in modules:
        if m.get("sequences_count", 0) == 0:
            continue
        mid = m["id"]
        seqs = api_get(f"/formations/{fid}/modules/{mid}/sequences", base=base, headers=headers)
        if not seqs:
            continue
        if isinstance(seqs, list):
            sequences.extend(seqs)
        elif isinstance(seqs, dict) and "sequences" in seqs:
            sequences.extend(seqs["sequences"])

    return sequences


def get_formation_students(fid, base, headers):
    """Récupère la liste des étudiants d'une formation."""
    r = SESSION.get(f"{base}/formations/{fid}/students", headers=headers)
    if r.status_code != 200:
        return []
    data = r.json()
    return [s["id"] for s in data.get("students", [])]


def generate_attendances(student_ids, absence_rate, delay_rate, justify_rate, rng):
    """Génère la liste d'attendances pour une séance.

    Returns:
        tuple: (attendances_list, n_absences, n_delays, n_justified)
    """
    attendances = []
    n_absences = 0
    n_delays = 0
    n_justified = 0

    for sid in student_ids:
        roll = rng.random()

        if roll < absence_rate:
            # Absence
            slug = pick_absence_slug(rng)
            justified = 1 if rng.random() < justify_rate else 0
            comment = rng.choice(ABSENCE_COMMENTS.get(slug, [""]))
            att = {
                "student_id": sid,
                "type": "absence",
                "absence_slug": slug,
                "justified": justified,
            }
            if comment:
                att["comment"] = comment
            attendances.append(att)
            n_absences += 1
            if justified:
                n_justified += 1

        elif roll < absence_rate + delay_rate:
            # Retard
            delay_seconds = rng.randint(DELAY_RANGE[0], DELAY_RANGE[1])
            # Arrondir aux 5 minutes
            delay_seconds = (delay_seconds // 300) * 300
            delay_seconds = max(300, delay_seconds)
            justified = 1 if rng.random() < justify_rate else 0
            comment = rng.choice(DELAY_COMMENTS)
            att = {
                "student_id": sid,
                "type": "delay",
                "delay": delay_seconds,
                "justified": justified,
            }
            if comment:
                att["comment"] = comment
            attendances.append(att)
            n_delays += 1
            if justified:
                n_justified += 1

        # else: présent — pas besoin d'envoyer (état par défaut)

    return attendances, n_absences, n_delays, n_justified


# ============================================================================
# Main
# ============================================================================

def seed_absences():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    # Dépendances
    require_step(manifest, "seed_sequences")

    # Config
    random_seed = config.get("meta", {}).get("random_seed", 2026)
    rng = random.Random(random_seed + 700)  # offset unique pour absences

    absences_config = config.get("absences", {})
    seeder_config = config.get("seeder", {})

    absence_rate_pct = seeder_config.get("absence_rate_pct",
                       absences_config.get("absence_rate_pct", 8))
    delay_rate_pct = seeder_config.get("delay_rate_pct",
                     absences_config.get("delay_rate_pct", 5))
    justify_rate_pct = absences_config.get("justify_rate_pct", 60)

    absence_rate = absence_rate_pct / 100.0
    delay_rate = delay_rate_pct / 100.0
    justify_rate = justify_rate_pct / 100.0

    log_banner("NEIL ERP — Absences & Retards")
    log_info(f"Taux d'absence par séance : {absence_rate_pct}%")
    log_info(f"Taux de retard par séance : {delay_rate_pct}%")
    log_info(f"Taux de justification : {justify_rate_pct}%")
    print()

    if absence_rate_pct == 0 and delay_rate_pct == 0:
        log_warn("Taux d'absence et de retard à 0% — rien à faire.")
        manifest["absences"] = {
            "total_absences": 0,
            "total_delays": 0,
            "total_sequences_processed": 0,
            "justified_pct": 0,
        }
        mark_step_complete(manifest, "seed_absences")
        save_manifest(manifest)
        return

    # Récupérer les formations depuis le manifest
    formations = manifest.get("formations", {})
    if not formations:
        log_error("Aucune formation dans le manifest.")
        return

    # Stats globales
    total_absences = 0
    total_delays = 0
    total_justified = 0
    total_sequences_processed = 0
    total_errors = 0

    formation_items = sorted(formations.items())
    n_formations = len(formation_items)

    for fi, (fm_key, fm_data) in enumerate(formation_items):
        fid = fm_data.get("id")
        fm_name = fm_data.get("name", fm_key)

        if not fid:
            continue

        log_section(f"Formation {fi + 1}/{n_formations} — {fm_name}")

        # Récupérer étudiants de la formation
        student_ids = get_formation_students(fid, base, headers)
        if not student_ids:
            log_warn(f"  Aucun étudiant dans la formation — skip")
            continue
        log_info(f"  {len(student_ids)} étudiants")

        # Récupérer séances
        sequences = get_formation_sequences(fid, base, headers)
        if not sequences:
            log_warn(f"  Aucune séance — skip")
            continue
        log_info(f"  {len(sequences)} séances")

        fm_absences = 0
        fm_delays = 0
        fm_justified = 0
        fm_errors = 0

        for si, seq in enumerate(sequences):
            seq_id = seq.get("id")
            if not seq_id:
                continue

            progress_bar(si + 1, len(sequences), prefix=f"  Séances")

            # Générer les absences/retards
            attendances, n_abs, n_del, n_just = generate_attendances(
                student_ids, absence_rate, delay_rate, justify_rate, rng,
            )

            if not attendances:
                total_sequences_processed += 1
                continue

            # Envoyer via PATCH
            r = SESSION.patch(
                f"{base}/formations/{fid}/sequences/{seq_id}/attendance-list",
                headers=headers,
                json={"attendances": attendances},
            )

            if r.status_code in (200, 201):
                fm_absences += n_abs
                fm_delays += n_del
                fm_justified += n_just
            else:
                fm_errors += 1
                if fm_errors <= 3:  # Ne pas spammer les erreurs
                    log_error(f"  Séance {seq_id} — HTTP {r.status_code}: {r.text[:200]}")

            total_sequences_processed += 1

        print()  # Après la barre de progression
        total_absences += fm_absences
        total_delays += fm_delays
        total_justified += fm_justified
        total_errors += fm_errors

        log_ok(f"  {fm_absences} absences, {fm_delays} retards" +
               (f" ({fm_errors} erreurs)" if fm_errors else ""))

    # ── FINALISATION ──
    total_events = total_absences + total_delays
    justified_pct = round(total_justified / total_events * 100) if total_events > 0 else 0

    manifest["absences"] = {
        "total_absences": total_absences,
        "total_delays": total_delays,
        "total_sequences_processed": total_sequences_processed,
        "total_errors": total_errors,
        "justified_pct": justified_pct,
    }
    mark_step_complete(manifest, "seed_absences")
    save_manifest(manifest)

    log_banner("ABSENCES & RETARDS TERMINÉS")
    print(f"  {total_absences} absences")
    print(f"  {total_delays} retards")
    print(f"  {total_sequences_processed} séances traitées")
    print(f"  {justified_pct}% justifiés")
    if total_errors:
        print(f"  {total_errors} erreurs")
    print()


if __name__ == "__main__":
    seed_absences()
