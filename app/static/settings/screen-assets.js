/* Screen-owned asset placement. Themes supply content; instances supply geometry. */
(function(){
  const esc=window.StatsSettings.esc,Renderer=window.StatsWidgetRenderer;
  const clamp=(value,low,high)=>Math.max(low,Math.min(high,Number(value)||0));
  const label=key=>String(key).replace(/_/g," ").replace(/\b\w/g,char=>char.toUpperCase());
  function initialize(screen,theme){
    if(Array.isArray(screen.assets))return;
    screen.assets=(theme?.layout?.asset_slots||[]).map((asset,index)=>({id:asset.id||`asset-${index}`,key:asset.key,x:asset.x,y:asset.y,width:asset.width,height:asset.height,fit:asset.fit||"contain"}));
  }
  function controls(screen,theme){
    const choices=Object.keys(theme?.assets||{}).filter(key=>!["background","row","champion"].includes(key)&&theme.assets[key]);
    return `<div class="subcard"><h3>Assets</h3><div class="row" style="flex-wrap:nowrap"><select data-screen-asset-choice aria-label="Theme asset"><option value="">Choose asset…</option>${choices.map(key=>`<option value="${esc(key)}">${esc(label(key))}</option>`).join("")}</select><button class="btn" type="button" data-screen-asset-add ${choices.length?"":"disabled"}>Add</button></div><div class="stack" style="margin-top:10px">${(screen.assets||[]).map(asset=>`<div class="screen-asset-control"><strong>${esc(label(asset.key))}</strong><select data-screen-asset-fit="${esc(asset.id)}" aria-label="${esc(label(asset.key))} sizing"><option value="contain" ${asset.fit!=="cover"?"selected":""}>Fit</option><option value="cover" ${asset.fit==="cover"?"selected":""}>Fill</option></select><button class="btn widget-small-button" data-screen-asset-remove="${esc(asset.id)}" aria-label="Remove ${esc(label(asset.key))}">×</button></div>`).join("")}</div></div>`;
  }
  function render(screen,theme){return (screen.assets||[]).map(asset=>{const url=Renderer.safeUrl(theme?.assets?.[asset.key]);return `<div class="screen-placed-asset" data-screen-asset="${esc(asset.id)}" style="left:${Number(asset.x)}%;top:${Number(asset.y)}%;width:${Number(asset.width)}%;height:${Number(asset.height)}%">${url?`<img src="${esc(url)}" alt="" style="object-fit:${asset.fit==="cover"?"cover":"contain"}">`:`<span>${esc(label(asset.key))}</span>`}<button class="screen-asset-handle" data-screen-asset-move="${esc(asset.id)}" aria-label="Move ${esc(label(asset.key))}">${esc(label(asset.key))}</button><button class="screen-instance-resize" data-screen-asset-resize="${esc(asset.id)}" aria-label="Resize ${esc(label(asset.key))}"></button></div>`;}).join("");}
  function bindControls(host,screen,onChange){
    host.querySelector("[data-screen-asset-add]")?.addEventListener("click",()=>{const key=host.querySelector("[data-screen-asset-choice]")?.value;if(!key)return;screen.assets=screen.assets||[];screen.assets.push({id:`asset-${crypto.randomUUID()}`,key,x:5,y:5,width:20,height:20,fit:"contain"});onChange();});
    host.querySelectorAll("[data-screen-asset-remove]").forEach(button=>button.addEventListener("click",()=>{screen.assets=screen.assets.filter(asset=>asset.id!==button.dataset.screenAssetRemove);onChange();}));
    host.querySelectorAll("[data-screen-asset-fit]").forEach(select=>select.addEventListener("change",()=>{const asset=screen.assets.find(item=>item.id===select.dataset.screenAssetFit);if(asset)asset.fit=select.value;onChange();}));
  }
  function bindCanvas(stage,screen,onChange){
    const start=(event,id,kind)=>{if(event.button!==undefined&&event.button!==0)return;event.preventDefault();event.stopPropagation();const asset=screen.assets.find(item=>item.id===id),element=stage.querySelector(`[data-screen-asset="${CSS.escape(id)}"]`),rect=stage.getBoundingClientRect(),initial={...asset},origin={x:event.clientX,y:event.clientY};if(!asset||!element)return;
      const move=pointer=>{const dx=(pointer.clientX-origin.x)/Math.max(1,rect.width)*100,dy=(pointer.clientY-origin.y)/Math.max(1,rect.height)*100;if(kind==="move"){asset.x=clamp(initial.x+dx,0,100-asset.width);asset.y=clamp(initial.y+dy,0,100-asset.height);}else{asset.width=clamp(initial.width+dx,1,100-asset.x);asset.height=clamp(initial.height+dy,1,100-asset.y);}for(const key of ["x","y","width","height"])asset[key]=Math.round(asset[key]*100)/100;element.style.left=asset.x+"%";element.style.top=asset.y+"%";element.style.width=asset.width+"%";element.style.height=asset.height+"%";};
      const end=()=>{window.removeEventListener("pointermove",move);window.removeEventListener("pointerup",end);window.removeEventListener("pointercancel",end);onChange();};window.addEventListener("pointermove",move);window.addEventListener("pointerup",end);window.addEventListener("pointercancel",end);
    };
    stage.querySelectorAll("[data-screen-asset-move]").forEach(handle=>handle.addEventListener("pointerdown",event=>start(event,handle.dataset.screenAssetMove,"move")));stage.querySelectorAll("[data-screen-asset-resize]").forEach(handle=>handle.addEventListener("pointerdown",event=>start(event,handle.dataset.screenAssetResize,"resize")));
  }
  window.StatsScreenAssets=Object.freeze({initialize,controls,render,bindControls,bindCanvas});
})();
