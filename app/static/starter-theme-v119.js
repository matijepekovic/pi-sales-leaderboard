/* v119: Starter is the default theme pack; Classic remains the plain option. */
(function(){
  function install(){
    const select=document.getElementById("tdPreset");
    if(!select) return false;

    if(!select.querySelector('option[value="starter"]')){
      const option=document.createElement("option");
      option.value="starter";
      option.textContent="Starter";
      select.insertBefore(option,select.firstChild);
    }

    const classic=select.querySelector('option[value="classic"]');
    if(classic) classic.textContent="Plain";
    const legacy=select.querySelector('option[value="undisputed"]');
    if(legacy) legacy.textContent="UNDISPUTED (existing)";

    // Phase 2: the base theme picker used to change only the live editor state.
    // Persist it immediately through Theme Studio's existing Save Design path,
    // just like the other theme controls, so closing/restarting Stats cannot
    // silently restore the previous base theme.
    if(!select.dataset.v119Autosave){
      select.dataset.v119Autosave="1";
      select.addEventListener("change",()=>{
        const save=document.getElementById("tdSave");
        if(save&&!save.disabled) save.click();
      });
    }

    const reset=document.getElementById("tdReset");
    if(reset&&!reset.dataset.v119Reset){
      reset.dataset.v119Reset="1";
      reset.textContent="Reset to Starter";
      reset.addEventListener("click",async e=>{
        e.preventDefault();
        e.stopImmediatePropagation();
        const name=String(document.getElementById("tdWhoName")?.textContent||"").trim();
        const team=(window.teamDefs||[]).find(t=>String(t.name||"").trim()===name);
        if(!team) return;
        if(!confirm("Reset this team's design to Starter? Custom artwork stops being used, but nothing is deleted.")) return;
        const status=document.getElementById("tdStatus");
        try{
          const response=await fetch(`/api/themes/team-${Number(team.team_id)}`,{method:"DELETE",cache:"no-store"});
          const data=await response.json().catch(()=>({}));
          if(!response.ok||data.ok===false) throw new Error(data.error||"Could not reset theme.");
          if(typeof window.openTeamDesign==="function") await window.openTeamDesign(Number(team.team_id));
          if(status) status.textContent="Reset to Starter.";
        }catch(err){
          if(status) status.textContent=err.message||"Could not reset theme.";
        }
      },true);
    }
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(install()) return;
      if(++tries<160) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(start,0),{once:true});
  }else{
    setTimeout(start,0);
  }
})();
