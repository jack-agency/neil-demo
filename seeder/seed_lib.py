#!/usr/bin/env python3
"""
seed_lib.py — Bibliothèque partagée pour les scripts de seed Neil ERP.

Fournit :
  - Lecture/écriture de seed_config.json et seed_manifest.json
  - Helpers API (GET, POST, PATCH, DELETE) avec gestion d'erreurs
  - Générateur de configuration par défaut (generate_default_config)
  - Pools de noms réalistes pour les différents thèmes
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import os
import sys
import re
import random
import copy
from urllib.parse import urlparse

# ============================================================================
# Chemins
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "seed_config.json")
MANIFEST_PATH = os.path.join(SCRIPT_DIR, "seed_manifest.json")
MANIFESTS_DIR = os.path.join(SCRIPT_DIR, "manifests")


# ============================================================================
# Instance-aware manifest (multi-endpoint)
# ============================================================================

# Module-level state: set by load_config(), used by load_manifest()/save_manifest()
_current_manifest_path = None


def instance_slug(base_url):
    """Extrait un slug filesystem-safe depuis une URL API.

    Exemples :
        "https://ecopia.erp.neil.app/api"      -> "ecopia"
        "https://neil-claude.erp.neil.app/api"  -> "neil-claude"
        "https://custom.domain.com/api"         -> "custom.domain.com"
        ""                                      -> "default"
    """
    if not base_url:
        return "default"
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        return "default"
    # Pour le pattern *.erp.neil.app, extraire le sous-domaine
    m = re.match(r'^([^.]+)\.erp\.neil\.app$', host)
    if m:
        return m.group(1)
    # Pour les autres domaines, utiliser le hostname complet (nettoyé)
    slug = re.sub(r'[^a-zA-Z0-9._-]', '_', host)
    return slug or "default"


def _compute_manifest_path(base_url):
    """Calcule le chemin du manifest pour une URL API donnée."""
    slug = instance_slug(base_url)
    if slug == "default":
        return MANIFEST_PATH
    return os.path.join(MANIFESTS_DIR, f"seed_manifest_{slug}.json")


def get_current_manifest_path():
    """Retourne le chemin du manifest de l'instance courante (pour le dashboard)."""
    return _current_manifest_path or MANIFEST_PATH



# ============================================================================
# Shared HTTP session with automatic retry on connection errors
# ============================================================================

def _make_session():
    """Create a requests.Session with retry on network errors."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,         # 1s, 2s, 4s, 8s, 16s
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "POST", "PATCH", "DELETE"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=1, pool_connections=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = _make_session()

# ============================================================================
# Couleurs pour les logs
# ============================================================================

class C:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN = "\033[0;36m"
    MAGENTA = "\033[0;35m"
    NC = "\033[0m"


def log_info(msg):
    print(f"{C.CYAN}[INFO]{C.NC}  {msg}")

def log_ok(msg):
    print(f"{C.GREEN}[OK]{C.NC}    {msg}")

def log_warn(msg):
    print(f"{C.YELLOW}[WARN]{C.NC}  {msg}")

def log_error(msg):
    print(f"{C.RED}[ERROR]{C.NC} {msg}", file=sys.stderr)

def log_section(msg):
    print(f"\n{C.YELLOW}━━ {msg} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.NC}")

def log_banner(msg):
    print(f"\n{C.CYAN}{'═' * 66}{C.NC}")
    print(f"{C.CYAN}   {msg}{C.NC}")
    print(f"{C.CYAN}{'═' * 66}{C.NC}\n")

def progress_bar(current, total, prefix="", width=40):
    filled = current * width // total if total > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r  [{bar}] {current}/{total} {prefix}")
    sys.stdout.flush()


# ============================================================================
# Config I/O
# ============================================================================

def load_config(path=None):
    """Charge la config depuis seed_config.json et configure le manifest path."""
    global _current_manifest_path
    p = path or CONFIG_PATH
    if not os.path.exists(p):
        log_warn(f"Config introuvable ({p}), génération de la config par défaut...")
        config = generate_default_config()
        save_config(config, p)
    else:
        with open(p, "r", encoding="utf-8") as f:
            config = json.load(f)

    # Résolution du manifest path selon l'instance API
    base_url = config.get("api", {}).get("base_url", "")
    base_url = os.environ.get("NEIL_API_BASE", base_url) or ""
    _current_manifest_path = _compute_manifest_path(base_url)

    # Créer le dossier manifests/ si nécessaire
    manifest_dir = os.path.dirname(_current_manifest_path)
    if manifest_dir and manifest_dir != SCRIPT_DIR and not os.path.exists(manifest_dir):
        os.makedirs(manifest_dir, exist_ok=True)

    return config


def save_config(config, path=None):
    """Écrit la config dans seed_config.json."""
    p = path or CONFIG_PATH
    with open(p, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    log_ok(f"Config sauvegardée → {os.path.basename(p)}")


# ============================================================================
# Manifest I/O
# ============================================================================

def load_manifest(path=None):
    """Charge le manifest (instance-aware si load_config a été appelé)."""
    p = path or _current_manifest_path or MANIFEST_PATH
    if not os.path.exists(p):
        return {"meta": {"steps_completed": []}}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest, path=None):
    """Écrit le manifest (instance-aware si load_config a été appelé)."""
    p = path or _current_manifest_path or MANIFEST_PATH
    d = os.path.dirname(p)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def mark_step_complete(manifest, step_name):
    """Marque une étape comme terminée dans le manifest."""
    if step_name not in manifest["meta"]["steps_completed"]:
        manifest["meta"]["steps_completed"].append(step_name)


def require_step(manifest, step_name):
    """Vérifie qu'une étape a été complétée, sinon exit."""
    if step_name not in manifest.get("meta", {}).get("steps_completed", []):
        log_error(f"Étape requise non terminée : {step_name}")
        log_error(f"Exécutez d'abord le script correspondant.")
        sys.exit(1)


# ============================================================================
# API helpers
# ============================================================================

def get_api_config(config=None):
    """Retourne (base_url, headers) depuis la config ou les variables d'env."""
    if config:
        base = config.get("api", {}).get("base_url", "")
        key = config.get("api", {}).get("key", "")
    else:
        base = ""
        key = ""

    base = os.environ.get("NEIL_API_BASE", base) or "https://neil-claude.erp.neil.app/api"
    key = os.environ.get("NEIL_API_KEY", key) or "LoYrwWXSNbqY/PFKRv4l2rCV.X3YF1HYVqBVcNeaOQnMmN52EyhLXNmzKNNl1Z+7ViFN31AxZT+ja9RqED7SlQIww"

    headers = {
        "X-Lucius-Api-Key": key,
        "Content-Type": "application/json",
    }
    return base, headers


def api_get(path, config=None, base=None, headers=None):
    """GET request. Retourne le JSON ou None en cas d'erreur."""
    if base is None or headers is None:
        base, headers = get_api_config(config)
    r = SESSION.get(f"{base}{path}", headers=headers, timeout=30)
    if r.status_code != 200:
        log_error(f"GET {path} → {r.status_code}: {r.text[:300]}")
        return None
    return r.json()


def api_post(path, data, config=None, base=None, headers=None):
    """POST request. Retourne le JSON ou None en cas d'erreur."""
    if base is None or headers is None:
        base, headers = get_api_config(config)
    r = SESSION.post(f"{base}{path}", headers=headers, json=data, timeout=30)
    if r.status_code not in (200, 201):
        log_error(f"POST {path} → {r.status_code}: {r.text[:300]}")
        return None
    return r.json()


def api_patch(path, data, config=None, base=None, headers=None):
    """PATCH request. Retourne le JSON ou None en cas d'erreur."""
    if base is None or headers is None:
        base, headers = get_api_config(config)
    r = SESSION.patch(f"{base}{path}", headers=headers, json=data, timeout=30)
    if r.status_code not in (200, 201, 204):
        log_error(f"PATCH {path} → {r.status_code}: {r.text[:300]}")
        return None
    if r.status_code == 204:
        return {}
    try:
        return r.json()
    except Exception:
        return {}


def api_delete(path, data=None, config=None, base=None, headers=None):
    """DELETE request. Retourne True si succès."""
    if base is None or headers is None:
        base, headers = get_api_config(config)
    if data:
        r = SESSION.delete(f"{base}{path}", headers=headers, json=data, timeout=30)
    else:
        r = SESSION.delete(f"{base}{path}", headers=headers, timeout=30)
    if r.status_code not in (200, 204):
        log_error(f"DELETE {path} → {r.status_code}: {r.text[:300]}")
        return False
    return True


