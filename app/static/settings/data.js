/* Data Settings owns Sources, Reports, Data Filters and pulled-data inspection. */
(function(){
  const runtime=window.StatsSettings,$=id=>document.getElementById(id),esc=runtime.esc;
  const state={
    sources:[],reports:[],values:[],activeSourceId:"",editor:null,inspection:null,
    columns:null,message:"",valuesError:"",reportSearch:"",availableReportsOpen:false,inspectionFieldKey:"",duplicateCheck:null
  };
  const UPDATE_INTERVALS=[[0,"Manual only"],[5,"Every 5 minutes"],[15,"Every 15 minutes"],[30,"Every 30 minutes"],[60,"Every hour"],[120,"Every 2 hours"],[240,"Every 4 hours"],[480,"Every 8 hours"],[720,"Every 12 hours"],[1440,"Every day"]];
  let loaded=false,loadPromise=null;

  const sourceBy=id=>state.sources.find(item=>String(item.id)===String(id))||null;
  const reportBy=id=>state.reports.find(item=>String(item.id)===String(id))||null;
  const selectedSource=()=>sourceBy(state.activeSourceId)||null;
  const sourceReports=()=>state.reports.filter(report=>String(report.source_id)===String(state.activeSourceId));
  const reportForValue=value=>sourceReports().find(report=>String(report.source_value||"")===String(value||""))||null;
  const updateIntervalOptions=value=>UPDATE_INTERVALS.map(([minutes,label])=>`<option value="${minutes}" ${Number(value||0)===minutes?"selected":""}>${label}</option>`).join("");
  const updateIntervalLabel=value=>UPDATE_INTERVALS.find(([minutes])=>minutes===Number(value||0))?.[1]||`Every ${Number(value||0)} minutes`;

  async function loadReportValues(quiet=false){
    const source=selectedSource();
    state.values=[];
    state.valuesError="";
    if(!source)return;
    if(!quiet){state.message="Loading Reports from Source…";render();}
    try{
      const data=await runtime.api(`/api/data/sources/${encodeURIComponent(source.id)}/report-values`);
      state.values=data.values||[];
      if(!quiet)state.message="";
    }catch(error){state.valuesError=error.message;if(!quiet)state.message="";}
    if(!quiet)render();
  }

  async function load(){
    if(loadPromise)return loadPromise;
    loadPromise=(async()=>{
      const [sources,reports]=await Promise.all([runtime.api("/api/data/sources"),runtime.api("/api/data/reports")]);
      state.sources=sources.sources||[];
      state.reports=reports.reports||[];
      if(!sourceBy(state.activeSourceId))state.activeSourceId=state.sources[0]?.id||"";
      await loadReportValues(true);
      loaded=true;
      render();
      runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
    })();
    try{return await loadPromise;}finally{loadPromise=null;}
  }

  async function selectSource(id){
    if(!sourceBy(id))return;
    state.activeSourceId=id;
    state.editor=null;
    state.inspection=null;
    state.columns=null;
    state.inspectionFieldKey="";
    state.duplicateCheck=null;
    state.message="";
    state.reportSearch="";
    state.availableReportsOpen=false;
    await loadReportValues(true);
    render();
  }

  function renderSourceMenu(){
    const host=$("settingsPageActions"),section=$("settingsData"),source=selectedSource();
    const hasTableau=state.sources.some(item=>item.adapter==="tableau");
    if(!host||!section?.classList.contains("active"))return;
    host.innerHTML=`<div class="row" style="justify-content:flex-end"><select id="dataSourcesMenu" aria-label="Sources" style="width:auto;min-width:210px">${state.sources.length?state.sources.map(item=>`<option value="${esc(item.id)}" ${item.id===state.activeSourceId?"selected":""}>${esc(item.name||"Source")}</option>`).join(""):'<option value="">No Sources</option>'}<option value="__new__">+ Add Source</option></select>${source?'<button id="dataEditSource" class="btn" type="button">Edit Source</button>':""}</div>`;
    $("dataSourcesMenu")?.addEventListener("change",async event=>{
      const value=event.target.value;
      if(value==="__new__"){
        event.target.value=state.activeSourceId||"";
        if(hasTableau){alert("Additional Sources are coming soon.");return;}
        openSource();
        return;
      }
      await selectSource(value);
    });
    $("dataEditSource")?.addEventListener("click",()=>openSource(state.activeSourceId));
  }

  function configuredReportCard(report,label=""){
    const detail=label&&label!==report.name?`<div class="small">${esc(label)}</div>`:"";
    const interval=report.runtime?.update_interval_minutes||0;
    const expanded=String(state.inspection?.report_id||"")===String(report.id);
    const editing=state.editor?.type==="report"&&String(state.editor.value?.id||"")===String(report.id);
    const actions=editing?"":`<div class="row"><label class="small" style="display:flex;align-items:center;gap:6px">Updates <select data-report-update-interval data-id="${esc(report.id)}" aria-label="Update interval for ${esc(report.name||label||"Report")}" style="width:auto">${updateIntervalOptions(interval)}</select></label><button class="btn" data-action="inspect-report" data-id="${esc(report.id)}">${expanded?"Hide Data":"View Data"}</button><button class="btn" data-action="refresh-report" data-id="${esc(report.id)}">Refresh now</button><button class="btn" data-action="edit-report" data-id="${esc(report.id)}">Edit</button>${String(report.id).startsWith("report-")&&!['report-reps','report-products'].includes(report.id)?`<button class="btn danger" data-action="delete-report" data-id="${esc(report.id)}">Delete</button>`:""}</div>`;
    return `<div class="subcard" data-saved-report="${esc(report.id)}"><div class="toolbar"><div><strong>${esc(report.name||label||"Report")}</strong>${detail}<div class="small">${esc(report.status||"Not pulled yet")}${report.last_refresh?` · ${esc(report.last_refresh)}`:""}</div></div>${actions}</div>${reportInspection(report)}${reportEditor(report.id)}</div>`;
  }

  function sourceValueCard(value){
    const editing=state.editor?.type==="report"&&!state.editor.value?.id&&String(state.editor.value?.source_value||"")===String(value.id);
    return `<div class="subcard"><div class="toolbar"><div><strong>${esc(value.label||"Report")}</strong><div class="small">Available from ${esc(selectedSource()?.name||"Source")}</div></div>${editing?"":`<button class="btn primary" data-action="add-report-value" data-value="${esc(value.id)}">Add</button>`}</div>${editing?`<div data-editing-report>${reportEditor("",value.id)}</div>`:""}</div>`;
  }

  function savedReportBrowser(){
    const reports=sourceReports().slice().sort((a,b)=>String(a.name||"").localeCompare(String(b.name||""),undefined,{sensitivity:"base"}));
    if(!reports.length)return '<div class="small">No saved Reports for this Source.</div>';
    return `<div class="stack">${reports.map(report=>{
      const value=state.values.find(item=>String(item.id)===String(report.source_value||""));
      return configuredReportCard(report,value?.label||"");
    }).join("")}</div>`;
  }

  function reportBrowser(){
    const source=selectedSource();
    if(!source)return '<div class="small">Add a Source to see Reports.</div>';
    if(state.valuesError)return '<div class="small">Available Reports could not be loaded. Your saved Reports are unaffected. Use Reload available to try again.</div>';

    const groups=new Map();
    const add=(group,label,html)=>{
      const name=String(group||"Other").trim()||"Other";
      if(!groups.has(name))groups.set(name,[]);
      groups.get(name).push({label:String(label||"Report"),html});
    };

    for(const value of state.values.filter(item=>!reportForValue(item.id))){
      add(value.group,value.label,sourceValueCard(value));
    }

    if(!groups.size)return state.values.length?'<div class="small">All available Reports have been saved.</div>':'<div class="small">No Report values returned by this Source.</div>';

    const sorted=Array.from(groups.entries()).sort((a,b)=>a[0].localeCompare(b[0],undefined,{sensitivity:"base"}));
    return `<div><input id="reportSearch" type="search" value="${esc(state.reportSearch)}" placeholder="Search available reports…" aria-label="Search available reports" style="margin-bottom:12px"><div id="reportGroups" class="stack">${sorted.map(([group,items])=>`<details class="subcard" data-report-group><summary style="cursor:pointer;font-weight:900;font-size:16px">${esc(group)} <span class="small">(${items.length})</span></summary><div class="stack" style="margin-top:10px">${items.sort((a,b)=>a.label.localeCompare(b.label,undefined,{sensitivity:"base"})).map(item=>`<div data-report-item data-search="${esc(`${group} ${item.label}`.toLowerCase())}">${item.html}</div>`).join("")}</div></details>`).join("")}</div></div>`;
  }

  function applyReportSearch(){
    const input=$("reportSearch");
    if(!input)return;
    const query=String(input.value||"").trim().toLowerCase();
    state.reportSearch=input.value||"";
    document.querySelectorAll("[data-report-item]").forEach(item=>{
      item.hidden=!!query&&!String(item.dataset.search||"").includes(query);
    });
    document.querySelectorAll("[data-report-group]").forEach(group=>{
      const visible=Array.from(group.querySelectorAll("[data-report-item]")).some(item=>!item.hidden);
      group.hidden=!visible;
      if((query&&visible)||group.querySelector("[data-editing-report]"))group.open=true;
    });
  }

  function sourceEditor(){
    if(state.editor?.type!=="source")return"";
    const source=state.editor.value||{},c=source.connection||{},reports=source.id?state.reports.filter(report=>report.source_id===source.id):[];
    return `<div class="card"><div class="toolbar"><div><h2>${source.id?"Edit Source":"Add Source"}</h2><div class="small">Connection details stay inside the selected Source adapter.</div></div><button class="btn" data-action="close-editor">Close</button></div><div class="grid"><div><label>Name</label><input data-source="name" value="${esc(source.name||"Tableau")}"></div><div><label>Adapter</label><select data-source="adapter"><option value="tableau">Tableau</option></select></div><div><label>Server</label><input data-source="server" value="${esc(c.server||"")}" placeholder="https://tableau.example.com"></div><div><label>Site</label><input data-source="site" value="${esc(c.site||"")}"></div><div><label>PAT name</label><input data-source="pat_name" value="${esc(c.pat_name||"")}"></div><div><label>PAT secret</label><input type="password" data-source="secret" placeholder="${c.secret_configured?"Saved — leave blank to keep":"Enter secret"}"></div></div><div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-source">Save Source</button>${source.id?'<button class="btn" data-action="test-editor-source">Test Connection</button>':""}${source.id&&!reports.length?`<button class="btn danger" data-action="delete-source" data-id="${esc(source.id)}">Delete Source</button>`:""}</div>${source.id&&reports.length?`<div class="small" style="margin-top:10px">This Source is used by ${reports.length} Report${reports.length===1?"":"s"} and cannot be deleted.</div>`:""}</div>`;
  }

  function filterFieldOptions(filters,index){
    const current=filters[index]?.field||"",catalog=state.columns?.filter_fields||[];
    const items=catalog.map(item=>String(item.field||"")).filter(Boolean);
    if(current&&!items.includes(current))items.unshift(current);
    return `<option value="">Choose field…</option>${items.map(field=>`<option value="${esc(field)}" ${field===current?"selected":""}>${esc(field)}</option>`).join("")}`;
  }

  function filterFieldControl(filters,index){
    const current=String(filters[index]?.field||"");
    if(!state.columns)return `<input data-data-filter-field="${index}" value="${esc(current)}" placeholder="Field name">`;
    return `<select data-data-filter-field="${index}">${filterFieldOptions(filters,index)}</select>`;
  }

  function filterValueControl(filters,index){
    const filter=filters[index]||{},entry=(state.columns?.filter_fields||[]).find(item=>String(item.field)===String(filter.field));
    const values=(entry?.values||[]).map(String),current=String(filter.value||"");
    if(values.length&&!entry?.truncated){
      const options=current&&!values.includes(current)?[current,...values]:values;
      return `<select data-data-filter-value="${index}"><option value="">Choose value…</option>${options.map(value=>`<option value="${esc(value)}" ${value===current?"selected":""}>${esc(value)}</option>`).join("")}</select>`;
    }
    return `<input data-data-filter-value="${index}" value="${esc(current)}" placeholder="Value">`;
  }

  function dataFilters(report){
    const filters=report.filters||[];
    return `<div class="subcard" style="margin-top:14px"><div class="toolbar"><div><strong>Data Filters</strong><div class="small">Filter the data pulled for this Report.</div></div><button class="btn" data-action="add-data-filter" ${report.source_value?"":"disabled"}>+ Data Filter</button></div>${filters.length?filters.map((filter,index)=>`<div class="rule-row" style="grid-template-columns:1fr 1fr auto;margin-top:9px"><div><label>Field</label>${filterFieldControl(filters,index)}</div><div><label>Value</label>${filterValueControl(filters,index)}</div><button class="btn danger" data-action="remove-data-filter" data-index="${index}">Remove</button></div>`).join(""):'<div class="small" style="margin-top:9px">No Data Filters.</div>'}</div>`;
  }

  function reportEditor(reportId="",valueId=""){
    if(state.editor?.type!=="report")return"";
    const report=state.editor.value,rt=report.runtime||(report.runtime={});
    const savedId=String(report.id||"");
    if(reportId&&savedId!==String(reportId))return"";
    if(!reportId&&(savedId||String(report.source_value||"")!==String(valueId)))return"";
    const current=String(report.source_value||"");
    const values=current&&!state.values.some(item=>String(item.id)===current)?[{id:current,label:report.name||current},...state.values]:state.values;
    const updates=report.id?`<div><label>Automatic updates</label><select data-report="update_interval_minutes">${updateIntervalOptions(rt.update_interval_minutes||0)}</select></div>`:"";
    const customDates=rt.date_mode==="custom"?`<div><label>Start date</label><input type="date" data-report="date_start" value="${esc(rt.date_start||"")}"></div><div><label>End date</label><input type="date" data-report="date_end" value="${esc(rt.date_end||"")}"></div>`:"";
    return `<div data-report-editor style="border-top:1px solid var(--line);margin-top:12px;padding-top:12px"><div class="toolbar"><div><h3 style="margin:0">${report.id?"Edit Report":"Add Report"}</h3><div class="small">This Report comes from ${esc(selectedSource()?.name||"the selected Source")}.</div></div><button class="btn" data-action="close-editor">Close</button></div><div class="grid" style="margin-top:12px"><div><label>Name</label><input data-report="name" value="${esc(report.name||"Report")}"></div><div><label>Report</label><select data-report="source_value"><option value="">Choose Report…</option>${values.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===current?"selected":""}>${esc(item.label||item.id)}</option>`).join("")}</select></div>${updates}<div><label>Date window</label><select data-report="date_mode"><option value="current_month" ${rt.date_mode!=="custom"?"selected":""}>Current month</option><option value="custom" ${rt.date_mode==="custom"?"selected":""}>Custom range</option></select></div>${customDates}</div><label class="choice" style="margin-top:12px"><input type="checkbox" data-report="keep_last_known_rows" ${rt.keep_last_known_rows!==false?"checked":""}><span><strong>Display last known value</strong></span></label>${dataFilters(report)}${state.columns?`<div class="subcard" style="margin-top:14px"><strong>Fields returned by Source</strong><div class="chips">${(state.columns.choices||state.columns.headers||[]).slice(0,80).map(value=>`<span class="chip">${esc(value)}</span>`).join("")||'<span class="small">No fields returned.</span>'}</div></div>`:""}<div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-report">Save Report</button></div></div>`;
  }

  function reportInspection(report){
    const item=state.inspection;
    if(!item||String(item.report_id)!==String(report.id))return"";
    const fields=item.fields||[],rows=item.sample_rows||[];
    const editor=window.StatsFieldEditor;
    const selectedField=fields.find(field=>String(field.key)===String(state.inspectionFieldKey));
    return `<div data-report-inspection="${esc(report.id)}" style="border-top:1px solid var(--line);margin-top:12px;padding-top:12px"><div class="small">${Number(item.total_rows||0)} rows · ${esc(item.status||"")}${item.last_refresh?` · refreshed ${esc(item.last_refresh)}`:""}</div><div class="small" style="margin-top:8px">Press any column heading or value to edit its global Report Field.</div><div class="data-table" style="margin-top:8px"><table><thead><tr>${fields.map(field=>`<th class="${String(field.key)===String(state.inspectionFieldKey)?"field-editing":""}"><button class="table-field-button" type="button" data-inspection-field="${esc(field.key)}"><strong>${esc(field.label||field.key)}</strong><span>${esc(field.type||"text")}</span></button></th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${fields.map(field=>`<td class="${String(field.key)===String(state.inspectionFieldKey)?"field-editing":""}" data-inspection-field="${esc(field.key)}" title="Edit ${esc(field.label||field.key)}">${esc(editor.formatValue(row[field.key],field.type,field.decimals,field.percent_input_scale))}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(fields.length,1)}">No pulled rows.</td></tr>`}</tbody></table></div><div data-inspection-field-editor style="margin-top:10px">${editor.form(report.id,selectedField)}</div>${retentionControls(report,item)}${duplicateControls(report,fields)}</div>`;
  }

  function retentionControls(report,item){
    const saved=item.retention?.saved_missing||[];
    if(!saved.length)return"";
    return `<div class="subcard" style="margin-top:10px"><strong>Saved Missing Rows</strong><div class="small" style="margin-top:4px">The latest refresh did not return these rows, so Stats kept their last values.</div><div class="row" style="margin-top:9px">${saved.map(row=>`<span class="chip">${esc(row.label||row.identity)} <button class="btn danger" type="button" data-action="remove-retained-row" data-id="${esc(report.id)}" data-identity="${esc(row.identity)}">Remove</button></span>`).join("")}</div></div>`;
  }

  function duplicateControls(report,fields){
    const cleanup=report.cleanup||{},check=String(state.duplicateCheck?.reportId||"")===String(report.id)?state.duplicateCheck:null,current=check?.field||cleanup.deduplicate_by||fields[0]?.key||"",result=check?.result;
    const applied=cleanup.deduplicate_by?`<div class="small saved" style="margin-top:8px">Automatic cleanup: ${esc(cleanup.deduplicate_by)} · keep ${esc(cleanup.deduplicate_keep||"first")} on every refresh. <button class="btn" type="button" data-action="clear-deduplication" data-id="${esc(report.id)}">Stop cleanup</button></div>`:"";
    const summary=result?result.duplicate_rows?`<div style="margin-top:10px"><strong>${Number(result.duplicate_rows)} duplicate row${Number(result.duplicate_rows)===1?"":"s"}</strong><div class="small">Across ${Number(result.duplicate_values)} repeated value${Number(result.duplicate_values)===1?"":"s"}. ${result.groups.slice(0,8).map(group=>`${esc(group.value)} (${Number(group.count)})`).join(" · ")}</div><div class="row" style="margin-top:9px"><select data-deduplicate-keep style="width:auto"><option value="first">Keep first row</option><option value="last">Keep last row</option></select><button class="btn danger" type="button" data-action="apply-deduplication" data-id="${esc(report.id)}">Remove duplicates</button></div></div>`:'<div class="small saved" style="margin-top:10px">No duplicates found for this field.</div>':"";
    return `<div class="subcard" style="margin-top:10px"><div class="toolbar"><div><strong>Duplicate Rows</strong><div class="small">Choose the field that must be unique. Removal is user-controlled and can be kept for future refreshes.</div></div><div class="row"><select data-duplicate-field style="width:auto;min-width:200px">${fields.map(field=>`<option value="${esc(field.key)}" ${String(field.key)===String(current)?"selected":""}>${esc(field.label||field.key)}</option>`).join("")}</select><button class="btn" type="button" data-action="check-duplicates" data-id="${esc(report.id)}">Look for duplicates</button></div></div>${applied}${summary}</div>`;
  }

  function render(){
    const host=$("settingsDataHost");
    if(!host)return;
    const source=selectedSource();
    host.innerHTML=`${sourceEditor()}<div class="card"><div><h2>Saved Reports</h2><div class="small">Reports you have configured. Choose how often each one updates.</div></div><div style="margin-top:12px">${savedReportBrowser()}</div></div><details class="card" data-available-reports ${state.availableReportsOpen?"open":""}><summary style="cursor:pointer"><strong style="font-size:20px">Available Reports</strong><div class="small">Reports available to add from ${esc(source?.name||"the selected Source")}.</div></summary><div class="toolbar" style="justify-content:flex-end;margin-top:12px">${source?'<button class="btn" data-action="reload-values">Reload available</button>':""}</div><div style="margin-top:12px">${reportBrowser()}</div></details><div class="status">${esc(state.message||"")}</div>`;
    bind();
    renderSourceMenu();
    applyReportSearch();
  }

  function readSourceEditor(){
    const current=state.editor.value,c=current.connection||{};
    return {...current,name:hostValue('[data-source="name"]'),adapter:hostValue('[data-source="adapter"]')||'tableau',connection:{...c,server:hostValue('[data-source="server"]'),site:hostValue('[data-source="site"]'),pat_name:hostValue('[data-source="pat_name"]')},secret:hostValue('[data-source="secret"]')};
  }

  function hostValue(selector){return $("settingsDataHost")?.querySelector(selector)?.value||"";}

  function syncReport(){
    const report=state.editor.value,rt=report.runtime||(report.runtime={});
    report.name=hostValue('[data-report="name"]')||report.name;
    report.source_id=state.activeSourceId;
    report.source_value=hostValue('[data-report="source_value"]');
    rt.date_mode=hostValue('[data-report="date_mode"]')||'current_month';
    rt.keep_last_known_rows=$("settingsDataHost")?.querySelector('[data-report="keep_last_known_rows"]')?.checked!==false;
    const startDate=$("settingsDataHost")?.querySelector('[data-report="date_start"]');
    const endDate=$("settingsDataHost")?.querySelector('[data-report="date_end"]');
    if(startDate)rt.date_start=startDate.value;
    if(endDate)rt.date_end=endDate.value;
    if(report.id)rt.update_interval_minutes=Number(hostValue('[data-report="update_interval_minutes"]')||0);
    $("settingsDataHost")?.querySelectorAll('[data-data-filter-field]').forEach(el=>{const i=Number(el.dataset.dataFilterField);if(report.filters?.[i])report.filters[i].field=el.value;});
    $("settingsDataHost")?.querySelectorAll('[data-data-filter-value]').forEach(el=>{const i=Number(el.dataset.dataFilterValue);if(report.filters?.[i])report.filters[i].value=el.value;});
    return report;
  }

  async function openSource(id){
    state.editor={type:"source",value:id?JSON.parse(JSON.stringify(sourceBy(id))):{name:"Tableau",adapter:"tableau",connection:{}}};
    state.columns=null;
    render();
  }

  async function openReport(id,valueId=""){
    const source=selectedSource();
    if(!source)return;
    const choice=state.values.find(item=>String(item.id)===String(valueId));
    const value=id?JSON.parse(JSON.stringify(reportBy(id))):{name:choice?.label||"Report",source_id:source.id,source_value:valueId,filters:[],runtime:{date_mode:"current_month"}};
    value.filters=Array.isArray(value.filters)?value.filters:[];
    state.editor={type:"report",value};
    state.columns=null;
    state.inspection=null;
    state.inspectionFieldKey="";
    state.duplicateCheck=null;
    render();
    if(value.source_value)await loadColumnsForEditor();
  }

  async function loadColumnsForEditor(quiet=false){
    const report=state.editor?.type==="report"?state.editor.value:null;
    if(!report?.source_value)return;
    const payload=syncReport();
    if(!quiet){state.message="Loading Report fields…";render();}
    try{
      const url=report.id
        ?`/api/data/reports/${encodeURIComponent(report.id)}/columns`
        :`/api/data/sources/${encodeURIComponent(report.source_id)}/report-columns`;
      state.columns=await runtime.api(url,runtime.json("POST",report.id?{}:payload));
      if(!quiet)state.message="";
    }catch(error){state.columns=null;if(!quiet)state.message=error.message;}
    render();
  }

  async function saveSource(){
    const payload=readSourceEditor();
    state.message="Saving Source…";
    render();
    try{
      const url=payload.id?`/api/data/sources/${encodeURIComponent(payload.id)}`:"/api/data/sources";
      const method=payload.id?"PUT":"POST";
      const data=await runtime.api(url,runtime.json(method,payload));
      state.activeSourceId=data.source?.id||state.activeSourceId;
      state.editor=null;
      state.message="Source saved.";
      await load();
    }catch(error){state.message=error.message;render();}
  }

  async function testSource(id,payload=null){
    state.message="Testing connection…";
    render();
    try{
      const source=payload||sourceBy(id);
      if(payload&&payload.id)await runtime.api(`/api/data/sources/${encodeURIComponent(payload.id)}`,runtime.json("PUT",payload));
      const data=await runtime.api(`/api/data/sources/${encodeURIComponent(source.id)}/test`,{method:"POST"});
      state.message=data.message||"Connected.";
    }catch(error){state.message=error.message;}
    render();
  }

  async function saveReport(){
    const payload=syncReport();
    if(!payload.source_value){state.message="Choose a Report from the selected Source.";render();return;}
    state.message="Saving Report…";
    render();
    try{
      const url=payload.id?`/api/data/reports/${encodeURIComponent(payload.id)}`:"/api/data/reports";
      const method=payload.id?"PUT":"POST";
      await runtime.api(url,runtime.json(method,payload));
      const reports=await runtime.api("/api/data/reports");
      state.reports=reports.reports||[];
      state.editor=null;
      state.columns=null;
      state.message="Report saved. Use Refresh now when you want to pull Tableau data.";
      render();
      runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
    }catch(error){state.message=error.message;render();}
  }

  async function inspectReport(id,force=false){
    if(!force&&String(state.inspection?.report_id||"")===String(id)){
      state.inspection=null;
      state.inspectionFieldKey="";
      state.message="";
      render();
      return;
    }
    state.inspection=null;
    state.inspectionFieldKey="";
    state.duplicateCheck=null;
    state.message="Loading pulled data…";
    render();
    try{state.inspection=await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/inspect`);state.message="";}catch(error){state.message=error.message;}
    render();
  }

  async function refreshReport(id){
    state.message="Refreshing Report…";
    render();
    try{
      await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/refresh`,{method:"POST"});
      const reports=await runtime.api("/api/data/reports");
      state.reports=reports.reports||[];
      state.message="Report refreshed.";
      await inspectReport(id,true);
    }catch(error){state.message=error.message;render();}
  }

  async function checkDuplicates(id){
    const field=$("settingsDataHost")?.querySelector("[data-duplicate-field]")?.value||"";
    if(!field){state.message="Choose a field to check.";render();return;}
    state.message="Looking for duplicate rows…";
    render();
    try{
      const result=await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/duplicates?field=${encodeURIComponent(field)}`);
      state.duplicateCheck={reportId:id,field,result};
      state.message="";
    }catch(error){state.message=error.message;}
    render();
  }

  async function applyDeduplication(id){
    const field=state.duplicateCheck?.field||$("settingsDataHost")?.querySelector("[data-duplicate-field]")?.value||"";
    const keep=$("settingsDataHost")?.querySelector("[data-deduplicate-keep]")?.value||"first";
    if(!field)return;
    state.message="Removing duplicate rows…";
    render();
    try{
      const result=await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/deduplication`,runtime.json("PUT",{field,keep}));
      const reports=await runtime.api("/api/data/reports");
      state.reports=reports.reports||[];
      state.duplicateCheck=null;
      await inspectReport(id,true);
      state.message=`Removed ${Number(result.removed||0)} duplicate row${Number(result.removed||0)===1?"":"s"}. This cleanup will run after every refresh.`;
      render();
      runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
    }catch(error){state.message=error.message;render();}
  }

  async function clearDeduplication(id){
    state.message="Removing duplicate cleanup rule…";
    render();
    try{
      await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/deduplication`,{method:"DELETE"});
      const reports=await runtime.api("/api/data/reports");
      state.reports=reports.reports||[];
      state.duplicateCheck=null;
      state.message="Cleanup rule removed. Refresh the Report to restore rows from the Source.";
      render();
      runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
    }catch(error){state.message=error.message;render();}
  }

  async function removeRetainedRow(id,identity){
    if(!confirm(`Remove the saved data for ${identity}?`))return;
    state.message="Removing saved row…";
    render();
    try{
      await runtime.api(`/api/data/reports/${encodeURIComponent(id)}/retained-rows`,runtime.json("DELETE",{identity}));
      await inspectReport(id,true);
      state.message=`Removed saved data for ${identity}.`;
      render();
      runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
    }catch(error){state.message=error.message;render();}
  }

  async function updateReportInterval(id,value){
    const report=reportBy(id);
    if(!report)return;
    const payload=JSON.parse(JSON.stringify(report));
    const minutes=Number(value||0);
    payload.runtime={...(payload.runtime||{}),update_interval_minutes:minutes};
    state.message="Saving update interval…";
    render();
    try{
      await runtime.api(`/api/data/reports/${encodeURIComponent(id)}`,runtime.json("PUT",payload));
      const data=await runtime.api("/api/data/reports");
      state.reports=data.reports||[];
      if(state.editor?.type==="report"&&String(state.editor.value?.id)===String(id))state.editor.value=JSON.parse(JSON.stringify(reportBy(id)));
      state.message=minutes?`${report.name||"Report"}: ${updateIntervalLabel(minutes)}.`:`${report.name||"Report"}: automatic updates off.`;
      render();
      runtime.emit("data-changed",{sources:state.sources,reports:state.reports});
    }catch(error){state.message=error.message;render();}
  }

  function bind(){
    const host=$("settingsDataHost");
    if(!host)return;
    window.StatsFieldEditor.bind(host,{onSaved:()=>{state.inspectionFieldKey="";},onClose:()=>{state.inspectionFieldKey="";render();}});
    host.querySelector('[data-available-reports]')?.addEventListener("toggle",event=>{state.availableReportsOpen=event.target.open;});
    host.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",async()=>{
      const a=button.dataset.action,id=button.dataset.id,index=Number(button.dataset.index||0);
      if(a==="add-report-value")return openReport(null,button.dataset.value);
      if(a==="edit-report")return openReport(id);
      if(a==="close-editor"){state.editor=null;state.columns=null;render();return;}
      if(a==="save-source")return saveSource();
      if(a==="test-editor-source")return testSource(state.editor.value.id,readSourceEditor());
      if(a==="save-report")return saveReport();
      if(a==="inspect-report")return inspectReport(id);
      if(a==="refresh-report")return refreshReport(id);
      if(a==="check-duplicates")return checkDuplicates(id);
      if(a==="apply-deduplication")return applyDeduplication(id);
      if(a==="clear-deduplication")return clearDeduplication(id);
      if(a==="remove-retained-row")return removeRetainedRow(id,button.dataset.identity||"");
      if(a==="reload-values")return loadReportValues();
      if(a==="add-data-filter"){syncReport();(state.editor.value.filters||(state.editor.value.filters=[])).push({field:"",value:""});render();return;}
      if(a==="remove-data-filter"){syncReport();state.editor.value.filters.splice(index,1);render();return;}
      if(a==="delete-source"){
        if(!confirm("Delete this Source?"))return;
        try{await runtime.api(`/api/data/sources/${encodeURIComponent(id)}`,{method:"DELETE"});state.activeSourceId="";state.editor=null;state.message="Source deleted.";await load();}catch(error){state.message=error.message;render();}
        return;
      }
      if(a==="delete-report"){
        if(!confirm("Delete this Report?"))return;
        try{await runtime.api(`/api/data/reports/${encodeURIComponent(id)}`,{method:"DELETE"});state.message="Report deleted.";await load();}catch(error){state.message=error.message;render();}
      }
    }));
    host.querySelectorAll('[data-data-filter-field]').forEach(el=>el.addEventListener("change",()=>{syncReport();render();}));
    host.querySelectorAll('[data-inspection-field]').forEach(el=>el.addEventListener("click",()=>{state.inspectionFieldKey=el.dataset.inspectionField;render();requestAnimationFrame(()=>host.querySelector('[data-inspection-field-editor]')?.scrollIntoView({block:"nearest"}));}));
    host.querySelectorAll('[data-report-update-interval]').forEach(el=>el.addEventListener("change",()=>updateReportInterval(el.dataset.id,el.value)));
    host.querySelector('[data-report="date_mode"]')?.addEventListener("change",()=>{syncReport();render();});
    host.querySelector('[data-report="source_value"]')?.addEventListener("change",async event=>{
      syncReport();
      state.editor.value.source_value=event.target.value;
      state.columns=null;
      render();
      if(state.editor.value.source_value)await loadColumnsForEditor();
    });
    $("reportSearch")?.addEventListener("input",applyReportSearch);
  }

  runtime.on("section",id=>{
    if(id!=="settingsData"){
      if($("settingsPageActions"))$("settingsPageActions").innerHTML="";
      return;
    }
    if(!loaded)load().catch(error=>{state.message=error.message;render();});
    else renderSourceMenu();
  });
  runtime.on("unlocked",()=>{loaded=false;});
  runtime.on("fields-changed",detail=>{
    const field=detail?.field,reportId=String(detail?.report_id||"");
    if(!field||!reportId)return;
    const report=reportBy(reportId);
    if(report)report.fields=(report.fields||[]).map(item=>String(item.key)===String(field.key)?field:item);
    if(String(state.inspection?.report_id||"")===reportId)state.inspection.fields=(state.inspection.fields||[]).map(item=>String(item.key)===String(field.key)?field:item);
    render();
  });
  runtime.on("request-data-refresh",()=>load().catch(()=>{}));
})();
