/* v121 Windows Settings desktop shell.
   Reuses the existing v98 section groups and moves them into a permanent left
   navigation + large content workspace. No settings controls or API behavior
   are replaced; existing DOM nodes and event listeners stay intact. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  const isWindows=/windows|win32|win64/i.test(platform);
  if(!isWindows) return;

  const ACTIVE_KEY="stats.windows.settings.active.v121";
  const $=id=>document.getElementById(id);
  let activeKey="";
  try{ activeKey=String(localStorage.getItem(ACTIVE_KEY)||""); }catch(_){ }

  const LABELS={
    "view":"Display",
    "tv-remote":"TV Controls",
    "team-builder":"Teams",
    "data":"Data & Tableau",
    "software":"Software",
    "security":"Security"
  };
  const DESCRIPTIONS={
    "view":"Choose what Stats shows and how leaderboard data is displayed.",
    "tv-remote":"Control and refresh the fullscreen Stats display.",
    "team-builder":"Create teams, assign members, and open team design tools.",
    "data":"Manage Tableau connection, report status, and data options.",
    "software":"Check the installed version and manage Stats updates.",
    "security":"Control access to the Settings interface."
  };

  function injectStyles(){
    if($("windowsSettingsSidebarStyles")) return;
    const style=document.createElement("style");
    style.id="windowsSettingsSidebarStyles";
    style.textContent=`
      body.windows-settings-desktop{
        padding:0 !important;overflow:hidden;background:#0b0b0b
      }
      #appWrap.windows-settings-desktop{
        width:100%;max-width:none !important;height:100vh;min-height:100vh;
        margin:0 !important;padding:0 !important;overflow:hidden
      }
      #appWrap.windows-settings-desktop > h1,
      #appWrap.windows-settings-desktop > .lead,
      #appWrap.windows-settings-desktop > .persist-note{
        display:none !important
      }
      #windowsSettingsShell{
        height:100vh;min-height:0;display:grid;
        grid-template-columns:clamp(220px,20vw,280px) minmax(0,1fr);
        background:#0b0b0b
      }
      #windowsSettingsSidebar{
        min-width:0;min-height:0;display:flex;flex-direction:column;
        background:#101821;border-right:1px solid #25313e;color:#f4f4f4;
        box-shadow:8px 0 24px rgba(0,0,0,.12);z-index:2
      }
      .ws-brand{
        min-height:88px;padding:20px 20px 16px;border-bottom:1px solid #25313e;
        display:flex;flex-direction:column;justify-content:center
      }
      .ws-brand-title{font-size:22px;font-weight:900;letter-spacing:.01em}
      .ws-brand-sub{margin-top:4px;color:#91a0b2;font-size:12px;text-transform:uppercase;letter-spacing:.11em}
      #windowsSettingsBackSlot{padding:12px 12px 4px}
      #windowsSettingsBackSlot #statsSettingsBackRow{margin:0 !important;display:block !important}
      #windowsSettingsBackSlot #backToStats{
        width:100%;min-height:42px;text-align:left;border-color:#314151;background:#131f2a
      }
      .ws-nav-label{
        padding:14px 18px 7px;color:#718197;font-size:11px;font-weight:900;
        text-transform:uppercase;letter-spacing:.12em
      }
      #windowsSettingsNav{
        min-height:0;overflow:auto;padding:0 10px 18px;scrollbar-width:thin
      }
      .ws-nav-button{
        width:100%;min-height:48px;margin:2px 0;padding:11px 14px;
        border:0;border-left:3px solid transparent;border-radius:7px;
        background:transparent;color:#c9d2dc;display:flex;align-items:center;gap:11px;
        text-align:left;font:700 15px Arial,Helvetica,sans-serif;cursor:pointer
      }
      .ws-nav-button:hover{background:#172432;color:#fff}
      .ws-nav-button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
      .ws-nav-button[aria-selected="true"]{
        background:#213142;color:#fff;border-left-color:var(--accent)
      }
      .ws-nav-mark{
        width:9px;height:9px;flex:0 0 auto;border-radius:2px;
        border:1px solid currentColor;opacity:.72;transform:rotate(45deg)
      }
      .ws-nav-button[aria-selected="true"] .ws-nav-mark{
        background:var(--accent);border-color:var(--accent);opacity:1
      }
      .ws-side-footer{
        margin-top:auto;padding:13px 18px 16px;border-top:1px solid #25313e;
        color:#718197;font-size:11px;line-height:1.4
      }
      #windowsSettingsMain{
        min-width:0;min-height:0;height:100vh;display:flex;flex-direction:column;
        background:#0b0b0b
      }
      #windowsSettingsHeader{
        flex:0 0 auto;min-height:88px;padding:19px clamp(22px,3vw,42px) 16px;
        border-bottom:1px solid #252525;background:#111;display:flex;
        align-items:center;justify-content:space-between;gap:20px
      }
      #windowsSettingsTitle{margin:0;font-size:clamp(23px,2.2vw,32px);line-height:1.1}
      #windowsSettingsDescription{margin-top:6px;color:var(--muted);font-size:13px;line-height:1.4}
      #windowsSettingsContent{
        flex:1 1 auto;min-height:0;overflow:auto;
        padding:clamp(20px,3vw,42px);overscroll-behavior:contain
      }
      #windowsSettingsContentInner{width:100%;max-width:1600px;margin:0 auto}
      #windowsSettingsContent #v98Sections{display:block !important;margin:0 !important}
      #windowsSettingsContent #v98Sections > .v98-section{
        display:none;margin:0 !important;border:0 !important;background:transparent !important
      }
      #windowsSettingsContent #v98Sections > .v98-section[data-ws-active="true"]{display:block}
      #windowsSettingsContent #v98Sections > .v98-section > summary{display:none !important}
      #windowsSettingsContent #v98Sections > .v98-section > .v98-section-body{
        padding:0 !important;border:0 !important
      }
      #windowsSettingsContent .v98-inner-card{
        width:100%;max-width:none !important
      }
      #windowsSettingsContent .grid{
        grid-template-columns:repeat(auto-fit,minmax(min(310px,100%),1fr));gap:16px
      }
      #windowsSettingsContent .grid3,
      #windowsSettingsContent .metrics,
      #windowsSettingsContent .source-fixed{
        grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr));gap:14px
      }
      #windowsSettingsContent .v98-subsection{
        border-radius:8px;overflow:hidden;margin:0 0 14px
      }
      #windowsSettingsContent .v98-inline-block{border-radius:8px}
      #windowsSettingsContent .btn{min-height:42px}
      #windowsSettingsContent .actions{position:sticky;bottom:0}

      /* The old phone-first top-level accordion is now the desktop tab host.
         Nested subsections remain collapsible because those are useful inside
         a large content page. */
      #v110QrSection{display:none !important}

      @media(max-width:980px){
        #windowsSettingsShell{grid-template-columns:210px minmax(0,1fr)}
        .ws-brand{padding-left:16px;padding-right:16px}
        .ws-brand-title{font-size:19px}
        #windowsSettingsHeader{padding-left:22px;padding-right:22px}
        #windowsSettingsContent{padding:22px}
      }
      @media(max-width:760px){
        #windowsSettingsShell{grid-template-columns:184px minmax(0,1fr)}
        .ws-nav-button{padding:10px 9px;font-size:13px;gap:8px}
        .ws-brand{padding:14px 12px;min-height:76px}
        .ws-brand-sub{font-size:10px}
        #windowsSettingsHeader{min-height:76px;padding:14px 16px}
        #windowsSettingsContent{padding:16px}
      }
    `;
    document.head.appendChild(style);
  }

  function rawLabel(section){
    return String(section.querySelector(":scope > summary")?.textContent||"Settings").replace(/\s+/g," ").trim();
  }

  function sectionKey(section){
    return String(section.dataset.v98Key||rawLabel(section).toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")||"settings");
  }

  function visibleSections(stack){
    return Array.from(stack.children).filter(section=>
      section.classList?.contains("v98-section") && section.id!=="v110QrSection"
    );
  }

  function labelFor(section){
    const key=sectionKey(section);
    return LABELS[key]||rawLabel(section)||"Settings";
  }

  function descriptionFor(section){
    const key=sectionKey(section);
    return DESCRIPTIONS[key]||`Manage ${labelFor(section).toLowerCase()} settings.`;
  }

  function storeActive(key){
    try{ localStorage.setItem(ACTIVE_KEY,key); }catch(_){ }
  }

  function activateSection(key,focusButton=false){
    const stack=$("v98Sections"),nav=$("windowsSettingsNav");
    if(!stack||!nav) return;
    const sections=visibleSections(stack);
    let target=sections.find(section=>sectionKey(section)===key);
    if(!target) target=sections.find(section=>sectionKey(section)==="view")||sections[0];
    if(!target) return;

    activeKey=sectionKey(target);
    sections.forEach(section=>{
      const active=section===target;
      section.dataset.wsActive=active?"true":"false";
      section.open=active;
      section.setAttribute("aria-hidden",active?"false":"true");
    });
    nav.querySelectorAll(".ws-nav-button").forEach(button=>{
      const active=button.dataset.wsKey===activeKey;
      button.setAttribute("aria-selected",active?"true":"false");
      button.tabIndex=active?0:-1;
      if(active&&focusButton) button.focus();
    });

    $("windowsSettingsTitle").textContent=labelFor(target);
    $("windowsSettingsDescription").textContent=descriptionFor(target);
    const content=$("windowsSettingsContent");
    if(content) content.scrollTop=0;
    storeActive(activeKey);
  }

  function rebuildNav(){
    const stack=$("v98Sections"),nav=$("windowsSettingsNav");
    if(!stack||!nav) return;
    const sections=visibleSections(stack);
    const wanted=sections.map(section=>sectionKey(section)).join("|");
    if(nav.dataset.wsKeys===wanted) return;
    nav.dataset.wsKeys=wanted;
    nav.innerHTML="";

    sections.forEach(section=>{
      const key=sectionKey(section);
      section.dataset.wsKey=key;
      const button=document.createElement("button");
      button.type="button";
      button.className="ws-nav-button";
      button.dataset.wsKey=key;
      button.setAttribute("role","tab");
      button.setAttribute("aria-controls",section.id||`windows-settings-panel-${key}`);
      button.innerHTML=`<span class="ws-nav-mark" aria-hidden="true"></span><span></span>`;
      button.querySelector("span:last-child").textContent=labelFor(section);
      if(!section.id) section.id=`windows-settings-panel-${key}`;
      button.addEventListener("click",()=>activateSection(key));
      nav.appendChild(button);
    });

    if(!nav.dataset.wsKeyboardBound){
      nav.dataset.wsKeyboardBound="1";
      nav.addEventListener("keydown",navKeydown);
    }
    activateSection(activeKey||"view");
  }

  function navKeydown(event){
    const nav=$("windowsSettingsNav");
    if(!nav) return;
    const buttons=Array.from(nav.querySelectorAll(".ws-nav-button"));
    const current=buttons.indexOf(document.activeElement);
    if(current<0) return;
    let next=current;
    if(event.key==="ArrowDown") next=(current+1)%buttons.length;
    else if(event.key==="ArrowUp") next=(current-1+buttons.length)%buttons.length;
    else if(event.key==="Home") next=0;
    else if(event.key==="End") next=buttons.length-1;
    else return;
    event.preventDefault();
    activateSection(buttons[next].dataset.wsKey,true);
  }

  function moveBackButton(){
    const slot=$("windowsSettingsBackSlot"),row=$("statsSettingsBackRow");
    if(slot&&row&&row.parentElement!==slot) slot.appendChild(row);
  }

  function buildShell(stack){
    const root=$("appWrap");
    if(!root||$("windowsSettingsShell")) return;
    injectStyles();
    document.body.classList.add("windows-settings-desktop");
    root.classList.add("windows-settings-desktop");

    const shell=document.createElement("div");
    shell.id="windowsSettingsShell";
    shell.innerHTML=`
      <aside id="windowsSettingsSidebar" aria-label="Settings navigation">
        <div class="ws-brand">
          <div class="ws-brand-title">Stats Settings</div>
          <div class="ws-brand-sub">Windows desktop</div>
        </div>
        <div id="windowsSettingsBackSlot"></div>
        <div class="ws-nav-label">Settings</div>
        <nav id="windowsSettingsNav" role="tablist" aria-orientation="vertical"></nav>
        <div class="ws-side-footer">Changes save through the existing Stats settings controls.</div>
      </aside>
      <main id="windowsSettingsMain">
        <header id="windowsSettingsHeader">
          <div>
            <h1 id="windowsSettingsTitle">Settings</h1>
            <div id="windowsSettingsDescription"></div>
          </div>
        </header>
        <div id="windowsSettingsContent">
          <div id="windowsSettingsContentInner"></div>
        </div>
      </main>`;

    root.insertBefore(shell,root.firstChild);
    $("windowsSettingsContentInner").appendChild(stack);
    moveBackButton();
    rebuildNav();
  }

  function organize(){
    const stack=$("v98Sections"),root=$("appWrap");
    if(!root||!stack) return false;
    if(!$("windowsSettingsShell")) buildShell(stack);
    moveBackButton();
    rebuildNav();
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(organize()){
        const stack=$("v98Sections");
        if(stack){
          new MutationObserver(()=>{
            rebuildNav();
            moveBackButton();
          }).observe(stack,{childList:true});
        }
        return;
      }
      if(++tries<120) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();
})();
