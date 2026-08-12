#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import re
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import (
    Flask, abort, jsonify, redirect, render_template, request, send_file, session
)

from database import (
    DEFAULT_SETTINGS,
    SECRET_SETTING_KEYS,
    METRIC_DEFS,
    set_team_lead,
    delete_team,
    create_team,
    delete_team_lead,
    get_meta,
    get_settings,
    get_team_definitions,
    init_db,
    list_reps,
    list_teams,
    rename_team,
    replace_reps,
    save_settings,
    save_team_builder,
    set_team_logo,
    set_meta,
    set_rep_team_assignments,
)
from sources.sample import SampleSource
from sources.tableau import TableauSource, TableauError, resolve_dates
from tableau_scheduler import start_tableau_scheduler
from themes import themes_blueprint, display_theme_state

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.register_blueprint(themes_blueprint)

APP_ROOT = Path(__file__).resolve().parent.parent
PERSISTENT_DATA_DIR = Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
TEAM_LOGO_DIR = PERSISTENT_DATA_DIR / "team-logos"
KIOSK_RESTART_REQUEST = PERSISTENT_DATA_DIR / "restart-kiosk.request"
UPDATE_DIR = PERSISTENT_DATA_DIR / "updates"
VERSION_FILE = APP_ROOT / "VERSION"

GITHUB_API_ROOT = "https://api.github.com"
HARD_CODED_GITHUB_REPO = "matijepekovic/pi-sales-leaderboard"
GITHUB_CHECK_SECONDS = 15 * 60
_GITHUB_UPDATE_LOCK = threading.Lock()
_SOURCE_REFRESH_LOCK = threading.Lock()

PIN_ITERATIONS = 200_000


# --------------------------------------------------------------------------
# Settings-page lock.
#
# The app listens on 0.0.0.0, so anyone on the office network can reach it.
# The TV display stays open (the kiosk must never see a prompt); everything
# that can change configuration or read back configuration detail requires
# the PIN once one has been set.
# --------------------------------------------------------------------------

# Endpoints the kiosk/display needs, plus the lock screen itself.
PUBLIC_ENDPOINTS = {
    "display", "api_leaderboard", "api_config", "api_team_logo",
    "health", "api_auth_status", "api_auth_unlock", "static",
    "themes.theme_asset",
    # The kiosk reports its own viewport and is deliberately unauthenticated.
    # Reading the geometry back stays behind the settings lock.
    "api_tv_geometry_report",
}


def app_secret_key():
    """Stable signing key so the unlock cookie survives a restart."""
    key = get_meta("flask_secret_key", "")
    if not key:
        key = secrets.token_hex(32)
        set_meta("flask_secret_key", key)
    return key


def hash_pin(pin, salt=None, iterations=PIN_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(pin).encode(), bytes.fromhex(salt), iterations
    ).hex()
    return f"pbkdf2${iterations}${salt}${digest}"


def verify_pin(pin, stored):
    """Constant-time check. Returns False for anything malformed."""
    try:
        algo, iterations, salt, digest = str(stored).split("$")
        if algo != "pbkdf2":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", str(pin).encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def pin_is_set():
    return bool(str(get_settings().get("settings_pin_hash") or "").strip())


def is_unlocked():
    return not pin_is_set() or bool(session.get("settings_unlocked"))


def public_settings(settings=None):
    """
    Settings safe to hand back over the network.

    Secrets are removed entirely and replaced with booleans, so a stored
    Tableau token can never be read out through the API even by someone
    already on the network.
    """
    data = dict(settings if settings is not None else get_settings())
    configured = bool(str(data.get("tableau_pat_secret") or "").strip())
    has_pin = bool(str(data.get("settings_pin_hash") or "").strip())
    for key in SECRET_SETTING_KEYS:
        data.pop(key, None)
    # Update source is appliance-owned, not user-configurable.
    data.pop("github_repo", None)
    data["tableau_pat_configured"] = configured
    data["settings_pin_set"] = has_pin
    return data


MODES = {
    "whole_office": "Whole Office",
    "team_vs_team": "Team vs Team",
    "all_teams": "All Teams",
    "per_team": "Per Team",
}

NON_DISPLAY_METRICS = {"home_branch", "title", "hire_date"}

SUM_FIELDS = {
    "issued_leads", "pitched_leads", "sold_leads",
    "gross_split", "pending_split", "net_split"
}


def metric_type_map():
    return {key: typ for key, label, typ in METRIC_DEFS}


def metric_label_map():
    return {key: label for key, label, typ in METRIC_DEFS}


