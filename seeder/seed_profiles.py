#!/usr/bin/env python3
"""
seed_profiles.py — Création des profils utilisateurs avec permissions granulaires.

Version dynamique : écrit les IDs de profils dans le manifest.

Profils créés (7) :
  1. Directeur d'école      — Vision consolidée, lecture + downloads
  2. Responsable pédagogique — CRUD formations, modules, notes, groupes
  3. Responsable des admissions — Formules, inscriptions, marketing
  4. Secrétaire pédagogique  — Gestion quotidienne étudiants
  5. Comptable               — Finance, paiements, factures
  6. Enseignant              — Consultation + saisie des notes
  7. Responsable RH          — Gestion employés, contrats, droits

Note : le profil Super Administrateur n'est pas créé car il existe déjà
un profil réservé (is_reserved=1, is_admin=1) fourni par défaut par Neil.

Chaque profil a des permissions adaptées au principe de moindre privilège.
L'obfuscation est configurée pour protéger les données sensibles selon le rôle.

NOTE API : le module "custom" (notifications) n'est pas accessible via l'API key
service-account. Les permissions custom.notifications doivent être configurées
manuellement dans l'interface Neil ERP après exécution du script.
"""

import requests
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete,
    get_api_config,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
)

# ============================================================================
# Définition des profils
# ============================================================================

