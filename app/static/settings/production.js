/* Production gating -- which features this build is allowed to show.

   Consolidated from the settings patch stack. Each section below was its own
   file and they are concatenated in their original load order, so what runs
   when is unchanged -- several of these mount by polling for a node the
   previous one creates. */


/* ------------------------------------------------------------------
   production-coming-eventually.js
   ------------------------------------------------------------------ */
/* Production feature-access UX.

   Phase 1 leaves every existing feature unlocked. The server publishes the
   central feature_access policy through /api/config; this script only blocks
   UI actions when that policy explicitly says a feature is unavailable.
*/
(function(){
  const MESSAGE="Coming eventually";
  let applying=false;
  let applyQueued=false;

  function featureFlags(){
    try{
      if(typeof config==="object"&&config&&config.feature_access&&
          typeof config.feature_access==="object"){
        return config.feature_access;
      }
    }catch(_){ }
    return {};
  }

  function canUse(feature){
    const flags=featureFlags();
    return flags[feature]!==false;
  }

  function featureForView(value){
    const raw=String(value||"").trim();
    if(raw.startsWith("per_team::")) return "per_team";
    return raw.split("::",1)[0];
  }

  function viewAllowed(value){
    const feature=featureForView(value);
    return !feature||canUse(feature);
  }

  function coming(){
    alert(MESSAGE);
  }

  function enforceAllowedMode(){
    const select=document.getElementById("activeMode");
    if(!select) return false;

    // Keep the production startup safety guard: Settings loads /api/config
    // asynchronously, so do not touch the select until its real options exist.
    // This prevents a MutationObserver/render loop while the page is booting.
    const wholeOfficeOption=select.querySelector('option[value="whole_office"]');
    if(!wholeOfficeOption) return false;

    if(viewAllowed(select.value)) return true;

    const fallback=[...select.options].find(option=>viewAllowed(option.value));
    if(!fallback) return true;

    select.value=fallback.value;
    try{
      if(typeof config==="object"&&config) config.active_mode=fallback.value;
      if(typeof parseActive==="function"){
        const parsed=parseActive(fallback.value);
        if(typeof displayMode!=="undefined") displayMode=parsed.mode;
      }
      if(typeof renderMode==="function") renderMode();
    }catch(_){ }
    return true;
  }

  function syncRotationRows(){
    document.querySelectorAll(".v112RotationView").forEach(input=>{
      const allowed=viewAllowed(input.value);
      const label=input.closest("label.check");

      if(!allowed){
        input.checked=false;
        input.setAttribute("aria-disabled","true");
        if(label){
          label.dataset.productionComing="1";
          label.style.opacity=".55";
          label.style.cursor="not-allowed";
          label.title=MESSAGE;
        }
        return;
      }

      input.removeAttribute("aria-disabled");
      if(label&&label.dataset.productionComing==="1"){
        delete label.dataset.productionComing;
        label.style.opacity="";
        label.style.cursor="";
        label.title="";
      }
    });
  }

  document.addEventListener("change",event=>{
    const select=event.target.closest?.("#activeMode");
    if(!select||viewAllowed(select.value)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    enforceAllowedMode();
    coming();
  },true);

  document.addEventListener("click",event=>{
    const rotationLabel=event.target.closest?.("label.check");
    const rotationInput=rotationLabel?.querySelector?.("input.v112RotationView")||
      event.target.closest?.("input.v112RotationView");
    if(rotationInput&&!viewAllowed(rotationInput.value)){
      event.preventDefault();
      event.stopImmediatePropagation();
      rotationInput.checked=false;
      coming();
      return;
    }

    const dateDetails=event.target.closest?.("#v113DateOverride");
    if(dateDetails&&!canUse("temporary_date")){
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
      if(!enforceAllowedMode()) return;
      syncRotationRows();
      const date=document.getElementById("v113DateOverride");
      if(date){
        if(canUse("temporary_date")){
          if(date.title===MESSAGE) date.title="";
        }else{
          date.open=false;
          date.title=MESSAGE;
        }
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

  const observer=new MutationObserver(scheduleApply);
  observer.observe(document.getElementById("appWrap")||document.body,{childList:true,subtree:true});

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",scheduleApply,{once:true});
  }else{
    scheduleApply();
  }
})();


/* ------------------------------------------------------------------
   production.js
   ------------------------------------------------------------------ */
/* Production Settings navigation + neutral Tableau connection examples. */
(function(){
  const EXAMPLES={
    v90Server:'Example: https://your-pod.online.tableau.com',
    v90Site:'Example: your-site',
    v90PatName:'Example: stats-pat'
  };

  function addBackButton(){
    const app=document.getElementById('appWrap');
    if(!app||document.getElementById('backToStats')) return !!app;

    const row=document.createElement('div');
    row.id='statsSettingsBackRow';
    row.style.cssText='display:flex;justify-content:flex-start;margin:0 0 12px';

    const button=document.createElement('button');
    button.id='backToStats';
    button.type='button';
    button.className='btn';
    button.textContent='← Back to Stats';
    button.setAttribute('aria-label','Back to Stats');
    button.addEventListener('click',()=>window.location.assign('/'));

    row.appendChild(button);
    app.insertBefore(row,app.firstChild);
    return true;
  }

  function applyExamples(){
    let found=0;
    Object.entries(EXAMPLES).forEach(([id,placeholder])=>{
      const input=document.getElementById(id);
      if(!input) return;
      input.placeholder=placeholder;
      found+=1;
    });
    return found===Object.keys(EXAMPLES).length;
  }

  function apply(){
    return addBackButton()&&applyExamples();
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(apply()) return;
      if(++tries<60) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true});
  else start();
})();
