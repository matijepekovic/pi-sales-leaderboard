/* Production-only gates for features that stay visible but are not shippable yet. */
(function(){
  const MESSAGE="Coming eventually";
  const DISABLED_ROTATION=new Set(["team_vs_team","all_teams"]);
  let applying=false;
  let applyQueued=false;

  function coming(){
    alert(MESSAGE);
  }

  function forceWholeOffice(){
    const select=document.getElementById("activeMode");
    if(!select) return false;

    // Settings loads /api/config asynchronously. Before that response returns,
    // activeMode has no options. Assigning a value that has no matching option
    // leaves select.value empty. The old MutationObserver interpreted that as a
    // new change forever, called renderMode(), observed its DOM rewrite, and
    // immediately repeated the cycle until Chromium reported Page Unresponsive.
    // Do nothing until the actual production option has been mounted.
    const wholeOfficeOption=select.querySelector('option[value="whole_office"]');
    if(!wholeOfficeOption) return false;

    let changed=false;
    if(select.value!=="whole_office"){
      select.value="whole_office";
      if(select.value==="whole_office") changed=true;
    }
    try{
      if(typeof config==="object"&&config&&config.active_mode!=="whole_office"){
        config.active_mode="whole_office";
        changed=true;
      }
      if(typeof displayMode!=="undefined"&&displayMode!=="whole_office"){
        displayMode="whole_office";
        changed=true;
      }
      if(changed&&typeof renderMode==="function") renderMode();
    }catch(_){ }
    return true;
  }

  function lockRotationRows(){
    document.querySelectorAll(".v112RotationView").forEach(input=>{
      const value=String(input.value||"");
      if(!DISABLED_ROTATION.has(value)) return;
      input.checked=false;
      input.setAttribute("aria-disabled","true");
      const label=input.closest("label.check");
      if(label){
        label.dataset.productionComing="1";
        label.style.opacity=".55";
        label.style.cursor="not-allowed";
        label.title=MESSAGE;
      }
    });
  }

  document.addEventListener("change",event=>{
    const select=event.target.closest?.("#activeMode");
    if(!select) return;
    if(String(select.value||"")!=="whole_office"){
      event.preventDefault();
      event.stopImmediatePropagation();
      forceWholeOffice();
      coming();
    }
  },true);

  document.addEventListener("click",event=>{
    const rotationLabel=event.target.closest?.("label.check");
    const rotationInput=rotationLabel?.querySelector?.("input.v112RotationView")||
      event.target.closest?.("input.v112RotationView");
    if(rotationInput&&DISABLED_ROTATION.has(String(rotationInput.value||""))){
      event.preventDefault();
      event.stopImmediatePropagation();
      rotationInput.checked=false;
      coming();
      return;
    }

    const dateDetails=event.target.closest?.("#v113DateOverride");
    if(dateDetails){
      event.preventDefault();
      event.stopImmediatePropagation();
      dateDetails.open=false;
      coming();
    }
  },true);

  function apply(){
    if(applying) return;
    applying=true;
    try{
      // If Settings is still booting, wait for a later DOM mutation instead of
      // touching the incomplete select and creating a self-triggering loop.
      if(!forceWholeOffice()) return;
      lockRotationRows();
      const date=document.getElementById("v113DateOverride");
      if(date){
        date.open=false;
        date.title=MESSAGE;
      }
    }finally{
      applying=false;
    }
  }

  function scheduleApply(){
    if(applyQueued) return;
    applyQueued=true;
    setTimeout(()=>{
      applyQueued=false;
      apply();
    },0);
  }

  // Only watch the settings application subtree, and debounce callbacks onto a
  // later task. DOM changes made by apply() can therefore never recurse inside
  // the same MutationObserver turn.
  const observer=new MutationObserver(scheduleApply);
  observer.observe(document.getElementById("appWrap")||document.body,{childList:true,subtree:true});

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",scheduleApply,{once:true});
  }else{
    scheduleApply();
  }
})();
