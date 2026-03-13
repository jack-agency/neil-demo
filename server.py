"""
Serveur Flask pour le guide de démo Neil.
Sert la page HTML statique et expose des API pour piloter le seeder.
Authentification Google Sign-In restreinte au domaine neil.app.
"""

import json
import os
import subprocess
import threading
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, session
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

load_dotenv()

app = Flask(__name__, static_folder=".", static_url_path="")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-fallback-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ALLOWED_DOMAIN = "neil.app"
DEV_BYPASS_AUTH = os.environ.get("DEV_BYPASS_AUTH", "").lower() == "true"

SEEDER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeder")
CONFIG_PATH = os.path.join(SEEDER_DIR, "seed_config.json")
MANIFEST_PATH = os.path.join(SEEDER_DIR, "seed_manifest.json")

# Session generator state
gen_state = {
    "running": False,
    "done": False,
    "error": False,
    "status_text": "",
    "progress_pct": 0,
    "output": "",
}
gen_lock = threading.Lock()
gen_process = None


# ── Authentication ──────────────────────────────────────────────

@app.before_request
def check_auth():
    """Protège toutes les routes sauf login et auth."""
    if DEV_BYPASS_AUTH and "user_email" not in session:
        session["user_email"] = "dev@neil.app"
        session["user_name"] = "Dev Mode"
        session["user_picture"] = ""
    if request.path in ("/login", "/auth/google", "/auth/logout"):
        return None
    if request.path.startswith("/auth/"):
        return None
    if "user_email" not in session:
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not authenticated"}), 401
        return redirect("/login")
    return None


@app.route("/login")
def login_page():
    if "user_email" in session:
        return redirect("/")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "login.html")) as f:
        html = f.read().replace("{{GOOGLE_CLIENT_ID}}", GOOGLE_CLIENT_ID)
    return html


@app.route("/auth/google", methods=["POST"])
def auth_google():
    token = request.json.get("credential", "")
    try:
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
        email = idinfo.get("email", "")
        hd = idinfo.get("hd", "")

        if hd != ALLOWED_DOMAIN:
            return jsonify({"error": "Seuls les comptes @neil.app sont autorisés"}), 403

        session["user_email"] = email
        session["user_name"] = idinfo.get("name", email)
        session["user_picture"] = idinfo.get("picture", "")
        return jsonify({"ok": True, "email": email})
    except ValueError:
        return jsonify({"error": "Token invalide"}), 401


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/auth/me", methods=["GET"])
def auth_me():
    if "user_email" not in session:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "email": session["user_email"],
        "name": session.get("user_name", ""),
        "picture": session.get("user_picture", ""),
    })


# ── Pages & API ─────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        return jsonify({
            "base_url": config.get("api", {}).get("base_url", ""),
            "key": config.get("api", {}).get("key", ""),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def save_config():
    data = request.json
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        config["api"]["base_url"] = data.get("base_url", config["api"]["base_url"])
        config["api"]["key"] = data.get("key", config["api"]["key"])
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/status", methods=["GET"])
def sessions_status():
    with gen_lock:
        return jsonify({
            "running": gen_state["running"],
            "done": gen_state["done"],
            "error": gen_state["error"],
            "status_text": gen_state["status_text"],
            "progress_pct": gen_state["progress_pct"],
            "output": gen_state["output"],
        })


@app.route("/api/sessions/generate", methods=["POST"])
def sessions_generate():
    data = request.json or {}
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", "")
    if not start_date or not end_date:
        return jsonify({"error": "Dates manquantes"}), 400

    with gen_lock:
        if gen_state["running"]:
            return jsonify({"error": "Génération déjà en cours"}), 409

    thread = threading.Thread(
        target=_run_generate, args=(start_date, end_date), daemon=True
    )
    thread.start()
    return jsonify({"ok": True})


@app.route("/api/sessions/stop", methods=["POST"])
def sessions_stop():
    global gen_process
    with gen_lock:
        if not gen_state["running"]:
            return jsonify({"error": "Aucune génération en cours"}), 400
        if gen_process and gen_process.poll() is None:
            gen_process.terminate()
            try:
                gen_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                gen_process.kill()
        gen_state["running"] = False
        gen_state["error"] = True
        gen_state["status_text"] = "Interrompu"
        gen_state["output"] += "\n--- Interrompu ---\n"
    return jsonify({"ok": True})


def _run_generate(start_date, end_date):
    global gen_process
    with gen_lock:
        gen_state["running"] = True
        gen_state["done"] = False
        gen_state["error"] = False
        gen_state["status_text"] = "Démarrage…"
        gen_state["progress_pct"] = 0
        gen_state["output"] = ""

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    filepath = os.path.join(SEEDER_DIR, "generate_sessions.py")

    try:
        gen_process = subprocess.Popen(
            ["python3", "-u", filepath, "--start", start_date, "--end", end_date],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=SEEDER_DIR,
            env=env,
        )

        output_lines = []
        for line in iter(gen_process.stdout.readline, ""):
            output_lines.append(line)
            # Parse progress hints from output (lines like "PROGRESS:42")
            stripped = line.strip()
            with gen_lock:
                if not gen_state["running"]:
                    break
                gen_state["output"] = "".join(output_lines[-100:])
                if stripped.startswith("PROGRESS:"):
                    try:
                        gen_state["progress_pct"] = int(stripped.split(":")[1])
                    except ValueError:
                        pass
                gen_state["status_text"] = "Génération en cours…"

        gen_process.wait()
        rc = gen_process.returncode

        with gen_lock:
            gen_state["output"] = "".join(output_lines[-200:])
            if rc == 0:
                gen_state["done"] = True
                gen_state["progress_pct"] = 100
                gen_state["status_text"] = "Génération terminée"
            else:
                gen_state["error"] = True
                gen_state["status_text"] = f"Erreur (code {rc})"

    except Exception as e:
        with gen_lock:
            gen_state["error"] = True
            gen_state["status_text"] = f"Erreur : {e}"
            gen_state["output"] += f"\nException: {e}\n"

    with gen_lock:
        gen_state["running"] = False


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
