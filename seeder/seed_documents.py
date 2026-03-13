#!/usr/bin/env python3
"""
seed_documents.py — Upload de la mascotte Neil sur tous les modules de toutes les formations.

Pour chaque module de chaque formation (1 042 modules au total), crée un document
"Mascotte Neil" avec l'image de la chouette Neil via le workflow d'upload en 3 étapes :
  1. POST /formations/{fid}/modules/{mid}/documents → crée le document, récupère l'URL Blow
  2. POST {blow_url} avec le binaire de l'image → Blow écrit sur GCS + encode
  3. POST /files/{file_id}/encode/success × 2 avec le broadcast de Blow

Prérequis : l'image source doit être disponible (téléchargée depuis le storage proxy
ou présente en local dans /tmp/mascotte-neil.jpg).
"""

import requests
import json
import sys
import time

# ============================================================================
# Configuration
# ============================================================================

API = "https://neil-claude.erp.neil.app/api"
HEADERS = {
    "X-Lucius-Api-Key": "LoYrwWXSNbqY/PFKRv4l2rCV.X3YF1HYVqBVcNeaOQnMmN52EyhLXNmzKNNl1Z+7ViFN31AxZT+ja9RqED7SlQIww",
    "Content-Type": "application/json",
}

FORMATION_IDS = list(range(10, 19))

# Document configuration
DOC_NAME = "Mascotte Neil"
DOC_TYPE_ID = 33  # Support de cours (pedagogy_module)
ORIGINAL_FILENAME = "mascotte-neil.jpg"
MIME_TYPE = "image/jpeg"

# Image source — thumbnail from existing upload (doc 5, module 1321, formation 10)
IMAGE_URL = (
    "https://neil-claude.erp.neil.app/storage/public/neil-claude/"
    "pedagogy_module/2026/02/df497c26-cdf0-439b-86ed-2bab3c527131/"
    "broadcast/thumbnail.jpeg"
)
LOCAL_IMAGE_PATH = "/tmp/mascotte-neil.jpg"

# Module to skip (already has the mascot uploaded from UI)
SKIP_MODULES = {(10, 1321)}

# Rate limiting
DELAY_BETWEEN_MODULES = 0.15  # seconds
DELAY_BETWEEN_FORMATIONS = 1.0  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds

TRANSIENT_CODES = {429, 500, 502, 503, 504}

# URL rewriting: Blow returns gs:// URLs, API expects https:// storage proxy URLs
GCS_REWRITES = [
    ("gs://tenants-assets.lucius-prod.neil.app/", "https://neil-claude.erp.neil.app/storage/public/"),
    ("gs://documents.lucius-prod.neil.app/", "https://neil-claude.erp.neil.app/storage/broadcast/"),
]


def rewrite_broadcast_urls(broadcast):
    """Rewrite gs:// URLs in Blow's broadcast response to https:// storage proxy URLs.
    The API only persists the broadcast if thumbnail/files URLs use https://.
    """
    s = json.dumps(broadcast)
    for gcs_prefix, https_prefix in GCS_REWRITES:
        s = s.replace(gcs_prefix, https_prefix)
    return json.loads(s)


# ============================================================================
# Image acquisition
# ============================================================================

