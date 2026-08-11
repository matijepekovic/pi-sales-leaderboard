from pathlib import Path

runtime = Path('app/static/theme-runtime.js')
s = runtime.read_text()

s = s.replace(
'''      .theme-hero{\n        display:block;max-height:clamp(72px,15vh,180px);max-width:min(56vw,900px);\n        object-fit:contain;filter:drop-shadow(0 4px 10px rgba(0,0,0,.8));\n        margin:0 18px 0 0;\n      }\n''',
'''      .theme-hero{\n        display:block;max-height:clamp(72px,15vh,180px);max-width:min(56vw,900px);\n        object-fit:contain;filter:drop-shadow(0 4px 10px rgba(0,0,0,.8));\n        margin:0 18px 0 0;\n      }\n      .theme-office-logo{\n        grid-column:1;grid-row:1 / 3;\n        width:clamp(86px,9vw,170px);height:clamp(66px,10vh,128px);\n        object-fit:contain;align-self:center;justify-self:start;\n        filter:drop-shadow(0 4px 10px rgba(0,0,0,.8));\n      }\n      body.team-theme-full header.theme-office-logo-active>div:first-child{\n        display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:auto auto;\n        column-gap:16px;align-items:center;min-width:0;\n      }\n      body.team-theme-full header.theme-office-logo-active #title{\n        grid-column:2;grid-row:1;align-self:end;\n      }\n      body.team-theme-full header.theme-office-logo-active .subtitle{\n        grid-column:2;grid-row:2;align-self:start;\n      }\n''',
1)

old = '''    document.querySelectorAll(".theme-frame,.theme-corner,.theme-hero").forEach(el=>el.remove());\n    document.body.classList.remove("team-theme-full");\n    const header=document.querySelector("header");\n    if(header) header.classList.remove("theme-has-hero");\n'''
new = '''    document.querySelectorAll(".theme-frame,.theme-corner,.theme-hero,.theme-office-logo").forEach(el=>el.remove());\n    document.body.classList.remove("team-theme-full");\n    const header=document.querySelector("header");\n    if(header) header.classList.remove("theme-has-hero","theme-office-logo-active");\n'''
if old not in s:
    raise SystemExit('removeDecor block not found')
s = s.replace(old,new,1)

old = '''  function chooseHero(data,theme){\n    const assets=theme.assets||{};\n'''
new = '''  function chooseHero(data,theme){\n    if(data.mode==="whole_office") return null;\n    const assets=theme.assets||{};\n'''
if old not in s:
    raise SystemExit('chooseHero block not found')
s = s.replace(old,new,1)

anchor = '''  function applyFullTheme(data,theme){\n'''
insert = '''  function renderedOfficeWinner(data){\n    const metrics=Array.isArray(data.metrics)?data.metrics:[];\n    const first=document.querySelector("#scaleRoot table tbody tr:not(.total-row)");\n    if(!first) return null;\n\n    let teamName="";\n    const teamIndex=metrics.indexOf("team");\n    if(teamIndex>=0 && first.cells[teamIndex]){\n      teamName=String(first.cells[teamIndex].textContent||"").trim();\n    }\n\n    let repName="";\n    const repIndex=metrics.indexOf("rep_name");\n    if(repIndex>=0 && first.cells[repIndex]){\n      repName=String(first.cells[repIndex].textContent||"").trim();\n    }\n\n    const source=(data.rows||[]).find(row=>{\n      if(repName && String(row?.rep_name||"").trim()!==repName) return false;\n      if(teamName && String(row?.team||"").trim()!==teamName) return false;\n      return !!(repName||teamName);\n    })||null;\n    if(!teamName && source) teamName=String(source.team||"").trim();\n    if(!teamName) return null;\n\n    return {\n      team_name:teamName,\n      team_id:source?.assigned_team_id||source?.team_id||null,\n      rep_name:repName||source?.rep_name||""\n    };\n  }\n\n  function injectOfficeLogo(data,theme){\n    const teamId=Number(theme?.team_id||0);\n    if(!teamId) return;\n    const header=document.querySelector("header");\n    const first=header&&header.querySelector(":scope > div:first-child");\n    if(!header||!first) return;\n    const img=document.createElement("img");\n    img.className="theme-office-logo";\n    img.src=`/api/teams/${teamId}/logo?v=${Number(data.organization_version||0)}`;\n    img.alt=theme.team_name||"Leading team";\n    img.addEventListener("error",()=>{img.remove();header.classList.remove("theme-office-logo-active");},{once:true});\n    first.insertBefore(img,first.firstChild);\n    header.classList.add("theme-office-logo-active");\n  }\n\n'''
if anchor not in s:
    raise SystemExit('applyFullTheme anchor not found')
s = s.replace(anchor,insert+anchor,1)

old = '''    injectFrame(theme);\n\n    const header=document.querySelector("header");\n'''
new = '''    injectFrame(theme);\n    if(data.mode==="whole_office") injectOfficeLogo(data,theme);\n\n    const header=document.querySelector("header");\n'''
if old not in s:
    raise SystemExit('injectFrame anchor not found')
s = s.replace(old,new,1)

old = '''    if(assets.totals_mark){\n      const total=document.querySelector("tr.total-row");\n'''
new = '''    if(assets.totals_mark && data.mode==="per_team"){\n      const total=document.querySelector("tr.total-row");\n'''
if old not in s:
    raise SystemExit('totals mark block not found')
s = s.replace(old,new,1)

old = '''    }else if(data.mode==="whole_office"){\n      applyFullTheme(data,(data.theme_state||{}).office);\n    }else{\n'''
new = '''    }else if(data.mode==="whole_office"){\n      const winner=renderedOfficeWinner(data);\n      const winningTheme=winner?lookupTheme(data,winner.team_name,winner.team_id):null;\n      applyFullTheme(data,winningTheme);\n    }else{\n'''
if old not in s:
    raise SystemExit('whole office theme block not found')
s = s.replace(old,new,1)

runtime.write_text(s)

display=Path('app/templates/display.html')
d=display.read_text().replace('/static/theme-runtime.js?v=43','/static/theme-runtime.js?v=51')
display.write_text(d)

Path('VERSION').write_text('51\n')
