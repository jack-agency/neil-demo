#!/usr/bin/env python3
"""
seed_students.py — Génère des étudiants répartis dynamiquement sur les écoles.

Version dynamique : lit les écoles depuis seed_manifest.json, la répartition
depuis seed_config.json. Écrit les IDs étudiants dans le manifest.
"""

import requests
import random
import json
import time
import sys
import os


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_lib import (
    SESSION,
    load_config, load_manifest, save_manifest, mark_step_complete, require_step,
    get_api_config, STUDENT_NAME_DATASETS,
    log_info, log_ok, log_warn, log_error, log_section, log_banner, progress_bar,
)

COUNTRY_FR = 75

# ─── Données de génération ─────────────────────────────────────────────
# Les pools de noms sont chargés dynamiquement depuis STUDENT_NAME_DATASETS
# en fonction de config["students"]["dataset"] ("standard" ou "poudlard").
# Les variables globales ci-dessous sont les fallbacks par défaut.
_DEFAULT_DS = STUDENT_NAME_DATASETS["standard"]
FIRST_NAMES_M = _DEFAULT_DS["first_names_m"]
FIRST_NAMES_F = _DEFAULT_DS["first_names_f"]
LAST_NAMES = _DEFAULT_DS["last_names"]

CITIES = [
    ("Paris", "75001", "75"), ("Paris", "75011", "75"), ("Paris", "75015", "75"),
    ("Lyon", "69001", "69"), ("Lyon", "69003", "69"), ("Lyon", "69007", "69"),
    ("Marseille", "13001", "13"), ("Marseille", "13002", "13"), ("Marseille", "13008", "13"),
    ("Bordeaux", "33000", "33"), ("Bordeaux", "33200", "33"),
    ("Gif-sur-Yvette", "91190", "91"), ("Orsay", "91400", "91"), ("Palaiseau", "91120", "91"),
    ("Villeurbanne", "69100", "69"), ("Toulouse", "31000", "31"),
    ("Nantes", "44000", "44"), ("Montpellier", "34000", "34"),
    ("Lille", "59000", "59"), ("Strasbourg", "67000", "67"),
    ("Nice", "06000", "06"), ("Rennes", "35000", "35"),
    ("Aix-en-Provence", "13100", "13"), ("Pessac", "33600", "33"),
]

STREETS = [
    "rue de la Paix", "avenue des Champs-Élysées", "boulevard Victor Hugo",
    "rue du Commerce", "avenue de la République", "rue Pasteur",
    "rue Jean Jaurès", "rue de la Liberté", "avenue Gambetta",
    "rue du Faubourg Saint-Antoine", "boulevard Voltaire", "rue Nationale",
    "avenue du Général de Gaulle", "rue des Lilas", "impasse des Acacias",
    "allée des Tilleuls", "rue du Château", "rue de la Gare",
    "place de la Mairie", "rue des Écoles", "rue Saint-Jacques",
    "boulevard de la Mer", "rue du Soleil", "avenue Jean Moulin",
]

DEPARTMENTS = [
    ("75", "Paris"), ("69", "Lyon"), ("13", "Marseille"), ("33", "Bordeaux"),
    ("91", "Essonne"), ("31", "Toulouse"), ("44", "Nantes"), ("34", "Montpellier"),
    ("59", "Lille"), ("67", "Strasbourg"), ("06", "Nice"), ("35", "Rennes"),
]


def normalize_email(s):
    for a, b in [('é','e'),('è','e'),('ë','e'),('ê','e'),('à','a'),('â','a'),('î','i'),('ï','i'),('ô','o'),('ù','u'),('û','u'),('ç','c'),('ü','u'),('ö','o'),('ä','a'),(' ','')]:
        s = s.replace(a, b)
    return s

def generate_phone():
    return f"+33 6 {random.randint(10,99)} {random.randint(10,99)} {random.randint(10,99)} {random.randint(10,99)}"