def numeric(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def sort_rows(rows, metric, direction="desc"):
    # One ranking rule everywhere: highest value is always #1.
    if metric in ("rep_name", "team", "home_branch", "title", "hire_date"):
        return sorted(
            rows,
            key=lambda r: str(r.get(metric) or "").lower(),
            reverse=True
        )
    return sorted(rows, key=lambda r: numeric(r.get(metric)), reverse=True)


def safe_rate(numerator, denominator, multiplier=100):
    return (numerator / denominator * multiplier) if denominator else 0


def aggregate_team(team_name, rows, team_definition=None):
    """
    Recalculate team performance from the raw rep components.

    This intentionally does NOT average rep percentages or per-rep averages.
    If a rep is moved between teams, every derived team KPI changes correctly.
    """
    total = {
        "team": team_name,
        "team_id": (team_definition or {}).get("team_id"),
        "rep_count": len(rows),
        "leads": (team_definition or {}).get("leads", []),
        "logo_url": (team_definition or {}).get("logo_url"),
    }

    for field in SUM_FIELDS:
        total[field] = sum(numeric(r.get(field)) for r in rows)

    total["pitched_rate"] = safe_rate(total["pitched_leads"], total["issued_leads"])
    total["close_rate"] = safe_rate(total["sold_leads"], total["issued_leads"])
    total["dpl"] = (
        total["net_split"] / total["issued_leads"]
        if total["issued_leads"] else 0
    )
    total["sales_retention"] = safe_rate(total["net_split"], total["gross_split"])
    total["avg_gross_sale"] = (
        total["gross_split"] / total["sold_leads"]
        if total["sold_leads"] else 0
    )
    total["avg_net_sale"] = (
        total["net_split"] / total["sold_leads"]
        if total["sold_leads"] else 0
    )
    return total


def get_leader_candidates():
    """
    Build the leader dropdown from Tableau/source data.

    Priority sources:
    1. Distinct Tableau Team Lead Name values already attached to rep rows.
    2. People whose Tableau title looks like a manager / SMIT.
    3. Existing saved Pi leaders, so a temporary Tableau omission does not
       make a saved leader disappear from the dropdown.
    """
    candidates = {}

    for rep in list_reps():
        tableau_lead = str(rep.get("team_lead") or "").strip()
        if tableau_lead:
            candidates.setdefault(
                tableau_lead.lower(),
                {"name": tableau_lead, "source": "Tableau Team Lead"}
            )

        title = str(rep.get("title") or "").strip()
        title_l = title.lower()
        if any(token in title_l for token in ("manager", "smit", "manager in training")):
            rep_name = str(rep.get("rep_name") or "").strip()
            if rep_name:
                candidates.setdefault(
                    rep_name.lower(),
                    {"name": rep_name, "source": title or "Tableau"}
                )

    for team in get_team_definitions():
        leader = team.get("leader")
        if leader and leader.get("lead_name"):
            name = str(leader["lead_name"]).strip()
            candidates.setdefault(
                name.lower(),
                {"name": name, "source": leader.get("lead_role") or "Saved Leader"}
            )

    return sorted(candidates.values(), key=lambda x: x["name"].lower())


def team_definitions_for_api():
    teams = get_team_definitions()
    reps = list_reps()

    # Effective membership includes:
    # - persistent Pi assignment when one exists
    # - Tableau/source team as fallback when there is no Pi assignment
    effective_members = {}
    for rep in reps:
        tid = rep.get("team_id")
        if tid:
            effective_members.setdefault(int(tid), []).append(rep.get("rep_key"))

    for team in teams:
        tid = int(team["team_id"])
        team["member_rep_keys"] = effective_members.get(tid, [])
        team["logo_url"] = (
            f"/api/teams/{tid}/logo?v={int(get_meta('organization_version','0'))}"
            if team.get("logo_path") else None
        )
    return teams


def organization_maps():
    defs = team_definitions_for_api()
    return defs, {t["name"]: t for t in defs}


def split_active_mode(value):
    value = str(value or "").strip()
    if value.startswith("per_team::"):
        return "per_team", value.split("::", 1)[1].strip()
    return value, ""


def get_mode_payload(mode=None, sort_metric_override=None, team_vs_team_override=None):
    settings = get_settings()

    raw_mode = mode if mode is not None else settings.get("active_mode", "whole_office")
    parsed_mode, parsed_team = split_active_mode(raw_mode)

    mode = parsed_mode if parsed_mode in MODES else "whole_office"
    selected_team_from_mode = parsed_team

    reps = list_reps()
    numeric_sort_metrics = {
        key for key, _, typ in METRIC_DEFS
        if typ in ("number", "percent", "currency") and key != "rank"
    }
    metric = settings["sort_metric"].get(mode, "net_split")
    if sort_metric_override in numeric_sort_metrics:
        metric = sort_metric_override
    direction = "desc"
    visible = [
        key for key in settings["visible_metrics"].get(mode, [])
        if key not in NON_DISPLAY_METRICS
    ]
    team_defs, team_by_name = organization_maps()

    if mode == "whole_office":
        ranked = sort_rows(reps, metric, direction)
        return {
            "mode": mode,
            "mode_label": MODES[mode],
            "metrics": visible,
            "rows": ranked,
            "teams": [],
            "office_summary": aggregate_team("WHOLE OFFICE", reps, None),
        }

    grouped = {t["name"]: [] for t in team_defs}
    for rep in reps:
        grouped.setdefault(rep.get("team") or "Unassigned", []).append(rep)

    if mode == "team_vs_team":
        # Head-to-head is always exactly a maximum of two teams.
        # The SAME metric + direction rank both levels:
        #   - members inside each team
        #   - the two aggregate team summaries
        requested_pair = (
            team_vs_team_override
            if isinstance(team_vs_team_override, (list, tuple))
            else None
        )
        selected = list(dict.fromkeys(
            requested_pair or settings.get("team_vs_team_selected") or []
        ))[:2]
        if not selected:
            selected = [t["name"] for t in team_defs[:2]]

        teams = []
        for team_name in selected:
            members = grouped.get(team_name, [])
            definition = team_by_name.get(team_name)
            if not members and not definition:
                continue
            teams.append({
                "summary": aggregate_team(team_name, members, definition),
                "members": sort_rows(members, metric, direction),
            })
        teams.sort(
            key=lambda t: numeric(t["summary"].get(metric)),
            reverse=True
        )
        numeric_types = {"number", "percent", "currency"}
        type_map = metric_type_map()
        selected_numeric = [
            key for key in visible
            if type_map.get(key) in numeric_types
        ]

        return {
            "mode": mode,
            "mode_label": MODES[mode],
            "metrics": visible,
            "rows": [],
            "teams": teams[:2],
            "show_members": True,
            # One selector controls both levels of the head-to-head display.
            "team_total_metrics": selected_numeric,
            "rep_stat_metrics": selected_numeric,
            "team_rank_metric": metric,
            "team_rank_direction": direction,
        }

    if mode == "per_team":
        selected_team = selected_team_from_mode or settings.get("per_team_selected") or ""
        if not selected_team and team_defs:
            selected_team = team_defs[0]["name"]

        members = grouped.get(selected_team, [])
        definition = team_by_name.get(selected_team)
        ranked = sort_rows(members, metric, direction)
        return {
            "mode": mode,
            "mode_label": f"{MODES[mode]} — {selected_team}" if selected_team else MODES[mode],
            "metrics": visible,
            "rows": ranked,
            "teams": [],
            "selected_team": selected_team,
            "team_summary": aggregate_team(selected_team, members, definition)
                if selected_team else None,
        }

    # all_teams
    teams = []
    for team_name, members in grouped.items():
        definition = team_by_name.get(team_name)
        if not members and not definition:
            continue
        teams.append({
            "summary": aggregate_team(team_name, members, definition),
            "members": sort_rows(members, metric, direction),
        })
    teams.sort(
        key=lambda t: numeric(t["summary"].get(metric)),
        reverse=True
    )
    return {
        "mode": mode,
        "mode_label": MODES[mode],
        "metrics": visible,
        "rows": [],
        "teams": teams,
    }



def normalize_github_repo(value):
    """
    Accept:
      owner/repo
      https://github.com/owner/repo
      https://github.com/owner/repo.git
    Return owner/repo.
    """
    value = str(value or "").strip()
    if not value:
        return ""

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        if parsed.netloc.lower() not in ("github.com", "www.github.com"):
            raise ValueError("Use a public github.com repository.")
        value = parsed.path.strip("/")

    if value.endswith(".git"):
        value = value[:-4]

    parts = [p for p in value.split("/") if p]
    if len(parts) != 2:
        raise ValueError("GitHub repository must look like username/repository.")

    owner, repo = parts
    valid = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not valid.match(owner) or not valid.match(repo):
        raise ValueError("GitHub repository name contains invalid characters.")

    return f"{owner}/{repo}"


def github_api_json(path, timeout=20):
    url = f"{GITHUB_API_ROOT}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pi-tableau-sales-leaderboard",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError("GitHub repo/file not found. Make sure the repo is public and the name is correct.")
        if exc.code == 403:
            raise ValueError("GitHub temporarily refused the check. Try again later.")
        raise ValueError(f"GitHub returned HTTP {exc.code}.")
    except urllib.error.URLError as exc:
        raise ValueError(f"Could not reach GitHub: {exc.reason}")


def version_key(value):
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(p) for p in parts) if parts else (0,)


