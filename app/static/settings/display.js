/* Display Settings owns active Screen and rotation playback configuration. */
(function(){
  const runtime=window.StatsSettings,$=id=>document.getElementById(id),esc=runtime.esc;
  const state={display:null,message:""};let loaded=false;

  async function load(){state.display=await runtime.api("/api/display");loaded=true;render();}
  function screenBy(id){return (state.display?.screens||[]).find(screen=>String(screen.id)===String(id))||null;}

  function render(){
    const host=$("settingsDisplayHost");if(!host)return;
    if(!state.display){host.innerHTML='<div class="card"><div class="small">Loading Display…</div></div>';return;}
    const d=state.display,screens=d.screens||[],rotation=new Set(d.rotation_screen_ids||[]);
    host.innerHTML=`<div class="card"><div class="toolbar"><div><h2>Display</h2><div class="small">The Display only chooses which Screen is playing. Screen data and Filters are configured elsewhere.</div></div><button class="btn" data-display-action="open-tv">Open TV</button></div><div class="grid" style="margin-top:14px"><div><label>Active Screen</label><select id="displayActiveScreen">${screens.map(screen=>`<option value="${esc(screen.id)}" ${screen.id===d.active_screen_id?"selected":""}>${esc(screen.name)}</option>`).join("")}</select></div><div><label>Currently Playing</label><div class="strong field-readout">${esc(screenBy(d.current_screen_id)?.name||d.current_screen_id||"")}</div></div></div><div class="subcard" style="margin-top:14px"><label class="choice"><input id="displayRotationEnabled" type="checkbox" ${d.rotation_enabled?"checked":""}><span><strong>Rotate Screens</strong><br><span class="small">Cycle through the checked Screens below.</span></span></label><div style="margin-top:10px;max-width:260px"><label for="displayRotationSeconds">Seconds per Screen</label><input id="displayRotationSeconds" type="number" min="5" max="3600" value="${Number(d.rotation_seconds||15)}"></div><div class="stack" style="margin-top:12px">${screens.map(screen=>`<label class="choice"><input type="checkbox" data-rotation-screen="${esc(screen.id)}" ${rotation.has(screen.id)?"checked":""}><span>${esc(screen.name)}</span></label>`).join("")}</div></div><div class="row" style="margin-top:14px"><button class="btn primary" data-display-action="save">Save Display</button><button class="btn" data-display-action="reload">Reload</button></div><div class="status">${esc(state.message||"")}</div></div>`;
    host.querySelectorAll('[data-display-action]').forEach(button=>button.addEventListener("click",()=>handle(button.dataset.displayAction)));
  }

  async function handle(action){
    if(action==="open-tv"){window.open("/","_blank");return;}
    if(action==="reload"){state.message="";return load().catch(error=>{state.message=error.message;render();});}
    if(action!=="save")return;
    const host=$("settingsDisplayHost");const payload={active_screen_id:host.querySelector("#displayActiveScreen")?.value||"",rotation_enabled:!!host.querySelector("#displayRotationEnabled")?.checked,rotation_seconds:Number(host.querySelector("#displayRotationSeconds")?.value||15),rotation_screen_ids:Array.from(host.querySelectorAll('[data-rotation-screen]:checked')).map(input=>input.dataset.rotationScreen)};
    state.message="Saving Display…";render();
    try{state.display=await runtime.api("/api/display",runtime.json("PUT",payload));state.display.screens=(await runtime.api("/api/screens")).screens||[];state.message="Display saved.";}catch(error){state.message=error.message;}render();
  }

  runtime.on("section",id=>{if(id==="settingsDisplay"&&!loaded)load().catch(error=>{state.message=error.message;render();});});runtime.on("unlocked",()=>{loaded=false;});runtime.on("screens-changed",()=>{loaded=false;if($("settingsDisplay")?.classList.contains("active"))load().catch(()=>{});});
})();
