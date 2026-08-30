#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

DATA_REL = Path(".local/share/pi-tableau-leaderboard")
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def env_for(tree: Path, home: Path):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "app"), str(tree / "windows")])
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_py(tree: Path, home: Path, code: str):
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tree, env=env_for(tree, home),
        text=True, capture_output=True, timeout=120,
    )
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result.stdout.strip()


def seed_baseline(tree: Path, home: Path):
    code = r'''
import database

database.init_db()
database.replace_reps([
 {"rep_key":"a1","rep_name":"Alice","team":"Alpha","issued_leads":20,"pitched_leads":18,"sold_leads":10,"close_rate":50,"net_split":11000},
 {"rep_key":"a2","rep_name":"Aaron","team":"Alpha","issued_leads":10,"pitched_leads":9,"sold_leads":4,"close_rate":40,"net_split":4500},
 {"rep_key":"b1","rep_name":"Bianca","team":"Beta","issued_leads":18,"pitched_leads":16,"sold_leads":8,"close_rate":44.4444,"net_split":8750},
])
alpha=next(t for t in database.get_team_definitions() if t["name"]=="Alpha")
beta=next(t for t in database.get_team_definitions() if t["name"]=="Beta")
database.set_rep_team_assignments([
 {"rep_key":"a1","team_id":alpha["team_id"]},
 {"rep_key":"a2","team_id":alpha["team_id"]},
 {"rep_key":"b1","team_id":beta["team_id"]},
])
cfg=database.get_settings()
cfg["per_team_selected"]="Alpha"
cfg["team_vs_team_selected"]=["Alpha","Beta"]
database.save_settings(cfg)
print(alpha["team_id"], beta["team_id"])
'''
    run_py(tree, home, code)


def copy_data(src_home: Path, dst_home: Path):
    src = src_home / DATA_REL
    dst = dst_home / DATA_REL
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def make_server_script(path: Path):
    path.write_text(r'''
import argparse, sys
from pathlib import Path
from werkzeug.serving import run_simple
p=argparse.ArgumentParser(); p.add_argument("--tree"); p.add_argument("--kind"); p.add_argument("--port",type=int); a=p.parse_args()
tree=Path(a.tree).resolve(); sys.path[:0]=[str(tree/"app"),str(tree/"windows")]
if a.kind=="baseline":
    import server
    import qr_controls_v110; qr_controls_v110.install_routes(server.app)
    import windows_runtime; windows_runtime.install(server.app,server)
    import windows_update_status_v128; windows_update_status_v128.install(server.app,server)
    import windows_update_diagnostics; windows_update_diagnostics.install(server.app,server)
    import windows_theme_editor_v122; windows_theme_editor_v122.install(server.app,server.PUBLIC_ENDPOINTS)
    import windows_tableau_login_v124; windows_tableau_login_v124.install(server.app)
    app=server.app
else:
    from stats_core.bootstrap import create_app
    app=create_app("windows",start_background=False)
run_simple("127.0.0.1",a.port,app,use_reloader=False,threaded=True)
''', encoding="utf-8")


def start_server(script: Path, tree: Path, home: Path, kind: str, port: int):
    proc = subprocess.Popen(
        [sys.executable, str(script), "--tree", str(tree), "--kind", kind, "--port", str(port)],
        cwd=tree, env=env_for(tree, home), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"{kind} server exited:\n{out[-5000:]}")
        try:
            if requests.get(url + "/health", timeout=.5).status_code == 200:
                return proc, url
        except Exception:
            pass
        time.sleep(.25)
    raise RuntimeError(f"{kind} server did not become healthy")


def stop_server(proc):
    if not proc:
        return ""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait(timeout=5)
    try:
        return proc.stdout.read()[-5000:] if proc.stdout else ""
    except Exception:
        return ""


def norm_json(value):
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if key in {"id", "url"} and isinstance(val, str) and ("user:" in val or "/api/asset-library/" in val):
                out[key] = "<generated-user-item>"
            else:
                out[key] = norm_json(val)
        return out
    if isinstance(value, list):
        return [norm_json(item) for item in value]
    return value


def applied_hashes(home: Path):
    root = home / DATA_REL / "applied-theme-assets"
    result = {}
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def request_record(name, response, binary=False):
    if binary:
        payload = {"sha256": hashlib.sha256(response.content).hexdigest(), "length": len(response.content)}
    else:
        try:
            payload = norm_json(response.json())
        except Exception:
            payload = response.text
    return {"name": name, "status": response.status_code, "payload": payload}


