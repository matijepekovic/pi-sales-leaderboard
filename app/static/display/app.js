(function(){
  const root=document.getElementById("statsDisplay");
  let lastSignature="";

  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

  function format(value,type){
    if(value===null||value===undefined||value==="")return"";
    if(type==="number"){
      const num=Number(String(value).replace(/,/g,""));return Number.isFinite(num)?num.toLocaleString(undefined,{maximumFractionDigits:2}):String(value);
    }
    if(type==="currency"){
      const num=Number(String(value).replace(/[$,]/g,""));return Number.isFinite(num)?num.toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:0}):String(value);
    }
    if(type==="percent"){
      const raw=String(value);if(raw.includes("%"))return raw;const num=Number(raw.replace(/,/g,""));return Number.isFinite(num)?`${num.toLocaleString(undefined,{maximumFractionDigits:1})}%`:raw;
    }
    return String(value);
  }

  function applyTheme(theme){
    const colors=theme?.colors||{};
    const vars={background:"--background",panel:"--panel",text:"--text",muted:"--muted",primary:"--primary",primary_bright:"--primary-bright",primary_dark:"--primary-dark",secondary:"--secondary",champion_text:"--champion-text"};
    for(const [key,name] of Object.entries(vars)){if(colors[key])document.documentElement.style.setProperty(name,colors[key]);}
    document.body.style.backgroundImage=theme?.assets?.background?`url("${theme.assets.background}")`:"none";
  }

  function sectionHtml(section,theme){
    const fields=section.fields||[];const rows=section.rows||[];
    const rowAsset=theme?.assets?.row||"";const championAsset=theme?.assets?.champion||"";
    const body=rows.map((row,index)=>{
      const asset=index===0?championAsset:rowAsset;
      const style=asset?` style="background-image:linear-gradient(rgba(0,0,0,.12),rgba(0,0,0,.12)),url('${esc(asset)}')"`:"";
      return `<tr${style}>${fields.map(field=>`<td title="${esc(row[field.key]??"")}">${esc(format(row[field.key],field.type))}</td>`).join("")}</tr>`;
    }).join("");
    return `<section class="report-section"><div class="report-heading"><div class="report-name">${esc(section.report_name||section.report_id)}</div><div class="report-count">${Number(section.total_rows||rows.length)} rows</div></div><div class="table-viewport"><table class="stats-table"><thead><tr>${fields.map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${body||`<tr><td colspan="${Math.max(fields.length,1)}">No matching rows</td></tr>`}</tbody></table></div></section>`;
  }

  function render(payload){
    applyTheme(payload.theme);
    if(!payload||payload.mode==="empty"||!payload.screen_id){
      root.innerHTML='<div class="display-shell"><div class="empty">No Screen configured.<br><span style="font-size:.55em">Open Settings → Screens to create one.</span></div></div>';
      return;
    }
    const filters=(payload.display_filters||[]).map(filter=>`<span class="filter-pill">${esc(filter.name)}</span>`).join("");
    const hero=payload.theme?.assets?.hero||"";
    root.innerHTML=`<div class="display-shell"><header class="display-header" ${hero?`style="background-image:linear-gradient(rgba(0,0,0,.32),rgba(0,0,0,.32)),url('${esc(hero)}')"`:""}><div class="display-title">${esc(payload.screen_name||"Stats")}</div><div class="display-filters">${filters}</div></header><main class="sections">${(payload.sections||[]).map(section=>sectionHtml(section,payload.theme)).join("")||'<div class="empty">This Screen has no data to display.</div>'}</main></div>`;
  }

  async function refresh(){
    try{
      const response=await fetch("/api/display/render",{cache:"no-store"});
      const data=await response.json();
      if(!response.ok||data.ok===false)throw new Error(data.error||"Could not load Display.");
      const payload=data.payload||{};
      const signature=JSON.stringify(payload);
      if(signature!==lastSignature){lastSignature=signature;render(payload);}
    }catch(error){
      root.innerHTML=`<div class="display-shell"><div class="empty error">${esc(error.message||"Display unavailable")}</div></div>`;
    }
  }

  refresh();
  setInterval(refresh,3000);
})();