def generate_social_number(gender, birth_year, birth_month, dept_num):
    sex = "1" if gender == "male" else "2"
    year = str(birth_year)[-2:]
    month = f"{birth_month:02d}"
    dept = dept_num.zfill(2)[:2]
    commune = f"{random.randint(1,999):03d}"
    order = f"{random.randint(1,999):03d}"
    base = f"{sex}{year}{month}{dept}{commune}{order}"
    key = 97 - (int(base) % 97)
    return f"{base}{key:02d}"

def generate_cvec():
    return f"CVEC{random.randint(1000000000, 9999999999)}"


def create_student(i, first_name, last_name, gender, school_id, base, headers,
                   force_minor=False, email_domain="edu-neil.fr", year_start=2025,
                   include_avatars=True, character_name=None):
    # Dates de naissance relatives à l'année scolaire :
    # - Mineur : né après le 1er sept de (year_start - 18) → <18 ans à la rentrée
    # - Majeur : né entre (year_start - 27) et (year_start - 19) → 19-27 ans
    minor_cutoff = year_start - 18  # Ex: 2025 → 2007
    if force_minor:
        birth_year = random.randint(minor_cutoff + 1, minor_cutoff + 2)
    else:
        birth_year = random.randint(year_start - 27, year_start - 19)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    birth_date = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"

    dept_num, dept_name = random.choice(DEPARTMENTS)
    city, postal, _ = random.choice(CITIES)

    email_base = normalize_email(first_name.lower())
    email_last = normalize_email(last_name.lower())
    email = f"{email_base}.{email_last}{random.randint(1,99)}@{email_domain}"

    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "birth_date": birth_date,
        "school_id": school_id,
        "gender": gender,
        "phone_number": generate_phone(),
        "birth_name": last_name,
        "birth_place": dept_name,
        "birth_department_number": dept_num,
        "nationality_id": COUNTRY_FR,
        "social_number": generate_social_number(gender, birth_year, birth_month, dept_num),
        "cvec_number": generate_cvec(),
        "top_level_sportsperson": random.random() < 0.03,
        "disability_recognition": random.random() < 0.05,
        "third_time": random.random() < 0.08,
        "address": {
            "address": f"{random.randint(1,150)} {random.choice(STREETS)}",
            "city": city,
            "postal_code": postal,
            "country_id": COUNTRY_FR,
        },
    }

    resp = SESSION.post(f"{base}/students", headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        log_error(f"Étudiant {first_name} {last_name}: {resp.status_code} {resp.text[:200]}")
        return None, None, False
    data = resp.json()
    student_id = data["id"]

    # Avatar upload (3-step flow: POST session → POST binary to GCS → PATCH)
    avatar_ok = False
    if include_avatars:
        avatar_ok = upload_avatar(student_id, i, gender, base, headers, character_name=character_name)

    return student_id, birth_date, avatar_ok


# ─── Avatar upload ────────────────────────────────────────────────────

# Correspondances nom commun → nom wiki (quand le titre de page diffère)
_WIKI_NAME_OVERRIDES = {
    # ── Élèves ──
    "Ginny Weasley": "Ginevra Weasley",
    "Ron Weasley": "Ronald Weasley",
    "Bill Weasley": "William Weasley",
    "Charlie Weasley": "Charles Weasley",
    "Ernie Macmillan": "Ernest Macmillan",
    "Teddy Lupin": "Edward Lupin",
    "Astoria Greengrass": "Astoria Malfoy",
    "Leanne Selwyn": "Leanne",
    "Molly Weasley": "Molly Weasley (II)",
    "James Potter": "James Sirius Potter",
    "Lily Potter": "Lily Luna Potter",
    # ── Staff Poudlard (noms français → noms wiki anglais) ──
    "Severus Rogue": "Severus Snape",
    "Pomona Chourave": "Pomona Sprout",
    "Sibylle Trelawney": "Sybill Trelawney",
    "Bathsheda Babbling": "Bathsheda Babbling",
    "Rolanda Bibine": "Rolanda Hooch",
    "Argus Rusard": "Argus Filch",
    "Poppy Pomfresh": "Poppy Pomfrey",
    "Alastor Maugrey": "Alastor Moody",
}

# Cache des images téléchargées {full_name: bytes}
_IMAGE_CACHE = {}

# Cache des URLs HP résolues {full_name: url}
_HP_URL_CACHE = {}

# ── Cache disque persistant ──
_AVATARS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatars")


def _cache_key(name):
    """Normalise un nom en clé de fichier safe."""
    import unicodedata, re
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s).strip("_").lower()


