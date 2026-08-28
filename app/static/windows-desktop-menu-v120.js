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
