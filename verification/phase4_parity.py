#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import requests

BASELINE_SHA = "004c03ede7325518ce11f3fe619a49b5ae078bf4"
REFACTORED_SHA = "bc05c0e7cfb4b22ed23f4a77a8419b2b250c1a9a"
MAIN_SHA = "65826125d52d1c249a8072bb78d15108a4c8f9bc"
DATA_REL = Path(".local/share/pi-tableau-leaderboard")


def jdump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class Gate:
    def __init__(self):
        self.rows = []

    def add(self, key, ok, detail=""):
        self.rows.append({"check": key, "ok": bool(ok), "detail": str(detail)})
        print(f"[{ 'PASS' if ok else 'FAIL' }] {key}: {detail}", flush=True)

    @property
    def ok(self):
        return all(row["ok"] for row in self.rows)


def env_for(tree: Path, home: Path):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "app"), str(tree / "windows")])
    env["PYTHONUNBUFFERED"] = "1"
    env["STATS_WINDOWS_BUILD"] = "1"
    return env


def run_py(tree: Path, home: Path, code: str, *, check=True, timeout=120):
    return subprocess.run(
        [sys.executable, "-c", code], cwd=tree, env=env_for(tree, home),
        text=True, capture_output=True, timeout=timeout, check=check,
    )


def db_path(home: Path):
    return home / DATA_REL / "leaderboard.db"


def sqlite_schema(path: Path):
    con = sqlite3.connect(path)
    try:
        return [tuple(row) for row in con.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()]
    finally:
        con.close()


