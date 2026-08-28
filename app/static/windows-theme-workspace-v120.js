/* v120 Windows Theme Builder workspace.
   The real TV preview owns the screen while the existing Theme Studio controls
   live in a movable, resizable desktop window. Theme APIs and save behavior are
   intentionally unchanged. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  const isWindows=/windows|win32|win64/i.test(platform);
  if(!isWindows) return;

  const MIN_WIDTH=440;
  const MIN_HEIGHT=520;
  const EDGE=12;
  const DEFAULT_WIDTH=560;
  const DEFAULT_HEIGHT=760;
  const STORAGE_KEY="stats.windows.themeBuilder.geometry.v120";

  const clamp=(value,min,max)=>Math.min(max,Math.max(min,value));

  function injectStyles(){
    if(document.getElementById("windowsThemeWorkspaceStyles")) return;
    const style=document.createElement("style");
    style.id="windowsThemeWorkspaceStyles";
    style.textContent=`
      /* Phone/QR controls are not part of the Windows desktop workflow. */
      #v110QrSection{display:none !important}

      #teamDesignOverlay.windows-theme-workspace{
        padding:0 !important;overflow:hidden !important;background:#000 !important;
        align-items:stretch !important;justify-content:stretch !important
      }

      /* The preview is the canvas, not a card inside the editor. */
      #teamDesignOverlay.windows-theme-workspace .td-preview-sec{
        position:absolute !important;inset:0 !important;z-index:0 !important;
        margin:0 !important;padding:0 !important;border:0 !important;background:#000 !important;
        display:flex !important;align-items:center !important;justify-content:center !important;
        overflow:hidden !important
      }
      #teamDesignOverlay.windows-theme-workspace .td-tvline,
      #teamDesignOverlay.windows-theme-workspace .td-hint{display:none !important}
      #teamDesignOverlay.windows-theme-workspace #tdStage{
        flex:0 0 auto;margin:0 !important;border:0 !important;background:#000 !important;
        max-width:none !important;max-height:none !important;overflow:hidden !important
      }

      /* Desktop tool window. The CSS minimums make it impossible to resize the
         editor below a usable size on a normal Windows display. On an unusually
         small viewport the minimum gracefully falls back to the available area. */
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel{
        position:absolute !important;z-index:20 !important;
        width:min(560px,calc(100vw - 24px));
        height:min(760px,calc(100vh - 24px));
        min-width:min(440px,calc(100vw - 24px)) !important;
        min-height:min(520px,calc(100vh - 24px)) !important;
        max-width:calc(100vw - 24px) !important;
        max-height:calc(100vh - 24px) !important;
        padding:0 !important;margin:0 !important;
        display:flex !important;flex-direction:column !important;
        overflow:hidden !important;resize:both;
        background:rgba(15,15,15,.98) !important;
        border:1px solid #444 !important;border-radius:12px;
        box-shadow:0 20px 60px rgba(0,0,0,.5);
        container-type:inline-size;container-name:themebuilder
      }
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel .td-head{
        position:static !important;top:auto !important;z-index:auto !important;
        flex:0 0 auto;padding:11px 12px !important;
        background:#111 !important;cursor:move;user-select:none;
        border-bottom:1px solid #333
      }
      #teamDesignOverlay.windows-theme-workspace .td-window-actions{
        display:flex;align-items:center;gap:7px;flex:0 0 auto
      }
      #teamDesignOverlay.windows-theme-workspace .td-window-actions .btn{
        min-width:42px;min-height:38px !important;padding:7px 10px
      }
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel .td-body{
        flex:1 1 auto;min-height:0;overflow:auto;
        padding:clamp(10px,2.4cqw,16px) !important;
        overscroll-behavior:contain
      }
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel .td-foot{
        position:static !important;bottom:auto !important;flex:0 0 auto;
        padding:10px 12px !important;background:#0c0c0c !important
      }
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel #tdMain{
        gap:clamp(14px,3.5cqw,22px) !important
      }

      /* Responsive editor contents follow the tool-window width, not the TV
         viewport width. This is what keeps the controls useful while resizing. */
      #teamDesignOverlay.windows-theme-workspace .td-colors{
        grid-template-columns:1fr !important
      }
      #teamDesignOverlay.windows-theme-workspace .td-nums{
        grid-template-columns:repeat(auto-fit,minmax(105px,1fr)) !important
      }
      #teamDesignOverlay.windows-theme-workspace .td-nudge{
        grid-template-columns:repeat(auto-fit,minmax(82px,1fr)) !important
      }
      #teamDesignOverlay.windows-theme-workspace .td-asset-head{
        flex-wrap:wrap
      }
      #teamDesignOverlay.windows-theme-workspace .td-thumb{
        width:clamp(64px,18cqw,88px);height:clamp(48px,12cqw,60px)
      }
      #teamDesignOverlay.windows-theme-workspace input,
      #teamDesignOverlay.windows-theme-workspace select,
      #teamDesignOverlay.windows-theme-workspace button{
        max-width:100%
      }
      #teamDesignOverlay.windows-theme-workspace .td-tiles{
        max-width:100%;scrollbar-width:thin
      }

      @container themebuilder (min-width:650px){
        #teamDesignOverlay.windows-theme-workspace .td-colors{
          grid-template-columns:repeat(2,minmax(0,1fr)) !important
        }
      }
      @container themebuilder (max-width:500px){
        #teamDesignOverlay.windows-theme-workspace .td-who img{
          width:36px;height:36px
        }
        #teamDesignOverlay.windows-theme-workspace .td-who-name{
          font-size:16px
        }
        #teamDesignOverlay.windows-theme-workspace .td-who-sub{
          font-size:11px
        }
        #teamDesignOverlay.windows-theme-workspace .td-foot .btn{
          flex:1 1 100% !important
        }
        #teamDesignOverlay.windows-theme-workspace .td-color{
          gap:8px;padding:8px
        }
        #teamDesignOverlay.windows-theme-workspace .td-color-chip{
          width:38px;height:38px
        }
      }

      /* Minimized mode exposes almost the entire preview but always leaves a
         clear restore target. Restoring returns to the previous usable size. */
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel.td-minimized{
        width:min(340px,calc(100vw - 24px)) !important;
        height:auto !important;min-width:min(260px,calc(100vw - 24px)) !important;
        min-height:0 !important;resize:none !important
      }
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel.td-minimized .td-body,
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel.td-minimized .td-foot{
        display:none !important
      }
      #teamDesignOverlay.windows-theme-workspace .td-desktop-panel.td-minimized .td-head{
        border-bottom:0
      }

      @media(max-width:560px), (max-height:620px){
        #teamDesignOverlay.windows-theme-workspace .td-desktop-panel:not(.td-minimized){
          border-radius:8px
        }
      }
    `;
    document.head.appendChild(style);
  }

  function readGeometry(){
    try{
      const parsed=JSON.parse(sessionStorage.getItem(STORAGE_KEY)||"null");
      if(!parsed || typeof parsed!=="object") return null;
      return parsed;
    }catch(_){return null;}
  }

  function writeGeometry(panel){
    if(panel.classList.contains("td-minimized")) return;
    const rect=panel.getBoundingClientRect();
    if(rect.width<1 || rect.height<1) return;
    try{
      sessionStorage.setItem(STORAGE_KEY,JSON.stringify({
        left:Math.round(rect.left),top:Math.round(rect.top),
        width:Math.round(rect.width),height:Math.round(rect.height)
      }));
    }catch(_){}
  }

  function applyGeometry(panel,geometry){
    const minW=Math.min(MIN_WIDTH,Math.max(1,innerWidth-EDGE*2));
    const minH=Math.min(MIN_HEIGHT,Math.max(1,innerHeight-EDGE*2));
    const maxW=Math.max(minW,innerWidth-EDGE*2);
    const maxH=Math.max(minH,innerHeight-EDGE*2);
    const width=clamp(Number(geometry?.width)||DEFAULT_WIDTH,minW,maxW);
    const height=clamp(Number(geometry?.height)||DEFAULT_HEIGHT,minH,maxH);
    const left=clamp(
      Number.isFinite(Number(geometry?.left))?Number(geometry.left):innerWidth-width-24,
      EDGE,Math.max(EDGE,innerWidth-width-EDGE)
    );
    const top=clamp(
      Number.isFinite(Number(geometry?.top))?Number(geometry.top):24,
      EDGE,Math.max(EDGE,innerHeight-height-EDGE)
    );
    panel.style.width=`${Math.round(width)}px`;
    panel.style.height=`${Math.round(height)}px`;
    panel.style.left=`${Math.round(left)}px`;
    panel.style.top=`${Math.round(top)}px`;
    panel.style.right="auto";
    panel.style.bottom="auto";
  }

  function clampWindow(panel){
    if(panel.classList.contains("td-minimized")){
      const rect=panel.getBoundingClientRect();
      const left=clamp(rect.left,EDGE,Math.max(EDGE,innerWidth-rect.width-EDGE));
      const top=clamp(rect.top,EDGE,Math.max(EDGE,innerHeight-rect.height-EDGE));
      panel.style.left=`${Math.round(left)}px`;
      panel.style.top=`${Math.round(top)}px`;
      return;
    }
    const rect=panel.getBoundingClientRect();
    applyGeometry(panel,{left:rect.left,top:rect.top,width:rect.width,height:rect.height});
    writeGeometry(panel);
  }

  function fitPreview(){
    const overlay=document.getElementById("teamDesignOverlay");
    const stage=document.getElementById("tdStage");
    const sizer=document.getElementById("tdSizer");
    const frame=document.getElementById("tdFrame");
    if(!overlay||!stage||!sizer||!frame) return;

    const frameWidth=parseFloat(frame.style.width)||1920;
    const frameHeight=parseFloat(frame.style.height)||1080;
    if(!(frameWidth>0&&frameHeight>0)) return;

    const availableWidth=overlay.clientWidth||innerWidth;
    const availableHeight=overlay.clientHeight||innerHeight;
    const aspect=frameWidth/frameHeight;
    const width=Math.max(1,Math.min(availableWidth,availableHeight*aspect));
    const scale=width/frameWidth;
    const height=frameHeight*scale;

    stage.style.width=`${Math.round(width)}px`;
    stage.style.height=`${Math.round(height)}px`;
    frame.style.width=`${frameWidth}px`;
    frame.style.height=`${frameHeight}px`;
    frame.style.transform="none";
    sizer.style.transformOrigin="top left";
    sizer.style.transform=`scale(${scale})`;
  }

  function bindDrag(panel,head){
    let dragging=false;
    let pointerId=null;
    let dx=0,dy=0;

    head.addEventListener("pointerdown",event=>{
      if(event.button!==0 || event.target.closest("button,input,select,a")) return;
      const rect=panel.getBoundingClientRect();
      dragging=true;
      pointerId=event.pointerId;
      dx=event.clientX-rect.left;
      dy=event.clientY-rect.top;
      panel.style.left=`${Math.round(rect.left)}px`;
      panel.style.top=`${Math.round(rect.top)}px`;
      panel.style.right="auto";
      panel.style.bottom="auto";
      head.setPointerCapture(pointerId);
      event.preventDefault();
    });

    head.addEventListener("pointermove",event=>{
      if(!dragging || event.pointerId!==pointerId) return;
      const rect=panel.getBoundingClientRect();
      const maxLeft=Math.max(EDGE,innerWidth-rect.width-EDGE);
      const maxTop=Math.max(EDGE,innerHeight-rect.height-EDGE);
      panel.style.left=`${Math.round(clamp(event.clientX-dx,EDGE,maxLeft))}px`;
      panel.style.top=`${Math.round(clamp(event.clientY-dy,EDGE,maxTop))}px`;
    });

    const stop=event=>{
      if(!dragging || event.pointerId!==pointerId) return;
      dragging=false;
      try{head.releasePointerCapture(pointerId);}catch(_){}
      pointerId=null;
      clampWindow(panel);
    };
    head.addEventListener("pointerup",stop);
    head.addEventListener("pointercancel",stop);
  }

  function decorate(){
    const overlay=document.getElementById("teamDesignOverlay");
    const panel=overlay?.querySelector(".panel");
    const preview=overlay?.querySelector(".td-preview-sec");
    const head=overlay?.querySelector(".td-head");
    const close=document.getElementById("tdClose");
    if(!overlay||!panel||!preview||!head||!close || overlay.dataset.windowsWorkspace==="1") return;

    injectStyles();
    overlay.dataset.windowsWorkspace="1";
    overlay.classList.add("windows-theme-workspace");
    panel.classList.add("td-desktop-panel");

    /* Pull the preview out of the scrollable controls. Its existing iframe and
       live refresh behavior remain untouched. */
    overlay.insertBefore(preview,panel);

    const actions=document.createElement("div");
    actions.className="td-window-actions";
    const minimize=document.createElement("button");
    minimize.id="tdMinimize";
    minimize.className="btn";
    minimize.type="button";
    minimize.setAttribute("data-td-always-on","1");
    minimize.setAttribute("aria-label","Minimize Theme Builder");
    minimize.title="Minimize";
    minimize.textContent="—";
    head.appendChild(actions);
    actions.appendChild(minimize);
    actions.appendChild(close);

    let restoreGeometry=readGeometry();
    applyGeometry(panel,restoreGeometry);

    function setMinimized(on){
      if(on===panel.classList.contains("td-minimized")) return;
      if(on){
        const rect=panel.getBoundingClientRect();
        restoreGeometry={left:rect.left,top:rect.top,width:rect.width,height:rect.height};
        writeGeometry(panel);
        panel.classList.add("td-minimized");
        minimize.textContent="□";
        minimize.title="Restore";
        minimize.setAttribute("aria-label","Restore Theme Builder");
        requestAnimationFrame(()=>clampWindow(panel));
      }else{
        panel.classList.remove("td-minimized");
        minimize.textContent="—";
        minimize.title="Minimize";
        minimize.setAttribute("aria-label","Minimize Theme Builder");
        applyGeometry(panel,restoreGeometry||readGeometry());
      }
    }

    minimize.addEventListener("click",event=>{
      event.stopPropagation();
      setMinimized(!panel.classList.contains("td-minimized"));
    });

    /* Closing Theme Builder should never make the next edit session reopen in
       a minimized state. The original close handler still owns the actual close. */
    close.addEventListener("click",()=>setMinimized(false));

    bindDrag(panel,head);

    let resizeTimer=null;
    new ResizeObserver(()=>{
      if(!overlay.classList.contains("open")) return;
      clearTimeout(resizeTimer);
      resizeTimer=setTimeout(()=>{
        clampWindow(panel);
        fitPreview();
      },40);
    }).observe(panel);

    const frame=document.getElementById("tdFrame");
    if(frame) frame.addEventListener("load",()=>requestAnimationFrame(fitPreview));

    new MutationObserver(()=>{
      if(overlay.classList.contains("open")){
        requestAnimationFrame(()=>{
          clampWindow(panel);
          fitPreview();
        });
      }
    }).observe(overlay,{attributes:true,attributeFilter:["class"]});

    window.addEventListener("resize",()=>{
      if(!overlay.classList.contains("open")) return;
      clampWindow(panel);
      fitPreview();
    });

    requestAnimationFrame(fitPreview);
  }

  function boot(){
    injectStyles();
    decorate();
    if(document.getElementById("teamDesignOverlay")) return;
    const observer=new MutationObserver(()=>{
      if(document.getElementById("teamDesignOverlay")){
        observer.disconnect();
        decorate();
      }
    });
    observer.observe(document.documentElement,{childList:true,subtree:true});
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
