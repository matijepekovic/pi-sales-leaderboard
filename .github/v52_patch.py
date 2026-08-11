from pathlib import Path

# v52: themes are team-owned only. Whole Office inherits the leading rep's team.

themes = Path('app/themes.py')
s = themes.read_text()

s = s.replace(
'''def _theme_store(settings):
    raw = settings.get("theme_config")
    if not isinstance(raw, dict):
        raw = {}
    office = raw.get("office") if isinstance(raw.get("office"), dict) else {}
    teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
    return {"office": dict(office), "teams": dict(teams)}
''',
'''def _theme_store(settings):
    raw = settings.get("theme_config")
    if not isinstance(raw, dict):
        raw = {}
    teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
    return {"teams": dict(teams)}
''',
1)

s = s.replace(
'''    if scope == "office":
        return "office", None
''',
'''    if scope == "office":
        raise ValueError("Whole Office inherits the theme of its #1 rep's team and cannot have its own theme.")
''',
1)

s = s.replace(
'''def _stored_config(settings, scope, team=None):
    store = _theme_store(settings)
    if scope == "office":
        return dict(store["office"])
    return dict(store["teams"].get(str(int(team["team_id"])), {}))
''',
'''def _stored_config(settings, scope, team=None):
    store = _theme_store(settings)
    return dict(store["teams"].get(str(int(team["team_id"])), {}))
''',
1)

s = s.replace(
'''def _set_config(settings, scope, team, config):
    store = _theme_store(settings)
    if scope == "office":
        store["office"] = config
    else:
        store["teams"][str(int(team["team_id"]))] = config
    return _save_store(settings, store)
''',
'''def _set_config(settings, scope, team, config):
    store = _theme_store(settings)
    store["teams"][str(int(team["team_id"]))] = config
    return _save_store(settings, store)
''',
1)

s = s.replace(
'''    return {
        "office": effective_theme("office", settings=settings),
        "teams": team_state,
        "by_name": by_name,
    }
''',
'''    return {
        "teams": team_state,
        "by_name": by_name,
    }
''',
1)

# Update validation wording too.
s = s.replace('Theme scope must be office or team-<id>.', 'Theme scope must be team-<id>.')

themes.write_text(s)

studio = Path('app/static/theme-studio.js')
t = studio.read_text()
t = t.replace('let currentScope="office";', 'let currentScope="";', 1)
t = t.replace(
'Full themes apply to individual team views. Team vs Team / All Teams use each team\'s colors and artwork. Whole Office has its own separate theme.',
'Themes belong to teams. Team view uses the full theme; Team vs Team and All Teams use each team\'s theme in their own sections; Whole Office automatically inherits the theme of the current #1 rep\'s team.',
1)
t = t.replace(
'''    sel.innerHTML=`<option value="office">Whole Office Theme</option>`+(state.teams||[]).map(t=>`<option value="team-${t.team_id}">${esc(t.name)}</option>`).join("");
    if([...sel.options].some(o=>o.value===old)) sel.value=old; else currentScope="office";
    populateScope();
''',
'''    sel.innerHTML=(state.teams||[]).map(t=>`<option value="team-${t.team_id}">${esc(t.name)}</option>`).join("");
    if([...sel.options].some(o=>o.value===old)){
      currentScope=old;sel.value=old;
    }else{
      currentScope=sel.options.length?sel.options[0].value:"";
      if(currentScope)sel.value=currentScope;
    }
    if(currentScope) populateScope();
    else byId("themeStatus").textContent="Create a team before building a theme.";
''',
1)
t = t.replace(
'''  function themeForScope(){
    if(!state) return null;
    if(currentScope==="office") return state.themes.office;
    const id=currentScope.split("-")[1];return state.themes.teams?.[id]||null;
  }
  function teamForScope(){
    if(currentScope==="office") return null;
    const id=Number(currentScope.split("-")[1]);return (state.teams||[]).find(t=>Number(t.team_id)===id)||null;
  }
''',
'''  function themeForScope(){
    if(!state||!currentScope) return null;
    const id=currentScope.split("-")[1];return state.themes.teams?.[id]||null;
  }
  function teamForScope(){
    if(!currentScope) return null;
    const id=Number(currentScope.split("-")[1]);return (state.teams||[]).find(t=>Number(t.team_id)===id)||null;
  }
''',
1)
# Make write actions safe if there are no teams.
t = t.replace('  async function saveTheme(){\n    byId("themeStatus").textContent="Saving…";', '  async function saveTheme(){\n    if(!currentScope){byId("themeStatus").textContent="Create a team first.";return;}\n    byId("themeStatus").textContent="Saving…";', 1)
t = t.replace('  async function resetTheme(){', '  async function resetTheme(){\n    if(!currentScope){byId("themeStatus").textContent="Create a team first.";return;}', 1)

studio.write_text(t)

settings = Path('app/templates/settings.html')
h = settings.read_text().replace('/static/theme-studio.js?v=43','/static/theme-studio.js?v=52')
settings.write_text(h)

Path('VERSION').write_text('52\n')
