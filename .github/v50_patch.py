from pathlib import Path
import json

server = Path('app/server.py')
s = server.read_text()
old = '''MODES = {\n    "whole_office": "Whole Office",\n    "team_vs_team": "Team vs Team",\n    "all_teams": "All Teams",\n    "per_team": "Per Team",\n}\n'''
new = old + '\nNON_DISPLAY_METRICS = {"home_branch", "title", "hire_date"}\n'
if 'NON_DISPLAY_METRICS = ' not in s:
    if old not in s:
        raise SystemExit('MODES block not found')
    s = s.replace(old, new, 1)
old = '    visible = settings["visible_metrics"].get(mode, [])\n'
new = '    visible = [\n        key for key in settings["visible_metrics"].get(mode, [])\n        if key not in NON_DISPLAY_METRICS\n    ]\n'
if old in s:
    s = s.replace(old, new, 1)
old = '''        "metrics": [\n            {"key": key, "label": label, "type": typ}\n            for key, label, typ in METRIC_DEFS\n        ],'''
new = '''        "metrics": [\n            {"key": key, "label": label, "type": typ}\n            for key, label, typ in METRIC_DEFS\n            if key not in NON_DISPLAY_METRICS\n        ],'''
if old in s:
    s = s.replace(old, new, 1)
old = '    valid_keys = {k for k, _, _ in METRIC_DEFS}\n'
new = '    valid_keys = {k for k, _, _ in METRIC_DEFS if k not in NON_DISPLAY_METRICS}\n'
if old in s:
    s = s.replace(old, new, 1)
server.write_text(s)

themes = Path('app/themes.py')
t = themes.read_text()
old = '    "hero": {"label": "Hero / Header Art", "builtin": "hero.png"},\n'
new = old + '    "logo_small": {"label": "Logo Small", "builtin": "hero.png"},\n'
if '"logo_small": {"label": "Logo Small"' not in t:
    if old not in t:
        raise SystemExit('theme hero asset not found')
    t = t.replace(old, new, 1)
themes.write_text(t)

catalog_path = Path('app/static/asset-library/catalog.json')
catalog = json.loads(catalog_path.read_text())
cats = catalog.setdefault('categories', [])
if not any(c.get('key') == 'logo_small' for c in cats):
    cats.insert(0, {"key": "logo_small", "label": "Logo Small"})
for collection in catalog.setdefault('collections', []):
    bundle = collection.setdefault('bundle', {})
    if collection.get('key') == 'undisputed':
        bundle['logo_small'] = '/static/theme-packs/undisputed/hero.png'
    small = bundle.get('logo_small') or bundle.get('hero')
    items = collection.setdefault('items', [])
    if small and not any(i.get('category') == 'logo_small' for i in items):
        items.insert(0, {
            "key": f"{collection.get('key','collection')}-logo-small",
            "category": "logo_small",
            "label": "Logo Small",
            "targets": {"logo_small": small},
        })
catalog['version'] = 3
catalog_path.write_text(json.dumps(catalog, indent=2) + '\n')

library = Path('app/static/asset-library.js')
a = library.read_text()
a = a.replace('const CATALOG_URL="/static/asset-library/catalog.json?v=44";',
              'const CATALOG_URL="/static/asset-library/catalog.json?v=50";')
old = '''  async function loadCatalog(){\n    const response=await request(CATALOG_URL);\n    catalog=await response.json();\n    return catalog;\n  }\n'''
new = '''  function normalizeCatalog(raw){\n    const next=(raw&&typeof raw==="object")?raw:{categories:[],collections:[]};\n    next.categories=Array.isArray(next.categories)?next.categories:[];\n    if(!next.categories.some(c=>c?.key==="logo_small")){\n      next.categories.unshift({key:"logo_small",label:"Logo Small"});\n    }\n    next.collections=(Array.isArray(next.collections)?next.collections:[]).map(collection=>{\n      const c={...collection,bundle:{...(collection.bundle||{})},items:[...(collection.items||[])]};\n      const small=c.bundle.logo_small||c.bundle.hero||null;\n      if(small){\n        c.bundle.logo_small=small;\n        if(!c.items.some(item=>item?.category==="logo_small")){\n          c.items.unshift({\n            key:`${c.key||"collection"}-logo-small`,\n            category:"logo_small",\n            label:"Logo Small",\n            targets:{logo_small:small}\n          });\n        }\n      }\n      return c;\n    });\n    return next;\n  }\n\n  async function loadCatalog(){\n    const response=await request(CATALOG_URL);\n    catalog=normalizeCatalog(await response.json());\n    return catalog;\n  }\n'''
if 'function normalizeCatalog(raw)' not in a:
    if old not in a:
        raise SystemExit('loadCatalog block not found')
    a = a.replace(old, new, 1)
