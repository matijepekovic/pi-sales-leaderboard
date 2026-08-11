from pathlib import Path
p=Path('app/static/theme-studio.js')
s=p.read_text()
old='''  async function resetTheme(){
    if(!currentScope){byId("themeStatus").textContent="Create a team first.";return;}
    byId("themeStatus").textContent="Resetting…";
    try{await jsonFetch(`/api/themes/${encodeURIComponent(currentScope)}`,{method:"DELETE"});await refreshState();byId("themeStatus").textContent="Theme reset to Classic.";}catch(e){byId("themeStatus").textContent=e.message;}
  }
'''
new='''  async function resetTheme(){
    if(!currentScope){byId("themeStatus").textContent="Create a team first.";return;}
    if(!confirm("Reset this design to the Classic theme? Custom artwork for this theme will stop being used."))return;
    try{await jsonFetch(`/api/themes/${encodeURIComponent(currentScope)}`,{method:"DELETE"});await refreshState();byId("themeStatus").textContent="Reset to Classic.";}catch(e){byId("themeStatus").textContent=e.message;}
  }
'''
if old not in s: raise SystemExit('reset block not found')
p.write_text(s.replace(old,new,1))
