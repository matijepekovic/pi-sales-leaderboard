/* Theme Builder workspace -- the Windows-only visual editor and the
   desktop sidebar it lives in.

   Consolidated from the settings patch stack. Each section below was its own
   file and they are concatenated in their original load order, so what runs
   when is unchanged -- several of these mount by polling for a node the
   previous one creates. */


/* ------------------------------------------------------------------
   theme-workspace.js
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   theme-visual-editor.js
   ------------------------------------------------------------------ */
/* v122 Windows Theme Builder host for direct canvas editing.
   Keeps Theme Studio as the source of truth for uploads/recolour/reset actions,
   while the iframe handles mouse transforms and fake sample data. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform)) return;

  const SAMPLE_KEY="stats.windows.themeEditor.sample.v122";
  let sample=1;
  try{sample=Math.max(1,Number(sessionStorage.getItem(SAMPLE_KEY)||1)||1);}catch(_){ }
  let frameObserver=null;

  function status(text){
    const el=document.getElementById("tdStatus");if(el)el.textContent=text||"";
  }
  function saveSample(){try{sessionStorage.setItem(SAMPLE_KEY,String(sample));}catch(_){ }}
  function editorUrl(raw){
    if(!raw||raw==="about:blank")return "";
    let url;try{url=new URL(raw,location.href);}catch(_){return "";}
    if(!/^team-\d+$/.test(String(url.searchParams.get("preview")||"")))return "";
    url.searchParams.set("themeEditor","1");
    url.searchParams.set("sample",String(sample));
    return `${url.pathname}${url.search}${url.hash}`;
  }
  function prepareFrame(){
    const frame=document.getElementById("tdFrame");if(!frame)return false;
    frame.style.pointerEvents="auto";
    frame.setAttribute("aria-label","Editable theme preview");
    if(!frameObserver){
      frameObserver=new MutationObserver(()=>{
        const raw=frame.getAttribute("src")||"";
        const next=editorUrl(raw);
        if(next&&next!==raw)frame.setAttribute("src",next);
      });
      frameObserver.observe(frame,{attributes:true,attributeFilter:["src"]});
    }
    const raw=frame.getAttribute("src")||"";
    const next=editorUrl(raw);
    if(next&&next!==raw)frame.setAttribute("src",next);
    return true;
  }
  function addStyles(){
    if(document.getElementById("windowsThemeVisualEditorV122Styles"))return;
    const style=document.createElement("style");style.id="windowsThemeVisualEditorV122Styles";
    style.textContent=`
      #teamDesignOverlay.windows-theme-workspace #tdFrame{pointer-events:auto!important}
      #teamDesignOverlay.windows-theme-workspace #tdStage{cursor:default!important;touch-action:none!important}
      #teamDesignOverlay.windows-theme-workspace .td-sample-button{min-width:92px!important;white-space:nowrap}
    `;
    document.head.appendChild(style);
  }
  function addSampleButton(){
    const actions=document.querySelector("#teamDesignOverlay .td-window-actions");
    if(!actions||document.getElementById("tdNewSample"))return !!actions;
    const button=document.createElement("button");button.id="tdNewSample";button.type="button";
    button.className="btn td-sample-button";button.dataset.tdAlwaysOn="1";
    button.textContent="↻ Sample";button.title="Generate different fake names and stats";
    button.addEventListener("click",()=>{
      sample+=1;saveSample();
      const frame=document.getElementById("tdFrame");
      if(frame){
        const raw=frame.getAttribute("src")||"";
        let url;try{url=new URL(raw,location.href);}catch(_){url=null;}
        if(url){url.searchParams.set("themeEditor","1");url.searchParams.set("sample",String(sample));url.searchParams.set("t",String(Date.now()));frame.src=`${url.pathname}${url.search}`;}
      }
      status("New sample names and stats loaded.");
    });
    actions.insertBefore(button,actions.firstChild);
    return true;
  }

  function clickUpload(key){
    const selector=`#teamDesignOverlay [data-add="${CSS.escape(key)}"]`;
    const button=document.querySelector(selector);
    if(button){button.click();return true;}
    status("That artwork is not available in this editor section.");
    return false;
  }
  function changeColor(key){
    if(key==="background"){
      const input=document.getElementById("tdColor_background");
      if(!input){status("Background colour control is unavailable.");return false;}
      input.addEventListener("change",()=>document.getElementById("tdSave")?.click(),{once:true});
      input.focus();input.click();return true;
    }
    const input=document.querySelector(`.tdTint[data-key="${CSS.escape(key)}"]`);
    const recolor=document.querySelector(`.tdRecolor[data-key="${CSS.escape(key)}"]`);
    if(!input||!recolor||recolor.disabled){status("Upload or choose artwork first, then change its colour.");return false;}
    input.addEventListener("change",()=>recolor.click(),{once:true});
    input.focus();input.click();return true;
  }
  function removeAsset(key){
    const button=document.querySelector(`.tdResetAsset[data-key="${CSS.escape(key)}"]`);
    if(button){button.click();return true;}
    status("That artwork cannot be removed from the canvas here.");
    return false;
  }
  function hostAction(action,key){
    key=String(key||"");
    if(action==="upload")return clickUpload(key);
    if(action==="color")return changeColor(key);
    if(action==="remove")return removeAsset(key);
    if(action==="ready")status("Double-click artwork to edit it. Right-click for asset options.");
    if(action==="selected")status(`${key.replaceAll("_"," ")} selected — drag to move, use handles to resize or rotate.`);
    return true;
  }
  window.StatsThemeEditorHost={action:hostAction};

  window.addEventListener("message",event=>{
    if(event.origin!==location.origin||event.data?.type!=="stats-theme-editor")return;
    hostAction(event.data.action,event.data.key,event.data.teamId);
  });

  function decorate(){addStyles();prepareFrame();addSampleButton();}
  function boot(){
    decorate();
    const observer=new MutationObserver(()=>decorate());
    observer.observe(document.documentElement,{childList:true,subtree:true});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();


/* ------------------------------------------------------------------
   theme-editor-help.js
   ------------------------------------------------------------------ */
