/* v61 Theme Studio direct corner editor.
   Corner ornaments are adjusted directly in the live preview: drag the art
   toward its screen edge to crop it, drag the on-preview handle to resize it,
   and double-click the ornament to reset. Saved theme data stays compatible
   with the v60 TV runtime. */
(function(){
  const CORNERS={
    corner_tl:{pos:"tl",label:"Top Left",sx:-1,sy:-1,innerX:1,innerY:1},
    corner_tr:{pos:"tr",label:"Top Right",sx:1,sy:-1,innerX:-1,innerY:1},
    corner_bl:{pos:"bl",label:"Bottom Left",sx:-1,sy:1,innerX:1,innerY:-1},
    corner_br:{pos:"br",label:"Bottom Right",sx:1,sy:1,innerX:-1,innerY:-1}
  };
  const DEFAULTS={size:100,crop_x:0,crop_y:0};
  const MIN_SIZE=50;
  const MAX_SIZE=250;
  const MAX_CROP=60;
  let state=null;
  let syncing=false;
  let syncTimer=null;

  function byId(id){return document.getElementById(id);}
  function scope(){return String(byId("themeScope")?.value||"").trim();}
  function teamId(){const s=scope();return s.startsWith("team-")?s.slice(5):"";}
  function theme(){const id=teamId();return id&&state?.themes?.teams?.[id]||null;}
  function num(v,d){v=Number(v);return Number.isFinite(v)?v:d;}
  function clamp(v,min,max){return Math.min(max,Math.max(min,v));}
  function settingsFor(key){
    const saved=theme()?.corner_settings?.[key]||{};
    return {
      size:clamp(num(saved.size,100),MIN_SIZE,MAX_SIZE),
      crop_x:clamp(num(saved.crop_x,0),0,MAX_CROP),
      crop_y:clamp(num(saved.crop_y,0),0,MAX_CROP)
    };
  }

  function injectStyles(){
    if(byId("v61DirectCornerStyles"))return;
    const s=document.createElement("style");
    s.id="v61DirectCornerStyles";
    s.textContent=`
      .v61-corner-help{margin:6px 0 9px;padding:8px 10px;border:1px solid #303030;background:#0b0b0b;color:#aaa;font-size:12px;line-height:1.35}
      .theme-preview-corner.v61-direct-corner{pointer-events:auto!important;cursor:grab;touch-action:none;user-select:none;-webkit-user-drag:none;outline:0 solid transparent;outline-offset:2px}
      .theme-preview-corner.v61-direct-corner:hover{outline-width:1px;outline-style:dashed;outline-color:var(--pb,#e6c760)}
      .theme-preview-corner.v61-direct-corner.v61-corner-active{cursor:grabbing;outline:1px dashed var(--pb,#e6c760)}
      .v61-corner-resize{position:absolute;z-index:12;width:15px;height:15px;margin:-7.5px 0 0 -7.5px;border-radius:50%;border:2px solid #080808;background:var(--pb,#e6c760);box-shadow:0 0 0 1px rgba(255,255,255,.75),0 2px 7px rgba(0,0,0,.8);touch-action:none;user-select:none}
      .v61-corner-resize[data-pos="tl"],.v61-corner-resize[data-pos="br"]{cursor:nwse-resize}
      .v61-corner-resize[data-pos="tr"],.v61-corner-resize[data-pos="bl"]{cursor:nesw-resize}
      .v61-corner-resize.v61-corner-active{box-shadow:0 0 0 2px var(--pb,#e6c760),0 2px 9px rgba(0,0,0,.9)}
    `;
    document.head.appendChild(s);
  }

  function transformFor(key,cfg){
    const info=CORNERS[key];
    return info?`translate(${info.sx*cfg.crop_x}%,${info.sy*cfg.crop_y}%) scale(${cfg.size/100})`:"";
  }

  function originFor(key){
    const p=CORNERS[key]?.pos||"tl";
    return `${p.endsWith("r")?"right":"left"} ${p.startsWith("b")?"bottom":"top"}`;
  }

  function imageFor(key){
    const p=CORNERS[key]?.pos;
    return p?byId("themePreview")?.querySelector(`.theme-preview-corner.${p}`):null;
  }

  function handleFor(key){
    return byId("themePreview")?.querySelector(`.v61-corner-resize[data-corner-key="${key}"]`)||null;
  }

  function positionHandle(key){
    const preview=byId("themePreview");
    const img=imageFor(key);
    const handle=handleFor(key);
    const info=CORNERS[key];
    if(!preview||!img||!handle||!info)return;
    const pr=preview.getBoundingClientRect();
    const r=img.getBoundingClientRect();
    const x=info.innerX>0?r.right:r.left;
    const y=info.innerY>0?r.bottom:r.top;
    handle.style.left=`${x-pr.left}px`;
    handle.style.top=`${y-pr.top}px`;
  }

  function applyPreview(key,cfg){
    const img=imageFor(key);
    if(!img)return;
    img.style.transformOrigin=originFor(key);
    img.style.transform=transformFor(key,cfg);
    img.style.willChange="transform";
    positionHandle(key);
    requestAnimationFrame(()=>positionHandle(key));
  }

  async function saveCorner(key,cfg){
    const s=scope();
    if(!s)return;
    const status=byId("themeStatus");
    if(status)status.textContent=`Saving ${CORNERS[key].label} corner…`;
    try{
      const r=await fetch(`/api/themes/${encodeURIComponent(s)}`,{
        method:"PUT",cache:"no-store",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({corner_settings:{[key]:cfg}})
      });
      const d=await r.json();
      if(!r.ok||d.ok===false)throw new Error(d.error||`Request failed (${r.status})`);
      const id=teamId();
      if(state?.themes?.teams?.[id]&&d.theme)state.themes.teams[id]=d.theme;
      if(status)status.textContent="Corner saved. The TV will pick it up automatically.";
    }catch(e){
      if(status)status.textContent=e.message;
      scheduleSync(40);
    }
  }

  function endPointerGesture(cleanup,img,handle){
    cleanup();
    img?.classList.remove("v61-corner-active");
    handle?.classList.remove("v61-corner-active");
  }

  function beginMove(ev,key){
    if(ev.pointerType==="mouse"&&ev.button!==0)return;
    const img=imageFor(key);
    if(!img)return;
    ev.preventDefault();
    ev.stopPropagation();
    const start=settingsFor(key);
    const startX=ev.clientX;
    const startY=ev.clientY;
    const baseW=Math.max(1,img.offsetWidth||55);
    const baseH=Math.max(1,img.offsetHeight||55);
    const info=CORNERS[key];
    let next={...start};
    let finished=false;
    img.classList.add("v61-corner-active");

    const move=e=>{
      const dx=e.clientX-startX;
      const dy=e.clientY-startY;
      next={
        ...start,
        crop_x:clamp(start.crop_x+(info.sx*dx/baseW*100),0,MAX_CROP),
        crop_y:clamp(start.crop_y+(info.sy*dy/baseH*100),0,MAX_CROP)
      };
      applyPreview(key,next);
    };
    const cleanup=()=>{
      window.removeEventListener("pointermove",move,true);
      window.removeEventListener("pointerup",up,true);
      window.removeEventListener("pointercancel",cancel,true);
    };
    const up=e=>{
      if(finished)return;
      finished=true;
      e.preventDefault();
      endPointerGesture(cleanup,img,null);
      saveCorner(key,next);
    };
    const cancel=()=>{
      if(finished)return;
      finished=true;
      endPointerGesture(cleanup,img,null);
      applyPreview(key,start);
    };
    window.addEventListener("pointermove",move,true);
    window.addEventListener("pointerup",up,true);
    window.addEventListener("pointercancel",cancel,true);
  }

  function beginResize(ev,key){
    if(ev.pointerType==="mouse"&&ev.button!==0)return;
    const img=imageFor(key);
    const handle=handleFor(key);
    const info=CORNERS[key];
    if(!img||!handle||!info)return;
    ev.preventDefault();
    ev.stopPropagation();
    const start=settingsFor(key);
    const startX=ev.clientX;
    const startY=ev.clientY;
    const base=Math.max(1,(img.offsetWidth+img.offsetHeight)/2||55);
    let next={...start};
    let finished=false;
    img.classList.add("v61-corner-active");
    handle.classList.add("v61-corner-active");

    const move=e=>{
      const dx=e.clientX-startX;
      const dy=e.clientY-startY;
      const projected=((dx*info.innerX)+(dy*info.innerY))/2;
      next={...start,size:clamp(start.size+(projected/base*100),MIN_SIZE,MAX_SIZE)};
      applyPreview(key,next);
    };
    const cleanup=()=>{
      window.removeEventListener("pointermove",move,true);
      window.removeEventListener("pointerup",up,true);
      window.removeEventListener("pointercancel",cancel,true);
    };
    const up=e=>{
      if(finished)return;
      finished=true;
      e.preventDefault();
      endPointerGesture(cleanup,img,handle);
      saveCorner(key,next);
    };
    const cancel=()=>{
      if(finished)return;
      finished=true;
      endPointerGesture(cleanup,img,handle);
      applyPreview(key,start);
    };
    window.addEventListener("pointermove",move,true);
    window.addEventListener("pointerup",up,true);
    window.addEventListener("pointercancel",cancel,true);
  }

  function resetCorner(ev,key){
    ev.preventDefault();
    ev.stopPropagation();
    const next={...DEFAULTS};
    applyPreview(key,next);
    saveCorner(key,next);
  }

  function ensureHelp(){
    const preview=byId("themePreview");
    if(!preview||byId("v61CornerHelp"))return;
    const note=document.createElement("div");
    note.id="v61CornerHelp";
    note.className="v61-corner-help";
    note.innerHTML="<strong>Edit corners on the preview:</strong> drag an ornament toward its screen edge to crop it, drag the dot to resize, and double-click the ornament to reset.";
    preview.insertAdjacentElement("beforebegin",note);
  }

  function ensureHandle(key,img){
    const preview=byId("themePreview");
    if(!preview||!img)return;
    let handle=handleFor(key);
    if(!handle){
      handle=document.createElement("div");
      handle.className="v61-corner-resize";
      handle.dataset.cornerKey=key;
      handle.dataset.pos=CORNERS[key].pos;
      handle.title=`Resize ${CORNERS[key].label} corner`;
      preview.appendChild(handle);
      handle.addEventListener("pointerdown",e=>beginResize(e,key));
    }
    positionHandle(key);
  }

  function decorateCorner(key){
    const img=imageFor(key);
    if(!img)return;
    img.classList.add("v61-direct-corner");
    img.draggable=false;
    img.title=`Drag ${CORNERS[key].label} corner toward the edge to crop; double-click to reset`;
    if(!img.dataset.v61Bound){
      img.dataset.v61Bound="1";
      img.addEventListener("dragstart",e=>e.preventDefault());
      img.addEventListener("pointerdown",e=>beginMove(e,key));
      img.addEventListener("dblclick",e=>resetCorner(e,key));
    }
    ensureHandle(key,img);
    applyPreview(key,settingsFor(key));
  }

  function decoratePreview(){
    if(!state)return;
    document.querySelectorAll(".v60-corner-controls").forEach(el=>el.remove());
    ensureHelp();
    Object.keys(CORNERS).forEach(key=>{
      if(imageFor(key))decorateCorner(key);
      else handleFor(key)?.remove();
    });
  }

  async function sync(){
    if(syncing||!byId("themeStudioOverlay"))return;
    syncing=true;
    try{
      const r=await fetch("/api/themes",{cache:"no-store"});
      const d=await r.json();
      if(r.ok&&d.ok!==false){state=d;decoratePreview();}
    }catch(e){}finally{syncing=false;}
  }

  function scheduleSync(delay=40){
    clearTimeout(syncTimer);
    syncTimer=setTimeout(sync,delay);
  }

  injectStyles();
  byId("openThemeStudio")?.addEventListener("click",()=>scheduleSync(120));
  byId("themeScope")?.addEventListener("change",()=>scheduleSync(60));
  byId("themePreset")?.addEventListener("change",()=>scheduleSync(80));
  byId("saveTheme")?.addEventListener("click",()=>scheduleSync(220));
  byId("resetTheme")?.addEventListener("click",()=>scheduleSync(220));
  window.addEventListener("resize",()=>Object.keys(CORNERS).forEach(positionHandle));

  const observer=new MutationObserver(mutations=>{
    let relevant=false;
    for(const m of mutations){
      for(const n of m.addedNodes){
        if(n.nodeType!==1)continue;
        if(n.matches?.(".theme-preview-corner")||n.querySelector?.(".theme-preview-corner")){relevant=true;break;}
      }
      if(relevant)break;
    }
    if(relevant){decoratePreview();scheduleSync(80);}
  });
  if(document.body)observer.observe(document.body,{childList:true,subtree:true});
})();