library.write_text(a)

cleanup = Path('app/static/whole-office-cleanup-v50.js')
cleanup.write_text('''/* v50 Whole Office presentation cleanup.\n   Data/ranking remain owned by the existing renderer. This layer only removes\n   the redundant mode label and adds a small team identity asset beside Team. */\n(function(){\n  if(typeof render!=="function") return;\n  const previousRender=render;\n  const STYLE_ID="v50WholeOfficeIdentityStyles";\n\n  function ensureStyles(){\n    if(document.getElementById(STYLE_ID)) return;\n    const style=document.createElement("style");\n    style.id=STYLE_ID;\n    style.textContent=`\n      #scaleRoot td.v50-team-cell{padding-top:5px;padding-bottom:5px}\n      #scaleRoot .v50-team-identity{display:inline-flex;align-items:center;gap:8px;min-width:0;vertical-align:middle}\n      #scaleRoot .v50-team-logo{width:clamp(36px,3vw,56px);height:clamp(24px,2.4vw,42px);object-fit:contain;flex:0 0 auto}\n      #scaleRoot .v50-team-name{white-space:nowrap}\n    `;\n    document.head.appendChild(style);\n  }\n\n  function teamTheme(data,name){\n    return data?.theme_state?.by_name?.[String(name||"").trim().toLowerCase()]||null;\n  }\n\n  function decorateWholeOffice(data){\n    if(data?.mode!=="whole_office") return;\n    const mode=document.getElementById("modeLabel");\n    if(mode) mode.textContent="";\n\n    const metrics=Array.isArray(data.metrics)?data.metrics:[];\n    const teamIndex=metrics.indexOf("team");\n    if(teamIndex<0) return;\n\n    const table=document.querySelector("#scaleRoot table");\n    if(!table) return;\n    ensureStyles();\n\n    table.querySelectorAll("tbody tr:not(.total-row)").forEach(row=>{\n      const cell=row.cells[teamIndex];\n      if(!cell) return;\n      const teamName=String(cell.textContent||"").trim();\n      if(!teamName) return;\n      const theme=teamTheme(data,teamName);\n      const teamId=Number(theme?.team_id||0);\n      const small=theme?.assets?.logo_small||null;\n      const fallback=teamId?`/api/teams/${teamId}/logo?v=${Number(data.organization_version||0)}`:null;\n      const src=small||fallback;\n      if(!src) return;\n\n      cell.classList.add("v50-team-cell");\n      cell.textContent="";\n      const wrap=document.createElement("span");\n      wrap.className="v50-team-identity";\n      const img=document.createElement("img");\n      img.className="v50-team-logo";\n      img.src=src;\n      img.alt="";\n      img.addEventListener("error",()=>img.remove(),{once:true});\n      const label=document.createElement("span");\n      label.className="v50-team-name";\n      label.textContent=teamName;\n      wrap.append(img,label);\n      cell.appendChild(wrap);\n    });\n  }\n\n  render=function(data){\n    const result=previousRender(data);\n    decorateWholeOffice(data);\n    return result;\n  };\n})();\n''')

display = Path('app/templates/display.html')
d = display.read_text()
if 'whole-office-cleanup-v50.js' not in d:
    d = d.rstrip() + '\n<script src="/static/whole-office-cleanup-v50.js?v=50"></script>\n'
display.write_text(d)

settings = Path('app/templates/settings.html')
sh = settings.read_text().replace('/static/asset-library.js?v=44', '/static/asset-library.js?v=50')
settings.write_text(sh)

Path('VERSION').write_text('50\n')