def github_remote_info(repo_value):
    repo = normalize_github_repo(repo_value)

    repo_info = github_api_json(f"/repos/{repo}")
    default_branch = str(repo_info.get("default_branch") or "main")

    encoded_branch = urllib.parse.quote(default_branch, safe="")
    version_info = github_api_json(
        f"/repos/{repo}/contents/VERSION?ref={encoded_branch}"
    )

    encoded = str(version_info.get("content") or "").replace("\n", "")
    if not encoded:
        raise ValueError("VERSION file is missing from the GitHub repo.")

    try:
        remote_version = base64.b64decode(encoded).decode("utf-8").strip()
    except Exception:
        raise ValueError("Could not read the VERSION file from GitHub.")

    if not remote_version:
        raise ValueError("GitHub VERSION file is empty.")

    return {
        "repo": repo,
        "branch": default_branch,
        "version": remote_version,
    }


def download_github_repo_zip(repo, branch, destination):
    encoded_branch = urllib.parse.quote(branch, safe="")
    url = f"{GITHUB_API_ROOT}/repos/{repo}/zipball/{encoded_branch}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pi-tableau-sales-leaderboard",
        },
    )
    try:
        # urllib follows GitHub's archive redirect automatically.
        with urllib.request.urlopen(req, timeout=60) as resp, open(destination, "wb") as out:
            shutil.copyfileobj(resp, out)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Could not download GitHub update (HTTP {exc.code}).")
    except urllib.error.URLError as exc:
        raise ValueError(f"Could not download GitHub update: {exc.reason}")


