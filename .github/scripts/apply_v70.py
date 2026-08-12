from pathlib import Path


def replace(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old in s:
        s = s.replace(old, new, 1)
    elif new not in s:
        raise SystemExit(f"{label} pattern not found in {path}")
    p.write_text(s)


# --------------------------- read-only API overrides -------------------------
replace(
    "app/server.py",
    "def get_mode_payload(mode=None):\n",
    "def get_mode_payload(mode=None, sort_metric_override=None, team_vs_team_override=None):\n",
    "get_mode_payload signature",
)
replace(
    "app/server.py",
    '''    reps = list_reps()\n    metric = settings["sort_metric"].get(mode, "net_split")\n    direction = "desc"\n''',
    '''    reps = list_reps()\n    numeric_sort_metrics = {\n        key for key, _, typ in METRIC_DEFS\n        if typ in ("number", "percent", "currency") and key != "rank"\n    }\n    metric = settings["sort_metric"].get(mode, "net_split")\n    if sort_metric_override in numeric_sort_metrics:\n        metric = sort_metric_override\n    direction = "desc"\n''',
    "sort metric override",
)
replace(
    "app/server.py",
    '''        selected = list(dict.fromkeys(settings.get("team_vs_team_selected") or []))[:2]\n''',
    '''        requested_pair = (\n            team_vs_team_override\n            if isinstance(team_vs_team_override, (list, tuple))\n            else None\n        )\n        selected = list(dict.fromkeys(\n            requested_pair or settings.get("team_vs_team_selected") or []\n        ))[:2]\n''',
    "team pair override",
)
replace(
    "app/server.py",
    '''@app.get("/api/leaderboard")\ndef api_leaderboard():\n    mode = request.args.get("mode")\n    settings = get_settings()\n    payload = get_mode_payload(mode)\n    payload.update({\n''',
    '''@app.get("/api/leaderboard")\ndef api_leaderboard():\n    mode = request.args.get("mode")\n    sort_metric_override = request.args.get("sort_metric")\n    team_override = request.args.getlist("team")\n    settings = get_settings()\n    payload = get_mode_payload(\n        mode,\n        sort_metric_override=sort_metric_override,\n        team_vs_team_override=team_override[:2] if team_override else None,\n    )\n    numeric_sort_metrics = {\n        key for key, _, typ in METRIC_DEFS\n        if typ in ("number", "percent", "currency") and key != "rank"\n    }\n    effective_sort_metric = sort_metric_override\n    if effective_sort_metric not in numeric_sort_metrics:\n        effective_sort_metric = settings["sort_metric"].get(payload["mode"], "net_split")\n    payload.update({\n''',
    "leaderboard query overrides",
)
replace(
    "app/server.py",
    '''        "sort_metric": settings["sort_metric"].get(payload["mode"], "net_split"),\n''',
    '''        "sort_metric": effective_sort_metric,\n''',
    "leaderboard effective sort metric",
)


# ------------------------ display request URL hook ---------------------------
replace(
    "app/templates/display_v35_base.html",
    '''    const res = await fetch("/api/leaderboard", {cache:"no-store"});\n''',
    '''    const leaderboardUrl = typeof window.keyboardLeaderboardUrl === "function"\n      ? window.keyboardLeaderboardUrl("/api/leaderboard")\n      : "/api/leaderboard";\n    const res = await fetch(leaderboardUrl, {cache:"no-store"});\n''',
    "leaderboard URL hook",
)


# ---------------------------- keyboard runtime -------------------------------
Path("app/static/keyboard-controls-v70.js").write_text(r'''/* v70 physical keyboard / macro-pad controls.
   Temporary local override only: no keyboard action writes Settings. After
   five minutes without a recognized control input the display drops every
   override and immediately reloads the latest remote-app configuration. */
(function(){
  const INACTIVITY_MS=5*60*1000;
  const NUMERIC_TYPES=new Set(["number","percent","currency"]);
  let config=null;
  let override=null;
  let expiryTimer=null;
  let lastWheelAt=0;

  const norm=v=>String(v||"").trim().toLowerCase();
  const parsedMode=view=>String(view||"").startsWith("per_team::")?"per_team":String(view||"");

  async function refreshConfig(){
    try{
      const response=await fetch("/api/config",{cache:"no-store"});
      if(!response.ok) throw new Error("config");
      config=await response.json();
      return config;
    }catch(_){
      return config;
    }
  }

  function remoteView(){
    const settings=config?.settings||{};
    let active=String(settings.active_mode||"whole_office");
    if(active==="per_team"){
      const team=String(settings.per_team_selected||"").trim();
      if(team) active=`per_team::${team}`;
    }
    return active;
  }

  function teamNames(){
    return (config?.team_definitions||[])
      .map(team=>String(team?.name||"").trim())
      .filter(Boolean);
  }

  function viewList(){
    return ["whole_office","team_vs_team","all_teams",...teamNames().map(name=>`per_team::${name}`)];
  }

  function ensureOverride(){
    if(override) return override;
    override={
      view:remoteView(),
      pair:null,
      sortByMode:{},
      expiresAt:0,
    };
    const selected=(config?.settings?.team_vs_team_selected||[]).map(String).filter(Boolean).slice(0,2);
    if(selected.length===2) override.pair=selected;
    return override;
  }

  function pairs(){
    const names=teamNames(),out=[];
    for(let i=0;i<names.length;i++){
      for(let j=i+1;j<names.length;j++) out.push([names[i],names[j]]);
    }
    return out;
  }

  function samePair(a,b){
    if(!Array.isArray(a)||!Array.isArray(b)||a.length!==2||b.length!==2) return false;
    return (norm(a[0])===norm(b[0])&&norm(a[1])===norm(b[1])) ||
           (norm(a[0])===norm(b[1])&&norm(a[1])===norm(b[0]));
  }

  function ensurePair(state){
    const all=pairs();
    if(!all.length){state.pair=null;return null;}
    const found=all.find(pair=>samePair(pair,state.pair));
    state.pair=found||all[0];
    return state.pair;
  }

  function markActivity(){
    const state=ensureOverride();
    state.expiresAt=Date.now()+INACTIVITY_MS;
    clearTimeout(expiryTimer);
    expiryTimer=setTimeout(endOverride,INACTIVITY_MS+25);
  }

  function forceReload(){
    try{ if(typeof lastSignature!=="undefined") lastSignature=""; }catch(_){}
    if(typeof load==="function") load();
  }

  function endOverride(){
    if(!override) return;
    if(Date.now()+10<override.expiresAt){
      clearTimeout(expiryTimer);
      expiryTimer=setTimeout(endOverride,Math.max(25,override.expiresAt-Date.now()+25));
      return;
    }
    override=null;
    clearTimeout(expiryTimer);
    expiryTimer=null;
    forceReload();
  }

  function moveView(delta){
    const state=ensureOverride();
    const views=viewList();
    if(!views.length) return false;
    let index=views.indexOf(state.view);
    if(index<0) index=views.indexOf(remoteView());
    if(index<0) index=0;
    index=(index+delta+views.length)%views.length;
    state.view=views[index];
    if(parsedMode(state.view)==="team_vs_team") ensurePair(state);
    return true;
  }

  function movePair(delta){
    const state=ensureOverride();
    if(parsedMode(state.view)!=="team_vs_team") return false;
    const all=pairs();
    if(!all.length) return false;
    let index=all.findIndex(pair=>samePair(pair,state.pair));
    if(index<0) index=0;
    else index=(index+delta+all.length)%all.length;
    state.pair=all[index];
    return true;
  }

  function sortableMetrics(mode){
    const defs=new Map((config?.metrics||[]).map(item=>[item.key,item]));
    const visible=config?.settings?.visible_metrics?.[mode]||[];
    return visible.filter(key=>key!=="rank"&&NUMERIC_TYPES.has(defs.get(key)?.type));
  }

  function moveSort(delta){
    const state=ensureOverride();
    const mode=parsedMode(state.view);
    const metrics=sortableMetrics(mode);
    if(!metrics.length) return false;
    const remote=String(config?.settings?.sort_metric?.[mode]||"");
    const current=String(state.sortByMode[mode]||remote);
    let index=metrics.indexOf(current);
    if(index<0) index=0;
    else index=(index+delta+metrics.length)%metrics.length;
    state.sortByMode[mode]=metrics[index];
    return true;
  }

  async function act(action){
    await refreshConfig();
    if(!config) return;
    let changed=false;
    if(action==="left") changed=moveView(-1);
    else if(action==="right") changed=moveView(1);
    else if(action==="pair") changed=movePair(1);
    else if(action==="sort-prev") changed=moveSort(-1);
    else if(action==="sort-next") changed=moveSort(1);
    if(!changed) return;
    markActivity();
    forceReload();
  }

  window.keyboardLeaderboardUrl=function(base){
    if(!override) return base;
    const params=new URLSearchParams();
    params.set("mode",override.view);
    const mode=parsedMode(override.view);
    const metric=override.sortByMode[mode];
    if(metric) params.set("sort_metric",metric);
    if(mode==="team_vs_team"){
      ensurePair(override);
      (override.pair||[]).forEach(team=>params.append("team",team));
    }
    return `${base}?${params.toString()}`;
  };

  document.addEventListener("keydown",event=>{
    if(event.repeat) return;
    if(event.key==="ArrowLeft"){
      event.preventDefault();act("left");
    }else if(event.key==="ArrowRight"){
      event.preventDefault();act("right");
    }else if(event.key==="ArrowUp"){
      event.preventDefault();act("pair");
    }else if(event.key==="PageUp"||event.key==="["){
      event.preventDefault();act("sort-prev");
    }else if(event.key==="PageDown"||event.key==="]"){
      event.preventDefault();act("sort-next");
    }
  },true);

  // The LUKCOZMO knob can be flashed as mouse-wheel up/down. One wheel detent
  // equals one metric step. A short gate prevents a single detent from being
  // interpreted twice by noisy HID firmware.
  window.addEventListener("wheel",event=>{
    if(!event.deltaY) return;
    const now=Date.now();
    if(now-lastWheelAt<55){event.preventDefault();return;}
    lastWheelAt=now;
    event.preventDefault();
    act(event.deltaY<0?"sort-prev":"sort-next");
  },{passive:false,capture:true});

  refreshConfig();
})();
''')


# ------------------------------- script stack -------------------------------
replace(
    "app/templates/display.html",
    '<script src="/static/tv-preview-v63.js?v=63"></script>\n',
    '<script src="/static/tv-preview-v63.js?v=63"></script>\n<script src="/static/keyboard-controls-v70.js?v=70"></script>\n',
    "keyboard runtime script",
)

Path("VERSION").write_text("70\n")
