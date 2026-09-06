/* Display consumes resolved Screens and shares Widget rendering with editor previews. */
(function(){
  const root=document.getElementById("statsDisplay"),Renderer=window.StatsWidgetRenderer;
  const previewScreen=new URLSearchParams(window.location.search).get("screen_id")||"";
  let lastSignature="",canvasSize={width:1920,height:1080};
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const numeric=(value,fallback)=>Number.isFinite(Number(value))?Number(value):fallback;
  function assets(theme,layout){
    return (layout?.asset_slots||[]).map(slot=>{const url=Renderer.safeUrl(theme?.assets?.[slot.key]);return url?'<img class="display-planned-asset" src="'+esc(url)+'" alt="" style="left:'+numeric(slot.x,0)+'%;top:'+numeric(slot.y,0)+'%;width:'+numeric(slot.width,15)+'%;height:'+numeric(slot.height,15)+'%;object-fit:'+(slot.fit==="cover"?"cover":"contain")+'">':"";}).join("");
  }
  function fitCanvas(){
    const canvas=root.querySelector("[data-display-canvas]");if(!canvas)return;
    const scale=Math.min(root.clientWidth/canvasSize.width,root.clientHeight/canvasSize.height);
    canvas.style.width=canvasSize.width*scale+"px";canvas.style.height=canvasSize.height*scale+"px";
    Renderer.fit(canvas);
  }
  function render(payload){
    if(!payload||payload.mode==="empty"||!payload.screen_id){root.innerHTML='<div class="display-empty">No Screen configured.<br><span>Open Settings → Screens to create one.</span></div>';return;}
    canvasSize={width:numeric(payload.canvas?.width,1920),height:numeric(payload.canvas?.height,1080)};
    const theme=payload.theme||{},background=Renderer.safeUrl(theme.assets?.background),sections=payload.sections||[],themeLayout=theme.layout||{},assetLayout={asset_slots:Array.isArray(payload.assets)?payload.assets:themeLayout.asset_slots};
    const content=themeLayout.content||{x:5,y:12,width:90,height:83};
    const instances=sections.map((section,index)=>{
      const layout=section.layout||{x:numeric(content.x,5),y:numeric(content.y,12)+index*numeric(content.height,83)/sections.length,width:numeric(content.width,90),height:numeric(content.height,83)/sections.length};
      return '<div class="display-widget-instance" style="left:'+numeric(layout.x,0)+'%;top:'+numeric(layout.y,0)+'%;width:'+numeric(layout.width,100)+'%;height:'+numeric(layout.height,100)+'%">'+Renderer.render(section,{theme:section.theme||theme,fit:section.fit||{}})+'</div>';
    }).join("");
    const isLegacy=sections.some(section=>!section.instance_id);
    root.innerHTML='<main class="display-canvas" data-display-canvas data-canvas-width="'+canvasSize.width+'" style="'+Renderer.themeStyle(theme)+'">'+(background?'<img class="display-background" src="'+esc(background)+'" alt="">':"")+assets(theme,assetLayout)+(isLegacy?'<header class="display-legacy-title">'+esc(payload.screen_name||"Stats")+'</header>':"")+(instances||'<div class="display-empty">This Screen has no Widgets.</div>')+'</main>';
    requestAnimationFrame(fitCanvas);
  }
  if("ResizeObserver" in window)new ResizeObserver(fitCanvas).observe(root);else window.addEventListener("resize",fitCanvas);
  async function refresh(){
    try{const url=previewScreen?"/api/display/render?screen_id="+encodeURIComponent(previewScreen):"/api/display/render",response=await fetch(url,{cache:"no-store"}),data=await response.json();if(!response.ok||data.ok===false)throw new Error(data.error||"Could not load Display.");const payload=data.payload||{},signature=JSON.stringify(payload);if(signature!==lastSignature){lastSignature=signature;render(payload);}}
    catch(error){if(!lastSignature)root.innerHTML='<div class="display-empty display-error">'+esc(error.message||"Display unavailable")+'</div>';}
  }
  refresh();setInterval(refresh,3000);
})();
