#!/usr/bin/env python3
"""
seed_dashboard.py — Interface Streamlit pour exécuter et paramétrer les scripts de seed Neil ERP.

2 onglets :
  1. Configuration initiale — Rôles, matières/sous-matières, niveaux, types de documents
  2. Seeder — Curseurs de configuration + récap + exécution automatique avec barre de progression

Usage : streamlit run seed_dashboard.py
"""

import streamlit as st
import subprocess
import os
import re
import json
import sys
import time
from datetime import datetime

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "seed_config.json")

# Import instance-aware helpers from seed_lib
sys.path.insert(0, SCRIPT_DIR)
from seed_lib import instance_slug, _compute_manifest_path, MANIFEST_PATH

STATUS_ICONS = {
    "not_run": "⚪",
    "running": "🔵",
    "success": "🟢",
    "error": "🔴",
    "skipped": "⏭️",
}

# ============================================================================
# Script registries
# ============================================================================

# "Defaults" scripts — Tab 1 (reference data)
DEFAULT_SCRIPTS = [
    {
        "id": "seed_profiles",
        "order": 1,
        "name": "Profils & Rôles",
        "file": "seed_profiles.py",
        "description": "7 profils utilisateurs avec permissions granulaires",
        "estimated_time": "30s",
    },
    {
        "id": "seed_subjects",
        "order": 2,
        "name": "Matières & Sous-matières",
        "file": "seed_subjects.py",
        "description": "Matières par thème + matières transversales",
        "estimated_time": "15s",
    },
    {
        "id": "seed_document_types",
        "order": 3,
        "name": "Types de documents",
        "file": "seed_document_types.py",
        "description": "26 types (pédagogie, admin, compta, marketing)",
        "estimated_time": "10s",
    },
]

# "Seeder" scripts — Tab 2 (pipeline)
SEEDER_SCRIPTS = [
    {
        "id": "seed_neil",
        "order": 1,
        "name": "Infrastructure",
        "file": "seed_neil.py",
        "description": "Écoles, campus, centres, salles, niveaux, calendriers",
        "depends_on": [],
        "estimated_time": "30s",
    },
    {
        "id": "seed_formulas",
        "order": 2,
        "name": "Formations & Formules",
        "file": "seed_formulas.py",
        "description": "Formations, formules, étapes, échéanciers, remises",
        "depends_on": ["seed_neil"],
        "estimated_time": "1min",
    },
    {
        "id": "seed_teaching_units",
        "order": 3,
        "name": "UE & Modules",
        "file": "seed_teaching_units.py",
        "description": "UEs, sous-UEs, modules (cours) par thème",
        "depends_on": ["seed_formulas"],
        "estimated_time": "2min",
    },
    {
        "id": "seed_module_types",
        "order": 4,
        "name": "Types de modules",
        "file": "seed_module_types.py",
        "description": "CM, TD, TP, Atelier, Projet...",
        "depends_on": ["seed_teaching_units"],
        "estimated_time": "30s",
    },
    {
        "id": "seed_students",
        "order": 5,
        "name": "Étudiants",
        "file": "seed_students.py",
        "description": "Création des étudiants avec données réalistes",
        "depends_on": ["seed_neil"],
        "estimated_time": "2min",
    },
    {
        "id": "seed_parents",
        "order": 6,
        "name": "Parents",
        "file": "seed_parents.py",
        "description": "Parents des mineurs et fratries",
        "depends_on": ["seed_students"],
        "estimated_time": "30s",
    },
    {
        "id": "seed_ibans",
        "order": 7,
        "name": "IBANs",
        "file": "seed_ibans.py",
        "description": "IBANs étudiants majeurs + parents",
        "depends_on": ["seed_parents"],
        "estimated_time": "1min",
    },
    {
        "id": "seed_enrollments",
        "order": 8,
        "name": "Inscriptions",
        "file": "seed_enrollments.py",
        "description": "Inscriptions aux formules, avancement étapes, remises",
        "depends_on": ["seed_students", "seed_formulas"],
        "estimated_time": "3min",
    },
    {
        "id": "seed_groups",
        "order": 9,
        "name": "Classes & Groupes",
        "file": "seed_groups.py",
        "description": "Ensembles de classes, groupes, affectation étudiants",
        "depends_on": ["seed_enrollments"],
        "estimated_time": "1min",
    },
    {
        "id": "seed_users",
        "order": 10,
        "name": "Employés",
        "file": "seed_users.py",
        "description": "Employés avec profils et scopes",
        "depends_on": ["seed_neil"],
        "estimated_time": "30s",
    },
    {
        "id": "seed_sequences",
        "order": 11,
        "name": "Séances",
        "file": "seed_sequences.py",
        "description": "Séances planifiées sur l'année scolaire",
        "depends_on": ["seed_groups", "seed_users", "seed_teaching_units"],
        "estimated_time": "5min",
    },
    {
        "id": "seed_absences",
        "order": 12,
        "name": "Absences & Retards",
        "file": "seed_absences.py",
        "description": "Absences et retards sur les séances",
        "depends_on": ["seed_sequences"],
        "estimated_time": "2min",
    },
    {
        "id": "seed_scores",
        "order": 13,
        "name": "Notes",
        "file": "seed_scores.py",
        "description": "Relevés de notes + notes composées",
        "depends_on": ["seed_groups", "seed_teaching_units"],
        "estimated_time": "3min",
    },
    {
        "id": "seed_report_cards",
        "order": 14,
        "name": "Bulletins",
        "file": "seed_report_cards.py",
        "description": "Bulletins de notes par semestre",
        "depends_on": ["seed_scores", "seed_groups"],
        "estimated_time": "2min",
    },
    {
        "id": "seed_payments",
        "order": 15,
        "name": "Échéanciers",
        "file": "seed_payments.py",
        "description": "Échéances de paiement",
        "depends_on": ["seed_enrollments", "seed_ibans"],
        "estimated_time": "3min",
    },
    {
        "id": "seed_employers",
        "order": 16,
        "name": "Employeurs",
        "file": "seed_employers.py",
        "description": "Entreprises partenaires, établissements et contacts",
        "depends_on": ["seed_neil"],
        "estimated_time": "30s",
    },
]

RESET_SCRIPT = {
    "id": "seed_reset",
    "order": 0,
    "name": "Remise à zéro",
    "file": "seed_reset.py",
    "description": "Supprime toutes les données (préserve comptes admin/service)",
    "depends_on": [],
    "estimated_time": "5min",
}

ALL_SCRIPTS_MAP = {}
for _s in DEFAULT_SCRIPTS + SEEDER_SCRIPTS + [RESET_SCRIPT]:
    ALL_SCRIPTS_MAP[_s["id"]] = _s


# ============================================================================
# Config / Manifest helpers
# ============================================================================