def check_github_update(install=False):
    """
    Check the built-in PUBLIC GitHub repository.

    Updates are driven by the VERSION file. If the GitHub VERSION is greater
    than the installed VERSION, the main/default branch archive is installed.
    """
    repo_value = HARD_CODED_GITHUB_REPO

    if not _GITHUB_UPDATE_LOCK.acquire(blocking=False):
        return {
            "ok": True,
            "busy": True,
            "message": "An update check is already running.",
        }

    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        set_meta("github_last_check", now)
        set_meta("github_update_status", "Checking GitHub…")

        remote = github_remote_info(repo_value)
        local_version = software_version()
        remote_version = remote["version"]
        set_meta("github_remote_version", remote_version)

        update_available = version_key(remote_version) > version_key(local_version)

        if not update_available:
            status = f"Up to date — v{local_version}"
            set_meta("github_update_status", status)
            return {
                "ok": True,
                "repo": remote["repo"],
                "branch": remote["branch"],
                "installed_version": local_version,
                "remote_version": remote_version,
                "update_available": False,
                "installed": False,
                "message": status,
            }

        if not install:
            status = f"Update available — v{remote_version}"
            set_meta("github_update_status", status)
            return {
                "ok": True,
                "repo": remote["repo"],
                "branch": remote["branch"],
                "installed_version": local_version,
                "remote_version": remote_version,
                "update_available": True,
                "installed": False,
                "message": status,
            }

        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix="github-update-",
            suffix=".zip",
            dir=str(UPDATE_DIR),
        )
        os.close(fd)
        temp_path = Path(temp_name)

        try:
            set_meta("github_update_status", f"Downloading v{remote_version}…")
            download_github_repo_zip(remote["repo"], remote["branch"], temp_path)

            set_meta("github_update_status", f"Installing v{remote_version}…")
            result = install_update_zip(temp_path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

        set_meta("github_update_status", f"Installed v{remote_version}; restarting…")

        return {
            "ok": True,
            "repo": remote["repo"],
            "branch": remote["branch"],
            "installed_version": local_version,
            "remote_version": remote_version,
            "update_available": True,
            "installed": True,
            "message": f"Installed v{result.get('version') or remote_version}.",
        }
    except Exception as exc:
        set_meta("github_update_status", f"GitHub update error: {exc}")
        raise
    finally:
        _GITHUB_UPDATE_LOCK.release()


def github_auto_update_worker():
    # Let Wi-Fi and the desktop session settle after boot/restart.
    time.sleep(30)

    while True:
        try:
            settings = get_settings()
            if settings.get("github_auto_update"):
                result = check_github_update(install=True)
                if result.get("installed"):
                    # No HTTP response needs flushing for a background update.
                    time.sleep(1)
                    os._exit(0)
        except Exception:
            # Status is recorded by check_github_update. Never crash the app
            # because GitHub or the internet is temporarily unavailable.
            pass

        time.sleep(GITHUB_CHECK_SECONDS)


def start_github_auto_update_worker():
    thread = threading.Thread(
        target=github_auto_update_worker,
        name="github-auto-updater",
        daemon=True,
    )
    thread.start()



def software_version():
    try:
        return VERSION_FILE.read_text().strip() or "unknown"
    except Exception:
        return "unknown"


def _safe_zip_member(name):
    p = Path(name)
    return not p.is_absolute() and ".." not in p.parts


def _find_update_root(extract_dir):
    # Accept either:
    #   pi_tableau_leaderboard/app/server.py
    # or:
    #   app/server.py
    direct = extract_dir
    if (direct / "app" / "server.py").exists():
        return direct

    candidates = []
    for child in extract_dir.iterdir():
        if child.is_dir() and (child / "app" / "server.py").exists():
            candidates.append(child)

    if len(candidates) == 1:
        return candidates[0]
    raise ValueError("Update ZIP does not contain a valid Pi Leaderboard package.")


def install_update_zip(zip_path):
    """
    Install a normal application update without touching the persistent SQLite DB.

    The app runs as the same Linux user that owns APP_ROOT, so it can replace its
    own application files. systemd restarts it after the process exits.
    """
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pi-leaderboard-update-", dir=str(UPDATE_DIR)) as td:
        td = Path(td)
        extract_dir = td / "extract"
        extract_dir.mkdir()

        with zipfile.ZipFile(zip_path, "r") as z:
            for info in z.infolist():
                if not _safe_zip_member(info.filename):
                    raise ValueError("Unsafe path found in update ZIP.")
            z.extractall(extract_dir)

        package = _find_update_root(extract_dir)

        required = [
            package / "app" / "server.py",
            package / "app" / "database.py",
            package / "app" / "templates" / "display.html",
            package / "app" / "templates" / "settings.html",
            package / "requirements.txt",
        ]
        for p in required:
            if not p.exists():
                raise ValueError(f"Update is missing required file: {p.name}")

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_dir = UPDATE_DIR / f"backup-{timestamp}"
        backup_dir.mkdir(parents=True)

        # Backup only replaceable application files. Persistent DB is separate.
        for name in (
            "app", "requirements.txt", "VERSION", "README.md", "kiosk.sh",
            "install.sh", "uninstall.sh", "INSTALL-LEADERBOARD",
            "pi-tableau-leaderboard.service", "pi-tableau-leaderboard.desktop",
            "GITHUB_SETUP.md", ".gitignore",
        ):
            src = APP_ROOT / name
            if not src.exists():
                continue
            dst = backup_dir / name
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        try:
            # Replace app atomically enough for a local single-user appliance.
            incoming_app = package / "app"
            staged_app = APP_ROOT / ".app-new"
            old_app = APP_ROOT / ".app-old"

            shutil.rmtree(staged_app, ignore_errors=True)
            shutil.rmtree(old_app, ignore_errors=True)
            shutil.copytree(incoming_app, staged_app)

            current_app = APP_ROOT / "app"
            if current_app.exists():
                current_app.rename(old_app)
            staged_app.rename(current_app)

            # Replace supporting files when present.
            for name in (
                "requirements.txt",
                "VERSION",
                "README.md",
                "kiosk.sh",
                "install.sh",
                "uninstall.sh",
                "INSTALL-LEADERBOARD",
                "pi-tableau-leaderboard.service",
                "pi-tableau-leaderboard.desktop",
                "GITHUB_SETUP.md",
                ".gitignore",
            ):
                src = package / name
                if src.exists():
                    shutil.copy2(src, APP_ROOT / name)

            # Install any Python dependency changes into the existing venv.
            pip = APP_ROOT / ".venv" / "bin" / "pip"
            requirements = APP_ROOT / "requirements.txt"
            if pip.exists() and requirements.exists():
                result = subprocess.run(
                    [str(pip), "install", "-r", str(requirements)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=300,
                )
                if result.returncode != 0:
                    raise RuntimeError("Dependency update failed:\n" + result.stdout[-3000:])

            shutil.rmtree(old_app, ignore_errors=True)

            return {
                "version": (package / "VERSION").read_text().strip()
                    if (package / "VERSION").exists() else "unknown",
                "backup": str(backup_dir),
            }

        except Exception:
            # Restore application files from backup.
            shutil.rmtree(APP_ROOT / "app", ignore_errors=True)
            if (backup_dir / "app").exists():
                shutil.copytree(backup_dir / "app", APP_ROOT / "app")

            for name in ("requirements.txt", "VERSION", "README.md", "kiosk.sh"):
                src = backup_dir / name
                if src.exists():
                    shutil.copy2(src, APP_ROOT / name)
            raise


@app.before_request
def enforce_settings_lock():
    """
    Gate everything except the display/kiosk endpoints once a PIN is set.

    Returns 401 for API calls so the settings page can show its unlock
    prompt, and never touches the TV display.
    """
    if not pin_is_set() or is_unlocked():
        return None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "locked": True,
                        "error": "Settings are locked. Enter your PIN."}), 401
    return render_template("settings.html")


@app.get("/api/auth/status")
def api_auth_status():
    return jsonify({"ok": True, "pin_set": pin_is_set(), "unlocked": is_unlocked()})


@app.post("/api/auth/unlock")
def api_auth_unlock():
    body = request.get_json(force=True, silent=True) or {}
    stored = str(get_settings().get("settings_pin_hash") or "")
    if not stored:
        return jsonify({"ok": True, "unlocked": True})
    if not verify_pin(str(body.get("pin") or ""), stored):
        return jsonify({"ok": False, "error": "Incorrect PIN."}), 401
    session["settings_unlocked"] = True
    session.permanent = True
    return jsonify({"ok": True, "unlocked": True})


@app.post("/api/auth/lock")
def api_auth_lock():
    session.pop("settings_unlocked", None)
    return jsonify({"ok": True, "unlocked": False})


@app.post("/api/auth/pin")
def api_auth_set_pin():
    """Set, change or clear the settings PIN."""
    body = request.get_json(force=True, silent=True) or {}
    settings = get_settings()
    stored = str(settings.get("settings_pin_hash") or "")
    new_pin = str(body.get("new_pin") or "").strip()

    # Changing or clearing an existing PIN requires the current one, unless
    # this session already unlocked with it.
    if stored and not session.get("settings_unlocked"):
        if not verify_pin(str(body.get("current_pin") or ""), stored):
            return jsonify({"ok": False, "error": "Current PIN is incorrect."}), 401

    if not new_pin:
        settings["settings_pin_hash"] = ""
        save_settings(settings)
        session.pop("settings_unlocked", None)
        return jsonify({"ok": True, "pin_set": False})

    if len(new_pin) < 4 or not new_pin.isdigit():
        return jsonify({"ok": False, "error": "PIN must be at least 4 digits."}), 400

    settings["settings_pin_hash"] = hash_pin(new_pin)
    save_settings(settings)
    session["settings_unlocked"] = True
    session.permanent = True
    return jsonify({"ok": True, "pin_set": True})


@app.get("/")
def display():
    return render_template("display.html")


@app.get("/settings")
def settings_page():
    return render_template("settings.html")


