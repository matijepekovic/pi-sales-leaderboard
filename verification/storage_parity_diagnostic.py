#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

DATA_REL = Path(".local/share/pi-tableau-leaderboard")
BASELINE_SHA = "004c03ede7325518ce11f3fe619a49b5ae078bf4"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def env_for(tree: Path, home: Path):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "app"), str(tree / "windows")])
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_py(tree: Path, home: Path, code: str):
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tree,
        env=env_for(tree, home),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(
            f"python failed in {tree}:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def db_path(home: Path):
    return home / DATA_REL / "leaderboard.db"


def copy_data(src_home: Path, dst_home: Path):
    src = src_home / DATA_REL
    dst = dst_home / DATA_REL
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def seed_baseline(tree: Path, home: Path):
    code = r'''
import json
from pathlib import Path
import database

database.init_db()
rows = [
 {"rep_key":"a1","rep_name":"Alice","team":"Alpha","team_lead":"A Lead","issued_leads":20,"pitched_leads":18,"pitched_rate":90,"sold_leads":10,"close_rate":50,"gross_split":12000,"pending_split":1000,"net_split":11000,"dpl":550,"sales_retention":91.6667,"avg_gross_sale":1200,"avg_net_sale":1100},
 {"rep_key":"a2","rep_name":"Aaron","team":"Alpha","team_lead":"A Lead","issued_leads":10,"pitched_leads":9,"pitched_rate":90,"sold_leads":4,"close_rate":40,"gross_split":5000,"pending_split":500,"net_split":4500,"dpl":450,"sales_retention":90,"avg_gross_sale":1250,"avg_net_sale":1125},
 {"rep_key":"b1","rep_name":"Bianca","team":"Beta","team_lead":"B Lead","issued_leads":18,"pitched_leads":16,"pitched_rate":88.8889,"sold_leads":8,"close_rate":44.4444,"gross_split":9500,"pending_split":750,"net_split":8750,"dpl":486.1111,"sales_retention":92.1053,"avg_gross_sale":1187.5,"avg_net_sale":1093.75},
 {"rep_key":"b2","rep_name":"Ben","team":"Beta","team_lead":"B Lead","issued_leads":8,"pitched_leads":7,"pitched_rate":87.5,"sold_leads":3,"close_rate":37.5,"gross_split":3600,"pending_split":300,"net_split":3300,"dpl":412.5,"sales_retention":91.6667,"avg_gross_sale":1200,"avg_net_sale":1100},
]
database.replace_reps(rows)
alpha = next(t for t in database.get_team_definitions() if t["name"] == "Alpha")
beta = next(t for t in database.get_team_definitions() if t["name"] == "Beta")
database.set_team_lead(alpha["team_id"], "A Lead", "Sales Manager")
database.set_team_lead(beta["team_id"], "B Lead", "Sales Manager")
database.set_rep_team_assignments([
 {"rep_key":"a1","team_id":alpha["team_id"]},{"rep_key":"a2","team_id":alpha["team_id"]},
 {"rep_key":"b1","team_id":beta["team_id"]},{"rep_key":"b2","team_id":beta["team_id"]},
])
database.replace_product_close([
 {"product":"Bath","close_rate":52.5},{"product":"Siding","close_rate":46.2},
 {"product":"Windows","close_rate":43.8},{"product":"Gutters","close_rate":39.1},{"product":"Roofing","close_rate":35.4},
])
cfg = database.get_settings()
cfg.update({"title":"PARITY BOARD","subtitle":"SEEDED","active_mode":"whole_office"})
cfg["team_vs_team_selected"] = ["Alpha","Beta"]
cfg["per_team_selected"] = "Alpha"
cfg["theme_config"] = {"teams": {
 str(alpha["team_id"]): {"base":"starter","enabled":True,"colors":{},"assets":{},"hero_scale":100,"row_stripe":{"strength":0}},
 str(beta["team_id"]): {"base":"starter","enabled":True,"colors":{},"assets":{},"hero_scale":100,"row_stripe":{"strength":0}},
}}
database.save_settings(cfg)
database.set_meta("source_status", "seeded")
database.set_meta("last_source_refresh", "2026-08-29 12:00:00")
root = Path.home()/".local/share/pi-tableau-leaderboard/asset-library/background"
root.mkdir(parents=True, exist_ok=True)
png = __import__("base64").b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
(root/"fixedasset.png").write_bytes(png)
(root/"index.json").write_text(json.dumps([{"id":"fixedasset","label":"Fixed","ext":".png","created":"2026-08-29 12:00:00"}]), encoding="utf-8")
print(json.dumps({"alpha":alpha["team_id"],"beta":beta["team_id"]}))
'''
    return json.loads(run_py(tree, home, code).splitlines()[-1])


def read_snapshot(tree: Path, home: Path, current: bool):
    if current:
        code = r'''
import json
from stats_core.repositories import Repositories
Repositories.initialize(); r=Repositories()
raw = r.reps.raw_list()
out = {
 "settings": r.settings.get(),
 "meta": {k:r.meta.get(k,"") for k in ("data_version","settings_version","organization_version","tv_refresh_version","source_status","last_source_refresh")},
 "reps": r.reps.list(),
 "raw_reps": raw,
 "overlay": r.reps.apply_organization([dict(x) for x in raw]),
 "teams": r.organization.list_team_names(),
 "definitions": r.organization.definitions(),
 "definitions_all": r.organization.definitions(include_inactive=True),
 "products": r.products.list(),
 "theme_store": r.themes.store(),
 "theme_1": r.themes.get(1),
 "library_index": r.asset_library.read_index("background"),
 "library_item_exists": bool(r.asset_library.item_path("background","fixedasset")),
 "builtin_catalog": r.asset_library.builtin_catalog(),
}
print(json.dumps(out, sort_keys=True, default=str))
'''
    else:
        code = r'''
import json
from pathlib import Path
import database

database.init_db()
with database.connect() as con:
    raw=[dict(x) for x in con.execute("SELECT * FROM reps").fetchall()]
cfg=database.get_settings()
store=cfg.get("theme_config") if isinstance(cfg.get("theme_config"),dict) else {}
store={"teams":dict(store.get("teams") or {})}
root=Path.home()/".local/share/pi-tableau-leaderboard/asset-library/background"
try:
    lib=json.loads((root/"index.json").read_text(encoding="utf-8"))
except Exception:
    lib=[]
# Important: use the checked-out tree explicitly. __file__ is not valid under python -c.
try:
    builtin=json.loads((Path.cwd()/"app/static/asset-library/catalog.json").read_text(encoding="utf-8"))
except Exception:
    builtin={"collections":[]}
out = {
 "settings": cfg,
 "meta": {k:database.get_meta(k,"") for k in ("data_version","settings_version","organization_version","tv_refresh_version","source_status","last_source_refresh")},
 "reps": database.list_reps(),
 "raw_reps": raw,
 "overlay": database.apply_team_overlay([dict(x) for x in raw]),
 "teams": database.list_teams(),
 "definitions": database.get_team_definitions(),
 "definitions_all": database.get_team_definitions(include_inactive=True),
 "products": database.get_product_close(),
 "theme_store": store,
 "theme_1": dict(store["teams"].get("1",{})),
 "library_index": lib,
 "library_item_exists": (root/"fixedasset.png").exists(),
 "builtin_catalog": builtin,
}
print(json.dumps(out, sort_keys=True, default=str))
'''
    return json.loads(run_py(tree, home, code).splitlines()[-1])


def replay_writes(tree: Path, home: Path, current: bool):
    rows = '[{"rep_key":"z1","rep_name":"Zoe","team":"Alpha","issued_leads":11,"pitched_leads":10,"sold_leads":6,"gross_split":7000,"pending_split":400,"net_split":6600}]'
    if current:
        code = f'''
from stats_core.repositories import Repositories
Repositories.initialize(); r=Repositories()
s=r.settings.get(); s["title"]="WRITE PARITY"; r.settings.save(s)                                      # 1
r.meta.set("parity_meta","x")                                                                        # 2
r.meta.bump("settings_version")                                                                       # 3
r.reps.replace({rows})                                                                                  # 4
r.products.replace([{{"product":"Bath","close_rate":61.25}},{{"product":"Roofing","close_rate":42.0}}]) # 5
gamma=r.organization.create("Gamma")                                                                  # 6
r.organization.rename(gamma,"Delta")                                                                  # 7
r.organization.set_leader(gamma,"D Lead","Manager")                                                 # 8
r.organization.assign_reps([{{"rep_key":"z1","team_id":gamma}}])                                  # 9
r.organization.save_builder(gamma,"Delta","D Lead","Manager",["z1"])                              # 10
epsilon=r.organization.create("Epsilon")                                                              # 11
r.themes.save(gamma,{{"base":"undisputed","enabled":True,"colors":{{}},"assets":{{}}}})          # 12
store=r.themes.store(); store["teams"][str(epsilon)]={{"base":"starter","enabled":True,"colors":{{}},"assets":{{}}}}; r.themes.save_store(store) # 13
for d in r.organization.definitions(include_inactive=True):
    for lead in d.get("leads") or []:
        if d["team_id"]==gamma:
            r.organization.delete_leader(lead["lead_id"]); break                                       # 14
r.organization.delete(gamma,[{{"rep_key":"z1","team_id":epsilon}}])                               # 15
'''
    else:
        code = f'''
import database
database.init_db()
s=database.get_settings(); s["title"]="WRITE PARITY"; database.save_settings(s)                        # 1
database.set_meta("parity_meta","x")                                                                  # 2
database.bump_meta("settings_version")                                                                 # 3
database.replace_reps({rows})                                                                           # 4
database.replace_product_close([{{"product":"Bath","close_rate":61.25}},{{"product":"Roofing","close_rate":42.0}}]) # 5
gamma=database.create_team("Gamma")                                                                    # 6
database.rename_team(gamma,"Delta")                                                                    # 7
database.set_team_lead(gamma,"D Lead","Manager")                                                     # 8
database.set_rep_team_assignments([{{"rep_key":"z1","team_id":gamma}}])                           # 9
database.save_team_builder(gamma,"Delta","D Lead","Manager",["z1"])                                # 10
epsilon=database.create_team("Epsilon")                                                                # 11
s=database.get_settings(); store=s.get("theme_config") if isinstance(s.get("theme_config"),dict) else {{}}; teams=dict(store.get("teams") or {{}}); teams[str(gamma)]={{"base":"undisputed","enabled":True,"colors":{{}},"assets":{{}}}}; s["theme_config"]={{"teams":teams}}; database.save_settings(s); database.bump_meta("settings_version") # 12
s=database.get_settings(); store=s.get("theme_config") if isinstance(s.get("theme_config"),dict) else {{}}; teams=dict(store.get("teams") or {{}}); teams[str(epsilon)]={{"base":"starter","enabled":True,"colors":{{}},"assets":{{}}}}; s["theme_config"]={{"teams":teams}}; database.save_settings(s); database.bump_meta("settings_version") # 13
for d in database.get_team_definitions(include_inactive=True):
    for lead in d.get("leads") or []:
        if d["team_id"]==gamma:
            database.delete_team_lead(lead["lead_id"]); break                                           # 14
database.delete_team(gamma,[{{"rep_key":"z1","team_id":epsilon}}])                                 # 15
'''
    run_py(tree, home, code)


def dump_db(path: Path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        result = {}
        for table in tables:
            cols = [row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()]
            rows = []
            for row in con.execute(f"SELECT * FROM {table}").fetchall():
                item = {key: row[key] for key in cols}
                for key in list(item):
                    lower = key.lower()
                    if lower.endswith("_at") or lower in {"created", "created_at", "deleted_at", "updated_at"}:
                        if item[key] not in (None, ""):
                            item[key] = "<timestamp>"
                rows.append(item)
            rows.sort(key=canonical_json)
            result[table] = rows
        return result
    finally:
        con.close()


def structural_diff(a, b, path="$"):
    diffs = []
    if type(a) is not type(b):
        return [{"path": path, "baseline": a, "current": b, "reason": "type"}]
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            child = f"{path}.{key}"
            if key not in a:
                diffs.append({"path": child, "baseline": "<missing>", "current": b[key], "reason": "missing-baseline"})
            elif key not in b:
                diffs.append({"path": child, "baseline": a[key], "current": "<missing>", "reason": "missing-current"})
            else:
                diffs.extend(structural_diff(a[key], b[key], child))
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append({"path": path, "baseline_length": len(a), "current_length": len(b), "reason": "length"})
        for index, (left, right) in enumerate(zip(a, b)):
            diffs.extend(structural_diff(left, right, f"{path}[{index}]"))
    elif a != b:
        diffs.append({"path": path, "baseline": a, "current": b, "reason": "value"})
    return diffs


def table_diff(a, b):
    report = {}
    for table in sorted(set(a) | set(b)):
        left = a.get(table, [])
        right = b.get(table, [])
        if left == right:
            continue
        left_map = {canonical_json(row): row for row in left}
        right_map = {canonical_json(row): row for row in right}
        report[table] = {
            "baseline_count": len(left),
            "current_count": len(right),
            "baseline_only": [left_map[key] for key in sorted(set(left_map) - set(right_map))],
            "current_only": [right_map[key] for key in sorted(set(right_map) - set(left_map))],
        }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    baseline = Path(args.baseline).resolve()
    current = Path(args.current).resolve()

    with tempfile.TemporaryDirectory(prefix="stats-storage-parity-") as tmp:
        root = Path(tmp)
        seed_home = root / "seed"
        seed_baseline(baseline, seed_home)

        read_base_home = root / "read-baseline"
        read_current_home = root / "read-current"
        copy_data(seed_home, read_base_home)
        copy_data(seed_home, read_current_home)
        baseline_reads = read_snapshot(baseline, read_base_home, False)
        current_reads = read_snapshot(current, read_current_home, True)
        read_diffs = structural_diff(baseline_reads, current_reads)

        write_base_home = root / "write-baseline"
        write_current_home = root / "write-current"
        copy_data(seed_home, write_base_home)
        copy_data(seed_home, write_current_home)
        replay_writes(baseline, write_base_home, False)
        replay_writes(current, write_current_home, True)
        baseline_db = dump_db(db_path(write_base_home))
        current_db = dump_db(db_path(write_current_home))
        write_diffs = table_diff(baseline_db, current_db)

        report = {
            "baseline_sha": BASELINE_SHA,
            "current_ref": str(current),
            "reads_equal": not read_diffs,
            "read_diffs": read_diffs,
            "writes_equal": not write_diffs,
            "write_diffs": write_diffs,
        }
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["reads_equal"] and report["writes_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
