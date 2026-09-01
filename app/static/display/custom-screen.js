/* Custom screen renderer. Consumes only normalized Screen sections. */
(function(){
  if(typeof render!=="function") return;
  const baseRender=render;
  const numberTypes=new Set(["currency","percent","number"]);
  const text=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const value=(v,type,symbol)=>{
    const n=Number(v||0);
    if(type==="currency") return `${symbol||"$"}${Math.round(n).toLocaleString()}`;
    if(type==="percent") return `${n.toFixed(1)}%`;
    if(type==="number") return Number.isInteger(n)?n.toLocaleString():n.toFixed(1);
    return text(v);
  };

  function sectionHTML(section,data){
    const fields=Array.isArray(section.fields)?section.fields:[];
    const rows=Array.isArray(section.rows)?section.rows:[];
    const head=fields.map(f=>`<th class="${numberTypes.has(f.type)?"number":""}">${text(f.label||f.key)}</th>`).join("");
    const body=rows.map(row=>`<tr>${fields.map(f=>`<td class="${numberTypes.has(f.type)?"number":""}">${value(row[f.key],f.type,data.currency_symbol)}</td>`).join("")}</tr>`).join("");
    return `<section class="custom-report-section"><div class="custom-report-head"><div><strong>${text(section.report_name||"Report")}</strong><span>${Number(section.total_rows||rows.length)} rows</span></div></div><div class="custom-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div></section>`;
  }

  function resolveTheme(data){
    if(data.theme_mode==="custom") return data.screen_theme||null;
    const winner=data.winning_team||{};
    const state=data.theme_state||{};
    if(winner.team_id&&state.teams?.[String(winner.team_id)]) return state.teams[String(winner.team_id)];
    if(winner.team_name&&state.by_name) return state.by_name[String(winner.team_name).trim().toLowerCase()]||null;
    return null;
  }

  function applyTheme(data){
    document.querySelectorAll(".custom-screen-frame,.custom-screen-corner,.custom-screen-hero").forEach(el=>el.remove());
    document.body.classList.remove("custom-screen-themed");
    document.body.style.removeProperty("background-image");
    const theme=resolveTheme(data);
    if(!theme||theme.enabled===false) return;
    document.body.classList.add("custom-screen-themed");
    const colors=theme.colors||{};
    const vars={primary:"--custom-primary",primary_bright:"--custom-bright",background:"--custom-bg",panel:"--custom-panel",text:"--custom-text",muted:"--custom-muted"};
    Object.entries(vars).forEach(([key,name])=>{if(colors[key])document.documentElement.style.setProperty(name,colors[key]);});
    const assets=theme.assets||{};
    if(assets.background) document.body.style.backgroundImage=`linear-gradient(rgba(7,7,6,.84),rgba(7,7,6,.84)),url("${assets.background}")`;
    const frame=document.createElement("div");frame.className="custom-screen-frame";document.body.appendChild(frame);
    [["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]].forEach(([key,pos])=>{
      if(!assets[key])return;const img=document.createElement("img");img.className=`custom-screen-corner ${pos}`;img.src=assets[key];img.alt="";document.body.appendChild(img);
    });
    if(assets.hero){
      const first=document.querySelector("header>div:first-child");
      if(first){const img=document.createElement("img");img.className="custom-screen-hero";img.src=assets.hero;img.alt="Screen branding";first.prepend(img);}
    }
    const sections=[...document.querySelectorAll(".custom-report-section")];
    sections.forEach((section,index)=>{
      section.style.setProperty("--custom-row-image",assets.row?`url("${assets.row}")`:"none");
      section.style.setProperty("--custom-champion-image",assets.champion?`url("${assets.champion}")`:"none");
      const first=section.querySelector("tbody tr");if(first)first.classList.add("custom-screen-champion");
      section.querySelectorAll("tbody tr:not(:first-child)").forEach(row=>row.classList.add("custom-screen-row"));
    });
  }

  function customRender(data){
    titleEl.textContent=data.title||data.screen_name||"STATS";
    subtitleEl.textContent=data.subtitle||"";
    modeEl.textContent=data.screen_name||"CUSTOM SCREEN";
    const sections=Array.isArray(data.sections)?data.sections:[];
    scaleRoot.innerHTML=sections.length?`<div class="custom-screen-grid">${sections.map(s=>sectionHTML(s,data)).join("")}</div>`:`<div class="empty">No reports on this screen</div>`;
    applyTheme(data);
    fitLeaderboard();
  }

  if(!document.getElementById("customScreenStyles")){
    const style=document.createElement("style"); style.id="customScreenStyles";
    style.textContent=`
      :root{--custom-primary:#d8b34a;--custom-bright:#e6c760;--custom-bg:#080808;--custom-panel:#111;--custom-text:#f5f5f5;--custom-muted:#9c9c9c}
      .custom-screen-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(620px,100%),1fr));gap:14px;align-items:start;width:100%}
      .custom-report-section{min-width:0;border:1px solid var(--line);background:var(--panel)}
      .custom-report-head{padding:10px 12px;border-bottom:1px solid var(--line);background:var(--panel2)}
      .custom-report-head>div{display:flex;justify-content:space-between;gap:12px;align-items:center}.custom-report-head span{color:var(--muted);font-size:12px}
      .custom-table-wrap{overflow:hidden}.custom-report-section table{table-layout:auto}.custom-report-section th,.custom-report-section td{padding:7px 8px}
      body.custom-screen-themed{background-color:var(--custom-bg)!important;color:var(--custom-text)!important;background-size:cover!important;background-position:center!important}
      body.custom-screen-themed #title,body.custom-screen-themed .mode{color:var(--custom-bright)!important}body.custom-screen-themed .subtitle{color:var(--custom-muted)!important}
      body.custom-screen-themed .custom-report-section{border-color:var(--custom-primary)!important;background:var(--custom-panel)!important;color:var(--custom-text)!important}
      body.custom-screen-themed .custom-report-head{background:color-mix(in srgb,var(--custom-panel) 88%,black)!important;border-color:var(--custom-primary)!important}
      body.custom-screen-themed .custom-report-head strong{color:var(--custom-bright)!important}body.custom-screen-themed .custom-report-head span,body.custom-screen-themed th{color:var(--custom-muted)!important}
      body.custom-screen-themed tr.custom-screen-row td{background-image:linear-gradient(rgba(5,5,5,.56),rgba(5,5,5,.56)),var(--custom-row-image);background-size:100% 100%}
      body.custom-screen-themed tr.custom-screen-champion td{background-image:var(--custom-champion-image);background-size:100% 100%;border-top:2px solid var(--custom-bright);border-bottom:2px solid var(--custom-bright);font-weight:900}
      .custom-screen-frame{position:fixed;inset:10px;z-index:80;pointer-events:none;border:2px solid var(--custom-primary);box-shadow:inset 0 0 0 1px #000,inset 0 0 0 5px color-mix(in srgb,var(--custom-primary) 32%,transparent),inset 0 0 70px rgba(0,0,0,.72)}
      .custom-screen-corner{position:fixed;z-index:81;width:clamp(58px,7vw,120px);pointer-events:none;object-fit:contain}.custom-screen-corner.tl{top:6px;left:6px}.custom-screen-corner.tr{top:6px;right:6px}.custom-screen-corner.bl{bottom:6px;left:6px}.custom-screen-corner.br{bottom:6px;right:6px}
      .custom-screen-hero{display:block;max-height:clamp(72px,15vh,180px);max-width:min(56vw,900px);object-fit:contain;margin:0 18px 0 0}
    `; document.head.appendChild(style);
  }
  render=function(data){ if(data&&data.mode==="custom_screen") return customRender(data); return baseRender(data); };
})();