/* v123 Windows Theme Builder host-side discoverability polish.
   Wraps the v122 host without replacing its upload, recolor, remove or sample
   actions. The canvas tells this layer what is selected; this layer makes the
   matching inspector controls easy to find. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  const LABELS={
    background:"Background",hero:"Hero / Header Art",row:"Leaderboard Row",
    champion:"Champion Row",medallion:"Champion Medallion",corner_tl:"Top Left Corner",
    corner_tr:"Top Right Corner",corner_bl:"Bottom Left Corner",corner_br:"Bottom Right Corner",
    totals_mark:"Totals Mark"
  };
  let currentKey="";

  function injectStyles(){
    if(document.getElementById("windowsThemeEditorHelpV123Styles"))return;
    const style=document.createElement("style");style.id="windowsThemeEditorHelpV123Styles";
    style.textContent=`
      #teamDesignOverlay.windows-theme-workspace #tdCanvasSelection{
        margin-top:3px;color:#9fdcff;font-size:11px;line-height:1.25;white-space:nowrap;
        overflow:hidden;text-overflow:ellipsis;max-width:240px
      }
      #teamDesignOverlay.windows-theme-workspace .td-help-button{min-width:42px!important;font-weight:900}
      #teamDesignOverlay.windows-theme-workspace .td-canvas-linked{
        border-color:#5dbde9!important;box-shadow:0 0 0 2px rgba(93,189,233,.16)!important;
        transition:border-color .15s ease,box-shadow .15s ease
      }
      #tdThemeHelpV123{position:absolute;inset:0;z-index:1000;display:grid;place-items:center;padding:18px;
        background:rgba(4,4,4,.84);font-family:Arial,sans-serif}
      #tdThemeHelpV123 .td-help-card{width:min(430px,100%);max-height:100%;overflow:auto;padding:20px;
        background:#151515;border:1px solid #4b6574;border-radius:11px;box-shadow:0 20px 55px rgba(0,0,0,.55)}
      #tdThemeHelpV123 h3{margin:0 0 8px;font-size:20px;color:#fff}
      #tdThemeHelpV123 p{margin:0 0 13px;color:#bfc9cf;font-size:13px;line-height:1.45}
      #tdThemeHelpV123 .td-help-row{padding:9px 10px;margin:7px 0;border:1px solid #303b42;border-radius:7px;
        background:#101518;color:#e8f6fd;font-size:13px;line-height:1.35}
      #tdThemeHelpV123 .td-help-actions{display:flex;gap:8px;margin-top:15px;flex-wrap:wrap}
      #tdThemeHelpV123 .td-help-actions .btn{flex:1 1 120px}
    `;
    document.head.appendChild(style);
  }

  function selectionLine(){
    let line=document.getElementById("tdCanvasSelection");if(line)return line;
    const sub=document.querySelector("#teamDesignOverlay .td-who-sub");if(!sub)return null;
    line=document.createElement("div");line.id="tdCanvasSelection";
    line.textContent="Canvas: hover artwork to see what is editable";
    sub.insertAdjacentElement("afterend",line);
    return line;
  }

  function inspectorFor(key){
    const overlay=document.getElementById("teamDesignOverlay");if(!overlay)return null;
    if(key==="background")return overlay.querySelector('[data-asset="background"]')||document.getElementById("tdColor_background")?.closest(".td-color");
    return overlay.querySelector(`[data-asset="${CSS.escape(key)}"]`);
  }
  function focusInspector(key){
    document.querySelectorAll("#teamDesignOverlay .td-canvas-linked").forEach(el=>el.classList.remove("td-canvas-linked"));
    const target=inspectorFor(key);if(!target)return;
    target.classList.add("td-canvas-linked");
    try{target.scrollIntoView({behavior:"smooth",block:"center",inline:"nearest"});}catch(_){target.scrollIntoView();}
  }
  function setSelected(key){
    currentKey=String(key||"");
    const line=selectionLine();if(line)line.textContent=currentKey?`Editing: ${LABELS[currentKey]||currentKey}`:"Canvas: no artwork selected";
    if(currentKey)focusInspector(currentKey);
  }

  function helpOverlay(){
    let help=document.getElementById("tdThemeHelpV123");if(help)return help;
    const panel=document.querySelector("#teamDesignOverlay .td-desktop-panel");if(!panel)return null;
    help=document.createElement("div");help.id="tdThemeHelpV123";help.style.display="none";
    help.innerHTML=`<div class="td-help-card" role="dialog" aria-modal="true" aria-label="Theme Builder help">
      <h3>Theme Builder mouse controls</h3>
      <p>Edit the artwork directly on the preview. Sales names and numbers stay controlled by Stats.</p>
      <div class="td-help-row"><strong>Hover</strong> — editable artwork gets a subtle outline.</div>
      <div class="td-help-row"><strong>Double-click</strong> — select artwork and show its transform box.</div>
      <div class="td-help-row"><strong>Drag</strong> — move the selected artwork.</div>
      <div class="td-help-row"><strong>Handles</strong> — resize. The round ↻ handle rotates.</div>
      <div class="td-help-row"><strong>Right-click</strong> — replace, recolor, change opacity, reset or remove.</div>
      <div class="td-help-actions"><button class="btn primary" type="button" data-help-close="1">Done</button><button class="btn" type="button" data-help-show-canvas="1">Show canvas guide</button></div>
    </div>`;
    panel.appendChild(help);
    help.querySelector('[data-help-close="1"]').addEventListener("click",()=>{help.style.display="none";});
    help.querySelector('[data-help-show-canvas="1"]').addEventListener("click",()=>{
      help.style.display="none";
      const frame=document.getElementById("tdFrame");
      try{frame?.contentWindow?.postMessage({type:"stats-theme-editor-help"},location.origin);}catch(_){ }
    });
    help.addEventListener("pointerdown",e=>{if(e.target===help)help.style.display="none";});
    return help;
  }

  function addHelpButton(){
    const actions=document.querySelector("#teamDesignOverlay .td-window-actions");if(!actions)return false;
    if(document.getElementById("tdThemeHelpButton"))return true;
    const button=document.createElement("button");button.id="tdThemeHelpButton";button.type="button";
    button.className="btn td-help-button";button.dataset.tdAlwaysOn="1";button.textContent="?";
    button.title="Theme Builder help";button.setAttribute("aria-label","Theme Builder help");
    button.addEventListener("click",()=>{const help=helpOverlay();if(help)help.style.display="grid";});
    const minimize=document.getElementById("tdMinimize");
    actions.insertBefore(button,minimize||actions.firstChild);
    return true;
  }

  function wrapHost(){
    const host=window.StatsThemeEditorHost;if(!host?.action||host.action.__v123Wrapped)return false;
    const previous=host.action;
    const wrapped=function(action,key,teamId){
      const result=previous(action,key,teamId);
      if(action==="selected")setSelected(key);
      if(action==="ready"&&!currentKey){const line=selectionLine();if(line)line.textContent="Canvas: hover artwork to see what is editable";}
      return result;
    };
    wrapped.__v123Wrapped=true;
    host.action=wrapped;
    return true;
  }

  function decorate(){injectStyles();selectionLine();addHelpButton();helpOverlay();wrapHost();}
  function boot(){
    decorate();
    const observer=new MutationObserver(()=>decorate());
    observer.observe(document.documentElement,{childList:true,subtree:true});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();


/* ------------------------------------------------------------------
   theme-stability.js
   ------------------------------------------------------------------ */
