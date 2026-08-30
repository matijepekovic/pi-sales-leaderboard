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