@app.get("/api/state")
def api_state():
    settings = get_settings()
    return jsonify({
        "data_version": int(get_meta("data_version", "0")),
        "settings_version": int(get_meta("settings_version", "0")),
        "organization_version": int(get_meta("organization_version", "0")),
        "tv_refresh_version": int(get_meta("tv_refresh_version", "0")),
        "app_restart_version": int(get_meta("app_restart_version", "0")),
        "active_mode": settings.get("active_mode", "whole_office"),
        "last_source_refresh": get_meta("last_source_refresh"),
        "source_status": get_meta("source_status", "sample"),
    })


@app.get("/api/config")
def api_config():
    settings = public_settings()
    return jsonify({
        "settings": settings,
        "metrics": [
            {"key": key, "label": label, "type": typ}
            for key, label, typ in METRIC_DEFS
            if key not in NON_DISPLAY_METRICS
        ],
        "modes": [{"key": k, "label": v} for k, v in MODES.items()],
        "teams": list_teams(),
        "team_definitions": team_definitions_for_api(),
        "leader_candidates": get_leader_candidates(),
        "reps": [
            {
                "rep_key": r.get("rep_key"),
                "rep_name": r.get("rep_name"),
                "tableau_team": r.get("tableau_team") or "Unassigned",
                "effective_team": r.get("team") or "Unassigned",
                "effective_team_id": r.get("team_id"),
                "assigned_team_id": r.get("assigned_team_id"),
                "local_team_override": bool(r.get("local_team_override")),
            }
            for r in sorted(list_reps(), key=lambda x: str(x.get("rep_name") or "").lower())
        ],
    })


@app.put("/api/config")
def api_save_config():
    incoming = request.get_json(force=True) or {}
    current = get_settings()

    incoming_active_mode = str(incoming.get("active_mode") or "").strip()
    if incoming_active_mode in MODES or incoming_active_mode.startswith("per_team::"):
        current["active_mode"] = incoming_active_mode
        parsed_mode, parsed_team = split_active_mode(incoming_active_mode)
        if parsed_mode == "per_team" and parsed_team:
            current["per_team_selected"] = parsed_team

    if isinstance(incoming.get("title"), str):
        current["title"] = incoming["title"][:80]
    if isinstance(incoming.get("subtitle"), str):
        current["subtitle"] = incoming["subtitle"][:120]

    if isinstance(incoming.get("github_auto_update"), bool):
        current["github_auto_update"] = incoming["github_auto_update"]

    # ---- Tableau connection ------------------------------------------
    if isinstance(incoming.get("tableau_server"), str):
        server_value = incoming["tableau_server"].strip().rstrip("/")
        if server_value and not server_value.startswith(("http://", "https://")):
            server_value = "https://" + server_value
        current["tableau_server"] = server_value[:300]
    for key in ("tableau_site", "tableau_pat_name", "tableau_view"):
        if isinstance(incoming.get(key), str):
            current[key] = incoming[key].strip()[:200]

    # Write-only: an empty string means "leave the stored token alone", so
    # saving other settings never wipes the token the UI can't read back.
    if isinstance(incoming.get("tableau_pat_secret"), str):
        secret_value = incoming["tableau_pat_secret"].strip()
        if secret_value:
            current["tableau_pat_secret"] = secret_value
    if incoming.get("tableau_pat_clear") is True:
        current["tableau_pat_secret"] = ""

    # ---- Data selection ----------------------------------------------
    if isinstance(incoming.get("data_office"), str):
        current["data_office"] = incoming["data_office"].strip()[:120]

    mode = str(incoming.get("data_date_mode") or "").strip()
    if mode in ("current_month", "custom"):
        current["data_date_mode"] = mode

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for key in ("data_date_start", "data_date_end"):
        if isinstance(incoming.get(key), str):
            value = incoming[key].strip()
            if value and not date_pattern.match(value):
                return jsonify({
                    "ok": False,
                    "error": "Dates must look like YYYY-MM-DD.",
                }), 400
            current[key] = value

    if (current.get("data_date_mode") == "custom"
            and current.get("data_date_start") and current.get("data_date_end")
            and current["data_date_start"] > current["data_date_end"]):
        return jsonify({
            "ok": False,
            "error": "The start date must be on or before the end date.",
        }), 400

    for key in ("data_date_param_start", "data_date_param_end"):
        if isinstance(incoming.get(key), str):
            current[key] = incoming[key].strip()[:80]

    for key in ("data_include_people", "data_exclude_people"):
        if isinstance(incoming.get(key), list):
            names, seen = [], set()
            for value in incoming[key]:
                name = str(value).strip()[:120]
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    names.append(name)
            current[key] = names[:200]

    if isinstance(incoming.get("team_vs_team_selected"), list):
        selected = []
        for value in incoming["team_vs_team_selected"]:
            value = str(value)
            if value and value not in selected:
                selected.append(value)
        current["team_vs_team_selected"] = selected[:2]

    if isinstance(incoming.get("per_team_selected"), str):
        current["per_team_selected"] = incoming["per_team_selected"][:120]

    # Team vs Team always includes individual rep stats in v18+.
    current["show_team_members_in_vs"] = True

    valid_keys = {k for k, _, _ in METRIC_DEFS if k not in NON_DISPLAY_METRICS}
    if isinstance(incoming.get("visible_metrics"), dict):
        for mode in MODES:
            vals = incoming["visible_metrics"].get(mode)
            if isinstance(vals, list):
                current["visible_metrics"][mode] = [v for v in vals if v in valid_keys]

    if isinstance(incoming.get("sort_metric"), dict):
        numeric_keys = {
            k for k, _, typ in METRIC_DEFS
            if typ in ("number", "percent", "currency")
        }
        for mode in MODES:
            val = incoming["sort_metric"].get(mode)
            if val in numeric_keys:
                current["sort_metric"][mode] = val

    try:
        refresh = int(
            incoming.get(
                "display_refresh_seconds",
                current.get("display_refresh_seconds", 5)
            )
        )
        current["display_refresh_seconds"] = min(max(refresh, 2), 60)
    except Exception:
        pass

    current["rank_direction"] = {
        "whole_office": "desc",
        "team_vs_team": "desc",
        "all_teams": "desc",
        "per_team": "desc",
    }
    save_settings(current)
    set_meta("settings_version", int(get_meta("settings_version", "0")) + 1)
    return jsonify({"ok": True, "settings": public_settings(current)})


