/* v112/v115 physical controls.
   Five actions are mapped from one shared set of keyboard and mouse inputs.
   v115 adds Product Close Rates as a normal previous/next rotation screen. */
(function(){
  const INACTIVITY_MS=5*60*1000;
  const NUMERIC_TYPES=new Set(["number","percent","currency"]);
  const DEFAULT_KEYS={
    previous:"ArrowLeft",
    next:"ArrowRight",
    pair:"ArrowUp",
    sort_prev:"MouseWheelUp",
    sort_next:"MouseWheelDown"
  };
  let config=null;
  let override=null;
  let expiryTimer=null;
  let lastWheelAt=0;

  const norm=v=>String(v||"").trim().toLowerCase();
  const parsedMode=view=>String(view||"").startsWith("per_team::")?"per_team":String(view||"");

  function keyToken(value){
    value=String(value??"");
    return value.length===1&&value!==" "?value.toLowerCase():value;
  }

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

  function availableViews(){
    return ["whole_office","team_vs_team","all_teams","product_close",...teamNames().map(name=>`per_team::${name}`)];
  }

  function viewList(){
    const available=availableViews();
    const saved=config?.settings?.keyboard_cycle_views;
    if(!Array.isArray(saved)||!saved.length) return available;
    const chosen=saved.map(String).filter(view=>available.includes(view));
    return chosen.length?chosen:available.slice(0,1);
  }

  function inputMap(){
    const saved=config?.settings?.keyboard_cycle_keys;
    const map=saved&&typeof saved==="object"?saved:{};
    return {
      previous:keyToken(map.previous||DEFAULT_KEYS.previous),
      next:keyToken(map.next||DEFAULT_KEYS.next),
      pair:keyToken(map.pair||DEFAULT_KEYS.pair),
      sort_prev:keyToken(map.sort_prev||DEFAULT_KEYS.sort_prev),
      sort_next:keyToken(map.sort_next||DEFAULT_KEYS.sort_next)
    };
  }

  function actionForInput(input){
    const map=inputMap();
    for(const action of ["previous","next","pair","sort_prev","sort_next"]){
      if(map[action]===input) return action;
    }
    return null;
  }

  function ensureOverride(){
    if(override) return override;
    override={view:remoteView(),pair:null,sortByMode:{},expiresAt:0};
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
    if(index<0){
      state.view=delta<0?views[views.length-1]:views[0];
    }else{
      index=(index+delta+views.length)%views.length;
      state.view=views[index];
    }
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

  function act(action){
    if(!config) return false;
    let changed=false;
    if(action==="previous") changed=moveView(-1);
    else if(action==="next") changed=moveView(1);
    else if(action==="pair") changed=movePair(1);
    else if(action==="sort_prev") changed=moveSort(-1);
    else if(action==="sort_next") changed=moveSort(1);
    if(!changed) return false;
    markActivity();
    forceReload();
    return true;
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
    if(event.repeat||!config) return;
    const action=actionForInput(keyToken(event.key));
    if(!action) return;
    event.preventDefault();
    act(action);
  },true);

  window.addEventListener("wheel",event=>{
    if(!event.deltaY||!config) return;
    const token=event.deltaY<0?"MouseWheelUp":"MouseWheelDown";
    const action=actionForInput(token);
    if(!action) return;
    const now=Date.now();
    if(now-lastWheelAt<55){event.preventDefault();return;}
    lastWheelAt=now;
    event.preventDefault();
    act(action);
  },{passive:false,capture:true});

  document.addEventListener("mousedown",event=>{
    if(!config) return;
    const token=event.button===0?"MouseLeft":event.button===1?"MouseMiddle":event.button===2?"MouseRight":null;
    if(!token) return;
    const action=actionForInput(token);
    if(!action) return;
    event.preventDefault();
    act(action);
  },true);

  document.addEventListener("contextmenu",event=>{
    if(config&&actionForInput("MouseRight")) event.preventDefault();
  },true);

  refreshConfig();
  setInterval(refreshConfig,1000);
})();