def download_source_image():
    """Download the mascot image. Try local file first, then storage proxy."""
    # Try local file
    try:
        with open(LOCAL_IMAGE_PATH, "rb") as f:
            data = f.read()
        if len(data) > 1000:
            return data
    except FileNotFoundError:
        pass

    # Download from storage proxy
    print("  Téléchargement depuis le storage proxy...")
    try:
        r = requests.get(IMAGE_URL, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            # Cache locally
            with open(LOCAL_IMAGE_PATH, "wb") as f:
                f.write(r.content)
            return r.content
    except Exception as e:
        print(f"  Erreur téléchargement: {e}")

    return None


# ============================================================================
# API helpers
# ============================================================================

def get_modules(session, fid):
    """Get all modules for a formation."""
    r = session.get(f"{API}/formations/{fid}/modules")
    r.raise_for_status()
    return r.json().get("modules", [])


# ============================================================================
# Upload workflow (3 steps)
# ============================================================================

def create_document(session, fid, mid, file_size):
    """Step 1: Create document record on module.
    Returns (file_id, blow_url) or raises on error.
    """
    r = session.post(
        f"{API}/formations/{fid}/modules/{mid}/documents",
        json={
            "name": DOC_NAME,
            "documents_type_id": DOC_TYPE_ID,
            "version": {
                "file": "",
                "original_name": ORIGINAL_FILENAME,
                "file_size": file_size,
                "mime_type": MIME_TYPE,
            },
        },
    )
    if r.status_code not in (200, 201):
        return None, None, r.status_code
    blow_url = r.headers.get("X-Upload-Location")
    doc = r.json().get("document", {})
    file_id = doc.get("version", {}).get("file", {}).get("id")
    return file_id, blow_url, r.status_code


def upload_to_blow(blow_url, image_bytes):
    """Step 2: Upload binary to Blow encoding service.
    Returns broadcast JSON or None.
    """
    r = requests.post(
        blow_url,
        data=image_bytes,
        headers={"Content-Type": MIME_TYPE},
        timeout=60,
    )
    if r.status_code not in (200, 201):
        return None, r.status_code
    return r.json(), r.status_code


def notify_encode_success(session, file_id, broadcast):
    """Step 3: Rewrite Blow's gs:// URLs to https://, then call encode/success.
    The broadcast must be wrapped in {"broadcast": ...} for the API to persist it.
    Must be called twice: first call persists the broadcast, second sets encoding=complete.
    """
    url = f"{API}/files/{file_id}/encode/success"
    rewritten = rewrite_broadcast_urls(broadcast)
    payload = {"broadcast": rewritten}
    r1 = session.post(url, json=payload)
    if r1.status_code not in (200, 201, 205):
        return False
    time.sleep(0.05)
    r2 = session.post(url, json=payload)
    return r2.status_code in (200, 201, 205)


def upload_to_module(session, fid, mid, image_bytes, file_size):
    """Execute the full 3-step upload workflow for one module.
    Returns (success, error_msg).
    """
    # Step 1
    file_id, blow_url, status = create_document(session, fid, mid, file_size)
    if not file_id or not blow_url:
        return False, f"create HTTP {status}"

    # Step 2
    broadcast, status = upload_to_blow(blow_url, image_bytes)
    if not broadcast:
        return False, f"blow HTTP {status}"

    # Step 3
    ok = notify_encode_success(session, file_id, broadcast)
    if not ok:
        return False, "encode/success failed"

    return True, None


def upload_with_retry(session, fid, mid, image_bytes, file_size):
    """Upload with retry on transient failures."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            success, error = upload_to_module(session, fid, mid, image_bytes, file_size)
            if success:
                return True, None
            last_error = error
            # Don't retry permanent errors
            if error and any(str(code) in error for code in (400, 403, 404, 409, 422)):
                return False, error
        except requests.exceptions.RequestException as e:
            last_error = str(e)
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)
    return False, last_error


# ============================================================================
# Main
# ============================================================================

def main():
    print()
    print("=" * 66)
    print("   NEIL ERP — Upload mascotte Neil sur tous les modules")
    print("=" * 66)
    print()

    # Download source image
    print("-- Image source --")
    image_bytes = download_source_image()
    if not image_bytes:
        print("  ERREUR: impossible de récupérer l'image de la mascotte")
        sys.exit(1)
    file_size = len(image_bytes)
    print(f"  {file_size:,} octets ({file_size / 1024:.1f} Ko)")
    print()

    # Create a session for connection pooling
    session = requests.Session()
    session.headers.update(HEADERS)

    grand_total = 0
    grand_success = 0
    grand_skip = 0
    grand_errors = 0
    errors_log = []

    for fid in FORMATION_IDS:
        modules = get_modules(session, fid)
        print(f"-- Formation {fid} ({len(modules)} modules) --")

        f_success = 0
        f_skip = 0
        f_errors = 0

        for i, mod in enumerate(modules):
            mid = mod["id"]

            # Skip modules that already have the mascot (static or dynamic check)
            if (fid, mid) in SKIP_MODULES:
                f_skip += 1
                done = i + 1
                total = len(modules)
                bar = "#" * (done * 40 // total) + "." * (40 - done * 40 // total)
                sys.stdout.write(f"\r  [{bar}] {done}/{total}")
                sys.stdout.flush()
                continue

            # Dynamic duplicate detection: check if module already has the document
            try:
                r_check = session.post(
                    f"{API}/formations/{fid}/modules/{mid}/documents/search",
                    json={"filters": {}},
                )
                if r_check.status_code == 200:
                    existing = r_check.json()
                    if any(d.get("name") == DOC_NAME for d in existing):
                        f_skip += 1
                        done = i + 1
                        total = len(modules)
                        bar = "#" * (done * 40 // total) + "." * (40 - done * 40 // total)
                        sys.stdout.write(
                            f"\r  [{bar}] {done}/{total} — {f_success} OK, {f_errors} err"
                        )
                        sys.stdout.flush()
                        continue
            except Exception:
                pass  # If check fails, proceed with upload

            success, error = upload_with_retry(session, fid, mid, image_bytes, file_size)
            if success:
                f_success += 1
            else:
                f_errors += 1
                errors_log.append((fid, mid, mod.get("name", "?"), error))

            done = i + 1
            total = len(modules)
            bar = "#" * (done * 40 // total) + "." * (40 - done * 40 // total)
            sys.stdout.write(
                f"\r  [{bar}] {done}/{total} — {f_success} OK, {f_errors} err"
            )
            sys.stdout.flush()

            time.sleep(DELAY_BETWEEN_MODULES)

        print()
        print(
            f"  => {f_success} créés, {f_skip} ignorés, {f_errors} erreurs"
        )

        grand_total += len(modules)
        grand_success += f_success
        grand_skip += f_skip
        grand_errors += f_errors

        time.sleep(DELAY_BETWEEN_FORMATIONS)

    print()
    print("=" * 66)
    print(f"   RÉSUMÉ")
    print(f"   {grand_success:,} documents créés")
    print(f"   {grand_skip} modules ignorés (déjà existant)")
    print(f"   {grand_errors} erreurs")
    print(f"   {grand_total:,} modules traités au total")
    print("=" * 66)

    if errors_log:
        print()
        print("-- Erreurs détaillées --")
        for fid, mid, name, error in errors_log[:50]:
            print(f"  F{fid} M{mid} ({name}): {error}")
        if len(errors_log) > 50:
            print(f"  ... et {len(errors_log) - 50} autres erreurs")

    print()
    print("=== DONE ===")


if __name__ == "__main__":
    main()