PROFILES = [
    # ── 1. Directeur d'école ─────────────────────────────────────────────
    {
        "key": "directeur",
        "name": "Directeur d'école",
        "description": "Vision consolidée de l'école. Lecture et téléchargements sur tous les modules, sans création ni suppression.",
        "is_active": True,
        "order": 1,
        "obfuscate": None,
        "permissions": {
            "configuration": {
                "schools": {"read": True, "update": True},
                "faculties": {"read": True, "update": True},
                "subjects": {"read": True},
                "profiles": {"read": True},
                "levels": {"read": True},
                "centers": {"read": True},
                "companies": {"read": True},
                "settings": {"read": True},
            },
            "hr": {
                "employees": {"read": True, "show_permissions": True, "show_logs": True, "show_workhours": True, "download_workhours": True},
                "contracts": {"read": True},
                "documents": {"show_library": True},
                "warnings": {"read": True},
            },
            "pedagogy": {
                "formations": {"read": True, "download_students_list": True, "download": True, "download_sequences": True, "download_students_list_no_contacts": True},
                "sequences": {"attendee": True, "schedule": True, "attendance_list_download": True},
                "groups": {"read": True, "download_students_list": True, "download_sequences": True, "download_students_list_no_contacts": True},
                "modules": {"read": True, "download_sequences": True},
                "scores": {"read": True, "download": True},
                "degrees": {"read": True},
                "report_cards": {"read": True},
                "constraints_calendar": {"read": True},
                "documents": {"show_library": True},
                "warnings": {"read": True},
                "repro": {"read": True},
            },
            "marketing": {
                "formulas": {"read": True, "download_students_list": True, "download": True, "download_students_list_no_contacts": True},
                "documents": {"show_library": True},
                "warnings": {"read": True},
                "dashboard": {"read": True},
            },
            "secretariat": {
                "students": {
                    "read": True, "show_schedules": True, "show_logs": True,
                    "absences": True, "delays": True, "show_scores": True,
                    "download_students_list": True, "download_students_list_no_contacts": True,
                    "show_invoices": True,
                },
                "documents": {"show_library": True},
                "messages": {"read": True},
                "warnings": {"read": True},
            },
            "accounting": {
                "payments": {"read": True, "download": True},
                "deposit": {"read": True, "download": True},
                "invoices": {"read": True, "download": True},
                "financial_control": {"read": True, "download": True},
                "documents": {"show_library": True},
                "warnings": {"read": True},
            },
        },
    },

    # ── 2. Responsable pédagogique ───────────────────────────────────────
    {
        "key": "resp_pedagogique",
        "name": "Responsable pédagogique",
        "description": "Gestion complète des formations, modules, notes, groupes et calendriers. Scopé par école et niveaux.",
        "is_active": True,
        "order": 2,
        "obfuscate": {
            "student": ["phone_number", "address", "city"],
            "parent": ["phone_number", "email", "address", "city"],
        },
        "permissions": {
            "configuration": {
                "schools": {"read": True},
                "faculties": {"read": True},
                "levels": {"read": True},
                "subjects": {"read": True},
            },
            "pedagogy": {
                "formations": {
                    "read": True, "create": True, "update": True, "delete": True,
                    "download_students_list": True, "download": True,
                    "download_sequences": True, "download_students_list_no_contacts": True,
                },
                "sequences": {"attendee": True, "schedule": True, "attendance_list_download": True},
                "groups": {
                    "read": True, "update": True, "create": True, "delete": True,
                    "download_students_list": True, "download_sequences": True,
                    "download_students_list_no_contacts": True,
                },
                "modules": {
                    "read": True, "create": True, "update": True, "delete": True,
                    "download_sequences": True, "import_shared_resource": True,
                },
                "scores": {"read": True, "create": True, "update": True, "delete": True, "download": True},
                "degrees": {"read": True, "create": True, "update": True, "delete": True},
                "report_cards": {"read": True, "create": True, "update": True, "delete": True},
                "repro": {"read": True, "create": True, "update": True, "delete": True},
                "constraints_calendar": {"read": True, "create": True, "update": True, "delete": True},
                "documents": {"show_library": True, "update_tags": True, "show_bin": True},
                "warnings": {"read": True, "update": True},
            },
            "secretariat": {
                "students": {"read": True, "absences": True, "delays": True, "show_scores": True},
            },
            "marketing": {
                "formulas": {"read": True},
            },
        },
    },

    # ── 3. Responsable des admissions ────────────────────────────────────
    {
        "key": "resp_admissions",
        "name": "Responsable des admissions",
        "description": "Gestion des formules, inscriptions et suivi marketing. Scopé par école, niveau et année.",
        "is_active": True,
        "order": 3,
        "obfuscate": None,
        "permissions": {
            "configuration": {
                "schools": {"read": True},
                "levels": {"read": True},
            },
            "marketing": {
                "formulas": {
                    "read": True, "create": True, "update": True, "delete": True,
                    "download_students_list": True, "download": True,
                    "download_students_list_no_contacts": True,
                },
                "documents": {"show_library": True, "update_tags": True},
                "warnings": {"read": True, "update": True},
                "dashboard": {"read": True},
            },
            "secretariat": {
                "students": {
                    "read": True, "create": True, "update": True,
                    "formula_registration": True, "send_activation_email": True,
                    "show_schedules": True, "update_schedules": True,
                    "download_students_list": True, "download_students_list_no_contacts": True,
                    "registration_transfer": True,
                    "show_student_files": True, "download_student_files": True,
                },
                "documents": {"show_library": True},
                "messages": {"read": True, "create": True},
                "warnings": {"read": True, "update": True},
                "employers": {"read": True, "create": True, "update": True, "delete": True},
            },
        },
    },

    # ── 4. Secrétaire pédagogique ────────────────────────────────────────
    {
        "key": "secretaire",
        "name": "Secrétaire pédagogique",
        "description": "Gestion quotidienne des étudiants : fichiers, absences, retards, messages. Scopé par école et campus.",
        "is_active": True,
        "order": 4,
        "obfuscate": None,
        "permissions": {
            "configuration": {
                "schools": {"read": True},
                "faculties": {"read": True},
            },
            "secretariat": {
                "students": {
                    "read": True, "update": True,
                    "show_student_files": True, "create_student_files": True,
                    "update_student_files": True, "delete_student_files": True,
                    "download_student_files": True,
                    "show_schedules": True, "absences": True, "delays": True,
                    "send_activation_email": True, "show_scores": True,
                    "download_students_list": True, "download_students_list_no_contacts": True,
                    "read_message": True, "create_message": True,
                    "update_message": True, "delete_message": True,
                    "show_logs": True,
                },
                "documents": {"show_library": True, "update_tags": True},
                "messages": {"read": True, "create": True, "update": True, "delete": True},
                "warnings": {"read": True, "update": True},
            },
            "pedagogy": {
                "formations": {"read": True},
                "groups": {"read": True},
                "sequences": {"attendee": True},
            },
        },
    },

    # ── 5. Comptable ─────────────────────────────────────────────────────
    {
        "key": "comptable",
        "name": "Comptable",
        "description": "Gestion financière : paiements, remises en banque, factures et contrôle. Scopé par société.",
        "is_active": True,
        "order": 5,
        "obfuscate": {
            "student": ["phone_number", "address", "city", "photo"],
            "parent": ["phone_number", "address", "city", "photo"],
            "employee": ["personal_email", "personal_phone_number", "address", "city", "photo"],
        },
        "permissions": {
            "configuration": {
                "companies": {"read": True},
            },
            "accounting": {
                "payments": {"read": True, "update": True, "delete": True, "download": True},
                "deposit": {
                    "read": True, "create": True, "delete": True,
                    "download": True, "to_bank": True, "cancel_bank": True,
                },
                "invoices": {"read": True, "download": True, "update": True, "delete": True, "save": True},
                "financial_control": {"read": True, "download": True},
                "documents": {
                    "show_library": True, "update_tags": True, "show_bin": True,
                    "show_orphans_company": True, "show_logs": True,
                },
                "warnings": {"read": True, "update": True},
            },
            "secretariat": {
                "students": {
                    "read": True, "show_schedules": True, "update_schedules": True,
                    "report_unpaid": True, "report_payment": True, "refund": True,
                    "show_invoices": True, "create_invoices": True,
                    "update_invoices": True, "delete_invoices": True, "save_invoices": True,
                },
            },
            "marketing": {
                "formulas": {"read": True},
            },
        },
    },

    # ── 6. Enseignant ────────────────────────────────────────────────────
    {
        "key": "enseignant",
        "name": "Enseignant",
        "description": "Consultation des formations et saisie des notes. Accès limité aux formations assignées. Scopé par école, matière et formations.",
        "is_active": True,
        "order": 6,
        "obfuscate": {
            "student": ["email", "phone_number", "address", "city"],
            "parent": ["last_name", "first_name", "email", "phone_number", "address", "city"],
        },
        "permissions": {
            "pedagogy": {
                "formations": {"read": True},
                "sequences": {"attendee": True, "schedule": True},
                "groups": {"read": True},
                "modules": {"read": True},
                "scores": {"read": True, "create": True, "update": True},
                "documents": {"show_library": True},
            },
            "secretariat": {
                "students": {"read": True, "absences": True, "delays": True},
            },
        },
    },

    # ── 7. Responsable RH ────────────────────────────────────────────────
    {
        "key": "resp_rh",
        "name": "Responsable RH",
        "description": "Gestion du personnel : employés, contrats, permissions et heures de travail. Scopé par société.",
        "is_active": True,
        "order": 7,
        "obfuscate": {
            "student": ["last_name", "first_name", "email", "phone_number", "address", "city", "photo"],
            "parent": ["last_name", "first_name", "email", "phone_number", "address", "city", "photo"],
        },
        "permissions": {
            "configuration": {
                "schools": {"read": True},
                "profiles": {"read": True},
            },
            "hr": {
                "employees": {
                    "read": True, "create": True, "update": True, "delete": True,
                    "show_permissions": True, "add_permissions": True,
                    "update_permissions": True, "delete_permissions": True,
                    "send_email_permissions": True,
                    "show_employee_files": True, "create_employee_files": True,
                    "update_employee_files": True, "delete_employee_files": True,
                    "download_employee_files": True,
                    "show_logs": True,
                    "show_workhours": True, "download_workhours": True,
                },
                "documents": {
                    "show_library": True, "update_tags": True, "show_bin": True, "show_logs": True,
                },
                "contracts": {"read": True, "create": True, "update": True, "delete": True},
                "warnings": {"read": True, "update": True},
            },
        },
    },
]


