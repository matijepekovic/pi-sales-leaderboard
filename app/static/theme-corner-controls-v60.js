/* v60 Theme Studio corner controls.
   Adds persistent per-corner size and edge-crop controls without replacing the
   existing Theme Studio. Changes save directly into the team's theme config. */
(function(){
  const CORNERS={
    corner_tl:{pos:"tl",label:"Top Left"},
    corner_tr:{pos:"tr",label:"Top Right"},
    corner_bl:{pos:"bl",label:"Bottom Left"},
    corner_br:{pos:"br",label:"Bottom Right"}
  };
  const DEFAULTS={size:100,crop_x:0,crop_y:0};
  let state=null;
  let syncing=false;
  let syncTimer=null;

  function byId(id){return document.getElementById(id);}
  function scope(){return String(byId("themeScope")?.value||"").trim();}
  function teamId(){const s=scope();return s.startsWith("team-")?s.slice(5):"";}
  function theme(){const id=teamId();return id&&state?.themes?.teams?.[id]||null;}
  function val(n,d){n=Number(n);return Number.isFinite(n)?n:d;}
  function settingsFor(key){
    const saved=theme()?.corner_settings?.[key]||{};
    return {size:val(saved.size,100),crop_x:val(saved.crop_x,0),crop_y:val(saved.crop_y,0)};
  }

  function injectStyles(){
    if(byId("v60CornerControlStyles")) return;
    const s=document.createElement("style");s.id="v60CornerControlStyles";
    s.textContent=`
      .v60-corner-controls{margin-top:10px;padding:10px;border:1px solid #2e2e2e;background:#090909}
      .v60-corner-controls-head{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:7px}
      .v60-corner-control{display:grid;grid-template-columns:74px minmax(0,1fr) 48px;gap:8px;align-items:center;margin-top:7px}
      .v60-corner-control label{margin:0;font-size:12px;color:#b8b8b8}.v60-corner-control input{padding:0;height:24px}
      .v60-corner-value{text-align:right;color:#d8b34a;font-size:12px;font-variant-numeric:tabular-nums}
      .v60-corner-help{font-size:11px;color:#777;line-height:1.35;margin-top:8px}
    `;
    document.head.appendChild(s);
  }

  function transformFor(key,cfg){
    const info=CORNERS[key];if(!info)return "";
    const sx=info.pos.endsWith("r")?1:-1;
    const sy=info.pos.startsWith("b")?1:-1;
    return `translate(${sx*cfg.crop_x}%,${sy*cfg.crop_y}%) scale(${cfg.size/100})`;
  }

  function originFor(key){
    const p=CORNERS[key]?.pos||"tl";
    return `${p.endsWith("r")?"right":"left"} ${p.startsWith("b")?"bottom":"top"}`;
  }

  function applyPreview(key,cfg){
    const p=CORNERS[key]?.pos;if(!p)return;
    document.querySelectorAll(`.theme-preview-corner.${p}`).forEach(img=>{
      img.style.transformOrigin=originFor(key);
      img.style.transform=transformFor(key,cfg);
    });
  }

  function readControls(box){
    return {
      size:val(box.querySelector('[data-corner-field="size"]')?.value,100),
      crop_x:val(box.querySelector('[data-corner-field="crop_x"]')?.value,0),
      crop_y:val(box.querySelector('[data-corner-field="crop_y"]')?.value,0),
    };
  }

  function refreshLabels(box,cfg){
    const values={size:`${Math.round(cfg.size)}%`,crop_x:`${Math.round(cfg.crop_x)}%`,crop_y:`${Math.round(cfg.crop_y)}%`};
    Object.entries(values).forEach(([field,text])=>{
      const out=box.querySelector(`[data-corner-value="${field}"]`);if(out)out.textContent=text;
    });
  }

  async function saveCorner(key,cfg){
    const s=scope();if(!s)return;
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
      if(status)status.textContent="Corner adjustment saved. The TV will pick it up automatically.";
    }catch(e){if(status)status.textContent=e.message;}
  }

  function addControls(card,key){
    if(card.querySelector(`.v60-corner-controls[data-corner-key="${key}"]`))return;
    const cfg=settingsFor(key);
    const box=document.createElement("div");box.className="v60-corner-controls";box.dataset.cornerKey=key;
    box.innerHTML=`
      <div class="v60-corner-controls-head"><strong>Size & Crop</strong><button class="btn v60CornerReset" type="button">Reset</button></div>
      <div class="v60-corner-control"><label>Size</label><input type="range" min="50" max="250" step="5" value="${cfg.size}" data-corner-field="size"><span class="v60-corner-value" data-corner-value="size"></span></div>
      <div class="v60-corner-control"><label>Crop X</label><input type="range" min="0" max="60" step="1" value="${cfg.crop_x}" data-corner-field="crop_x"><span class="v60-corner-value" data-corner-value="crop_x"></span></div>
      <div class="v60-corner-control"><label>Crop Y</label><input type="range" min="0" max="60" step="1" value="${cfg.crop_y}" data-corner-field="crop_y"><span class="v60-corner-value" data-corner-value="crop_y"></span></div>
      <div class="v60-corner-help">Crop pushes the ornament past its screen edge so the excess is clipped. Each corner is adjusted independently.</div>`;
    card.appendChild(box);
    refreshLabels(box,cfg);applyPreview(key,cfg);

    box.querySelectorAll('input[type="range"]').forEach(input=>{
      input.addEventListener("input",()=>{const next=readControls(box);refreshLabels(box,next);applyPreview(key,next);});
      input.addEventListener("change",()=>saveCorner(key,readControls(box)));
    });
    box.querySelector(".v60CornerReset")?.addEventListener("click",()=>{
      Object.entries(DEFAULTS).forEach(([field,value])=>{const input=box.querySelector(`[data-corner-field="${field}"]`);if(input)input.value=value;});
      const next=readControls(box);refreshLabels(box,next);applyPreview(key,next);saveCorner(key,next);
    });
  }

  function renderControls(){
    if(!state)return;
    Object.keys(CORNERS).forEach(key=>{
      const card=document.querySelector(`.theme-asset[data-asset-key="${key}"]`);
      if(card)addControls(card,key);
      applyPreview(key,settingsFor(key));
    });
  }

  async function sync(){
    if(syncing||!byId("themeStudioOverlay"))return;
    syncing=true;
    try{
      const r=await fetch("/api/themes",{cache:"no-store"});
      const d=await r.json();
      if(r.ok&&d.ok!==false){state=d;renderControls();}
    }catch(e){}finally{syncing=false;}
  }

  function scheduleSync(delay=40){
    clearTimeout(syncTimer);syncTimer=setTimeout(sync,delay);
  }

  injectStyles();
  byId("openThemeStudio")?.addEventListener("click",()=>scheduleSync(120));
  byId("themeScope")?.addEventListener("change",()=>scheduleSync(80));
  byId("themePreset")?.addEventListener("change",()=>scheduleSync(80));
  byId("saveTheme")?.addEventListener("click",()=>scheduleSync(220));
  byId("resetTheme")?.addEventListener("click",()=>scheduleSync(220));

  const observer=new MutationObserver(mutations=>{
    let relevant=false;
    for(const m of mutations){
      for(const n of m.addedNodes){
        if(n.nodeType!==1)continue;
        if(n.matches?.(".theme-asset,.theme-preview-corner")||n.querySelector?.(".theme-asset,.theme-preview-corner")){relevant=true;break;}
      }
      if(relevant)break;
    }
    if(relevant){renderControls();scheduleSync(100);}
  });
  if(document.body)observer.observe(document.body,{childList:true,subtree:true});
})();