/* v126 Windows Theme Builder stability/policy hints.
   Preview data selection happens inside the iframe. This host-side layer keeps
   the desktop controls simple and avoids exposing the old fake-sample cycler. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform)) return;

  function addStyles(){
    if(document.getElementById("windowsThemeStabilityV126Styles"))return;
    const style=document.createElement("style");
    style.id="windowsThemeStabilityV126Styles";
    style.textContent=`
      #teamDesignOverlay #tdNewSample{display:none!important}
      #teamDesignOverlay #tdPreviewPolicyV126{
        color:#9a9a9a;font-size:10px;line-height:1.25;margin-top:3px;
        max-width:280px;white-space:normal
      }
    `;
    document.head.appendChild(style);
  }

  function installNote(){
    const sub=document.querySelector("#teamDesignOverlay .td-who-sub");
    if(!sub)return false;
    if(document.getElementById("tdPreviewPolicyV126"))return true;
    const note=document.createElement("div");
    note.id="tdPreviewPolicyV126";
    note.textContent="Real team stats are used when members exist. Empty teams use a mock design preview.";
    sub.insertAdjacentElement("afterend",note);
    return true;
  }

  function boot(){
    addStyles();
    let tries=0;
    (function attempt(){
      if(installNote())return;
      if(++tries<120)setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();


/* ------------------------------------------------------------------
   theme-color-editor.js
   ------------------------------------------------------------------ */