# ============================================================================
# API helpers
# ============================================================================

def get_profiles(base, headers):
    """Récupère la liste des profils existants."""
    r = SESSION.get(f"{base}/profiles", headers=headers)
    if r.status_code == 200:
        return r.json()
    return []


def create_profile(data, base, headers):
    """
    Crée un profil en 2 étapes :
    1. POST /profiles avec métadonnées (sans permissions)
    2. POST /profiles/{id}/permissions avec les permissions
    """
    create_data = {
        "name": data["name"],
        "description": data.get("description", ""),
        "is_active": data.get("is_active", True),
        "order": data.get("order"),
    }
    if data.get("obfuscate") is not None:
        create_data["obfuscate"] = data["obfuscate"]

    r = SESSION.post(f"{base}/profiles", headers=headers, json=create_data)

    if r.status_code in (200, 201):
        pid = r.json()["id"]
    elif r.status_code == 409:
        existing = get_profiles(base, headers)
        pid = None
        for p in existing:
            if p["name"] == data["name"]:
                pid = p["id"]
                break
        if pid is None:
            log_error(f"Profil '{data['name']}' en conflit mais introuvable")
            return None
        SESSION.patch(f"{base}/profiles/{pid}", headers=headers, json=create_data)
    else:
        log_error(f"Création '{data['name']}': {r.status_code} {r.text[:300]}")
        return None

    if "permissions" in data and data["permissions"]:
        ok = set_permissions(pid, data["permissions"], base, headers)
        if not ok:
            log_warn(f"Profil '{data['name']}' créé (id={pid}) mais permissions partielles")

    if data.get("obfuscate") is not None:
        set_obfuscation(pid, data["obfuscate"], base, headers)

    return pid


