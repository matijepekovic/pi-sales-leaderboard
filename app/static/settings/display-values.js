/* Display Values are the normalized Report fields available to Screens. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const state={reports:[],inspections:new Map(),message:""};

  async function load(){
    const host=$("settingsDisplayValuesHost");if(host)host.innerHTML='<div class="card"><div class="small">Loading Display Values…</div></div>';
    try{
      const data=await R.api("/api/data/reports");state.reports=data.reports||[];state.inspections=new Map();
      await Promise.all(state.reports.map(async report=>{
        try{state.inspections.set(String(report.id),await R.api(`/api/data/reports/${encodeURIComponent(report.id)}/inspect`));}
        catch(error){state.inspections.set(String(report.id),{error:error.message||"Could not inspect Report.",fields:report.fields||[]});}
      }));state.message="";
    }catch(error){state.message=error.message||"Could not load Display Values.";}
    render();
  }

  function fieldCard(field){
    const key=String(field.key||""),label=String(field.label||key),values=field.sample_values||[];
    return `<div class="field-card"><div class="toolbar"><div><strong>${esc(label)}</strong><div class="field-key">Source field: ${esc(key)} · ${esc(field.type||"text")}</div></div><span class="chip">Display Value</span></div><div class="chips" style="margin-top:8px">${values.slice(0,30).map(value=>`<span class="chip">${esc(value)}</span>`).join("")||'<span class="small">No sample values</span>'}</div></div>`;
  }

  function reportCard(report){
    const inspection=state.inspections.get(String(report.id))||{},fields=inspection.fields||report.fields||[];
    return `<div class="card"><div class="toolbar"><div><h2>${esc(report.name||report.id)}</h2><div class="small">${Number(inspection.total_rows||0)} pulled rows · ${fields.length} Display Value${fields.length===1?"":"s"}</div></div><button class="btn" data-refresh-report="${esc(report.id)}">Reload</button></div>${inspection.error?`<div class="danger-text small" style="margin-top:10px">${esc(inspection.error)}</div>`:""}<div class="stack" style="margin-top:12px">${fields.map(fieldCard).join("")||'<div class="small">This Report has no pulled fields yet. Refresh it in Data.</div>'}</div></div>`;
  }

  function render(){
    const host=$("settingsDisplayValuesHost");if(!host)return;
    if(state.message){host.innerHTML=`<div class="card"><div class="danger-text">${esc(state.message)}</div><button class="btn" data-display-values-reload style="margin-top:12px">Reload</button></div>`;bind();return;}
    host.innerHTML=`<div class="card"><div class="toolbar"><div><h2>Display Values</h2><div class="small">Every field returned by a Report is a Display Value that a Screen can show, sort or rank by. Data Filters stay in Data because they control the pull.</div></div><button class="btn" data-display-values-reload>Reload All</button></div></div>${state.reports.map(reportCard).join("")||'<div class="card"><div class="small">No Reports yet. Add and pull a Report in Data first.</div></div>'}`;
    bind();
  }

  function bind(){
    const host=$("settingsDisplayValuesHost");if(!host)return;
    host.querySelectorAll("[data-display-values-reload]").forEach(button=>button.addEventListener("click",load));
    host.querySelectorAll("[data-refresh-report]").forEach(button=>button.addEventListener("click",async()=>{
      const id=button.dataset.refreshReport;button.disabled=true;
      try{state.inspections.set(String(id),await R.api(`/api/data/reports/${encodeURIComponent(id)}/inspect`));state.message="";}catch(error){state.message=error.message;}render();
    }));
  }

  R.on("section",id=>{if(id==="settingsDisplayValues")load();});R.on("data-changed",()=>{});
})();