def load_config_file():
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config_file(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_manifest_file():
    """Charge le manifest de l'instance API courante."""
    config = load_config_file()
    base_url = config.get("api", {}).get("base_url", "") if config else ""
    manifest_path = _compute_manifest_path(base_url)
    if not os.path.exists(manifest_path):
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_config_from_ui(params):
    """Generate config using seed_lib's generator with UI params."""
    import sys as _sys, importlib
    _sys.path.insert(0, SCRIPT_DIR)
    import seed_lib; importlib.reload(seed_lib)
    config = seed_lib.generate_default_config(
        n_schools=params["n_schools"],
        campus_counts=params.get("campus_counts"),
        themes=params["themes"],
        n_students=params["n_students"],
        n_employees=params["n_employees"],
        n_companies=params.get("n_companies"),
        formation_hours_min=params.get("formation_hours_min"),
        formation_hours_max=params.get("formation_hours_max"),
        avg_discounts=params.get("avg_discounts"),
        formations_per_formula=params.get("formations_per_formula"),
        n_centers=params.get("n_centers"),
        formulas_per_campus=params.get("formulas_per_campus"),
        formation_indices=params.get("formation_indices"),
        include_degrees=params.get("include_degrees", True),
        n_employers=params.get("n_employers", 10),
    )
    # Année scolaire
    y_start = params.get("academic_year_start", 2025)
    y_end = params.get("academic_year_end", 2026)
    config["meta"]["academic_year"] = f"{y_start}-{y_end}"
    # Inscriptions
    config["enrollments"]["final_pct"] = params.get("final_pct", 65)
    config["enrollments"]["discount_pct"] = params.get("discount_pct", 30)
    config["enrollments"]["minor_pct"] = params.get("minor_pct", 3)
    # Datasets (standard ou poudlard)
    config["students"]["dataset"] = params.get("student_dataset", "standard")
    config["employees"]["dataset"] = params.get("employee_dataset", "standard")
    config["employers"]["dataset"] = params.get("employer_dataset", "standard")
    # Notes
    config["scores"]["mean"] = params.get("scores_mean", 1200)
    config["scores"]["std"] = params.get("scores_std", 300)
    config["scores"]["absent_rate_pct"] = params.get("absent_rate", 3)
    # Seeder-specific params
    config.setdefault("seeder", {})
    config["seeder"]["enrolled_pct"] = params.get("enrolled_pct", 90)
    config["seeder"]["formulas_per_campus"] = params.get("formulas_per_campus", 3)
    config["seeder"]["avg_discounts"] = params.get("avg_discounts", 2)
    config["seeder"]["formations_per_formula"] = params.get("formations_per_formula", 1)
    config["seeder"]["formation_hours_min"] = params.get("formation_hours_min", 100)
    config["seeder"]["formation_hours_max"] = params.get("formation_hours_max", 1200)
    config["seeder"]["module_coverage_pct"] = params.get("module_coverage_pct", 100)
    config["seeder"]["sequence_coverage_pct"] = params.get("sequence_coverage_pct", 100)
    config["seeder"]["sequence_publish_pct"] = params.get("sequence_publish_pct", 100)
    config["seeder"]["scores_per_formation"] = params.get("scores_per_formation", 5)
    config["seeder"]["include_compound_scores"] = params.get("include_compound_scores", True)
    config["seeder"]["include_report_cards"] = params.get("include_report_cards", True)
    config["seeder"]["include_calendars"] = params.get("include_calendars", True)
    config["seeder"]["include_avatars"] = params.get("include_avatars", True)
    config["seeder"]["include_degrees"] = params.get("include_degrees", True)
    config["seeder"]["absence_rate_pct"] = params.get("absence_rate_pct", 8)
    config["seeder"]["delay_rate_pct"] = params.get("delay_rate_pct", 5)
    config["seeder"]["n_companies"] = params.get("n_companies", 1)
    # Override API settings from dashboard fields
    if params.get("api_url"):
        config["api"]["base_url"] = params["api_url"].rstrip("/")
    if params.get("api_key"):
        config["api"]["key"] = params["api_key"]
    return config


# ============================================================================
# Pipeline helpers
# ============================================================================

def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


def init_session_state():
    all_ids = [s["id"] for s in DEFAULT_SCRIPTS + SEEDER_SCRIPTS + [RESET_SCRIPT]]
    if "statuses" not in st.session_state:
        st.session_state.statuses = {sid: "not_run" for sid in all_ids}
    if "outputs" not in st.session_state:
        st.session_state.outputs = {sid: "" for sid in all_ids}
    if "running_process" not in st.session_state:
        st.session_state.running_process = None
    if "running_script_id" not in st.session_state:
        st.session_state.running_script_id = None
    if "run_mode" not in st.session_state:
        st.session_state.run_mode = None  # "defaults", "seeder", "live_reset", "live_seeder", or None
    if "run_queue" not in st.session_state:
        st.session_state.run_queue = []
    if "run_queue_idx" not in st.session_state:
        st.session_state.run_queue_idx = 0
    if "confirm_reset" not in st.session_state:
        st.session_state.confirm_reset = False
    if "live_start_time" not in st.session_state:
        st.session_state.live_start_time = None


def build_env(script_id=None):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_script(script_id):
    """Legacy non-live run (used by queue runner when not in live mode)."""
    script = ALL_SCRIPTS_MAP.get(script_id)
    if not script:
        return

    st.session_state.statuses[script_id] = "running"
    st.session_state.outputs[script_id] = ""
    st.session_state.running_script_id = script_id

    filepath = os.path.join(SCRIPT_DIR, script["file"])
    cmd = ["python3", "-u", filepath]
    env = build_env(script_id)

    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, cwd=SCRIPT_DIR, text=True, bufsize=1,
        )
        st.session_state.running_process = process

        output_lines = []
        for line in iter(process.stdout.readline, ''):
            clean_line = strip_ansi(line)
            output_lines.append(clean_line)
            st.session_state.outputs[script_id] = "".join(output_lines)

        process.wait()

        if process.returncode == 0:
            st.session_state.statuses[script_id] = "success"
        else:
            st.session_state.statuses[script_id] = "error"
            output_lines.append(f"\n--- Exit code: {process.returncode} ---\n")
            st.session_state.outputs[script_id] = "".join(output_lines)

    except Exception as e:
        st.session_state.statuses[script_id] = "error"
        st.session_state.outputs[script_id] += f"\n--- Exception: {e} ---\n"
    finally:
        st.session_state.running_process = None
        st.session_state.running_script_id = None


# ============================================================================
# Live execution helpers (real-time progress)
# ============================================================================

# Reset script has 18 numbered sections (log_section("N/18 — ..."))
RESET_TOTAL_STEPS = 20
RESET_STEP_LABELS = {
    1: "Échéanciers de paiement",
    2: "Bulletins de notes",
    3: "Notes et notes composées",
    4: "Absences et retards",
    5: "Séances",
    6: "Classes et groupes",
    7: "Inscriptions aux formules",
    8: "IBANs",
    9: "Parents",
    10: "Étudiants",
    11: "Employés",
    12: "Profils utilisateurs",
    13: "Modules et UEs",
    14: "Types de modules",
    15: "Types de documents",
    16: "Matières et sous-matières",
    17: "Calendriers de contraintes",
    18: "Diplômes",
    19: "Formations et formules",
    20: "Infrastructure",
}

# Regex to detect reset step progression from stdout
RE_RESET_STEP = re.compile(r'(\d+)/20\s*[—–-]')
# Regex to detect progress_bar lines (e.g. "[███░░░] 42/100 étudiants")
RE_PROGRESS_BAR = re.compile(r'\[([█░]+)\]\s*(\d+)/(\d+)\s*(.*)')
# Regex to detect log_section lines (for seeder scripts)
RE_LOG_SECTION = re.compile(r'━━\s*(.+?)\s*━')
# Regex to detect [OK] lines
RE_LOG_OK = re.compile(r'\[OK\]\s*(.*)')


def parse_reset_progress(output_text):
    """Parse reset script output to find current step N/17."""
    steps_found = []
    for m in RE_RESET_STEP.finditer(output_text):
        steps_found.append(int(m.group(1)))
    if steps_found:
        return max(steps_found)
    return 0


def parse_last_section(output_text):
    """Parse last log_section label from output."""
    matches = RE_LOG_SECTION.findall(output_text)
    if matches:
        return matches[-1].strip()
    return ""


def parse_intra_progress(output_text):
    """Parse the last progress_bar from output (e.g. 42/100 étudiants)."""
    matches = RE_PROGRESS_BAR.findall(output_text)
    if matches:
        _, current, total, label = matches[-1]
        return int(current), int(total), label.strip()
    return None, None, ""