@app.get("/api/leaderboard")
def api_leaderboard():
    mode = request.args.get("mode")
    sort_metric_override = request.args.get("sort_metric")
    team_override = request.args.getlist("team")
    settings = get_settings()
    payload = get_mode_payload(
        mode,
        sort_metric_override=sort_metric_override,
        team_vs_team_override=team_override[:2] if team_override else None,
    )
    numeric_sort_metrics = {
        key for key, _, typ in METRIC_DEFS
        if typ in ("number", "percent", "currency") and key != "rank"
    }
    effective_sort_metric = sort_metric_override
    if effective_sort_metric not in numeric_sort_metrics:
        effective_sort_metric = settings["sort_metric"].get(payload["mode"], "net_split")
    payload.update({
        "title": settings.get("title", "SALES LEADERBOARD"),
        "subtitle": settings.get("subtitle", ""),
        "sort_metric": effective_sort_metric,
        "rank_direction": "desc",
        "currency_symbol": settings.get("currency_symbol", "$"),
        "data_version": int(get_meta("data_version", "0")),
        "settings_version": int(get_meta("settings_version", "0")),
        "organization_version": int(get_meta("organization_version", "0")),
        "tv_refresh_version": int(get_meta("tv_refresh_version", "0")),
        "app_restart_version": int(get_meta("app_restart_version", "0")),
        "metric_labels": metric_label_map(),
        "metric_types": metric_type_map(),
    })
    payload["theme_state"] = display_theme_state(settings)
    return jsonify(payload)


