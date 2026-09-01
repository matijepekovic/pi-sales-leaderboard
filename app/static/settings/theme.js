/* Screen Theme + Asset Manager Settings owner. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const S={id:"",manifest:{},theme:{},library:{},message:""};
  const overlay=()=>$("screenThemeOverlay");

  async function load(id){
    S.id=String(id||"");
    if(!S.id)throw new Error("Save the Screen before editing its Theme.");
    const [t,l]=await Promise.all([R.api(`/api/screen-themes/${encodeURIComponent(S.id)}`),R.api("/api/asset-library")]);
    S.manifest=t.manifest||{};S.theme=t.theme||{};S.library=l.items||{};S.message="";
  }

  function colors(){
    return `<div class="grid">${(S.manifest.colors||[]).map(c=>`<div><label>${esc(c.label)}</label><div class="row" style="flex-wrap:nowrap"><input type="color" data-color="${esc(c.key)}" value="${esc(S.theme.colors?.[c.key]||'#000000')}" style="width:52px;height:42px;padding:3px"><input data-color-text="${esc(c.key)}" value="${esc(S.theme.colors?.[c.key]||'')}" maxlength="7"></div></div>`).join("")}</div>`;
  }

  function assets(){
    return `<div class="stack">${(S.manifest.assets||[]).map(a=>{
      const items=S.library[a.key]||[],url=S.theme.assets?.[a.key]||"";
      return `<div class="subcard"><div class="toolbar"><strong>${esc(a.label)}</strong>${url?`<img src="${esc(url)}" alt="" style="width:90px;height:52px;object-fit:contain;background:#080b0e;border:1px solid #333">`:""}</div><div class="grid" style="margin-top:9px"><div><label>Saved Asset</label><select data-library="${esc(a.key)}"><option value="">Choose…</option>${items.map(i=>`<option value="${esc(i.id)}">${esc(i.label||i.id)}</option>`).join("")}</select></div><div><label>Upload</label><input type="file" accept="image/png,image/jpeg,image/webp" data-upload="${esc(a.key)}"></div></div><div class="row" style="margin-top:8px"><button class="btn" data-action="apply" data-key="${esc(a.key)}">Apply Saved</button><button class="btn" data-action="upload" data-key="${esc(a.key)}">Upload & Apply</button><button class="btn danger" data-action="remove" data-key="${esc(a.key)}">Remove</button></div></div>`;
    }).join("")}</div>`;
  }

  function render(){
    const root=overlay();if(!root)return;
    root.innerHTML=`<div class="panel" style="width:min(1500px,100%)"><div class="toolbar"><div><h2>Screen Theme</h2><div class="small">Theme changes visuals only.</div></div><button class="btn" data-action="close">Close</button></div><div class="screen-layout" style="margin-top:14px"><div><div class="subcard"><label>Base</label><select id="themeBase">${(S.manifest.presets||[]).map(p=>`<option value="${esc(p.key)}" ${p.key===S.theme.base?"selected":""}>${esc(p.label)}</option>`).join("")}</select><h3 style="margin-top:16px">Colors</h3>${colors()}<div class="grid" style="margin-top:12px"><div><label>Hero Scale</label><input id="themeHeroScale" type="number" min="50" max="200" value="${Number(S.theme.hero_scale||100)}"></div><div><label>Row Accent Strength</label><input id="themeStripeStrength" type="number" min="0" max="100" value="${Number(S.theme.row_stripe?.strength||0)}"></div><div><label>Row Accent</label><input id="themeStripeColor" type="color" value="${esc(S.theme.row_stripe?.color||S.theme.colors?.primary||'#d8b34a')}"></div></div><div class="row" style="margin-top:12px"><button class="btn primary" data-action="save">Save Theme</button><button class="btn danger" data-action="reset">Reset Theme</button></div></div><div class="card" style="margin-top:12px"><h3>Asset Manager</h3>${assets()}</div><div class="status">${esc(S.message)}</div></div><div class="preview" style="padding:0;height:70vh;overflow:hidden"><iframe id="themePreview" src="/?screen_id=${encodeURIComponent(S.id)}" title="Screen preview" style="width:100%;height:100%;border:0"></iframe></div></div></div>`;
    bind();
  }

  function sync(){
    const root=overlay();if(!root)return;
    S.theme.base=root.querySelector("#themeBase")?.value||S.theme.base;
    const next={...(S.theme.colors||{})};root.querySelectorAll("[data-color-text]").forEach(i=>next[i.dataset.colorText]=i.value.trim());S.theme.colors=next;
    S.theme.hero_scale=Number(root.querySelector("#themeHeroScale")?.value||100);
    S.theme.row_stripe={color:root.querySelector("#themeStripeColor")?.value||next.primary,strength:Number(root.querySelector("#themeStripeStrength")?.value||0)};
  }
  function refreshPreview(){const f=$("themePreview");if(f)f.src=`/?screen_id=${encodeURIComponent(S.id)}&v=${Date.now()}`;}
  async function refreshLibrary(){const l=await R.api("/api/asset-library");S.library=l.items||{};}

  async function save(){sync();try{const d=await R.api(`/api/screen-themes/${encodeURIComponent(S.id)}`,R.json("PUT",S.theme));S.theme=d.theme;S.message="Theme saved.";render();refreshPreview();R.emit("theme-changed",S.id);}catch(e){S.message=e.message;render();}}
  async function reset(){if(!confirm("Reset this Screen Theme?"))return;try{const d=await R.api(`/api/screen-themes/${encodeURIComponent(S.id)}`,{method:"DELETE"});S.theme=d.theme;S.message="Theme reset.";render();refreshPreview();R.emit("theme-changed",S.id);}catch(e){S.message=e.message;render();}}
  async function apply(key){const select=overlay()?.querySelector(`[data-library="${key}"]`);if(!select?.value){S.message="Choose a saved asset.";render();return;}try{const d=await R.api(`/api/screen-themes/${encodeURIComponent(S.id)}/assets/${encodeURIComponent(key)}`,R.json("POST",{library_id:select.value}));S.theme=d.theme;S.message="Asset applied.";render();refreshPreview();R.emit("theme-changed",S.id);}catch(e){S.message=e.message;render();}}
  async function upload(key){const input=overlay()?.querySelector(`[data-upload="${key}"]`),file=input?.files?.[0];if(!file){S.message="Choose an image.";render();return;}const form=new FormData();form.append("asset",file);try{const d=await R.api(`/api/screen-themes/${encodeURIComponent(S.id)}/assets/${encodeURIComponent(key)}`,{method:"POST",body:form});S.theme=d.theme;await refreshLibrary();S.message="Asset uploaded and applied.";render();refreshPreview();R.emit("theme-changed",S.id);}catch(e){S.message=e.message;render();}}
  async function remove(key){try{const d=await R.api(`/api/screen-themes/${encodeURIComponent(S.id)}/assets/${encodeURIComponent(key)}`,{method:"DELETE"});S.theme=d.theme;S.message="Asset removed.";render();refreshPreview();R.emit("theme-changed",S.id);}catch(e){S.message=e.message;render();}}
  function close(){const root=overlay();root?.classList.remove("open");root?.setAttribute("aria-hidden","true");if(root)root.innerHTML="";}

  function bind(){
    const root=overlay();if(!root)return;
    root.querySelectorAll("[data-color]").forEach(i=>i.addEventListener("input",()=>{const t=root.querySelector(`[data-color-text="${i.dataset.color}"]`);if(t)t.value=i.value;}));
    root.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",()=>{const a=b.dataset.action,k=b.dataset.key;if(a==="close")close();else if(a==="save")save();else if(a==="reset")reset();else if(a==="apply")apply(k);else if(a==="upload")upload(k);else if(a==="remove")remove(k);}));
  }

  async function open(id){await load(id);render();overlay().classList.add("open");overlay().setAttribute("aria-hidden","false");}
  window.StatsThemeManager=Object.freeze({open});
})();
