/* Data Settings owns Sources, Reports, Data Filters and pulled-data inspection. */
(function(){
  const runtime=window.StatsSettings,$=id=>document.getElementById(id),esc=runtime.esc;
  const state={sources:[],reports:[],editor:null,inspection:null,columns:null,message:""};
  let loaded=false;

  const sourceBy=id=>state.sources.find(item=>String(item.id)===String(id))||null;
  const reportBy=id=>state.reports.find(item=>String(item.id)===String(id))||null;
  const selectedSource=()=>sourceBy(state.editor?.value?.source_id)||state.sources[0]||null;

  async function load(){
    const [sources,reports]=await Promise.all([runtime.api("/api/data/sources"),runtime.api("/api/data/reports")]);
    state.sources=sources.sources||[];state.reports=reports.reports||[];loaded=true;render();
    runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
  }

  function renderSourceMenu(){
    const host=$("settingsPageActions"),section=$("settingsData");
    if(!host||!section?.classList.contains("active"))return;
    host.innerHTML=`<select id="dataSourcesMenu" aria-label="Sources" style="width:auto;min-width:190px"><option value="">Sources</option>${state.sources.map(source=>`<option value="${esc(source.id)}">${esc(source.name||"Source")}</option>`).join("")}<option value="__new__">+ Add Source</option></select>`;
    $("dataSourcesMenu")?.addEventListener("change",event=>{const value=event.target.value;event.target.value="";if(value==="__new__")openSource();else if(value)openSource(value);});
  }

  function reportCard(report){
    return `<div class="subcard"><div class="toolbar"><div><strong>${esc(report.name||"Report")}</strong><div class="small">${esc(sourceBy(report.source_id)?.name||report.source_id)} · ${esc(report.kind||"table")}</div><div class="small">${esc(report.status||"Not pulled yet")}${report.last_refresh?` · ${esc(report.last_refresh)}`:""}</div></div><div class="row"><button class="btn" data-action="inspect-report" data-id="${esc(report.id)}">View Data</button><button class="btn" data-action="refresh-report" data-id="${esc(report.id)}">Refresh</button><button class="btn" data-action="edit-report" data-id="${esc(report.id)}">Edit</button>${String(report.id).startsWith("report-")&&!['report-reps','report-products'].includes(report.id)?`<button class="btn danger" data-action="delete-report" data-id="${esc(report.id)}">Delete</button>`:""}</div></div></div>`;
  }

  function sourceEditor(){
    if(state.editor?.type!=="source")return"";const source=state.editor.value||{},c=source.connection||{},reports=source.id?state.reports.filter(report=>report.source_id===source.id):[];
    return `<div class="card"><div class="toolbar"><div><h2>${source.id?"Edit Source":"Add Source"}</h2><div class="small">Connection details stay inside the selected Source adapter.</div></div><button class="btn" data-action="close-editor">Close</button></div><div class="grid"><div><label>Name</label><input data-source="name" value="${esc(source.name||"Tableau")}"></div><div><label>Adapter</label><select data-source="adapter"><option value="tableau">Tableau</option></select></div><div><label>Server</label><input data-source="server" value="${esc(c.server||"")}" placeholder="https://tableau.example.com"></div><div><label>Site</label><input data-source="site" value="${esc(c.site||"")}"></div><div><label>PAT name</label><input data-source="pat_name" value="${esc(c.pat_name||"")}"></div><div><label>PAT secret</label><input type="password" data-source="secret" placeholder="${c.secret_configured?"Saved — leave blank to keep":"Enter secret"}"></div></div><div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-source">Save Source</button>${source.id?'<button class="btn" data-action="test-editor-source">Test Connection</button>':""}${source.id&&!reports.length?`<button class="btn danger" data-action="delete-source" data-id="${esc(source.id)}">Delete Source</button>`:""}</div>${source.id&&reports.length?`<div class="small" style="margin-top:10px">This Source is used by ${reports.length} Report${reports.length===1?"":"s"} and cannot be deleted.</div>`:""}</div>`;
  }

  function filterFieldOptions(filters,index){
    const current=filters[index]?.field||"";const catalog=state.columns?.filter_fields||[];
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
    const filters=report.source_config?.filters||[];
    return `<div class="subcard" style="margin-top:14px"><div class="toolbar"><div><strong>Data Filters</strong><div class="small">These are the only Filters in Stats. They change what the Source pulls.</div></div><button class="btn" data-action="add-data-filter" ${state.columns?"":"disabled"}>+ Data Filter</button></div>${filters.length?filters.map((filter,index)=>`<div class="rule-row" style="grid-template-columns:1fr 1fr auto;margin-top:9px"><div><label>Source field</label><select data-data-filter-field="${index}">${filterFieldOptions(filters,index)}</select></div><div><label>Value</label>${filterValueControl(filters,index)}</div><button class="btn danger" data-action="remove-data-filter" data-index="${index}">Remove</button></div>`).join(""):'<div class="small" style="margin-top:9px">No Data Filters.</div>'}</div>`;
  }

  function reportEditor(){
    if(state.editor?.type!=="report")return"";const report=state.editor.value,config=report.source_config||(report.source_config={}),rt=report.runtime||(report.runtime={});
    const source=selectedSource(),workbooks=state.editor.workbooks||[],views=state.editor.views||[];
    return `<div class="card"><div class="toolbar"><div><h2>${report.id?"Edit Report":"Add Report"}</h2><div class="small">A Report is normalized data Stats can pull and reuse.</div></div><button class="btn" data-action="close-editor">Close</button></div><div class="grid"><div><label>Name</label><input data-report="name" value="${esc(report.name||"New Report")}"></div><div><label>Source</label><select data-report="source_id">${state.sources.map(item=>`<option value="${esc(item.id)}" ${item.id===report.source_id?"selected":""}>${esc(item.name)}</option>`).join("")}</select></div><div><label>Workbook</label><select data-report="workbook"><option value="">Choose workbook…</option>${workbooks.map(item=>{const value=String(item.content_url||item.id||item.name||"");return `<option value="${esc(value)}" ${value===config.workbook?"selected":""}>${esc(item.name||value)}</option>`}).join("")}</select></div><div><label>Report / View</label><select data-report="sheet"><option value="">Choose report…</option>${views.map(item=>{const value=String(item.content_url||item.view_url_name||item.name||"").split('/').pop();return `<option value="${esc(value)}" ${value===config.sheet?"selected":""}>${esc(item.name||value)}</option>`}).join("")}</select></div><div><label>Export</label><select data-report="export"><option value="auto" ${config.export==="auto"?"selected":""}>Auto</option><option value="csv" ${config.export==="csv"?"selected":""}>CSV</option><option value="crosstab" ${config.export==="crosstab"?"selected":""}>Crosstab</option></select></div><div><label>Date window</label><select data-report="date_mode"><option value="current_month" ${rt.date_mode!=="custom"?"selected":""}>Current month</option><option value="custom" ${rt.date_mode==="custom"?"selected":""}>Custom range</option></select></div><div><label>Start date</label><input type="date" data-report="date_start" value="${esc(rt.date_start||"")}"></div><div><label>End date</label><input type="date" data-report="date_end" value="${esc(rt.date_end||"")}"></div></div><div class="row" style="margin-top:14px"><button class="btn" data-action="load-workbooks">Reload Workbooks</button>${report.id?'<button class="btn" data-action="read-report">Read Report Fields</button>':""}</div>${dataFilters(report)}${state.columns?`<div class="subcard" style="margin-top:14px"><strong>Fields returned by Source</strong><div class="chips">${(state.columns.choices||state.columns.headers||[]).slice(0,80).map(value=>`<span class="chip">${esc(value)}</span>`).join("")||'<span class="small">No fields returned.</span>'}</div></div>`:""}<div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-report">Save Report</button>${report.id?'<button class="btn" data-action="test-report">Test Pull</button>':""}</div></div>`;
  }

  function inspection(){
    const item=state.inspection;if(!item)return"";const fields=item.fields||[],rows=item.sample_rows||[];
    return `<div class="card"><div class="toolbar"><div><h2>${esc(item.report_name||"Pulled Data")}</h2><div class="small">${Number(item.total_rows||0)} rows · ${esc(item.status||"")}${item.last_refresh?` · refreshed ${esc(item.last_refresh)}`:""}</div></div><button class="btn" data-action="close-inspection">Close</button></div><div class="data-table" style="margin-top:12px"><table><thead><tr>${fields.map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${fields.map(field=>`<td>${esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(fields.length,1)}">No pulled rows.</td></tr>`}</tbody></table></div><div class="stack" style="margin-top:12px">${fields.map(field=>`<div class="field-card"><strong>${esc(field.label||field.key)}</strong><div class="field-key">${esc(field.key)} · ${esc(field.type||"text")}</div><div class="chips">${(field.sample_values||[]).slice(0,40).map(value=>`<span class="chip">${esc(value)}</span>`).join("")||'<span class="small">No values</span>'}</div></div>`).join("")}</div></div>`;
  }

  function render(){
    const host=$("settingsDataHost");if(!host)return;
    host.innerHTML=`${sourceEditor()}<div class="card"><div class="toolbar"><div><h2>Reports</h2><div class="small">Pulled datasets whose fields become Display Values for Screens.</div></div><button class="btn primary" data-action="new-report" ${state.sources.length?"":"disabled"}>+ Report</button></div><div class="stack" style="margin-top:12px">${state.reports.map(reportCard).join("")||'<div class="small">No Reports yet.</div>'}</div></div>${reportEditor()}${inspection()}<div class="status">${esc(state.message||"")}</div>`;
    bind();renderSourceMenu();
  }

  function readSourceEditor(){
    const current=state.editor.value,c=current.connection||{};return {...current,name:hostValue('[data-source="name"]'),adapter:hostValue('[data-source="adapter"]')||'tableau',connection:{...c,server:hostValue('[data-source="server"]'),site:hostValue('[data-source="site"]'),pat_name:hostValue('[data-source="pat_name"]')},secret:hostValue('[data-source="secret"]')};
  }
  function hostValue(selector){return $("settingsDataHost")?.querySelector(selector)?.value||"";}
  function syncReport(){
    const report=state.editor.value,config=report.source_config||(report.source_config={}),rt=report.runtime||(report.runtime={});
    report.name=hostValue('[data-report="name"]')||report.name;report.source_id=hostValue('[data-report="source_id"]')||report.source_id;config.workbook=hostValue('[data-report="workbook"]');config.sheet=hostValue('[data-report="sheet"]');config.export=hostValue('[data-report="export"]')||'auto';rt.date_mode=hostValue('[data-report="date_mode"]')||'current_month';rt.date_start=hostValue('[data-report="date_start"]');rt.date_end=hostValue('[data-report="date_end"]');
    $("settingsDataHost")?.querySelectorAll('[data-data-filter-field]').forEach(el=>{const i=Number(el.dataset.dataFilterField);if(config.filters?.[i])config.filters[i].field=el.value;});
    $("settingsDataHost")?.querySelectorAll('[data-data-filter-value]').forEach(el=>{const i=Number(el.dataset.dataFilterValue);if(config.filters?.[i])config.filters[i].value=el.value;});
    return report;
  }

  async function openSource(id){state.editor={type:"source",value:id?JSON.parse(JSON.stringify(sourceBy(id))):{name:"Tableau",adapter:"tableau",connection:{}}};state.columns=null;render();}
  async function openReport(id){
    const value=id?JSON.parse(JSON.stringify(reportBy(id))):{name:"New Report",source_id:state.sources[0]?.id||"",kind:"table",source_config:{export:"auto",filters:[]},runtime:{date_mode:"current_month"}};
    state.editor={type:"report",value,workbooks:[],views:[]};state.columns=null;await loadWorkbooks(true);render();
  }

  async function loadWorkbooks(quiet=false){
    if(state.editor?.type!=="report")return;syncReport();const source=selectedSource();if(!source)return;
    if(!quiet)state.message="Loading workbooks…";
    try{const data=await runtime.api(`/api/data/sources/${encodeURIComponent(source.id)}/workbooks`);state.editor.workbooks=data.workbooks||[];await loadViews(true);state.message="";}catch(error){state.message=error.message;}
    if(!quiet)render();
  }
  async function loadViews(quiet=false){
    const source=selectedSource(),workbook=state.editor?.value?.source_config?.workbook;if(!source||!workbook){if(state.editor)state.editor.views=[];return;}
    try{const data=await runtime.api(`/api/data/sources/${encodeURIComponent(source.id)}/workbooks/${encodeURIComponent(workbook)}/views`);state.editor.views=data.views||[];}catch(error){state.editor.views=[];if(!quiet)state.message=error.message;}
  }

  async function readColumns(){
    const report=syncReport();if(!report.id){state.message="Save the Report first, then read its fields.";render();return;}
    state.message="Reading source fields…";render();
    try{const body={...(report.source_config||{}),...(report.runtime||{})};state.columns=await runtime.api(`/api/data/reports/${encodeURIComponent(report.id)}/columns`,runtime.json("POST",body));state.message="Fields loaded.";}catch(error){state.message=error.message;}
    render();
  }

  async function saveSource(){
    const payload=readSourceEditor();state.message="Saving Source…";render();
    try{const url=payload.id?`/api/data/sources/${encodeURIComponent(payload.id)}`:"/api/data/sources";const method=payload.id?"PUT":"POST";await runtime.api(url,runtime.json(method,payload));state.editor=null;state.message="Source saved.";await load();}catch(error){state.message=error.message;render();}
  }
  async function testSource(id,payload=null){state.message="Testing connection…";render();try{const source=payload||sourceBy(id);if(payload&&payload.id)await runtime.api(`/api/data/sources/${encodeURIComponent(payload.id)}`,runtime.json("PUT",payload));const data=await runtime.api(`/api/data/sources/${encodeURIComponent(source.id)}/test`,{method:"POST"});state.message=data.message||"Connected.";}catch(error){state.message=error.message;}render();}
  async function saveReport(){
    const payload=syncReport();state.message="Saving Report…";render();
    try{const url=payload.id?`/api/data/reports/${encodeURIComponent(payload.id)}`:"/api/data/reports";const method=payload.id?"PUT":"POST";const data=await runtime.api(url,runtime.json(method,payload));state.editor={type:"report",value:JSON.parse(JSON.stringify(data.report)),workbooks:state.editor.workbooks||[],views:state.editor.views||[]};state.message="Report saved.";await load();}catch(error){state.message=error.message;render();}
  }
  async function inspectReport(id){state.message="Loading pulled data…";render();try{state.inspection=await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/inspect`);state.message="";}catch(error){state.message=error.message;}render();}
  async function refreshReport(id){state.message="Refreshing Report…";render();try{await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/refresh`,{method:"POST"});state.message="Report refreshed.";await load();await inspectReport(id);}catch(error){state.message=error.message;render();}}
  async function testReport(){const report=syncReport();state.message="Testing pull…";render();try{const data=await runtime.api(`/api/data/reports/${encodeURIComponent(report.id)}/preview`,runtime.json("POST",{...(report.source_config||{}),...(report.runtime||{})}));const preview=data.preview||data;const fields=preview.fields||[];const rows=preview.rows||data.rows||[];state.inspection={report_id:report.id,report_name:report.name,fields,sample_rows:rows.slice(0,20),total_rows:rows.length,status:"Test pull — not saved",last_refresh:""};state.message="Test pull succeeded.";}catch(error){state.message=error.message;}render();}

  function bind(){
    const host=$("settingsDataHost");if(!host)return;
    host.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",async()=>{
      const a=button.dataset.action,id=button.dataset.id,index=Number(button.dataset.index||0);
      if(a==="new-source")return openSource();if(a==="edit-source")return openSource(id);if(a==="new-report")return openReport();if(a==="edit-report")return openReport(id);if(a==="close-editor"){state.editor=null;state.columns=null;render();return;}if(a==="close-inspection"){state.inspection=null;render();return;}
      if(a==="save-source")return saveSource();if(a==="test-source")return testSource(id);if(a==="test-editor-source")return testSource(state.editor.value.id,readSourceEditor());if(a==="save-report")return saveReport();if(a==="inspect-report")return inspectReport(id);if(a==="refresh-report")return refreshReport(id);if(a==="read-report")return readColumns();if(a==="load-workbooks")return loadWorkbooks();if(a==="test-report")return testReport();
      if(a==="add-data-filter"){syncReport();(state.editor.value.source_config.filters||(state.editor.value.source_config.filters=[])).push({field:"",value:""});render();return;}if(a==="remove-data-filter"){syncReport();state.editor.value.source_config.filters.splice(index,1);render();return;}
      if(a==="delete-source"){if(!confirm("Delete this Source?"))return;try{await runtime.api(`/api/data/sources/${encodeURIComponent(id)}`,{method:"DELETE"});state.editor=null;state.message="Source deleted.";await load();}catch(error){state.message=error.message;render();}return;}
      if(a==="delete-report"){if(!confirm("Delete this Report?"))return;try{await runtime.api(`/api/data/reports/${encodeURIComponent(id)}`,{method:"DELETE"});state.message="Report deleted.";await load();}catch(error){state.message=error.message;render();}return;}
    }));
    host.querySelector('[data-report="source_id"]')?.addEventListener("change",async event=>{syncReport();state.editor.value.source_id=event.target.value;state.editor.value.source_config.workbook="";state.editor.value.source_config.sheet="";await loadWorkbooks();});
    host.querySelector('[data-report="workbook"]')?.addEventListener("change",async event=>{syncReport();state.editor.value.source_config.workbook=event.target.value;state.editor.value.source_config.sheet="";await loadViews();render();});
  }

  runtime.on("section",id=>{if(id!=="settingsData"){if($("settingsPageActions"))$("settingsPageActions").innerHTML="";return;}if(!loaded)load().catch(error=>{state.message=error.message;render();});else renderSourceMenu();});
  runtime.on("unlocked",()=>{loaded=false;});
  runtime.on("request-data-refresh",()=>load().catch(()=>{}));
})();