/* v127 Windows Theme Builder color/apply reliability.

   Chromium's native color dialog is awkward in kiosk/fullscreen mode and can
   temporarily blank the visual editor. Keep the existing theme inputs and API
   as the source of truth, but edit them through an in-app H/S/L + hex picker.
   The picker paints the real iframe immediately, persists without reloading it,
   and makes any actual design edit activate the team's theme on the TV. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  const META={
    primary:{label:"Frame & Borders",help:"Outer frame, dividers and border accents."},
    primary_bright:{label:"Main Accent",help:"Team name, ranks, totals and highlighted numbers."},
    primary_dark:{label:"Shadow / Depth",help:"Dark depth behind the frame and champion row."},
    secondary:{label:"Background Glow",help:"Secondary glow used in the theme atmosphere."},
    background:{label:"Canvas Background",help:"Main color behind the theme artwork."},
    panel:{label:"Rows & Panels",help:"Leaderboard rows, column header and totals panel."},
    text:{label:"Main Text",help:"Normal stat text and team-lead text."},
    muted:{label:"Labels / Muted Text",help:"Column labels and secondary information."},
    champion_text:{label:"Champion Highlight",help:"Champion name and highlighted champion value."}
  };
  const BT_VAR={
    primary:"--bt-primary",primary_bright:"--bt-bright",primary_dark:"--bt-dark",
    secondary:"--bt-secondary",background:"--bt-bg",panel:"--bt-panel",
    text:"--bt-text",muted:"--bt-muted",champion_text:"--bt-champ"
  };
  const LEGACY_VAR={
    primary:"--theme-primary",primary_bright:"--theme-primary-bright",primary_dark:"--theme-primary-dark",
    secondary:"--theme-secondary",background:"--theme-bg",panel:"--theme-panel",
    text:"--theme-text",muted:"--theme-muted",champion_text:"--theme-champion-text"
  };

  let picker=null;
  let mode=null;
  let decorateTimer=0;
  let enableTimer=0;
  let activePromise=null;

  const clamp=(v,a,b)=>Math.min(b,Math.max(a,Number(v)||0));
  const validHex=value=>/^#[0-9a-f]{6}$/i.test(String(value||""));
  const status=text=>{const el=document.getElementById("tdStatus");if(el)el.textContent=text||"";};
  const overlay=()=>document.getElementById("teamDesignOverlay");

  function teamId(){
    const frame=document.getElementById("tdFrame");
    try{
      const url=new URL(frame?.getAttribute("src")||"",location.href);
      const match=/^team-(\d+)$/.exec(String(url.searchParams.get("preview")||""));
      if(match)return Number(match[1]);
    }catch(_){ }
    const name=String(document.getElementById("tdWhoName")?.textContent||"").trim().toLowerCase();
    const team=(window.teamDefs||[]).find(t=>String(t.name||"").trim().toLowerCase()===name);
    return Number(team?.team_id||0)||null;
  }

  async function putTheme(payload){
    const id=teamId();
    if(!id)throw new Error("Could not determine which team is being edited.");
    const response=await fetch(`/api/themes/team-${id}`,{
      method:"PUT",cache:"no-store",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload||{})
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false)throw new Error(data.error||"Could not save the theme.");
    return data;
  }

  function markActive(){
    const enabled=document.getElementById("tdEnabled");
    if(enabled)enabled.checked=true;
  }
  async function ensureActive(){
    markActive();
    if(activePromise)return activePromise;
    activePromise=putTheme({enabled:true}).catch(error=>{status(error.message);}).finally(()=>{activePromise=null;});
    return activePromise;
  }
  function ensureActiveSoon(){
    markActive();clearTimeout(enableTimer);
    enableTimer=setTimeout(()=>ensureActive(),260);
  }

  function hexToHsl(hex){
    const r=parseInt(hex.slice(1,3),16)/255,g=parseInt(hex.slice(3,5),16)/255,b=parseInt(hex.slice(5,7),16)/255;
    const max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;
    let h=0;
    if(d){
      if(max===r)h=((g-b)/d)%6;
      else if(max===g)h=(b-r)/d+2;
      else h=(r-g)/d+4;
      h=Math.round(h*60);if(h<0)h+=360;
    }
    const l=(max+min)/2;
    const s=d===0?0:d/(1-Math.abs(2*l-1));
    return [h,Math.round(s*100),Math.round(l*100)];
  }
  function hslToHex(h,s,l){
    h=((Number(h)%360)+360)%360;s=clamp(s,0,100)/100;l=clamp(l,0,100)/100;
    const c=(1-Math.abs(2*l-1))*s,x=c*(1-Math.abs((h/60)%2-1)),m=l-c/2;
    let r=0,g=0,b=0;
    if(h<60){r=c;g=x;}else if(h<120){r=x;g=c;}else if(h<180){g=c;b=x;}
    else if(h<240){g=x;b=c;}else if(h<300){r=x;b=c;}else{r=c;b=x;}
    const one=v=>Math.round((v+m)*255).toString(16).padStart(2,"0");
    return `#${one(r)}${one(g)}${one(b)}`;
  }

  function frameDoc(){
    try{return document.getElementById("tdFrame")?.contentDocument||null;}catch(_){return null;}
  }
  function paintThemeColor(key,value){
    const doc=frameDoc();if(!doc)return;
    const root=doc.getElementById("themedTeamBroadcast");
    if(root&&BT_VAR[key])root.style.setProperty(BT_VAR[key],value);
    if(root&&key==="background"){
      const bg=root.querySelector(".bt-bg");if(bg)bg.style.backgroundColor=value;
    }
    if(LEGACY_VAR[key])doc.documentElement.style.setProperty(LEGACY_VAR[key],value);
  }
  function paintStripe(value){
    const doc=frameDoc();if(!doc)return;
    [doc.getElementById("themedTeamBroadcast"),doc.getElementById("v55OfficeBroadcast"),...doc.querySelectorAll(".v69-team-card")]
      .filter(Boolean).forEach(root=>root.style.setProperty("--v69-stripe-color",value));
  }

  function updateOriginalInput(value){
    if(!mode||!validHex(value))return;
    value=value.toLowerCase();
    mode.input.value=value;
    if(mode.kind==="theme"){
      const chip=document.querySelector(`[data-chip="${CSS.escape(mode.key)}"]`);
      const label=document.querySelector(`[data-value="${CSS.escape(mode.key)}"]`);
      if(chip)chip.style.background=value;if(label)label.textContent=value;
      paintThemeColor(mode.key,value);
    }else if(mode.kind==="stripe"){
      const chip=document.getElementById("tdStripeChip"),label=document.getElementById("tdStripeValue");
      if(chip)chip.style.background=value;if(label)label.textContent=value;
      paintStripe(value);
    }else if(mode.kind==="tint"){
      const chip=document.querySelector(`[data-tint-chip="${CSS.escape(mode.key)}"]`);
      if(chip)chip.style.background=value;
    }
  }

  function ensureStyles(){
    if(document.getElementById("windowsThemeColorV127Styles"))return;
    const style=document.createElement("style");style.id="windowsThemeColorV127Styles";
    style.textContent=`
      #teamDesignOverlay .td-color-help-v127{margin-top:3px;color:#8e9ba3;font-size:10px;line-height:1.25}
      #teamDesignOverlay #tdColorPickerV127{position:absolute;inset:0;z-index:2400;display:none;place-items:center;
        padding:16px;background:rgba(5,7,9,.80)}
      #teamDesignOverlay #tdColorPickerV127.open{display:grid}
      #tdColorPickerV127 .tcp-card{width:min(390px,100%);padding:18px;border:1px solid #4c6573;border-radius:11px;
        background:#11181d;box-shadow:0 22px 60px rgba(0,0,0,.58)}
      #tdColorPickerV127 h3{margin:0 0 4px;color:#fff;font-size:19px}
      #tdColorPickerV127 .tcp-help{color:#9eabb2;font-size:11px;line-height:1.35;margin-bottom:13px}
      #tdColorPickerV127 .tcp-top{display:grid;grid-template-columns:64px minmax(0,1fr);gap:12px;align-items:center;margin-bottom:13px}
      #tdColorPickerV127 .tcp-swatch{width:64px;height:64px;border-radius:10px;border:1px solid #73828a;box-shadow:inset 0 0 0 1px rgba(0,0,0,.5)}
      #tdColorPickerV127 .tcp-hex{width:100%;min-height:42px;padding:8px 10px;border:1px solid #43515a;border-radius:7px;
        background:#080d10;color:#fff;font:700 14px Consolas,monospace;text-transform:uppercase}
      #tdColorPickerV127 .tcp-line{display:grid;grid-template-columns:72px minmax(0,1fr) 42px;gap:8px;align-items:center;margin:10px 0}
      #tdColorPickerV127 .tcp-line label{font-size:12px;color:#d2dce1}
      #tdColorPickerV127 .tcp-line output{text-align:right;color:#aebbc2;font-size:11px;font-variant-numeric:tabular-nums}
      #tdColorPickerV127 input[type=range]{width:100%;accent-color:#56bdea}
      #tdColorPickerV127 .tcp-actions{display:flex;gap:9px;margin-top:16px}
      #tdColorPickerV127 .tcp-actions .btn{flex:1 1 0}
      #teamDesignOverlay .td-color-native-disabled-v127{display:none!important}
    `;
    document.head.appendChild(style);
  }

  function ensurePicker(){
    if(picker)return picker;
    const panel=document.querySelector("#teamDesignOverlay .td-desktop-panel")||document.querySelector("#teamDesignOverlay .panel");
    if(!panel)return null;
    picker=document.createElement("div");picker.id="tdColorPickerV127";
    picker.innerHTML=`<div class="tcp-card" role="dialog" aria-modal="true" aria-label="Theme color picker">
      <h3 id="tcpTitle">Color</h3><div id="tcpHelp" class="tcp-help"></div>
      <div class="tcp-top"><div id="tcpSwatch" class="tcp-swatch"></div><input id="tcpHex" class="tcp-hex" type="text" maxlength="7" spellcheck="false" aria-label="Hex color"></div>
      <div class="tcp-line"><label for="tcpHue">Hue</label><input id="tcpHue" type="range" min="0" max="359" step="1"><output id="tcpHueOut"></output></div>
      <div class="tcp-line"><label for="tcpSat">Saturation</label><input id="tcpSat" type="range" min="0" max="100" step="1"><output id="tcpSatOut"></output></div>
      <div class="tcp-line"><label for="tcpLight">Lightness</label><input id="tcpLight" type="range" min="0" max="100" step="1"><output id="tcpLightOut"></output></div>
      <div class="tcp-actions"><button class="btn" type="button" data-tcp-cancel="1">Cancel</button><button class="btn primary" type="button" data-tcp-apply="1">Apply</button></div>
    </div>`;
    panel.appendChild(picker);
    const hue=picker.querySelector("#tcpHue"),sat=picker.querySelector("#tcpSat"),light=picker.querySelector("#tcpLight"),hex=picker.querySelector("#tcpHex");
    const fromSliders=()=>setPickerColor(hslToHex(hue.value,sat.value,light.value),false);
    [hue,sat,light].forEach(input=>input.addEventListener("input",fromSliders));
    hex.addEventListener("input",()=>{const v=String(hex.value||"").trim();if(validHex(v))setPickerColor(v,true);});
    picker.querySelector('[data-tcp-cancel="1"]').addEventListener("click",cancelPicker);
    picker.querySelector('[data-tcp-apply="1"]').addEventListener("click",applyPicker);
    picker.addEventListener("pointerdown",e=>{if(e.target===picker)cancelPicker();});
    return picker;
  }

  function setPickerColor(value,fromHex){
    if(!picker||!validHex(value))return;
    value=value.toLowerCase();
    const [h,s,l]=hexToHsl(value);
    if(!fromHex){picker.querySelector("#tcpHex").value=value.toUpperCase();}
    else{
      picker.querySelector("#tcpHue").value=String(h);picker.querySelector("#tcpSat").value=String(s);picker.querySelector("#tcpLight").value=String(l);
    }
    if(!fromHex){
      picker.querySelector("#tcpHue").value=String(h);picker.querySelector("#tcpSat").value=String(s);picker.querySelector("#tcpLight").value=String(l);
    }
    picker.querySelector("#tcpSwatch").style.background=value;
    picker.querySelector("#tcpHueOut").textContent=`${h}°`;
    picker.querySelector("#tcpSatOut").textContent=`${s}%`;
    picker.querySelector("#tcpLightOut").textContent=`${l}%`;
    updateOriginalInput(value);
  }

  function openPicker(nextMode){
    const box=ensurePicker();if(!box||!nextMode?.input)return false;
    const value=validHex(nextMode.input.value)?String(nextMode.input.value).toLowerCase():"#d8b34a";
    mode={...nextMode,original:value};
    box.querySelector("#tcpTitle").textContent=nextMode.label||"Color";
    box.querySelector("#tcpHelp").textContent=nextMode.help||"Adjust the color and watch the TV preview update live.";
    box.classList.add("open");
    setPickerColor(value,true);
    setTimeout(()=>box.querySelector("#tcpHex")?.focus(),0);
    return true;
  }
  function closePicker(){if(picker)picker.classList.remove("open");mode=null;}
  function cancelPicker(){
    if(mode)updateOriginalInput(mode.original);
    closePicker();
  }

  function palette(){
    const colors={};
    document.querySelectorAll("#teamDesignOverlay .tdColorInput").forEach(input=>{
      if(input.dataset.colorKey&&validHex(input.value))colors[input.dataset.colorKey]=String(input.value).toLowerCase();
    });
    return colors;
  }
  async function applyPicker(){
    if(!mode)return;
    const current=String(mode.input.value||"").toLowerCase();
    if(!validHex(current)){status("Enter a six-digit hex color such as #D8B34A.");return;}
    const applying={...mode};
    const applyButton=picker?.querySelector('[data-tcp-apply="1"]');if(applyButton)applyButton.disabled=true;
    try{
      if(applying.kind==="theme"){
        markActive();
        await putTheme({base:document.getElementById("tdPreset")?.value||"starter",enabled:true,colors:palette()});
        status(`${applying.label} saved and applied.`);
      }else if(applying.kind==="stripe"){
        markActive();
        const strength=clamp(document.getElementById("tdStripeStrength")?.value,0,100);
        await putTheme({enabled:true,row_stripe:{color:current,strength}});
        status("Alternating row tint saved and applied.");
      }else if(applying.kind==="tint"){
        await ensureActive();
        const recolor=document.querySelector(`.tdRecolor[data-key="${CSS.escape(applying.key)}"]`);
        if(!recolor||recolor.disabled)throw new Error("Choose artwork first, then recolor it.");
        closePicker();
        recolor.click();
        return;
      }
      closePicker();
    }catch(error){status(error.message||"Could not save that color.");}
    finally{if(applyButton)applyButton.disabled=false;}
  }

  function openThemeColor(key){
    const input=document.getElementById(`tdColor_${key}`),meta=META[key]||{label:key,help:"Theme color."};
    if(!input){status("That color control is unavailable.");return false;}
    return openPicker({kind:"theme",key,input,label:meta.label,help:meta.help});
  }
  function openStripe(){
    const input=document.getElementById("tdStripeColor");if(!input)return false;
    return openPicker({kind:"stripe",key:"row_stripe",input,label:"Alternating Row Tint",help:"Color laid over every other leaderboard row. Tint Strength controls how much of it shows."});
  }
  function openTint(key){
    const input=document.querySelector(`.tdTint[data-key="${CSS.escape(key)}"]`);
    const recolor=document.querySelector(`.tdRecolor[data-key="${CSS.escape(key)}"]`);
    if(!input||!recolor||recolor.disabled){status("Choose artwork first, then recolor it.");return false;}
    const asset=document.querySelector(`[data-asset="${CSS.escape(key)}"] .td-asset-name`)?.textContent||key.replaceAll("_"," ");
    return openPicker({kind:"tint",key,input,label:`Recolor ${asset}`,help:"This recolors the artwork itself. Position, size, rotation and opacity are left unchanged."});
  }

  function decorateColors(){
    ensureStyles();
    const colors=document.getElementById("tdColors");
    if(colors){
      const section=colors.closest(".td-sec");
      if(section&&!section.querySelector(".td-colors-intro-v127")){
        const intro=document.createElement("div");intro.className="small td-colors-intro-v127";
        intro.textContent="Every color below is used by the TV design. The name tells you exactly what it controls.";
        section.querySelector("h3")?.insertAdjacentElement("afterend",intro);
      }
      colors.querySelectorAll(".td-color[data-color]").forEach(row=>{
        const key=String(row.dataset.color||""),meta=META[key];if(!meta)return;
        const label=row.querySelector(".td-color-label");if(label&&label.textContent!==meta.label)label.textContent=meta.label;
        const text=row.querySelector(".td-color-text");
        let help=row.querySelector(".td-color-help-v127");
        if(text&&!help){help=document.createElement("div");help.className="td-color-help-v127";text.appendChild(help);}
        if(help&&help.textContent!==meta.help)help.textContent=meta.help;
      });
    }
    const save=document.getElementById("tdSave");if(save&&save.textContent!=="Save & Apply Design")save.textContent="Save & Apply Design";
    const enabled=document.getElementById("tdEnabled");
    const label=enabled?.closest("label")?.querySelector("span");if(label&&label.textContent!=="Theme is active on the TV")label.textContent="Theme is active on the TV";
    ensurePicker();wrapHost();
  }
  function scheduleDecorate(){
    if(decorateTimer)return;
    decorateTimer=requestAnimationFrame(()=>{decorateTimer=0;decorateColors();});
  }

  function interceptClick(event){
    if(!overlay()?.contains(event.target))return;
    const themeButton=event.target.closest?.("[data-open-color]");
    if(themeButton){
      event.preventDefault();event.stopImmediatePropagation();openThemeColor(String(themeButton.dataset.openColor||""));return;
    }
    if(event.target.closest?.("#tdStripeOpen")){
      event.preventDefault();event.stopImmediatePropagation();openStripe();return;
    }
    const tintChip=event.target.closest?.(".tdTintChip");
    if(tintChip){
      event.preventDefault();event.stopImmediatePropagation();openTint(String(tintChip.dataset.tintChip||""));return;
    }
    if(event.target.closest?.("#tdSave"))markActive();
    if(event.target.closest?.(".td-tile:not(.td-tile-add),.tdRecolor,.tdResetAsset,.tdSnap,.tdUnsnap,#tdLogoReset,#tdSheetReset"))ensureActiveSoon();
  }
  function interceptValueEdit(event){
    if(!overlay()?.contains(event.target)||event.target.id==="tdEnabled")return;
    if(event.target.matches?.("#tdHeroScale,#tdStripeStrength,.tdNum"))ensureActiveSoon();
  }

  function wrapHost(){
    const host=window.StatsThemeEditorHost;if(!host?.action||host.action.__v127Wrapped)return false;
    const previous=host.action;
    const wrapped=function(action,key,team){
      if(action==="color")return key==="background"?openThemeColor("background"):openTint(String(key||""));
      if(action==="upload"||action==="remove")ensureActiveSoon();
      return previous(action,key,team);
    };
    wrapped.__v127Wrapped=true;host.action=wrapped;return true;
  }

  function boot(){
    ensureStyles();decorateColors();
    document.addEventListener("click",interceptClick,true);
    document.addEventListener("change",interceptValueEdit,true);
    document.addEventListener("input",interceptValueEdit,true);
    document.addEventListener("keydown",event=>{if(event.key==="Escape"&&picker?.classList.contains("open"))cancelPicker();});
    const colors=document.getElementById("tdColors");
    if(colors)new MutationObserver(scheduleDecorate).observe(colors,{childList:true,subtree:true});
    let tries=0;(function retryHost(){if(wrapHost())return;if(++tries<120)setTimeout(retryHost,50);})();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();


/* ------------------------------------------------------------------
   windows-sidebar.js
   ------------------------------------------------------------------ */
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
