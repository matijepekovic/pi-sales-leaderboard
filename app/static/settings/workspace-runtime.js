export function createRuntime(){
  const state={sources:[],reports:[],filters:[],screens:[],display:{},inspections:new Map()};
  const listeners=new Set();

  async function api(url,options={}){
    const headers={...(options.headers||{})};
    if(options.body && !(options.body instanceof FormData)) headers["Content-Type"]="application/json";
    const response=await fetch(url,{cache:"no-store",...options,headers});
    let data={};
    try{data=await response.json();}catch(_){data={};}
    if(response.status===401&&data.locked){
      window.dispatchEvent(new CustomEvent("stats-settings-locked"));
      throw new Error("Settings are locked.");
    }
    if(!response.ok||data.ok===false) throw new Error(data.error||`Request failed (${response.status})`);
    return data;
  }

  function emit(){for(const fn of listeners)fn(state);}
  function subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);}
  function json(method,body){return{method,body:JSON.stringify(body||{})};}
  function esc(value){return String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));}
  function clone(value){return JSON.parse(JSON.stringify(value));}
  function report(id){return state.reports.find(item=>item.id===id)||null;}
  function filter(id){return state.filters.find(item=>item.id===id)||null;}
  function screen(id){return state.screens.find(item=>item.id===id)||null;}
  function source(id){return state.sources.find(item=>item.id===id)||null;}

  async function reload(){
    const [sources,reports,filters,screens,display]=await Promise.all([
      api("/api/data/sources"),api("/api/data/reports"),api("/api/filters"),api("/api/screens"),api("/api/display")
    ]);
    state.sources=sources.sources||[];
    state.reports=reports.reports||[];
    state.filters=filters.filters||[];
    state.screens=screens.screens||[];
    state.display=display||{};
    emit();
    return state;
  }

  async function inspect(reportId,force=false){
    if(!reportId)return null;
    if(!force&&state.inspections.has(reportId))return state.inspections.get(reportId);
    const data=await api(`/api/data/reports/${encodeURIComponent(reportId)}/inspect`);
    state.inspections.set(reportId,data);
    return data;
  }

  function invalidateReport(reportId){if(reportId)state.inspections.delete(reportId);}

  return {state,api,json,esc,clone,reload,inspect,invalidateReport,subscribe,report,filter,screen,source};
}

export function tableHtml(runtime,inspection,maxRows=12){
  if(!inspection)return'<div class="empty">No pulled data yet.</div>';
  const fields=inspection.fields||[];
  const rows=(inspection.sample_rows||inspection.rows||[]).slice(0,maxRows);
  if(!fields.length)return'<div class="empty">No fields yet. Pull the Report first.</div>';
  const head=fields.map(field=>`<th>${runtime.esc(field.label||field.key)}</th>`).join("");
  const body=rows.map(row=>`<tr>${fields.map(field=>`<td>${runtime.esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body||`<tr><td colspan="${fields.length}">No rows.</td></tr>`}</tbody></table></div>`;
}

export function renderPayload(runtime,payload){
  if(!payload||payload.mode==="empty")return'<div class="empty">No Screen configured.</div>';
  const sections=payload.sections||[];
  return `<div class="preview">${sections.map(section=>{
    const fields=section.fields||[];
    const rows=section.rows||[];
    const head=fields.map(field=>`<th>${runtime.esc(field.label||field.key)}</th>`).join("");
    const body=rows.map(row=>`<tr>${fields.map(field=>`<td>${runtime.esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("");
    return `<div class="section-preview"><div class="toolbar"><div><strong>${runtime.esc(section.report_name||section.report_id)}</strong><div class="meta">${section.total_rows??rows.length} matching rows</div></div></div><div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body||`<tr><td colspan="${Math.max(fields.length,1)}">No matching rows.</td></tr>`}</tbody></table></div></div>`;
  }).join("")||'<div class="empty">This Screen has no tables yet.</div>'}</div>`;
}
