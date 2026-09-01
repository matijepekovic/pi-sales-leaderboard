/* Security settings owns the PIN gate and PIN changes. */
(function(){
  const $=id=>document.getElementById(id);
  let ready=false;

  function showLock(message=""){
    $("settingsLockOverlay")?.classList.add("open");
    $("settingsLockOverlay")?.setAttribute("aria-hidden","false");
    if($("appWrap"))$("appWrap").style.display="none";
    if($("unlockStatus"))$("unlockStatus").textContent=message;
    setTimeout(()=>$("unlockPin")?.focus(),40);
  }

  function publishReady(){
    if($("settingsLockOverlay")){
      $("settingsLockOverlay").classList.remove("open");
      $("settingsLockOverlay").setAttribute("aria-hidden","true");
    }
    if($("appWrap"))$("appWrap").style.display="";
    if(!ready){
      ready=true;
      window.StatsSettingsReady=true;
      document.dispatchEvent(new CustomEvent("stats:settings-ready"));
    }
  }

  async function json(url,options={}){
    const response=await fetch(url,{cache:"no-store",...options});
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false)throw new Error(data.error||`Request failed (${response.status})`);
    return data;
  }

  async function boot(){
    try{
      const status=await json("/api/auth/status");
      if(status.pin_set&&!status.unlocked){showLock();return;}
      publishReady();
    }catch(_){
      showLock("Could not reach Stats.");
    }
  }

  async function unlock(){
    const button=$("unlockBtn"),status=$("unlockStatus");
    if(button)button.disabled=true;if(status)status.textContent="Checking…";
    try{
      await json("/api/auth/unlock",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({pin:String($("unlockPin")?.value||"").trim()})
      });
      if($("unlockPin"))$("unlockPin").value="";
      if(status)status.textContent="";
      publishReady();
    }catch(err){if(status)status.textContent=err.message||"Incorrect PIN.";}
    finally{if(button)button.disabled=false;}
  }

  async function savePin(){
    const button=$("savePin"),status=$("pinStatus");
    if(button)button.disabled=true;if(status)status.textContent="Saving…";
    try{
      const result=await json("/api/auth/pin",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          current_pin:String($("pinCurrent")?.value||"").trim(),
          new_pin:String($("pinNew")?.value||"").trim()
        })
      });
      if($("pinCurrent"))$("pinCurrent").value="";
      if($("pinNew"))$("pinNew").value="";
      if(status)status.textContent=result.pin_set?"PIN saved.":"PIN removed.";
    }catch(err){if(status)status.textContent=err.message||"Could not save PIN.";}
    finally{if(button)button.disabled=false;}
  }

  async function lockNow(){
    try{await fetch("/api/auth/lock",{method:"POST"});}catch(_){ }
    location.reload();
  }

  function install(){
    $("unlockBtn")?.addEventListener("click",unlock);
    $("unlockPin")?.addEventListener("keydown",event=>{if(event.key==="Enter")unlock();});
    $("savePin")?.addEventListener("click",savePin);
    $("lockNow")?.addEventListener("click",lockNow);
    boot();
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