@app.post("/api/team-builder/save")
def api_team_builder_save():
    incoming = request.get_json(force=True) or {}
    try:
        team_id = save_team_builder(
            incoming.get("team_id"),
            incoming.get("name"),
            incoming.get("leader_name"),
            incoming.get("leader_role", "Sales Manager"),
            incoming.get("member_rep_keys", []),
        )
        return jsonify({
            "ok": True,
            "team_id": team_id,
            "team_definitions": team_definitions_for_api(),
            "teams": list_teams(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/teams/<int:team_id>/logo")
def api_upload_team_logo(team_id):
    upload = request.files.get("logo")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "Choose a logo file."}), 400

    ext = Path(upload.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return jsonify({"ok": False, "error": "Logo must be PNG, JPG, or WEBP."}), 400

    # 5 MB guard.
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > 5 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Logo must be under 5 MB."}), 400

    TEAM_LOGO_DIR.mkdir(parents=True, exist_ok=True)

    # Remove previous logo for this team.
    for old in TEAM_LOGO_DIR.glob(f"team-{team_id}.*"):
        try:
            old.unlink()
        except Exception:
            pass

    path = TEAM_LOGO_DIR / f"team-{team_id}{ext}"
    upload.save(path)
    set_team_logo(team_id, str(path))

    return jsonify({
        "ok": True,
        "logo_url": f"/api/teams/{team_id}/logo?v={int(get_meta('organization_version','0'))}",
    })


@app.delete("/api/teams/<int:team_id>/logo")
def api_delete_team_logo(team_id):
    team = next((t for t in get_team_definitions(include_inactive=True) if int(t["team_id"]) == team_id), None)
    if team and team.get("logo_path"):
        try:
            Path(team["logo_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    set_team_logo(team_id, None)
    return jsonify({"ok": True})


@app.get("/api/teams/<int:team_id>/logo")
def api_team_logo(team_id):
    team = next((t for t in get_team_definitions(include_inactive=True) if int(t["team_id"]) == team_id), None)
    if not team or not team.get("logo_path"):
        abort(404)
    path = Path(team["logo_path"])
    if not path.exists():
        abort(404)
    return send_file(path, conditional=True)


@app.post("/api/teams")
def api_create_team():
    incoming = request.get_json(force=True) or {}
    try:
        team_id = create_team(incoming.get("name"))
        return jsonify({"ok": True, "team_id": team_id, "teams": get_team_definitions()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.put("/api/teams/<int:team_id>")
def api_rename_team(team_id):
    incoming = request.get_json(force=True) or {}
    try:
        rename_team(team_id, incoming.get("name"))
        return jsonify({"ok": True, "teams": get_team_definitions()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.delete("/api/teams/<int:team_id>")
def api_delete_team(team_id):
    incoming = request.get_json(silent=True) or {}
    try:
        result = delete_team(team_id, incoming.get("reassignments", []))

        # Remove the persistent team logo after the DB transaction succeeds.
        if result.get("logo_path"):
            try:
                Path(result["logo_path"]).unlink(missing_ok=True)
            except Exception:
                pass

        # Clean display selections that referenced the deleted team.
        current = get_settings()
        deleted_name = result["name"]

        current["team_vs_team_selected"] = [
            name for name in (current.get("team_vs_team_selected") or [])
            if str(name).lower() != deleted_name.lower()
        ][:2]

        remaining_defs = get_team_definitions()
        remaining_by_id = {
            int(t["team_id"]): t["name"] for t in remaining_defs
        }
        destination_names = [
            remaining_by_id[tid]
            for tid in result.get("destination_team_ids", [])
            if tid in remaining_by_id
        ]

        # Keep Team vs Team usable by filling empty slots with destinations /
        # other remaining teams when possible.
        for candidate in destination_names + [t["name"] for t in remaining_defs]:
            if len(current["team_vs_team_selected"]) >= 2:
                break
            if candidate not in current["team_vs_team_selected"]:
                current["team_vs_team_selected"].append(candidate)

        if str(current.get("per_team_selected") or "").lower() == deleted_name.lower():
            current["per_team_selected"] = (
                destination_names[0]
                if destination_names
                else (remaining_defs[0]["name"] if remaining_defs else "")
            )

        parsed_mode, parsed_team = split_active_mode(current.get("active_mode", ""))
        if parsed_mode == "per_team" and str(parsed_team).lower() == deleted_name.lower():
            if current.get("per_team_selected"):
                current["active_mode"] = f"per_team::{current['per_team_selected']}"
            else:
                current["active_mode"] = "whole_office" 

        save_settings(current)

        return jsonify({
            "ok": True,
            "deleted_team": deleted_name,
            "reassigned_reps": result["member_count"],
            "team_definitions": team_definitions_for_api(),
            "teams": list_teams(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.put("/api/teams/<int:team_id>/leader")
def api_set_team_leader(team_id):
    incoming = request.get_json(force=True) or {}
    try:
        lead_id = set_team_lead(
            team_id,
            incoming.get("lead_name"),
            incoming.get("lead_role", "Sales Manager")
        )
        return jsonify({
            "ok": True,
            "lead_id": lead_id,
            "teams": get_team_definitions()
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.delete("/api/team-leads/<int:lead_id>")
def api_delete_team_lead(lead_id):
    try:
        delete_team_lead(lead_id)
        return jsonify({"ok": True, "teams": get_team_definitions()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.put("/api/rep-team-assignments")
def api_rep_team_assignments():
    incoming = request.get_json(force=True) or {}
    assignments = incoming.get("assignments", [])
    if not isinstance(assignments, list):
        return jsonify({"ok": False, "error": "assignments must be a list"}), 400
    try:
        set_rep_team_assignments(assignments)
        return jsonify({
            "ok": True,
            "teams": list_teams(),
            "team_definitions": team_definitions_for_api(),
            "reps": [
                {
                    "rep_key": r.get("rep_key"),
                    "rep_name": r.get("rep_name"),
                    "tableau_team": r.get("tableau_team") or "Unassigned",
                    "effective_team": r.get("team") or "Unassigned",
                    "effective_team_id": r.get("team_id"),
                    "assigned_team_id": r.get("assigned_team_id"),
                    "local_team_override": bool(r.get("local_team_override")),
                }
                for r in sorted(
                    list_reps(),
                    key=lambda x: str(x.get("rep_name") or "").lower()
                )
            ],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/source/options")
def api_source_options():
    """Offices and rep names for the selection pickers, from the last pull."""
    reps = list_reps()
    offices = sorted({
        str(r.get("home_branch") or "").strip()
        for r in reps if str(r.get("home_branch") or "").strip()
    })
    names = sorted(
        {str(r.get("rep_name") or "").strip() for r in reps if r.get("rep_name")},
        key=str.lower,
    )
    settings = get_settings()
    start, end = resolve_dates(settings)
    return jsonify({
        "ok": True,
        "offices": offices,
        "names": names,
        "effective_start": start,
        "effective_end": end,
        "source_status": get_meta("source_status", ""),
        "last_source_refresh": get_meta("last_source_refresh", ""),
        "scheduled_tableau_status": get_meta("scheduled_tableau_status", ""),
        "scheduled_tableau_last_attempt": get_meta("scheduled_tableau_last_attempt", ""),
    })


@app.post("/api/source/test")
def api_source_test():
    """Sign in and pull, reporting counts only. Nothing is written."""
    try:
        preview = TableauSource(get_settings()).preview()
    except TableauError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Tableau test failed: {exc}"}), 400

    return jsonify({
        "ok": True,
        "start": preview["start"],
        "end": preview["end"],
        "total_rows": preview["total_rows"],
        "selected_rows": preview["selected_rows"],
        "offices": preview["offices"],
        "names": preview["names"],
        "message": (
            f"Connected. {preview['total_rows']} people in {preview['start']}"
            f" to {preview['end']}; {preview['selected_rows']} match your selection."
        ),
    })


@app.post("/api/source/refresh")
def api_source_refresh():
    """Pull from Tableau with the saved selection and store the result."""
    if not _SOURCE_REFRESH_LOCK.acquire(blocking=False):
        return jsonify({"ok": False, "error": "A refresh is already running."}), 409
    try:
        settings = get_settings()
        source = TableauSource(settings)
        rows = source.fetch()
        if not rows:
            set_meta("source_status", "Tableau returned no matching people")
            return jsonify({
                "ok": False,
                "error": ("Tableau returned no people for this selection. "
                          "Check the office name and date range."),
                "total_rows": source.last_total_rows,
                "offices": source.last_offices,
            }), 400

        # Sales metrics only. Pi team assignments are untouched by design.
        replace_reps(rows)
        start, end = resolve_dates(settings)
        status = (f"Tableau — {len(rows)} people, {start} to {end}"
                  + (f", office {settings.get('data_office')}"
                     if settings.get("data_office") else ", all offices"))
        set_meta("source_status", status)
        set_meta("last_source_refresh", time.strftime("%Y-%m-%d %H:%M:%S"))
        set_meta("data_version", int(get_meta("data_version", "0")) + 1)
        return jsonify({
            "ok": True,
            "rows": len(rows),
            "total_rows": source.last_total_rows,
            "offices": source.last_offices,
            "start": start,
            "end": end,
            "message": status,
        })
    except TableauError as exc:
        set_meta("source_status", f"Tableau error: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        set_meta("source_status", f"Tableau error: {exc}")
        return jsonify({"ok": False, "error": f"Tableau refresh failed: {exc}"}), 400
    finally:
        _SOURCE_REFRESH_LOCK.release()


@app.post("/api/demo/load")
def api_load_demo():
    rows = SampleSource().fetch()
    replace_reps(rows)
    set_meta("last_source_refresh", time.strftime("%Y-%m-%d %H:%M:%S"))
    set_meta("source_status", "sample data loaded")
    return jsonify({"ok": True, "rows": len(rows)})




@app.post("/api/tv/fullscreen")
def api_tv_fullscreen():
    """
    Ask the graphical-session kiosk watchdog to relaunch Chromium with the
    Raspberry Pi labwc-compatible kiosk flags.
    """
    try:
        ensure_labwc_kiosk_autostart()
        PERSISTENT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        KIOSK_RESTART_REQUEST.write_text(str(time.time()))

        # If wtype is present, also ask the active graphical session for F11.
        # This is only a fallback for an already-open non-kiosk Chromium window.
        try:
            subprocess.run(
                ["wtype", "-k", "F11"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "message": "TV fullscreen relaunch requested.",
            "startup_status": get_meta("kiosk_startup_status", ""),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def drm_native_mode():
    """
    The connected display's native mode straight from the kernel.

    Every HDMI output publishes its supported modes, native first, at
    /sys/class/drm/card*-HDMI-A-*/modes. No extra packages and no root, and it
    still answers before the kiosk browser has ever reported in.
    """
    try:
        for modes in sorted(Path("/sys/class/drm").glob("card*-HDMI-A-*/modes")):
            status = modes.with_name("status")
            if status.exists() and status.read_text().strip() != "connected":
                continue
            first = (modes.read_text().strip().splitlines() or [""])[0]
            match = re.match(r"^(\d{3,5})x(\d{3,5})", first.strip())
            if match:
                return int(match.group(1)), int(match.group(2))
    except Exception:
        pass
    return 0, 0


@app.post("/api/tv/geometry")
def api_tv_geometry_report():
    """
    The kiosk reports its own viewport.

    Chromium runs fullscreen on the TV, so its viewport IS the usable TV shape,
    overscan included — a better answer than any mode table. Public, because
    the kiosk is deliberately unauthenticated.
    """
    body = request.get_json(force=True, silent=True) or {}
    try:
        width = int(float(body.get("w") or 0))
        height = int(float(body.get("h") or 0))
    except (TypeError, ValueError):
        width = height = 0
    if not (320 <= width <= 16384 and 240 <= height <= 16384):
        return jsonify({"ok": False, "error": "Unusable viewport size."}), 400

    set_meta("tv_viewport_w", width)
    set_meta("tv_viewport_h", height)
    set_meta("tv_viewport_seen", time.strftime("%Y-%m-%d %H:%M:%S"))
    return jsonify({"ok": True, "w": width, "h": height})


@app.get("/api/tv/geometry")
def api_tv_geometry():
    """Best available TV shape: what the kiosk saw, else the kernel, else 16:9."""
    width = int(get_meta("tv_viewport_w", "0") or 0)
    height = int(get_meta("tv_viewport_h", "0") or 0)
    source = "kiosk"

    if not (width and height):
        width, height = drm_native_mode()
        source = "drm"
    if not (width and height):
        width, height, source = 1920, 1080, "default"

    return jsonify({
        "ok": True,
        "width": width,
        "height": height,
        "aspect": round(width / height, 6) if height else 16 / 9,
        "source": source,
        "seen_at": get_meta("tv_viewport_seen", ""),
    })


@app.post("/api/tv/refresh")
def api_tv_refresh():
    version = int(get_meta("tv_refresh_version", "0")) + 1
    set_meta("tv_refresh_version", version)
    return jsonify({"ok": True, "tv_refresh_version": version})


@app.post("/api/tv/restart")
def api_tv_restart():
    """
    Reliably restart the leaderboard application itself.

    The backend runs under systemd with Restart=always. We bump a persistent
    restart counter, send the HTTP response to the phone, then deliberately
    exit this process. systemd immediately starts the app again.

    The TV page sees the changed restart counter after the server returns and
    performs a full page reload.
    """
    restart_version = int(get_meta("app_restart_version", "0")) + 1
    set_meta("app_restart_version", restart_version)

    # Also force the TV page to hard-refresh once the backend comes back.
    refresh_version = int(get_meta("tv_refresh_version", "0")) + 1
    set_meta("tv_refresh_version", refresh_version)

    def exit_for_systemd_restart():
        # os._exit exits the Waitress process cleanly from our perspective.
        # systemd's Restart=always launches a fresh copy.
        os._exit(0)

    # Give the JSON response time to reach the phone first.
    threading.Timer(1.2, exit_for_systemd_restart).start()

    return jsonify({
        "ok": True,
        "message": "Leaderboard app is restarting.",
        "app_restart_version": restart_version,
    })


@app.get("/api/github/status")
def api_github_status():
    settings = get_settings()
    return jsonify({
        "ok": True,
        "auto_update": bool(settings.get("github_auto_update")),
        "installed_version": software_version(),
        "remote_version": get_meta("github_remote_version", ""),
        "last_check": get_meta("github_last_check", ""),
        "status": get_meta("github_update_status", "Not configured"),
        "check_minutes": int(GITHUB_CHECK_SECONDS / 60),
    })


@app.post("/api/github/check")
def api_github_check():
    try:
        result = check_github_update(install=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if result.get("installed"):
        # Flush response, then systemd restarts the newly installed app.
        threading.Timer(1.5, lambda: os._exit(0)).start()
        result["restarting"] = True

    return jsonify(result)


@app.get("/api/system/version")
def api_system_version():
    return jsonify({
        "ok": True,
        "version": software_version(),
    })


@app.post("/api/system/update")
def api_system_update():
    upload = request.files.get("update")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "Choose an update ZIP first."}), 400

    if not upload.filename.lower().endswith(".zip"):
        return jsonify({"ok": False, "error": "Update file must be a ZIP."}), 400

    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="uploaded-update-",
        suffix=".zip",
        dir=str(UPDATE_DIR)
    )
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        upload.save(temp_path)
        result = install_update_zip(temp_path)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Return the HTTP response first, then exit. systemd Restart=always
    # brings the new server back automatically.
    threading.Timer(1.5, lambda: os._exit(0)).start()

    return jsonify({
        "ok": True,
        "message": "Update installed. Leaderboard is restarting.",
        "version": result.get("version"),
    })


@app.get("/health")
def health():
    return jsonify({"ok": True})


def ensure_labwc_kiosk_autostart():
    """
    Raspberry Pi OS Bookworm and newer use labwc/Wayland by default.
    Keep one managed kiosk launcher line in ~/.config/labwc/autostart.

    This runs as the normal scoreboard user, so no sudo is required.
    """
    try:
        labwc_dir = Path.home() / ".config" / "labwc"
        labwc_dir.mkdir(parents=True, exist_ok=True)
        autostart = labwc_dir / "autostart"

        begin = "# >>> PI TABLEAU LEADERBOARD KIOSK >>>"
        end = "# <<< PI TABLEAU LEADERBOARD KIOSK <<<"
        managed = (
            f"{begin}\n"
            f"bash {APP_ROOT / 'kiosk.sh'} &\n"
            f"{end}\n"
        )

        existing = autostart.read_text() if autostart.exists() else ""

        # Remove our previous managed block, preserving anything else the user has.
        pattern = re.compile(
            re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
            re.S,
        )
        existing = pattern.sub("", existing).rstrip()

        text = (existing + "\n\n" if existing else "") + managed
        autostart.write_text(text)

        # Generic XDG autostart from older versions can launch a second Chromium
        # window. Remove only our own old desktop file.
        old_desktop = Path.home() / ".config" / "autostart" / "pi-tableau-leaderboard.desktop"
        try:
            old_desktop.unlink(missing_ok=True)
        except Exception:
            pass

        set_meta("kiosk_startup_status", "labwc autostart configured")
    except Exception as exc:
        set_meta("kiosk_startup_status", f"labwc setup failed: {exc}")


def ensure_sample_data():
    if not list_reps():
        rows = SampleSource().fetch()
        replace_reps(rows)
        set_meta("source_status", "sample data — Tableau not connected")


# Initialize on import because production runs through Waitress.
init_db()
app.secret_key = app_secret_key()
ensure_labwc_kiosk_autostart()
ensure_sample_data()
start_github_auto_update_worker()
# Twice-daily Tableau pull. Must come after init_db(); the call is idempotent,
# so a re-import can never start a second worker.
start_tableau_scheduler()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765, threaded=True)
