/* Theme Studio for the settings page.
   Uses the normal Pi APIs, stores custom assets persistently, and generates
   recolored PNG assets in-browser before uploading them to the Pi. */
(function(){
  const CLASSIC={
    primary:"#d8b34a",primary_bright:"#e6c760",primary_dark:"#705b20",
    secondary:"#303030",background:"#080808",panel:"#111111",text:"#f5f5f5",
    muted:"#9c9c9c",champion_text:"#ffffff"
  };
  const UNDISPUTED={
    primary:"#c58a2a",primary_bright:"#e1ad48",primary_dark:"#6f4612",
    secondary:"#8b130c",background:"#070706",panel:"#11100d",text:"#e8d6ad",
    muted:"#a3946f",champion_text:"#f7e7ae"
  };

  let state=null;
  let currentScope="office";

  function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
  function byId(id){return document.getElementById(id);}
  async function jsonFetch(url,options={}){
    const r=await fetch(url,{cache:"no-store",...options});
    let d={};try{d=await r.json();}catch(e){}
    if(!r.ok||d.ok===false) throw new Error(d.error||`Request failed (${r.status})`);
    return d;
  }

  function injectStyles(){
    if(byId("themeStudioStyles")) return;
    const s=document.createElement("style");s.id="themeStudioStyles";
    s.textContent=`
      .theme-studio-grid{display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px;align-items:start}
      .theme-studio-side{border:1px solid #303030;background:#0d0d0d;padding:14px;position:sticky;top:10px}
      .theme-studio-main{min-width:0}.theme-color-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
      .theme-color{border:1px solid #2e2e2e;background:#0d0d0d;padding:9px}.theme-color input{height:42px;padding:3px}
      .theme-assets{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}
      .theme-asset{border:1px solid #303030;background:#0d0d0d;padding:10px;min-width:0}
      .theme-asset-preview{width:100%;height:115px;object-fit:contain;background:#070707;border:1px solid #242424;margin:7px 0;display:block}
      .theme-asset-preview.empty{display:grid;place-items:center;color:#777;font-size:12px}.theme-asset-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
      .theme-asset-actions input[type=color]{width:54px;height:36px;padding:2px}.theme-asset-actions input[type=file]{font-size:12px;padding:6px}
      .theme-preview{position:relative;overflow:hidden;border:2px solid #444;min-height:330px;margin-top:12px;background:#080808;padding:16px;color:#fff}
      .theme-preview-frame{position:absolute;inset:7px;border:1px solid var(--p,#d8b34a);pointer-events:none}.theme-preview-head{display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid color-mix(in srgb,var(--p,#d8b34a) 45%,transparent);padding-bottom:10px;position:relative;z-index:1}
      .theme-preview-logo{max-width:280px;max-height:90px;object-fit:contain}.theme-preview-title{font-weight:900;font-size:24px;color:var(--pb,#e6c760);letter-spacing:.05em}.theme-preview-mode{font-size:11px;color:var(--pb,#e6c760);text-transform:uppercase;letter-spacing:.1em}
      .theme-preview-rows{position:relative;z-index:1;margin-top:10px}.theme-preview-row{display:grid;grid-template-columns:44px minmax(150px,1fr) repeat(3,minmax(80px,.7fr));align-items:center;gap:8px;min-height:48px;border-bottom:1px solid rgba(255,255,255,.08);padding:5px 7px;background:rgba(0,0,0,.55)}
      .theme-preview-row.champ{border:1px solid var(--pb,#e6c760);color:var(--ct,#fff);box-shadow:0 0 15px color-mix(in srgb,var(--pb,#e6c760) 24%,transparent)}
      .theme-preview-rank{color:var(--pb,#e6c760);font-weight:900;text-align:center}.theme-preview-name{font-weight:900}.theme-preview-stat{text-align:right;font-variant-numeric:tabular-nums}.theme-preview-stat span{display:block;color:var(--m,#999);font-size:9px;text-transform:uppercase}.theme-preview-stat strong{font-size:14px}
      .theme-preview-corner{position:absolute;width:55px;height:55px;object-fit:contain;z-index:2}.theme-preview-corner.tl{top:0;left:0}.theme-preview-corner.tr{top:0;right:0}.theme-preview-corner.bl{bottom:0;left:0}.theme-preview-corner.br{bottom:0;right:0}
      .theme-status{min-height:20px;margin-top:8px;color:#d8b34a}.theme-logo-box{display:flex;gap:12px;align-items:center;margin-top:8px}.theme-logo-box img{width:90px;height:90px;object-fit:contain;border:1px solid #333;background:#080808}
      @media(max-width:900px){.theme-studio-grid{grid-template-columns:1fr}.theme-studio-side{position:static}.theme-color-grid,.theme-assets{grid-template-columns:1fr}.theme-preview-row{grid-template-columns:34px 1fr}.theme-preview-stat{display:none}}
    `;
    document.head.appendChild(s);
  }

  function installUI(){
    if(byId("openThemeStudio")) return;
    injectStyles();
    const cards=[...document.querySelectorAll("#appWrap .card")];
    const dataCard=cards.find(c=>c.querySelector("h2")?.textContent.trim()==="Data Source");
    const card=document.createElement("div");card.className="card";
    card.innerHTML=`<h2>Theme Studio</h2>
      <p class="small">Give each team its own TV identity. Start with Classic or the imported UNDISPUTED design, then change colors, artwork and logos. Custom assets survive software updates.</p>
      <button id="openThemeStudio" class="btn primary" type="button">Open Theme Studio</button>`;
    (dataCard?.parentNode||byId("appWrap")).insertBefore(card,dataCard||null);

    const overlay=document.createElement("div");overlay.id="themeStudioOverlay";overlay.className="overlay";overlay.setAttribute("aria-hidden","true");
    overlay.innerHTML=`<div class="panel" style="width:min(1180px,100%)">
      <div class="row" style="justify-content:space-between;align-items:flex-start">
        <div><h2 style="margin:0">Theme Studio</h2><div class="small">Full themes apply to individual team views. Team vs Team / All Teams use each team's colors and artwork. Whole Office has its own separate theme.</div></div>
        <button id="closeThemeStudio" class="btn" type="button">Close</button>
      </div>
      <div class="theme-studio-grid" style="margin-top:16px">
        <aside class="theme-studio-side">
          <label for="themeScope">Design</label><select id="themeScope"></select>
          <label for="themePreset" style="margin-top:12px">Starting Theme</label><select id="themePreset"><option value="classic">Classic</option><option value="undisputed">UNDISPUTED</option></select>
          <label class="row" style="margin-top:12px"><input id="themeEnabled" type="checkbox"><span>Use custom theme on TV</span></label>
          <div id="themeLogoControls" style="display:none;margin-top:16px">
            <label>Team Logo</label><div class="theme-logo-box"><div id="themeLogoPreview" class="team-logo placeholder">No logo</div><div style="flex:1"><input id="themeLogoFile" type="file" accept="image/png,image/jpeg,image/webp"><div class="row" style="margin-top:7px"><button id="themeLogoUpload" class="btn" type="button">Replace Logo</button><button id="themeLogoReset" class="btn danger" type="button">Remove</button></div></div></div>
          </div>
          <div class="row" style="margin-top:18px"><button id="saveTheme" class="btn primary" type="button">Save Theme</button><button id="resetTheme" class="btn danger" type="button">Reset to Classic</button></div>
          <div id="themeStatus" class="theme-status small"></div>
        </aside>
        <div class="theme-studio-main">
          <h3 style="margin-top:0">Colors</h3><div id="themeColors" class="theme-color-grid"></div>
          <h3>Live Preview</h3><div class="small">Uses the team's current reps and current ranking metric.</div><div id="themePreview" class="theme-preview"></div>
          <h3>Artwork</h3><div class="small">Upload a replacement, or recolor the current artwork. Recolor creates a real PNG copy; the original preset asset is never modified.</div><div id="themeAssets" class="theme-assets"></div>
        </div>
      </div>
    </div>`;
    document.body.appendChild(overlay);

    byId("openThemeStudio").addEventListener("click",openStudio);
    byId("closeThemeStudio").addEventListener("click",()=>setOpen(false));
    byId("themeScope").addEventListener("change",()=>{currentScope=byId("themeScope").value;populateScope();});
    byId("themePreset").addEventListener("change",presetChanged);
    byId("themeEnabled").addEventListener("change",renderPreview);
    byId("saveTheme").addEventListener("click",saveTheme);
    byId("resetTheme").addEventListener("click",resetTheme);
    byId("themeLogoUpload").addEventListener("click",uploadLogo);
    byId("themeLogoReset").addEventListener("click",resetLogo);
  }

  function setOpen(open){const o=byId("themeStudioOverlay");o.classList.toggle("open",open);o.setAttribute("aria-hidden",open?"false":"true");}

  async function refreshState(){
    state=await jsonFetch("/api/themes");
    const sel=byId("themeScope");
    const old=currentScope;
    sel.innerHTML=`<option value="office">Whole Office Theme</option>`+(state.teams||[]).map(t=>`<option value="team-${t.team_id}">${esc(t.name)}</option>`).join("");
    if([...sel.options].some(o=>o.value===old)) sel.value=old; else currentScope="office";
    populateScope();
  }

  function themeForScope(){
    if(!state) return null;
    if(currentScope==="office") return state.themes.office;
    const id=currentScope.split("-")[1];return state.themes.teams?.[id]||null;
  }
  function teamForScope(){
    if(currentScope==="office") return null;
    const id=Number(currentScope.split("-")[1]);return (state.teams||[]).find(t=>Number(t.team_id)===id)||null;
  }

  function populateScope(){
    const theme=themeForScope();if(!theme) return;
    byId("themePreset").value=theme.base||"classic";
    byId("themeEnabled").checked=!!theme.enabled;
    renderColorInputs(theme.colors||{});
    renderAssets(theme);
    renderLogoControls();
    renderPreview();
    byId("themeStatus").textContent="";
  }

  function renderColorInputs(colors){
    const defs=state.manifest.colors||[];
    byId("themeColors").innerHTML=defs.map(d=>`<div class="theme-color"><label for="themeColor_${d.key}">${esc(d.label)}</label><input class="themeColorInput" data-color-key="${d.key}" id="themeColor_${d.key}" type="color" value="${esc(colors[d.key]||"#000000")}"></div>`).join("");
    document.querySelectorAll(".themeColorInput").forEach(i=>i.addEventListener("input",renderPreview));
  }

  function currentColors(){const out={};document.querySelectorAll(".themeColorInput").forEach(i=>out[i.dataset.colorKey]=i.value);return out;}

  function presetChanged(){
    const preset=byId("themePreset").value;
    const colors=preset==="undisputed"?UNDISPUTED:CLASSIC;
    byId("themeEnabled").checked=preset!=="classic";
    renderColorInputs(colors);
    renderPreview();
  }

  function renderAssets(theme){
    const defs=state.manifest.assets||[];
    const assets=theme.assets||{};
    byId("themeAssets").innerHTML=defs.map(d=>{
      const src=assets[d.key];
      return `<div class="theme-asset" data-asset-key="${d.key}"><strong>${esc(d.label)}</strong>
        ${src?`<img class="theme-asset-preview" data-preview-for="${d.key}" src="${esc(src)}" alt="${esc(d.label)}">`:`<div class="theme-asset-preview empty" data-preview-for="${d.key}">No asset in this preset</div>`}
        <input class="themeAssetFile" data-key="${d.key}" type="file" accept="image/png,image/jpeg,image/webp">
        <div class="theme-asset-actions" style="margin-top:7px"><button class="btn themeAssetUpload" data-key="${d.key}" type="button">Upload</button><input class="themeAssetTint" data-key="${d.key}" type="color" value="${esc(theme.colors?.primary_bright||"#d8b34a")}" title="Recolor"><button class="btn themeAssetRecolor" data-key="${d.key}" type="button" ${src?"":"disabled"}>Recolor</button><button class="btn danger themeAssetReset" data-key="${d.key}" type="button">Reset Asset</button></div>
      </div>`;
    }).join("");
    document.querySelectorAll(".themeAssetUpload").forEach(b=>b.addEventListener("click",()=>uploadAsset(b.dataset.key)));
    document.querySelectorAll(".themeAssetRecolor").forEach(b=>b.addEventListener("click",()=>recolorAsset(b.dataset.key)));
    document.querySelectorAll(".themeAssetReset").forEach(b=>b.addEventListener("click",()=>resetAsset(b.dataset.key)));
  }

  function renderLogoControls(){
    const t=teamForScope();const box=byId("themeLogoControls");box.style.display=t?"block":"none";if(!t)return;
    const p=byId("themeLogoPreview");
    if(t.logo_url){p.className="";p.innerHTML=`<img src="${esc(t.logo_url)}" alt="${esc(t.name)} logo" style="width:90px;height:90px;object-fit:contain">`;}
    else{p.className="team-logo placeholder";p.textContent="No logo";}
  }

  async function openStudio(){
    setOpen(true);byId("themeStatus").textContent="Loading themes…";
    try{await refreshState();}catch(e){byId("themeStatus").textContent=e.message;}
  }

  async function saveTheme(){
    byId("themeStatus").textContent="Saving…";
    try{
      await jsonFetch(`/api/themes/${encodeURIComponent(currentScope)}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({base:byId("themePreset").value,enabled:byId("themeEnabled").checked,colors:currentColors()})});
      await refreshState();byId("themeStatus").textContent="Theme saved. The TV will pick it up automatically.";
    }catch(e){byId("themeStatus").textContent=e.message;}
  }

  async function resetTheme(){
    if(!confirm("Reset this design to the Classic theme? Custom artwork for this theme will stop being used."))return;
    try{await jsonFetch(`/api/themes/${encodeURIComponent(currentScope)}`,{method:"DELETE"});await refreshState();byId("themeStatus").textContent="Reset to Classic.";}catch(e){byId("themeStatus").textContent=e.message;}
  }

  async function uploadAsset(key,blob=null,filename=null){
    const input=document.querySelector(`.themeAssetFile[data-key="${CSS.escape(key)}"]`);
    const file=blob||input?.files?.[0];
    if(!file){byId("themeStatus").textContent="Choose an image first.";return;}
    const form=new FormData();form.append("asset",file,filename||file.name||`${key}.png`);
    byId("themeStatus").textContent=`Saving ${key}…`;
    try{await jsonFetch(`/api/themes/${encodeURIComponent(currentScope)}/assets/${encodeURIComponent(key)}`,{method:"POST",body:form});await refreshState();byId("themeStatus").textContent="Artwork saved.";}catch(e){byId("themeStatus").textContent=e.message;}
  }

  async function resetAsset(key){
    try{await jsonFetch(`/api/themes/${encodeURIComponent(currentScope)}/assets/${encodeURIComponent(key)}`,{method:"DELETE"});await refreshState();byId("themeStatus").textContent="Asset reset to the preset original.";}catch(e){byId("themeStatus").textContent=e.message;}
  }

  function loadImage(src){return new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(new Error("Could not load artwork for recoloring."));img.src=src+(src.includes("?")?"&":"?")+"recolor="+Date.now();});}
  function hexRgb(hex){return [parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)];}

  async function recolorAsset(key){
    const preview=document.querySelector(`[data-preview-for="${CSS.escape(key)}"]`);
    const src=preview?.tagName==="IMG"?preview.src:null;if(!src)return;
    const tint=document.querySelector(`.themeAssetTint[data-key="${CSS.escape(key)}"]`)?.value||"#d8b34a";
    byId("themeStatus").textContent=`Recoloring ${key}…`;
    try{
      const img=await loadImage(src);const canvas=document.createElement("canvas");canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
      const ctx=canvas.getContext("2d",{willReadFrequently:true});ctx.drawImage(img,0,0);const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);const d=pixels.data;const [tr,tg,tb]=hexRgb(tint);
      for(let i=0;i<d.length;i+=4){if(d[i+3]===0)continue;const lum=(0.2126*d[i]+0.7152*d[i+1]+0.0722*d[i+2])/255;const lift=0.30+0.90*lum;d[i]=Math.min(255,tr*lift);d[i+1]=Math.min(255,tg*lift);d[i+2]=Math.min(255,tb*lift);}
      ctx.putImageData(pixels,0,0);
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/png",0.95));if(!blob)throw new Error("Could not generate recolored artwork.");
      await uploadAsset(key,blob,`${key}-recolored.png`);
    }catch(e){byId("themeStatus").textContent=e.message;}
  }

  async function uploadLogo(){
    const team=teamForScope();const file=byId("themeLogoFile").files?.[0];if(!team||!file){byId("themeStatus").textContent="Choose a logo file first.";return;}
    const form=new FormData();form.append("logo",file,file.name);
    try{await jsonFetch(`/api/teams/${team.team_id}/logo`,{method:"POST",body:form});await refreshState();byId("themeStatus").textContent="Team logo updated.";}catch(e){byId("themeStatus").textContent=e.message;}
  }
  async function resetLogo(){const team=teamForScope();if(!team)return;try{await jsonFetch(`/api/teams/${team.team_id}/logo`,{method:"DELETE"});await refreshState();byId("themeStatus").textContent="Team logo removed.";}catch(e){byId("themeStatus").textContent=e.message;}}

  function number(v){const n=Number(v||0);return Number.isFinite(n)?n:0;}
  function money(v){return "$"+number(v).toLocaleString(undefined,{maximumFractionDigits:0});}
  function previewTheme(){
    const existing=themeForScope()||{};return {...existing,base:byId("themePreset").value,enabled:byId("themeEnabled").checked,colors:currentColors()};
  }

  async function renderPreview(){
    const box=byId("themePreview");if(!box||!state)return;
    const theme=previewTheme();const colors=theme.colors||CLASSIC;const assets=(themeForScope()||{}).assets||{};const team=teamForScope();
    box.style.setProperty("--p",colors.primary||"#d8b34a");box.style.setProperty("--pb",colors.primary_bright||"#e6c760");box.style.setProperty("--m",colors.muted||"#999");box.style.setProperty("--ct",colors.champion_text||"#fff");box.style.backgroundColor=colors.background||"#080808";box.style.color=colors.text||"#fff";
    box.style.backgroundImage=theme.enabled&&assets.background?`linear-gradient(rgba(5,5,5,.82),rgba(5,5,5,.82)),url("${assets.background}")`:"none";
    box.innerHTML=`<div class="theme-preview-frame"></div><div style="padding:35px;color:#888">Loading live preview…</div>`;
    const mode=team?`per_team::${team.name}`:"whole_office";
    try{
      const data=await jsonFetch(`/api/leaderboard?mode=${encodeURIComponent(mode)}`);
      const rows=(data.rows||[]).slice(0,4);const heroCustom=assets.hero&&String(assets.hero).includes("/api/theme-assets/");const hero=theme.enabled?(heroCustom?assets.hero:(team?.name?.toLowerCase()==="undisputed"?assets.hero:team?.logo_url)):team?.logo_url;
      const corners=theme.enabled?[["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]]:[];
      box.innerHTML=`<div class="theme-preview-frame"></div>${corners.map(([k,p])=>assets[k]?`<img class="theme-preview-corner ${p}" src="${esc(assets[k])}" alt="">`:"").join("")}
        <div class="theme-preview-head">${hero?`<img class="theme-preview-logo" src="${esc(hero)}" alt="">`:`<div class="theme-preview-title">${esc(team?.name||data.title||"WHOLE OFFICE")}</div>`}<div class="theme-preview-mode">${esc(team?"Team Leaderboard":"Whole Office")}</div></div>
        <div class="theme-preview-rows">${rows.map((r,i)=>`<div class="theme-preview-row ${i===0&&theme.enabled?"champ":""}" style="${i===0&&theme.enabled&&assets.champion?`background-image:linear-gradient(rgba(0,0,0,.35),rgba(0,0,0,.35)),url('${esc(assets.champion)}');background-size:100% 100%`:theme.enabled&&assets.row?`background-image:linear-gradient(rgba(0,0,0,.45),rgba(0,0,0,.45)),url('${esc(assets.row)}');background-size:100% 100%`:""}"><div class="theme-preview-rank">${i===0&&theme.enabled&&assets.medallion?`<img src="${esc(assets.medallion)}" style="width:34px;height:34px;object-fit:contain">`:`#${i+1}`}</div><div class="theme-preview-name">${esc(r.rep_name)}</div><div class="theme-preview-stat"><span>Close</span><strong>${number(r.close_rate).toFixed(2)}%</strong></div><div class="theme-preview-stat"><span>Sold</span><strong>${number(r.sold_leads).toFixed(2).replace(/\.00$/,"")}</strong></div><div class="theme-preview-stat"><span>Net</span><strong>${money(r.net_split)}</strong></div></div>`).join("")||`<div style="padding:35px;color:#888">No assigned reps yet.</div>`}</div>`;
    }catch(e){box.innerHTML=`<div class="theme-preview-frame"></div><div style="padding:35px;color:#888">Preview unavailable: ${esc(e.message)}</div>`;}
  }

  installUI();
})();