def theme_sequence(base_url: str, home: Path):
    records = []

    def add(name, response, binary=False):
        record = request_record(name, response, binary)
        record["applied_hashes_after"] = applied_hashes(home)
        records.append(record)
        return response

    add("GET themes", requests.get(base_url + "/api/themes", timeout=10))
    add("PUT theme", requests.put(base_url + "/api/themes/team-1", json={
        "base":"undisputed","enabled":True,"hero_scale":110,"row_stripe":{"strength":10}
    }, timeout=10))
    add("DELETE theme", requests.delete(base_url + "/api/themes/team-1", timeout=10))
    add("GET library", requests.get(base_url + "/api/asset-library", timeout=10))
    uploaded = add("POST library", requests.post(
        base_url + "/api/asset-library/background",
        files={"asset": ("one.png", TINY_PNG, "image/png")}, data={"label":"one"}, timeout=10,
    ))
    data = uploaded.json() if uploaded.headers.get("content-type", "").startswith("application/json") else {}
    item = str(data.get("id") or "").replace("user:", "")
    add("GET library item", requests.get(base_url + f"/api/asset-library/background/{item}", timeout=10), True)
    add("DELETE library item", requests.delete(base_url + f"/api/asset-library/background/{item}", timeout=10))
    add("POST applied asset", requests.post(
        base_url + "/api/themes/team-1/assets/background",
        files={"asset": ("applied.png", TINY_PNG, "image/png")}, timeout=10,
    ))
    applied = add("GET applied asset", requests.get(
        base_url + "/api/theme-assets/team-1/background", timeout=10
    ), True)
    applied_sha = hashlib.sha256(applied.content).hexdigest()
    add("DELETE applied asset", requests.delete(
        base_url + "/api/themes/team-1/assets/background", timeout=10
    ))
    return records, applied_sha


def timed_request(method, url, **kwargs):
    start = time.monotonic()
    response = requests.request(method, url, **kwargs)
    return response, round(time.monotonic() - start, 4)


def controls_sequence(base_url: str):
    views = ["whole_office", "team_vs_team", "all_teams", "product_close", "per_team::Alpha"]
    transitions = []
    for view in views:
        put, put_seconds = timed_request("PUT", base_url + "/api/config", json={"active_mode": view}, timeout=15)
        state, state_seconds = timed_request("GET", base_url + "/api/state", timeout=15)
        try:
            actual = (state.json() or {}).get("active_mode")
        except Exception:
            actual = None
        transitions.append({
            "expected": view,
            "put_status": put.status_code,
            "put_seconds": put_seconds,
            "state_status": state.status_code,
            "state_seconds": state_seconds,
            "actual": actual,
        })
    keys = {"previous":"z","next":"x","pair":"ArrowUp","sort_prev":"PageUp","sort_next":"PageDown"}
    key_response, key_seconds = timed_request(
        "POST", base_url + "/api/keyboard-controls", json={"keys": keys}, timeout=15
    )
    config, config_seconds = timed_request("GET", base_url + "/api/config", timeout=15)
    try:
        stored_keys = (config.json() or {}).get("settings", {}).get("keyboard_cycle_keys")
    except Exception:
        stored_keys = None
    ok = (
        all(row["put_status"] == 200 and row["state_status"] == 200 and row["actual"] == row["expected"] for row in transitions)
        and key_response.status_code == 200
        and config.status_code == 200
        and stored_keys == keys
    )
    return ok, {
        "transitions": transitions,
        "key_status": key_response.status_code,
        "key_seconds": key_seconds,
        "config_status": config.status_code,
        "config_seconds": config_seconds,
        "stored_keys": stored_keys,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    baseline = Path(args.baseline).resolve()
    current = Path(args.current).resolve()

    with tempfile.TemporaryDirectory(prefix="stats-theme-controls-") as tmp:
        root = Path(tmp)
        seed_home = root / "seed"
        seed_baseline(baseline, seed_home)
        baseline_home = root / "baseline-home"
        current_home = root / "current-home"
        copy_data(seed_home, baseline_home)
        copy_data(seed_home, current_home)
        server_script = root / "serve.py"
        make_server_script(server_script)
        baseline_proc = current_proc = None
        baseline_log = current_log = ""
        try:
            baseline_proc, baseline_url = start_server(server_script, baseline, baseline_home, "baseline", 8876)
            current_proc, current_url = start_server(server_script, current, current_home, "current", 8877)

            baseline_theme, baseline_sha = theme_sequence(baseline_url, baseline_home)
            current_theme, current_sha = theme_sequence(current_url, current_home)
            baseline_controls_ok, baseline_controls = controls_sequence(baseline_url)
            current_controls_ok, current_controls = controls_sequence(current_url)

            theme_route_equal = [
                {k:v for k,v in row.items() if k != "applied_hashes_after"}
                for row in baseline_theme
            ] == [
                {k:v for k,v in row.items() if k != "applied_hashes_after"}
                for row in current_theme
            ]
            theme_disk_equal = [row["applied_hashes_after"] for row in baseline_theme] == [row["applied_hashes_after"] for row in current_theme]
            report = {
                "theme": {
                    "routes_equal": theme_route_equal,
                    "served_applied_sha_equal": baseline_sha == current_sha,
                    "disk_history_equal": theme_disk_equal,
                    "baseline": baseline_theme,
                    "current": current_theme,
                },
                "controls": {
                    "baseline_ok": baseline_controls_ok,
                    "current_ok": current_controls_ok,
                    "behavior_equal": baseline_controls == current_controls,
                    "baseline": baseline_controls,
                    "current": current_controls,
                },
            }
        finally:
            baseline_log = stop_server(baseline_proc)
            current_log = stop_server(current_proc)

        report["server_log_tails"] = {"baseline": baseline_log, "current": current_log}
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        # Diagnostic succeeds only when route/content parity and control behavior are correct.
        # Disk-history mismatch is reported separately because retained protected copies may be intentional.
        ok = (
            report["theme"]["routes_equal"]
            and report["theme"]["served_applied_sha_equal"]
            and report["controls"]["baseline_ok"]
            and report["controls"]["current_ok"]
        )
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
