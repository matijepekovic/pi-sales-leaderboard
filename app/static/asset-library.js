/* Prebuilt Theme Studio asset library.
   Catalog items are fetched from /static/asset-library/catalog.json.
   Selecting an item copies it through the existing persistent theme-asset API.
   Tinting is generated in-browser and saved as a PNG, so the source library is
   never modified and user themes continue to survive software updates. */
(function(){
  const CATALOG_URL="/static/asset-library/catalog.json?v=44";
  let catalog=null;
  let activeCollection="all";

  function byId(id){return document.getElementById(id);}
  function esc(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
  function scope(){return byId("themeScope")?.value||"office";}
  function setStatus(text){const el=byId("assetLibraryStatus");if(el)el.textContent=text||"";}
  function setBusy(busy){document.querySelectorAll(".asset-library-action").forEach(b=>b.disabled=!!busy);}

  async function request(url,options={}){
    const response=await fetch(url,{cache:"no-store",...options});
    if(!response.ok){
      let message=`Request failed (${response.status})`;
      try{const data=await response.json();message=data.error||message;}catch(e){}
      throw new Error(message);
    }
    return response;
  }

  async function loadCatalog(){
    const response=await request(CATALOG_URL);
    catalog=await response.json();
    return catalog;
  }

  function injectStyles(){
    if(byId("assetLibraryStyles"))return;
    const style=document.createElement("style");style.id="assetLibraryStyles";
    style.textContent=`
      .asset-library-shell{border:1px solid #383838;background:#0c0c0c;padding:14px;margin:10px 0 20px}
      .asset-library-top{display:grid;grid-template-columns:minmax(180px,260px) 1fr;gap:12px;align-items:end}
      .asset-library-bundle{border:1px solid #2d2d2d;background:#101010;padding:12px;margin-top:12px}
      .asset-library-bundle-actions{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin-top:9px}
      .asset-library-bundle-actions input[type=color]{width:56px;height:38px;padding:2px}
      .asset-library-category{margin-top:17px}.asset-library-category h4{margin:0 0 8px;color:#ddd}
      .asset-library-items{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
      .asset-library-item{border:1px solid #303030;background:#111;padding:9px;min-width:0}
      .asset-library-badge{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#d8b34a;margin-bottom:4px}
      .asset-library-name{font-weight:900;margin-bottom:7px}
      .asset-library-preview{height:105px;border:1px solid #292929;background:#070707;display:grid;place-items:center;position:relative;overflow:hidden}
      .asset-library-preview>img{width:100%;height:100%;object-fit:contain}
      .asset-library-corners img{position:absolute;width:54px;height:54px;object-fit:contain}
      .asset-library-corners .tl{top:2px;left:2px}.asset-library-corners .tr{top:2px;right:2px}.asset-library-corners .bl{bottom:2px;left:2px}.asset-library-corners .br{bottom:2px;right:2px}
      .asset-library-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:8px}
      .asset-library-actions input[type=color]{width:48px;height:35px;padding:2px}
      .asset-library-empty{color:#777;padding:12px;border:1px dashed #333}
      #assetLibraryStatus{min-height:18px;color:#d8b34a;margin-top:9px}
      @media(max-width:900px){.asset-library-top{grid-template-columns:1fr}.asset-library-items{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function installUI(){
    if(byId("assetLibraryPanel"))return true;
    const studio=byId("themeStudioOverlay");
    const main=studio?.querySelector(".theme-studio-main");
    if(!main)return false;
    injectStyles();
    const artworkHeading=[...main.querySelectorAll("h3")].find(h=>h.textContent.trim()==="Artwork");
    const panel=document.createElement("section");panel.id="assetLibraryPanel";panel.className="asset-library-shell";
    panel.innerHTML=`
      <div class="row" style="justify-content:space-between;align-items:flex-start">
        <div><h3 style="margin:0">Asset Collections</h3><div class="small" style="margin-top:4px">Choose prebuilt artwork, then use it as-is or tint it to the team's colors. Mix pieces from different collections or apply a whole collection at once.</div></div>
      </div>
      <div class="asset-library-top" style="margin-top:12px">
        <div><label for="assetLibraryCollection">Collection</label><select id="assetLibraryCollection"><option value="all">All Collections</option></select></div>
        <div id="assetLibraryBundle"></div>
      </div>
      <div id="assetLibraryCategories"></div>
      <div id="assetLibraryStatus" class="small"></div>`;
    if(artworkHeading)main.insertBefore(panel,artworkHeading);else main.appendChild(panel);
    byId("assetLibraryCollection").addEventListener("change",e=>{activeCollection=e.target.value;renderLibrary();});
    return true;
  }

  function collectionByKey(key){return (catalog?.collections||[]).find(c=>c.key===key)||null;}
  function firstTarget(item){return Object.values(item.targets||{})[0]||null;}

  function previewHTML(item){
    const targets=item.targets||{};
    if(item.category==="corners"){
      return `<div class="asset-library-preview asset-library-corners">
        ${targets.corner_tl?`<img class="tl" src="${esc(targets.corner_tl)}" alt="">`:""}
        ${targets.corner_tr?`<img class="tr" src="${esc(targets.corner_tr)}" alt="">`:""}
        ${targets.corner_bl?`<img class="bl" src="${esc(targets.corner_bl)}" alt="">`:""}
        ${targets.corner_br?`<img class="br" src="${esc(targets.corner_br)}" alt="">`:""}
      </div>`;
    }
    const src=firstTarget(item);
    return src?`<div class="asset-library-preview"><img src="${esc(src)}" alt="${esc(item.label)}"></div>`:`<div class="asset-library-preview asset-library-empty">No preview</div>`;
  }

  function renderCollectionOptions(){
    const select=byId("assetLibraryCollection");if(!select||!catalog)return;
    const previous=activeCollection;
    select.innerHTML='<option value="all">All Collections</option>'+(catalog.collections||[]).map(c=>`<option value="${esc(c.key)}">${esc(c.label)}</option>`).join("");
    select.value=[...select.options].some(o=>o.value===previous)?previous:"all";
    activeCollection=select.value;
  }

  function renderBundle(){
    const box=byId("assetLibraryBundle");if(!box||!catalog)return;
    if(activeCollection==="all"){
      box.innerHTML='<div class="small">Select a collection to apply its complete row, champion, medallion, totals mark and corner set in one click.</div>';
      return;
    }
    const collection=collectionByKey(activeCollection);
    if(!collection){box.innerHTML="";return;}
    box.innerHTML=`<div class="asset-library-bundle"><strong>${esc(collection.label)} Collection</strong><div class="small" style="margin-top:3px">${esc(collection.description||"")}</div><div class="asset-library-bundle-actions"><button class="btn asset-library-action" id="assetLibraryUseBundle" type="button">Use Entire Collection</button><input id="assetLibraryBundleTint" type="color" value="#d8b34a" title="Collection tint"><button class="btn primary asset-library-action" id="assetLibraryTintBundle" type="button">Tint Entire Collection</button></div></div>`;
    byId("assetLibraryUseBundle").addEventListener("click",()=>applyTargets(collection.bundle||{},null,`${collection.label} collection`));
    byId("assetLibraryTintBundle").addEventListener("click",()=>applyTargets(collection.bundle||{},byId("assetLibraryBundleTint").value,`${collection.label} collection`));
  }

  function visibleItems(){
    const collections=activeCollection==="all"?(catalog?.collections||[]):[collectionByKey(activeCollection)].filter(Boolean);
    return collections.flatMap(collection=>(collection.items||[]).map(item=>({...item,_collection:collection})));
  }

  function renderLibrary(){
    if(!catalog||!installUI())return;
    renderCollectionOptions();renderBundle();
    const container=byId("assetLibraryCategories");
    const items=visibleItems();
    container.innerHTML=(catalog.categories||[]).map(category=>{
      const matching=items.filter(item=>item.category===category.key);
      if(!matching.length)return "";
      return `<section class="asset-library-category"><h4>${esc(category.label)}</h4><div class="asset-library-items">${matching.map(item=>`<article class="asset-library-item" data-library-item="${esc(item.key)}"><div class="asset-library-badge">${esc(item._collection.label)}</div><div class="asset-library-name">${esc(item.label)}</div>${previewHTML(item)}<div class="asset-library-actions"><button class="btn asset-library-action libraryUseOriginal" data-item="${esc(item.key)}" type="button">Use Original</button><input class="libraryTint" data-item="${esc(item.key)}" type="color" value="#d8b34a" title="Tint"><button class="btn primary asset-library-action libraryUseTint" data-item="${esc(item.key)}" type="button">Tint & Use</button></div></article>`).join("")}</div></section>`;
    }).join("")||'<div class="asset-library-empty">No assets in this collection yet.</div>';

    document.querySelectorAll(".libraryUseOriginal").forEach(button=>button.addEventListener("click",()=>{
      const item=items.find(x=>x.key===button.dataset.item);if(item)applyTargets(item.targets||{},null,item.label);
    }));
    document.querySelectorAll(".libraryUseTint").forEach(button=>button.addEventListener("click",()=>{
      const item=items.find(x=>x.key===button.dataset.item);const tint=document.querySelector(`.libraryTint[data-item="${CSS.escape(button.dataset.item)}"]`)?.value||"#d8b34a";if(item)applyTargets(item.targets||{},tint,item.label);
    }));
  }

  async function sourceBlob(url){
    const response=await request(url+(url.includes("?")?"&":"?")+"assetlib="+Date.now());
    return response.blob();
  }

  function loadBlobImage(blob){
    return new Promise((resolve,reject)=>{
      const url=URL.createObjectURL(blob);const img=new Image();
      img.onload=()=>{URL.revokeObjectURL(url);resolve(img);};
      img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("Could not load library artwork."));};
      img.src=url;
    });
  }

  function hexRgb(hex){return [parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)];}

  async function tintedBlob(url,tint){
    const source=await sourceBlob(url);const img=await loadBlobImage(source);
    const canvas=document.createElement("canvas");canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
    const ctx=canvas.getContext("2d",{willReadFrequently:true});ctx.drawImage(img,0,0);
    const image=ctx.getImageData(0,0,canvas.width,canvas.height);const data=image.data;const [tr,tg,tb]=hexRgb(tint);
    for(let i=0;i<data.length;i+=4){
      if(data[i+3]===0)continue;
      const lum=(0.2126*data[i]+0.7152*data[i+1]+0.0722*data[i+2])/255;
      const lift=0.30+0.90*lum;
      data[i]=Math.min(255,tr*lift);data[i+1]=Math.min(255,tg*lift);data[i+2]=Math.min(255,tb*lift);
    }
    ctx.putImageData(image,0,0);
    return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error("Could not generate tinted artwork.")),"image/png",0.95));
  }

  function sourceExtension(url){
    const clean=String(url||"").split("?")[0].toLowerCase();
    if(clean.endsWith(".jpg")||clean.endsWith(".jpeg"))return ".jpg";
    if(clean.endsWith(".webp"))return ".webp";
    return ".png";
  }

  async function uploadTarget(target,url,tint){
    const blob=tint?await tintedBlob(url,tint):await sourceBlob(url);
    const ext=tint?".png":sourceExtension(url);
    const form=new FormData();form.append("asset",blob,`${target}-library${tint?"-tinted":""}${ext}`);
    const response=await request(`/api/themes/${encodeURIComponent(scope())}/assets/${encodeURIComponent(target)}`,{method:"POST",body:form});
    const data=await response.json();if(data.ok===false)throw new Error(data.error||"Could not save asset.");
  }

  async function enableTheme(){
    const response=await request(`/api/themes/${encodeURIComponent(scope())}`,{
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({enabled:true})
    });
    const data=await response.json();if(data.ok===false)throw new Error(data.error||"Could not enable theme.");
  }

  async function applyTargets(targets,tint,label){
    const pairs=Object.entries(targets||{}).filter(([,url])=>!!url);
    if(!pairs.length)return;
    setBusy(true);setStatus(`${tint?"Tinting and applying":"Applying"} ${label}…`);
    try{
      for(const [target,url] of pairs)await uploadTarget(target,url,tint);
      await enableTheme();
      setStatus(`${label} applied${tint?` with tint ${tint}`:""}.`);
      // Re-run the existing Theme Studio opener while it is already open. This
      // refreshes its private state and previews without closing the overlay.
      byId("openThemeStudio")?.click();
      setTimeout(()=>setStatus(`${label} applied${tint?` with tint ${tint}`:""}.`),250);
    }catch(error){setStatus(error.message||String(error));}
    finally{setBusy(false);}
  }

  async function start(){
    // theme-studio.js creates the overlay synchronously, but retry briefly in
    // case this script is moved or loaded asynchronously later.
    for(let i=0;i<20&&!installUI();i++)await new Promise(r=>setTimeout(r,50));
    if(!byId("assetLibraryPanel"))return;
    setStatus("Loading asset collections…");
    try{await loadCatalog();renderLibrary();setStatus("");}
    catch(error){setStatus(error.message||String(error));}
  }

  start();
})();
