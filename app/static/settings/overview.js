/* Settings Overview shows the current Stats configuration without owning it. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const state={version:"",system:null,sources:[],reports:[],screens:[],display:null,message:""};

  async function load(){
    const host=$("settingsOverviewHost");if(host)host.innerHTML='<div class="card"><div class="small">Loading current Stats state…</div></div>';
    try{
      const [version,system,sources,reports,screens,display]=await Promise.all([
        R.api("/api/system/version"),R.api("/api/state"),R.api("/api/data/sources"),R.api("/api/data/reports"),R.api("/api/screens"),R.api("/api/display")
      ]);
      state.version=String(version.version||"unknown");state.system=system;state.sources=sources.sources||[];state.reports=reports.reports||[];state.screens=screens.screens||[];state.display=display;state.message="";
    }catch(error){state.message=error.message||"Could not load Stats state.";}
    render();
  }

  function nameBy(items,id){return items.find(item=>String(item.id)===String(id))?.name||String(id||"");}
  function list(items,empty,detail){return items.length?items.map(item=>`<div class="subcard"><strong>${esc(item.name||item.id)}</strong>${detail?`<div class="small" style="margin-top:4px">${detail(item)}</div>`:""}</div>`).join(""):`<div class="small">${esc(empty)}</div>`;}

  function render(){
    const host=$("settingsOverviewHost");if(!host)return;
    if(state.message){host.innerHTML=`<div class="card"><div class="danger-text">${esc(state.message)}</div><button class="btn" data-overview-reload style="margin-top:12px">Reload</button></div>`;bind();return;}
    const d=state.display||{},current=nameBy(state.screens,d.current_screen_id),active=nameBy(state.screens,d.active_screen_id);
    host.innerHTML=`
      <div class="grid">
        <div class="card"><div class="small">Version</div><div class="strong">${esc(state.version)}</div></div>
        <div class="card"><div class="small">Sources</div><div class="strong">${state.sources.length}</div></div>
        <div class="card"><div class="small">Reports</div><div class="strong">${state.reports.length}</div></div>
        <div class="card"><div class="small">Screens</div><div class="strong">${state.screens.length}</div></div>
      </div>
      <div class="card"><div class="toolbar"><div><h2>Current Display</h2><div class="small">What Stats is configured to show right now.</div></div><button class="btn" data-overview-reload>Reload</button></div><div class="grid" style="margin-top:12px"><div><label>Active Screen</label><div class="field-readout strong">${esc(active||"None")}</div></div><div><label>Currently Playing</label><div class="field-readout strong">${esc(current||"None")}</div></div><div><label>Rotation</label><div class="field-readout strong">${d.rotation_enabled?"On":"Off"}${d.rotation_enabled?` · ${Number(d.rotation_seconds||15)}s`:""}</div></div><div><label>Revisions</label><div class="field-readout small">Data ${Number(state.system?.data_version||0)} · Settings ${Number(state.system?.settings_version||0)}</div></div></div></div>
      <div class="grid" style="align-items:start">
        <div class="card"><h2>Sources</h2><div class="stack" style="margin-top:10px">${list(state.sources,"No Sources configured.",item=>`${esc(item.adapter||"")} · ${esc(item.connection?.server||"Not configured")}`)}</div></div>
        <div class="card"><h2>Reports</h2><div class="stack" style="margin-top:10px">${list(state.reports,"No Reports configured.",item=>`${esc(item.status||"Not pulled yet")}${item.last_refresh?` · ${esc(item.last_refresh)}`:""}`)}</div></div>
      </div>
      <div class="card"><h2>Screens</h2><div class="stack" style="margin-top:10px">${list(state.screens,"No Screens configured.",item=>`${(item.reports||[]).length} Report${(item.reports||[]).length===1?"":"s"} · ${item.theme_mode==="custom"?"Custom Theme":"Inherited Theme"}`)}</div></div>`;
    bind();
  }
  function bind(){$("settingsOverviewHost")?.querySelectorAll("[data-overview-reload]").forEach(button=>button.addEventListener("click",load));}
  R.on("section",id=>{if(id==="settingsOverview")load();});R.on("unlocked",()=>{});R.on("data-changed",()=>{});R.on("screens-changed",()=>{});
})();