def run_script_live(script_id, progress_placeholder, console_placeholder, stop_placeholder):
    """Run a script with real-time progress bar and console output in Streamlit.

    Uses non-blocking reads with select() to update the UI periodically.
    """
    import select
    import io

    script = ALL_SCRIPTS_MAP.get(script_id)
    if not script:
        return

    st.session_state.statuses[script_id] = "running"
    st.session_state.outputs[script_id] = ""
    st.session_state.running_script_id = script_id

    filepath = os.path.join(SCRIPT_DIR, script["file"])
    cmd = ["python3", "-u", filepath]
    env = build_env(script_id)

    is_reset = (script_id == "seed_reset")
    start_time = time.time()

    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, cwd=SCRIPT_DIR, bufsize=0,
        )
        st.session_state.running_process = process

        output_text = ""
        last_ui_update = 0
        update_interval = 0.3  # Update UI every 300ms

        # Make stdout non-blocking
        import fcntl
        fd = process.stdout.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        while True:
            # Check if process is done
            retcode = process.poll()

            # Try to read available data
            try:
                chunk = process.stdout.read(4096)
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    output_text += text
            except (IOError, BlockingIOError):
                pass

            now = time.time()
            elapsed = now - start_time

            # Update UI periodically
            if now - last_ui_update >= update_interval:
                last_ui_update = now
                clean_output = strip_ansi(output_text)
                st.session_state.outputs[script_id] = clean_output

                # Update progress bar
                if is_reset:
                    step = parse_reset_progress(clean_output)
                    pct = step / RESET_TOTAL_STEPS if RESET_TOTAL_STEPS > 0 else 0
                    step_label = RESET_STEP_LABELS.get(step, "")
                    intra_cur, intra_tot, intra_label = parse_intra_progress(clean_output)
                    detail = ""
                    if intra_cur is not None and intra_tot > 0:
                        detail = f" — {intra_cur}/{intra_tot} {intra_label}"
                    progress_placeholder.progress(
                        min(pct, 1.0),
                        text=f"🗑️ Étape {step}/{RESET_TOTAL_STEPS} — {step_label}{detail}  ⏱️ {elapsed:.0f}s"
                    )
                else:
                    # For seeder scripts: show section + intra-progress
                    section = parse_last_section(clean_output)
                    intra_cur, intra_tot, intra_label = parse_intra_progress(clean_output)
                    detail = ""
                    if intra_cur is not None and intra_tot > 0:
                        detail = f" — {intra_cur}/{intra_tot} {intra_label}"
                    if section:
                        progress_placeholder.progress(
                            0.5,  # indeterminate-style
                            text=f"⚙️ {section}{detail}  ⏱️ {elapsed:.0f}s"
                        )
                    else:
                        progress_placeholder.progress(
                            0.0,
                            text=f"⚙️ {script['name']} en cours...  ⏱️ {elapsed:.0f}s"
                        )

                # Update console (show last 80 lines max for performance)
                lines = clean_output.split("\n")
                display_lines = lines[-80:] if len(lines) > 80 else lines
                console_placeholder.code("\n".join(display_lines), language=None)

            # Process is done and we've read all output
            if retcode is not None:
                # Final read
                try:
                    remaining = process.stdout.read()
                    if remaining:
                        output_text += remaining.decode("utf-8", errors="replace")
                except (IOError, BlockingIOError):
                    pass
                break

            time.sleep(0.1)

        # Final update
        clean_output = strip_ansi(output_text)
        st.session_state.outputs[script_id] = clean_output
        elapsed = time.time() - start_time

        if process.returncode == 0:
            st.session_state.statuses[script_id] = "success"
            progress_placeholder.progress(1.0, text=f"✅ {script['name']} terminé en {elapsed:.0f}s")
        else:
            st.session_state.statuses[script_id] = "error"
            clean_output += f"\n--- Exit code: {process.returncode} ---\n"
            st.session_state.outputs[script_id] = clean_output
            progress_placeholder.progress(1.0, text=f"❌ {script['name']} — erreur (exit {process.returncode}) après {elapsed:.0f}s")

        # Final console update
        lines = clean_output.split("\n")
        display_lines = lines[-80:] if len(lines) > 80 else lines
        console_placeholder.code("\n".join(display_lines), language=None)

    except Exception as e:
        st.session_state.statuses[script_id] = "error"
        st.session_state.outputs[script_id] += f"\n--- Exception: {e} ---\n"
        progress_placeholder.progress(1.0, text=f"❌ Exception: {e}")
    finally:
        st.session_state.running_process = None
        st.session_state.running_script_id = None


def stop_current():
    proc = st.session_state.get("running_process")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    st.session_state.running_process = None
    sid = st.session_state.get("running_script_id")
    if sid:
        st.session_state.statuses[sid] = "error"
        st.session_state.outputs[sid] += "\n--- Interrupted ---\n"
    st.session_state.running_script_id = None
    st.session_state.run_mode = None
    st.session_state.run_queue = []


# ============================================================================
# Tab 1: Configuration initiale
# ============================================================================

THEME_OPTIONS = ["sciences", "arts", "droit", "sante", "ingenierie"]

def render_defaults_tab():
    # If in live reset mode, show the live reset view
    if st.session_state.run_mode == "live_reset":
        render_live_reset(key_suffix="_defaults")
        return

    # If in live defaults mode, show the live defaults pipeline
    if st.session_state.run_mode == "live_defaults":
        render_live_pipeline(DEFAULT_SCRIPTS, "Configuration initiale")
        return

    st.markdown("### Données de référence")
    st.caption(
        "Ces scripts créent les valeurs par défaut de l'ERP : profils/rôles, "
        "matières et sous-matières, types de documents. "
        "Les niveaux académiques sont créés automatiquement par le pipeline du seeder."
    )

    is_running = st.session_state.running_script_id is not None

    # Config for themes (affects which subjects are created)
    config = load_config_file()
    current_themes = []
    if config:
        for s in config.get("schools", []):
            t = s.get("theme", "sciences")
            if t not in current_themes:
                current_themes.append(t)

    st.divider()

    # Action buttons
    btn_cols = st.columns([1, 1, 1, 1])
    with btn_cols[0]:
        if st.button("▶️ Tout générer", disabled=is_running, type="primary", use_container_width=True):
            st.session_state.run_mode = "live_defaults"
            st.session_state.run_queue = [s["id"] for s in DEFAULT_SCRIPTS]
            st.session_state.run_queue_idx = 0
            for s in DEFAULT_SCRIPTS:
                st.session_state.statuses[s["id"]] = "not_run"
                st.session_state.outputs[s["id"]] = ""
            st.rerun()
    with btn_cols[1]:
        if st.button("⏹ Stop", disabled=not is_running, use_container_width=True):
            stop_current()
            st.rerun()
    with btn_cols[2]:
        if st.button("💣 Remise à zéro", disabled=is_running, use_container_width=True):
            st.session_state.confirm_reset = True
            st.rerun()
    with btn_cols[3]:
        if st.button("🔄 Reset statuts", use_container_width=True):
            for s in DEFAULT_SCRIPTS:
                st.session_state.statuses[s["id"]] = "not_run"
                st.session_state.outputs[s["id"]] = ""
            st.rerun()

    # Reset confirmation
    if st.session_state.get("confirm_reset"):
        st.warning(
            "⚠️ **Remise à zéro complète** — Cette action va supprimer **toutes** les données "
            "de l'ERP. Les comptes de service et administrateurs seront préservés."
        )
        confirm_cols = st.columns([1, 1, 3])
        with confirm_cols[0]:
            if st.button("✅ Confirmer la RAZ", type="primary", use_container_width=True):
                st.session_state.confirm_reset = False
                st.session_state.run_mode = "live_reset"
                st.rerun()
        with confirm_cols[1]:
            if st.button("❌ Annuler", use_container_width=True):
                st.session_state.confirm_reset = False
                st.rerun()

    st.divider()

    # Load seed_lib data for previews
    import sys as _sys, importlib
    _sys.path.insert(0, SCRIPT_DIR)
    try:
        import seed_lib as _sl; importlib.reload(_sl)
        SUBJECT_TEMPLATES = _sl.SUBJECT_TEMPLATES
        SUBJECT_TRANSVERSAL = _sl.SUBJECT_TRANSVERSAL
        DOCUMENT_TYPE_TEMPLATES = _sl.DOCUMENT_TYPE_TEMPLATES
        import seed_profiles as _sp; importlib.reload(_sp)
        PROFILE_DEFS = _sp.PROFILES
        _seed_lib_loaded = True
    except Exception:
        _seed_lib_loaded = False

    # Script cards with data previews
    for script in DEFAULT_SCRIPTS:
        sid = script["id"]
        status = st.session_state.statuses.get(sid, "not_run")
        icon = STATUS_ICONS.get(status, "⚪")

        with st.expander(f"{icon} {script['order']}. {script['name']} — {script['description']}", expanded=(status == "error")):
            info_cols = st.columns([1, 1, 2])
            with info_cols[0]:
                st.metric("Statut", f"{icon} {status}")
            with info_cols[1]:
                st.metric("Durée estimée", script["estimated_time"])

            run_cols = st.columns([1, 1, 3])
            with run_cols[0]:
                if st.button("▶️ Run", disabled=is_running, key=f"run_def_{sid}", use_container_width=True):
                    run_script(sid)
                    st.rerun()
            with run_cols[1]:
                if st.button("🗑️ Clear", key=f"clear_def_{sid}", use_container_width=True):
                    st.session_state.outputs[sid] = ""
                    st.session_state.statuses[sid] = "not_run"
                    st.rerun()

            # ── Data preview ──
            if _seed_lib_loaded:
                if sid == "seed_profiles":
                    _render_profiles_preview(PROFILE_DEFS)
                elif sid == "seed_subjects":
                    # Toujours afficher les matières standard (hors poudlard)
                    preview_themes = [t for t in SUBJECT_TEMPLATES if t != "poudlard"]
                    _render_subjects_preview(SUBJECT_TEMPLATES, SUBJECT_TRANSVERSAL, preview_themes)
                elif sid == "seed_document_types":
                    _render_document_types_preview(DOCUMENT_TYPE_TEMPLATES)

            # ── Script output ──
            output = st.session_state.outputs.get(sid, "")
            if output:
                st.markdown("##### 📜 Sortie console")
                st.code(output, language=None)

    # Reset script output
    reset_output = st.session_state.outputs.get("seed_reset", "")
    if reset_output:
        with st.expander("💣 Dernière remise à zéro", expanded=False):
            st.code(reset_output, language=None)