def set_permissions(pid, permissions, base, headers):
    """Remplace toutes les permissions d'un profil."""
    r = SESSION.post(
        f"{base}/profiles/{pid}/permissions",
        headers=headers,
        json={"permissions": permissions},
    )
    if r.status_code not in (200, 201):
        log_warn(f"Erreur permissions profil {pid}: {r.status_code} {r.text[:200]}")
    return r.status_code in (200, 201)


def set_obfuscation(pid, obfuscate, base, headers):
    """Configure le masquage de données pour un profil."""
    r = SESSION.patch(
        f"{base}/profiles/{pid}",
        headers=headers,
        json={"obfuscate": obfuscate},
    )
    return r.status_code in (200, 201)


def delete_profile(pid, base, headers):
    """Supprime un profil."""
    r = SESSION.delete(f"{base}/profiles/{pid}", headers=headers)
    return r.status_code in (200, 204)


def get_profile_permissions(pid, base, headers):
    """Récupère les permissions d'un profil."""
    r = SESSION.get(f"{base}/profiles/{pid}/permissions", headers=headers)
    if r.status_code == 200:
        return r.json()
    return {}


def count_permissions(perms):
    """Compte le nombre total de permissions individuelles (true) dans l'arbre."""
    n = 0
    for module_perms in perms.values():
        if isinstance(module_perms, dict):
            for feature_perms in module_perms.values():
                if isinstance(feature_perms, dict):
                    n += sum(1 for v in feature_perms.values() if v is True)
    return n


# ============================================================================
# Cleanup
# ============================================================================

def cleanup(base, headers):
    """Supprime tous les profils custom existants (pas les réservés)."""
    log_section("CLEANUP")
    existing = get_profiles(base, headers)
    deleted = 0
    for p in existing:
        if not p.get("is_reserved") and not p.get("is_admin"):
            ok = delete_profile(p["id"], base, headers)
            if ok:
                deleted += 1
                log_info(f"Supprimé : {p['name']} (id={p['id']})")
    if deleted == 0:
        log_info("Aucun profil custom à supprimer")


# ============================================================================
# Main
# ============================================================================

def seed_profiles():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    log_banner("NEIL ERP — Profils utilisateurs")

    cleanup(base, headers)

    # Create profiles
    log_section("CRÉATION DES PROFILS")
    profile_ids = {}

    for profile_def in PROFILES:
        name = profile_def["name"]
        key = profile_def["key"]
        pid = create_profile(profile_def, base, headers)

        if pid:
            perms = get_profile_permissions(pid, base, headers)
            n_modules = len(perms)
            n_perms = count_permissions(perms)
            obfusc = "oui" if profile_def.get("obfuscate") else "non"
            log_ok(f"{name:35s} (id={pid:2d}) — {n_modules} modules, {n_perms:3d} permissions, masquage={obfusc}")
            profile_ids[key] = {"id": pid, "name": name}
        else:
            log_error(f"{name:35s} — ÉCHEC")

    # Verify
    log_section("VÉRIFICATION")
    profiles = get_profiles(base, headers)
    log_info(f"{len(profiles)} profils trouvés")

    for p in profiles:
        pid = p["id"]
        perms = get_profile_permissions(pid, base, headers)
        n_perms = count_permissions(perms)
        modules = list(perms.keys())

        active = "✅" if p.get("is_active") else "⏸️ "
        admin = " [ADMIN]" if p.get("is_admin") else ""
        reserved = " [RÉSERVÉ]" if p.get("is_reserved") else ""
        obfusc = " 🔒" if p.get("obfuscate") else ""
        log_info(f"  {active} {p['name']:35s} id={pid:2d} — {n_perms:3d} permissions — [{', '.join(modules)}]{obfusc}{admin}{reserved}")

    # Store in manifest
    manifest["profiles"] = profile_ids
    mark_step_complete(manifest, "seed_profiles")
    save_manifest(manifest)

    # Summary
    log_banner("PROFILS TERMINÉS")
    print(f"  {len(profile_ids)} profils créés")
    for key, data in profile_ids.items():
        print(f"    {data['id']:2d}. {data['name']} ({key})")
    print()
    log_warn("Le module 'custom' (notifications) n'est pas configurable via")
    print("     l'API key service-account. Configurer manuellement dans l'interface.")
    print()


if __name__ == "__main__":
    seed_profiles()
