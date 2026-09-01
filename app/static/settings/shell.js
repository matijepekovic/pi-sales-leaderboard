/* Settings shell owns navigation and page framing only. */
(function(){
  const ACTIVE_KEY="stats.settings.section";
  const buttons=()=>Array.from(document.querySelectorAll("[data-settings-target]"));
  const sections=()=>Array.from(document.querySelectorAll(".settings-section"));

  function activate(id,focus=false){
    const target=document.getElementById(id)||sections()[0];
    if(!target)return;
    sections().forEach(section=>section.classList.toggle("active",section===target));
    buttons().forEach(button=>{
      const active=button.dataset.settingsTarget===target.id;
      button.setAttribute("aria-selected",active?"true":"false");
      button.tabIndex=active?0:-1;
      if(active&&focus)button.focus();
    });
    const title=document.getElementById("settingsPageTitle");
    const description=document.getElementById("settingsPageDescription");
    if(title)title.textContent=target.dataset.settingsTitle||"Settings";
    if(description)description.textContent=target.dataset.settingsDescription||"";
    const content=document.getElementById("settingsContent");
    if(content)content.scrollTop=0;
    try{localStorage.setItem(ACTIVE_KEY,target.id);}catch(_){ }
  }

  function navKeydown(event){
    const list=buttons();const index=list.indexOf(document.activeElement);if(index<0)return;
    let next=index;
    if(event.key==="ArrowDown"||event.key==="ArrowRight")next=(index+1)%list.length;
    else if(event.key==="ArrowUp"||event.key==="ArrowLeft")next=(index-1+list.length)%list.length;
    else if(event.key==="Home")next=0;
    else if(event.key==="End")next=list.length-1;
    else return;
    event.preventDefault();activate(list[next].dataset.settingsTarget,true);
  }

  function boot(){
    buttons().forEach(button=>button.addEventListener("click",()=>activate(button.dataset.settingsTarget)));
    document.getElementById("settingsNav")?.addEventListener("keydown",navKeydown);
    document.getElementById("settingsBack")?.addEventListener("click",()=>window.location.assign("/"));
    let wanted="settingsWorkspace";
    try{wanted=localStorage.getItem(ACTIVE_KEY)||wanted;}catch(_){ }
    activate(wanted);
    window.StatsSettingsShell=Object.freeze({activate});
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});else boot();
})();
