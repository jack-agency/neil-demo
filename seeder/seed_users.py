#!/usr/bin/env python3
"""
seed_users.py — Création des utilisateurs (employés) avec affectation de profils.

Version dynamique : lit les IDs de profils depuis le manifest.

Crée les employés répartis par profil :
  - Enseignants (majorité, assignables comme intervenants sur les séances)
  - Directeurs d'école
  - Responsables pédagogiques
  - Responsables des admissions
  - Secrétaire pédagogique
  - Comptable
  - Responsable RH
  - Multi-profil (Resp. péda + Enseignant)

Chaque employé est créé via POST /employees puis son profil est assigné
via POST /employees/{id}/profiles avec un scope total (toutes écoles).

NOTE : notify=false pour ne pas envoyer d'emails d'activation.
NOTE : DELETE /employees/{id} retourne 500 (bug API), la cleanup désactive uniquement.
"""

import requests
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, EMPLOYEE_NAME_DATASETS,
    log_info, log_ok, log_warn, log_error, log_section, log_banner,
)

SCOPE_FULL = {"schools": True, "subjects": True, "levels": True, "years": True}

# Profil admin obligatoires (1 de chaque minimum) — ordre de priorité
ADMIN_PROFILES = [
    "directeur",
    "resp_pedagogique",
    "resp_admissions",
    "secretaire",
    "comptable",
    "resp_rh",
]