def _render_profiles_preview(profiles):
    """Show a table of profiles to be created."""
    st.markdown("##### 📋 Profils à créer")
    rows = []
    for p in profiles:
        # Count permissions
        perm_count = 0
        for module in p.get("permissions", {}).values():
            for feature in module.values():
                perm_count += sum(1 for v in feature.values() if v)
        obf = p.get("obfuscate")
        obf_fields = 0
        if obf:
            for cat in obf.values():
                obf_fields += len(cat)
        rows.append({
            "Profil": p["name"],
            "Description": p.get("description", "")[:80],
            "Permissions": perm_count,
            "Champs masqués": obf_fields,
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_subjects_preview(templates, transversal, active_themes, dataset_key="default"):
    """Show subjects grouped by theme.

    dataset_key is used to generate unique widget keys so Streamlit correctly
    re-renders when the user switches between Standard and Poudlard datasets.
    """
    THEME_LABELS = {
        "sciences": "Sciences",
        "arts": "Arts",
        "droit": "Droit",
        "sante": "Santé",
        "ingenierie": "Ingénierie",
        "poudlard": "Poudlard",
    }
    # Use a keyed container so the whole block is rebuilt on dataset change
    container = st.container()
    with container:
        themes_to_show = active_themes if active_themes else ["sciences"]

        # Count totals across all themes
        all_subjects = []
        for theme in themes_to_show:
            all_subjects.extend(templates.get(theme, []))
        all_subjects.extend(transversal or [])
        grand_total_sub = sum(len(s.get("sub", [])) for s in all_subjects)
        st.markdown(f"##### 📋 Matières à créer — {len(all_subjects)} matières, {grand_total_sub} sous-matières")

        for idx, theme in enumerate(themes_to_show):
            subjects = templates.get(theme, [])
            if not subjects:
                continue
            total_sub = sum(len(s.get("sub", [])) for s in subjects)
            label = THEME_LABELS.get(theme, theme.title())
            st.markdown(f"**🎨 {label}** — {len(subjects)} matières, {total_sub} sous-matières")
            rows = []
            for s in subjects:
                subs = s.get("sub", [])
                sub_names = ", ".join(ss["name"] for ss in subs)
                rows.append({
                    "Matière": s["name"],
                    "Sous-matières": sub_names if sub_names else "—",
                    "Nb": len(subs),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True,
                         key=f"subj_df_{dataset_key}_{theme}_{idx}")

        # Transversal
        if transversal:
            total_sub = sum(len(s.get("sub", [])) for s in transversal)
            st.markdown(f"**🌐 Transversales** — {len(transversal)} matières, {total_sub} sous-matières")
            rows = []
            for s in transversal:
                subs = s.get("sub", [])
                sub_names = ", ".join(ss["name"] for ss in subs)
                rows.append({
                    "Matière": s["name"],
                    "Sous-matières": sub_names if sub_names else "—",
                    "Nb": len(subs),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True,
                          key=f"subj_df_{dataset_key}_transversal")


def _render_document_types_preview(templates):
    """Show document types grouped by category."""
    st.markdown("##### 📋 Types de documents à créer")

    # Group by category based on libraries
    categories = {
        "📚 Pédagogie": [],
        "🏢 Secrétariat / Admin": [],
        "📢 Marketing": [],
        "💰 Comptabilité": [],
    }

    for dt in templates:
        libs = dt.get("libraries", {})
        if libs.get("pedagogy") or libs.get("pedagogy_module"):
            categories["📚 Pédagogie"].append(dt)
        elif libs.get("accounting"):
            categories["💰 Comptabilité"].append(dt)
        elif libs.get("marketing"):
            categories["📢 Marketing"].append(dt)
        elif libs.get("secretariat"):
            categories["🏢 Secrétariat / Admin"].append(dt)
        else:
            categories["🏢 Secrétariat / Admin"].append(dt)

    for cat_name, cat_docs in categories.items():
        if not cat_docs:
            continue
        st.markdown(f"**{cat_name}** ({len(cat_docs)})")
        rows = []
        for dt in cat_docs:
            visible = "✅" if dt.get("authz_for_students") else "❌"
            printable = "✅" if dt.get("authz_for_print") else "❌"
            shareable = "✅" if dt.get("authz_for_external_share") else "❌"
            rows.append({
                "Type": dt["name"],
                "Description": dt["description"][:60],
                "👁️ Étudiants": visible,
                "🖨️ Impression": printable,
                "🔗 Partage ext.": shareable,
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)


def render_live_reset(key_suffix=""):
    """Render live reset with real-time progress bar."""
    st.markdown("### 💣 Remise à zéro en cours")

    btn_cols = st.columns([1, 4])
    with btn_cols[0]:
        if st.button("⏹ Arrêter", type="primary", use_container_width=True, key=f"stop_live_reset{key_suffix}"):
            stop_current()
            st.session_state.run_mode = None
            st.rerun()

    progress_ph = st.empty()
    progress_ph.progress(0.0, text="🗑️ Démarrage de la remise à zéro...")

    console_ph = st.empty()
    console_ph.code("Lancement de seed_reset.py...", language=None)

    stop_ph = st.empty()

    # Run the reset script with live progress
    run_script_live("seed_reset", progress_ph, console_ph, stop_ph)

    # Done — show back button
    st.divider()
    status = st.session_state.statuses.get("seed_reset", "not_run")
    if status == "success":
        st.success("✅ Remise à zéro terminée avec succès !")
    elif status == "error":
        st.error("❌ La remise à zéro a rencontré une erreur.")

    if st.button("← Retour", use_container_width=True, key=f"back_from_reset{key_suffix}"):
        st.session_state.run_mode = None
        st.rerun()


def render_live_pipeline(scripts_list, pipeline_name):
    """Render live sequential pipeline with real-time per-script progress."""
    queue = st.session_state.run_queue
    total = len(queue)
    idx = st.session_state.run_queue_idx

    st.markdown(f"### 🚀 {pipeline_name} — Exécution en cours")

    btn_cols = st.columns([1, 4])
    with btn_cols[0]:
        if st.button("⏹ Arrêter", type="primary", use_container_width=True, key=f"stop_live_{pipeline_name}"):
            stop_current()
            st.session_state.run_mode = None
            st.rerun()

    # Global progress bar
    global_ph = st.empty()

    # Per-script progress + console
    script_progress_ph = st.empty()
    console_ph = st.empty()
    stop_ph = st.empty()

    # Execute scripts sequentially with live progress
    for i in range(idx, total):
        sid = queue[i]
        script = ALL_SCRIPTS_MAP.get(sid, {})
        st.session_state.run_queue_idx = i

        # Update global progress
        completed = sum(1 for s in queue[:i] if st.session_state.statuses.get(s) == "success")
        global_pct = completed / total
        global_ph.progress(global_pct, text=f"Pipeline : script {i + 1}/{total} — {script.get('name', sid)}")

        # Run this script live
        script_progress_ph.progress(0.0, text=f"⚙️ {script.get('name', sid)} — démarrage...")
        console_ph.code(f"Lancement de {script.get('file', sid)}...", language=None)

        run_script_live(sid, script_progress_ph, console_ph, stop_ph)

        # If errored, stop the pipeline
        if st.session_state.statuses.get(sid) == "error":
            global_ph.progress((i + 1) / total, text=f"❌ Pipeline arrêté — erreur sur {script.get('name', sid)}")
            break

    # Final global progress
    completed = sum(1 for s in queue if st.session_state.statuses.get(s) == "success")
    errored = sum(1 for s in queue if st.session_state.statuses.get(s) == "error")
    if errored == 0:
        global_ph.progress(1.0, text=f"✅ {pipeline_name} terminé — {completed}/{total} étapes")
    else:
        pct = (completed + errored) / total
        global_ph.progress(pct, text=f"⚠️ {pipeline_name} — {completed}/{total} succès, {errored} erreur(s)")

    st.session_state.run_mode = None

    # Summary
    st.divider()
    if errored == 0:
        st.success(f"✅ {pipeline_name} terminé avec succès ! ({completed} étapes)")
    else:
        st.error(f"❌ {pipeline_name} terminé avec {errored} erreur(s).")

    # Show all script outputs
    for sid in queue:
        script = ALL_SCRIPTS_MAP.get(sid, {})
        status = st.session_state.statuses.get(sid, "not_run")
        icon = STATUS_ICONS.get(status, "⚪")
        output = st.session_state.outputs.get(sid, "")
        if output:
            with st.expander(f"{icon} {script.get('name', sid)}", expanded=(status == "error")):
                st.code(output, language=None)

    if st.button("← Retour", use_container_width=True, key=f"back_from_{pipeline_name}"):
        st.session_state.run_mode = None
        st.rerun()


# ============================================================================
# Tab 2: Seeder
# ============================================================================

def render_seeder_tab():
    is_running = st.session_state.running_script_id is not None

    # If in live execution mode, show the live pipeline
    if st.session_state.run_mode == "live_seeder":
        render_live_pipeline(SEEDER_SCRIPTS, "Seeder")
        return

    # If in live reset mode, show the live reset
    if st.session_state.run_mode == "live_reset":
        render_live_reset(key_suffix="_seeder")
        return

    st.markdown("### Configuration du seed")
    st.caption("Paramétrez les données à générer, puis cliquez sur **Lancer le seed** pour exécuter le pipeline.")

    # ── Column layout ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### 🏫 Structure")

        year_cols = st.columns(2)
        with year_cols[0]:
            academic_year_start = st.number_input(
                "Année de début", min_value=2020, max_value=2035, value=2025,
                key="sd_year_start", help="Année de rentrée (septembre)",
            )
        with year_cols[1]:
            academic_year_end = st.number_input(
                "Année de fin", min_value=academic_year_start + 1, max_value=academic_year_start + 3,
                value=academic_year_start + 1,
                key="sd_year_end", help="Année de fin d'année scolaire (juin)",
            )

        n_schools = st.slider("Nombre d'écoles", 1, 5, 1, key="sd_schools")

        # Per-school: campus count + theme
        # Max campus depends on theme (number of available cities)
        import sys as _sys2, importlib as _il2
        _sys2.path.insert(0, SCRIPT_DIR)
        import seed_lib as _sl_cities; _il2.reload(_sl_cities)
        _CAMPUS_CITIES = _sl_cities.CAMPUS_CITIES

        campus_counts = []
        themes = []
        for i in range(n_schools):
            sub_cols = st.columns([1, 1])
            # Theme first (needed to compute campus max)
            with sub_cols[1]:
                default_idx = i if i < len(THEME_OPTIONS) else 0
                theme = st.selectbox(
                    f"Thème école {i+1}",
                    THEME_OPTIONS,
                    index=default_idx,
                    key=f"sd_theme_{i}",
                    help="Détermine les noms de formations, cours, salles",
                )
                themes.append(theme)
            with sub_cols[0]:
                max_campuses = len(_CAMPUS_CITIES.get(theme, _CAMPUS_CITIES["sciences"]))
                n_c = st.number_input(
                    f"Campus école {i+1}", min_value=1, max_value=max_campuses, value=min(1, max_campuses),
                    key=f"sd_campus_{i}",
                    help=f"Max {max_campuses} villes disponibles pour ce thème",
                )
                campus_counts.append(n_c)

        st.markdown("---")

        n_companies = st.number_input("Nombre de sociétés", min_value=1, max_value=10, value=n_schools, key="sd_companies")

        st.markdown("#### 🏢 Centres & Salles")
        total_campuses_for_default = sum(campus_counts)
        n_centers = st.slider("Nombre de centres d'activité", 1, 20, max(total_campuses_for_default, 1), key="sd_n_centers",
                              help="Centres créés puis associés aléatoirement aux campus")
        rooms_per_center = st.slider("Salles par centre", 1, 10, 4, key="sd_rooms_per_center")
        total_capacity = st.slider("Places totales par centre", 30, 500, 120, step=10, key="sd_total_capacity",
                                   help="Capacité totale répartie entre les salles du centre")

        st.markdown("#### 📚 Formations & Formules")
        # Compute max formations/formulas based on selected themes
        from seed_lib import FORMATION_TEMPLATES as _FM_TPL, FORMULA_TEMPLATES as _FML_TPL
        _max_fm = min(len(_FM_TPL.get(t, [])) for t in themes) if themes else 4
        _max_fml = min(len(_FML_TPL.get(t, [])) for t in themes) if themes else 3
        if _max_fm > 1:
            n_formations_per_school = st.slider("Formations par école", 1, _max_fm, _max_fm, key="sd_n_formations",
                                                 help=f"Max {_max_fm} formations disponibles pour les thèmes sélectionnés")
        else:
            n_formations_per_school = _max_fm
            st.info(f"1 formation disponible pour le thème sélectionné")
        formations_per_formula = st.slider("Formations par formule", 1, 5, 1, key="sd_formations_per_formula",
                                            help="Nombre de formations rattachées à chaque formule")
        if _max_fml > 1:
            formulas_per_campus = st.slider("Formules par école", 1, _max_fml, _max_fml, key="sd_formulas_per_campus",
                                           help=f"Max {_max_fml} formules disponibles pour les thèmes sélectionnés")
        else:
            formulas_per_campus = _max_fml
            st.info(f"1 formule disponible pour le thème sélectionné")
        avg_discounts = st.slider("Réductions moyennes par formule", 0, 3, 2, key="sd_avg_discounts",
                                  help="Nombre max de remises par formule (max 3 disponibles par template)")
        hours_cols = st.columns(2)
        with hours_cols[0]:
            formation_hours_min = st.number_input("Durée min (h)", 50, 2000, 100, step=50, key="sd_hours_min")
        with hours_cols[1]:
            formation_hours_max = st.number_input("Durée max (h)", 50, 2000, 1200, step=50, key="sd_hours_max")
        if formation_hours_min > formation_hours_max:
            st.warning(f"⚠️ Durée min ({formation_hours_min}h) > durée max ({formation_hours_max}h) — les valeurs seront inversées automatiquement.")
            formation_hours_min, formation_hours_max = formation_hours_max, formation_hours_min

    with col_right:
        st.markdown("#### 👥 Population")
        n_students = st.slider("Nombre d'étudiants", 10, 1000, 50, step=10, key="sd_students")
        n_employees = st.slider("Nombre d'employés", 8, 50, 10, key="sd_employees",
                                help="Min 8 requis : 6 profils admin + 1 multi-profil + 1 enseignant")
        n_employers = st.slider("Nombre d'employeurs", 0, 30, 10, key="sd_employers",
                                help="Entreprises partenaires (Capgemini, LVMH, BNP, SNCF…)")
        minor_pct = st.slider("% étudiants mineurs", 0, 20, 3, key="sd_minor_pct")
        include_avatars = st.checkbox("📷 Photos d'étudiants", value=True, key="sd_include_avatars",
                                      help="Upload d'avatars via pravatar.cc (ralentit la création ~1s/étudiant)")

        st.markdown("#### 📝 Inscriptions")
        enrolled_pct = st.slider("% étudiants inscrits", 0, 100, 90, step=5, key="sd_enrolled_pct",
                                 help="Pourcentage d'étudiants ayant au moins une inscription")
        final_pct = st.slider("% inscriptions définitives", 0, 100, 65, step=5, key="sd_final_pct")
        discount_pct = st.slider("% étudiants avec remise", 0, 100, 30, step=5, key="sd_discount_pct")

        st.markdown("#### 📊 Modules & Séances")
        module_coverage_pct = st.slider("Couverture modules (%)", 0, 100, 100, step=10, key="sd_module_cov",
                                        help="0% = aucun module · 100% = tous les modules")
        sequence_coverage_pct = st.slider("Couverture séances (%)", 0, 100, 100, step=10, key="sd_sequence_cov",
                                          help="0% = aucune séance · 100% = planification complète")
        sequence_publish_pct = st.slider("Séances publiées (%)", 0, 100, 100, step=10, key="sd_seq_publish",
                                          help="0% = brouillon · 100% = toutes publiées")
        include_calendars = st.checkbox("Calendriers de contraintes", value=True, key="sd_include_calendars",
                                        help="Vacances scolaires et jours fériés par zone (A/B/C)")

        st.markdown("#### 🚫 Absences & Retards")
        absence_rate_pct = st.slider("Taux d'absence (%)", 0, 30, 8, key="sd_absence_rate",
                                     help="% d'étudiants absents par séance (0 = aucune absence)")
        delay_rate_pct = st.slider("Taux de retard (%)", 0, 20, 5, key="sd_delay_rate",
                                   help="% d'étudiants en retard par séance (0 = aucun retard)")

        st.markdown("#### 📈 Notes")
        scores_per_formation = st.slider("Relevés de notes par formation", 0, 20, 5, key="sd_scores_per_fm",
                                         help="Modules aléatoires sélectionnés pour les relevés")
        include_compound = st.checkbox("Inclure des notes composées", value=True, key="sd_compound_scores")
        include_report_cards = st.checkbox("📋 Générer des bulletins de notes", value=True, key="sd_report_cards",
                                           help="Bulletins par semestre avec structure UE, assignation des notes et publication")
        include_degrees = st.checkbox("🎓 Diplômes (degrees)", value=True, key="sd_degrees",
                                      help="Créer des diplômes et certifications liés aux formules")

    st.divider()

    # ── Récapitulatif ──
    total_campuses = sum(campus_counts)

    # Generate a preview config to get accurate counts
    import importlib
    import seed_lib as _sl
    importlib.reload(_sl)
    # Build formation_indices for standard seeder (None = all, list = subset)
    _sd_formation_indices = list(range(n_formations_per_school)) if n_formations_per_school < _max_fm else None
    _preview = _sl.generate_default_config(
        n_schools=n_schools,
        campus_counts=campus_counts,
        themes=themes,
        n_students=n_students,
        n_employees=n_employees,
        n_companies=n_companies,
        formation_hours_min=formation_hours_min,
        formation_hours_max=formation_hours_max,
        avg_discounts=avg_discounts,
        formations_per_formula=formations_per_formula,
        n_centers=n_centers,
        formulas_per_campus=formulas_per_campus,
        formation_indices=_sd_formation_indices,
        include_degrees=include_degrees,
    )
    n_formations = len(_preview["formations"])
    n_formulas = len(_preview["formulas"])
    n_total_fm_keys = sum(len(f.get("formation_keys", [])) for f in _preview["formulas"])
    n_degrees = sum(1 for f in _preview["formulas"] if f.get("degree"))

    st.markdown(f"### 📋 Récapitulatif — {academic_year_start}-{academic_year_end}")
    recap_cols = st.columns(4)
    with recap_cols[0]:
        st.metric("Écoles", n_schools)
        st.metric("Campus", total_campuses)
        st.metric("Centres", n_centers)
        st.metric("Sociétés", n_companies)
    with recap_cols[1]:
        st.metric("Formations", n_formations)
        st.metric("Formules", n_formulas)
        st.metric("Formations/formule", f"~{n_total_fm_keys / n_formulas:.1f}" if n_formulas else "—")
        st.metric("Salles", n_centers * rooms_per_center)
    with recap_cols[2]:
        st.metric("Étudiants", n_students)
        st.metric("Employés", n_employees)
        st.metric("Employeurs", n_employers)
        st.metric("Mineurs", f"~{max(1, int(n_students * minor_pct / 100))}")
    with recap_cols[3]:
        n_inscriptions = int(n_students * enrolled_pct / 100)
        st.metric("Inscriptions", f"~{n_inscriptions}")
        st.metric("Modules", f"{module_coverage_pct}%")
        st.metric("Diplômes", n_degrees if include_degrees else "—")

    st.divider()

    # ── Action buttons ──
    action_cols = st.columns([2, 1, 1])
    with action_cols[0]:
        if st.button("🚀 Lancer le seed", type="primary", use_container_width=True, disabled=is_running):
            # Generate config from sliders
            params = {
                "academic_year_start": academic_year_start,
                "academic_year_end": academic_year_end,
                "n_schools": n_schools,
                "campus_counts": campus_counts,
                "themes": themes,
                "n_students": n_students,
                "student_dataset": "standard",
                "n_employees": n_employees,
                "employee_dataset": "standard",
                "n_employers": n_employers,
                "employer_dataset": "standard",
                "final_pct": final_pct,
                "discount_pct": discount_pct,
                "minor_pct": minor_pct,
                "scores_mean": 1200,
                "scores_std": 300,
                "absent_rate": 3,
                "enrolled_pct": enrolled_pct,
                "formulas_per_campus": formulas_per_campus,
                "formation_indices": _sd_formation_indices,
                "avg_discounts": avg_discounts,
                "n_centers": n_centers,
                "formations_per_formula": formations_per_formula,
                "formation_hours_min": formation_hours_min,
                "formation_hours_max": formation_hours_max,
                "module_coverage_pct": module_coverage_pct,
                "sequence_coverage_pct": sequence_coverage_pct,
                "sequence_publish_pct": sequence_publish_pct,
                "scores_per_formation": scores_per_formation,
                "include_compound_scores": include_compound,
                "include_report_cards": include_report_cards,
                "include_calendars": include_calendars,
                "include_avatars": include_avatars,
                "include_degrees": include_degrees,
                "absence_rate_pct": absence_rate_pct,
                "delay_rate_pct": delay_rate_pct,
                "n_companies": n_companies,
                "api_url": st.session_state.get("api_url", ""),
                "api_key": st.session_state.get("api_key", ""),
            }
            new_config = generate_config_from_ui(params)

            # Override rooms config with slider values
            new_config["centers"]["rooms_per_campus"] = rooms_per_center
            avg_cap = total_capacity // rooms_per_center if rooms_per_center > 0 else 30
            new_config["centers"]["capacity_range"] = [max(10, avg_cap // 3), avg_cap * 2]

            save_config_file(new_config)

            # Build pipeline queue — defaults first, then seeders
            queue = [s["id"] for s in DEFAULT_SCRIPTS]
            for s in SEEDER_SCRIPTS:
                if s["id"] == "seed_teaching_units" and module_coverage_pct == 0:
                    continue
                if s["id"] == "seed_sequences" and sequence_coverage_pct == 0:
                    continue
                if s["id"] == "seed_absences" and absence_rate_pct == 0 and delay_rate_pct == 0:
                    continue
                if s["id"] == "seed_scores" and scores_per_formation == 0:
                    continue
                if s["id"] == "seed_report_cards" and not include_report_cards:
                    continue
                queue.append(s["id"])

            # Reset statuses
            for s in SEEDER_SCRIPTS:
                st.session_state.statuses[s["id"]] = "not_run"
                st.session_state.outputs[s["id"]] = ""

            st.session_state.run_mode = "live_seeder"
            st.session_state.run_queue = queue
            st.session_state.run_queue_idx = 0
            st.rerun()

    with action_cols[1]:
        if st.button("💣 Remettre à zéro", disabled=is_running, use_container_width=True):
            st.session_state.confirm_reset = True
            st.rerun()
    with action_cols[2]:
        if st.button("🔄 Reset statuts", use_container_width=True, key="reset_seeder_statuses"):
            for s in SEEDER_SCRIPTS:
                st.session_state.statuses[s["id"]] = "not_run"
                st.session_state.outputs[s["id"]] = ""
            st.rerun()

    # Reset confirmation
    if st.session_state.get("confirm_reset"):
        st.warning("⚠️ **Remise à zéro complète** — Suppression de toutes les données.")
        confirm_cols = st.columns([1, 1, 3])
        with confirm_cols[0]:
            if st.button("✅ Confirmer", type="primary", use_container_width=True, key="confirm_reset_seeder"):
                st.session_state.confirm_reset = False
                st.session_state.run_mode = "live_reset"
                st.rerun()
        with confirm_cols[1]:
            if st.button("❌ Annuler", use_container_width=True, key="cancel_reset_seeder"):
                st.session_state.confirm_reset = False
                st.rerun()

    # Show previous outputs
    has_output = any(st.session_state.outputs.get(s["id"], "") for s in SEEDER_SCRIPTS)
    if has_output:
        st.divider()
        st.markdown("### 📜 Dernière exécution")
        for script in SEEDER_SCRIPTS:
            sid = script["id"]
            status = st.session_state.statuses.get(sid, "not_run")
            output = st.session_state.outputs.get(sid, "")
            if output:
                icon = STATUS_ICONS.get(status, "⚪")
                with st.expander(f"{icon} {script['order']}. {script['name']}", expanded=(status == "error")):
                    st.code(output, language=None)


    # (render_seeder_execution removed — replaced by render_live_pipeline)


# ============================================================================
# Tab 3: Seeder Poudlard
# ============================================================================

def _inject_poudlard_css():
    """Inject Harry Potter-themed CSS for the Poudlard tab."""
    st.markdown("""
    <style>
    .poudlard-header {
        background: linear-gradient(135deg, #1a0a2e 0%, #2d1b4e 50%, #4a2c72 100%);
        border: 2px solid #c9a84c;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1.5rem;
        color: #f0e6d2;
    }
    .poudlard-header h2 {
        color: #c9a84c !important;
        margin: 0 0 0.3rem 0;
        font-size: 1.6rem;
    }
    .poudlard-header p {
        color: #d4c4a8;
        margin: 0;
        font-size: 0.95rem;
    }
    .poudlard-recap {
        background: linear-gradient(135deg, #1a0a2e 0%, #2d1b4e 100%);
        border: 1px solid #7B1FA2;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        margin-bottom: 1rem;
    }
    .poudlard-recap h3 {
        color: #c9a84c !important;
        margin-top: 0;
    }
    </style>
    """, unsafe_allow_html=True)


def render_poudlard_tab():
    is_running = st.session_state.running_script_id is not None

    # If in live poudlard mode, show the live pipeline
    if st.session_state.run_mode == "live_poudlard":
        render_live_pipeline(SEEDER_SCRIPTS, "Seeder Poudlard")
        return

    # If in live reset mode (shared), show the live reset
    if st.session_state.run_mode == "live_reset":
        render_live_reset(key_suffix="_poudlard")
        return

    _inject_poudlard_css()

    st.markdown("""
    <div class="poudlard-header">
        <h2>⚡ Poudlard — École de Sorcellerie</h2>
        <p>Bienvenue au Château de Poudlard. Configurez votre promotion de sorciers ci-dessous.</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Quick Setup ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### 🏰 École & Campus")
        st.info("**1 école** — Poudlard — École de Sorcellerie")
        pd_campuses = st.slider("Campus magiques", 1, 3, 1, key="pd_campuses",
                                help="Pré-au-Lard · Londres · Godric's Hollow")

        year_cols = st.columns(2)
        with year_cols[0]:
            pd_year_start = st.number_input("Année de début", min_value=2020, max_value=2035,
                                            value=2025, key="pd_year_start")
        with year_cols[1]:
            pd_year_end = st.number_input("Année de fin", min_value=pd_year_start + 1,
                                          max_value=pd_year_start + 3,
                                          value=pd_year_start + 1, key="pd_year_end")

        st.markdown("#### 🏛️ Salles & Lieux")
        pd_rooms = st.slider("Salles par centre", 1, 8, 4, key="pd_rooms",
                             help="Grande Salle, Cachots, Tour d'Astronomie, Salle sur Demande…")

        st.markdown("#### 📚 Formations")
        # Poudlard formations classified by duration:
        # Short (≤250h): index 1 Prépa Init (220h), index 2 Prépa Approf (220h), index 6 Stage (140h)
        # Medium (250-500h): index 3 ASPIC (400h), index 4 Quidditch (300h), index 5 Master (500h)
        # Long (>500h): index 0 Tronc commun BUSE (1000h)
        pd_short = st.checkbox("📗 Courtes (≤250h)", value=True, key="pd_short",
                               help="Prépa Initiation (220h), Prépa Approfondissement (220h), Stage (140h)")
        pd_medium = st.checkbox("📙 Moyennes (250-500h)", value=True, key="pd_medium",
                                help="ASPIC (400h), Quidditch (300h), Master Magie (500h)")
        pd_long = st.checkbox("📕 Longues (>500h)", value=True, key="pd_long",
                              help="Tronc commun BUSE (1000h)")

        # Build formation_indices based on checkboxes
        _pd_formation_indices = []
        if pd_long:
            _pd_formation_indices.extend([0])         # BUSE 1000h
        if pd_short:
            _pd_formation_indices.extend([1, 2, 6])   # Prépa Init, Prépa Approf, Stage
        if pd_medium:
            _pd_formation_indices.extend([3, 4, 5])    # ASPIC, Quidditch, Master
        # Ensure at least one category selected
        if not _pd_formation_indices:
            st.warning("⚠️ Sélectionnez au moins un type de formation")
            _pd_formation_indices = [0]  # fallback: BUSE

        # Sort to keep original order
        _pd_formation_indices.sort()
        if len(_pd_formation_indices) > 1:
            pd_n_formations = st.slider("Nombre de formations", 1, len(_pd_formation_indices),
                                        min(len(_pd_formation_indices), 7), key="pd_n_formations",
                                        help=f"{len(_pd_formation_indices)} formations disponibles dans les catégories sélectionnées")
        else:
            pd_n_formations = len(_pd_formation_indices)
        # Trim to requested count
        _pd_formation_indices = _pd_formation_indices[:pd_n_formations]

        st.markdown("#### 📜 Formules & Remises")
        # Max formulas depends on which formations are selected (formulas need their formations)
        from seed_lib import FORMULA_TEMPLATES as _PD_FML_TPL
        _pd_fml_all = _PD_FML_TPL.get("poudlard", [])
        _pd_fml_avail = [f for f in _pd_fml_all
                         if all(idx in _pd_formation_indices for idx in f["formation_indices"])]
        _pd_max_fml = len(_pd_fml_avail)
        if _pd_max_fml > 1:
            pd_n_formulas = st.slider("Nombre de formules", 1, _pd_max_fml,
                                      min(_pd_max_fml, 5), key="pd_n_formulas",
                                      help=f"{_pd_max_fml} formules possibles avec les formations sélectionnées")
        elif _pd_max_fml == 1:
            pd_n_formulas = 1
            st.info(f"1 formule compatible : **{_pd_fml_avail[0]['name_tpl'].split('—')[0].strip()}**")
        else:
            pd_n_formulas = 0
            st.warning("⚠️ Aucune formule compatible avec les formations sélectionnées")
        pd_discounts = st.slider("Remises par formule", 0, 3, 2, key="pd_discounts",
                                 help="Bourse Ministère, Fratrie sorcière, Bourse Dumbledore…")

    with col_right:
        st.markdown("#### 🧙 Sorciers & Staff")
        pd_students = st.slider("Élèves sorciers", 10, 76, 50, step=5, key="pd_students",
                                help="76 personnages HP max (Gryffondor, Serpentard, Serdaigle, Poufsouffle)")
        pd_employees = st.slider("Staff de Poudlard", 8, 20, 15, key="pd_employees",
                                 help="Dumbledore, McGonagall, Rogue, Hagrid… (20 max)")
        pd_employers = st.slider("Entreprises magiques", 0, 15, 10, key="pd_employers",
                                 help="Gringotts, Gazette, Honeydukes, Ministère… (15 max)")
        pd_minor_pct = st.slider("% élèves mineurs", 0, 20, 5, key="pd_minor_pct")
        pd_avatars = st.checkbox("📷 Avatars (Wiki Harry Potter)", value=True, key="pd_avatars",
                                 help="Photos des personnages depuis le wiki HP (~1s/personnage)")

        st.markdown("#### 📝 Inscriptions")
        pd_enrolled = st.slider("% inscrits", 50, 100, 90, step=5, key="pd_enrolled")
        pd_final = st.slider("% inscriptions définitives", 30, 100, 65, step=5, key="pd_final")
        pd_discount_pct = st.slider("% avec remise", 0, 100, 30, step=5, key="pd_discount_pct")

        st.markdown("#### 📊 Cours & Séances")
        pd_module_cov = st.slider("Couverture modules (%)", 0, 100, 100, step=10, key="pd_mod_cov",
                                  help="Sortilèges, Potions, Métamorphose, DCFM…")
        pd_seq_cov = st.slider("Couverture séances (%)", 0, 100, 100, step=10, key="pd_seq_cov")
        pd_seq_publish = st.slider("Séances publiées (%)", 0, 100, 100, step=10, key="pd_seq_publish",
                                   help="0% = brouillon · 100% = toutes publiées")
        pd_calendars = st.checkbox("📅 Calendriers (vacances sorcières)", value=True, key="pd_calendars")

        st.markdown("#### 🚫 Absences & Retards")
        pd_absence = st.slider("Taux d'absence (%)", 0, 30, 8, key="pd_absence")
        pd_delay = st.slider("Taux de retard (%)", 0, 20, 5, key="pd_delay")

        st.markdown("#### 📈 Notes & Bulletins")
        pd_scores = st.slider("Relevés par formation", 0, 20, 5, key="pd_scores",
                              help="Contrôles de baguette, Examens BUSE, Épreuves ASPIC…")
        pd_compound = st.checkbox("Notes composées", value=True, key="pd_compound")
        pd_report_cards = st.checkbox("📋 Bulletins de notes", value=True, key="pd_report_cards")
        pd_degrees = st.checkbox("🎓 Diplômes (BUSE, ASPIC…)", value=True, key="pd_degrees",
                                  help="Brevet Universel de Sorcellerie, ASPIC, Master en Magie Avancée…")

    st.divider()

    # ── Recap ──
    import importlib
    import seed_lib as _sl
    importlib.reload(_sl)
    _preview = _sl.generate_default_config(
        n_schools=1,
        campus_counts=[pd_campuses],
        themes=["poudlard"],
        n_students=pd_students,
        n_employees=pd_employees,
        n_companies=1,
        avg_discounts=pd_discounts,
        formation_indices=_pd_formation_indices,
        formulas_per_campus=pd_n_formulas if pd_n_formulas < _pd_max_fml else None,
        include_degrees=pd_degrees,
    )
    n_formations = len(_preview["formations"])
    n_formulas = len(_preview["formulas"])
    n_pd_degrees = sum(1 for f in _preview["formulas"] if f.get("degree"))

    st.markdown(f"""
    <div class="poudlard-recap">
        <h3>⚡ Récapitulatif — {pd_year_start}-{pd_year_end}</h3>
    </div>
    """, unsafe_allow_html=True)

    recap_cols = st.columns(4)
    with recap_cols[0]:
        st.metric("🏰 École", "Poudlard")
        st.metric("Campus", pd_campuses)
        st.metric("Salles", pd_campuses * pd_rooms)
    with recap_cols[1]:
        _fm_cats = []
        if pd_long:
            _fm_cats.append("📕")
        if pd_medium:
            _fm_cats.append("📙")
        if pd_short:
            _fm_cats.append("📗")
        st.metric("Formations", f"{n_formations} ({' '.join(_fm_cats)})")
        st.metric("Formules", n_formulas)
    with recap_cols[2]:
        st.metric("🧙 Sorciers", pd_students)
        st.metric("Staff", pd_employees)
        st.metric("🏢 Entreprises", pd_employers)
        st.metric("Mineurs", f"~{max(1, int(pd_students * pd_minor_pct / 100))}")
    with recap_cols[3]:
        n_inscriptions = int(pd_students * pd_enrolled / 100)
        st.metric("Inscriptions", f"~{n_inscriptions}")
        st.metric("Modules", f"{pd_module_cov}%")
        st.metric("🎓 Diplômes", n_pd_degrees if pd_degrees else "—")

    st.divider()

    # ── Action Buttons ──
    action_cols = st.columns([2, 1, 1])
    with action_cols[0]:
        if st.button("⚡ Lancer le seed magique", type="primary", use_container_width=True,
                     disabled=is_running, key="pd_launch"):
            params = {
                "academic_year_start": pd_year_start,
                "academic_year_end": pd_year_end,
                "n_schools": 1,
                "campus_counts": [pd_campuses],
                "themes": ["poudlard"],
                "n_students": pd_students,
                "student_dataset": "poudlard",
                "n_employees": pd_employees,
                "employee_dataset": "poudlard",
                "n_employers": pd_employers,
                "employer_dataset": "poudlard",
                "final_pct": pd_final,
                "discount_pct": pd_discount_pct,
                "minor_pct": pd_minor_pct,
                "scores_mean": 1200,
                "scores_std": 300,
                "absent_rate": 3,
                "enrolled_pct": pd_enrolled,
                "avg_discounts": pd_discounts,
                "n_centers": pd_campuses,
                "formation_indices": _pd_formation_indices,
                "formulas_per_campus": pd_n_formulas if pd_n_formulas < _pd_max_fml else None,
                "formations_per_formula": 1,
                "formation_hours_min": 100,
                "formation_hours_max": 1200,
                "module_coverage_pct": pd_module_cov,
                "sequence_coverage_pct": pd_seq_cov,
                "sequence_publish_pct": pd_seq_publish,
                "scores_per_formation": pd_scores,
                "include_compound_scores": pd_compound,
                "include_report_cards": pd_report_cards,
                "include_calendars": pd_calendars,
                "include_avatars": pd_avatars,
                "include_degrees": pd_degrees,
                "absence_rate_pct": pd_absence,
                "delay_rate_pct": pd_delay,
                "n_companies": 1,
                "api_url": st.session_state.get("api_url", ""),
                "api_key": st.session_state.get("api_key", ""),
            }
            new_config = generate_config_from_ui(params)

            new_config["centers"]["rooms_per_campus"] = pd_rooms
            avg_cap = 120 // pd_rooms if pd_rooms > 0 else 30
            new_config["centers"]["capacity_range"] = [max(10, avg_cap // 3), avg_cap * 2]

            save_config_file(new_config)

            # Build pipeline queue
            queue = [s["id"] for s in DEFAULT_SCRIPTS]
            for s in SEEDER_SCRIPTS:
                if s["id"] == "seed_teaching_units" and pd_module_cov == 0:
                    continue
                if s["id"] == "seed_sequences" and pd_seq_cov == 0:
                    continue
                if s["id"] == "seed_absences" and pd_absence == 0 and pd_delay == 0:
                    continue
                if s["id"] == "seed_scores" and pd_scores == 0:
                    continue
                if s["id"] == "seed_report_cards" and not pd_report_cards:
                    continue
                queue.append(s["id"])

            for s in SEEDER_SCRIPTS:
                st.session_state.statuses[s["id"]] = "not_run"
                st.session_state.outputs[s["id"]] = ""

            st.session_state.run_mode = "live_poudlard"
            st.session_state.run_queue = queue
            st.session_state.run_queue_idx = 0
            st.rerun()

    with action_cols[1]:
        if st.button("💣 Remettre à zéro", disabled=is_running, use_container_width=True, key="pd_reset"):
            st.session_state.confirm_reset = True
            st.rerun()
    with action_cols[2]:
        if st.button("🔄 Reset statuts", use_container_width=True, key="pd_reset_statuses"):
            for s in SEEDER_SCRIPTS:
                st.session_state.statuses[s["id"]] = "not_run"
                st.session_state.outputs[s["id"]] = ""
            st.rerun()

    # Reset confirmation
    if st.session_state.get("confirm_reset"):
        st.warning("⚠️ **Remise à zéro complète** — Suppression de toutes les données.")
        confirm_cols = st.columns([1, 1, 3])
        with confirm_cols[0]:
            if st.button("✅ Confirmer", type="primary", use_container_width=True, key="confirm_reset_poudlard"):
                st.session_state.confirm_reset = False
                st.session_state.run_mode = "live_reset"
                st.rerun()
        with confirm_cols[1]:
            if st.button("❌ Annuler", use_container_width=True, key="cancel_reset_poudlard"):
                st.session_state.confirm_reset = False
                st.rerun()

    # Show previous outputs
    has_output = any(st.session_state.outputs.get(s["id"], "") for s in SEEDER_SCRIPTS)
    if has_output:
        st.divider()
        st.markdown("### 📜 Dernière exécution")
        for script in SEEDER_SCRIPTS:
            sid = script["id"]
            status = st.session_state.statuses.get(sid, "not_run")
            output = st.session_state.outputs.get(sid, "")
            if output:
                icon = STATUS_ICONS.get(status, "⚪")
                with st.expander(f"{icon} {script['order']}. {script['name']}", expanded=(status == "error")):
                    st.code(output, language=None)


# ============================================================================
# Main
# ============================================================================

def main():
    st.set_page_config(
        page_title="Neil ERP — Seed Dashboard",
        page_icon="🎛️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    init_session_state()

    st.markdown("""
    <style>
    div[data-testid="stExpander"] { border: 1px solid #333; border-radius: 8px; }
    .stCodeBlock { max-height: 400px; overflow-y: auto; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🎛️ Neil ERP — Seed Dashboard")

    # ── API connection fields (always visible) ──
    config = load_config_file()
    default_url = config.get("api", {}).get("base_url", "https://neil-claude.erp.neil.app/api") if config else "https://neil-claude.erp.neil.app/api"
    default_key = config.get("api", {}).get("key", "") if config else ""

    api_cols = st.columns([2, 2, 1])
    with api_cols[0]:
        api_url = st.text_input("🔗 URL de l'API", value=default_url, key="api_url")
    with api_cols[1]:
        api_key = st.text_input("🔑 Clé API", value=default_key, key="api_key")
    with api_cols[2]:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Sauvegarder", key="save_api", use_container_width=True):
            cfg = load_config_file() or {}
            cfg.setdefault("api", {})["base_url"] = api_url.rstrip("/")
            cfg["api"]["key"] = api_key
            save_config_file(cfg)
            st.success("Config API sauvegardée")

    # Indicateur d'instance
    _slug = instance_slug(api_url.rstrip("/") if api_url else "")
    if _slug and _slug != "default":
        st.caption(f"📌 Instance : **{_slug}** — manifeste : `manifests/seed_manifest_{_slug}.json`")
    else:
        st.caption("📌 Instance : **default** — manifeste : `seed_manifest.json`")

    st.divider()

    tab1, tab2, tab3 = st.tabs(["📋 Configuration initiale", "🚀 Seeder", "🧙 Seeder Poudlard"])

    with tab1:
        render_defaults_tab()
    with tab2:
        render_seeder_tab()
    with tab3:
        render_poudlard_tab()


if __name__ == "__main__":
    main()
