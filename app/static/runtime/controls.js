/* Controls runtime -- physical input and on-screen affordances.

   Keyboard, mouse and macro pad post named actions to the
   server; the QR overlay and the Windows desktop menu live here
   because they are the other things a person touches.

   Consolidated from the versioned patch stack. Each section below was its own
   file, wrapping the previous one by reassigning render(). They now register
   ordered stages instead, so this grouping is presentation only -- the
   execution order is the numbers, not the file boundaries. */


/* ------------------------------------------------------------------
   keyboard-controls.js   (stage/style order 230)
   ------------------------------------------------------------------ */
/* Physical controls: keyboard, mouse and macro pad.

   This file used to own the rotation itself -- which screen was showing, which
   team pair, which sort column, and a five minute idle timer -- inside a
   closure. That made the steer private to one tab: a second display never saw
   it, a reload lost it, and the list of screens had to be repeated here so the
   closure could walk it.

   The server owns that state now. This file recognises an input, names the
   action, and posts it. The key map and the action list come from the server
   too, so there is one definition of each. */
(function(){
  let keys=null;
  let lastWheelAt=0;

  function keyToken(value){
    value=String(value??"");
    return value.length===1&&value!==" "?value.toLowerCase():value;
  }

  async function refreshVocabulary(){
    try{
      const response=await fetch("/api/keyboard-controls",{cache:"no-store"});
      if(!response.ok) throw new Error("controls");
      const payload=await response.json();
      const map=payload?.keyboard?.keys;
      if(map&&typeof map==="object"){
        const resolved={};
        for(const action of Object.keys(map)) resolved[action]=keyToken(map[action]);
        keys=resolved;
      }
    }catch(_){ /* keep the last known map rather than going deaf */ }
    return keys;
  }

  function actionForInput(input){
    if(!keys) return null;
    for(const action of Object.keys(keys)){
      if(keys[action]===input) return action;
    }
    return null;
  }

  function forceReload(){
    try{ if(typeof lastSignature!=="undefined") lastSignature=""; }catch(_){}
    if(typeof load==="function") load();
  }

  async function act(action){
    try{
      const response=await fetch("/api/controls/action",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        cache:"no-store",
        body:JSON.stringify({action})
      });
      if(!response.ok) return false;
      const payload=await response.json();
      if(payload?.state?.changed) forceReload();
      return true;
    }catch(_){
      return false;
    }
  }

  document.addEventListener("keydown",event=>{
    if(event.repeat) return;
    const action=actionForInput(keyToken(event.key));
    if(!action) return;
    event.preventDefault();
    act(action);
  },true);

  window.addEventListener("wheel",event=>{
    if(!event.deltaY) return;
    const action=actionForInput(event.deltaY<0?"MouseWheelUp":"MouseWheelDown");
    if(!action) return;
    event.preventDefault();
    // The pad emits a burst of wheel events per detent; one step per detent.
    const now=Date.now();
    if(now-lastWheelAt<55) return;
    lastWheelAt=now;
    act(action);
  },{passive:false,capture:true});

  document.addEventListener("mousedown",event=>{
    const token=event.button===0?"MouseLeft":event.button===1?"MouseMiddle":event.button===2?"MouseRight":null;
    if(!token) return;
    const action=actionForInput(token);
    if(!action) return;
    event.preventDefault();
    act(action);
  },true);

  document.addEventListener("contextmenu",event=>{
    if(actionForInput("MouseRight")) event.preventDefault();
  },true);

  refreshVocabulary();
  setInterval(refreshVocabulary,5000);
})();


/* ------------------------------------------------------------------
   remote-qr-overlay.js   (stage/style order 320)
   ------------------------------------------------------------------ */