def generate_employees(n_total, seed=2026, dataset_key="standard"):
    """Génère dynamiquement n_total employés avec une répartition réaliste.

    En mode "poudlard" : utilise les vrais noms du staff HP avec profils pré-assignés.
    En mode "standard" : génère des noms français avec répartition automatique.

    Distribution standard :
      - 1 de chaque profil admin (6 obligatoires)
      - 1 multi-profil (resp_pedagogique + enseignant)
      - Le reste en enseignants (≥50% du total)
    """
    import random
    import unicodedata
    rng = random.Random(seed)

    ds = EMPLOYEE_NAME_DATASETS.get(dataset_key, EMPLOYEE_NAME_DATASETS["standard"])
    paired_mode = ds.get("paired", False)
    paired_employees = ds.get("employees", []) if paired_mode else []
    first_names_m = ds["first_names_m"]
    first_names_f = ds["first_names_f"]
    last_names = ds["last_names"]

    employees = []
    used_emails = set()
    email_domain = "poudlard-neil.fr" if dataset_key == "poudlard" else "neil-demo.fr"

    def _normalize(s):
        s = unicodedata.normalize("NFKD", s)
        return "".join(c for c in s if not unicodedata.combining(c)).lower().replace(" ", "")

    def _make_employee(first, last, gender, profiles, idx):
        base_email = f"{_normalize(first)}.{_normalize(last)}"
        email = f"{base_email}@{email_domain}"
        if email in used_emails:
            email = f"{base_email}{idx}@{email_domain}"
        used_emails.add(email)

        year = rng.randint(1968, 1996)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        phone_prefix = rng.choice(["06", "07"])
        phone = f"{phone_prefix} {rng.randint(10,99)} {rng.randint(10,99)} {rng.randint(10,99)} {rng.randint(10,99)}"

        return {
            "first_name": first,
            "last_name": last,
            "gender": gender,
            "email": email,
            "birth_date": f"{year}-{month:02d}-{day:02d}",
            "phone_number": phone,
            "profiles": profiles,
        }

    def _pick_name(idx):
        if idx % 2 == 0:
            first = first_names_m[idx // 2 % len(first_names_m)]
            gender = "male"
        else:
            first = first_names_f[idx // 2 % len(first_names_f)]
            gender = "female"
        last = last_names[idx % len(last_names)]
        return first, last, gender

    if paired_mode and paired_employees:
        # Mode Poudlard : utiliser les paires fixes avec profils pré-assignés
        # D'abord les paires, puis compléter si n_total > len(paired_employees)
        for idx in range(min(n_total, len(paired_employees))):
            first, last, gender, profiles = paired_employees[idx]
            employees.append(_make_employee(first, last, gender, profiles, idx))

        # Si on demande plus d'employés que de paires, compléter avec le fallback
        idx = len(paired_employees)
        while idx < n_total:
            first, last, gender = _pick_name(idx)
            employees.append(_make_employee(first, last, gender, ["enseignant"], idx))
            idx += 1
    else:
        # Mode standard : répartition automatique
        idx = 0

        # 1. Profils admin obligatoires (1 de chaque)
        admin_count = min(len(ADMIN_PROFILES), max(0, n_total - 2))
        for pi in range(admin_count):
            first, last, gender = _pick_name(idx)
            employees.append(_make_employee(first, last, gender, [ADMIN_PROFILES[pi]], idx))
            idx += 1

        # 2. Multi-profil (resp_pedagogique + enseignant)
        if idx < n_total:
            first, last, gender = _pick_name(idx)
            employees.append(_make_employee(first, last, gender, ["resp_pedagogique", "enseignant"], idx))
            idx += 1

        # 3. Le reste en enseignants
        while idx < n_total:
            first, last, gender = _pick_name(idx)
            employees.append(_make_employee(first, last, gender, ["enseignant"], idx))
            idx += 1

    return employees


# ============================================================================
# API helpers
# ============================================================================

def get_employees(base, headers):
    """Récupère la liste des employés via POST /employees/search."""
    r = SESSION.post(f"{base}/employees/search", headers=headers, json={"filters": {}})
    if r.status_code == 200:
        return r.json()
    return []


_employee_cache = None  # Cached scan of all employees (including deactivated)

def scan_all_employees(base, headers, max_id=500):
    """Scan all employee IDs to find all employees, including deactivated ones.

    POST /employees/search doesn't return deactivated employees,
    so we scan individual IDs via GET /employees/{id}.
    Results are cached for the session.
    Uses a high miss threshold (100) because IDs can have large gaps
    (e.g. employees start at ID 81+ after previous runs).
    """
    global _employee_cache
    if _employee_cache is not None:
        return _employee_cache
    _employee_cache = {}
    miss_streak = 0
    for eid in range(1, max_id + 1):
        r = SESSION.get(f"{base}/employees/{eid}", headers=headers)
        if r.status_code == 200:
            emp = r.json()
            _employee_cache[emp.get("email", "")] = emp
            miss_streak = 0
        else:
            miss_streak += 1
            if miss_streak > 100:
                break  # No more employees likely
    return _employee_cache


def find_employee_by_email(email, base, headers):
    """Find an employee by email, including deactivated ones."""
    cache = scan_all_employees(base, headers)
    return cache.get(email)


def cleanup_non_reserved(base, headers):
    """Désactive les employés non réservés."""
    employees = get_employees(base, headers)
    reserved_ids = {1, 2, 3}
    count = 0
    for emp in employees:
        eid = emp["id"]
        if eid in reserved_ids:
            continue
        if emp.get("has_reserved") or emp.get("is_admin"):
            continue
        r = SESSION.get(f"{base}/employees/{eid}/profiles", headers=headers)
        if r.status_code == 200:
            for p in r.json():
                ep_id = p.get("employee_profile_id")
                if ep_id:
                    SESSION.delete(f"{base}/employees/{eid}/profiles/{ep_id}", headers=headers)
        SESSION.patch(f"{base}/employees/{eid}/deactivate", headers=headers)
        count += 1
    if count:
        log_info(f"{count} employé(s) nettoyé(s) (désactivés)")
    else:
        log_info("Aucun employé à nettoyer")


def upload_employee_avatar(eid, character_name, base, headers, gender="male"):
    """Upload un avatar pour un employé (même flow 3 étapes que les étudiants).

    En mode Poudlard, character_name est utilisé pour trouver la photo HP.
    En mode standard, pravatar.cc / randomuser.me sont utilisés comme fallback.
    """
    from seed_students import _download_avatar_image
    import requests as _req

    # Utiliser un offset pour éviter les collisions de pravatar avec les étudiants
    avatar_index = eid + 10000
    image_data = _download_avatar_image(avatar_index, gender, character_name=character_name)
    if not image_data:
        return False

    content_type = "image/jpeg"
    ext = "jpeg"
    if image_data[:4] == b"RIFF":
        content_type = "image/webp"
        ext = "webp"
    elif image_data[:8] == b"\x89PNG\r\n\x1a\n":
        content_type = "image/png"
        ext = "png"

    try:
        session_r = SESSION.post(
            f"{base}/employees/{eid}/avatar",
            headers=headers,
            json={"original_name": f"avatar.{ext}", "type": content_type, "size": len(image_data)},
        )
        if session_r.status_code not in (200, 201):
            return False

        upload_url = session_r.headers.get("x-upload-location", "")
        if not upload_url:
            return False

        gcs_r = _req.post(upload_url, headers={"Content-Type": content_type}, data=image_data, timeout=15)
        if gcs_r.status_code not in (200, 201):
            return False

        patch_r = SESSION.patch(f"{base}/employees/{eid}/avatar", headers=headers, json=gcs_r.json())
        return patch_r.status_code in (200, 201)
    except Exception:
        return False


def create_employee(data, profile_id_map, base, headers, upload_avatar_fn=None):
    """Crée un employé et lui assigne ses profils."""
    create_data = {
        "first_name": data["first_name"],
        "last_name": data["last_name"],
        "email": data["email"],
        "birth_date": data["birth_date"],
        "notify": False,
    }
    if data.get("phone_number"):
        create_data["phone_number"] = data["phone_number"]

    r = SESSION.post(f"{base}/employees", headers=headers, json=create_data)

    if r.status_code in (200, 201):
        emp = r.json()
        eid = emp["id"]
    elif r.status_code == 409:
        # Search includes deactivated employees (POST /employees/search skips them)
        emp = find_employee_by_email(data["email"], base, headers)
        if emp is None:
            log_warn(f"409 pour {data['first_name']} {data['last_name']} mais introuvable")
            return None, False, []
        eid = emp["id"]
        SESSION.patch(f"{base}/employees/{eid}/activate", headers=headers)
        SESSION.patch(f"{base}/employees/{eid}", headers=headers, json=create_data)
    else:
        log_error(f"{data['first_name']} {data['last_name']} — HTTP {r.status_code}: {r.text[:200]}")
        return None, False, []

    profiles_assigned = []
    employee_profile_ids = []  # IDs from POST /employees/{id}/profiles (different from employee ID)
    for profile_key in data.get("profiles", []):
        profile_id = profile_id_map.get(profile_key)
        if profile_id is None:
            log_warn(f"Profil inconnu : {profile_key}")
            continue

        rp = SESSION.post(
            f"{base}/employees/{eid}/profiles",
            headers=headers,
            json={"profile_id": profile_id, "scope": SCOPE_FULL},
        )
        if rp.status_code in (200, 201):
            profiles_assigned.append(profile_key)
            rp_data = rp.json()
            # API may return a dict or a list
            if isinstance(rp_data, list):
                for item in rp_data:
                    if isinstance(item, dict):
                        ep_id = item.get("employee_profile_id") or item.get("id")
                        if ep_id and ep_id not in employee_profile_ids:
                            employee_profile_ids.append(ep_id)
            elif isinstance(rp_data, dict):
                ep_id = rp_data.get("employee_profile_id") or rp_data.get("id")
                if ep_id:
                    employee_profile_ids.append(ep_id)
        elif rp.status_code == 409:
            profiles_assigned.append(f"{profile_key}(existed)")
            # Retrieve existing profile assignment IDs
            existing = SESSION.get(f"{base}/employees/{eid}/profiles", headers=headers)
            if existing.status_code == 200:
                ep_list = existing.json()
                if isinstance(ep_list, dict):
                    ep_list = ep_list.get("data", ep_list.get("profiles", []))
                if isinstance(ep_list, list):
                    for ep in ep_list:
                        epid = ep.get("employee_profile_id") or ep.get("id")
                        if epid and epid not in employee_profile_ids:
                            employee_profile_ids.append(epid)
        else:
            log_warn(f"Profil {profile_key} → HTTP {rp.status_code}: {rp.text[:150]}")

    # Avatar upload
    avatar_ok = False
    if upload_avatar_fn:
        char_name = f"{data['first_name']} {data['last_name']}"
        gender = data.get("gender", "male")
        avatar_ok = upload_avatar_fn(eid, char_name, base, headers, gender=gender)

    profile_str = ", ".join(profiles_assigned)
    avatar_mark = " 📷" if avatar_ok else ""
    log_ok(f"{data['first_name']} {data['last_name']} (ID:{eid}) — [{profile_str}]{avatar_mark}")
    return eid, avatar_ok, employee_profile_ids


# ============================================================================
# Main
# ============================================================================

def seed_users():
    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_profiles")

    log_banner("NEIL ERP — Utilisateurs (employés + profils)")

    # Build profile ID map from manifest
    profile_id_map = {}
    for key, data in manifest.get("profiles", {}).items():
        profile_id_map[key] = data["id"]

    if not profile_id_map:
        log_error("Aucun profil trouvé dans le manifest. Exécutez seed_profiles.py d'abord.")
        sys.exit(1)

    log_info(f"Profils depuis le manifest : {profile_id_map}")

    # Generate employee list dynamically from config
    employees_config = config.get("employees", {})
    n_employees = employees_config.get("total", 20)
    dataset_key = employees_config.get("dataset", "standard")
    random_seed = config.get("meta", {}).get("random_seed", 2026)
    EMPLOYEES = generate_employees(n_employees, seed=random_seed, dataset_key=dataset_key)

    dataset_label = "🧙 Poudlard" if dataset_key == "poudlard" else "📚 Standard"
    log_info(f"Dataset : {dataset_label}")
    log_info(f"{len(EMPLOYEES)} employés à créer (config: {n_employees})")

    # Avatars : résoudre les images HP si mode poudlard, sinon pravatar.cc
    include_avatars = config.get("seeder", {}).get("include_avatars", True)
    poudlard_mode = dataset_key == "poudlard"
    if include_avatars and poudlard_mode:
        from seed_students import _resolve_hp_images, _HP_URL_CACHE
        char_names = [f"{e['first_name']} {e['last_name']}" for e in EMPLOYEES]
        _resolve_hp_images(char_names)
        log_ok(f"{sum(1 for n in char_names if n in _HP_URL_CACHE)}/{len(char_names)} photos HP résolues")
    if include_avatars:
        log_info(f"Avatars : ✅ activés{' (photos HP)' if poudlard_mode else ' (pravatar.cc)'}")

    # Cleanup
    log_section("NETTOYAGE")
    cleanup_non_reserved(base, headers)

    # Create employees
    log_section("CRÉATION DES EMPLOYÉS")
    created_ids = []
    teachers_ids = []
    managers_ids = []
    teacher_profile_ids = []   # employee_profile_ids des enseignants (pour assignment formations/modules/groupes)
    manager_profile_ids = []   # employee_profile_ids des managers (directeurs, resp. péda, enseignants)
    by_profile = {}
    avatar_count = 0

    # Fonction d'upload d'avatar (si activé — fonctionne en mode standard ET poudlard)
    avatar_fn = upload_employee_avatar if include_avatars else None

    for emp_data in EMPLOYEES:
        eid, avatar_ok, ep_ids = create_employee(emp_data, profile_id_map, base, headers, upload_avatar_fn=avatar_fn)
        if eid is not None:
            created_ids.append(eid)
            if avatar_ok:
                avatar_count += 1
            for p in emp_data["profiles"]:
                by_profile[p] = by_profile.get(p, 0) + 1
            # Track teachers and managers (employees with pedagogy access)
            if "enseignant" in emp_data["profiles"]:
                teachers_ids.append(eid)
                managers_ids.append(eid)
                teacher_profile_ids.extend(ep_ids)
                manager_profile_ids.extend(ep_ids)
            elif any(p in emp_data["profiles"] for p in ["resp_pedagogique", "directeur"]):
                managers_ids.append(eid)
                manager_profile_ids.extend(ep_ids)

    # Verify available managers (employees with sequence scheduling permission)
    log_section("VÉRIFICATION INTERVENANTS")
    # Use first formation to check
    first_fm_id = None
    for fm_data in manifest.get("formations", {}).values():
        first_fm_id = fm_data["id"]
        break

    available_managers = []
    if first_fm_id:
        r = SESSION.post(
            f"{base}/formations/{first_fm_id}/sequences/managers-suggestions",
            headers=headers,
            json={"filters": {}},
        )
        if r.status_code == 200:
            suggestions = r.json()
            available_managers = [s for s in suggestions if not s.get("has_reserved")]
            log_info(f"{len(available_managers)} employé(s) disponibles comme intervenants")
            for s in available_managers[:5]:
                log_info(f"  → {s['first_name']} {s['last_name']} (ID:{s['id']})")
            if len(available_managers) > 5:
                log_info(f"  ... et {len(available_managers) - 5} autres")

    # Store in manifest
    manifest["employees"] = {
        "all_ids": created_ids,
        "teachers_ids": teachers_ids,
        "managers_ids": [m["id"] for m in available_managers] if available_managers else managers_ids,
        "teacher_profile_ids": teacher_profile_ids,
        "manager_profile_ids": manager_profile_ids,
        "by_profile": by_profile,
        "avatars_uploaded": avatar_count,
    }
    mark_step_complete(manifest, "seed_users")
    save_manifest(manifest)

    # Summary
    log_banner("EMPLOYÉS TERMINÉS")
    print(f"  {len(created_ids)}/{len(EMPLOYEES)} employés créés avec succès")
    if avatar_count:
        print(f"  Avatars: {avatar_count}/{len(created_ids)}")
    print()
    print("  Répartition par profil :")
    profile_labels = {
        "enseignant": "Enseignant",
        "directeur": "Directeur d'école",
        "resp_pedagogique": "Responsable pédagogique",
        "resp_admissions": "Responsable des admissions",
        "secretaire": "Secrétaire pédagogique",
        "comptable": "Comptable",
        "resp_rh": "Responsable RH",
    }
    for key, label in profile_labels.items():
        count = by_profile.get(key, 0)
        if count:
            marker = " ← intervenants séances" if key == "enseignant" else ""
            print(f"    {label:.<40} {count}{marker}")
    print()


if __name__ == "__main__":
    seed_users()
