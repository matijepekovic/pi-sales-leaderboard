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