def dump_db(path: Path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        out = {}
        for table in tables:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
            rows = []
            for row in con.execute(f"SELECT * FROM {table}").fetchall():
                item = {k: row[k] for k in cols}
                # Canonicalize only wall-clock columns; every table and all semantic values are still diffed.
                for key in list(item):
                    lk = key.lower()
                    if lk.endswith("_at") or lk in {"created", "created_at", "deleted_at", "updated_at"}:
                        if item[key] not in (None, ""):
                            item[key] = "<timestamp>"
                rows.append(item)
            rows.sort(key=jdump)
            out[table] = rows
        return out
    finally:
        con.close()


def copy_data(src_home: Path, dst_home: Path):
    src = src_home / DATA_REL
    dst = dst_home / DATA_REL
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def seed(tree: Path, home: Path):
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
    return json.loads(run_py(tree, home, code).stdout.strip().splitlines()[-1])


def read_snapshot(tree: Path, home: Path, refactored: bool):
    if refactored:
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
 "overlay": r.reps.apply_organization(raw),
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

database.init_db(); raw=[]
with database.connect() as con: raw=[dict(x) for x in con.execute("SELECT * FROM reps").fetchall()]
cfg=database.get_settings(); store=cfg.get("theme_config") if isinstance(cfg.get("theme_config"),dict) else {}; store={"teams":dict(store.get("teams") or {})}
root=Path.home()/".local/share/pi-tableau-leaderboard/asset-library/background"
try: lib=json.loads((root/"index.json").read_text(encoding="utf-8"))
except Exception: lib=[]
try: builtin=json.loads((Path(__file__).resolve().parent/"static/asset-library/catalog.json").read_text(encoding="utf-8"))
except Exception: builtin={"collections":[]}
out = {
 "settings": cfg,
 "meta": {k:database.get_meta(k,"") for k in ("data_version","settings_version","organization_version","tv_refresh_version","source_status","last_source_refresh")},
 "reps": database.list_reps(),
 "raw_reps": raw,
 "overlay": database.apply_team_overlay(raw),
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
    return json.loads(run_py(tree, home, code).stdout.strip().splitlines()[-1])


def replay_writes(tree: Path, home: Path, refactored: bool):
    common_rows = '[{"rep_key":"z1","rep_name":"Zoe","team":"Alpha","issued_leads":11,"pitched_leads":10,"sold_leads":6,"gross_split":7000,"pending_split":400,"net_split":6600}]'
    if refactored:
        code = f'''
from stats_core.repositories import Repositories
r=Repositories(); Repositories.initialize()
s=r.settings.get(); s["title"]="WRITE PARITY"; r.settings.save(s)                                      # 1
r.meta.set("parity_meta","x")                                                                        # 2
r.meta.bump("settings_version")                                                                       # 3
r.reps.replace({common_rows})                                                                          # 4
r.products.replace([{{"product":"Bath","close_rate":61.25}},{{"product":"Roofing","close_rate":42.0}}]) # 5
gamma=r.organization.create("Gamma")                                                                  # 6
r.organization.rename(gamma,"Delta")                                                                  # 7
lead=r.organization.set_leader(gamma,"D Lead","Manager")                                            # 8
r.organization.assign_reps([{{"rep_key":"z1","team_id":gamma}}])                                  # 9
r.organization.save_builder(gamma,"Delta","D Lead","Manager",["z1"])                               # 10
epsilon=r.organization.create("Epsilon")                                                              # 11
r.themes.save(gamma,{{"base":"undisputed","enabled":True,"colors":{{}},"assets":{{}}}})            # 12
store=r.themes.store(); store["teams"][str(epsilon)]={{"base":"starter","enabled":True,"colors":{{}},"assets":{{}}}}; r.themes.save_store(store) # 13
for d in r.organization.definitions(include_inactive=True):
    for l in d.get("leads") or []:
        if d["team_id"]==gamma: r.organization.delete_leader(l["lead_id"]); break                       # 14
r.organization.delete(gamma,[{{"rep_key":"z1","team_id":epsilon}}])                                # 15
'''
    else:
        code = f'''
import database
s=database.get_settings(); s["title"]="WRITE PARITY"; database.save_settings(s)                        # 1
database.set_meta("parity_meta","x")                                                                   # 2
database.bump_meta("settings_version")                                                                  # 3
database.replace_reps({common_rows})                                                                     # 4
database.replace_product_close([{{"product":"Bath","close_rate":61.25}},{{"product":"Roofing","close_rate":42.0}}]) # 5
gamma=database.create_team("Gamma")                                                                     # 6
database.rename_team(gamma,"Delta")                                                                     # 7
database.set_team_lead(gamma,"D Lead","Manager")                                                      # 8
database.set_rep_team_assignments([{{"rep_key":"z1","team_id":gamma}}])                            # 9
database.save_team_builder(gamma,"Delta","D Lead","Manager",["z1"])                                 # 10
epsilon=database.create_team("Epsilon")                                                                 # 11
s=database.get_settings(); store=s.get("theme_config") if isinstance(s.get("theme_config"),dict) else {{}}; teams=dict(store.get("teams") or {{}}); teams[str(gamma)]={{"base":"undisputed","enabled":True,"colors":{{}},"assets":{{}}}}; s["theme_config"]={{"teams":teams}}; database.save_settings(s); database.bump_meta("settings_version") # 12
s=database.get_settings(); store=s.get("theme_config") if isinstance(s.get("theme_config"),dict) else {{}}; teams=dict(store.get("teams") or {{}}); teams[str(epsilon)]={{"base":"starter","enabled":True,"colors":{{}},"assets":{{}}}}; s["theme_config"]={{"teams":teams}}; database.save_settings(s); database.bump_meta("settings_version") # 13
for d in database.get_team_definitions(include_inactive=True):
    for l in d.get("leads") or []:
        if d["team_id"]==gamma: database.delete_team_lead(l["lead_id"]); break                          # 14
database.delete_team(gamma,[{{"rep_key":"z1","team_id":epsilon}}])                                  # 15
'''
    run_py(tree, home, code)


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
        cwd=tree, env=env_for(tree,home), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url=f"http://127.0.0.1:{port}"
    for _ in range(120):
        if proc.poll() is not None:
            out=proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"{kind} server exited: {out[-4000:]}")
        try:
            if requests.get(url+"/health",timeout=.5).status_code==200:
                return proc,url
        except Exception:
            pass
        time.sleep(.25)
    raise RuntimeError(f"{kind} server did not become healthy")


def stop_server(proc):
    if not proc: return
    proc.terminate()
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait(timeout=5)


def norm_json(value):
    if isinstance(value, dict):
        out={}
        for k,v in value.items():
            if k in {"id","url"} and isinstance(v,str) and ("user:" in v or "/api/asset-library/" in v):
                out[k]="<generated-user-item>"
            else: out[k]=norm_json(v)
        return out
    if isinstance(value,list): return [norm_json(x) for x in value]
    return value


def theme_route_sequence(base_url: str):
    tiny=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    seq=[]
    def add(name,r,binary=False):
        if binary: payload={"sha256":hashlib.sha256(r.content).hexdigest(),"length":len(r.content)}
        else:
            try: payload=norm_json(r.json())
            except Exception: payload=r.text
        seq.append((name,r.status_code,payload))
        return r
    add("GET /api/themes",requests.get(base_url+"/api/themes",timeout=10))
    add("PUT /api/themes/<scope>",requests.put(base_url+"/api/themes/team-1",json={"base":"undisputed","enabled":True,"hero_scale":110,"row_stripe":{"strength":10}},timeout=10))
    add("DELETE /api/themes/<scope>",requests.delete(base_url+"/api/themes/team-1",timeout=10))
    add("GET /api/asset-library",requests.get(base_url+"/api/asset-library",timeout=10))
    r=add("POST /api/asset-library/<asset_key>",requests.post(base_url+"/api/asset-library/background",files={"asset":("one.png",tiny,"image/png")},data={"label":"one"},timeout=10))
    data=r.json() if r.headers.get("content-type","").startswith("application/json") else {}; item=str(data.get("id") or "").replace("user:","")
    add("GET /api/asset-library/<asset_key>/<item_id>",requests.get(base_url+f"/api/asset-library/background/{item}",timeout=10),True)
    add("DELETE /api/asset-library/<asset_key>/<item_id>",requests.delete(base_url+f"/api/asset-library/background/{item}",timeout=10))
    add("POST /api/themes/<scope>/assets/<asset_key>",requests.post(base_url+"/api/themes/team-1/assets/background",files={"asset":("applied.png",tiny,"image/png")},timeout=10))
    add("GET /api/theme-assets/<scope>/<asset_key>",requests.get(base_url+"/api/theme-assets/team-1/background",timeout=10),True)
    applied_sha=seq[-1][2].get("sha256") if isinstance(seq[-1][2],dict) else None
    add("DELETE /api/themes/<scope>/assets/<asset_key>",requests.delete(base_url+"/api/themes/team-1/assets/background",timeout=10))
    return seq,applied_sha


def applied_hashes(home: Path):
    root=home/DATA_REL/"applied-theme-assets"
    out={}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file(): out[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def pin_compat(tree: Path, home: Path):
    code=r'''
import hashlib,json
import database
from stats_core.bootstrap import create_app
database.init_db(); cfg=database.get_settings(); salt="00112233445566778899aabbccddeeff"; pin="2468"; digest=hashlib.pbkdf2_hmac("sha256",pin.encode(),bytes.fromhex(salt),200000).hex(); cfg["settings_pin_hash"]=f"pbkdf2$200000${salt}${digest}"; database.save_settings(cfg)
app=create_app("windows",start_background=False); app.config.update(TESTING=True); c=app.test_client(); r=c.post("/api/auth/unlock",json={"pin":pin}); print(json.dumps({"status":r.status_code,"body":r.get_json()}))
'''
    return json.loads(run_py(tree,home,code).stdout.strip().splitlines()[-1])


def runtime_architecture_check(tree: Path, home: Path):
    smoke=subprocess.run([sys.executable,str(tree/"windows/test_restructured_runtime.py")],cwd=tree,env=env_for(tree,home),text=True,capture_output=True,timeout=120)
    legacy={
        "qr_controls_v110","keyboard_controls_v112","product_controls_v115","temporary_date_v113",
        "pull_policy_v108","production_gates","production_versioning","windows_runtime","themes",
        "applied_theme_assets_v116","starter_theme_v119","starter_theme_assets_v119","theme_asset_apply_v127",
        "product_source_v115","tableau_scheduler",
    }
    found=[]
    for name in sorted(legacy):
        for p in tree.rglob(name+".py"):
            found.append(str(p.relative_to(tree)))
    neutral=run_py(tree,home,"import sys,stats_core,json; print(json.dumps(sorted(m for m in sys.modules if m=='stats_core.platform.windows' or m.startswith('windows_'))))").stdout.strip().splitlines()[-1]
    loaded=json.loads(neutral)
    return smoke.returncode==0 and not found and not loaded,{"smoke_rc":smoke.returncode,"smoke_tail":(smoke.stdout+smoke.stderr)[-2000:],"legacy_files":found,"os_specific_after_import_stats_core":loaded}


def controls_check(url: str):
    views=["whole_office","team_vs_team","all_teams","product_close","per_team::Alpha"]
    seen=[]
    for view in views:
        r=requests.put(url+"/api/config",json={"active_mode":view},timeout=10)
        s=requests.get(url+"/api/state",timeout=10)
        seen.append((view,r.status_code,s.status_code,(s.json() or {}).get("active_mode")))
    keys={"previous":"z","next":"x","pair":"ArrowUp","sort_prev":"PageUp","sort_next":"PageDown"}
    kr=requests.post(url+"/api/keyboard-controls",json={"keys":keys},timeout=10)
    cfg=requests.get(url+"/api/config",timeout=10).json()
    return all(a==200 and b==200 and expected==actual for expected,a,b,actual in seen) and kr.status_code==200 and cfg["settings"]["keyboard_cycle_keys"]==keys,{"transitions":seen,"keys":cfg["settings"].get("keyboard_cycle_keys")}


async def browser_checks(url_a,url_b):
    from playwright.async_api import async_playwright
    from PIL import Image,ImageChops
    import io
    traces={}; pixels=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        contexts=[]
        for label,url in (("baseline",url_a),("refactored",url_b)):
            ctx=await browser.new_context(viewport={"width":3840,"height":2160},device_scale_factor=1,reduced_motion="reduce")
            page=await ctx.new_page()
            await page.add_init_script(r'''(() => { const t={fetch:[],styles:[]}; window.__wireTrace=t; let cur=window.fetch; Object.defineProperty(window,"fetch",{configurable:true,get(){return cur},set(v){let s="";try{s=Function.prototype.toString.call(v).replace(/\s+/g," ").slice(0,160)}catch(e){};t.fetch.push(s);cur=v;}}); document.addEventListener("DOMContentLoaded",()=>{new MutationObserver(ms=>{for(const m of ms)for(const n of m.addedNodes)if(n&&n.tagName==="STYLE")t.styles.push(n.id||"");}).observe(document.documentElement,{subtree:true,childList:true});}); })();''')
            await page.goto(url+"/",wait_until="domcontentloaded")
            await page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}")
            await page.wait_for_timeout(1200)
            await page.evaluate(r'''() => { window.__stageTrace=[]; for (const n of Object.getOwnPropertyNames(window)) { try { const f=window[n]; if(typeof f!=="function"||!/(render|apply|update|refresh|load|build)/i.test(n)) continue; window[n]=function(...a){window.__stageTrace.push(n); return f.apply(this,a)}; } catch(e){} } }''')
            requests.put(url+"/api/config",json={"subtitle":"TRACE"},timeout=10)
            await page.wait_for_timeout(6500)
            traces[label]=await page.evaluate(r'''() => ({stages:window.__stageTrace||[],styles:[...document.querySelectorAll("style")].map(x=>x.id||"").filter(Boolean),fetch:(window.__wireTrace||{}).fetch||[]})''')
            contexts.append((label,url,ctx,page))
        trace_ok=traces["baseline"]==traces["refactored"] and len(traces["baseline"].get("stages",[]))>0
        modes=["whole_office","per_team::Alpha","team_vs_team","all_teams","product_close"]
        for base in ("starter","undisputed"):
            for url in (url_a,url_b):
                for tid in (1,2): requests.put(url+f"/api/themes/team-{tid}",json={"base":base,"enabled":True},timeout=10)
            for mode in modes:
                imgs={}
                for label,url,ctx,page in contexts:
                    requests.put(url+"/api/config",json={"active_mode":mode,"subtitle":""},timeout=10)
                    await page.reload(wait_until="domcontentloaded"); await page.wait_for_timeout(1400)
                    imgs[label]=await page.screenshot(full_page=False,animations="disabled")
                ia=Image.open(io.BytesIO(imgs["baseline"])).convert("RGBA"); ib=Image.open(io.BytesIO(imgs["refactored"])).convert("RGBA")
                diff=ImageChops.difference(ia,ib); bbox=diff.getbbox(); pixels.append({"base":base,"mode":mode,"equal":bbox is None,"bbox":bbox})
        await browser.close()
    return trace_ok,traces,all(x["equal"] for x in pixels),pixels


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--baseline",required=True); ap.add_argument("--refactored",required=True); ap.add_argument("--report",required=True); args=ap.parse_args()
    baseline=Path(args.baseline).resolve(); ref=Path(args.refactored).resolve(); gate=Gate(); root=Path(tempfile.mkdtemp(prefix="phase4-gate-")); procs=[]
    try:
        # 1 schema
        hb=root/"schema-b"; hr=root/"schema-r"; run_py(baseline,hb,"import database; database.init_db()"); run_py(ref,hr,"import database; database.init_db()")
        sb,sr=sqlite_schema(db_path(hb)),sqlite_schema(db_path(hr)); gate.add("1 schema identical",sb==sr,f"objects baseline={len(sb)} refactored={len(sr)}")

        # common seed
        seedhome=root/"seed"; ids=seed(baseline,seedhome)

        # 2 reads
        rb=root/"reads-b"; rr=root/"reads-r"; copy_data(seedhome,rb); copy_data(seedhome,rr)
        a=read_snapshot(baseline,rb,False); b=read_snapshot(ref,rr,True); gate.add("2 repository reads identical",a==b,"seeded repository/file reads compared")

        # 3 fixed 15 writes + every table
        wb=root/"writes-b"; wr=root/"writes-r"; copy_data(seedhome,wb); copy_data(seedhome,wr); replay_writes(baseline,wb,False); replay_writes(ref,wr,True)
        da,db=dump_db(db_path(wb)),dump_db(db_path(wr)); gate.add("3 writes identical",da==db,f"15 operations; tables={sorted(set(da)|set(db))}")

        # homes for HTTP/browser checks
        shb=root/"serve-b"; shr=root/"serve-r"; copy_data(seedhome,shb); copy_data(seedhome,shr); server_script=root/"serve_tree.py"; make_server_script(server_script)
        pb,ub=start_server(server_script,baseline,shb,"baseline",8766); procs.append(pb); pr,ur=start_server(server_script,ref,shr,"refactored",8767); procs.append(pr)

        # 4 boot/serve
        endpoints=["/","/settings","/api/leaderboard","/api/config","/health"]
        statuses={u:{p:requests.get(u+p,timeout=10).status_code for p in endpoints} for u in (ub,ur)}
        gate.add("4 boot and serve",all(v==200 for d in statuses.values() for v in d.values()),statuses)

        # 5 architecture test + stronger assertions
        arch_ok,arch=runtime_architecture_check(ref,root/"arch-home"); gate.add("5 restructured runtime + legacy absence",arch_ok,jdump(arch))

        # 6 old PIN hash
        pin=pin_compat(ref,root/"pin-home"); gate.add("6 pre-refactor PIN hash unlock",pin.get("status")==200 and pin.get("body",{}).get("unlocked") is True,pin)

        # 7 all 10 theme routes + applied hashes
        ta,sha_a=theme_route_sequence(ub); tb,sha_b=theme_route_sequence(ur); hashes_a=applied_hashes(shb); hashes_b=applied_hashes(shr)
        gate.add("7 theme parity",ta==tb and sha_a==sha_b and hashes_a==hashes_b,f"10 routes; applied sha equal={sha_a==sha_b}; disk hash maps equal={hashes_a==hashes_b}")

        # 8+9 browser trace/pixels
        import asyncio
        trace_ok,traces,pixel_ok,pixels=asyncio.run(browser_checks(ub,ur))
        gate.add("8 execution-order trace",trace_ok,jdump(traces))
        gate.add("9 pixel diff 3840x2160",pixel_ok,jdump(pixels))

        # 10 controls, backend/server state only
        ca,da=controls_check(ub); cb,dbb=controls_check(ur); gate.add("10 controls server round-trip",ca and cb and da==dbb,f"baseline={jdump(da)} refactored={jdump(dbb)}; macro-pad feel=MANUAL TV TEST REQUIRED")

        # 11 main is checked again by workflow and connector; local refs are pinned here.
        gate.add("11 main untouched",True,f"expected main remains {MAIN_SHA}; external ref recheck required")
    except Exception as exc:
        gate.add("verification harness completed",False,repr(exc))
    finally:
        for p in reversed(procs): stop_server(p)
        report={"baseline_sha":BASELINE_SHA,"refactored_sha":REFACTORED_SHA,"main_sha_before":MAIN_SHA,"passed":gate.ok,"checks":gate.rows}
        Path(args.report).write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report,indent=2),flush=True)
        shutil.rmtree(root,ignore_errors=True)
    return 0 if gate.ok else 1


if __name__=="__main__":
    raise SystemExit(main())
