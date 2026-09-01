/* Data Settings owns Sources, Reports, Data Filters and pulled-data inspection. */
(function(){
  const runtime=window.StatsSettings,$=id=>document.getElementById(id),esc=runtime.esc;
  const state={sources:[],reports:[],values:[],activeSourceId:"",editor:null,inspection:null,columns:null,message:""};
  let loaded=false;

  const sourceBy=id=>state.sources.find(item=>String(item.id)===String(id))||null;
  const reportBy=id=>state.reports.find(item=>String(item.id)===String(id))||null;
  const selectedSource=()=>sourceBy(state.activeSourceId)||null;
  const sourceReports=()=>state.reports.filter(report=>String(report.source_id)===String(state.activeSourceId));
  const reportForValue=value=>sourceReports().find(report=>String(report.source_value||"")===String(value||""))||null;

  async function loadReportValues(quiet=false){
    const source=selectedSource();
    state.values=[];
    if(!source)return;
    if(!quiet){state.message="Loading Reports from Source…";render();}
    try{
      const data=await runtime.api(`/api/data/sources/${encodeURIComponent(source.id)}/report-values`);
      state.values=data.values||[];
      if(!quiet)state.message="";
    }catch(error){state.message=error.message;}
    if(!quiet)render();
  }

  async function load(){
    const [sources,reports]=await Promise.all([runtime.api("/api/data/sources"),runtime.api("/api/data/reports")]);
    state.sources=sources.sources||[];state.reports=reports.reports||[];
    if(!sourceBy(state.activeSourceId))state.activeSourceId=state.sources[0]?.id||"";
    await loadReportValues(true);loaded=true;render();
    runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
  }

  async function selectSource(id){
    if(!sourceBy(id))return;
    state.activeSourceId=id;state.editor=null;state.inspection=null;state.columns=null;state.message="";
    await loadReportValues(true);render();
  }

  function renderSourceMenu(){
    const host=$("settingsPageActions"),section=$("settingsData"),source=selectedSource(),hasTableau=state.sources.some(item=>item.adapter==="tableau");
    if(!host||!section?.classList.contains("active"))return;
    host.innerHTML=`<div class="row" style="justify-content:flex-end"><select id="dataSourcesMenu" aria-label="Sources" style="width:auto;min-width:210px">${state.sources.length?state.sources.map(item=>`<option value="${esc(item.id)}" ${item.id===state.activeSourceId?"selected":""}>${esc(item.name||"Source")}</option>`).join(""):'<option value="">No Sources</option>'}<option value="__new__">+ Add Source</option></select>${source?'<button id="dataEditSource" class="btn" type="button">Edit Source</button>':""}</div>`;
    $("dataSourcesMenu")?.addEventListener("change",async event=>{
      const value=event.target.value;
      if(value==="__new__"){
        event.target.value=state.activeSourceId||"";
        if(hasTableau){alert("Additional Sources are coming soon.");return;}
        openSource();return;
      }
      await selectSource(value);
    });
    $("dataEditSource")?.addEventListener("click",()=>openSource(state.activeSourceId));
  }

  function configuredReportCard(report,label=""){
    const detail=label&&label!==report.name?`<div class="small">${esc(label)}</div>`:"";
    return `<div class="subcard"><div class="toolbar"><div><strong>${esc(report.name||label||"Report")}</strong>${detail}<div class="small">${esc(report.status||"Not pulled yet")}${report.last_refresh?` · ${esc(report.last_refresh)}`:""}</div></div><div class="row"><button class="btn" data-action="inspect-report" data-id="${esc(report.id)}">View Data</button><button class="btn" data-action="refresh-report" data-id="${esc(report.id)}">Refresh</button><button class="btn" data-action="edit-report" data-id="${esc(report.id)}">Edit</button>${String(report.id).startsWith("report-")&&!['report-reps','report-products'].includes(report.id)?`<button class="btn danger" data-action="delete-report" data-id="${esc(report.id)}">Delete</button>`:""}</div></div></div>`;
  }

  function sourceValueCard(value){
    const report=reportForValue(value.id);
    if(report)return configuredReportCard(report,value.label);
    return `<div class="subcard"><div class="toolbar"><div><strong>${esc(value.label||"Report")}</strong><div class="small">Available from ${esc(selectedSource()?.name||"Source")}</div></div><button class="btn primary" data-action="add-report-value" data-value="${esc(value.id)}">Add</button></div></div>`;
  }

  function sourceEditor(){
    if(state.editor?.type!=="source")return"";const source=state.editor.value||{},c=source.connection||{},reports=source.id?state.reports.filter(report=>report.source_id===source.id):[];
    return `<div class="card"><div class="toolbar"><div><h2>${source.id?"Edit Source":"Add Source"}</h2><div class="small">Connection details stay inside the selected Source adapter.</div></div><button class="btn" data-action="close-editor">Close</button></div><div class="grid"><div><label>Name</label><input data-source="name" value="${esc(source.name||"Tableau")}"></div><div><label>Adapter</label><select data-source="adapter"><option value="tableau">Tableau</option></select></div><div><label>Server</label><input data-source="server" value="${esc(c.server||"")}" placeholder="https://tableau.example.com"></div><div><label>Site</label><input data-source="site" value="${esc(c.site||"")}"></div><div><label>PAT name</label><input data-source="pat_name" value="${esc(c.pat_name||"")}"></div><div><label>PAT secret</label><input type="password" data-source="secret" placeholder="${c.secret_configured?"Saved — leave blank to keep":"Enter secret"}"></div></div><div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-source">Save Source</button>${source.id?'<button class="btn" data-action="test-editor-source">Test Connection</button>':""}${source.id&&!reports.length?`<button class="btn danger" data-action="delete-source" data-id="${esc(source.id)}">Delete Source</button>`:""}</div>${source.id&&reports.length?`<div class="small" style="margin-top:10px">This Source is used by ${reports.length} Report${reports.length===1?"":"s"} and cannot be deleted.</div>`:""}</div>`;
  }

  function filterFieldOptions(filters,index){
    const current=filters[index]?.field||"",catalog=state.columns?.filter_fields||[];
    const items=catalog.map(item=>String(item.field||"")).filter(Boolean);if(current&&!items.includes(current))items.unshift(current);
    return `<option value="">Choose field…</option>${items.map(field=>`<option value="${esc(field)}" ${field===current?"selected":""}>${esc(field)}</option>`).join("")}`;
  }

  function filterValueControl(filters,index){
    const filter=filters[index]||{},entry=(state.columns?.filter_fields||[]).find(item=>String(item.field)===String(filter.field));
    const values=(entry?.values||[]).map(String),current=String(filter.value||"");
    if(values.length&&!entry?.truncated){const options=current&&!values.includes(current)?[current,...values]:values;return `<select data-data-filter-value="${index}"><option value="">Choose value…</option>${options.map(value=>`<option value="${esc(value)}" ${value===current?"selected":""}>${esc(value)}</option>`).join("")}</select>`;}
    return `<input data-data-filter-value="${index}" value="${esc(current)}" placeholder="Value">`;
  }

  function dataFilters(report){
    const filters=report.filters||[];
    return `<div class="subcard" style="margin-top:14px"><div class="toolbar"><div><strong>Data Filters</strong><div class="small">Filter the data pulled for this Report.</div></div><button class="btn" data-action="add-data-filter" ${state.columns?"":"disabled"}>+ Data Filter</button></div>${filters.length?filters.map((filter,index)=>`<div class="rule-row" style="grid-template-columns:1fr 1fr auto;margin-top:9px"><div><label>Field</label><select data-data-filter-field="${index}">${filterFieldOptions(filters,index)}</select></div><div><label>Value</label>${filterValueControl(filters,index)}</div><button class="btn danger" data-action="remove-data-filter" data-index="${index}">Remove</button></div>`).join(""):'<div class="small" style="margin-top:9px">No Data Filters.</div>'}</div>`;
  }

  function reportEditor(){
    if(state.editor?.type!=="report")return"";const report=state.editor.value,rt=report.runtime||(report.runtime={});
    const current=String(report.source_value||""),values=current&&!state.values.some(item=>String(item.id)===current)?[{id:current,label:report.name||current},...state.values]:state.values;
    return `<div class="card"><div class="toolbar"><div><h2>${report.id?"Edit Report":"Add Report"}</h2><div class="small">This Report comes from ${esc(selectedSource()?.name||"the selected Source")}.</div></div><button class="btn" data-action="close-editor">Close</button></div><div class="grid"><div><label>Name</label><input data-report="name" value="${esc(report.name||"Report")}"></div><div><label>Report</label><select data-report="source_value"><option value="">Choose Report…</option>${values.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===current?"selected":""}>${esc(item.label||item.id)}</option>`).join("")}</select></div><div><label>Date window</label><select data-report="date_mode"><option value="current_month" ${rt.date_mode!=="custom"?"selected":""}>Current month</option><option value="custom" ${rt.date_mode==="custom"?"selected":""}>Custom range</option></select></div><div><label>Start date</label><input type="date" data-report="date_start" value="${esc(rt.date_start||"")}"></div><div><label>End date</label><input type="date" data-report="date_end" value="${esc(rt.date_end||"")}"></div></div>${dataFilters(report)}${state.columns?`<div class="subcard" style="margin-top:14px"><strong>Fields returned by Source</strong><div class="chips">${(state.columns.choices||state.columns.headers||[]).slice(0,80).map(value=>`<span class="chip">${esc(value)}</span>`).join("")||'<span class="small">No fields returned.</span>'}</div></div>`:""}<div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-report">Save Report</button></div></div>`;
  }

  function inspection(){
    const item=state.inspection;if(!item)return"";const fields=item.fields||[],rows=item.sample_rows||[];
    return `<div class="card"><div class="toolbar"><div><h2>${esc(item.report_name||"Pulled Data")}</h2><div class="small">${Number(item.total_rows||0)} rows · ${esc(item.status||"")}${item.last_refresh?` · refreshed ${esc(item.last_refresh)}`:""}</div></div><button class="btn" data-action="close-inspection">Close</button></div><div class="data-table" style="margin-top:12px"><table><thead><tr>${fields.map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${fields.map(field=>`<td>${esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(fields.length,1)}">No pulled rows.</td></tr>`}</tbody></table></div><div class="stack" style="margin-top:12px">${fields.map(field=>`<div class="field-card"><strong>${esc(field.label||field.key)}</strong><div class="field-key">${esc(field.key)} · ${esc(field.type||"text")}</div><div class="chips">${(field.sample_values||[]).slice(0,40).map(value=>`<span class="chip">${esc(value)}</span>`).join("")||'<span class="small">No values</span>'}</div></div>`).join("")}</div></div>`;
  }

  function render(){
    const host=$("settingsDataHost");if(!host)return;const source=selectedSource();
    const unmatched=sourceReports().filter(report=>!state.values.some(value=>String(value.id)===String(report.source_value||"")));
    const reportsBody=!source?'<div class="small">Add a Source to see Reports.</div>':state.values.length?`${state.values.map(sourceValueCard).join("")}${unmatched.map(report=>configuredReportCard(report)).join("")}`:`${unmatched.map(report=>configuredReportCard(report)).join("")||'<div class="small">No Report values returned by this Source.</div>'}`;
    host.innerHTML=`${sourceEditor()}<div class="card"><div class="toolbar"><div><h2>Reports</h2><div class="small">Reports available from ${esc(source?.name||"the selected Source")}.</div></div>${source?'<button class="btn" data-action="reload-values">Reload</button>':""}</div><div class="stack" style="margin-top:12px">${reportsBody}</div></div>${reportEditor()}${inspection()}<div class="status">${esc(state.message||"")}</div>`;
    bind();renderSourceMenu();
  }

  function readSourceEditor(){
    const current=state.editor.value,c=current.connection||{};return {...current,name:hostValue('[data-source="name"]'),adapter:hostValue('[data-source="adapter"]')||'tableau',connection:{...c,server:hostValue('[data-source="server"]'),site:hostValue('[data-source="site"]'),pat_name:hostValue('[data-source="pat_name"]')},secret:hostValue('[data-source="secret"]')};
  }
  function hostValue(selector){return $("settingsDataHost")?.querySelector(selector)?.value||"";}
  function syncReport(){
    const report=state.editor.value,rt=report.runtime||(report.runtime={});
    report.name=hostValue('[data-report="name"]')||report.name;report.source_id=state.activeSourceId;report.source_value=hostValue('[data-report="source_value"]')||report.source_value;
    rt.date_mode=hostValue('[data-report="date_mode"]')||'current_month';rt.date_start=hostValue('[data-report="date_start"]');rt.date_end=hostValue('[data-report="date_end"]');
    $("settingsDataHost")?.querySelectorAll('[data-data-filter-field]').forEach(el=>{const i=Number(el.dataset.dataFilterField);if(report.filters?.[i])report.filters[i].field=el.value;});
    $("settingsDataHost")?.querySelectorAll('[data-data-filter-value]').forEach(el=>{const i=Number(el.dataset.dataFilterValue);if(report.filters?.[i])report.filters[i].value=el.value;});
    return report;
  }

  async function openSource(id){state.editor={type:"source",value:id?JSON.parse(JSON.stringify(sourceBy(id))):{name:"Tableau",adapter:"tableau",connection:{}}};state.columns=null;render();}
  async function openReport(id,valueId=""){
    const source=selectedSource();if(!source)return;
    const choice=state.values.find(item=>String(item.id)===String(valueId));
    const value=id?JSON.parse(JSON.stringify(reportBy(id))):{name:choice?.label||"Report",source_id:source.id,source_value:valueId,filters:[],runtime:{date_mode:"current_month"}};
    value.filters=Array.isArray(value.filters)?value.filters:[];
    state.editor={type:"report",value};state.columns=null;state.inspection=null;render();
    if(value.id)await loadColumnsForEditor();
  }

  async function loadColumnsForEditor(quiet=false){
    const report=state.editor?.type==="report"?state.editor.value:null;if(!report?.id)return;
    if(!quiet){state.message="Loading Report fields…";render();}
    try{state.columns=await runtime.api(`/api/data/reports/${encodeURIComponent(report.id)}/columns`,runtime.json("POST",{}));if(!quiet)state.message="";}catch(error){state.columns=null;if(!quiet)state.message=error.message;}
    render();
  }

  async function saveSource(){
    const payload=readSourceEditor();state.message="Saving Source…";render();
    try{const url=payload.id?`/api/data/sources/${encodeURIComponent(payload.id)}`:"/api/data/sources";const method=payload.id?"PUT":"POST";const data=await runtime.api(url,runtime.json(method,payload));state.activeSourceId=data.source?.id||state.activeSourceId;state.editor=null;state.message="Source saved.";await load();}catch(error){state.message=error.message;render();}
  }
  async function testSource(id,payload=null){state.message="Testing connection…";render();try{const source=payload||sourceBy(id);if(payload&&payload.id)await runtime.api(`/api/data/sources/${encodeURIComponent(payload.id)}`,runtime.json("PUT",payload));const data=await runtime.api(`/api/data/sources/${encodeURIComponent(source.id)}/test`,{method:"POST"});state.message=data.message||"Connected.";}catch(error){state.message=error.message;}render();}
  async function saveReport(){
    const payload=syncReport();if(!payload.source_value){state.message="Choose a Report from the selected Source.";render();return;}
    state.message="Saving Report…";render();
    try{
      const url=payload.id?`/api/data/reports/${encodeURIComponent(payload.id)}`:"/api/data/reports",method=payload.id?"PUT":"POST";
      const data=await runtime.api(url,runtime.json(method,payload)),savedId=data.report.id;
      let refreshError="";try{await runtime.api(`/api/data/reports/${encodeURIComponent(savedId)}/refresh`,{method:"POST"});}catch(error){refreshError=error.message;}
      const reports=await runtime.api("/api/data/reports");state.reports=reports.reports||[];
      const saved=reportBy(savedId);state.editor=saved?{type:"report",value:JSON.parse(JSON.stringify(saved))}:null;state.message=refreshError?`Report saved. Refresh failed: ${refreshError}`:"Report saved and refreshed.";
      if(state.editor)await loadColumnsForEditor(true);else render();
      runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
    }catch(error){state.message=error.message;render();}
  }
  async function inspectReport(id){state.message="Loading pulled data…";render();try{state.inspection=await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/inspect`);state.message="";}catch(error){state.message=error.message;}render();}
  async function refreshReport(id){state.message="Refreshing Report…";render();try{await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/refresh`,{method:"POST"});const reports=await runtime.api("/api/data/reports");state.reports=reports.reports||[];state.message="Report refreshed.";await inspectReport(id);}catch(error){state.message=error.message;render();}}

  function bind(){
    const host=$("settingsDataHost");if(!host)return;
    host.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",async()=>{
      const a=button.dataset.action,id=button.dataset.id,index=Number(button.dataset.index||0);
      if(a==="add-report-value")return openReport(null,button.dataset.value);if(a==="edit-report")return openReport(id);if(a==="close-editor"){state.editor=null;state.columns=null;render();return;}if(a==="close-inspection"){state.inspection=null;render();return;}
      if(a==="save-source")return saveSource();if(a==="test-editor-source")return testSource(state.editor.value.id,readSourceEditor());if(a==="save-report")return saveReport();if(a==="inspect-report")return inspectReport(id);if(a==="refresh-report")return refreshReport(id);if(a==="reload-values")return loadReportValues();
      if(a==="add-data-filter"){syncReport();(state.editor.value.filters||(state.editor.value.filters=[])).push({field:"",value:""});render();return;}if(a==="remove-data-filter"){syncReport();state.editor.value.filters.splice(index,1);render();return;}
      if(a==="delete-source"){if(!confirm("Delete this Source?"))return;try{await runtime.api(`/api/data/sources/${encodeURIComponent(id)}`,{method:"DELETE"});state.activeSourceId="";state.editor=null;state.message="Source deleted.";await load();}catch(error){state.message=error.message;render();}return;}
      if(a==="delete-report"){if(!confirm("Delete this Report?"))return;try{await runtime.api(`/api/data/reports/${encodeURIComponent(id)}`,{method:"DELETE"});state.message="Report deleted.";await load();}catch(error){state.message=error.message;render();}return;}
    }));
    host.querySelectorAll('[data-data-filter-field]').forEach(el=>el.addEventListener("change",()=>{syncReport();render();}));
  }

  runtime.on("section",id=>{if(id!=="settingsData"){if($("settingsPageActions"))$("settingsPageActions").innerHTML="";return;}if(!loaded)load().catch(error=>{state.message=error.message;render();});else renderSourceMenu();});
  runtime.on("unlocked",()=>{loaded=false;});
  runtime.on("request-data-refresh",()=>load().catch(()=>{}));
})();
