/* Number size for built-in leaderboard Screens. */
(function(){
  const $=id=>document.getElementById(id);
  const MIN=60,MAX=300,STEP=10;
  const SUPPORTED=new Set(["whole_office","team_vs_team","all_teams","per_team"]);
  let snapshot=null,mode="",screenName="";

  function modeKey(raw){
    const value=String(raw||"");
    return value.startsWith("per_team::")?"per_team":value;
  }

  function mount(){
    const host=$("settingsNumberSizeControls");if(!host||$("numberSizeCard"))return false;
    host.innerHTML=`<div class="card" id="numberSizeCard">
      <h2>Number Size</h2>
      <p class="small">Adjust the number size for the active built-in leaderboard Screen. Custom Screens own their own presentation.</p>
      <div class="row" style="align-items:center;margin-top:12px">
        <button id="numberSizeMinus" class="btn" type="button" aria-label="Smaller numbers">Font −</button>
        <div id="numberSizeValue" class="strong" style="min-width:110px;text-align:center">100%</div>
        <button id="numberSizePlus" class="btn" type="button" aria-label="Bigger numbers">Font +</button>
      </div>
      <div id="numberSizeScreen" class="small" style="margin-top:8px"></div>
      <div id="numberSizeStatus" class="small settings-status"></div>
    </div>`;
    $("numberSizeMinus").addEventListener("click",()=>nudge(-STEP));
    $("numberSizePlus").addEventListener("click",()=>nudge(STEP));
    load();return true;
  }

  function current(){
    const value=Number(snapshot?.settings?.number_font_scale?.[mode]);
    return Number.isFinite(value)?Math.min(MAX,Math.max(MIN,value)):100;
  }

  function paint(){
    const supported=SUPPORTED.has(mode);
    $("numberSizeValue").textContent=supported?`${current()}%`:"—";
    $("numberSizeMinus").disabled=!supported||current()<=MIN;
    $("numberSizePlus").disabled=!supported||current()>=MAX;
    $("numberSizeScreen").textContent=supported
      ?`Applies to: ${screenName||mode}`
      :`Number Size is not used by ${screenName||"the active Screen"}.`;
  }

  async function load(){
    const status=$("numberSizeStatus");
    try{
      const response=await fetch("/api/config",{cache:"no-store"});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(data.error||"Could not load Number Size.");
      snapshot=data;
      const activeId=data.display?.active_screen_id;
      const screen=(data.screens||[]).find(item=>item.id===activeId)||null;
      mode=screen?.kind==="builtin"?modeKey(screen.mode):"";
      screenName=screen?.name||"Active Screen";
      status.textContent="";paint();
    }catch(err){status.textContent=err.message||"Could not load Number Size.";}
  }

  async function nudge(delta){
    if(!SUPPORTED.has(mode)||!snapshot)return;
    const status=$("numberSizeStatus"),next=Math.min(MAX,Math.max(MIN,current()+delta));
    status.textContent="Saving…";
    try{
      const response=await fetch("/api/config",{
        method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({number_font_scale:{[mode]:next}})
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false)throw new Error(data.error||"Could not save Number Size.");
      snapshot.settings=data.settings||snapshot.settings;
      paint();status.textContent="Saved. The TV updates on its next refresh.";
    }catch(err){status.textContent=err.message||"Could not save Number Size.";}
  }

  function start(){let tries=0;(function attempt(){if(mount())return;if(++tries<80)setTimeout(attempt,50);})();}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