/* v110: QR-only TV overlay with persistent size + free position controls. */
(function(){
  const DEFAULT={size:68,x:100,y:0};
  const LIMITS={min:36,max:180,margin:12};
  let state={...DEFAULT};
  let overlay=null;
  let qrImage=null;

  const clamp=(value,min,max)=>Math.min(max,Math.max(min,Number(value)||0));

  function qrSrc(){
    return `/static/remote-qr-v109.svg?v=115&t=${Date.now()}`;
  }

  function reloadQr(){
    if(!qrImage) return;
    qrImage.src=qrSrc();
  }

  function openSettings(){
    window.location.assign('/settings');
  }

  function mount(){
    if(document.getElementById('remoteQrV110')) return;

    const style=document.createElement('style');
    style.id='remoteQrV110Style';
    style.textContent=`
      #remoteQrV110{
        position:fixed;
        z-index:2147483000;
        box-sizing:border-box;
        padding:3px;
        border-radius:7px;
        background:#000;
        box-shadow:0 0 0 1px rgba(255,255,255,.10);
        line-height:0;
        pointer-events:auto;
        cursor:pointer;
        user-select:none;
      }
      #remoteQrV110 img{display:block;height:auto;border-radius:4px}
    `;
    Display.placeStyle(320, style);

    overlay=document.createElement('div');
    overlay.id='remoteQrV110';
    overlay.setAttribute('role','button');
    overlay.setAttribute('tabindex','0');
    overlay.setAttribute('aria-label','Open Settings');
    overlay.title='Double-click to open Settings';
    overlay.addEventListener('dblclick',(event)=>{
      event.preventDefault();
      event.stopPropagation();
      openSettings();
    });

    qrImage=document.createElement('img');
    qrImage.alt='';
    qrImage.draggable=false;
    qrImage.addEventListener('load',()=>{overlay.style.display='block';});
    qrImage.addEventListener('error',()=>{overlay.style.display='none';});
    overlay.appendChild(qrImage);
    document.body.appendChild(overlay);

    apply();
    reloadQr();
    refresh();
    setInterval(refresh,2000);
    // Windows regenerates the underlying QR whenever its LAN address changes.
    // Reload the tiny SVG so a restart/update can never leave a stale link on TV.
    setInterval(reloadQr,15000);
    window.addEventListener('resize',apply);
  }

  function apply(){
    if(!overlay) return;
    const image=overlay.querySelector('img');
    const size=Math.round(clamp(state.size,LIMITS.min,LIMITS.max));
    const x=clamp(state.x,0,100);
    const y=clamp(state.y,0,100);
    const pad=6;
    const total=size+pad;
    const margin=Math.min(LIMITS.margin,Math.max(4,Math.floor(Math.min(innerWidth,innerHeight)*.01)));
    const travelX=Math.max(0,innerWidth-total-margin*2);
    const travelY=Math.max(0,innerHeight-total-margin*2);
    overlay.style.left=`${Math.round(margin+travelX*x/100)}px`;
    overlay.style.top=`${Math.round(margin+travelY*y/100)}px`;
    image.style.width=`${size}px`;
  }

  async function refresh(){
    try{
      const response=await fetch('/api/config',{cache:'no-store'});
      if(!response.ok) return;
      const data=await response.json();
      const settings=data.settings||{};
      const next={
        size:clamp(settings.qr_overlay_size??DEFAULT.size,LIMITS.min,LIMITS.max),
        x:clamp(settings.qr_overlay_x??DEFAULT.x,0,100),
        y:clamp(settings.qr_overlay_y??DEFAULT.y,0,100)
      };
      if(next.size!==state.size||next.x!==state.x||next.y!==state.y){
        state=next;
        apply();
      }
    }catch(_){ }
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();


/* ------------------------------------------------------------------
   windows-desktop-menu.js   (stage/style order 330)
   ------------------------------------------------------------------ */
/* v120 Windows desktop navigation.
   Windows no longer advertises phone control. The legacy TV QR is hidden and
   replaced by a small desktop hamburger that opens Settings in the same kiosk. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  const isWindows=/windows|win32|win64/i.test(platform);
  if(!isWindows || window.top!==window.self) return;

  function mount(){
    if(document.getElementById("statsDesktopMenuButton")) return;

    const style=document.createElement("style");
    style.id="statsDesktopMenuStyles";
    style.textContent=`
      #remoteQrV110{display:none !important}
      #statsDesktopMenuWrap{
        position:fixed;top:14px;right:14px;z-index:2147483640;
        font-family:Arial,Helvetica,sans-serif;color:#fff
      }
      #statsDesktopMenuButton{
        width:50px;height:50px;display:grid;place-items:center;padding:0;
        border:1px solid rgba(255,255,255,.18);border-radius:10px;
        background:rgba(8,8,8,.88);color:#fff;cursor:pointer;
        box-shadow:0 8px 24px rgba(0,0,0,.28);backdrop-filter:blur(8px)
      }
      #statsDesktopMenuButton:hover,#statsDesktopMenuButton:focus-visible{
        border-color:rgba(255,255,255,.42);background:rgba(22,22,22,.94)
      }
      #statsDesktopMenuButton:focus-visible{outline:2px solid #d8b34a;outline-offset:2px}
      .stats-menu-bars{width:23px;display:grid;gap:4px}
      .stats-menu-bars span{display:block;height:2px;border-radius:2px;background:currentColor}
      #statsDesktopMenuPanel{
        position:absolute;top:58px;right:0;width:190px;padding:7px;
        border:1px solid rgba(255,255,255,.16);border-radius:10px;
        background:rgba(12,12,12,.96);box-shadow:0 14px 34px rgba(0,0,0,.4);
        backdrop-filter:blur(10px)
      }
      #statsDesktopMenuPanel[hidden]{display:none}
      #statsDesktopMenuPanel button{
        width:100%;min-height:44px;padding:10px 12px;border:0;border-radius:7px;
        background:transparent;color:#fff;text-align:left;font:600 15px Arial,Helvetica,sans-serif;
        cursor:pointer
      }
      #statsDesktopMenuPanel button:hover,#statsDesktopMenuPanel button:focus-visible{
        background:#242424;outline:none
      }
    `;
    document.head.appendChild(style);

    const wrap=document.createElement("div");
    wrap.id="statsDesktopMenuWrap";
    wrap.innerHTML=`
      <button id="statsDesktopMenuButton" type="button" aria-label="Open menu"
              aria-expanded="false" aria-controls="statsDesktopMenuPanel" title="Menu">
        <span class="stats-menu-bars" aria-hidden="true"><span></span><span></span><span></span></span>
      </button>
      <div id="statsDesktopMenuPanel" role="menu" hidden>
        <button id="statsDesktopSettingsButton" type="button" role="menuitem">Settings</button>
      </div>`;
    document.body.appendChild(wrap);

    const button=document.getElementById("statsDesktopMenuButton");
    const panel=document.getElementById("statsDesktopMenuPanel");
    const settings=document.getElementById("statsDesktopSettingsButton");

    function setOpen(open){
      panel.hidden=!open;
      button.setAttribute("aria-expanded",open?"true":"false");
      if(open) settings.focus();
    }

    button.addEventListener("click",event=>{
      event.stopPropagation();
      setOpen(panel.hidden);
    });
    settings.addEventListener("click",()=>window.location.assign("/settings"));
    document.addEventListener("pointerdown",event=>{
      if(!wrap.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown",event=>{
      if(event.key==="Escape"){setOpen(false);button.focus();}
    });
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",mount,{once:true});
  else mount();
})();
