/* Stats workspace: Sources -> Reports -> Filters -> Screens -> Display. */
(function(){
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const clone=value=>JSON.parse(JSON.stringify(value));
  const state={
    tab:"data",sources:[],reports:[],filters:[],screens:[],display:{},
    inspections:{},editor:null,themeEditor:null,message:"",busy:false
  };
  let root=null,previewTimer=null;

  async function api(url,options={}){
    const headers={...(options.headers||{})};
    if(options.body && !(options.body instanceof FormData)) headers["Content-Type"]="application/json";
    const response=await fetch(url,{cache:"no-store",...options,headers});
    let data={};try{data=await response.json();}catch(_){ }
    if(!response.ok||data.ok===false) throw new Error(data.error||`Request failed (${response.status})`);
    return data;
  }
  const json=(method,body)=>({method,body:JSON.stringify(body||{})});
  const sourceBy=id=>state.sources.find(item=>item.id===id)||null;
  const reportBy=id=>state.reports.find(item=>item.id===id)||null;
  const filterBy=id=>state.filters.find(item=>item.id===id)||null;
  const screenBy=id=>state.screens.find(item=>item.id===id)||null;

  function removeObsoleteDataMarkup(){
    ["openDataSource","sourceStatusLine","displaySettingsTitle"].forEach(id=>{
      const el=document.getElementById(id);const card=el?.closest(".card");if(card)card.remove();
    });
    const overlay=document.getElementById("dataSourceOverlay");if(overlay)overlay.remove();
    const active=document.getElementById("activeMode");if(active?.parentElement)active.parentElement.remove();
  }

  async function loadAll(){
    const [sources,reports,filters,screens,display]=await Promise.all([
      api("/api/data/sources"),api("/api/data/reports"),api("/api/filters"),api("/api/screens"),api("/api/display")
    ]);
    state.sources=sources.sources||[];
    state.reports=reports.reports||[];
    state.filters=filters.filters||[];
    state.screens=screens.screens||[];
    state.display=display;
  }

  async function loadInspection(reportId,force=false){
    if(!reportId)return null;
    if(!force&&state.inspections[reportId])return state.inspections[reportId];
    const data=await api(`/api/data/reports/${encodeURIComponent(reportId)}/inspect`);
    state.inspections[reportId]=data;
    return data;
  }

  function shell(){
    return `<style id="statsWorkspaceStyles">
      #statsWorkspace{margin:18px 0}.stats-tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:16px;overflow:auto}.stats-tab{border:0;border-bottom:3px solid transparent;background:transparent;color:var(--muted);padding:12px 16px;font-weight:900;cursor:pointer;white-space:nowrap}.stats-tab.active{color:var(--accent);border-color:var(--accent)}
      .stats-toolbar{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}.stats-stack{display:grid;gap:10px}.stats-item,.stats-subcard{border:1px solid var(--line);background:#0f0f0f;padding:13px}.stats-subcard{background:#0c0c0c}.stats-meta{color:var(--muted);font-size:12px;margin-top:4px}.stats-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.stats-editor{border:1px solid #5f5226;background:#111;padding:16px;margin:12px 0}.stats-status{min-height:18px;color:var(--accent);margin:8px 0}.stats-danger{color:#ffaaaa}.stats-muted{color:var(--muted)}
      .stats-report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px}.stats-data-table{max-width:100%;overflow:auto;border:1px solid #292929;margin-top:10px}.stats-data-table table{border-collapse:collapse;width:100%;font-size:12px}.stats-data-table th,.stats-data-table td{padding:6px 8px;border-bottom:1px solid #242424;text-align:left;white-space:nowrap}.stats-data-table th{position:sticky;top:0;background:#111;color:#aaa}.stats-chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}.stats-chip{border:1px solid #333;background:#151515;padding:3px 6px;font-size:11px;color:#ccc;border-radius:999px}.stats-field{border:1px solid #292929;background:#0b0b0b;padding:10px}.stats-field-grid{display:grid;grid-template-columns:minmax(150px,.8fr) minmax(200px,1.2fr);gap:12px;align-items:start}.stats-field-name{font-weight:900}.stats-field-key{color:#777;font-size:11px;margin-top:3px}.stats-match{display:grid;grid-template-columns:1fr auto;gap:7px}.stats-create-inline{display:grid;grid-template-columns:1fr auto;gap:7px;margin-top:7px}.stats-match-note{font-size:11px;color:#8d8d8d;margin-top:5px}.stats-filter-card{border:1px solid #383838;background:#111;padding:10px}.stats-filter-card.mapped{border-color:#756326}.stats-filter-value{display:grid;grid-template-columns:minmax(160px,1fr) minmax(180px,1fr);gap:10px;align-items:end}
      .stats-steps{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 18px}.stats-step{border:1px solid #333;padding:7px 10px;color:#888;background:#0d0d0d}.stats-step.active{border-color:var(--accent);color:var(--accent)}.stats-step.done{color:#ccc}.stats-step-page{display:grid;gap:12px}.stats-screen-report{border:1px solid #303030;background:#0d0d0d;padding:12px}.stats-screen-report.selected{border-color:#706026}.stats-report-choice{display:flex;gap:9px;align-items:flex-start}.stats-report-choice input{width:auto;margin-top:3px}.stats-columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:7px}.stats-check{display:flex;gap:7px;align-items:center;border:1px solid #292929;padding:7px}.stats-check input{width:auto}.stats-preview{border:1px solid #3a3a3a;background:#080808;padding:12px;max-height:520px;overflow:auto}.stats-preview-grid{display:grid;gap:12px}.stats-preview-section{border:1px solid #2e2e2e;background:#0d0d0d;padding:10px}.stats-preview-section h4{margin:0 0 6px}.stats-preview table{width:100%;border-collapse:collapse;font-size:12px}.stats-preview th,.stats-preview td{padding:5px 7px;border-bottom:1px solid #242424;text-align:left;white-space:nowrap}.stats-preview-wrap{overflow:auto}.stats-order{display:grid;grid-template-columns:auto minmax(160px,1fr) auto;gap:8px;align-items:center;border:1px solid #292929;padding:9px}.stats-order input{width:auto}.stats-theme-colors{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}.stats-theme-color{display:grid;grid-template-columns:46px 1fr;gap:8px;align-items:center}.stats-theme-color input[type=color]{height:42px;padding:2px}.stats-section-title{margin:0}.stats-explain{border-left:3px solid var(--accent);background:#12110c;padding:10px 12px;color:#ddd}.stats-separator{border-top:1px solid #2c2c2c;margin:14px 0}.stats-pill{display:inline-block;border:1px solid #3a3a3a;padding:3px 7px;border-radius:999px;font-size:11px;color:#bbb;margin:2px}.stats-kicker{text-transform:uppercase;letter-spacing:.08em;color:#8c8c8c;font-size:10px;font-weight:900}
      @media(max-width:760px){.stats-field-grid,.stats-filter-value{grid-template-columns:1fr}.stats-order{grid-template-columns:auto 1fr}.stats-order .stats-actions{grid-column:1/-1}.stats-match,.stats-create-inline{grid-template-columns:1fr}.stats-tabs{margin-left:-4px;margin-right:-4px}.stats-editor{padding:12px}}
    </style>
    <div class="card" id="statsWorkspace">
      <div class="stats-tabs">
        <button class="stats-tab" data-tab="data">Data</button>
        <button class="stats-tab" data-tab="screens">Screens</button>
        <button class="stats-tab" data-tab="display">Display</button>
      </div>
      <div id="statsWorkspaceBody"></div>
    </div>`;
  }

  function inspectionTable(inspection,maxRows=6){
    if(!inspection)return'<div class="small">Open pulled data to see real values.</div>';
    const fields=inspection.fields||[];const rows=(inspection.sample_rows||[]).slice(0,maxRows);
    if(!fields.length)return'<div class="small">No fields found in this Report yet. Pull it first.</div>';
    const head=fields.map(field=>`<th>${esc(field.label||field.key)}</th>`).join("");
    const body=rows.map(row=>`<tr>${fields.map(field=>`<td>${esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("");
    return `<div class="stats-data-table"><table><thead><tr>${head}</tr></thead><tbody>${body||`<tr><td colspan="${fields.length}">No pulled rows.</td></tr>`}</tbody></table></div>`;
  }

  function inspectionFields(inspection){
    if(!inspection)return"";
    return `<div class="stats-stack" style="margin-top:10px">${(inspection.fields||[]).map(field=>`<div class="stats-field"><div class="stats-field-name">${esc(field.label||field.key)}</div><div class="stats-field-key">${esc(field.key)} · ${esc(field.type||"text")}</div><div class="stats-chips">${(field.sample_values||[]).slice(0,12).map(value=>`<span class="stats-chip">${esc(value)}</span>`).join("")||'<span class="stats-muted small">No values in pulled rows</span>'}</div></div>`).join("")}</div>`;
  }

  function sourceEditor(){
    const editor=state.editor;if(editor?.type!=="source")return"";
    const source=editor.value||{};const connection=source.connection||{};
    return `<div class="stats-editor">
      <div class="stats-toolbar"><div><div class="stats-kicker">Source</div><h3 style="margin:2px 0">${source.id?"Edit Source":"Add Source"}</h3></div><button class="btn" data-action="close-editor">Close</button></div>
      <div class="grid">
        <div><label>Name</label><input data-source-edit="name" value="${esc(source.name||"Tableau")}"></div>
        <div><label>Adapter</label><select data-source-edit="adapter"><option value="tableau">Tableau</option></select></div>
        <div><label>Server</label><input data-source-edit="server" value="${esc(connection.server||"")}" placeholder="https://tableau.example.com"></div>
        <div><label>Site</label><input data-source-edit="site" value="${esc(connection.site||"")}"></div>
        <div><label>PAT name</label><input data-source-edit="pat_name" value="${esc(connection.pat_name||"")}"></div>
        <div><label>PAT secret</label><input type="password" data-source-edit="secret" placeholder="${connection.secret_configured?"Saved — leave blank to keep":"Enter secret"}"></div>
      </div>
      <div class="stats-actions"><button class="btn primary" data-action="save-source">Save Source</button>${source.id?'<button class="btn" data-action="test-source">Test Connection</button>':""}</div>
    </div>`;
  }

  function dataFilterEditor(report){
    const columns=state.editor?.columns;const filters=report.source_config?.filters||[];
    if(!columns)return'<div class="small">Read Report first to see source fields and values.</div>';
    const catalog=columns.filter_fields||[];
    return `<div class="stats-subcard">
      <div class="stats-toolbar"><div><div class="stats-kicker">Affects pull</div><h4 style="margin:2px 0">Data Filters</h4></div><button class="btn" data-action="add-data-filter">+ Data Filter</button></div>
      <div class="small">These are sent to the Source and change what gets pulled. They are not Display Filters.</div>
      ${filters.map((item,index)=>`<div class="grid" style="margin-top:9px"><select data-data-filter-field="${index}"><option value="">Choose source field</option>${catalog.map(row=>`<option value="${esc(row.field)}" ${row.field===item.field?"selected":""}>${esc(row.field)}</option>`).join("")}</select><div class="row"><input data-data-filter-value="${index}" value="${esc(item.value||"")}" placeholder="Value"><button class="btn danger" data-action="drop-data-filter" data-index="${index}">Remove</button></div></div>`).join("")||'<div class="small" style="margin-top:8px">No Data Filters.</div>'}
    </div>`;
  }

  function mappingEditor(report){
    const columns=state.editor?.columns;if(!columns||report.kind!=="rep_performance")return"";
    const choices=(columns.choices||columns.headers||[]).map(String);const mapping=report.source_config?.mapping||{};
    const select=(key,label,current)=>`<div><label>${esc(label)}</label><select data-report-map="${esc(key)}"><option value="">— not mapped —</option>${choices.map(value=>`<option value="${esc(value)}" ${value===current?"selected":""}>${esc(value)}</option>`).join("")}</select></div>`;
    const metrics=(report.fields||reportBy(report.id)?.fields||[]).filter(field=>["number","percent","currency"].includes(field.type));
    return `<div class="stats-subcard"><h4 style="margin-top:0">Normalize Sales Rep Report</h4><div class="small">This mapping converts this vendor Report into the Stats rep-performance contract.</div><div class="grid" style="margin-top:10px">${select("rep_name","Sales Rep",mapping.rep_name||"")}${select("home_branch","Home Branch",mapping.home_branch||"")}${select("team","Team",mapping.team||"")}</div><div class="grid" style="margin-top:10px">${metrics.map(metric=>select(`metric:${metric.key}`,metric.label,mapping.metrics?.[metric.key]||"")).join("")}</div></div>`;
  }

  function reportEditor(){
    const editor=state.editor;if(editor?.type!=="report")return"";
    const report=editor.value||{};const config=report.source_config||(report.source_config={});const runtime=report.runtime||(report.runtime={});
    const sourceId=report.source_id||state.sources[0]?.id||"";const workbooks=editor.workbooks||[];const views=editor.views||[];
    return `<div class="stats-editor">
      <div class="stats-toolbar"><div><div class="stats-kicker">Report</div><h3 style="margin:2px 0">${report.id?"Edit Report":"Add Report"}</h3></div><button class="btn" data-action="close-editor">Close</button></div>
      <div class="grid">
        <div><label>Name</label><input data-report-edit="name" value="${esc(report.name||"New Report")}"></div>
        <div><label>Source</label><select data-report-edit="source_id">${state.sources.map(source=>`<option value="${esc(source.id)}" ${source.id===sourceId?"selected":""}>${esc(source.name)}</option>`).join("")}</select></div>
        ${report.kind==="product_close"?`<div><label>Market</label><input data-report-edit="market" value="${esc(runtime.market||"Olympia")}"></div>`:`
        <div><label>Workbook</label><select data-report-edit="workbook"><option value="">Choose workbook</option>${workbooks.map(book=>`<option value="${esc(book.content_url)}" ${book.content_url===config.workbook?"selected":""}>${esc(book.name||book.content_url)}</option>`).join("")}</select></div>
        <div><label>Report / View</label><select data-report-edit="sheet"><option value="">Choose report</option>${views.map(view=>`<option value="${esc(view.content_url)}" ${view.content_url===config.sheet?"selected":""}>${esc(view.name||view.content_url)}</option>`).join("")}</select></div>
        <div><label>Export</label><select data-report-edit="export"><option value="auto" ${config.export==="auto"?"selected":""}>Auto</option><option value="csv" ${config.export==="csv"?"selected":""}>CSV</option><option value="crosstab" ${config.export==="crosstab"?"selected":""}>Crosstab</option></select></div>
        <div><label>Date</label><select data-report-edit="date_mode"><option value="current_month" ${runtime.date_mode!=="custom"?"selected":""}>Current month</option><option value="custom" ${runtime.date_mode==="custom"?"selected":""}>Custom range</option></select></div>
        <div><label>Start</label><input type="date" data-report-edit="date_start" value="${esc(runtime.date_start||"")}"></div>
        <div><label>End</label><input type="date" data-report-edit="date_end" value="${esc(runtime.date_end||"")}"></div>`}
      </div>
      ${report.kind!=="product_close"?`<div class="stats-actions"><button class="btn" data-action="load-workbooks">Load Workbooks</button><button class="btn" data-action="read-report">Read Report</button><button class="btn" data-action="preview-report">Preview Candidate</button></div>${mappingEditor(report)}${dataFilterEditor(report)}`:""}
      <div class="stats-actions"><button class="btn primary" data-action="save-report">Save Report</button>${report.id?'<button class="btn" data-action="refresh-report">Pull Now</button>':""}</div>
    </div>`;
  }

  function reportCard(report){
    const inspection=state.inspections[report.id];
    return `<div class="stats-subcard">
      <strong>${esc(report.name)}</strong><div class="stats-meta">${esc(report.status||"Not refreshed")}${report.last_refresh?` · ${esc(report.last_refresh)}`:""}</div>
      <div class="stats-actions"><button class="btn" data-action="edit-report" data-id="${esc(report.id)}">Edit</button><button class="btn primary" data-action="refresh-report-card" data-id="${esc(report.id)}">Pull Now</button><button class="btn" data-action="inspect-report" data-id="${esc(report.id)}">${inspection?"Refresh data view":"View pulled data"}</button>${!["report-reps","report-products"].includes(report.id)?`<button class="btn danger" data-action="delete-report" data-id="${esc(report.id)}">Delete</button>`:""}</div>
      ${inspection?`<div class="stats-separator"></div><div class="stats-meta"><strong>${inspection.total_rows||0}</strong> pulled rows · showing real sample data</div>${inspectionTable(inspection)}<details style="margin-top:9px"><summary>See fields and sample values</summary>${inspectionFields(inspection)}</details>`:""}
    </div>`;
  }

  function dataView(){
    return `<div class="stats-toolbar"><div><h2 class="stats-section-title">Data</h2><div class="small">Sources connect to external systems. Reports define what Stats pulls and stores.</div></div><button class="btn primary" data-action="new-source">+ Source</button></div>
      <div class="stats-explain"><strong>Data Filters live here.</strong> They affect what a Report pulls from its Source. Display Filters are configured later inside a Screen and only work with data Stats has already pulled.</div>
      ${sourceEditor()}${reportEditor()}
      <div class="stats-stack" style="margin-top:12px">${state.sources.map(source=>`<div class="stats-item"><div class="stats-toolbar"><div><h3 style="margin:0">${esc(source.name)}</h3><div class="stats-meta">${esc(source.adapter)} · ${esc(source.connection?.server||"No server")} · ${source.connection?.secret_configured?"credentials saved":"credentials missing"}</div></div><div class="row"><button class="btn" data-action="edit-source" data-id="${esc(source.id)}">Edit</button><button class="btn" data-action="test-source-card" data-id="${esc(source.id)}">Test</button><button class="btn primary" data-action="new-report" data-id="${esc(source.id)}">+ Report</button></div></div><div class="stats-report-grid">${(source.reports||[]).map(reportCard).join("")||'<div class="small">No Reports yet.</div>'}</div></div>`).join("")||'<div class="small">No Sources configured.</div>'}</div>`;
  }

  function filterLibrary(){
    return `<div class="stats-subcard"><div class="stats-toolbar"><div><h3 style="margin:0">Filters</h3><div class="small">Reusable names such as Team, Office, Product or Rep. Filters do not know report fields until a Screen matches them to pulled data.</div></div></div>
      <div class="row"><input id="statsNewFilterName" style="max-width:330px" placeholder="New Filter name"><button class="btn primary" data-action="create-filter">+ Create Filter</button></div>
      <div class="stats-actions">${state.filters.map(filter=>`<span class="stats-filter-card"><strong>${esc(filter.name)}</strong> <button class="btn danger" style="padding:4px 7px;margin-left:6px" data-action="delete-filter" data-id="${esc(filter.id)}">Delete</button></span>`).join("")||'<span class="small">No Filters yet. You can also create one while looking at pulled data in Step 2.</span>'}</div>
    </div>`;
  }

  function emptyScreen(){
    return {name:"New Screen",kind:"custom",reports:[],filter_ids:[],display_filter_mappings:[],filter_values:{},tables:[],theme_mode:"inherited"};
  }

  function screenSteps(editor){
    const labels=["1. Choose Data","2. Display Data — Match Filters","3. Create Table","4. Theme"];
    return `<div class="stats-steps">${labels.map((label,index)=>`<div class="stats-step ${editor.step===index?"active":editor.step>index?"done":""}">${label}</div>`).join("")}</div>`;
  }

  function selectedReports(screen){return (screen.reports||[]).map(reportBy).filter(Boolean);}

  function stepChooseData(screen){
    return `<div class="stats-step-page"><div><label>Screen Name</label><input data-screen-name value="${esc(screen.name||"")}"></div>
      <div class="stats-explain">Choose every pulled Report this Screen may display. A Screen can combine data from multiple Reports.</div>
      <div class="stats-stack">${state.reports.map(report=>{const selected=(screen.reports||[]).includes(report.id);return`<label class="stats-screen-report ${selected?"selected":""}"><span class="stats-report-choice"><input type="checkbox" data-screen-report="${esc(report.id)}" ${selected?"checked":""}><span><strong>${esc(report.name)}</strong><span class="stats-meta" style="display:block">${esc(report.status||"Not refreshed")}${report.last_refresh?` · ${esc(report.last_refresh)}`:""}</span></span></span></label>`;}).join("")||'<div class="small">Create and pull a Report on the Data tab first.</div>'}</div>
    </div>`;
  }

  function mappingFor(screen,filterId,reportId){return (screen.display_filter_mappings||[]).find(item=>item.filter_id===filterId&&item.report_id===reportId)||null;}
  function filterMappedAnywhere(screen,filterId){return (screen.display_filter_mappings||[]).some(item=>item.filter_id===filterId);}

  function fieldMatchRow(screen,reportId,field){
    const mapped=(screen.display_filter_mappings||[]).find(item=>item.report_id===reportId&&item.field===field.key);
    const values=(field.sample_values||[]).slice(0,12);
    return `<div class="stats-field"><div class="stats-field-grid"><div><div class="stats-field-name">${esc(field.label||field.key)}</div><div class="stats-field-key">${esc(field.key)} · ${esc(field.type||"text")}</div><div class="stats-chips">${values.map(value=>`<span class="stats-chip">${esc(value)}</span>`).join("")||'<span class="small stats-muted">No sample values</span>'}</div></div><div><label>Match this data to a Filter</label><div class="stats-match"><select data-display-map="${esc(reportId)}|${esc(field.key)}"><option value="">— no Filter —</option>${state.filters.map(filter=>`<option value="${esc(filter.id)}" ${mapped?.filter_id===filter.id?"selected":""}>${esc(filter.name)}</option>`).join("")}</select>${mapped?`<span class="stats-pill">Matched: ${esc(filterBy(mapped.filter_id)?.name||mapped.filter_id)}</span>`:""}</div><details><summary class="small" style="cursor:pointer;margin-top:7px">Create a new Filter from this field</summary><div class="stats-create-inline"><input data-new-filter-name="${esc(reportId)}|${esc(field.key)}" placeholder="Example: Team"><button class="btn" data-action="create-filter-for-field" data-report="${esc(reportId)}" data-field="${esc(field.key)}">Create & Match</button></div></details></div></div></div>`;
  }

  function filterValueOptions(screen,filterId){
    const seen=new Map();
    for(const mapping of screen.display_filter_mappings||[]){
      if(mapping.filter_id!==filterId)continue;
      const inspection=state.inspections[mapping.report_id];
      const field=(inspection?.fields||[]).find(item=>item.key===mapping.field);
      for(const value of field?.sample_values||[]){const key=String(value).casefold?String(value).casefold():String(value).toLowerCase();if(!seen.has(key))seen.set(key,String(value));}
    }
    return [...seen.values()].sort((a,b)=>a.localeCompare(b,undefined,{sensitivity:"base"}));
  }

  function matchedFiltersSummary(screen){
    const ids=(screen.filter_ids||[]).filter(id=>filterMappedAnywhere(screen,id));
    if(!ids.length)return'<div class="small">No Display Filters matched yet. That is okay if this Screen does not need filtering.</div>';
    return `<div class="stats-stack">${ids.map(filterId=>{const filter=filterBy(filterId);const mappings=(screen.display_filter_mappings||[]).filter(item=>item.filter_id===filterId);const values=filterValueOptions(screen,filterId);const selected=screen.filter_values?.[filterId]||"";return`<div class="stats-filter-card mapped"><div class="stats-filter-value"><div><strong>${esc(filter?.name||filterId)}</strong><div class="stats-meta">${mappings.map(item=>`${esc(reportBy(item.report_id)?.name||item.report_id)} → ${esc(item.field)}`).join(" · ")}</div></div><div><label>Display value</label><select data-screen-filter-value="${esc(filterId)}"><option value="" ${!selected?"selected":""}>All</option>${values.map(value=>`<option value="${esc(value)}" ${value===selected?"selected":""}>${esc(value)}</option>`).join("")}</select></div></div></div>`;}).join("")}</div>`;
  }

  function stepMatchFilters(screen){
    const reports=selectedReports(screen);
    return `<div class="stats-step-page"><div class="stats-explain"><strong>Display Filters only.</strong> Look at the real pulled rows and values below, then tell Stats what each reusable Filter means in each Report. The same Filter can map to different field names in different Reports.</div>
      ${reports.map(report=>{const inspection=state.inspections[report.id];return`<div class="stats-screen-report"><div class="stats-toolbar"><div><h3 style="margin:0">${esc(report.name)}</h3><div class="stats-meta">${inspection?`${inspection.total_rows||0} pulled rows`:"Loading pulled data…"}</div></div><button class="btn" data-action="reload-inspection" data-id="${esc(report.id)}">Refresh pulled data</button></div>${inspection?`${inspectionTable(inspection,5)}<div class="stats-separator"></div><div class="stats-stack">${(inspection.fields||[]).map(field=>fieldMatchRow(screen,report.id,field)).join("")}</div>`:'<div class="small">Loading…</div>'}</div>`;}).join("")}
      <div class="stats-subcard"><h3 style="margin-top:0">Filters on this Screen</h3><div class="small" style="margin-bottom:9px">After a Filter is matched to data, choose the value this Screen should display. “All” keeps every pulled row.</div>${matchedFiltersSummary(screen)}</div>
    </div>`;
  }

  function tableFor(screen,reportId){
    screen.tables=screen.tables||[];let table=screen.tables.find(item=>item.report_id===reportId);
    if(!table){const fields=reportBy(reportId)?.fields||[];table={report_id:reportId,columns:fields.slice(0,8).map(field=>field.key),sort_field:"",sort_direction:"desc",limit:100};screen.tables.push(table);}
    return table;
  }

  function stepCreateTable(screen){
    return `<div class="stats-step-page"><div class="stats-explain">Choose what each Report contributes to the Screen. The preview uses the real pulled rows after your Display Filter mappings and selected values are applied.</div>
      ${selectedReports(screen).map(report=>{const fields=report.fields||[];const table=tableFor(screen,report.id);return`<div class="stats-screen-report"><h3 style="margin-top:0">${esc(report.name)}</h3><div class="stats-columns">${fields.map(field=>`<label class="stats-check"><input type="checkbox" data-table-column="${esc(report.id)}|${esc(field.key)}" ${(table.columns||[]).includes(field.key)?"checked":""}><span>${esc(field.label||field.key)}</span></label>`).join("")}</div><div class="grid" style="margin-top:10px"><div><label>Sort by</label><select data-table-setting="sort_field|${esc(report.id)}"><option value="">Source order</option>${fields.map(field=>`<option value="${esc(field.key)}" ${table.sort_field===field.key?"selected":""}>${esc(field.label||field.key)}</option>`).join("")}</select></div><div><label>Direction</label><select data-table-setting="sort_direction|${esc(report.id)}"><option value="desc" ${table.sort_direction!=="asc"?"selected":""}>High to low</option><option value="asc" ${table.sort_direction==="asc"?"selected":""}>Low to high</option></select></div><div><label>Rows</label><input type="number" min="1" max="500" data-table-setting="limit|${esc(report.id)}" value="${Number(table.limit||100)}"></div></div></div>`;}).join("")}
      <div><div class="stats-toolbar"><div><h3 style="margin:0">Live Preview</h3><div class="small">Updates as you change columns, sorting or Filter values.</div></div><button class="btn" data-action="refresh-screen-preview">Refresh Preview</button></div>${screenPreview()}</div>
    </div>`;
  }

  function screenPreview(){
    const payload=state.editor?.preview;if(!payload)return'<div class="stats-preview"><div class="small">Preview will appear here.</div></div>';
    const sections=payload.sections||[];
    return `<div class="stats-preview"><div class="stats-preview-grid">${sections.map(section=>`<div class="stats-preview-section"><h4>${esc(section.report_name)}</h4><div class="stats-meta">${section.total_rows||0} matching rows</div><div class="stats-preview-wrap"><table><thead><tr>${(section.fields||[]).map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${(section.rows||[]).slice(0,12).map(row=>`<tr>${(section.fields||[]).map(field=>`<td>${esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("")||'<tr><td>No matching rows</td></tr>'}</tbody></table></div></div>`).join("")||'<div class="small">No report sections.</div>'}</div></div>`;
  }

  function stepTheme(screen){
    return `<div class="stats-step-page"><div class="stats-subcard"><h3 style="margin-top:0">Theme</h3><label class="stats-check"><input type="radio" name="statsThemeMode" data-screen-theme="inherited" ${screen.theme_mode!=="custom"?"checked":""}><span><strong>Inherited</strong><br><span class="small">Use the winning team’s theme when a winning team can be resolved from displayed data.</span></span></label><label class="stats-check" style="margin-top:8px"><input type="radio" name="statsThemeMode" data-screen-theme="custom" ${screen.theme_mode==="custom"?"checked":""}><span><strong>Custom</strong><br><span class="small">This Screen owns its own theme and artwork.</span></span></label>${screen.id&&screen.theme_mode==="custom"?`<div class="stats-actions"><button class="btn" data-action="open-screen-theme" data-id="${esc(screen.id)}">Open Theme Editor</button></div>`:screen.theme_mode==="custom"?'<div class="small" style="margin-top:9px">Save the Screen and the Theme Editor will open.</div>':""}</div><div class="stats-explain">Theme choice changes appearance only. Report selection and Display Filters stay owned by this Screen.</div></div>`;
  }

  function screenEditor(){
    const editor=state.editor;if(editor?.type!=="screen")return"";const screen=editor.value;
    const pages=[stepChooseData,stepMatchFilters,stepCreateTable,stepTheme];
    return `<div class="stats-editor"><div class="stats-toolbar"><div><div class="stats-kicker">Screen Builder</div><h2 style="margin:2px 0">${screen.id?`Edit ${esc(screen.name)}`:"Create Screen"}</h2></div><button class="btn" data-action="close-editor">Close</button></div>${screenSteps(editor)}${pages[editor.step](screen)}<div class="stats-actions" style="justify-content:space-between"><button class="btn" data-action="screen-back" ${editor.step===0?"disabled":""}>Back</button><div class="row">${editor.step<3?'<button class="btn primary" data-action="screen-next">Next</button>':'<button class="btn primary" data-action="save-screen">Save Screen</button>'}</div></div></div>`;
  }

  function screensView(){
    return `<div class="stats-toolbar"><div><h2 class="stats-section-title">Screens</h2><div class="small">Screens turn pulled Reports into something people actually see.</div></div><button class="btn primary" data-action="new-screen">+ Screen</button></div>${filterLibrary()}${screenEditor()}${themeEditor()}<div class="stats-stack" style="margin-top:12px">${state.screens.map(screen=>`<div class="stats-item"><div class="stats-toolbar"><div><h3 style="margin:0">${esc(screen.name)}</h3><div class="stats-meta">${screen.kind==="builtin"?`Built-in · ${esc(screen.mode||"")}`:`${(screen.reports||[]).length} Reports · ${(screen.filter_ids||[]).length} Filters · ${esc(screen.theme_mode||"inherited")} theme`}</div></div><div class="row">${screen.kind!=="builtin"?`<button class="btn" data-action="edit-screen" data-id="${esc(screen.id)}">Edit</button>${screen.theme_mode==="custom"?`<button class="btn" data-action="open-screen-theme" data-id="${esc(screen.id)}">Theme</button>`:""}<button class="btn danger" data-action="delete-screen" data-id="${esc(screen.id)}">Delete</button>`:""}<button class="btn primary" data-action="show-screen" data-id="${esc(screen.id)}">Show Now</button></div></div></div>`).join("")}</div>`;
  }

  function displayView(){
    const display=state.display||{};const rotation=display.rotation_screen_ids||[];
    return `<div class="stats-toolbar"><div><h2 class="stats-section-title">Display</h2><div class="small">Display owns playback only: which Screen is active and which Screens rotate.</div></div></div>
      <div class="stats-subcard"><div class="grid"><div><label>Active Screen</label><select data-display-setting="active_screen_id">${state.screens.map(screen=>`<option value="${esc(screen.id)}" ${display.active_screen_id===screen.id?"selected":""}>${esc(screen.name)}</option>`).join("")}</select></div><div><label>Rotation time (seconds)</label><input type="number" min="5" max="3600" data-display-setting="rotation_seconds" value="${Number(display.rotation_seconds||15)}"></div></div><label class="stats-check" style="margin-top:10px"><input type="checkbox" data-display-setting="rotation_enabled" ${display.rotation_enabled?"checked":""}><span>Rotate through selected Screens</span></label></div>
      <div class="stats-subcard" style="margin-top:10px"><h3 style="margin-top:0">Screens in Rotation</h3><div class="stats-stack">${state.screens.map(screen=>{const index=rotation.indexOf(screen.id);return`<div class="stats-order"><input type="checkbox" data-rotation="${esc(screen.id)}" ${index>=0?"checked":""}><div><strong>${esc(screen.name)}</strong>${index>=0?`<div class="stats-meta">Position ${index+1}</div>`:""}</div>${index>=0?`<div class="row"><button class="btn" data-action="rotation-up" data-id="${esc(screen.id)}">↑</button><button class="btn" data-action="rotation-down" data-id="${esc(screen.id)}">↓</button></div>`:""}</div>`;}).join("")}</div></div>
      <div class="stats-subcard" style="margin-top:10px"><h3 style="margin-top:0">Temporary Data Override</h3><div class="small">This is separate from Display Filters. It temporarily changes the date/data window used by Reports and does not change Screen filter mappings.</div><div class="stats-meta" style="margin-top:7px">${display.temporary_data?.active?`Active: ${esc(display.temporary_data.start)} to ${esc(display.temporary_data.end)}`:"No temporary data override active."}</div></div>
      <div class="stats-actions"><button class="btn primary" data-action="save-display">Save Display</button></div>`;
  }

  function themeEditor(){
    const editor=state.themeEditor;if(!editor)return"";const theme=editor.theme||{};const manifest=editor.manifest||{};
    return `<div class="stats-editor"><div class="stats-toolbar"><div><div class="stats-kicker">Theme Editor</div><h3 style="margin:2px 0">${esc(screenBy(editor.screenId)?.name||"Custom Screen")}</h3></div><button class="btn" data-action="close-theme-editor">Close</button></div><label class="stats-check"><input type="checkbox" data-theme-setting="enabled" ${theme.enabled!==false?"checked":""}><span>Theme enabled</span></label><div class="stats-theme-colors" style="margin-top:10px">${(manifest.colors||[]).map(item=>`<label class="stats-theme-color"><input type="color" data-theme-color="${esc(item.key)}" value="${esc(theme.colors?.[item.key]||"#111111")}"><span>${esc(item.label)}</span></label>`).join("")}</div><div class="stats-separator"></div><h4>Artwork</h4><div class="stats-columns">${(manifest.assets||[]).map(item=>`<div class="stats-subcard"><strong>${esc(item.label)}</strong>${theme.assets?.[item.key]?`<div class="small" style="margin:5px 0">Applied</div>`:'<div class="small" style="margin:5px 0">None</div>'}<input type="file" accept="image/png,image/jpeg,image/webp" data-theme-file="${esc(item.key)}"><button class="btn" style="margin-top:7px" data-action="reset-theme-asset" data-key="${esc(item.key)}">Reset</button></div>`).join("")}</div><div class="stats-actions"><button class="btn primary" data-action="save-screen-theme">Save Theme</button><button class="btn danger" data-action="reset-screen-theme">Reset Theme</button></div></div>`;
  }

  function render(){
    if(!root)return;root.querySelectorAll(".stats-tab").forEach(button=>button.classList.toggle("active",button.dataset.tab===state.tab));
    const body=root.querySelector("#statsWorkspaceBody");
    body.innerHTML=`<div class="stats-status">${esc(state.message||"")}</div>${state.tab==="data"?dataView():state.tab==="screens"?screensView():displayView()}`;
  }

  async function ensureSelectedInspections(){
    const editor=state.editor;if(editor?.type!=="screen")return;
    await Promise.all((editor.value.reports||[]).map(id=>loadInspection(id).catch(err=>{state.message=err.message;return null;})));
  }

  function screenPayload(){
    const screen=clone(state.editor.value);
    screen.filter_ids=[...new Set((screen.filter_ids||[]).filter(id=>(screen.display_filter_mappings||[]).some(item=>item.filter_id===id)))];
    screen.filter_values=screen.filter_values||{};
    return screen;
  }

  function schedulePreview(){
    clearTimeout(previewTimer);previewTimer=setTimeout(refreshScreenPreview,250);
  }

  async function refreshScreenPreview(){
    if(state.editor?.type!=="screen"||state.editor.step<2)return;
    try{const result=await api("/api/screens/preview",json("POST",screenPayload()));state.editor.preview=result.payload;state.message="";}catch(err){state.editor.preview=null;state.message=err.message;}render();
  }

  function updateScreenMapping(reportId,field,filterId){
    const screen=state.editor.value;screen.display_filter_mappings=screen.display_filter_mappings||[];screen.filter_ids=screen.filter_ids||[];
    screen.display_filter_mappings=screen.display_filter_mappings.filter(item=>!(item.report_id===reportId&&item.field===field));
    if(filterId){
      screen.display_filter_mappings=screen.display_filter_mappings.filter(item=>!(item.report_id===reportId&&item.filter_id===filterId));
      screen.display_filter_mappings.push({filter_id:filterId,report_id:reportId,field});
      if(!screen.filter_ids.includes(filterId))screen.filter_ids.push(filterId);
    }
    const used=new Set(screen.display_filter_mappings.map(item=>item.filter_id));
    screen.filter_ids=screen.filter_ids.filter(id=>used.has(id));
    for(const id of Object.keys(screen.filter_values||{}))if(!used.has(id))delete screen.filter_values[id];
  }

  async function createFilter(name){
    const data=await api("/api/filters",json("POST",{name}));
    await loadAll();return data.filter;
  }

  async function openScreenEditor(screen){
    state.themeEditor=null;state.editor={type:"screen",value:clone(screen||emptyScreen()),step:0,preview:null};
    state.editor.value.filter_ids=state.editor.value.filter_ids||[];
    state.editor.value.display_filter_mappings=state.editor.value.display_filter_mappings||[];
    state.editor.value.filter_values=state.editor.value.filter_values||{};
    state.editor.value.tables=state.editor.value.tables||[];
    render();
  }

  async function openThemeEditor(screenId){
    const data=await api(`/api/screen-themes/${encodeURIComponent(screenId)}`);
    state.themeEditor={screenId,theme:data.theme,manifest:data.manifest};state.editor=null;state.tab="screens";render();
  }

  async function handleClick(event){
    const button=event.target.closest("button");if(!button)return;
    if(button.dataset.tab){state.tab=button.dataset.tab;state.editor=null;state.themeEditor=null;state.message="";render();return;}
    const action=button.dataset.action;if(!action)return;
    try{
      state.message="";
      if(action==="close-editor"){state.editor=null;render();return;}
      if(action==="new-source"){state.editor={type:"source",value:{name:"Tableau",adapter:"tableau",connection:{}}};render();return;}
      if(action==="edit-source"){state.editor={type:"source",value:clone(sourceBy(button.dataset.id))};render();return;}
      if(action==="save-source"){
        const source=state.editor.value;const method=source.id?"PUT":"POST";const url=source.id?`/api/data/sources/${encodeURIComponent(source.id)}`:"/api/data/sources";
        await api(url,json(method,source));await loadAll();state.editor=null;state.message="Source saved.";render();return;
      }
      if(action==="test-source"||action==="test-source-card"){
        const id=button.dataset.id||state.editor.value.id;if(!id)throw new Error("Save the Source first.");const result=await api(`/api/data/sources/${encodeURIComponent(id)}/test`,{method:"POST"});state.message=`Connected · ${result.selected_rows??result.total_rows??0} rows visible`;render();return;
      }
      if(action==="new-report"){
        state.editor={type:"report",value:{name:"New Report",source_id:button.dataset.id,kind:"table",source_config:{export:"auto",filters:[]},runtime:{date_mode:"current_month"}},workbooks:[],views:[],columns:null};render();return;
      }
      if(action==="edit-report"){
        const report=clone(reportBy(button.dataset.id));state.editor={type:"report",value:report,workbooks:[],views:[],columns:null};render();return;
      }
      if(action==="load-workbooks"){
        const sourceId=state.editor.value.source_id||state.sources[0]?.id;if(!sourceId)throw new Error("Choose a Source first.");state.message="Loading workbooks…";render();const data=await api(`/api/data/sources/${encodeURIComponent(sourceId)}/workbooks`);state.editor.workbooks=data.workbooks||[];state.message=`${state.editor.workbooks.length} workbooks found.`;render();return;
      }
      if(action==="read-report"){
        if(!state.editor.value.id)throw new Error("Save the Report first, then read it.");state.message="Reading Report fields and values…";render();const data=await api(`/api/data/reports/${encodeURIComponent(state.editor.value.id)}/columns`,json("POST",state.editor.value.source_config||{}));state.editor.columns=data;state.message=`${(data.headers||data.choices||[]).length} fields found.`;render();return;
      }
      if(action==="preview-report"){
        if(!state.editor.value.id)throw new Error("Save the Report first.");const result=await api(`/api/data/reports/${encodeURIComponent(state.editor.value.id)}/preview`,json("POST",state.editor.value.source_config||{}));state.message=`Preview read ${result.reps??result.preview?.rows?.length??0} rows.`;render();return;
      }
      if(action==="save-report"){
        const report=state.editor.value;const method=report.id?"PUT":"POST";const url=report.id?`/api/data/reports/${encodeURIComponent(report.id)}`:"/api/data/reports";const data=await api(url,json(method,report));await loadAll();state.editor={type:"report",value:clone(data.report),workbooks:[],views:[],columns:null};state.message="Report saved.";render();return;
      }
      if(action==="refresh-report"||action==="refresh-report-card"){
        const id=button.dataset.id||state.editor.value.id;if(!id)throw new Error("Save the Report first.");state.message="Pulling Report…";render();await api(`/api/data/reports/${encodeURIComponent(id)}/refresh`,{method:"POST"});delete state.inspections[id];await loadAll();state.message="Report pulled.";render();return;
      }
      if(action==="delete-report"){
        if(confirm("Delete this Report?")){await api(`/api/data/reports/${encodeURIComponent(button.dataset.id)}`,{method:"DELETE"});delete state.inspections[button.dataset.id];await loadAll();state.message="Report deleted.";render();}return;
      }
      if(action==="inspect-report"||action==="reload-inspection"){
        state.message="Loading real pulled data…";render();await loadInspection(button.dataset.id,true);state.message="Pulled data loaded.";render();return;
      }
      if(action==="add-data-filter"){
        const cfg=state.editor.value.source_config||(state.editor.value.source_config={});cfg.filters=cfg.filters||[];cfg.filters.push({field:"",value:""});render();return;
      }
      if(action==="drop-data-filter"){state.editor.value.source_config.filters.splice(Number(button.dataset.index),1);render();return;}
      if(action==="create-filter"){
        const input=root.querySelector("#statsNewFilterName");const name=String(input?.value||"").trim();if(!name)throw new Error("Enter a Filter name.");await createFilter(name);state.message="Filter created.";render();return;
      }
      if(action==="delete-filter"){
        if(confirm("Delete this Filter?")){await api(`/api/filters/${encodeURIComponent(button.dataset.id)}`,{method:"DELETE"});await loadAll();state.message="Filter deleted.";render();}return;
      }
      if(action==="new-screen"){await openScreenEditor(emptyScreen());return;}
      if(action==="edit-screen"){await openScreenEditor(screenBy(button.dataset.id));return;}
      if(action==="screen-back"){state.editor.step=Math.max(0,state.editor.step-1);render();return;}
      if(action==="screen-next"){
        if(state.editor.step===0&&!(state.editor.value.reports||[]).length)throw new Error("Choose at least one Report.");
        state.editor.step=Math.min(3,state.editor.step+1);if(state.editor.step===1)await ensureSelectedInspections();if(state.editor.step===2)await refreshScreenPreview();render();return;
      }
      if(action==="create-filter-for-field"){
        const selector=`[data-new-filter-name="${CSS.escape(button.dataset.report+'|'+button.dataset.field)}"]`;const input=root.querySelector(selector);const name=String(input?.value||"").trim();if(!name)throw new Error("Enter a Filter name.");const created=await createFilter(name);updateScreenMapping(button.dataset.report,button.dataset.field,created.id);state.message=`Created ${created.name} and matched it.`;await ensureSelectedInspections();render();return;
      }
      if(action==="refresh-screen-preview"){await refreshScreenPreview();return;}
      if(action==="save-screen"){
        const screen=screenPayload();const wasNew=!screen.id;const method=screen.id?"PUT":"POST";const url=screen.id?`/api/screens/${encodeURIComponent(screen.id)}`:"/api/screens";const result=await api(url,json(method,screen));await loadAll();state.editor=null;state.message="Screen saved.";render();if(wasNew&&result.screen.theme_mode==="custom")await openThemeEditor(result.screen.id);return;
      }
      if(action==="delete-screen"){
        if(confirm("Delete this Screen?")){await api(`/api/screens/${encodeURIComponent(button.dataset.id)}`,{method:"DELETE"});await loadAll();state.message="Screen deleted.";render();}return;
      }
      if(action==="show-screen"){
        state.display.active_screen_id=button.dataset.id;state.display.rotation_enabled=false;await api("/api/display",json("PUT",state.display));await loadAll();state.message="TV switched to this Screen.";render();return;
      }
      if(action==="rotation-up"||action==="rotation-down"){
        const list=state.display.rotation_screen_ids||[];const index=list.indexOf(button.dataset.id);const target=action==="rotation-up"?index-1:index+1;if(index>=0&&target>=0&&target<list.length){[list[index],list[target]]=[list[target],list[index]];render();}return;
      }
      if(action==="save-display"){await api("/api/display",json("PUT",state.display));await loadAll();state.message="Display saved.";render();return;}
      if(action==="open-screen-theme"){await openThemeEditor(button.dataset.id);return;}
      if(action==="close-theme-editor"){state.themeEditor=null;render();return;}
      if(action==="save-screen-theme"){
        const editor=state.themeEditor;const data=await api(`/api/screen-themes/${encodeURIComponent(editor.screenId)}`,json("PUT",editor.theme));editor.theme=data.theme;state.message="Theme saved.";render();return;
      }
      if(action==="reset-screen-theme"){
        const editor=state.themeEditor;const data=await api(`/api/screen-themes/${encodeURIComponent(editor.screenId)}`,{method:"DELETE"});editor.theme=data.theme;state.message="Theme reset.";render();return;
      }
      if(action==="reset-theme-asset"){
        const editor=state.themeEditor;const data=await api(`/api/screen-themes/${encodeURIComponent(editor.screenId)}/assets/${encodeURIComponent(button.dataset.key)}`,{method:"DELETE"});editor.theme=data.theme;state.message="Artwork reset.";render();return;
      }
    }catch(err){state.message=err.message;render();}
  }

  async function handleInput(event){
    const target=event.target;
    try{
      if(target.dataset.sourceEdit){
        const source=state.editor.value;const key=target.dataset.sourceEdit;if(["server","site","pat_name"].includes(key)){source.connection=source.connection||{};source.connection[key]=target.value;}else if(key==="secret")source.secret=target.value;else source[key]=target.value;return;
      }
      if(target.dataset.reportEdit){
        const report=state.editor.value;report.source_config=report.source_config||{};report.runtime=report.runtime||{};const key=target.dataset.reportEdit;
        if(key==="name"||key==="source_id")report[key]=target.value;
        else if(["workbook","sheet","export"].includes(key)){report.source_config[key]=target.value;if(key==="workbook"){state.editor.views=[];if(target.value){const sourceId=report.source_id;const data=await api(`/api/data/sources/${encodeURIComponent(sourceId)}/workbooks/${encodeURIComponent(target.value)}/views`);state.editor.views=data.views||[];render();}}}
        else if(key==="market")report.runtime.market=target.value;
        else report.runtime[key]=target.value;
        return;
      }
      if(target.dataset.reportMap){
        const report=state.editor.value;const mapping=report.source_config.mapping||(report.source_config.mapping={metrics:{}});const key=target.dataset.reportMap;if(key.startsWith("metric:")){mapping.metrics=mapping.metrics||{};mapping.metrics[key.slice(7)]=target.value;}else mapping[key]=target.value;return;
      }
      if(target.dataset.dataFilterField!==undefined){state.editor.value.source_config.filters[Number(target.dataset.dataFilterField)].field=target.value;return;}
      if(target.dataset.dataFilterValue!==undefined){state.editor.value.source_config.filters[Number(target.dataset.dataFilterValue)].value=target.value;return;}
      if(target.dataset.screenName!==undefined){state.editor.value.name=target.value;return;}
      if(target.dataset.screenReport){
        const screen=state.editor.value;const id=target.dataset.screenReport;screen.reports=screen.reports||[];
        if(target.checked&&!screen.reports.includes(id))screen.reports.push(id);
        if(!target.checked){screen.reports=screen.reports.filter(value=>value!==id);screen.tables=(screen.tables||[]).filter(table=>table.report_id!==id);screen.display_filter_mappings=(screen.display_filter_mappings||[]).filter(mapping=>mapping.report_id!==id);}
        const used=new Set((screen.display_filter_mappings||[]).map(mapping=>mapping.filter_id));screen.filter_ids=(screen.filter_ids||[]).filter(filterId=>used.has(filterId));render();return;
      }
      if(target.dataset.displayMap){
        const [reportId,field]=target.dataset.displayMap.split("|");updateScreenMapping(reportId,field,target.value);render();schedulePreview();return;
      }
      if(target.dataset.screenFilterValue){state.editor.value.filter_values=state.editor.value.filter_values||{};state.editor.value.filter_values[target.dataset.screenFilterValue]=target.value;render();schedulePreview();return;}
      if(target.dataset.tableColumn){
        const [reportId,key]=target.dataset.tableColumn.split("|");const table=tableFor(state.editor.value,reportId);if(target.checked&&!table.columns.includes(key))table.columns.push(key);if(!target.checked)table.columns=table.columns.filter(value=>value!==key);schedulePreview();return;
      }
      if(target.dataset.tableSetting){
        const [setting,reportId]=target.dataset.tableSetting.split("|");const table=tableFor(state.editor.value,reportId);table[setting]=setting==="limit"?Number(target.value):target.value;schedulePreview();return;
      }
      if(target.dataset.screenTheme){state.editor.value.theme_mode=target.dataset.screenTheme;render();return;}
      if(target.dataset.displaySetting){const key=target.dataset.displaySetting;state.display[key]=key==="rotation_enabled"?target.checked:key==="rotation_seconds"?Number(target.value):target.value;return;}
      if(target.dataset.rotation){const list=state.display.rotation_screen_ids||(state.display.rotation_screen_ids=[]);if(target.checked&&!list.includes(target.dataset.rotation))list.push(target.dataset.rotation);if(!target.checked){const index=list.indexOf(target.dataset.rotation);if(index>=0)list.splice(index,1);}render();return;}
      if(target.dataset.themeSetting){state.themeEditor.theme[target.dataset.themeSetting]=target.dataset.themeSetting==="enabled"?target.checked:target.value;return;}
      if(target.dataset.themeColor){state.themeEditor.theme.colors=state.themeEditor.theme.colors||{};state.themeEditor.theme.colors[target.dataset.themeColor]=target.value;return;}
      if(target.dataset.themeFile&&target.files?.[0]){
        const editor=state.themeEditor;const form=new FormData();form.append("asset",target.files[0]);const response=await fetch(`/api/screen-themes/${encodeURIComponent(editor.screenId)}/assets/${encodeURIComponent(target.dataset.themeFile)}`,{method:"POST",body:form});const data=await response.json();if(!response.ok||data.ok===false)throw new Error(data.error||"Upload failed");editor.theme=data.theme;state.message="Artwork applied.";render();return;
      }
    }catch(err){state.message=err.message;render();}
  }

  function mount(){
    if(root)return;const app=document.getElementById("appWrap");if(!app)return;removeObsoleteDataMarkup();const holder=document.createElement("div");holder.innerHTML=shell();root=holder.firstElementChild;const note=app.querySelector(".persist-note");(note||app.firstElementChild).insertAdjacentElement("afterend",root);root.addEventListener("click",handleClick);root.addEventListener("input",handleInput);root.addEventListener("change",handleInput);loadAll().then(render).catch(err=>{state.message=err.message;render();});
  }
  function wait(){const app=document.getElementById("appWrap");if(app&&getComputedStyle(app).display!=="none")mount();else setTimeout(wait,180);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",wait,{once:true});else wait();
})();
