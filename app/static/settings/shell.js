/* Settings shell owns navigation and authentication framing only. */
(function(){
  const ACTIVE_KEY="stats.settings.section";
  const runtime=window.StatsSettings;
  const $=id=>document.getElementById(id);
  const buttons=()=>Array.from(document.querySelectorAll("[data-settings-target]"));
  const sections=()=>Array.from(document.querySelectorAll(".settings-section"));

  function setLocked(locked){
    $("settingsLockOverlay")?.classList.toggle("open",!!locked);
    $("settingsLockOverlay")?.setAttribute("aria-hidden",locked?"false":"true");
    if($("appWrap")) $("appWrap").style.display=locked?"none":"";
    if(locked) setTimeout(()=>$("unlockPin")?.focus(),0);
  }

  async function authStatus(){
    try{const data=await runtime.api("/api/auth/status");setLocked(!data.unlocked);return !!data.unlocked;}
    catch(_){setLocked(true);return false;}
  }

  async function unlock(){
    const status=$("unlockStatus"),button=$("unlockBtn"),pin=$("unlockPin");if(!pin||!button)return;
    button.disabled=true;if(status)status.textContent="Unlocking…";
    try{await runtime.api("/api/auth/unlock",runtime.json("POST",{pin:pin.value}));pin.value="";if(status)status.textContent="";setLocked(false);runtime.emit("unlocked");runtime.emit("section",activeSectionId());}
    catch(error){if(status)status.textContent=error.message||"Could not unlock.";}finally{button.disabled=false;}
  }

  function activeSectionId(){return sections().find(section=>section.classList.contains("active"))?.id||"settingsOverview";}
  function activate(id,focus=false){
    const target=$(id)||sections()[0];if(!target)return;
    sections().forEach(section=>section.classList.toggle("active",section===target));
    buttons().forEach(button=>{const active=button.dataset.settingsTarget===target.id;button.setAttribute("aria-selected",active?"true":"false");button.tabIndex=active?0:-1;if(active&&focus)button.focus();});
    $("settingsPageTitle").textContent=target.dataset.settingsTitle||"Settings";$("settingsPageDescription").textContent=target.dataset.settingsDescription||"";
    if($("settingsContent"))$("settingsContent").scrollTop=0;try{localStorage.setItem(ACTIVE_KEY,target.id);}catch(_){ }runtime.emit("section",target.id);
  }

  function navKeydown(event){
    const list=buttons(),index=list.indexOf(document.activeElement);if(index<0)return;let next=index;
    if(event.key==="ArrowDown"||event.key==="ArrowRight")next=(index+1)%list.length;else if(event.key==="ArrowUp"||event.key==="ArrowLeft")next=(index-1+list.length)%list.length;else if(event.key==="Home")next=0;else if(event.key==="End")next=list.length-1;else return;
    event.preventDefault();activate(list[next].dataset.settingsTarget,true);
  }

  function boot(){
    buttons().forEach(button=>button.addEventListener("click",()=>activate(button.dataset.settingsTarget)));$("settingsNav")?.addEventListener("keydown",navKeydown);$("settingsBack")?.addEventListener("click",()=>window.location.assign("/"));$("unlockBtn")?.addEventListener("click",unlock);$("unlockPin")?.addEventListener("keydown",event=>{if(event.key==="Enter")unlock();});document.addEventListener("stats:settings-locked",()=>setLocked(true));
    let wanted="settingsOverview";try{wanted=localStorage.getItem(ACTIVE_KEY)||wanted;}catch(_){ }if(!$(wanted))wanted="settingsOverview";activate(wanted);authStatus().then(unlocked=>{if(unlocked)runtime.emit("section",activeSectionId());});
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});else boot();
})();