def _load_from_disk_cache(name, dataset="poudlard"):
    """Charge une image depuis le cache disque. Retourne bytes | None."""
    folder = os.path.join(_AVATARS_DIR, dataset)
    key = _cache_key(name)
    for ext in ("jpeg", "jpg", "webp", "png"):
        path = os.path.join(folder, f"{key}.{ext}")
        if os.path.isfile(path) and os.path.getsize(path) > 1000:
            with open(path, "rb") as f:
                return f.read()
    return None


def _save_to_disk_cache(name, data, dataset="poudlard"):
    """Sauvegarde une image dans le cache disque."""
    folder = os.path.join(_AVATARS_DIR, dataset)
    os.makedirs(folder, exist_ok=True)
    key = _cache_key(name)
    # Détecter l'extension
    if data[:4] == b"RIFF":
        ext = "webp"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    else:
        ext = "jpeg"
    path = os.path.join(folder, f"{key}.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def _resolve_hp_images(character_names):
    """Résout les URLs d'images pour les personnages HP via HP-API + Wiki HP.

    Charge en batch pour minimiser les appels réseau.
    Stocke les résultats dans _HP_URL_CACHE.
    """
    from urllib.parse import quote

    # 1. HP-API (personnages principaux avec images haute qualité)
    try:
        r = requests.get("https://hp-api.onrender.com/api/characters", timeout=15)
        if r.status_code == 200:
            for char in r.json():
                if char.get("image"):
                    _HP_URL_CACHE[char["name"]] = char["image"]
    except Exception:
        pass

    # 2. Wiki HP pour les personnages non trouvés (batch par 50)
    remaining = [n for n in character_names if n not in _HP_URL_CACHE]
    for i in range(0, len(remaining), 50):
        batch = remaining[i:i + 50]
        slugs = []
        slug_to_name = {}
        for name in batch:
            wiki_name = _WIKI_NAME_OVERRIDES.get(name, name)
            slug = wiki_name.replace(" ", "_")
            slugs.append(slug)
            slug_to_name[slug] = name

        titles = "|".join(slugs)
        try:
            url = (
                f"https://harrypotter.fandom.com/api.php?action=query"
                f"&titles={quote(titles)}&prop=pageimages&format=json&pithumbsize=400"
            )
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 NeilERP-Seeder/1.0"})
            if r.status_code != 200:
                continue
            data = r.json()
            # Reconstruire le mapping via les normalisations wiki
            norm_map = {}
            for n in data.get("query", {}).get("normalized", []):
                norm_map[n["to"]] = n["from"]

            pages = data.get("query", {}).get("pages", {})
            for pid, pdata in pages.items():
                img = pdata.get("thumbnail", {}).get("source")
                if not img:
                    continue
                title = pdata.get("title", "")
                # Retrouver le slug original → nom du personnage
                original_slug = norm_map.get(title, title).replace(" ", "_")
                if original_slug in slug_to_name:
                    _HP_URL_CACHE[slug_to_name[original_slug]] = img
                else:
                    # Fallback : chercher par titre wiki
                    for slug, name in slug_to_name.items():
                        wiki_name = _WIKI_NAME_OVERRIDES.get(name, name)
                        if title == wiki_name or title == wiki_name.replace("_", " "):
                            _HP_URL_CACHE[name] = img
                            break
        except Exception:
            continue


def _download_avatar_image(index, gender, character_name=None):
    """Télécharge une image d'avatar avec cache disque persistant.

    En mode Poudlard (character_name fourni), utilise l'image HP résolue.
    Sinon, utilise pravatar.cc / randomuser.me comme fallback.
    Les images téléchargées sont sauvées dans avatars/<dataset>/ pour les runs suivants.

    Returns:
        bytes | None: Image en bytes, ou None si échec.
    """
    # Mode Poudlard : image spécifique du personnage
    if character_name:
        # 1) Cache disque
        cached = _load_from_disk_cache(character_name, "poudlard")
        if cached:
            return cached
        # 2) Réseau via URL résolue
        if character_name in _HP_URL_CACHE:
            url = _HP_URL_CACHE[character_name]
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200 and len(r.content) > 1000:
                    _save_to_disk_cache(character_name, r.content, "poudlard")
                    return r.content
            except Exception:
                pass

    # Standard : cache disque par index
    cache_name = f"avatar_{index}_{gender}"

    cached = _load_from_disk_cache(cache_name, "standard")
    if cached:
        return cached

    # Fallback 1 : pravatar.cc (visages divers)
    url = f"https://i.pravatar.cc/512?u=neil-seed-{index}"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200 and len(r.content) > 1000:
            _save_to_disk_cache(cache_name, r.content, "standard")
            return r.content
    except Exception:
        pass

    # Fallback 2 : randomuser.me (portraits par genre)
    gender_path = "men" if gender == "male" else "women"
    portrait_idx = index % 100
    url2 = f"https://randomuser.me/api/portraits/{gender_path}/{portrait_idx}.jpg"
    try:
        r = requests.get(url2, timeout=8)
        if r.status_code == 200 and len(r.content) > 1000:
            _save_to_disk_cache(cache_name, r.content, "standard")
            return r.content
    except Exception:
        pass

    return None


def upload_avatar(student_id, index, gender, base, headers, character_name=None):
    """Upload un avatar pour un étudiant via le flow 3 étapes :
    1. POST /students/{id}/avatar → session + X-Upload-Location
    2. POST binary image au X-Upload-Location (Cloud Run → GCS)
    3. PATCH /students/{id}/avatar avec la réponse GCS
    """
    image_data = _download_avatar_image(index, gender, character_name=character_name)
    if not image_data:
        return False

    # Détecter le content-type (wiki renvoie du webp, pravatar du jpeg)
    content_type = "image/jpeg"
    ext = "jpeg"
    if image_data[:4] == b"RIFF":
        content_type = "image/webp"
        ext = "webp"
    elif image_data[:8] == b"\x89PNG\r\n\x1a\n":
        content_type = "image/png"
        ext = "png"

    try:
        # Step 1: Créer la session d'upload
        session_r = SESSION.post(
            f"{base}/students/{student_id}/avatar",
            headers=headers,
            json={
                "original_name": f"avatar.{ext}",
                "type": content_type,
                "size": len(image_data),
            },
        )
        if session_r.status_code not in (200, 201):
            return False

        upload_url = session_r.headers.get("x-upload-location", "")
        if not upload_url:
            return False

        # Step 2: Upload binary vers GCS via Cloud Run
        gcs_r = requests.post(
            upload_url,
            headers={"Content-Type": content_type},
            data=image_data,
            timeout=15,
        )
        if gcs_r.status_code not in (200, 201):
            return False

        gcs_response = gcs_r.json()

        # Step 3: Finaliser avec PATCH
        patch_r = SESSION.patch(
            f"{base}/students/{student_id}/avatar",
            headers=headers,
            json=gcs_response,
        )
        return patch_r.status_code in (200, 201)

    except Exception:
        return False


def register_to_school(student_id, school_id, base, headers):
    resp = SESSION.post(
        f"{base}/students/{student_id}/registrations",
        headers=headers,
        json={"school_id": school_id},
    )
    return resp.status_code in (200, 201)


# ============================================================================
# Main
# ============================================================================

def seed_students():
    global FIRST_NAMES_M, FIRST_NAMES_F, LAST_NAMES

    config = load_config()
    manifest = load_manifest()
    base, headers = get_api_config(config)

    require_step(manifest, "seed_neil")

    log_banner("NEIL ERP — Génération des étudiants")

    random.seed(config.get("meta", {}).get("random_seed", 42))

    # Load name dataset from config
    students_config = config.get("students", {})
    dataset_key = students_config.get("dataset", "standard")
    ds = STUDENT_NAME_DATASETS.get(dataset_key, STUDENT_NAME_DATASETS["standard"])
    FIRST_NAMES_M = ds["first_names_m"]
    FIRST_NAMES_F = ds["first_names_f"]
    LAST_NAMES = ds["last_names"]

    # Mode paires fixes (ex: Poudlard) : on utilise les vrais couples prénom+nom
    paired_mode = ds.get("paired", False)
    paired_students = ds.get("students", []) if paired_mode else []
    paired_idx = 0  # Index courant dans la liste de paires

    dataset_label = "🧙 Poudlard" if dataset_key == "poudlard" else "📚 Standard"
    if paired_mode:
        log_info(f"Dataset noms : {dataset_label} — {len(paired_students)} personnages (paires fixes)")
    else:
        log_info(f"Dataset noms : {dataset_label} ({len(FIRST_NAMES_M)}M + {len(FIRST_NAMES_F)}F, {len(LAST_NAMES)} noms)")

    # Parse academic year
    academic_year = config.get("meta", {}).get("academic_year", "2025-2026")
    _ay_parts = academic_year.split("-")
    year_start = int(_ay_parts[0])
    minor_cutoff_date = f"{year_start - 18}-09-01"  # Seuil de majorité au 1er sept
    log_info(f"Année scolaire : {academic_year} — seuil mineur : né après {minor_cutoff_date}")

    # Read school IDs from manifest
    schools = manifest["infrastructure"]["schools"]
    school_keys = sorted(schools.keys())

    if len(school_keys) < 1:
        log_error("Aucune école dans le manifest.")
        sys.exit(1)

    # Read student distribution from config
    total = students_config.get("total", 200)
    by_school = students_config.get("by_school", {})
    double_cursus = students_config.get("double_cursus", 0)

    # Build distribution
    distribution = []  # (school_key, school_id, count, is_double_target)
    for sk in school_keys:
        sid = schools[sk]["id"]
        count = by_school.get(sk, 0)
        distribution.append((sk, sid, count))

    # Minor percentage from config
    minor_pct = config.get("enrollments", {}).get("minor_pct", 3) / 100.0
    n_minors_target = max(0, int(total * minor_pct))

    # Avatars
    include_avatars = students_config.get("include_avatars", True)
    seeder_config = config.get("seeder", {})
    if "include_avatars" in seeder_config:
        include_avatars = seeder_config["include_avatars"]

    # Mode Poudlard : résoudre les images HP en batch avant de créer les étudiants
    poudlard_mode = dataset_key == "poudlard"
    if include_avatars and poudlard_mode:
        char_names = [f"{first} {last}" for first, last, _ in paired_students]
        # Compter les images déjà en cache disque
        n_cached = sum(1 for n in char_names if _load_from_disk_cache(n, "poudlard"))
        if n_cached == len(char_names):
            log_ok(f"📦 {n_cached}/{len(char_names)} photos HP en cache local — pas de téléchargement")
        else:
            log_info(f"📦 {n_cached}/{len(char_names)} en cache local, résolution du reste (HP-API + Wiki)...")
            _resolve_hp_images(char_names)
            log_ok(f"{len(_HP_URL_CACHE)} photos HP trouvées sur {len(char_names)} personnages")

    log_info(f"Distribution : {total} étudiants ({n_minors_target} mineurs ciblés)")
    log_info(f"Avatars : {'✅ activés' if include_avatars else '❌ désactivés'}{' (photos HP)' if poudlard_mode and include_avatars else ''}")
    for sk, sid, count in distribution:
        log_info(f"  {schools[sk]['name']} (ID:{sid}): {count} étudiants solo")
    if double_cursus > 0 and len(school_keys) >= 2:
        log_info(f"  Double cursus: {double_cursus} étudiants")
    print()

    # Email domain based on dataset
    email_domain = "poudlard-neil.fr" if dataset_key == "poudlard" else "edu-neil.fr"

    # Generate students
    created_ids = []
    minor_ids = []  # Students born after minor_cutoff_date
    _minor_counter = 0  # Track how many minors we've forced
    double_cursus_ids = []
    by_school_ids = {sk: [] for sk in school_keys}
    avatar_count = 0  # Nombre d'avatars uploadés

    def pick_name():
        """Retourne (first_name, last_name, gender) selon le mode du dataset."""
        nonlocal paired_idx
        if paired_mode and paired_students:
            pair = paired_students[paired_idx % len(paired_students)]
            paired_idx += 1
            return pair[0], pair[1], pair[2]
        else:
            gender = random.choice(["male", "female"])
            if random.random() < 0.02:
                gender = "non_binary"
            if gender == "male":
                fn = random.choice(FIRST_NAMES_M)
            elif gender == "female":
                fn = random.choice(FIRST_NAMES_F)
            else:
                fn = random.choice(FIRST_NAMES_M + FIRST_NAMES_F)
            ln = random.choice(LAST_NAMES)
            return fn, ln, gender

    student_num = 0
    # Solo students for each school
    for sk, sid, count in distribution:
        for j in range(count):
            student_num += 1
            first_name, last_name, gender = pick_name()
            char_name = f"{first_name} {last_name}" if poudlard_mode else None
            is_minor = _minor_counter < n_minors_target
            student_id, birth_date, avatar_ok = create_student(
                student_num, first_name, last_name, gender, sid, base, headers,
                force_minor=is_minor, email_domain=email_domain,
                year_start=year_start, include_avatars=include_avatars,
                character_name=char_name,
            )
            if is_minor:
                _minor_counter += 1

            if student_id:
                created_ids.append(student_id)
                by_school_ids[sk].append(student_id)
                if avatar_ok:
                    avatar_count += 1

                # Check if minor
                if birth_date and birth_date > minor_cutoff_date:
                    minor_ids.append(student_id)

            avatar_info = " 📷" if avatar_ok else ""
            progress_bar(student_num, total, f"— {first_name} {last_name} ({schools[sk]['short']}){avatar_info}")

    # Double cursus students
    if double_cursus > 0 and len(school_keys) >= 2:
        primary_sk = school_keys[0]
        primary_sid = schools[primary_sk]["id"]
        secondary_sk = school_keys[1]
        secondary_sid = schools[secondary_sk]["id"]

        for j in range(double_cursus):
            student_num += 1
            first_name, last_name, gender = pick_name()
            char_name = f"{first_name} {last_name}" if poudlard_mode else None
            student_id, birth_date, avatar_ok = create_student(
                student_num, first_name, last_name, gender, primary_sid, base, headers,
                email_domain=email_domain, year_start=year_start,
                include_avatars=include_avatars, character_name=char_name,
            )

            if student_id:
                created_ids.append(student_id)
                by_school_ids[primary_sk].append(student_id)
                if avatar_ok:
                    avatar_count += 1

                ok = register_to_school(student_id, secondary_sid, base, headers)
                if ok:
                    double_cursus_ids.append(student_id)
                    by_school_ids[secondary_sk].append(student_id)

                if birth_date and birth_date > minor_cutoff_date:
                    minor_ids.append(student_id)

            avatar_info = " 📷" if avatar_ok else ""
            progress_bar(student_num, total, f"— {first_name} {last_name} (double cursus){avatar_info}")

    print()
    print()

    # Store in manifest
    manifest["students"] = {
        "all_ids": created_ids,
        "minor_ids": minor_ids,
        "double_cursus_ids": double_cursus_ids,
        "by_school": {sk: ids for sk, ids in by_school_ids.items()},
        "avatars_uploaded": avatar_count,
    }
    mark_step_complete(manifest, "seed_students")
    save_manifest(manifest)

    log_banner("ÉTUDIANTS TERMINÉS")
    print(f"  {len(created_ids)} étudiants créés")
    for sk in school_keys:
        print(f"  {schools[sk]['name']}: {len(by_school_ids[sk])} étudiants")
    print(f"  Double cursus: {len(double_cursus_ids)}")
    print(f"  Mineurs: {len(minor_ids)}")
    print(f"  Avatars: {avatar_count}/{len(created_ids)}")
    print()


if __name__ == "__main__":
    seed_students()
