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
  function customRender(data){
    titleEl.textContent=data.title||data.screen_name||"STATS";
    subtitleEl.textContent=data.subtitle||"";
    modeEl.textContent=data.screen_name||"CUSTOM SCREEN";
    const sections=Array.isArray(data.sections)?data.sections:[];
    scaleRoot.innerHTML=sections.length?`<div class="custom-screen-grid">${sections.map(s=>sectionHTML(s,data)).join("")}</div>`:`<div class="empty">No reports on this screen</div>`;
    fitLeaderboard();
  }
  if(!document.getElementById("customScreenStyles")){
    const style=document.createElement("style"); style.id="customScreenStyles";
    style.textContent=`
      .custom-screen-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(620px,100%),1fr));gap:14px;align-items:start;width:100%}
      .custom-report-section{min-width:0;border:1px solid var(--line);background:var(--panel)}
      .custom-report-head{padding:10px 12px;border-bottom:1px solid var(--line);background:var(--panel2)}
      .custom-report-head>div{display:flex;justify-content:space-between;gap:12px;align-items:center}.custom-report-head span{color:var(--muted);font-size:12px}
      .custom-table-wrap{overflow:hidden}.custom-report-section table{table-layout:auto}.custom-report-section th,.custom-report-section td{padding:7px 8px}
    `; document.head.appendChild(style);
  }
  render=function(data){ if(data&&data.mode==="custom_screen") return customRender(data); return baseRender(data); };
})();