def api_post_safe(path, data, config=None, base=None, headers=None):
    """POST qui retourne (status_code, json_or_text) sans exit en cas d'erreur."""
    if base is None or headers is None:
        base, headers = get_api_config(config)
    r = SESSION.post(f"{base}{path}", headers=headers, json=data, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


# ============================================================================
# Pools de noms et données
# ============================================================================

# ── Datasets de noms pour les étudiants et parents ──────────────────────────
# Chaque dataset contient des prénoms M/F, noms de famille, et prénoms de parents.
# Le dataset "standard" est utilisé par défaut, "poudlard" pour le thème Harry Potter.

STUDENT_NAME_DATASETS = {
    "standard": {
        "first_names_m": [
            "Adam", "Alexandre", "Antoine", "Arthur", "Baptiste", "Benjamin", "Charles",
            "Clément", "Damien", "David", "Édouard", "Émile", "Étienne", "Fabien",
            "Florian", "Gabriel", "Guillaume", "Hugo", "Ibrahim", "Ismaël", "Julien",
            "Kévin", "Léo", "Louis", "Lucas", "Mathieu", "Maxime", "Nathan", "Nicolas",
            "Olivier", "Paul", "Pierre", "Quentin", "Raphaël", "Romain", "Samuel",
            "Théo", "Thomas", "Valentin", "Victor", "Xavier", "Yann", "Zacharie",
            "Adrien", "Bastien", "Cédric", "Dylan", "Erwan", "Félix", "Gaël",
        ],
        "first_names_f": [
            "Adèle", "Alice", "Amandine", "Anaïs", "Aurélie", "Béatrice", "Camille",
            "Charlotte", "Chloé", "Clara", "Diane", "Élodie", "Emma", "Eva", "Fanny",
            "Gabrielle", "Hélène", "Inès", "Jade", "Julie", "Justine", "Laetitia",
            "Laura", "Léa", "Lina", "Louise", "Manon", "Marie", "Mathilde", "Morgane",
            "Nathalie", "Nina", "Noémie", "Océane", "Pauline", "Rachel", "Romane",
            "Sarah", "Sofia", "Sophie", "Valentine", "Victoire", "Yasmine", "Zoé",
            "Agathe", "Clémence", "Élise", "Flora", "Margaux", "Salomé",
        ],
        "last_names": [
            "Martin", "Bernard", "Thomas", "Petit", "Robert", "Richard", "Durand",
            "Dubois", "Moreau", "Laurent", "Simon", "Michel", "Lefèvre", "Leroy",
            "Roux", "David", "Bertrand", "Morel", "Fournier", "Girard", "Bonnet",
            "Dupont", "Lambert", "Fontaine", "Rousseau", "Vincent", "Müller", "Lefèvre",
            "Faure", "André", "Mercier", "Blanc", "Guérin", "Boyer", "Garnier",
            "Chevalier", "François", "Legrand", "Gauthier", "Garcia", "Perrin",
            "Robin", "Clément", "Morin", "Nicolas", "Henry", "Roussel", "Mathieu",
            "Gautier", "Masson", "Marchand", "Duval", "Denis", "Dumont", "Marie",
            "Lemaire", "Noël", "Meyer", "Dufour", "Meunier", "Brun", "Blanchard",
            "Giraud", "Joly", "Rivière", "Lucas", "Brunet", "Gaillard", "Barbier",
            "Arnaud", "Martinez", "Gérard", "Renard", "Schmitt", "Roy", "Collet",
            "Leclercq", "Renaud", "Colin", "Vidal", "Picard", "Aubert",
        ],
        "father_names": [
            "Jean", "Philippe", "Michel", "Alain", "Patrick", "Bruno", "Christophe",
            "Didier", "Éric", "François", "Gilles", "Hervé", "Jacques", "Laurent",
            "Marc", "Nicolas", "Olivier", "Pascal", "Pierre", "Thierry", "Vincent",
            "Yves", "Stéphane", "Frédéric", "Dominique", "Bernard", "Daniel",
            "Serge", "Gérard", "Christian", "André", "Robert", "David", "Sébastien",
            "Antoine", "Benoît", "Cédric", "Emmanuel", "Fabrice", "Guillaume",
        ],
        "mother_names": [
            "Catherine", "Nathalie", "Isabelle", "Sylvie", "Christine", "Véronique",
            "Sandrine", "Marie", "Anne", "Florence", "Valérie", "Brigitte",
            "Françoise", "Laurence", "Sophie", "Corinne", "Patricia", "Martine",
            "Stéphanie", "Delphine", "Céline", "Audrey", "Pascale", "Dominique",
            "Hélène", "Claire", "Émilie", "Béatrice", "Agnès", "Élisabeth",
            "Monique", "Jocelyne", "Myriam", "Carole", "Karine", "Virginie",
        ],
        "maiden_names": [
            "Dupuis", "Lemoine", "Carpentier", "Leclerc", "Benoit", "Barbier",
            "Lecomte", "Maréchal", "Aubert", "Rolland", "Vasseur", "Pichon",
            "Renault", "Guillot", "Berger", "Caron", "Dumas", "Fleury",
            "Maillard", "Delorme", "Bouvier", "Cordier", "Ferrand", "Huet",
            "Joubert", "Lamy", "Mallet", "Navarro", "Poirier", "Tanguy",
            "Guyon", "Jacquet", "Prevost", "Roche", "Seguin", "Tessier",
        ],
    },
    "poudlard": {
        # Mode paires fixes : chaque étudiant a un vrai couple (prénom, nom, genre)
        "paired": True,
        "students": [
            # ── Gryffondor ──
            ("Harry", "Potter", "male"),
            ("Ron", "Weasley", "male"),
            ("Hermione", "Granger", "female"),
            ("Neville", "Longbottom", "male"),
            ("Ginny", "Weasley", "female"),
            ("Fred", "Weasley", "male"),
            ("George", "Weasley", "male"),
            ("Dean", "Thomas", "male"),
            ("Seamus", "Finnigan", "male"),
            ("Lavender", "Brown", "female"),
            ("Parvati", "Patil", "female"),
            ("Colin", "Creevey", "male"),
            ("Dennis", "Creevey", "male"),
            ("Lee", "Jordan", "male"),
            ("Katie", "Bell", "female"),
            ("Angelina", "Johnson", "female"),
            ("Alicia", "Spinnet", "female"),
            ("Oliver", "Wood", "male"),
            ("Cormac", "McLaggen", "male"),
            ("Romilda", "Vane", "female"),
            # ── Serpentard ──
            ("Draco", "Malfoy", "male"),
            ("Pansy", "Parkinson", "female"),
            ("Blaise", "Zabini", "male"),
            ("Theodore", "Nott", "male"),
            ("Vincent", "Crabbe", "male"),
            ("Gregory", "Goyle", "male"),
            ("Millicent", "Bulstrode", "female"),
            ("Daphne", "Greengrass", "female"),
            ("Astoria", "Greengrass", "female"),
            ("Tracey", "Davis", "female"),
            ("Marcus", "Flint", "male"),
            ("Adrian", "Pucey", "male"),
            ("Graham", "Montague", "male"),
            ("Terence", "Higgs", "male"),
            # ── Serdaigle ──
            ("Luna", "Lovegood", "female"),
            ("Cho", "Chang", "female"),
            ("Padma", "Patil", "female"),
            ("Marietta", "Edgecombe", "female"),
            ("Michael", "Corner", "male"),
            ("Terry", "Boot", "male"),
            ("Anthony", "Goldstein", "male"),
            ("Roger", "Davies", "male"),
            ("Penelope", "Clearwater", "female"),
            ("Lisa", "Turpin", "female"),
            ("Mandy", "Brocklehurst", "female"),
            # ── Poufsouffle ──
            ("Cedric", "Diggory", "male"),
            ("Susan", "Bones", "female"),
            ("Hannah", "Abbott", "female"),
            ("Ernie", "Macmillan", "male"),
            ("Justin", "Finch-Fletchley", "male"),
            ("Zacharias", "Smith", "male"),
            ("Megan", "Jones", "female"),
            ("Eleanor", "Branstone", "female"),
            ("Leanne", "Selwyn", "female"),
            # ── Nouvelle génération ──
            ("Albus", "Potter", "male"),
            ("James", "Potter", "male"),
            ("Lily", "Potter", "female"),
            ("Rose", "Granger-Weasley", "female"),
            ("Hugo", "Granger-Weasley", "male"),
            ("Scorpius", "Malfoy", "male"),
            ("Teddy", "Lupin", "male"),
            ("Victoire", "Weasley", "female"),
            ("Dominique", "Weasley", "female"),
            ("Louis", "Weasley", "male"),
            ("Molly", "Weasley", "female"),
            ("Lucy", "Weasley", "female"),
            ("Roxanne", "Weasley", "female"),
            ("Lorcan", "Scamander", "male"),
            ("Lysander", "Scamander", "male"),
            # ── Beauxbâtons & Durmstrang ──
            ("Fleur", "Delacour", "female"),
            ("Gabrielle", "Delacour", "female"),
            ("Viktor", "Krum", "male"),
            # ── Élèves secondaires ──
            ("Percy", "Weasley", "male"),
            ("Bill", "Weasley", "male"),
            ("Charlie", "Weasley", "male"),
            ("Nymphadora", "Tonks", "female"),
        ],
        # Fallback pools (si plus d'étudiants que de paires, on recycle)
        "first_names_m": [
            "Harry", "Ron", "Neville", "Draco", "Fred", "George", "Cedric",
            "Seamus", "Dean", "Oliver", "Percy", "Bill", "Charlie", "Lee",
            "Ernie", "Justin", "Colin", "Dennis", "Blaise", "Theodore",
        ],
        "first_names_f": [
            "Hermione", "Ginny", "Luna", "Cho", "Lavender", "Parvati",
            "Padma", "Katie", "Angelina", "Alicia", "Penelope", "Fleur",
            "Pansy", "Daphne", "Susan", "Hannah", "Romilda", "Nymphadora",
        ],
        "last_names": [
            "Potter", "Weasley", "Granger", "Malfoy", "Longbottom", "Lovegood",
            "Diggory", "Finnigan", "Thomas", "Wood", "Bell", "Johnson",
            "Zabini", "Nott", "Parkinson", "Greengrass", "Chang", "Patil",
        ],
        "father_names": [
            "James", "Arthur", "Lucius", "Xenophilius", "Amos", "Frank",
            "Ted", "Vernon", "Bartemius", "Remus", "Sirius", "Albus",
            "Rubeus", "Severus", "Cornelius", "Kingsley", "Rufus",
            "Neville", "Draco", "Harry", "Ron", "George", "Percy", "Bill",
            "Charlie", "Dudley", "Ernie", "Blaise", "Cormac", "Oliver",
            "Viktor", "Filius", "Horace", "Gilderoy", "Mundungus",
            "Aberforth", "Gellert", "Alastor", "Elphias", "Dedalus",
        ],
        "mother_names": [
            "Lily", "Molly", "Narcissa", "Alice", "Petunia", "Andromeda",
            "Nymphadora", "Minerva", "Pomona", "Fleur", "Ginny", "Hermione",
            "Luna", "Angelina", "Audrey", "Helena", "Rowena", "Helga",
            "Bathilda", "Ariana", "Célestina", "Hestia", "Emmeline",
            "Augusta", "Muriel", "Apolline", "Gabrielle", "Olympe",
            "Charity", "Aurora", "Rolanda", "Poppy", "Irma", "Dolores",
            "Amelia", "Millicent", "Pansy", "Astoria", "Daphne", "Rose",
        ],
        "maiden_names": [
            "Evans", "Prewett", "Black", "Fortescue", "Dursley", "Rosier",
            "Crouch", "Shacklebolt", "Marchbanks", "Fudge", "Scrimgeour",
            "Bagman", "Maxime", "Karkaroff", "Delacour", "Krum",
            "Flamel", "Dumbledore", "Gaunt", "Peverell", "Riddle",
            "Ollivander", "Fortescue", "Cattermole", "Grindelwald",
            "Lestrange", "Rowle", "Yaxley", "Dolohov", "Carrow",
            "Amycus", "Travers", "Selwyn", "Avery", "Mulciber", "Rookwood",
        ],
    },
}

# ============================================================================
# Datasets employés (noms par thème)
# ============================================================================

EMPLOYEE_NAME_DATASETS = {
    "standard": {
        "first_names_m": [
            "Philippe", "Jean", "Pierre", "François", "Olivier", "Antoine",
            "Stéphane", "Laurent", "Thomas", "Éric", "Nicolas", "Christophe",
            "David", "Frédéric", "Guillaume", "Julien", "Marc", "Pascal",
            "Sébastien", "Vincent", "Benoît", "Damien", "Maxime", "Romain",
        ],
        "first_names_f": [
            "Marie", "Sophie", "Isabelle", "Catherine", "Nathalie", "Véronique",
            "Aurélie", "Sandrine", "Céline", "Christelle", "Élodie", "Florence",
            "Hélène", "Julie", "Laetitia", "Margaux", "Pascale", "Sylvie",
            "Valérie", "Anne", "Caroline", "Delphine", "Emmanuelle", "Géraldine",
        ],
        "last_names": [
            "Dupont", "Martin", "Bernard", "Leroy", "Moreau", "Petit", "Roux",
            "Fournier", "Girard", "Lambert", "Mercier", "Blanc", "Garnier",
            "Faure", "Robin", "Morel", "Simon", "Lefebvre", "Bonnet", "Duval",
            "Perrin", "Meyer", "Fontaine", "Chevalier", "Renard", "Lucas",
            "Gauthier", "Leclerc", "Barbier", "Rivière", "Colin", "Picard",
        ],
    },
    "poudlard": {
        "paired": True,
        # Employés Poudlard : vrais noms du staff (professeurs, directeurs, admin)
        # Chaque tuple : (prénom, nom, genre, profils suggérés)
        # Les profils sont indicatifs et mappés dans seed_users.py
        "employees": [
            # ── Direction ──
            ("Albus", "Dumbledore", "male", ["directeur"]),
            ("Minerva", "McGonagall", "female", ["resp_pedagogique"]),
            # ── Enseignants principaux ──
            ("Severus", "Rogue", "male", ["enseignant"]),
            ("Rubeus", "Hagrid", "male", ["enseignant"]),
            ("Filius", "Flitwick", "male", ["enseignant"]),
            ("Pomona", "Chourave", "female", ["enseignant"]),
            ("Horace", "Slughorn", "male", ["enseignant"]),
            ("Remus", "Lupin", "male", ["enseignant"]),
            ("Sibylle", "Trelawney", "female", ["enseignant"]),
            ("Aurora", "Sinistra", "female", ["enseignant"]),
            ("Charity", "Burbage", "female", ["enseignant"]),
            ("Bathsheda", "Babbling", "female", ["enseignant"]),
            ("Septima", "Vector", "female", ["enseignant"]),
            ("Cuthbert", "Binns", "male", ["enseignant"]),
            ("Rolanda", "Bibine", "female", ["enseignant"]),
            # ── Administration ──
            ("Argus", "Rusard", "male", ["secretaire"]),
            ("Poppy", "Pomfresh", "female", ["resp_admissions"]),
            ("Irma", "Pince", "female", ["comptable"]),
            ("Alastor", "Maugrey", "male", ["resp_rh"]),
            # ── Multi-profil ──
            ("Nymphadora", "Tonks", "female", ["resp_pedagogique", "enseignant"]),
        ],
        # Fallback pools pour recyclage si n_employees > 20
        "first_names_m": [
            "Albus", "Severus", "Rubeus", "Filius", "Horace", "Remus",
            "Cuthbert", "Argus", "Alastor", "Gilderoy", "Quirinus",
            "Bartemius", "Kingsley", "Arthur", "Cornelius",
        ],
        "first_names_f": [
            "Minerva", "Pomona", "Sibylle", "Aurora", "Charity",
            "Bathsheda", "Septima", "Rolanda", "Poppy", "Irma",
            "Nymphadora", "Dolores", "Olympe", "Amelia",
        ],
        "last_names": [
            "Dumbledore", "McGonagall", "Rogue", "Hagrid", "Flitwick",
            "Chourave", "Slughorn", "Lupin", "Trelawney", "Sinistra",
            "Burbage", "Babbling", "Vector", "Binns", "Bibine",
            "Rusard", "Pomfresh", "Pince", "Maugrey", "Lockhart",
            "Quirrell", "Croupton", "Shacklebolt", "Weasley", "Fudge",
        ],
    },
}

CAMPUS_CITIES = {
    "sciences": [
        {"city": "Gif-sur-Yvette", "postal": "91190", "name_tpl": "Campus {school_short} — Saclay", "center_name": "Pôle Scientifique de Saclay", "center_color": "#1E88E5", "addr": "3 rue Joliot-Curie, Bâtiment Breguet", "zone": "C"},
        {"city": "Lyon", "postal": "69003", "name_tpl": "Campus {school_short} — Lyon", "center_name": "Espace Lyon Part-Dieu", "center_color": "#43A047", "addr": "47 boulevard Vivier Merle", "zone": "A"},
        {"city": "Toulouse", "postal": "31000", "name_tpl": "Campus {school_short} — Toulouse", "center_name": "Centre Capitole Sciences", "center_color": "#039BE5", "addr": "118 route de Narbonne", "zone": "A"},
        {"city": "Strasbourg", "postal": "67000", "name_tpl": "Campus {school_short} — Strasbourg", "center_name": "Pôle Universitaire Esplanade", "center_color": "#00897B", "addr": "4 rue Blaise Pascal", "zone": "B"},
    ],
    "arts": [
        {"city": "Bordeaux", "postal": "33000", "name_tpl": "Campus {school_short} — Bordeaux", "center_name": "Maison des Arts de Bordeaux", "center_color": "#FB8C00", "addr": "12 quai des Chartrons", "zone": "A"},
        {"city": "Marseille", "postal": "13002", "name_tpl": "Campus {school_short} — Marseille", "center_name": "Campus Méditerranée", "center_color": "#E53935", "addr": "58 quai du Port", "zone": "B"},
        {"city": "Paris", "postal": "75006", "name_tpl": "Campus {school_short} — Paris", "center_name": "Espace Beaux-Arts Rive Gauche", "center_color": "#8E24AA", "addr": "14 rue Bonaparte", "zone": "C"},
        {"city": "Nantes", "postal": "44000", "name_tpl": "Campus {school_short} — Nantes", "center_name": "Atelier Île de Nantes", "center_color": "#F4511E", "addr": "42 boulevard de la Prairie au Duc", "zone": "A"},
    ],
    "droit": [
        {"city": "Paris", "postal": "75005", "name_tpl": "Campus {school_short} — Paris", "center_name": "Centre Panthéon Droit", "center_color": "#5E35B1", "addr": "12 place du Panthéon", "zone": "C"},
        {"city": "Montpellier", "postal": "34000", "name_tpl": "Campus {school_short} — Montpellier", "center_name": "Faculté de Droit Montpellier", "center_color": "#00ACC1", "addr": "39 rue de l'Université", "zone": "A"},
        {"city": "Lille", "postal": "59000", "name_tpl": "Campus {school_short} — Lille", "center_name": "Pôle Juridique Vauban", "center_color": "#7CB342", "addr": "1 place Déliot", "zone": "B"},
    ],
    "sante": [
        {"city": "Paris", "postal": "75013", "name_tpl": "Campus {school_short} — Paris", "center_name": "Centre Pitié-Santé", "center_color": "#D81B60", "addr": "47 boulevard de l'Hôpital", "zone": "C"},
        {"city": "Rennes", "postal": "35000", "name_tpl": "Campus {school_short} — Rennes", "center_name": "Pôle Santé Villejean", "center_color": "#00897B", "addr": "2 avenue du Professeur Léon Bernard", "zone": "B"},
        {"city": "Marseille", "postal": "13005", "name_tpl": "Campus {school_short} — Marseille", "center_name": "Faculté de Médecine La Timone", "center_color": "#1E88E5", "addr": "27 boulevard Jean Moulin", "zone": "B"},
    ],
    "ingenierie": [
        {"city": "Gif-sur-Yvette", "postal": "91190", "name_tpl": "Campus {school_short} — Saclay", "center_name": "École d'Ingénieurs Saclay", "center_color": "#546E7A", "addr": "8 avenue de la Vauve", "zone": "C"},
        {"city": "Grenoble", "postal": "38400", "name_tpl": "Campus {school_short} — Grenoble", "center_name": "Centre INP Grenoble", "center_color": "#00838F", "addr": "46 avenue Félix Viallet", "zone": "A"},
        {"city": "Nantes", "postal": "44300", "name_tpl": "Campus {school_short} — Nantes", "center_name": "Campus Chantrerie", "center_color": "#6D4C41", "addr": "4 rue Alfred Kastler", "zone": "A"},
    ],
    "poudlard": [
        {"city": "Pré-au-Lard", "postal": "00001", "name_tpl": "Campus {school_short} — Pré-au-Lard", "center_name": "Château de Poudlard", "center_color": "#7B1FA2", "addr": "1 chemin de la Forêt Interdite", "zone": "C"},
        {"city": "Londres", "postal": "WC2H", "name_tpl": "Campus {school_short} — Londres", "center_name": "Chemin de Traverse", "center_color": "#C62828", "addr": "Voie 9¾, King's Cross Station", "zone": "A"},
        {"city": "Godric's Hollow", "postal": "00002", "name_tpl": "Campus {school_short} — Godric's Hollow", "center_name": "Centre Godric Gryffondor", "center_color": "#F9A825", "addr": "12 Church Lane", "zone": "B"},
    ],
}

ROOM_POOLS = {
    "sciences": [
        ("Amphithéâtre {name}", 120), ("Salle de TD — {name}", 35), ("Salle de TD — {name2}", 35),
        ("Laboratoire Informatique", 24), ("Salle de réunion {name3}", 12),
    ],
    "arts": [
        ("Atelier Peinture & Sculpture", 25), ("Studio Photographie", 15),
        ("Salle de conférence {name}", 60), ("Bibliothèque", 40), ("Espace Exposition", 50),
    ],
    "droit": [
        ("Amphithéâtre {name}", 100), ("Salle de cours {name}", 40),
        ("Salle de TD — {name2}", 30), ("Bibliothèque juridique", 35),
    ],
    "sante": [
        ("Amphithéâtre {name}", 150), ("Salle de TP Anatomie", 30),
        ("Laboratoire de simulation", 20), ("Salle de cours {name}", 40),
    ],
    "ingenierie": [
        ("Amphithéâtre {name}", 100), ("Salle de TD — {name}", 35),
        ("Laboratoire {name2}", 24), ("Atelier Prototypage", 20), ("Salle de réunion", 12),
    ],
    "poudlard": [
        ("Grande Salle — Aile {name}", 120), ("Salle de cours — Tour {name2}", 35),
        ("Cachots — Salle {name3}", 28), ("Salle sur Demande — Config. {name4}", 45),
        ("Serre n°{name5}", 18), ("Terrain de Quidditch — Tribune {name}", 80),
        ("Bibliothèque — Section {name6}", 22), ("Tour d'Astronomie — Étage {name7}", 15),
    ],
}

ROOM_FAMOUS_NAMES = {
    "sciences": {
        "name": ["Curie", "Newton", "Einstein", "Fermi", "Bohr", "Planck", "Faraday", "Maxwell"],
        "name2": ["Euler", "Gauss", "Fourier", "Lagrange", "Laplace", "Cauchy", "Poincaré"],
        "name3": ["Pasteur", "Lavoisier", "Galois", "Descartes"],
    },
    "arts": {
        "name": ["Montaigne", "Voltaire", "Hugo", "Camus", "Malraux", "Rodin", "Monet"],
    },
    "droit": {
        "name": ["Portalis", "Cambacérès", "Carbonnier", "Hauriou", "Duguit", "Jèze"],
        "name2": ["Capitant", "Josserand", "Ripert", "Planiol"],
    },
    "sante": {
        "name": ["Laennec", "Charcot", "Bichat", "Broussais", "Trousseau", "Broca"],
    },
    "ingenierie": {
        "name": ["Eiffel", "Dassault", "Fréyssinet", "Caquot", "Hennebique"],
        "name2": ["Becquerel", "Bréguet", "Carnot", "Ampère"],
    },
    "poudlard": {
        "name": ["Gryffondor", "Serdaigle", "Poufsouffle", "Serpentard", "des Quatre Maisons", "des Fondateurs"],
        "name2": ["Gryffondor", "Serpentard", "Serdaigle", "Poufsouffle", "des Préfets", "du 7ᵉ étage"],
        "name3": ["Rogue", "Slughorn", "Ombrage", "Lockhart", "Chourave", "Flitwick", "Trelawney", "Binns"],
        "name4": ["Défense", "Potions", "Sortilèges", "Métamorphose", "Botanique", "Divination", "Duels", "Enchantements"],
        "name5": ["3", "7", "12", "5", "9", "2", "1", "4"],
        "name6": ["Interdite", "Enchantements", "Potions rares", "Créatures magiques", "Runes anciennes", "Sortilèges avancés"],
        "name7": ["supérieur", "inférieur", "central", "nord", "sud", "observatoire"],
    },
}

CENTER_HOURS_TEMPLATES = {
    "standard": {  # lun-ven 8h-19h30
        "0": {"open": 28800, "close": 70200}, "1": {"open": 28800, "close": 70200},
        "2": {"open": 28800, "close": 70200}, "3": {"open": 28800, "close": 70200},
        "4": {"open": 28800, "close": 70200},
    },
    "etendu": {  # lun-ven 7h30-20h, sam 8h-13h
        "0": {"open": 27000, "close": 72000}, "1": {"open": 27000, "close": 72000},
        "2": {"open": 27000, "close": 72000}, "3": {"open": 27000, "close": 72000},
        "4": {"open": 27000, "close": 72000}, "5": {"open": 28800, "close": 46800},
    },
    "soiree": {  # lun-ven 9h-21h, sam 10h-18h
        "0": {"open": 32400, "close": 75600}, "1": {"open": 32400, "close": 75600},
        "2": {"open": 32400, "close": 75600}, "3": {"open": 32400, "close": 75600},
        "4": {"open": 32400, "close": 75600}, "5": {"open": 36000, "close": 64800},
    },
    "matin_etendu": {  # lun-ven 8h30-20h30, sam 9h-17h
        "0": {"open": 30600, "close": 73800}, "1": {"open": 30600, "close": 73800},
        "2": {"open": 30600, "close": 73800}, "3": {"open": 30600, "close": 73800},
        "4": {"open": 30600, "close": 73800}, "5": {"open": 32400, "close": 61200},
    },
}

HOURS_ROTATION = ["etendu", "standard", "soiree", "matin_etendu"]

# ============================================================================
# Calendriers de contraintes — Vacances scolaires dynamiques par zone
# ============================================================================

from datetime import date as _date, timedelta as _timedelta


def _easter(year):
    """Calcul de la date de Pâques (algorithme de Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return _date(year, month, day)


def _fmt(d):
    """Format date → ISO string."""
    return d.isoformat()


def generate_jours_feries(year_start, year_end):
    """Génère les jours fériés pour une année scolaire (sept year_start → juin year_end)."""
    easter = _easter(year_end)
    return [
        {"name": "Toussaint",        "start_date": f"{year_start}-11-01", "end_date": f"{year_start}-11-01"},
        {"name": "Armistice",        "start_date": f"{year_start}-11-11", "end_date": f"{year_start}-11-11"},
        {"name": "Noël",             "start_date": f"{year_start}-12-25", "end_date": f"{year_start}-12-25"},
        {"name": "Jour de l'an",     "start_date": f"{year_end}-01-01",   "end_date": f"{year_end}-01-01"},
        {"name": "Lundi de Pâques",  "start_date": _fmt(easter + _timedelta(days=1)), "end_date": _fmt(easter + _timedelta(days=1))},
        {"name": "Fête du travail",  "start_date": f"{year_end}-05-01",   "end_date": f"{year_end}-05-01"},
        {"name": "Victoire 1945",    "start_date": f"{year_end}-05-08",   "end_date": f"{year_end}-05-08"},
        {"name": "Ascension",        "start_date": _fmt(easter + _timedelta(days=39)), "end_date": _fmt(easter + _timedelta(days=39))},
    ]


def generate_vacances_scolaires(year_start, year_end):
    """
    Génère les vacances scolaires par zone pour une année scolaire.
    Les dates sont approximatives et basées sur le calendrier français typique.
    """
    easter = _easter(year_end)
    ascension = easter + _timedelta(days=39)

    # Toussaint : 3e samedi d'octobre → +16 jours (toutes zones identiques)
    toussaint_start = _date(year_start, 10, 18)
    # Ajuster au samedi le plus proche du 18 oct
    toussaint_start += _timedelta(days=(5 - toussaint_start.weekday()) % 7)
    toussaint_end = toussaint_start + _timedelta(days=16)

    # Noël : ~20 déc → ~5 jan (toutes zones identiques)
    noel_start = _date(year_start, 12, 20)
    noel_start += _timedelta(days=(5 - noel_start.weekday()) % 7)
    noel_end = noel_start + _timedelta(days=16)

    # Hiver : zones décalées (A=sem 6, B=sem 8, C=sem 7 environ)
    # Base : 1er samedi de février + offset par zone
    feb1 = _date(year_end, 2, 1)
    feb_first_sat = feb1 + _timedelta(days=(5 - feb1.weekday()) % 7)
    hiver_a_start = feb_first_sat + _timedelta(days=7)   # ~2e samedi fév
    hiver_b_start = feb_first_sat + _timedelta(days=21)  # ~4e samedi fév
    hiver_c_start = feb_first_sat + _timedelta(days=14)  # ~3e samedi fév

    # Printemps : ~2 semaines autour de Pâques, décalé par zone
    printemps_a_start = easter - _timedelta(days=2)
    printemps_a_start += _timedelta(days=(5 - printemps_a_start.weekday()) % 7)
    printemps_b_start = printemps_a_start + _timedelta(days=14)
    printemps_c_start = printemps_a_start + _timedelta(days=7)

    # Pont de l'Ascension
    ascension_start = ascension
    ascension_end = ascension + _timedelta(days=4)

    def _vac_list(hiver_start, printemps_start):
        return [
            {"name": "Vacances de la Toussaint",  "start_date": _fmt(toussaint_start), "end_date": _fmt(toussaint_end)},
            {"name": "Vacances de Noël",           "start_date": _fmt(noel_start),      "end_date": _fmt(noel_end)},
            {"name": "Vacances d'hiver",           "start_date": _fmt(hiver_start),     "end_date": _fmt(hiver_start + _timedelta(days=16))},
            {"name": "Vacances de printemps",      "start_date": _fmt(printemps_start),  "end_date": _fmt(printemps_start + _timedelta(days=16))},
            {"name": "Pont de l'Ascension",        "start_date": _fmt(ascension_start),  "end_date": _fmt(ascension_end)},
        ]

    return {
        "A": _vac_list(hiver_a_start, printemps_a_start),
        "B": _vac_list(hiver_b_start, printemps_b_start),
        "C": _vac_list(hiver_c_start, printemps_c_start),
    }


# Compatibilité ascendante : constantes pour 2025-2026 (utilisées si pas de year_from/year_to)
JOURS_FERIES_2025_2026 = generate_jours_feries(2025, 2026)
VACANCES_SCOLAIRES_2025_2026 = generate_vacances_scolaires(2025, 2026)


def get_calendar_constraints(zone, year_start=None, year_end=None):
    """Retourne la liste complète de contraintes (vacances + fériés) pour une zone donnée."""
    if year_start and year_end:
        jours_feries = generate_jours_feries(year_start, year_end)
        vacances = generate_vacances_scolaires(year_start, year_end)
    else:
        jours_feries = JOURS_FERIES_2025_2026
        vacances = VACANCES_SCOLAIRES_2025_2026

    constraints = []
    # Vacances scolaires
    for vac in vacances.get(zone, vacances["C"]):
        constraints.append({
            "name": vac["name"],
            "type": "holiday",
            "start_date": vac["start_date"],
            "end_date": vac["end_date"],
        })
    # Jours fériés
    for jf in jours_feries:
        constraints.append({
            "name": jf["name"],
            "type": "holiday",
            "start_date": jf["start_date"],
            "end_date": jf["end_date"],
        })
    return constraints


SCHOOL_TEMPLATES = {
    "sciences": {"name": "Sciences & Technologies", "short": "S&T"},
    "arts": {"name": "Arts & Lettres", "short": "A&L"},
    "droit": {"name": "Droit & Sciences Politiques", "short": "D&SP"},
    "sante": {"name": "Santé & Médecine", "short": "S&M"},
    "ingenierie": {"name": "Ingénierie & Innovation", "short": "I&I"},
    "poudlard": {"name": "Poudlard — École de Sorcellerie", "short": "Pdlrd"},
}

COMPANY_TEMPLATES = {
    "sciences": {"name": "SAS ÉduSciences", "short": "ÉduSci"},
    "arts": {"name": "SARL ArtsCréa", "short": "ArtCr"},
    "droit": {"name": "SAS JuriFormation", "short": "JuriF"},
    "sante": {"name": "SAS MédÉtudes", "short": "MédÉ"},
    "ingenierie": {"name": "SAS IngéForma", "short": "IngéF"},
    "poudlard": {"name": "SAS Poudlard Éducation Magique", "short": "PdlrdEM"},
}

# ============================================================================
# Thèmes — Teaching Units
# ============================================================================

THEME_DEFINITIONS = {
    "sciences_generales": {
        "ues": [
            {"name": "Mathématiques", "sub_ues": [
                {"name": "Analyse", "weight": 3, "courses": ["Analyse réelle", "Analyse complexe", "Suites et séries numériques", "Intégrales multiples", "Équations différentielles ordinaires", "Analyse numérique", "TD Analyse", "TP Analyse numérique"]},
                {"name": "Algèbre", "weight": 2.5, "courses": ["Algèbre linéaire", "Algèbre bilinéaire", "Groupes et anneaux", "Espaces vectoriels normés", "Réduction des endomorphismes", "TD Algèbre", "TP Calcul formel"]},
                {"name": "Probabilités et Statistiques", "weight": 2, "courses": ["Probabilités discrètes", "Probabilités continues", "Variables aléatoires", "Statistiques descriptives", "Tests d'hypothèses", "TD Probabilités", "TP Statistiques R"]},
            ]},
            {"name": "Physique", "sub_ues": [
                {"name": "Mécanique", "weight": 2.5, "courses": ["Cinématique du point", "Dynamique du point", "Énergie et travail", "Mécanique du solide", "Oscillations et ondes", "TD Mécanique", "TP Mécanique"]},
                {"name": "Électromagnétisme", "weight": 2, "courses": ["Électrostatique", "Magnétostatique", "Ondes électromagnétiques", "Circuits électriques", "Électronique analogique", "TD Électromagnétisme", "TP Électronique"]},
                {"name": "Thermodynamique et Optique", "weight": 2, "courses": ["Premier principe", "Second principe", "Transferts thermiques", "Optique géométrique", "Optique ondulatoire", "TD Thermodynamique", "TP Optique"]},
            ]},
            {"name": "Informatique", "sub_ues": [
                {"name": "Algorithmique et Programmation", "weight": 2.5, "courses": ["Algorithmique fondamentale", "Programmation Python", "Programmation C", "Structures de données", "Complexité algorithmique", "TP Python avancé", "Projet programmation"]},
                {"name": "Systèmes et Réseaux", "weight": 2, "courses": ["Architecture des ordinateurs", "Systèmes d'exploitation Unix", "Réseaux et protocoles TCP/IP", "Sécurité informatique", "TP Systèmes", "TP Réseaux"]},
                {"name": "Bases de données et Web", "weight": 2, "courses": ["Modèle relationnel", "SQL et requêtes avancées", "NoSQL et Big Data", "Développement web front-end", "Développement web back-end", "TP SQL", "Projet web"]},
            ]},
            {"name": "Transversales", "sub_ues": [
                {"name": "Langues et Communication", "weight": 1.5, "courses": ["Anglais scientifique S1", "Anglais scientifique S2", "Communication écrite", "Communication orale", "Rédaction technique"]},
                {"name": "Projets et Professionnalisation", "weight": 2, "courses": ["Projet tutoré S1", "Projet tutoré S2", "Gestion de projet", "Méthodologie scientifique", "Insertion professionnelle", "Éthique scientifique"]},
            ]},
        ],
    },
    "sciences_prepa": {
        "ues": [
            {"name": "Mathématiques fondamentales", "sub_ues": [
                {"name": "Calcul et Analyse", "weight": 3, "courses": ["Calcul différentiel", "Suites numériques", "Intégration", "Développements limités", "TD Calcul"]},
                {"name": "Géométrie", "weight": 2, "courses": ["Géométrie euclidienne", "Géométrie affine", "Nombres complexes et géométrie", "TD Géométrie"]},
            ]},
            {"name": "Physique fondamentale", "sub_ues": [
                {"name": "Mécanique", "weight": 2.5, "courses": ["Mécanique du point", "Cinématique", "Énergie et travail", "TP Mécanique", "TD Mécanique"]},
                {"name": "Optique", "weight": 2, "courses": ["Optique géométrique", "Lentilles et miroirs", "Optique ondulatoire", "TP Optique"]},
            ]},
            {"name": "Chimie", "sub_ues": [
                {"name": "Chimie générale", "weight": 2.5, "courses": ["Atomistique", "Liaisons chimiques", "Thermochimie", "Cinétique chimique"]},
                {"name": "Travaux pratiques", "weight": 2, "courses": ["TP Chimie organique", "TP Chimie analytique", "TP Dosages", "TP Synthèse"]},
            ]},
            {"name": "Méthodologie", "sub_ues": [
                {"name": "Compétences transversales", "weight": 1.5, "courses": ["Méthodologie scientifique", "Expression écrite", "Expression orale", "Anglais"]},
            ]},
        ],
    },
    "sciences_stage": {
        "ues": [
            {"name": "Méthodologie de recherche", "sub_ues": [
                {"name": "Rédaction scientifique", "weight": 2, "courses": ["Rédaction d'articles", "Bibliographie et sources", "Normes de publication", "Atelier d'écriture scientifique"]},
                {"name": "Éthique et intégrité", "weight": 1.5, "courses": ["Éthique de la recherche", "Intégrité scientifique", "Propriété intellectuelle"]},
            ]},
            {"name": "Travail en laboratoire", "sub_ues": [
                {"name": "Protocoles expérimentaux", "weight": 2.5, "courses": ["Conception de protocoles", "Sécurité au laboratoire", "Techniques de mesure", "Instrumentation avancée", "Métrologie"]},
                {"name": "Analyse et restitution", "weight": 3, "courses": ["Analyse de données expérimentales", "Statistiques appliquées", "Logiciels d'analyse", "Présentation de résultats", "Rapport de stage", "Soutenance de stage"]},
            ]},
        ],
    },
    "arts_theorie": {
        "ues": [
            {"name": "Histoire de l'art ancien", "sub_ues": [
                {"name": "Antiquité", "weight": 2, "courses": ["Art égyptien", "Art grec", "Art romain", "Archéologie et patrimoine", "TD Antiquité"]},
                {"name": "Moyen Âge et Renaissance", "weight": 2.5, "courses": ["Art roman", "Art gothique", "Renaissance italienne", "Renaissance nordique", "Maniérisme", "TD Renaissance"]},
                {"name": "Baroque et Classicisme", "weight": 2, "courses": ["Art baroque", "Classicisme français", "Peinture hollandaise du Siècle d'or", "Architecture baroque", "TD Baroque"]},
            ]},
            {"name": "Histoire de l'art moderne", "sub_ues": [
                {"name": "XIXe siècle", "weight": 2.5, "courses": ["Néoclassicisme", "Romantisme", "Réalisme", "Impressionnisme", "Post-impressionnisme", "Art nouveau", "TD XIXe siècle"]},
                {"name": "XXe siècle et contemporain", "weight": 3, "courses": ["Fauvisme", "Cubisme", "Dadaïsme", "Surréalisme", "Expressionnisme abstrait", "Pop Art", "Art conceptuel", "TD XXe siècle"]},
            ]},
            {"name": "Esthétique et philosophie", "sub_ues": [
                {"name": "Esthétique", "weight": 2, "courses": ["Esthétique antique", "Esthétique moderne", "Esthétique contemporaine", "Philosophie de l'art", "TD Esthétique"]},
                {"name": "Sémiologie", "weight": 1.5, "courses": ["Sémiologie de l'image", "Analyse iconographique", "Sémiotique de l'art contemporain", "TD Sémiologie"]},
            ]},
            {"name": "Méthodologie et Langues", "sub_ues": [
                {"name": "Analyse d'œuvres", "weight": 2.5, "courses": ["Analyse de peinture", "Analyse de sculpture", "Analyse d'architecture", "Commentaire d'œuvre", "Dissertation", "TD Analyse"]},
                {"name": "Recherche et Langues", "weight": 1.5, "courses": ["Recherche documentaire", "Méthodologie universitaire", "Anglais de spécialité", "Rédaction académique"]},
            ]},
        ],
    },
    "arts_pratique": {
        "ues": [
            {"name": "Dessin", "sub_ues": [
                {"name": "Observation et Technique", "weight": 2.5, "courses": ["Dessin d'observation", "Dessin de modèle vivant", "Croquis rapide", "Dessin au fusain", "Dessin à l'encre"]},
                {"name": "Perspectives et Volumes", "weight": 2, "courses": ["Perspective linéaire", "Dessin de volumes", "Dessin d'architecture", "Projet dessin"]},
            ]},
            {"name": "Peinture et couleur", "sub_ues": [
                {"name": "Techniques picturales", "weight": 2.5, "courses": ["Peinture acrylique", "Peinture à l'huile", "Aquarelle", "Techniques mixtes", "Atelier peinture grand format"]},
                {"name": "Théorie de la couleur", "weight": 1.5, "courses": ["Colorimétrie", "Harmonie des couleurs", "Couleur et lumière"]},
            ]},
            {"name": "Sculpture et volume", "sub_ues": [
                {"name": "Modelage et Moulage", "weight": 2, "courses": ["Modelage argile", "Moulage plâtre", "Taille directe", "Assemblage", "Atelier modelage libre"]},
                {"name": "Installation et Espace", "weight": 1.5, "courses": ["Installation in situ", "Art et espace public", "Scénographie", "Projet installation"]},
            ]},
            {"name": "Arts numériques", "sub_ues": [
                {"name": "Photographie", "weight": 2, "courses": ["Photographie numérique", "Retouche photo", "Studio photo", "Reportage photographique"]},
                {"name": "Création numérique", "weight": 2.5, "courses": ["PAO — Mise en page", "Illustration vectorielle", "Vidéo et montage", "Animation 2D", "Création 3D", "Projet numérique"]},
            ]},
        ],
    },
    "arts_master": {
        "ues": [
            {"name": "Théories de la création", "sub_ues": [
                {"name": "Art et Société", "weight": 2, "courses": ["Art et société contemporaine", "Sociologie de l'art", "Art et politique", "Conférences invités", "TD Art et société"]},
                {"name": "Théories critiques", "weight": 2, "courses": ["Théories critiques contemporaines", "Post-modernisme", "Études postcoloniales", "Gender studies et art", "TD Théories critiques"]},
                {"name": "Études culturelles", "weight": 1.5, "courses": ["Cultural studies", "Industries culturelles", "Art et numérique", "TD Études culturelles"]},
            ]},
            {"name": "Pratique artistique avancée", "sub_ues": [
                {"name": "Création personnelle", "weight": 3, "courses": ["Atelier de création S1", "Atelier de création S2", "Jury de création intermédiaire", "Jury de création final", "Portfolio artistique", "Accrochage personnel"]},
                {"name": "Expérimentation", "weight": 2.5, "courses": ["Expérimentation pluridisciplinaire", "Nouvelles technologies et art", "Performance et art vivant", "Art sonore", "Art vidéo avancé"]},
            ]},
            {"name": "Recherche et mémoire", "sub_ues": [
                {"name": "Méthodologie", "weight": 1.5, "courses": ["Méthodologie de recherche en art", "Recherche-création", "Veille artistique"]},
                {"name": "Mémoire", "weight": 2, "courses": ["Séminaire de mémoire S1", "Séminaire de mémoire S2", "Rédaction du mémoire", "Soutenance du mémoire"]},
            ]},
            {"name": "Professionnalisation", "sub_ues": [
                {"name": "Droit et Gestion", "weight": 2, "courses": ["Droit de l'art", "Propriété intellectuelle", "Gestion de projet artistique", "Économie de l'art", "Financement et mécénat"]},
                {"name": "Langues et réseau", "weight": 2, "courses": ["Anglais professionnel S1", "Anglais professionnel S2", "Réseaux professionnels", "Préparation exposition", "Stage en institution culturelle"]},
            ]},
        ],
    },
    "arts_workshop": {
        "ues": [
            {"name": "Création collaborative", "sub_ues": [
                {"name": "Projet collectif", "weight": 3, "courses": ["Brief et conception du projet", "Recherche et inspiration", "Production collective jour 1", "Production collective jour 2", "Production collective jour 3", "Finalisation du projet"]},
                {"name": "Co-création interdisciplinaire", "weight": 1.5, "courses": ["Co-création interdisciplinaire", "Atelier interculturel", "Dialogue artistique", "Critique collective"]},
            ]},
            {"name": "Exposition et diffusion", "sub_ues": [
                {"name": "Commissariat d'exposition", "weight": 2, "courses": ["Commissariat d'exposition", "Scénographie d'exposition", "Accrochage et mise en espace", "Catalogue et documentation"]},
                {"name": "Communication et médiation", "weight": 1.5, "courses": ["Communication culturelle", "Médiation des publics", "Relations presse culturelle", "Vernissage collectif"]},
            ]},
        ],
    },
    # ── Droit themes ──
    "droit_general": {
        "ues": [
            {"name": "Droit civil", "sub_ues": [
                {"name": "Droit des personnes", "weight": 2.5, "courses": ["Cours Droit des personnes", "Cours Droit de la famille", "Cours Régimes matrimoniaux", "Cours Droit des successions", "TD Droit des personnes", "TD Cas pratiques famille"]},
                {"name": "Droit des obligations", "weight": 3, "courses": ["Cours Droit des contrats", "Cours Responsabilité civile", "Cours Régime général des obligations", "Cours Droit des sûretés", "Cours Quasi-contrats", "TD Contrats", "TD Responsabilité"]},
                {"name": "Droit des biens", "weight": 2, "courses": ["Cours Droit de la propriété", "Cours Droit immobilier", "Cours Copropriété", "TD Droit des biens"]},
            ]},
            {"name": "Droit public", "sub_ues": [
                {"name": "Droit constitutionnel", "weight": 2.5, "courses": ["Cours Institutions de la Ve République", "Cours Contrôle de constitutionnalité", "Cours Libertés fondamentales", "Cours Droit constitutionnel comparé", "TD Droit constitutionnel"]},
                {"name": "Droit administratif", "weight": 2.5, "courses": ["Cours Organisation administrative", "Cours Actes administratifs", "Cours Responsabilité administrative", "Cours Contentieux administratif", "Cours Service public", "TD Droit administratif"]},
                {"name": "Finances publiques", "weight": 2, "courses": ["Cours Budget de l'État", "Cours Fiscalité", "Cours Comptabilité publique", "TD Finances publiques"]},
            ]},
            {"name": "Droit pénal", "sub_ues": [
                {"name": "Droit pénal général", "weight": 2.5, "courses": ["Cours Infraction et responsabilité pénale", "Cours Classifications des infractions", "Cours Peines et sanctions", "Cours Causes d'irresponsabilité", "TD Droit pénal"]},
                {"name": "Procédure pénale", "weight": 2, "courses": ["Cours Enquête de police", "Cours Instruction", "Cours Jugement et voies de recours", "Cours Droits de la défense", "TD Procédure pénale"]},
            ]},
            {"name": "Transversales juridiques", "sub_ues": [
                {"name": "Méthodologie juridique", "weight": 2, "courses": ["Cours Méthodologie du cas pratique", "Cours Dissertation juridique", "Cours Commentaire d'arrêt", "Cours Recherche documentaire juridique", "TD Méthodologie"]},
                {"name": "Langues et culture", "weight": 1.5, "courses": ["Anglais juridique S1", "Anglais juridique S2", "Histoire du droit", "Institutions européennes", "Économie politique"]},
            ]},
        ],
    },
    "droit_prepa": {
        "ues": [
            {"name": "Fondamentaux du droit", "sub_ues": [
                {"name": "Introduction au droit", "weight": 2.5, "courses": ["Cours Introduction générale au droit", "Cours Sources du droit", "Cours Organisation judiciaire", "Cours Vocabulaire juridique", "TD Introduction au droit"]},
                {"name": "Droit civil élémentaire", "weight": 2, "courses": ["Cours Droit des personnes (initiation)", "Cours Droit de la famille (initiation)", "Cours Contrats (initiation)", "TD Droit civil"]},
            ]},
            {"name": "Sciences politiques", "sub_ues": [
                {"name": "Institutions", "weight": 2, "courses": ["Cours Institutions politiques françaises", "Cours Institutions européennes", "Cours Relations internationales", "TD Sciences politiques"]},
                {"name": "Méthodologie", "weight": 1.5, "courses": ["Cours Expression écrite juridique", "Cours Expression orale", "Cours Culture générale juridique", "Anglais juridique"]},
            ]},
        ],
    },
    "droit_master": {
        "ues": [
            {"name": "Droit des affaires", "sub_ues": [
                {"name": "Droit commercial", "weight": 3, "courses": ["Cours Droit des sociétés", "Cours Droit de la concurrence", "Cours Droit de la distribution", "Cours Propriété intellectuelle", "Cours Droit bancaire et financier", "TD Droit des sociétés", "TD Cas pratiques affaires"]},
                {"name": "Droit fiscal", "weight": 2.5, "courses": ["Cours Fiscalité des entreprises", "Cours Fiscalité internationale", "Cours TVA et impôts indirects", "Cours Optimisation fiscale", "TD Fiscalité"]},
            ]},
            {"name": "Droit international", "sub_ues": [
                {"name": "Droit international privé", "weight": 2.5, "courses": ["Cours Conflits de lois", "Cours Conflits de juridictions", "Cours Droit du commerce international", "Cours Arbitrage international", "TD DIP"]},
                {"name": "Droit européen", "weight": 2, "courses": ["Cours Droit de l'UE", "Cours Marché intérieur", "Cours CEDH et droits fondamentaux", "TD Droit européen"]},
            ]},
            {"name": "Recherche et mémoire", "sub_ues": [
                {"name": "Séminaire de recherche", "weight": 2, "courses": ["Séminaire méthodologie de recherche", "Séminaire de mémoire S1", "Séminaire de mémoire S2", "Soutenance du mémoire"]},
                {"name": "Professionnalisation", "weight": 2, "courses": ["Cours Déontologie et éthique", "Cours Techniques de plaidoirie", "Cours Rédaction d'actes", "Anglais juridique avancé", "Stage en cabinet"]},
            ]},
        ],
    },
    "droit_stage": {
        "ues": [
            {"name": "Stage juridique", "sub_ues": [
                {"name": "Préparation au stage", "weight": 2, "courses": ["Cours Rédaction de CV juridique", "Cours Entretien professionnel", "Cours Déontologie du stagiaire", "Cours Cadre légal du stage"]},
                {"name": "Pratique professionnelle", "weight": 3, "courses": ["Stage Cabinet d'avocats", "Stage Juridiction", "Stage Entreprise (service juridique)", "Rapport de stage", "Analyse de jurisprudence", "Soutenance devant le jury"]},
            ]},
        ],
    },
    # ── Santé themes ──
    "sante_general": {
        "ues": [
            {"name": "Sciences fondamentales", "sub_ues": [
                {"name": "Biologie cellulaire et moléculaire", "weight": 3, "courses": ["Cours Biologie cellulaire", "Cours Biologie moléculaire", "Cours Génétique", "Cours Biochimie structurale", "Cours Biochimie métabolique", "TD Biologie", "TP Biologie cellulaire"]},
                {"name": "Anatomie et Physiologie", "weight": 3, "courses": ["Cours Anatomie générale", "Cours Anatomie des membres", "Cours Anatomie du tronc", "Cours Neuroanatomie", "Cours Physiologie des systèmes", "TD Anatomie", "TP Dissection"]},
                {"name": "Chimie et Physique médicale", "weight": 2, "courses": ["Cours Chimie organique médicale", "Cours Chimie analytique", "Cours Biophysique", "Cours Radiobiologie", "TD Chimie médicale"]},
            ]},
            {"name": "Sciences cliniques", "sub_ues": [
                {"name": "Sémiologie médicale", "weight": 2.5, "courses": ["Cours Sémiologie générale", "Cours Sémiologie cardiologique", "Cours Sémiologie pneumologique", "Cours Sémiologie digestive", "Cours Sémiologie neurologique", "TD Sémiologie", "TP Examen clinique"]},
                {"name": "Pharmacologie", "weight": 2.5, "courses": ["Cours Pharmacologie générale", "Cours Pharmacocinétique", "Cours Pharmacodynamie", "Cours Thérapeutique médicamenteuse", "Cours Toxicologie", "TD Pharmacologie"]},
            ]},
            {"name": "Santé publique", "sub_ues": [
                {"name": "Épidémiologie", "weight": 2, "courses": ["Cours Épidémiologie descriptive", "Cours Épidémiologie analytique", "Cours Biostatistiques", "Cours Méthodologie des essais cliniques", "TD Biostatistiques"]},
                {"name": "Santé publique et éthique", "weight": 1.5, "courses": ["Cours Organisation du système de santé", "Cours Éthique médicale", "Cours Droit de la santé", "Cours Économie de la santé"]},
            ]},
            {"name": "Transversales médicales", "sub_ues": [
                {"name": "Langues et Communication", "weight": 1.5, "courses": ["Anglais médical S1", "Anglais médical S2", "Communication patient-soignant", "Rédaction scientifique médicale"]},
                {"name": "Formation pratique", "weight": 2, "courses": ["Stage d'observation hospitalier", "Gestes de premiers secours", "Simulation clinique", "Annonce diagnostique (jeux de rôle)"]},
            ]},
        ],
    },
    "sante_prepa": {
        "ues": [
            {"name": "Sciences fondamentales PASS", "sub_ues": [
                {"name": "Biologie et Biochimie", "weight": 3, "courses": ["Cours Biologie cellulaire PASS", "Cours Biochimie PASS", "Cours Histologie", "Cours Embryologie", "TD Biologie PASS"]},
                {"name": "Physique et Chimie", "weight": 2.5, "courses": ["Cours Biophysique PASS", "Cours Chimie générale PASS", "Cours Chimie organique PASS", "TD Physique-Chimie PASS"]},
            ]},
            {"name": "Sciences humaines et sociales", "sub_ues": [
                {"name": "SHS Santé", "weight": 2, "courses": ["Cours Psychologie médicale", "Cours Sociologie de la santé", "Cours Histoire de la médecine", "Cours Éthique fondamentale"]},
                {"name": "Méthodologie", "weight": 1.5, "courses": ["Cours Méthodologie QCM", "Cours Expression écrite", "Cours Anglais médical", "Entraînement concours"]},
            ]},
        ],
    },
    "sante_master": {
        "ues": [
            {"name": "Spécialités cliniques", "sub_ues": [
                {"name": "Médecine interne", "weight": 3, "courses": ["Cours Cardiologie avancée", "Cours Pneumologie avancée", "Cours Gastro-entérologie", "Cours Endocrinologie", "Cours Hématologie", "TD Cas cliniques", "TP Simulation haute fidélité"]},
                {"name": "Chirurgie et spécialités", "weight": 2.5, "courses": ["Cours Chirurgie générale", "Cours Orthopédie", "Cours ORL et ophtalmologie", "Cours Dermatologie", "Cours Urgences médico-chirurgicales", "TD Chirurgie", "TP Simulation chirurgicale"]},
            ]},
            {"name": "Recherche biomédicale", "sub_ues": [
                {"name": "Méthodologie de recherche", "weight": 2.5, "courses": ["Cours Méthodologie des essais cliniques", "Cours Lecture critique d'article", "Cours Biostatistiques avancées", "Cours Recherche translationnelle", "TD Méthodologie recherche"]},
                {"name": "Mémoire et publication", "weight": 2, "courses": ["Séminaire de mémoire S1", "Séminaire de mémoire S2", "Rédaction d'article scientifique", "Soutenance du mémoire"]},
            ]},
            {"name": "Professionnalisation", "sub_ues": [
                {"name": "Stage hospitalier avancé", "weight": 2, "courses": ["Stage externat service 1", "Stage externat service 2", "Gardes hospitalières", "Cours Gestion d'équipe soignante"]},
                {"name": "Droit et Gestion", "weight": 1.5, "courses": ["Cours Responsabilité médicale", "Cours Droit de la santé avancé", "Cours Management hospitalier", "Anglais médical avancé"]},
            ]},
        ],
    },
    "sante_stage": {
        "ues": [
            {"name": "Stage hospitalier et recherche", "sub_ues": [
                {"name": "Préparation au stage", "weight": 2, "courses": ["Cours Cadre réglementaire du stage", "Cours Éthique et déontologie", "Cours Rédaction du projet de stage", "Cours Secret médical et confidentialité"]},
                {"name": "Pratique clinique", "weight": 3, "courses": ["Stage Service hospitalier (6 semaines)", "Stage Consultation spécialisée", "Stage Recherche clinique", "Rapport de stage médical", "Présentation de cas clinique", "Soutenance devant le jury"]},
            ]},
        ],
    },
    # ── Ingénierie themes ──
    "ingenierie_general": {
        "ues": [
            {"name": "Sciences de l'ingénieur", "sub_ues": [
                {"name": "Mécanique et Matériaux", "weight": 3, "courses": ["Cours Mécanique des solides", "Cours Résistance des matériaux", "Cours Science des matériaux", "Cours Mécanique des fluides", "Cours Vibrations et acoustique", "TD Mécanique", "TP Matériaux"]},
                {"name": "Thermique et Énergétique", "weight": 2.5, "courses": ["Cours Thermodynamique appliquée", "Cours Transferts thermiques", "Cours Énergies renouvelables", "Cours Génie climatique", "TD Thermique", "TP Énergétique"]},
            ]},
            {"name": "Informatique et Automatique", "sub_ues": [
                {"name": "Programmation", "weight": 2.5, "courses": ["Cours Algorithmique et C", "Cours Python scientifique", "Cours Programmation orientée objet", "Cours Calcul scientifique", "TP Programmation", "Projet informatique"]},
                {"name": "Automatique et Robotique", "weight": 2.5, "courses": ["Cours Automatique linéaire", "Cours Systèmes asservis", "Cours Robotique industrielle", "Cours Capteurs et instrumentation", "TD Automatique", "TP Robotique"]},
            ]},
            {"name": "Électronique et Génie électrique", "sub_ues": [
                {"name": "Électronique", "weight": 2.5, "courses": ["Cours Électronique analogique", "Cours Électronique numérique", "Cours Microcontrôleurs", "Cours Traitement du signal", "TD Électronique", "TP Circuits"]},
                {"name": "Génie électrique", "weight": 2, "courses": ["Cours Machines électriques", "Cours Électrotechnique", "Cours Électronique de puissance", "TD Génie électrique"]},
            ]},
            {"name": "Transversales ingénieur", "sub_ues": [
                {"name": "Mathématiques appliquées", "weight": 2.5, "courses": ["Cours Analyse numérique", "Cours Probabilités et Statistiques", "Cours Optimisation", "Cours Méthodes aux éléments finis", "TD Maths appliquées"]},
                {"name": "Langues et Management", "weight": 1.5, "courses": ["Anglais technique S1", "Anglais technique S2", "Gestion de projet technique", "Communication en entreprise", "Économie industrielle"]},
            ]},
        ],
    },
    "ingenierie_prepa": {
        "ues": [
            {"name": "Mathématiques pour l'ingénieur", "sub_ues": [
                {"name": "Analyse et Algèbre", "weight": 3, "courses": ["Cours Analyse réelle", "Cours Algèbre linéaire", "Cours Équations différentielles", "Cours Séries et intégrales", "TD Mathématiques"]},
                {"name": "Géométrie et Calcul", "weight": 2, "courses": ["Cours Géométrie analytique", "Cours Calcul matriciel", "Cours Nombres complexes", "TD Géométrie"]},
            ]},
            {"name": "Sciences physiques", "sub_ues": [
                {"name": "Mécanique et Physique", "weight": 2.5, "courses": ["Cours Mécanique du point", "Cours Électricité", "Cours Thermodynamique", "Cours Optique", "TP Physique"]},
                {"name": "Méthodologie", "weight": 1.5, "courses": ["Cours Méthodologie scientifique", "Cours Expression technique", "Cours Anglais scientifique", "Projet technique"]},
            ]},
        ],
    },
    "ingenierie_master": {
        "ues": [
            {"name": "Génie avancé", "sub_ues": [
                {"name": "Conception et Innovation", "weight": 3, "courses": ["Cours CAO/DAO avancée", "Cours Conception mécatronique", "Cours Fabrication additive", "Cours Prototypage rapide", "Cours Innovation et brevets", "TD Conception", "TP Prototypage"]},
                {"name": "Simulation numérique", "weight": 2.5, "courses": ["Cours Éléments finis avancés", "Cours Simulation CFD", "Cours Simulation multiphysique", "Cours Jumeau numérique", "TD Simulation"]},
            ]},
            {"name": "Management industriel", "sub_ues": [
                {"name": "Gestion de production", "weight": 2.5, "courses": ["Cours Lean Manufacturing", "Cours Supply Chain Management", "Cours Qualité et normes ISO", "Cours Industrie 4.0", "TD Gestion de production"]},
                {"name": "Gestion de projet", "weight": 2, "courses": ["Cours Management de projet technique", "Cours Gestion des risques", "Cours Droit de l'ingénieur", "Cours Développement durable"]},
            ]},
            {"name": "Recherche et mémoire", "sub_ues": [
                {"name": "Séminaire", "weight": 2, "courses": ["Séminaire de recherche S1", "Séminaire de recherche S2", "Rédaction du mémoire d'ingénieur", "Soutenance du mémoire"]},
                {"name": "Professionnalisation", "weight": 2, "courses": ["Cours Entrepreneuriat technologique", "Cours Intelligence artificielle industrielle", "Anglais professionnel", "Stage en entreprise industrielle"]},
            ]},
        ],
    },
    "ingenierie_stage": {
        "ues": [
            {"name": "Projet industriel et stage", "sub_ues": [
                {"name": "Préparation du projet", "weight": 2, "courses": ["Cours Cahier des charges", "Cours Planification de projet", "Cours Gestion d'équipe technique", "Cours Normes et certifications"]},
                {"name": "Réalisation et stage", "weight": 3, "courses": ["Projet industriel en équipe", "Stage en entreprise (12 semaines)", "Stage en laboratoire de recherche", "Rapport de projet industriel", "Présentation technique", "Soutenance devant le jury"]},
            ]},
        ],
    },
    # ── Poudlard themes ──
    "poudlard_tronc": {
        "ues": [
            {"name": "Sortilèges et Enchantements", "sub_ues": [
                {"name": "Sortilèges fondamentaux", "weight": 3, "courses": ["Cours Lumos et Nox", "Cours Wingardium Leviosa", "Cours Accio et sortilèges d'attraction", "Cours Expelliarmus", "Cours Protego et boucliers magiques", "Cours Patronus", "TD Sortilèges offensifs", "TP Sortilèges pratiques"]},
                {"name": "Enchantements avancés", "weight": 2.5, "courses": ["Cours Enchantements de métamorphose", "Cours Enchantements de mémoire", "Cours Sortilèges Impardonnables (théorie)", "Cours Contresorts", "Cours Enchantements de protection", "TD Enchantements", "TP Enchantements supervisés"]},
                {"name": "Magie sans baguette", "weight": 1.5, "courses": ["Cours Magie informulée", "Cours Magie instinctive", "Cours Occlumencie fondamentale", "Cours Legilimencie (initiation)", "TD Magie sans baguette"]},
            ]},
            {"name": "Potions", "sub_ues": [
                {"name": "Potions élémentaires", "weight": 2.5, "courses": ["Cours Potions de soin", "Cours Potions de sommeil", "Cours Potions de chance (Felix Felicis)", "Cours Élixirs de base", "Cours Antidotes courants", "TD Potions élémentaires", "TP Brassage supervisé"]},
                {"name": "Potions avancées", "weight": 2, "courses": ["Cours Polynectar", "Cours Veritaserum", "Cours Potions de régénération", "Cours Poisons et antidotes avancés", "Cours Amortentia (théorie)", "TD Potions avancées", "TP Brassage complexe"]},
            ]},
            {"name": "Métamorphose", "sub_ues": [
                {"name": "Métamorphose élémentaire", "weight": 2.5, "courses": ["Cours Transformation d'objets", "Cours Disparition et apparition", "Cours Permutation", "Cours Conjuration élémentaire", "TD Métamorphose", "TP Métamorphose pratique"]},
                {"name": "Métamorphose humaine", "weight": 2, "courses": ["Cours Animagus (théorie)", "Cours Métamorphomage", "Cours Transformation partielle", "Cours Auto-métamorphose", "TD Métamorphose humaine", "TP Métamorphose supervisée"]},
            ]},
            {"name": "Défense contre les Forces du Mal", "sub_ues": [
                {"name": "Créatures des ténèbres", "weight": 2.5, "courses": ["Cours Détraqueurs et Patronus", "Cours Loups-garous et vampires", "Cours Épouvantards et Riddikulus", "Cours Inferis et spectres", "Cours Basilics et serpents magiques", "TD Créatures obscures", "TP Combat anti-créatures"]},
                {"name": "Magie noire (défense)", "weight": 2, "courses": ["Cours Maléfices et contre-maléfices", "Cours Objets maudits", "Cours Horcruxes (théorie)", "Cours Magie noire historique", "TD Défense appliquée", "TP Duels de défense"]},
            ]},
            {"name": "Transversales magiques", "sub_ues": [
                {"name": "Histoire de la Magie", "weight": 1.5, "courses": ["Cours Guerres des Gobelins", "Cours Procès de sorcières", "Cours Statut du Secret", "Cours Fondateurs de Poudlard", "Cours Histoire du Ministère"]},
                {"name": "Astronomie et Divination", "weight": 1.5, "courses": ["Cours Cartographie céleste", "Cours Lecture des astres", "Cours Boule de cristal", "Cours Feuilles de thé", "TD Astronomie pratique"]},
            ]},
        ],
    },
    "poudlard_aspic": {
        "ues": [
            {"name": "Botanique magique", "sub_ues": [
                {"name": "Plantes dangereuses", "weight": 2.5, "courses": ["Cours Mandragore", "Cours Filet du Diable", "Cours Saule Cogneur", "Cours Tentacula vénéneuse", "Cours Bubobulb", "TD Botanique pratique", "TP Serres avancées"]},
                {"name": "Herbologie appliquée", "weight": 2, "courses": ["Cours Propriétés médicinales", "Cours Ingrédients de potions", "Cours Plantes aquatiques magiques", "Cours Culture en serre", "TD Herbologie", "TP Récoltes"]},
            ]},
            {"name": "Soins aux Créatures Magiques", "sub_ues": [
                {"name": "Créatures classifiées", "weight": 2.5, "courses": ["Cours Hippogriffes", "Cours Sombrals", "Cours Niffleurs et Botrucs", "Cours Scroutts à Pétard", "Cours Dragons (théorie)", "TD Soins créatures", "TP Approche terrain"]},
                {"name": "Élevage et conservation", "weight": 2, "courses": ["Cours Licornes et êtres de la forêt", "Cours Phénix", "Cours Elfes de maison (éthique)", "Cours Réserves magiques", "TD Conservation", "TP Enclos pédagogiques"]},
            ]},
            {"name": "Étude des Runes et Arithmancie", "sub_ues": [
                {"name": "Runes anciennes", "weight": 2, "courses": ["Cours Runes elfiques", "Cours Runes nordiques", "Cours Déchiffrage de textes anciens", "Cours Inscriptions protectrices", "TD Runes pratiques"]},
                {"name": "Arithmancie", "weight": 2, "courses": ["Cours Numérologie magique", "Cours Prédictions arithmantiques", "Cours Formules et équations magiques", "Cours Matrices de pouvoir", "TD Arithmancie appliquée"]},
            ]},
            {"name": "Vol et Quidditch", "sub_ues": [
                {"name": "Technique de vol", "weight": 1.5, "courses": ["Cours Balai — Bases", "Cours Vol avancé", "Cours Acrobaties aériennes", "Cours Entretien du balai", "TP Vol libre"]},
                {"name": "Quidditch et sports magiques", "weight": 1.5, "courses": ["Cours Règles du Quidditch", "Cours Stratégies d'équipe", "Cours Entraînement physique magique", "Atelier Match inter-maisons"]},
            ]},
        ],
    },
    "poudlard_master": {
        "ues": [
            {"name": "Recherche en Magie Avancée", "sub_ues": [
                {"name": "Magie expérimentale", "weight": 3, "courses": ["Cours Création de sortilèges", "Cours Fusion de magies", "Cours Limites de la magie", "Cours Magie élémentaire avancée", "Projet recherche magique", "TP Expérimentation supervisée"]},
                {"name": "Théorie magique fondamentale", "weight": 2.5, "courses": ["Cours Lois fondamentales de la magie", "Cours Exceptions de Gamp", "Cours Magie ancienne", "Cours Liens magiques et serments", "TD Théorie magique"]},
            ]},
            {"name": "Spécialisations du Ministère", "sub_ues": [
                {"name": "Auror — Formation avancée", "weight": 3, "courses": ["Cours Filature et dissimulation", "Cours Interrogatoire magique", "Cours Combat en situation réelle", "Cours Droit magique pénal", "Cours Procédures du Ministère", "TP Simulations d'intervention"]},
                {"name": "Médicomagie", "weight": 2.5, "courses": ["Cours Diagnostic magique", "Cours Guérison des maléfices", "Cours Potions médicinales avancées", "Cours Empoisonnements et morsures", "Cours Maladies magiques", "TP Stage Ste Mangouste"]},
            ]},
            {"name": "Étude des Moldus", "sub_ues": [
                {"name": "Civilisation moldue", "weight": 1.5, "courses": ["Cours Technologie moldue", "Cours Société moldue contemporaine", "Cours Électricité (découverte)", "Cours Relations sorciers-moldus"]},
                {"name": "Adaptation et intégration", "weight": 1.5, "courses": ["Cours Passer inaperçu", "Cours Monnaie et économie moldue", "Cours Transports moldus", "Projet immersion moldue"]},
            ]},
        ],
    },
    "poudlard_stage": {
        "ues": [
            {"name": "Stage professionnel", "sub_ues": [
                {"name": "Préparation au stage", "weight": 2, "courses": ["Cours Rédaction de parchemin de candidature", "Cours Entretien avec le Maître de stage", "Cours Éthique professionnelle magique", "Cours Serment de confidentialité"]},
                {"name": "Pratique en milieu magique", "weight": 3, "courses": ["Stage Ministère de la Magie", "Stage Gringotts", "Stage Ste Mangouste", "Stage Chemin de Traverse", "Rapport de stage magique", "Soutenance devant le jury"]},
            ]},
        ],
    },
    "poudlard_prepa": {
        "ues": [
            {"name": "Initiation à la Magie", "sub_ues": [
                {"name": "Premiers sortilèges", "weight": 2.5, "courses": ["Cours Lumos et Nox", "Cours Wingardium Leviosa", "Cours Alohomora", "Cours Reparo", "Cours Nettoyage magique", "TD Baguette — premiers gestes", "TP Sortilèges dirigés"]},
                {"name": "Potions — Niveau découverte", "weight": 2, "courses": ["Cours Potion Cure-Furoncle", "Cours Philtre de Paix", "Cours Herbicide magique", "Cours Règles de sécurité en cachot", "TD Potions simples", "TP Brassage d'initiation"]},
                {"name": "Vol sur balai", "weight": 1.5, "courses": ["Cours Appel du balai", "Cours Décollage et atterrissage", "Cours Manœuvres de base", "Cours Sécurité aérienne", "TP Vol supervisé"]},
            ]},
            {"name": "Culture du Monde Magique", "sub_ues": [
                {"name": "Histoire de la Magie (initiation)", "weight": 2, "courses": ["Cours Fondateurs de Poudlard", "Cours Code International du Secret Magique", "Cours Grandes batailles sorcières", "Cours Personnalités marquantes", "Cours Confédération Internationale des Sorciers"]},
                {"name": "Vie et coutumes sorcières", "weight": 1.5, "courses": ["Cours Monnaie sorcière (Gallions, Mornilles, Noises)", "Cours Transports magiques (Poudre de Cheminette, Portoloin, Transplanage)", "Cours Le Ministère de la Magie", "Cours La Gazette du Sorcier"]},
                {"name": "Botanique — Découverte", "weight": 1.5, "courses": ["Cours Plantes magiques inoffensives", "Cours Mandragore (théorie)", "Cours Dictame et plantes curatives", "TD Serres niveau 1"]},
            ]},
        ],
    },
    "poudlard_quidditch": {
        "ues": [
            {"name": "Quidditch — Entraînement intensif", "sub_ues": [
                {"name": "Postes et tactiques", "weight": 3, "courses": ["Cours Attrapeur — Techniques de capture du Vif d'Or", "Cours Poursuiveur — Passes et tirs", "Cours Gardien — Défense des anneaux", "Cours Batteur — Maniement des Cognards", "TD Stratégies d'équipe", "TD Analyse de matchs historiques", "TP Match d'entraînement"]},
                {"name": "Condition physique magique", "weight": 2, "courses": ["Cours Endurance en vol longue durée", "Cours Réflexes magiques", "Cours Aérodynamique sur balai", "Cours Résistance aux intempéries", "TP Circuit d'obstacles aériens"]},
                {"name": "Réglementation et arbitrage", "weight": 1.5, "courses": ["Cours Règles officielles de la Ligue", "Cours Fautes et pénalités", "Cours Histoire de la Coupe du Monde", "Cours Rôle de l'arbitre"]},
            ]},
            {"name": "Sports magiques complémentaires", "sub_ues": [
                {"name": "Courses de balais", "weight": 2, "courses": ["Cours Slalom en forêt", "Cours Course de vitesse", "Cours Relais aérien", "Cours Entretien et personnalisation du balai", "TP Course chronométrée"]},
                {"name": "Duels sportifs", "weight": 2, "courses": ["Cours Club de Duel — Fondamentaux", "Cours Sortilèges de compétition", "Cours Parade et riposte", "Cours Étiquette du duel", "Atelier Tournoi inter-maisons"]},
            ]},
        ],
    },
    "arts_stage": {
        "ues": [
            {"name": "Cadre de recherche", "sub_ues": [
                {"name": "Projet de recherche", "weight": 2, "courses": ["Élaboration du projet", "Problématique et hypothèses", "Cadre théorique", "Méthodologie de recherche-création"]},
                {"name": "État de l'art", "weight": 1.5, "courses": ["Bibliographie commentée", "Revue de littérature artistique", "Cartographie des pratiques"]},
            ]},
            {"name": "Pratique de terrain", "sub_ues": [
                {"name": "Résidence de création", "weight": 3, "courses": ["Résidence semaine 1 — Exploration", "Résidence semaine 2 — Expérimentation", "Résidence semaine 3 — Production", "Résidence semaine 4 — Finalisation", "Atelier en résidence", "Rencontres professionnelles"]},
                {"name": "Restitution", "weight": 2.5, "courses": ["Journal de recherche-création", "Documentation du processus créatif", "Restitution publique", "Soutenance finale", "Rapport de stage"]},
            ]},
        ],
    },
}

# ============================================================================
# Formation templates par thème d'école
# ============================================================================

FORMATION_TEMPLATES = {
    "sciences": [
        {"name_tpl": "Tronc commun {school_name} L2-L3", "hours": 1200, "theme": "sciences_generales", "levels": ["L2", "L3"], "year_span": 2, "capacity": 120, "primary": True},
        {"name_tpl": "Prépa {school_short} — T1 Fondamentaux", "hours": 200, "theme": "sciences_prepa", "levels": ["Prépa"], "year_span": 1, "capacity": 80, "trimester": 1},
        {"name_tpl": "Prépa {school_short} — T2 Approfondissement", "hours": 200, "theme": "sciences_prepa", "levels": ["Prépa"], "year_span": 1, "capacity": 80, "trimester": 2},
        {"name_tpl": "Stage Recherche en Laboratoire", "hours": 140, "theme": "sciences_stage", "levels": ["M1", "M2"], "year_span": 1, "capacity": 40},
    ],
    "arts": [
        {"name_tpl": "Enseignements théoriques — Histoire de l'art", "hours": 400, "theme": "arts_theorie", "levels": ["L1", "L2", "L3"], "year_span": 1, "capacity": 60, "primary": True},
        {"name_tpl": "Ateliers pratiques — Arts plastiques", "hours": 300, "theme": "arts_pratique", "levels": ["L1", "L2", "L3"], "year_span": 1, "capacity": 45},
        {"name_tpl": "Master Création Contemporaine — Tronc commun", "hours": 400, "theme": "arts_master", "levels": ["M1", "M2"], "year_span": 1, "capacity": 35},
        {"name_tpl": "Workshop International Arts", "hours": 100, "theme": "arts_workshop", "levels": ["M1", "M2"], "year_span": 1, "capacity": 25},
        {"name_tpl": "Stage Recherche Création", "hours": 140, "theme": "arts_stage", "levels": ["M1", "M2"], "year_span": 1, "capacity": 30},
    ],
    "droit": [
        {"name_tpl": "Tronc commun {school_name} — Droit L1-L3", "hours": 1000, "theme": "droit_general", "levels": ["L1", "L2", "L3"], "year_span": 3, "capacity": 100, "primary": True},
        {"name_tpl": "Prépa {school_short} — Concours juridiques", "hours": 200, "theme": "droit_prepa", "levels": ["Prépa"], "year_span": 1, "capacity": 60},
        {"name_tpl": "Master {school_short} — Droit des affaires", "hours": 450, "theme": "droit_master", "levels": ["M1", "M2"], "year_span": 1, "capacity": 40},
        {"name_tpl": "Stage Juridique — Cabinet & Juridiction", "hours": 140, "theme": "droit_stage", "levels": ["M1", "M2"], "year_span": 1, "capacity": 30},
    ],
    "sante": [
        {"name_tpl": "Tronc commun {school_name} — PASS/LAS", "hours": 1200, "theme": "sante_general", "levels": ["L1", "L2", "L3"], "year_span": 3, "capacity": 120, "primary": True},
        {"name_tpl": "Prépa {school_short} — Concours santé", "hours": 250, "theme": "sante_prepa", "levels": ["Prépa"], "year_span": 1, "capacity": 80},
        {"name_tpl": "Master {school_short} — Spécialités cliniques", "hours": 500, "theme": "sante_master", "levels": ["M1", "M2"], "year_span": 1, "capacity": 35},
        {"name_tpl": "Stage Hospitalier & Recherche", "hours": 160, "theme": "sante_stage", "levels": ["M1", "M2"], "year_span": 1, "capacity": 30},
    ],
    "ingenierie": [
        {"name_tpl": "Tronc commun {school_name} — Cycle ingénieur", "hours": 1100, "theme": "ingenierie_general", "levels": ["L1", "L2", "L3"], "year_span": 3, "capacity": 100, "primary": True},
        {"name_tpl": "Prépa {school_short} — Sciences de l'ingénieur", "hours": 220, "theme": "ingenierie_prepa", "levels": ["Prépa"], "year_span": 1, "capacity": 70},
        {"name_tpl": "Master {school_short} — Génie & Innovation", "hours": 450, "theme": "ingenierie_master", "levels": ["M1", "M2"], "year_span": 1, "capacity": 40},
        {"name_tpl": "Projet Industriel & Stage", "hours": 160, "theme": "ingenierie_stage", "levels": ["M1", "M2"], "year_span": 1, "capacity": 30},
    ],
    "poudlard": [
        {"name_tpl": "Tronc commun {school_name} — BUSE", "hours": 1000, "theme": "poudlard_tronc", "levels": ["L1", "L2", "L3"], "year_span": 3, "capacity": 100, "primary": True},
        {"name_tpl": "Prépa {school_short} — Initiation Magique", "hours": 220, "theme": "poudlard_prepa", "levels": ["Prépa"], "year_span": 1, "capacity": 80, "trimester": 1},
        {"name_tpl": "Prépa {school_short} — Approfondissement Magique", "hours": 220, "theme": "poudlard_prepa", "levels": ["Prépa"], "year_span": 1, "capacity": 80, "trimester": 2},
        {"name_tpl": "ASPIC {school_short} — Spécialisations", "hours": 400, "theme": "poudlard_aspic", "levels": ["M1"], "year_span": 1, "capacity": 60},
        {"name_tpl": "Perfectionnement Quidditch & Sports Magiques", "hours": 300, "theme": "poudlard_quidditch", "levels": ["L1", "L2", "L3"], "year_span": 1, "capacity": 45},
        {"name_tpl": "Master Magie Avancée & Spécialisations Ministère", "hours": 500, "theme": "poudlard_master", "levels": ["M1", "M2"], "year_span": 1, "capacity": 35},
        {"name_tpl": "Stage Professionnel Monde Magique", "hours": 140, "theme": "poudlard_stage", "levels": ["M2"], "year_span": 1, "capacity": 30},
    ],
}

FORMULA_TEMPLATES = {
    "sciences": [
        {
            "name_tpl": "Licence {school_name} — Cycle L2-L3",
            "levels": ["L2", "L3"], "price_cents": 850000, "year_span": 2,
            "formation_indices": [0], "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 15000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["CV", "Lettre de motivation", "Relevés de notes"]},
                {"name": "Admission", "commission": True, "advance_cents": 100000, "advance_label": "Acompte de réservation"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "Photo d'identité"]},
            ],
            "discounts": [
                {"name": "Bourse au mérite", "amount_cents": 100000},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
                {"name": "Fratrie", "amount_pct": 10},
            ],
            "charges": [{"name": "Frais de matériel scientifique", "amount_cents": 35000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
        {
            "name_tpl": "Prépa Scientifique Intensive",
            "levels": ["Prépa"], "price_cents": 450000, "year_span": 1,
            "formation_indices": [1, 2], "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 8000, "charge_label": "Frais de candidature", "charge_deductible": True, "files": ["Bulletins scolaires", "Résultats bac"]},
                {"name": "Confirmation", "advance_cents": 50000, "advance_label": "Acompte de confirmation"},
                {"name": "Inscription", "files": ["Pièce d'identité", "Attestation CVEC"]},
            ],
            "discounts": [
                {"name": "Réduction paiement anticipé", "amount_cents": 30000},
                {"name": "Bourse excellence", "amount_pct": 15},
            ],
            "charges": [{"name": "Manuels et supports de cours", "amount_cents": 15000}],
            "schedules": ["comptant", "2x"],
        },
        {
            "name_tpl": "Stage Recherche en Laboratoire",
            "levels": ["M1", "M2"], "price_cents": 180000, "year_span": 1,
            "formation_indices": [3], "is_salable": True,
            "steps": [
                {"name": "Pré-inscription", "charge_cents": 5000, "charge_label": "Frais de traitement", "charge_deductible": False, "files": ["Projet de recherche", "CV académique"]},
                {"name": "Validation scientifique", "commission": True},
                {"name": "Inscription au stage", "files": ["Convention de stage signée"]},
            ],
            "discounts": [{"name": "Étudiant de l'établissement", "amount_pct": 20}],
            "charges": [{"name": "Équipement de laboratoire", "amount_cents": 12000}],
            "schedules": ["unique"],
        },
    ],
    "arts": [
        {
            "name_tpl": "Licence Arts Plastiques — Cycle complet",
            "levels": ["L1", "L2", "L3"], "price_cents": 650000, "year_span": 1,
            "formation_indices": [0, 1], "is_salable": True,
            "steps": [
                {"name": "Candidature artistique", "charge_cents": 12000, "charge_label": "Frais de candidature", "charge_deductible": True, "files": ["Portfolio artistique", "Lettre de motivation", "Bulletins scolaires"]},
                {"name": "Jury d'admission", "commission": True, "advance_cents": 80000, "advance_label": "Acompte de réservation"},
                {"name": "Inscription administrative", "files": ["Pièce d'identité", "Attestation CVEC", "Photo d'identité", "Attestation assurance"]},
            ],
            "discounts": [
                {"name": "Bourse talent artistique", "amount_cents": 80000},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
                {"name": "Fratrie", "amount_pct": 10},
            ],
            "charges": [
                {"name": "Fournitures artistiques", "amount_cents": 25000},
                {"name": "Accès ateliers spécialisés", "amount_cents": 18000},
            ],
            "schedules": ["comptant", "3x", "8_mensualites"],
        },
        {
            "name_tpl": "Master Création Contemporaine",
            "levels": ["M1", "M2"], "price_cents": 780000, "year_span": 1,
            "formation_indices": [2],
            "optional_formation_indices": [3, 4], "option_min": 1, "option_max": 2,
            "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 15000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["Portfolio", "Projet de recherche", "CV", "Diplômes"]},
                {"name": "Entretien et commission", "commission": True, "advance_cents": 120000, "advance_label": "Acompte d'admission"},
                {"name": "Choix des options"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "Attestation assurance", "RIB"]},
            ],
            "discounts": [
                {"name": "Bourse recherche création", "amount_cents": 150000},
                {"name": "Ancien étudiant Licence", "amount_pct": 10},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
            ],
            "charges": [{"name": "Matériel studio", "amount_cents": 30000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
    ],
    "droit": [
        {
            "name_tpl": "Licence {school_name} — Droit général",
            "levels": ["L1", "L2", "L3"], "price_cents": 750000, "year_span": 3,
            "formation_indices": [0], "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 12000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["CV", "Lettre de motivation", "Relevés de notes"]},
                {"name": "Admission", "commission": True, "advance_cents": 90000, "advance_label": "Acompte de réservation"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "Photo d'identité"]},
            ],
            "discounts": [
                {"name": "Bourse au mérite", "amount_cents": 90000},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
                {"name": "Fratrie", "amount_pct": 10},
            ],
            "charges": [{"name": "Codes et manuels juridiques", "amount_cents": 25000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
        {
            "name_tpl": "Prépa Concours Juridiques",
            "levels": ["Prépa"], "price_cents": 380000, "year_span": 1,
            "formation_indices": [1], "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 8000, "charge_label": "Frais de candidature", "charge_deductible": True, "files": ["Bulletins scolaires", "Résultats bac"]},
                {"name": "Confirmation", "advance_cents": 45000, "advance_label": "Acompte de confirmation"},
                {"name": "Inscription", "files": ["Pièce d'identité", "Attestation CVEC"]},
            ],
            "discounts": [
                {"name": "Réduction paiement anticipé", "amount_cents": 25000},
                {"name": "Bourse excellence juridique", "amount_pct": 15},
            ],
            "charges": [{"name": "Recueil de jurisprudence", "amount_cents": 12000}],
            "schedules": ["comptant", "2x"],
        },
        {
            "name_tpl": "Master Droit des Affaires",
            "levels": ["M1", "M2"], "price_cents": 920000, "year_span": 1,
            "formation_indices": [2],
            "optional_formation_indices": [3], "option_min": 0, "option_max": 1,
            "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 15000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["CV", "Lettre de motivation", "Relevés L3", "Mémoire de recherche"]},
                {"name": "Entretien et commission", "commission": True, "advance_cents": 130000, "advance_label": "Acompte d'admission"},
                {"name": "Choix de spécialisation"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "RIB"]},
            ],
            "discounts": [
                {"name": "Bourse recherche juridique", "amount_cents": 120000},
                {"name": "Ancien étudiant Licence", "amount_pct": 10},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
            ],
            "charges": [{"name": "Accès bases de données juridiques", "amount_cents": 18000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
    ],
    "sante": [
        {
            "name_tpl": "PASS/LAS — {school_name}",
            "levels": ["L1", "L2", "L3"], "price_cents": 900000, "year_span": 3,
            "formation_indices": [0], "is_salable": True,
            "steps": [
                {"name": "Candidature Parcoursup", "charge_cents": 10000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["Bulletins scolaires", "Lettre de motivation", "Résultats bac"]},
                {"name": "Admission", "commission": True, "advance_cents": 120000, "advance_label": "Acompte de réservation"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "Certificat médical", "Photo d'identité"]},
            ],
            "discounts": [
                {"name": "Bourse au mérite scientifique", "amount_cents": 110000},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
                {"name": "Fratrie", "amount_pct": 10},
            ],
            "charges": [{"name": "Blouse et matériel TP", "amount_cents": 20000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
        {
            "name_tpl": "Prépa Concours Santé Intensive",
            "levels": ["Prépa"], "price_cents": 480000, "year_span": 1,
            "formation_indices": [1], "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 8000, "charge_label": "Frais de candidature", "charge_deductible": True, "files": ["Bulletins scolaires", "Résultats bac S/STL"]},
                {"name": "Confirmation", "advance_cents": 55000, "advance_label": "Acompte de confirmation"},
                {"name": "Inscription", "files": ["Pièce d'identité", "Attestation CVEC"]},
            ],
            "discounts": [
                {"name": "Réduction paiement anticipé", "amount_cents": 30000},
                {"name": "Bourse excellence", "amount_pct": 15},
            ],
            "charges": [{"name": "Supports de cours et QCM", "amount_cents": 15000}],
            "schedules": ["comptant", "2x"],
        },
        {
            "name_tpl": "Master Spécialités Cliniques",
            "levels": ["M1", "M2"], "price_cents": 980000, "year_span": 1,
            "formation_indices": [2],
            "optional_formation_indices": [3], "option_min": 0, "option_max": 1,
            "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 15000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["CV médical", "Relevés de notes", "Attestation de stage hospitalier", "Lettre de motivation"]},
                {"name": "Commission d'admission", "commission": True, "advance_cents": 150000, "advance_label": "Acompte d'admission"},
                {"name": "Choix de spécialité"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "Certificat de vaccination", "RIB"]},
            ],
            "discounts": [
                {"name": "Bourse recherche médicale", "amount_cents": 150000},
                {"name": "Ancien étudiant PASS", "amount_pct": 10},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
            ],
            "charges": [{"name": "Matériel de stage clinique", "amount_cents": 30000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
    ],
    "ingenierie": [
        {
            "name_tpl": "Cycle Ingénieur — {school_name}",
            "levels": ["L1", "L2", "L3"], "price_cents": 850000, "year_span": 3,
            "formation_indices": [0], "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 12000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["CV", "Lettre de motivation", "Relevés de notes", "Résultats concours"]},
                {"name": "Admission sur concours", "commission": True, "advance_cents": 100000, "advance_label": "Acompte de réservation"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "Photo d'identité"]},
            ],
            "discounts": [
                {"name": "Bourse au mérite ingénieur", "amount_cents": 100000},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
                {"name": "Fratrie", "amount_pct": 10},
            ],
            "charges": [{"name": "Matériel informatique et prototypage", "amount_cents": 35000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
        {
            "name_tpl": "Prépa Sciences de l'Ingénieur",
            "levels": ["Prépa"], "price_cents": 420000, "year_span": 1,
            "formation_indices": [1], "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 8000, "charge_label": "Frais de candidature", "charge_deductible": True, "files": ["Bulletins scolaires", "Résultats bac"]},
                {"name": "Confirmation", "advance_cents": 50000, "advance_label": "Acompte de confirmation"},
                {"name": "Inscription", "files": ["Pièce d'identité", "Attestation CVEC"]},
            ],
            "discounts": [
                {"name": "Réduction paiement anticipé", "amount_cents": 28000},
                {"name": "Bourse excellence technique", "amount_pct": 15},
            ],
            "charges": [{"name": "Manuels et logiciels", "amount_cents": 15000}],
            "schedules": ["comptant", "2x"],
        },
        {
            "name_tpl": "Master Génie & Innovation",
            "levels": ["M1", "M2"], "price_cents": 950000, "year_span": 1,
            "formation_indices": [2],
            "optional_formation_indices": [3], "option_min": 0, "option_max": 1,
            "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 15000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["CV", "Relevés cycle ingénieur", "Projet de spécialisation", "Lettre de recommandation"]},
                {"name": "Entretien technique et commission", "commission": True, "advance_cents": 140000, "advance_label": "Acompte d'admission"},
                {"name": "Choix de spécialisation"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité", "Attestation CVEC", "Attestation assurance", "RIB"]},
            ],
            "discounts": [
                {"name": "Bourse recherche industrielle", "amount_cents": 130000},
                {"name": "Ancien élève ingénieur", "amount_pct": 10},
                {"name": "Réduction paiement comptant (-5%)", "amount_pct": 5},
            ],
            "charges": [{"name": "Accès laboratoires et plateformes", "amount_cents": 25000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
    ],
    "poudlard": [
        {
            "name_tpl": "Cursus BUSE — {school_name}",
            "levels": ["L1", "L2", "L3"], "price_cents": 700000, "year_span": 3,
            "formation_indices": [0], "is_salable": True,
            "steps": [
                {"name": "Lettre d'admission", "charge_cents": 0, "charge_label": "Hibou postal", "charge_deductible": False, "files": ["Lettre de Poudlard", "Liste de fournitures"]},
                {"name": "Cérémonie du Choixpeau", "commission": True, "advance_cents": 80000, "advance_label": "Acompte de rentrée"},
                {"name": "Inscription définitive", "files": ["Baguette magique enregistrée", "Attestation parentale", "Photo d'identité sorcière"]},
            ],
            "discounts": [
                {"name": "Bourse du Ministère de la Magie", "amount_cents": 120000},
                {"name": "Fratrie sorcière", "amount_pct": 15},
                {"name": "Réduction Sang-Mêlé solidarité", "amount_pct": 5},
            ],
            "charges": [{"name": "Fournitures magiques (Fleury & Bott)", "amount_cents": 45000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
        {
            "name_tpl": "Prépa Sorcière Intensive — {school_short}",
            "levels": ["Prépa"], "price_cents": 380000, "year_span": 1,
            "formation_indices": [1, 2], "is_salable": True,
            "steps": [
                {"name": "Réception du hibou", "charge_cents": 0, "charge_label": "Frais de chouette postale", "charge_deductible": False, "files": ["Lettre d'acceptation", "Résultats scolaires moldus"]},
                {"name": "Passage au Chemin de Traverse", "advance_cents": 40000, "advance_label": "Acompte de fournitures"},
                {"name": "Inscription à la Prépa", "files": ["Baguette magique", "Attestation parentale"]},
            ],
            "discounts": [
                {"name": "Né-Moldu (aide à l'intégration)", "amount_cents": 50000},
                {"name": "Bourse Pré-au-Lard", "amount_pct": 10},
            ],
            "charges": [
                {"name": "Chaudron, balance et fioles", "amount_cents": 18000},
                {"name": "Robes de sorcier (Mme Guipure)", "amount_cents": 12000},
            ],
            "schedules": ["comptant", "2x"],
        },
        {
            "name_tpl": "ASPIC & Spécialisations",
            "levels": ["M1"], "price_cents": 500000, "year_span": 1,
            "formation_indices": [3], "is_salable": True,
            "steps": [
                {"name": "Résultats BUSE", "charge_cents": 5000, "charge_label": "Frais d'examen", "charge_deductible": True, "files": ["Relevé de BUSE", "Lettre de recommandation du directeur de maison"]},
                {"name": "Validation des ASPIC", "advance_cents": 60000, "advance_label": "Acompte de spécialisation"},
                {"name": "Inscription ASPIC", "files": ["Choix de matières", "Attestation parentale"]},
            ],
            "discounts": [
                {"name": "Excellence BUSE (Optimal)", "amount_cents": 80000},
                {"name": "Bourse Dumbledore", "amount_pct": 20},
            ],
            "charges": [{"name": "Équipement de spécialisation", "amount_cents": 25000}],
            "schedules": ["comptant", "2x"],
        },
        {
            "name_tpl": "Perfectionnement Quidditch & Sports — {school_short}",
            "levels": ["L1", "L2", "L3"], "price_cents": 350000, "year_span": 1,
            "formation_indices": [4], "is_salable": True,
            "steps": [
                {"name": "Essais sur le terrain", "charge_cents": 8000, "charge_label": "Frais de sélection", "charge_deductible": True, "files": ["Certificat médical (Mme Pomfresh)", "Autorisation parentale pour vol"]},
                {"name": "Sélection par le capitaine", "commission": True, "advance_cents": 35000, "advance_label": "Acompte équipement sportif"},
                {"name": "Inscription définitive", "files": ["Choix de poste", "Engagement sportif"]},
            ],
            "discounts": [
                {"name": "Bourse sportive inter-maisons", "amount_cents": 60000},
                {"name": "Réduction ancien joueur", "amount_pct": 10},
            ],
            "charges": [
                {"name": "Balai de compétition (Nimbus / Éclair de Feu)", "amount_cents": 55000},
                {"name": "Tenue de Quidditch personnalisée", "amount_cents": 15000},
            ],
            "schedules": ["comptant", "3x"],
        },
        {
            "name_tpl": "Master Magie Avancée",
            "levels": ["M1", "M2"], "price_cents": 900000, "year_span": 1,
            "formation_indices": [5],
            "optional_formation_indices": [6], "option_min": 0, "option_max": 1,
            "is_salable": True,
            "steps": [
                {"name": "Candidature", "charge_cents": 10000, "charge_label": "Frais de dossier", "charge_deductible": True, "files": ["Relevé ASPIC", "Projet de recherche magique", "Parchemin de motivation"]},
                {"name": "Entretien devant le jury", "commission": True, "advance_cents": 150000, "advance_label": "Acompte de recherche"},
                {"name": "Choix de spécialisation"},
                {"name": "Inscription définitive", "files": ["Pièce d'identité sorcière", "Serment magique", "RIB Gringotts"]},
            ],
            "discounts": [
                {"name": "Bourse Ordre de Merlin", "amount_cents": 200000},
                {"name": "Ancien élève de Poudlard", "amount_pct": 10},
                {"name": "Réduction paiement Gallions comptant", "amount_pct": 5},
            ],
            "charges": [{"name": "Accès Département des Mystères (stage)", "amount_cents": 35000}],
            "schedules": ["comptant", "3x", "10_mensualites"],
        },
    ],
}


# ============================================================================
# Templates — Diplômes (degrees) liés aux formules
# ============================================================================
# Chaque entrée : formula_index → { degree info }
# formula_index correspond à l'index dans FORMULA_TEMPLATES du thème
# degree_level_id : cf GET /degrees/levels (25 niveaux disponibles)
#   1=phd, 2=hdr, 3=doc, 4=master, 5=engineer_commerce, 6=master_specialized,
#   7=master_research, 8=master_pro, 9=licence, 10=licence_pro,
#   11=other_6 (bac+3/4), 12=bts, 13=but, 14=cap_bep, 15=deust,
#   16=dut, 17=du, 18=other_4 (bac), 19=other_5 (bac+2),
#   20=other_3 (infra-bac), 21=other_7 (bac+5+), 22=other_2,
#   23=bachelor, 24=none, 25=other_1

DEGREE_TEMPLATES = {
    "sciences": {
        # Formula 0: Licence Sciences & Techno → Licence
        0: {
            "name": "Licence Sciences et Technologies",
            "official_name": "Licence mention Sciences et Technologies",
            "degree_level_id": 9,  # licence
            "code": "LST",
            "rncp_level": 6,
        },
        # Formula 1: Prépa Scientifique → Pas de diplôme (prépa)
        # Formula 2: Stage Recherche → DU (diplôme universitaire)
        2: {
            "name": "Diplôme Universitaire Recherche",
            "official_name": "DU Recherche en Sciences Expérimentales",
            "degree_level_id": 17,  # du
            "code": "DUR",
            "rncp_level": 7,
        },
    },
    "arts": {
        # Formula 0: Licence Arts Plastiques — Cycle complet → Licence
        0: {
            "name": "Licence Arts, Lettres et Culture",
            "official_name": "Licence mention Arts plastiques",
            "degree_level_id": 9,  # licence
            "code": "LAC",
            "rncp_level": 6,
        },
        # Formula 1: Master Création Contemporaine → Master
        1: {
            "name": "Master Création Contemporaine",
            "official_name": "Master mention Création artistique",
            "degree_level_id": 4,  # master
            "code": "MCC",
            "rncp_level": 7,
        },
    },
    "droit": {
        0: {
            "name": "Licence en Droit",
            "official_name": "Licence mention Droit",
            "degree_level_id": 9,
            "code": "LD",
            "rncp_level": 6,
        },
    },
    "sante": {
        0: {
            "name": "Licence Sciences de la Santé",
            "official_name": "Licence mention Sciences pour la santé",
            "degree_level_id": 9,
            "code": "LSS",
            "rncp_level": 6,
        },
    },
    "ingenierie": {
        0: {
            "name": "Diplôme d'Ingénieur",
            "official_name": "Titre d'ingénieur diplômé",
            "degree_level_id": 5,  # engineer_commerce
            "code": "ING",
            "rncp_level": 7,
        },
        2: {
            "name": "Master Génie et Innovation",
            "official_name": "Master mention Génie industriel",
            "degree_level_id": 4,
            "code": "MGI",
            "rncp_level": 7,
        },
    },
    "poudlard": {
        # Formula 0: Cursus BUSE → Licence (3 ans)
        0: {
            "name": "Brevet Universel de Sorcellerie",
            "official_name": "BUSE — Brevet Universel de Sorcellerie Élémentaire",
            "degree_level_id": 9,  # licence (EQF 6)
            "code": "BUSE",
            "rncp_level": 6,
        },
        # Formula 1: Prépa Sorcière → Bac-level
        1: {
            "name": "Certificat de Prépa Sorcière",
            "official_name": "Certificat de Préparation aux Arts Magiques",
            "degree_level_id": 18,  # other_4 / bac
            "code": "CPS",
            "rncp_level": 4,
        },
        # Formula 2: ASPIC & Spécialisations → Master
        2: {
            "name": "Accumulation de Sorcellerie",
            "official_name": "ASPIC — Accumulation de Sorcellerie Particulièrement Intensive et Contraignante",
            "degree_level_id": 4,  # master (EQF 7)
            "code": "ASPIC",
            "rncp_level": 7,
        },
        # Formula 3: Quidditch → Diplôme sportif bac+3
        3: {
            "name": "Brevet de Quidditch Professionnel",
            "official_name": "Brevet Professionnel de Quidditch et Sports Magiques",
            "degree_level_id": 11,  # other_6 (bac+3/4)
            "code": "BQP",
            "rncp_level": 6,
        },
        # Formula 4: Master Magie Avancée → Master
        4: {
            "name": "Master en Magie Avancée",
            "official_name": "Master mention Recherche en Magie Avancée et Défense",
            "degree_level_id": 4,  # master (EQF 7)
            "code": "MMA",
            "rncp_level": 7,
        },
    },
}


# ============================================================================
# Templates — Employeurs (employers)
# ============================================================================
# Chaque entrée : legal_name, commercial_name, siren, sector, naf, employees_count,
#                  city, postal, address, domain, contacts[]

EMPLOYER_DATASETS = {
    "standard": [
        # --- Tech / ESN ---
        {"legal_name": "Capgemini SE", "commercial_name": "Capgemini", "siren": "330703844", "sector": "private", "naf": "6202A", "employees_count": 350000, "city": "Paris", "postal": "75008", "address": "11 rue de Tilsitt", "domain": "capgemini.com",
         "contacts": [{"first_name": "Nathalie", "last_name": "Dumont", "position": "Responsable alternance", "email": "n.dumont@capgemini.com"},
                      {"first_name": "Marc", "last_name": "Lefèvre", "position": "Tuteur entreprise", "email": "m.lefevre@capgemini.com"}]},
        {"legal_name": "Dassault Systèmes SE", "commercial_name": "Dassault Systèmes", "siren": "322306440", "sector": "private", "naf": "5829C", "employees_count": 23000, "city": "Vélizy-Villacoublay", "postal": "78140", "address": "10 rue Marcel Dassault", "domain": "3ds.com",
         "contacts": [{"first_name": "Sophie", "last_name": "Bernard", "position": "DRH", "email": "s.bernard@3ds.com"}]},
        {"legal_name": "Atos SE", "commercial_name": "Atos", "siren": "323623603", "sector": "private", "naf": "6202A", "employees_count": 95000, "city": "Bezons", "postal": "95870", "address": "River Ouest, 80 quai Voltaire", "domain": "atos.net",
         "contacts": [{"first_name": "Pierre", "last_name": "Moreau", "position": "Responsable stage", "email": "p.moreau@atos.net"}]},
        {"legal_name": "OVHcloud SAS", "commercial_name": "OVHcloud", "siren": "424761419", "sector": "private", "naf": "6311Z", "employees_count": 2600, "city": "Roubaix", "postal": "59100", "address": "2 rue Kellermann", "domain": "ovhcloud.com",
         "contacts": [{"first_name": "Léa", "last_name": "Petit", "position": "Campus manager", "email": "l.petit@ovhcloud.com"}]},
        {"legal_name": "Doctolib SAS", "commercial_name": "Doctolib", "siren": "794598813", "sector": "private", "naf": "6201Z", "employees_count": 2800, "city": "Levallois-Perret", "postal": "92300", "address": "54 quai Charles Pasqua", "domain": "doctolib.fr",
         "contacts": [{"first_name": "Julien", "last_name": "Garcia", "position": "Talent acquisition", "email": "j.garcia@doctolib.fr"}]},
        {"legal_name": "Thales SA", "commercial_name": "Thales", "siren": "552059024", "sector": "private", "naf": "2630Z", "employees_count": 81000, "city": "Meudon", "postal": "92190", "address": "Tour Carpe Diem, 31 place des Corolles", "domain": "thalesgroup.com",
         "contacts": [{"first_name": "Élise", "last_name": "Faure", "position": "Chargée de recrutement", "email": "e.faure@thalesgroup.com"}]},
        # --- Industrie ---
        {"legal_name": "Schneider Electric SE", "commercial_name": "Schneider Electric", "siren": "542048574", "sector": "private", "naf": "2712Z", "employees_count": 150000, "city": "Rueil-Malmaison", "postal": "92500", "address": "35 rue Joseph Monier", "domain": "se.com",
         "contacts": [{"first_name": "Antoine", "last_name": "Rousseau", "position": "Responsable apprentissage", "email": "a.rousseau@se.com"}]},
        {"legal_name": "Airbus SE", "commercial_name": "Airbus", "siren": "383474814", "sector": "private", "naf": "3030Z", "employees_count": 134000, "city": "Blagnac", "postal": "31700", "address": "1 rond-point Maurice Bellonte", "domain": "airbus.com",
         "contacts": [{"first_name": "Catherine", "last_name": "Martin", "position": "Responsable alternance", "email": "c.martin@airbus.com"}]},
        {"legal_name": "Saint-Gobain SA", "commercial_name": "Saint-Gobain", "siren": "542039532", "sector": "private", "naf": "2311Z", "employees_count": 160000, "city": "Courbevoie", "postal": "92400", "address": "Tour Saint-Gobain, 12 place de l'Iris", "domain": "saint-gobain.com",
         "contacts": [{"first_name": "François", "last_name": "Lemaire", "position": "DRH adjoint", "email": "f.lemaire@saint-gobain.com"}]},
        {"legal_name": "Michelin SCA", "commercial_name": "Michelin", "siren": "855200507", "sector": "private", "naf": "2211Z", "employees_count": 132000, "city": "Clermont-Ferrand", "postal": "63000", "address": "23 place des Carmes-Déchaux", "domain": "michelin.com",
         "contacts": [{"first_name": "Anne", "last_name": "Dupuis", "position": "Gestionnaire RH", "email": "a.dupuis@michelin.com"}]},
        # --- Banque / Assurance ---
        {"legal_name": "BNP Paribas SA", "commercial_name": "BNP Paribas", "siren": "662042449", "sector": "private", "naf": "6419Z", "employees_count": 190000, "city": "Paris", "postal": "75009", "address": "16 boulevard des Italiens", "domain": "bnpparibas.com",
         "contacts": [{"first_name": "Marie", "last_name": "Leroy", "position": "Responsable stage", "email": "m.leroy@bnpparibas.com"}]},
        {"legal_name": "AXA SA", "commercial_name": "AXA", "siren": "572093920", "sector": "private", "naf": "6512Z", "employees_count": 145000, "city": "Paris", "postal": "75008", "address": "25 avenue Matignon", "domain": "axa.com",
         "contacts": [{"first_name": "Thomas", "last_name": "Robert", "position": "Talent manager", "email": "t.robert@axa.com"}]},
        {"legal_name": "Société Générale SA", "commercial_name": "Société Générale", "siren": "552120222", "sector": "private", "naf": "6419Z", "employees_count": 117000, "city": "Paris", "postal": "75009", "address": "29 boulevard Haussmann", "domain": "socgen.com",
         "contacts": [{"first_name": "Camille", "last_name": "Vincent", "position": "Campus manager", "email": "c.vincent@socgen.com"}]},
        # --- Santé / Pharma ---
        {"legal_name": "Sanofi SA", "commercial_name": "Sanofi", "siren": "395030844", "sector": "private", "naf": "2120Z", "employees_count": 91000, "city": "Paris", "postal": "75008", "address": "54 rue La Boétie", "domain": "sanofi.com",
         "contacts": [{"first_name": "Isabelle", "last_name": "Girard", "position": "Responsable alternance pharma", "email": "i.girard@sanofi.com"}]},
        {"legal_name": "bioMérieux SA", "commercial_name": "bioMérieux", "siren": "673620399", "sector": "private", "naf": "2660Z", "employees_count": 14000, "city": "Marcy-l'Étoile", "postal": "69280", "address": "376 chemin de l'Orme", "domain": "biomerieux.com",
         "contacts": [{"first_name": "Laurent", "last_name": "Blanc", "position": "Directeur R&D", "email": "l.blanc@biomerieux.com"}]},
        # --- Commerce / Luxe ---
        {"legal_name": "LVMH Moët Hennessy Louis Vuitton SE", "commercial_name": "LVMH", "siren": "775670417", "sector": "private", "naf": "7010Z", "employees_count": 213000, "city": "Paris", "postal": "75008", "address": "22 avenue Montaigne", "domain": "lvmh.com",
         "contacts": [{"first_name": "Diane", "last_name": "Marchand", "position": "Talent acquisition luxe", "email": "d.marchand@lvmh.com"}]},
        {"legal_name": "L'Oréal SA", "commercial_name": "L'Oréal", "siren": "632012100", "sector": "private", "naf": "2042Z", "employees_count": 88000, "city": "Clichy", "postal": "92110", "address": "41 rue Martre", "domain": "loreal.com",
         "contacts": [{"first_name": "Émilie", "last_name": "Fournier", "position": "Responsable RH campus", "email": "e.fournier@loreal.com"}]},
        {"legal_name": "Decathlon SA", "commercial_name": "Decathlon", "siren": "500569405", "sector": "private", "naf": "4764Z", "employees_count": 100000, "city": "Villeneuve-d'Ascq", "postal": "59650", "address": "4 boulevard de Mons", "domain": "decathlon.com",
         "contacts": [{"first_name": "Romain", "last_name": "Mercier", "position": "Recruteur alternance", "email": "r.mercier@decathlon.com"}]},
        # --- Énergie ---
        {"legal_name": "TotalEnergies SE", "commercial_name": "TotalEnergies", "siren": "542051180", "sector": "private", "naf": "0610Z", "employees_count": 101000, "city": "Courbevoie", "postal": "92400", "address": "Tour TotalEnergies, 2 place Jean Millier", "domain": "totalenergies.com",
         "contacts": [{"first_name": "Nicolas", "last_name": "Dubois", "position": "Responsable alternance", "email": "n.dubois@totalenergies.com"}]},
        {"legal_name": "EDF SA", "commercial_name": "EDF", "siren": "552081317", "sector": "public", "naf": "3511Z", "employees_count": 167000, "city": "Paris", "postal": "75008", "address": "22-30 avenue de Wagram", "domain": "edf.fr",
         "contacts": [{"first_name": "Valérie", "last_name": "Simon", "position": "Chargée de mission apprentissage", "email": "v.simon@edf.fr"}]},
        # --- Startups / PME ---
        {"legal_name": "Alan SAS", "commercial_name": "Alan", "siren": "817882021", "sector": "private", "naf": "6512Z", "employees_count": 600, "city": "Paris", "postal": "75002", "address": "12 rue du Quatre-Septembre", "domain": "alan.com",
         "contacts": [{"first_name": "Hugo", "last_name": "Bonnet", "position": "People partner", "email": "h.bonnet@alan.com"}]},
        {"legal_name": "Qonto SAS", "commercial_name": "Qonto", "siren": "819489498", "sector": "private", "naf": "6419Z", "employees_count": 1400, "city": "Paris", "postal": "75002", "address": "18 rue de Navarin", "domain": "qonto.com",
         "contacts": [{"first_name": "Sarah", "last_name": "Lambert", "position": "Talent acquisition", "email": "s.lambert@qonto.com"}]},
        {"legal_name": "ManoMano SAS", "commercial_name": "ManoMano", "siren": "792576315", "sector": "private", "naf": "4791A", "employees_count": 800, "city": "Paris", "postal": "75010", "address": "38 rue de Paradis", "domain": "manomano.fr",
         "contacts": [{"first_name": "Mathieu", "last_name": "Perrin", "position": "Responsable recrutement", "email": "m.perrin@manomano.fr"}]},
        # --- Public ---
        {"legal_name": "Assistance Publique — Hôpitaux de Paris", "commercial_name": "AP-HP", "siren": "267500452", "sector": "public", "naf": "8610Z", "employees_count": 100000, "city": "Paris", "postal": "75004", "address": "3-9 avenue Victoria", "domain": "aphp.fr",
         "contacts": [{"first_name": "Christine", "last_name": "Morel", "position": "Directrice des stages", "email": "c.morel@aphp.fr"}]},
        {"legal_name": "CNRS", "commercial_name": "CNRS", "siren": "180089013", "sector": "public", "naf": "7219Z", "employees_count": 33000, "city": "Paris", "postal": "75016", "address": "3 rue Michel-Ange", "domain": "cnrs.fr",
         "contacts": [{"first_name": "Philippe", "last_name": "André", "position": "Responsable accueil chercheurs", "email": "p.andre@cnrs.fr"}]},
        {"legal_name": "INRIA", "commercial_name": "Inria", "siren": "180089021", "sector": "public", "naf": "7219Z", "employees_count": 3800, "city": "Le Chesnay-Rocquencourt", "postal": "78150", "address": "Domaine de Voluceau", "domain": "inria.fr",
         "contacts": [{"first_name": "Cécile", "last_name": "Henry", "position": "Responsable stage recherche", "email": "c.henry@inria.fr"}]},
        # --- Conseil / Audit ---
        {"legal_name": "McKinsey & Company France SAS", "commercial_name": "McKinsey", "siren": "722007405", "sector": "private", "naf": "7022Z", "employees_count": 1500, "city": "Paris", "postal": "75008", "address": "112 avenue Kléber", "domain": "mckinsey.com",
         "contacts": [{"first_name": "Olivier", "last_name": "Masson", "position": "Recruiting manager", "email": "o.masson@mckinsey.com"}]},
        {"legal_name": "Accenture SAS", "commercial_name": "Accenture", "siren": "732829296", "sector": "private", "naf": "6202A", "employees_count": 9000, "city": "Paris", "postal": "75008", "address": "118 avenue de France", "domain": "accenture.com",
         "contacts": [{"first_name": "Aurélie", "last_name": "Chevalier", "position": "Campus recruiter", "email": "a.chevalier@accenture.com"}]},
        # --- Transport ---
        {"legal_name": "SNCF SA", "commercial_name": "SNCF", "siren": "552049447", "sector": "public", "naf": "4910Z", "employees_count": 211000, "city": "Saint-Denis", "postal": "93200", "address": "2 place aux Étoiles", "domain": "sncf.com",
         "contacts": [{"first_name": "David", "last_name": "Roux", "position": "Responsable alternance", "email": "d.roux@sncf.com"}]},
        {"legal_name": "Renault Group SA", "commercial_name": "Renault", "siren": "441639465", "sector": "private", "naf": "2910Z", "employees_count": 105000, "city": "Boulogne-Billancourt", "postal": "92100", "address": "122-122 bis avenue du Général Leclerc", "domain": "renaultgroup.com",
         "contacts": [{"first_name": "Stéphane", "last_name": "Lemoine", "position": "Ingénieur tuteur", "email": "s.lemoine@renault.com"}]},
    ],
    "poudlard": [
        # --- Banque ---
        {"legal_name": "Banque Gringotts — Établissement Gobelin", "commercial_name": "Gringotts", "siren": "900000001", "sector": "private", "naf": "6419Z", "employees_count": 500,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "South Side, Chemin de Traverse", "domain": "gringotts.wiz",
         "contacts": [{"first_name": "Gripsec", "last_name": "Gobelin", "position": "Directeur de coffre", "email": "gripsec@gringotts.wiz"},
                      {"first_name": "Ragnok", "last_name": "Gobelin", "position": "Gérant principal", "email": "ragnok@gringotts.wiz"}]},
        # --- Presse ---
        {"legal_name": "La Gazette du Sorcier SARL", "commercial_name": "Gazette du Sorcier", "siren": "900000002", "sector": "private", "naf": "5813Z", "employees_count": 120,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "Diagon Alley, Bureau 7", "domain": "gazette-sorcier.wiz",
         "contacts": [{"first_name": "Rita", "last_name": "Skeeter", "position": "Journaliste senior", "email": "r.skeeter@gazette-sorcier.wiz"},
                      {"first_name": "Barnabas", "last_name": "Cuffe", "position": "Rédacteur en chef", "email": "b.cuffe@gazette-sorcier.wiz"}]},
        # --- Commerce ---
        {"legal_name": "Honeydukes SARL", "commercial_name": "Honeydukes", "siren": "900000003", "sector": "private", "naf": "1082Z", "employees_count": 25,
         "city": "Pré-au-Lard", "postal": "HGS01", "address": "High Street, Pré-au-Lard", "domain": "honeydukes.wiz",
         "contacts": [{"first_name": "Ambrosius", "last_name": "Flume", "position": "Gérant", "email": "a.flume@honeydukes.wiz"}]},
        {"legal_name": "Zonko — Farces pour Sorciers Facétieux", "commercial_name": "Zonko", "siren": "900000004", "sector": "private", "naf": "3240Z", "employees_count": 15,
         "city": "Pré-au-Lard", "postal": "HGS01", "address": "High Street, Pré-au-Lard", "domain": "zonko.wiz",
         "contacts": [{"first_name": "Bilton", "last_name": "Bilmes", "position": "Directeur commercial", "email": "b.bilmes@zonko.wiz"}]},
        {"legal_name": "Weasley, Farces pour Sorciers Facétieux", "commercial_name": "Weasley Farces", "siren": "900000005", "sector": "private", "naf": "3240Z", "employees_count": 8,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "93 Chemin de Traverse", "domain": "weasley-farces.wiz",
         "contacts": [{"first_name": "Fred", "last_name": "Weasley", "position": "Co-fondateur", "email": "fred@weasley-farces.wiz"},
                      {"first_name": "George", "last_name": "Weasley", "position": "Co-fondateur", "email": "george@weasley-farces.wiz"}]},
        # --- Artisanat magique ---
        {"legal_name": "Ollivander — Fabricants de Baguettes Magiques", "commercial_name": "Ollivander", "siren": "900000006", "sector": "private", "naf": "3212Z", "employees_count": 3,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "South Side, Chemin de Traverse", "domain": "ollivander.wiz",
         "contacts": [{"first_name": "Garrick", "last_name": "Ollivander", "position": "Maître artisan", "email": "g.ollivander@ollivander.wiz"}]},
        {"legal_name": "Fleury et Bott — Librairie Magique", "commercial_name": "Fleury et Bott", "siren": "900000007", "sector": "private", "naf": "4761Z", "employees_count": 12,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "Chemin de Traverse", "domain": "fleury-bott.wiz",
         "contacts": [{"first_name": "Obscurus", "last_name": "Bott", "position": "Libraire", "email": "o.bott@fleury-bott.wiz"}]},
        # --- Sport ---
        {"legal_name": "Nimbus Racing Broom Company", "commercial_name": "Nimbus Racing", "siren": "900000008", "sector": "private", "naf": "3230Z", "employees_count": 200,
         "city": "Londres", "postal": "EC4M7", "address": "Usine de balais, quartier sorcier", "domain": "nimbus-racing.wiz",
         "contacts": [{"first_name": "Devlin", "last_name": "Whitehorn", "position": "Directeur technique", "email": "d.whitehorn@nimbus-racing.wiz"}]},
        {"legal_name": "Quality Quidditch Supplies Ltd", "commercial_name": "Quality Quidditch Supplies", "siren": "900000009", "sector": "private", "naf": "4763Z", "employees_count": 30,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "Chemin de Traverse", "domain": "qq-supplies.wiz",
         "contacts": [{"first_name": "Alicia", "last_name": "Cromwell", "position": "Responsable boutique", "email": "a.cromwell@qq-supplies.wiz"}]},
        # --- Public ---
        {"legal_name": "Ministère de la Magie", "commercial_name": "Ministère de la Magie", "siren": "900000010", "sector": "public", "naf": "8411Z", "employees_count": 5000,
         "city": "Londres", "postal": "SW1A1", "address": "Whitehall, entrée visiteurs (cabine téléphonique)", "domain": "ministere-magie.gouv.wiz",
         "contacts": [{"first_name": "Kingsley", "last_name": "Shacklebolt", "position": "Ministre de la Magie", "email": "k.shacklebolt@ministere-magie.gouv.wiz"},
                      {"first_name": "Arthur", "last_name": "Weasley", "position": "Directeur détournement objets moldus", "email": "a.weasley@ministere-magie.gouv.wiz"}]},
        # --- Santé ---
        {"legal_name": "Hôpital Ste Mangouste pour les Maladies et Blessures Magiques", "commercial_name": "Ste Mangouste", "siren": "900000011", "sector": "public", "naf": "8610Z", "employees_count": 800,
         "city": "Londres", "postal": "EC4M7", "address": "Purge & Pionce Ltd (façade)", "domain": "ste-mangouste.wiz",
         "contacts": [{"first_name": "Hippocrate", "last_name": "Smethwyck", "position": "Guérisseur en chef", "email": "h.smethwyck@ste-mangouste.wiz"}]},
        # --- Mode ---
        {"legal_name": "Mme Guipure — Prêt-à-Porter pour Mages", "commercial_name": "Mme Guipure", "siren": "900000012", "sector": "private", "naf": "1413Z", "employees_count": 10,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "Chemin de Traverse", "domain": "guipure.wiz",
         "contacts": [{"first_name": "Madame", "last_name": "Guipure", "position": "Propriétaire", "email": "mme.guipure@guipure.wiz"}]},
        # --- Potion / Apothicaire ---
        {"legal_name": "Slug & Jiggers — Apothicaire", "commercial_name": "Slug & Jiggers", "siren": "900000013", "sector": "private", "naf": "4773Z", "employees_count": 6,
         "city": "Chemin de Traverse", "postal": "WC2H7", "address": "Chemin de Traverse", "domain": "slug-jiggers.wiz",
         "contacts": [{"first_name": "Arsenius", "last_name": "Jigger", "position": "Maître apothicaire", "email": "a.jigger@slug-jiggers.wiz"}]},
        # --- Transport ---
        {"legal_name": "Poudlard Express — Réseau Ferroviaire Magique", "commercial_name": "Poudlard Express", "siren": "900000014", "sector": "public", "naf": "4910Z", "employees_count": 50,
         "city": "Londres", "postal": "N1C4", "address": "King's Cross, Voie 9¾", "domain": "poudlard-express.wiz",
         "contacts": [{"first_name": "Stanley", "last_name": "Rocade", "position": "Conducteur en chef", "email": "s.rocade@poudlard-express.wiz"}]},
        # --- Pub ---
        {"legal_name": "Le Chaudron Baveur SARL", "commercial_name": "Chaudron Baveur", "siren": "900000015", "sector": "private", "naf": "5610A", "employees_count": 5,
         "city": "Londres", "postal": "WC2H7", "address": "Charing Cross Road", "domain": "chaudron-baveur.wiz",
         "contacts": [{"first_name": "Tom", "last_name": "Barman", "position": "Gérant", "email": "tom@chaudron-baveur.wiz"}]},
    ],
}


# ============================================================================
# Helpers pour la génération de config
# ============================================================================

def _generate_rooms_for_config(theme, rooms_per_campus, capacity_range, campus_idx=0):
    """
    Génère la liste de salles pour un campus dans la config.
    Utilise ROOM_POOLS et ROOM_FAMOUS_NAMES pour produire des noms réalistes.
    Retourne une liste de {"name": ..., "capacity": ...}.
    """
    pool = ROOM_POOLS.get(theme, ROOM_POOLS["sciences"])
    names = ROOM_FAMOUS_NAMES.get(theme, ROOM_FAMOUS_NAMES["sciences"])

    rooms = []
    # Offset name counters by campus_idx to avoid duplicate names across campuses
    # Use campus_idx directly (not * rooms_per_campus) to avoid modulo collisions
    name_counters = {k: campus_idx for k in names}

    for i, (name_tpl, base_cap) in enumerate(pool):
        if i >= rooms_per_campus:
            break

        room_name = name_tpl
        for placeholder, name_list in names.items():
            if "{" + placeholder + "}" in room_name:
                idx = name_counters[placeholder] % len(name_list)
                room_name = room_name.replace("{" + placeholder + "}", name_list[idx])
                name_counters[placeholder] = idx + 1

        # Vary capacity by ±20% based on campus and room index
        variation = 1.0 + 0.2 * (((campus_idx * 7 + i * 3) % 5) - 2) / 2  # -20% to +20%
        varied_cap = int(base_cap * variation)
        cap = min(max(varied_cap, capacity_range[0]), capacity_range[1])
        rooms.append({"name": room_name, "capacity": cap})

    return rooms


# ============================================================================
# Templates — Matières et sous-matières
# ============================================================================

SUBJECT_TEMPLATES = {
    "sciences": [
        {"name": "Mathématiques", "description": "Sciences mathématiques fondamentales et appliquées", "sub": [
            {"name": "Analyse", "description": "Analyse réelle et complexe, suites, séries, intégrales"},
            {"name": "Algèbre", "description": "Algèbre linéaire, structures algébriques"},
            {"name": "Probabilités et Statistiques", "description": "Calcul des probabilités, statistiques descriptives et inférentielles"},
            {"name": "Géométrie", "description": "Géométrie euclidienne, affine et projective"},
        ]},
        {"name": "Physique", "description": "Sciences physiques fondamentales et expérimentales", "sub": [
            {"name": "Mécanique", "description": "Mécanique du point, du solide et des fluides"},
            {"name": "Électromagnétisme", "description": "Électrostatique, magnétostatique, ondes EM"},
            {"name": "Thermodynamique", "description": "Principes de la thermodynamique, transferts thermiques"},
            {"name": "Optique", "description": "Optique géométrique et ondulatoire"},
        ]},
        {"name": "Chimie", "description": "Sciences chimiques fondamentales et appliquées", "sub": [
            {"name": "Chimie générale", "description": "Atomes, liaisons, réactions chimiques"},
            {"name": "Chimie organique", "description": "Composés du carbone, réactions organiques"},
            {"name": "Chimie analytique", "description": "Méthodes d'analyse et techniques de séparation"},
        ]},
        {"name": "Informatique", "description": "Sciences du numérique et de l'information", "sub": [
            {"name": "Algorithmique et Programmation", "description": "Conception d'algorithmes, langages de programmation"},
            {"name": "Systèmes et Réseaux", "description": "Architecture des systèmes, protocoles réseau"},
            {"name": "Bases de données", "description": "Modélisation, SQL, systèmes de gestion"},
            {"name": "Développement Web", "description": "Technologies web, front-end et back-end"},
        ]},
        {"name": "Sciences de la vie", "description": "Biologie et sciences du vivant", "sub": [
            {"name": "Biologie cellulaire", "description": "Structure et fonction des cellules"},
            {"name": "Biologie moléculaire", "description": "ADN, ARN, expression génétique"},
        ]},
        {"name": "Sciences de l'ingénieur", "description": "Sciences appliquées à l'ingénierie", "sub": [
            {"name": "Mécanique appliquée", "description": "Résistance des matériaux, dimensionnement"},
            {"name": "Électronique", "description": "Circuits analogiques et numériques"},
        ]},
    ],
    "arts": [
        {"name": "Histoire de l'art", "description": "Étude historique des mouvements et des œuvres artistiques", "sub": [
            {"name": "Art ancien et médiéval", "description": "De l'Antiquité au Moyen Âge"},
            {"name": "Art moderne", "description": "Du XIXe siècle aux avant-gardes"},
            {"name": "Art contemporain", "description": "Pratiques artistiques depuis 1945"},
        ]},
        {"name": "Arts plastiques", "description": "Pratiques artistiques visuelles et plastiques", "sub": [
            {"name": "Dessin", "description": "Observation, perspective, croquis"},
            {"name": "Peinture", "description": "Techniques picturales, couleur, composition"},
            {"name": "Sculpture et volume", "description": "Modelage, installation, art dans l'espace"},
        ]},
        {"name": "Arts visuels et médias", "description": "Pratiques artistiques numériques et médiatiques", "sub": [
            {"name": "Photographie", "description": "Techniques photo, composition, post-production"},
            {"name": "Vidéo et cinéma", "description": "Réalisation, montage, narration visuelle"},
            {"name": "Arts numériques", "description": "Création numérique, interactivité, IA"},
        ]},
        {"name": "Arts vivants", "description": "Spectacle vivant et performances", "sub": [
            {"name": "Théâtre et performance", "description": "Jeu dramatique, mise en scène"},
            {"name": "Danse", "description": "Techniques corporelles, chorégraphie"},
        ]},
    ],
    "droit": [
        {"name": "Droit civil", "description": "Droit des personnes, des biens et des obligations", "sub": [
            {"name": "Droit des obligations", "description": "Contrats, responsabilité civile"},
            {"name": "Droit des personnes", "description": "État civil, capacité, filiation"},
            {"name": "Droit des biens", "description": "Propriété, droits réels"},
        ]},
        {"name": "Droit public", "description": "Droit constitutionnel, administratif et international", "sub": [
            {"name": "Droit constitutionnel", "description": "Constitution, institutions, libertés"},
            {"name": "Droit administratif", "description": "Administration, actes, contentieux"},
        ]},
        {"name": "Droit pénal", "description": "Infractions, procédure pénale et sanctions", "sub": [
            {"name": "Droit pénal général", "description": "Théorie de l'infraction, responsabilité pénale"},
            {"name": "Procédure pénale", "description": "Enquête, instruction, jugement"},
        ]},
        {"name": "Sciences politiques", "description": "Analyse des systèmes et des acteurs politiques", "sub": [
            {"name": "Institutions politiques", "description": "Régimes, partis, élections"},
            {"name": "Relations internationales", "description": "Géopolitique, diplomatie, organisations"},
        ]},
    ],
    "sante": [
        {"name": "Sciences fondamentales", "description": "Bases scientifiques de la médecine et de la santé", "sub": [
            {"name": "Anatomie", "description": "Structure du corps humain"},
            {"name": "Physiologie", "description": "Fonctionnement des organes et systèmes"},
            {"name": "Biochimie", "description": "Métabolisme, enzymologie, biologie moléculaire"},
        ]},
        {"name": "Sciences cliniques", "description": "Pratique médicale et soins", "sub": [
            {"name": "Sémiologie", "description": "Signes cliniques, diagnostic"},
            {"name": "Thérapeutique", "description": "Traitements, protocoles de soins"},
        ]},
        {"name": "Pharmacologie", "description": "Sciences du médicament", "sub": [
            {"name": "Pharmacologie générale", "description": "Mécanismes d'action, pharmacocinétique"},
            {"name": "Pharmacie galénique", "description": "Formulation, fabrication des médicaments"},
        ]},
        {"name": "Santé publique", "description": "Prévention, épidémiologie et organisation des soins", "sub": [
            {"name": "Épidémiologie", "description": "Études de population, biostatistiques"},
            {"name": "Organisation des soins", "description": "Systèmes de santé, politiques sanitaires"},
        ]},
    ],
    "ingenierie": [
        {"name": "Mathématiques appliquées", "description": "Outils mathématiques pour l'ingénieur", "sub": [
            {"name": "Analyse numérique", "description": "Méthodes numériques, approximation"},
            {"name": "Optimisation", "description": "Programmation linéaire, algorithmes d'optimisation"},
        ]},
        {"name": "Sciences de l'ingénieur", "description": "Fondamentaux de l'ingénierie", "sub": [
            {"name": "Mécanique des structures", "description": "Résistance des matériaux, éléments finis"},
            {"name": "Thermique et énergétique", "description": "Transferts thermiques, conversion d'énergie"},
            {"name": "Matériaux", "description": "Propriétés, mise en œuvre, choix des matériaux"},
        ]},
        {"name": "Génie électrique", "description": "Électrotechnique et automatisme", "sub": [
            {"name": "Électrotechnique", "description": "Machines électriques, convertisseurs"},
            {"name": "Automatique", "description": "Systèmes asservis, régulation"},
        ]},
        {"name": "Informatique industrielle", "description": "Systèmes embarqués et informatique temps réel", "sub": [
            {"name": "Systèmes embarqués", "description": "Microcontrôleurs, programmation bas niveau"},
            {"name": "Informatique temps réel", "description": "Ordonnancement, systèmes critiques"},
        ]},
    ],
    "poudlard": [
        {"name": "Sortilèges et Enchantements", "description": "Étude et pratique des sortilèges, enchantements et charmes", "sub": [
            {"name": "Sortilèges fondamentaux", "description": "Lumos, Expelliarmus, Accio, sortilèges de base"},
            {"name": "Enchantements avancés", "description": "Enchantements complexes, contresorts, protections"},
            {"name": "Magie informulée", "description": "Pratique de la magie sans incantation verbale"},
        ]},
        {"name": "Potions", "description": "Art du brassage, élixirs, antidotes et poisons", "sub": [
            {"name": "Potions élémentaires", "description": "Potions de soin, de sommeil, antidotes courants"},
            {"name": "Potions avancées", "description": "Polynectar, Veritaserum, Felix Felicis"},
            {"name": "Ingrédients et préparation", "description": "Reconnaissance et préparation des ingrédients"},
        ]},
        {"name": "Métamorphose", "description": "Transformation d'objets et de créatures vivantes", "sub": [
            {"name": "Métamorphose élémentaire", "description": "Transformation d'objets inanimés"},
            {"name": "Métamorphose avancée", "description": "Transformation humaine, Animagus"},
        ]},
        {"name": "Défense contre les Forces du Mal", "description": "Protection contre les créatures et la magie noire", "sub": [
            {"name": "Créatures des ténèbres", "description": "Détraqueurs, loups-garous, épouvantards"},
            {"name": "Contre-maléfices", "description": "Défense contre les sorts de magie noire"},
            {"name": "Duels magiques", "description": "Techniques de combat magique défensif"},
        ]},
        {"name": "Botanique magique", "description": "Étude et soin des plantes magiques", "sub": [
            {"name": "Plantes dangereuses", "description": "Mandragore, Filet du Diable, Tentacula"},
            {"name": "Herbologie appliquée", "description": "Propriétés médicinales et ingrédients de potions"},
        ]},
        {"name": "Soins aux Créatures Magiques", "description": "Approche et soin des créatures magiques", "sub": [
            {"name": "Créatures classifiées", "description": "Hippogriffes, Sombrals, Niffleurs"},
            {"name": "Élevage et conservation", "description": "Protection des espèces magiques menacées"},
        ]},
        {"name": "Vol et Quidditch", "description": "Maîtrise du vol sur balai et sports magiques aériens", "sub": [
            {"name": "Technique de vol", "description": "Décollage, manœuvres, vol acrobatique"},
            {"name": "Quidditch — Postes et tactiques", "description": "Attrapeur, Poursuiveur, Gardien, Batteur"},
            {"name": "Sports magiques", "description": "Courses de balais, duels sportifs, tournois"},
        ]},
        {"name": "Runes et Arithmancie", "description": "Étude des runes anciennes et des sciences numériques magiques", "sub": [
            {"name": "Runes anciennes", "description": "Déchiffrage et traduction de textes runiques"},
            {"name": "Arithmancie", "description": "Numérologie magique et prédictions arithmantiques"},
        ]},
        {"name": "Études avancées", "description": "Recherche magique et spécialisations du Ministère", "sub": [
            {"name": "Formation d'Auror", "description": "Filature, combat, droit magique pénal"},
            {"name": "Médicomagie", "description": "Diagnostic, guérison des maléfices, Ste Mangouste"},
            {"name": "Étude des Moldus", "description": "Technologie, société et intégration moldue"},
        ]},
    ],
}

# Matières transversales (ajoutées à tous les thèmes)
SUBJECT_TRANSVERSAL = [
    {"name": "Langues", "description": "Langues vivantes et communication internationale", "sub": [
        {"name": "Anglais", "description": "Anglais général et de spécialité"},
        {"name": "Français / Expression écrite", "description": "Rédaction, argumentation, synthèse"},
    ]},
    {"name": "Sciences humaines et sociales", "description": "Approches transversales en SHS", "sub": [
        {"name": "Philosophie et épistémologie", "description": "Réflexion critique, histoire des sciences"},
        {"name": "Sociologie", "description": "Analyse des phénomènes sociaux"},
    ]},
    {"name": "Méthodologie et recherche", "description": "Outils méthodologiques et initiation à la recherche", "sub": [
        {"name": "Méthodologie universitaire", "description": "Prise de notes, dissertation, exposé"},
        {"name": "Initiation à la recherche", "description": "Bibliographie, démarche expérimentale"},
    ]},
    {"name": "Professionnalisation", "description": "Insertion professionnelle et compétences transversales", "sub": [
        {"name": "Projet professionnel", "description": "CV, lettre de motivation, entretien"},
        {"name": "Gestion de projet", "description": "Planification, travail en équipe, outils"},
    ]},
]


# ============================================================================
# Templates — Types de documents
# ============================================================================

DOCUMENT_TYPE_TEMPLATES = [
    # Pédagogie
    {"name": "Support de cours", "description": "Supports pédagogiques diffusés aux étudiants (slides, polycopiés, notes de cours)",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 1},
    {"name": "Sujet d'examen", "description": "Sujets d'examens et épreuves de contrôle continu",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 2},
    {"name": "Corrigé", "description": "Corrigés d'examens et de travaux dirigés",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 3},
    {"name": "Fiche de TD/TP", "description": "Fiches de travaux dirigés et travaux pratiques",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 4},
    {"name": "Syllabus", "description": "Programme détaillé du cours, objectifs, bibliographie et modalités d'évaluation",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 1, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 5},
    {"name": "Grille d'évaluation", "description": "Critères et barèmes de notation",
     "authz_for_students": 0, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "pedagogy_module": True}, "order": 6},
    {"name": "Feuille d'émargement", "description": "Feuilles de présence à signer par les étudiants",
     "authz_for_students": 0, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True}, "order": 7},
    # Administratif / secrétariat
    {"name": "Règlement intérieur", "description": "Règlement intérieur de l'établissement",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 1, "download_only": 0,
     "libraries": {"secretariat": True, "student": True}, "order": 8},
    {"name": "Courrier administratif", "description": "Courriers officiels (attestations, certificats, convocations)",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"secretariat": True, "student": True}, "order": 9},
    {"name": "PV de jury", "description": "Procès-verbaux des jurys d'examen et de délibération",
     "authz_for_students": 0, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"secretariat": True}, "order": 10},
    # Marketing
    {"name": "Brochure de formation", "description": "Plaquettes et brochures de présentation des formations",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 1, "download_only": 0,
     "libraries": {"marketing": True, "student": True}, "order": 11},
    {"name": "Dossier de candidature", "description": "Documents pour les candidatures (formulaires, pièces justificatives)",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"marketing": True, "student": True}, "order": 12},
    # Comptabilité
    {"name": "Facture", "description": "Factures et relevés de compte",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"accounting": True, "student": True}, "order": 13},
    {"name": "Avoir", "description": "Avoirs et notes de crédit",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"accounting": True, "student": True}, "order": 14},
    {"name": "Bon de commande", "description": "Bons de commande pour achats et fournitures",
     "authz_for_students": 0, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"accounting": True}, "order": 15},
    # Interne
    {"name": "Note interne", "description": "Communications internes et notes de service",
     "authz_for_students": 0, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"secretariat": True}, "order": 16},
    # Ressources pédagogiques complémentaires
    {"name": "Vidéo de cours", "description": "Enregistrements vidéo de cours et conférences",
     "authz_for_students": 1, "authz_for_print": 0, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 17},
    {"name": "Fiche de cours", "description": "Fiches de révision et résumés de cours",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 18},
    {"name": "Exercice", "description": "Exercices d'entraînement avec ou sans corrigé",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 19},
    {"name": "Annale d'examen", "description": "Sujets d'examens des années précédentes",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 20},
    {"name": "Bibliographie", "description": "Listes de références bibliographiques recommandées",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 21},
    {"name": "Tutoriel", "description": "Guides pratiques et tutoriels pas-à-pas",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 22},
    {"name": "Podcast / Audio", "description": "Enregistrements audio pédagogiques",
     "authz_for_students": 1, "authz_for_print": 0, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 23},
    {"name": "Consigne de projet", "description": "Cahiers des charges et consignes de projets étudiants",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 24},
    {"name": "Ressource complémentaire", "description": "Tout autre document pédagogique complémentaire",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "pedagogy_module": True, "pedagogy_module_student": True}, "order": 25},
    {"name": "Guide de stage", "description": "Conventions, objectifs et évaluations de stage",
     "authz_for_students": 1, "authz_for_print": 1, "authz_for_external_share": 0, "download_only": 0,
     "libraries": {"pedagogy": True, "student": True, "secretariat": True}, "order": 26},
]


# ============================================================================
# Générateur de configuration par défaut
# ============================================================================

def generate_default_config(
    n_schools=2,
    campuses_per_school=2,
    campus_counts=None,
    themes=None,
    n_students=200,
    n_employees=20,
    n_companies=None,
    formation_hours_min=None,
    formation_hours_max=None,
    formulas_per_campus=None,
    avg_discounts=None,
    formations_per_formula=None,
    n_centers=None,
    formation_indices=None,
    include_degrees=True,
    n_employers=10,
):
    """
    Génère une configuration par défaut.

    Parameters :
      n_schools: nombre d'écoles
      campuses_per_school: campus par école (int, appliqué à toutes) — ignoré si campus_counts fourni
      campus_counts: liste [nb_campus_école_1, nb_campus_école_2, ...] — prioritaire sur campuses_per_school
      themes: liste de thèmes par école
      n_students, n_employees, n_companies: population
      formation_hours_min/max: bornes de durée des formations (heures)
      formulas_per_campus: nombre max de formules par campus (limite les templates)
      avg_discounts: nombre moyen de remises par formule
      formations_per_formula: nombre de formations rattachées à chaque formule
      n_centers: nombre total de centres d'activité (assignés aléatoirement aux campus)
      formation_indices: liste d'indices de formations à inclure depuis les templates (None = toutes)
      include_degrees: si True, ajouter les diplômes aux formules (via DEGREE_TEMPLATES)
    """
    if themes is None:
        themes = ["sciences", "arts"]

    # Trim themes to n_schools
    school_themes = themes[:n_schools]

    # Déterminer l'année scolaire dynamiquement
    # Sept+ → année en cours – année suivante ; avant sept → année précédente – année en cours
    _today = _date.today()
    _ay_start = _today.year if _today.month >= 9 else _today.year - 1
    _ay_end = _ay_start + 1

    config = {
        "meta": {
            "academic_year": f"{_ay_start}-{_ay_end}",
            "random_seed": _ay_end,
            "version": 1,
        },
        "api": {
            "base_url": "",
            "key": "",
        },
        "schools": [],
        "campuses": [],
        "companies": [],
        "levels": [
            "CPGE", "Prépa", "DEUST",
            "BTS 1", "BTS 2",
            "BUT 1", "BUT 2", "BUT 3",
            "L1", "L2", "L3", "Licence Pro",
            "M1", "M2", "Mastère Spécialisé",
            "Diplôme d'Ingénieur",
            "D1", "D2", "D3",
        ],
        "centers": {
            "rooms_per_campus": 4,
            "capacity_range": [15, 120],
            "definitions": [],  # List of center defs, assigned to campuses
        },
        "formations": [],
        "formulas": [],
        "students": {
            "total": n_students,
            "by_school": {},
            "double_cursus": 0,
            "dataset": "standard",  # "standard" ou "poudlard"
        },
        "employees": {"total": n_employees, "dataset": "standard"},
        "employers": {"total": n_employers, "dataset": "standard"},
        "enrollments": {"final_pct": 65, "discount_pct": 30},
        "scores": {"mean": 1200, "std": 300, "absent_rate_pct": 3},
        "absences": {"absence_rate_pct": 8, "delay_rate_pct": 5, "justify_rate_pct": 60},
        "teaching_units": {"themes": {}},
    }

    # Effective n_companies
    _n_companies = n_companies if n_companies is not None else n_schools

    # --- Schools ---
    for i, theme in enumerate(school_themes):
        tpl = SCHOOL_TEMPLATES.get(theme, {"name": f"École {i+1}", "short": f"E{i+1}"})
        school_key = f"school_{i+1}"

        config["schools"].append({
            "key": school_key,
            "theme": theme,
            "name": tpl["name"],
            "short": tpl["short"],
        })

    # --- Companies (generated separately to support n_companies != n_schools) ---
    for ci in range(_n_companies):
        theme_for_company = school_themes[ci % len(school_themes)]
        comp_tpl = COMPANY_TEMPLATES.get(theme_for_company, {"name": f"Société {ci+1}", "short": f"S{ci+1}"})
        # Each company is linked to one or more schools
        if _n_companies <= n_schools:
            # Fewer companies than schools → group schools per company
            linked_keys = []
            for si in range(n_schools):
                if si % _n_companies == ci:
                    linked_keys.append(f"school_{si+1}")
        else:
            # More companies than schools → each maps to one school (cycling)
            linked_keys = [f"school_{(ci % n_schools) + 1}"]
        comp_name = comp_tpl["name"] if ci < len(school_themes) else f"Société {ci+1}"
        config["companies"].append({
            "key": f"company_{ci+1}",
            "name": comp_name,
            "school_keys": linked_keys,
        })

    # --- Per-school: Campuses, Centers, Formations, Formulas ---
    import random as _rng
    _rng.seed(config["meta"]["random_seed"])

    # Resolve campus counts per school
    if campus_counts and len(campus_counts) >= n_schools:
        _campus_counts = campus_counts[:n_schools]
    else:
        _campus_counts = [campuses_per_school] * n_schools

    rooms_per_campus = config["centers"]["rooms_per_campus"]
    capacity_range = config["centers"]["capacity_range"]

    # Collect all city pools across schools for center generation
    all_center_cities = []
    for i, theme in enumerate(school_themes):
        tpl = SCHOOL_TEMPLATES.get(theme, {"name": f"École {i+1}", "short": f"E{i+1}"})
        city_pool = CAMPUS_CITIES.get(theme, CAMPUS_CITIES["sciences"])
        for j, city in enumerate(city_pool):
            all_center_cities.append({"city": city, "theme": theme, "school_idx": i, "city_idx": j})

    # Determine how many centers to create
    total_campuses = sum(min(_campus_counts[si], len(CAMPUS_CITIES.get(t, CAMPUS_CITIES["sciences"]))) for si, t in enumerate(school_themes))
    effective_n_centers = n_centers if n_centers is not None else total_campuses

    # Build center definitions (pick from available cities, cycling if needed)
    center_defs = []
    for ci in range(effective_n_centers):
        src = all_center_cities[ci % len(all_center_cities)]
        city = src["city"]
        center_rooms = _generate_rooms_for_config(
            src["theme"], rooms_per_campus, capacity_range, campus_idx=ci,
        )
        hours_key = HOURS_ROTATION[ci % len(HOURS_ROTATION)]
        center_defs.append({
            "key": f"center_{ci+1}",
            "name": city["center_name"],
            "color": city["center_color"],
            "addr": city["addr"],
            "city": city["city"],
            "postal": city["postal"],
            "zone": city.get("zone", "C"),
            "hours_template": hours_key,
            "rooms": center_rooms,
        })
    config["centers"]["definitions"] = center_defs

    # Build campuses, then randomly assign centers
    for i, theme in enumerate(school_themes):
        tpl = SCHOOL_TEMPLATES.get(theme, {"name": f"École {i+1}", "short": f"E{i+1}"})
        school_key = f"school_{i+1}"

        city_pool = CAMPUS_CITIES.get(theme, CAMPUS_CITIES["sciences"])
        n_camp = min(_campus_counts[i], len(city_pool))

        for j in range(n_camp):
            city = city_pool[j]
            campus_name = city["name_tpl"].format(school_short=tpl["short"])

            config["campuses"].append({
                "key": f"campus_{i+1}_{j+1}",
                "school_key": school_key,
                "name": campus_name,
                "city": city["city"],
                "postal": city["postal"],
                "zone": city.get("zone", "C"),
            })

    # Assign centers to campuses randomly (each center → 1 campus, round-robin if more centers than campuses)
    campus_keys = [c["key"] for c in config["campuses"]]
    center_assignments = {}  # campus_key -> [center_keys]
    for ck in campus_keys:
        center_assignments[ck] = []
    for ci, cdef in enumerate(center_defs):
        target = campus_keys[ci % len(campus_keys)] if campus_keys else None
        if target:
            center_assignments[target].append(cdef["key"])
    # Shuffle assignments so it's not always sequential
    if len(center_defs) > len(campus_keys):
        extra = list(range(len(campus_keys), len(center_defs)))
        _rng.shuffle(extra)
        for idx, ci in enumerate(extra):
            target = campus_keys[idx % len(campus_keys)]
            # already assigned above via round-robin, shuffle just reorders
    # Store assignments in campus config
    for campus_cfg in config["campuses"]:
        campus_cfg["center_keys"] = center_assignments.get(campus_cfg["key"], [])

    for i, theme in enumerate(school_themes):
        tpl = SCHOOL_TEMPLATES.get(theme, {"name": f"École {i+1}", "short": f"E{i+1}"})
        school_key = f"school_{i+1}"

        # --- Formations ---
        fm_templates = FORMATION_TEMPLATES.get(theme, [])

        # Filter formations by indices if specified
        if formation_indices is not None:
            fm_templates_filtered = [(k, t) for k, t in enumerate(fm_templates) if k in formation_indices]
        else:
            fm_templates_filtered = list(enumerate(fm_templates))

        # Build mapping: original_index → new_index (for formula formation_indices remapping)
        _orig_to_new = {}
        for new_idx, (orig_idx, _) in enumerate(fm_templates_filtered):
            _orig_to_new[orig_idx] = new_idx

        for new_k, (orig_k, fm_tpl) in enumerate(fm_templates_filtered):
            fm_name = fm_tpl["name_tpl"].format(school_name=tpl["name"], school_short=tpl["short"])
            campus_keys = [c["key"] for c in config["campuses"] if c["school_key"] == school_key]
            # Primary campus for the first campus, or all for multi-campus formations
            if fm_tpl.get("primary"):
                fm_campuses = campus_keys  # big formations go to all campus
            else:
                fm_campuses = campus_keys[:1]  # smaller formations to primary campus

            # Clamp hours if min/max specified
            fm_hours = fm_tpl["hours"]
            if formation_hours_min is not None:
                fm_hours = max(fm_hours, formation_hours_min)
            if formation_hours_max is not None:
                fm_hours = min(fm_hours, formation_hours_max)

            config["formations"].append({
                "key": f"formation_{i+1}_{new_k+1}",
                "school_key": school_key,
                "name": fm_name,
                "campus_keys": fm_campuses,
                "hours": fm_hours,
                "theme": fm_tpl["theme"],
                "levels": fm_tpl["levels"],
                "capacity": fm_tpl["capacity"],
                "year_span": fm_tpl.get("year_span", 1),
            })

        # --- Formulas ---
        fml_templates_raw = FORMULA_TEMPLATES.get(theme, [])
        # Tag each template with its original index (for degree lookup)
        fml_templates = list(enumerate(fml_templates_raw))

        # Filter formulas by compatibility FIRST (before limiting count)
        if formation_indices is not None:
            fml_templates = [
                (orig_k, fml) for orig_k, fml in fml_templates
                if all(idx in _orig_to_new for idx in fml["formation_indices"])
            ]

        # Then limit formulas per school
        if formulas_per_campus is not None:
            fml_templates = fml_templates[:formulas_per_campus]

        for k, (orig_fml_k, fml_tpl) in enumerate(fml_templates):
            fml_name = fml_tpl["name_tpl"].format(school_name=tpl["name"], school_short=tpl["short"])

            # Map formation indices to formation keys (remap via _orig_to_new if filtering)
            school_formations = [f for f in config["formations"] if f["school_key"] == school_key]
            if formation_indices is not None:
                tpl_indices = [_orig_to_new[idx] for idx in fml_tpl["formation_indices"] if idx in _orig_to_new]
            else:
                tpl_indices = fml_tpl["formation_indices"]
            if formations_per_formula is not None:
                # Adjust: take first N formations (cycling if needed)
                adj_indices = []
                for fi in range(formations_per_formula):
                    idx = tpl_indices[fi % len(tpl_indices)] if tpl_indices else fi
                    if idx < len(school_formations) and idx not in adj_indices:
                        adj_indices.append(idx)
                tpl_indices = adj_indices if adj_indices else tpl_indices[:1]
            formation_keys = [school_formations[idx]["key"] for idx in tpl_indices if idx < len(school_formations)]

            # Find which company is linked to this school
            _company_key = f"company_{i+1}"  # default fallback
            for comp in config["companies"]:
                if school_key in comp["school_keys"]:
                    _company_key = comp["key"]
                    break

            fml = {
                "key": f"formula_{i+1}_{k+1}",
                "school_key": school_key,
                "company_key": _company_key,
                "name": fml_name,
                "levels": fml_tpl["levels"],
                "price_cents": fml_tpl["price_cents"],
                "year_span": fml_tpl.get("year_span", 1),
                "is_salable": fml_tpl.get("is_salable", True),
                "formation_keys": formation_keys,
                "steps": fml_tpl["steps"],
                "discounts": fml_tpl.get("discounts", [])[:avg_discounts] if avg_discounts is not None else fml_tpl.get("discounts", []),
                "charges": fml_tpl.get("charges", []),
                "schedules": fml_tpl.get("schedules", ["comptant"]),
            }

            # Optional formations
            if "optional_formation_indices" in fml_tpl:
                if formation_indices is not None:
                    opt_remapped = [_orig_to_new[idx] for idx in fml_tpl["optional_formation_indices"] if idx in _orig_to_new]
                else:
                    opt_remapped = fml_tpl["optional_formation_indices"]
                opt_keys = [school_formations[idx]["key"] for idx in opt_remapped if idx < len(school_formations)]
                if opt_keys:  # Only add optional if at least one optional formation exists
                    fml["optional_formation_keys"] = opt_keys
                    fml["option_min"] = fml_tpl.get("option_min", 1)
                    fml["option_max"] = min(fml_tpl.get("option_max", 2), len(opt_keys))

            # Degree (diplôme)
            if include_degrees:
                degree_tpls = DEGREE_TEMPLATES.get(theme, {})
                if orig_fml_k in degree_tpls:
                    fml["degree"] = copy.deepcopy(degree_tpls[orig_fml_k])

            config["formulas"].append(fml)

    # --- Students distribution ---
    n_per_school = n_students // n_schools
    remainder = n_students % n_schools
    double_cursus = int(n_students * 0.10) if n_schools >= 2 else 0

    for i, school in enumerate(config["schools"]):
        count = n_per_school + (1 if i < remainder else 0)
        if i == 0 and double_cursus > 0:
            count -= double_cursus  # Remove double cursus from first school's solo count
        config["students"]["by_school"][school["key"]] = count

    config["students"]["double_cursus"] = double_cursus

    # --- Teaching unit themes (only include themes that are used) ---
    used_themes = set()
    for fm in config["formations"]:
        used_themes.add(fm["theme"])
    for theme_key in used_themes:
        if theme_key in THEME_DEFINITIONS:
            config["teaching_units"]["themes"][theme_key] = copy.deepcopy(THEME_DEFINITIONS[theme_key])

    return config


# ============================================================================
# Main (for standalone testing)
# ============================================================================

if __name__ == "__main__":
    print("=== Génération de la config par défaut ===")
    config = generate_default_config()
    save_config(config)
    print(f"  {len(config['schools'])} écoles")
    print(f"  {len(config['campuses'])} campus")
    print(f"  {len(config['companies'])} sociétés")
    print(f"  {len(config['formations'])} formations")
    print(f"  {len(config['formulas'])} formules")
    print(f"  {config['students']['total']} étudiants")
    print(f"  Config → {CONFIG_PATH}")
    print()

    # Verify config
    config2 = load_config()
    print("=== Relecture OK ===")
    print(f"  Écoles : {[s['name'] for s in config2['schools']]}")
    print(f"  Thèmes UE : {list(config2['teaching_units']['themes'].keys())}")
