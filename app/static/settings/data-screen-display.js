/* Normalized Stats workspace: Sources -> Reports -> Screens -> Display. */
(function(){
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const rootState={tab:"data",sources:[],reports:[],screens:[],display:{},editor:null,columns:null,preview:null,busy:false,message:""};
  let root=null, previewTimer=null;

  async function api(url,options={}){
    const r=await fetch(url,{cache:"no-store",...options,headers:{"Content-Type":"application/json",...(options.headers||{})}});
    let d={}; try{d=await r.json();}catch(_){ }
    if(!r.ok||d.ok===false) throw new Error(d.error||`Request failed (${r.status})`);
    return d;
  }
  const json=(method,body)=>({method,body:JSON.stringify(body||{})});

  function removeLegacyDataUI(){
    ["openDataSource","sourceStatusLine","displaySettingsTitle"].forEach(id=>{
      const el=document.getElementById(id); const card=el?.closest(".card"); if(card) card.style.display="none";
    });
    const overlay=document.getElementById("dataSourceOverlay"); if(overlay) overlay.remove();
    const active=document.getElementById("activeMode"); if(active?.parentElement) active.parentElement.style.display="none";
  }

  async function loadAll(){
    const [sources,reports,screens,display]=await Promise.all([
      api("/api/data/sources"), api("/api/data/reports"), api("/api/screens"), api("/api/display")
    ]);
    rootState.sources=sources.sources||[]; rootState.reports=reports.reports||[]; rootState.screens=screens.screens||[]; rootState.display=display;
  }

  function sourceBy(id){return rootState.sources.find(x=>x.id===id)||null;}
  function reportBy(id){return rootState.reports.find(x=>x.id===id)||null;}
  function screenBy(id){return rootState.screens.find(x=>x.id===id)||null;}
  function fieldsFor(reportId){return reportBy(reportId)?.fields||[];}

  function shell(){
    return `<style id="statsWorkspaceStyles">
      #statsWorkspace{margin:18px 0}.stats-tabs{display:flex;gap:6px;border-bottom:1px solid var(--line);margin-bottom:14px}.stats-tab{border:0;border-bottom:3px solid transparent;background:transparent;color:var(--muted);padding:11px 15px;font-weight:900;cursor:pointer}.stats-tab.active{color:var(--accent);border-color:var(--accent)}
      .stats-toolbar{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}.stats-stack{display:grid;gap:10px}.stats-item{border:1px solid var(--line);background:#0f0f0f;padding:13px}.stats-item h3{margin:0}.stats-meta{color:var(--muted);font-size:12px;margin-top:4px}.stats-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.stats-editor{border:1px solid #52451e;background:#111;padding:15px;margin:12px 0}.stats-editor h3{margin-top:0}.stats-subcard{border:1px solid #292929;padding:12px;background:#0c0c0c;margin-top:10px}.stats-columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:6px}.stats-check{display:flex;gap:7px;align-items:center;border:1px solid #272727;padding:7px}.stats-check input{width:auto}.stats-status{min-height:18px;color:var(--accent);margin:8px 0}.stats-preview{border:1px solid #333;background:#080808;padding:12px;max-height:480px;overflow:auto}.stats-preview table{width:100%;border-collapse:collapse;font-size:12px}.stats-preview th,.stats-preview td{padding:5px 7px;border-bottom:1px solid #242424;text-align:left}.stats-preview th{color:#aaa}.stats-order{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;border:1px solid #292929;padding:9px}.stats-order input{width:auto}.stats-danger{color:#ffaaaa}.stats-theme-colors{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}.stats-theme-color{display:grid;grid-template-columns:42px 1fr;gap:8px;align-items:center}.stats-theme-color input[type=color]{height:40px;padding:2px}.stats-report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:10px}
      @media(max-width:760px){.stats-editor .grid{grid-template-columns:1fr}.stats-order{grid-template-columns:auto 1fr}.stats-order .stats-actions{grid-column:1/-1}}
    </style>
    <div class="card" id="statsWorkspace">
      <div class="stats-tabs"><button class="stats-tab" data-tab="data">Data</button><button class="stats-tab" data-tab="screens">Screens</button><button class="stats-tab" data-tab="display">Display</button></div>
      <div id="statsWorkspaceBody"></div>
    </div>`;
  }

  function sourceEditor(){
    const e=rootState.editor;if(!e||e.type!=="source")return""; const s=e.value||{}; const c=s.connection||{};
    return `<div class="stats-editor"><div class="stats-toolbar"><h3>${s.id?"Edit Source":"Add Source"}</h3><button class="btn" data-action="close-editor">Close</button></div>
      <div class="grid"><div><label>Name</label><input data-edit="source-name" value="${esc(s.name||"Tableau")}"></div><div><label>Adapter</label><select data-edit="source-adapter"><option value="tableau">Tableau</option></select></div><div><label>Server</label><input data-edit="source-server" value="${esc(c.server||"")}" placeholder="https://tableau.example.com"></div><div><label>Site</label><input data-edit="source-site" value="${esc(c.site||"")}"></div><div><label>PAT name</label><input data-edit="source-pat" value="${esc(c.pat_name||"")}"></div><div><label>PAT secret</label><input type="password" data-edit="source-secret" placeholder="${c.secret_configured?"Saved — leave blank to keep":"Enter PAT secret"}"></div></div>
      <div class="stats-actions"><button class="btn primary" data-action="save-source">Save Source</button>${s.id?`<button class="btn" data-action="test-source">Test Connection</button>`:""}</div></div>`;
  }

  function mappingEditor(report){
    const d=rootState.columns;if(!d)return`<div class="small">Read Report to load fields and filters.</div>`;
    const choices=(d.choices||d.headers||[]).map(String); const mapping=report.source_config?.mapping||{};
    if(report.kind!=="rep_performance") return `<div class="small">${choices.length} fields found. Generic table reports keep the source columns as returned.</div>`;
    const metrics=(report.fields||[]).filter(f=>["number","percent","currency"].includes(f.type));
    const select=(key,label,current)=>`<div><label>${esc(label)}</label><select data-map="${esc(key)}"><option value="">— not mapped —</option>${choices.map(v=>`<option value="${esc(v)}" ${v===current?"selected":""}>${esc(v)}</option>`).join("")}</select></div>`;
    return `<div class="stats-subcard"><h4>Field Mapping</h4><div class="grid">${select("rep_name","Sales Rep",mapping.rep_name||"")}${select("home_branch","Home Branch",mapping.home_branch||"")}${select("team","Team",mapping.team||"")}</div><div class="grid" style="margin-top:10px">${metrics.map(m=>select(`metric:${m.key}`,m.label,mapping.metrics?.[m.key]||"")).join("")}</div></div>`;
  }

  function filterEditor(report){
    const catalog=rootState.columns?.filter_fields||[]; const filters=report.source_config?.filters||[];
    if(!rootState.columns)return"";
    return `<div class="stats-subcard"><div class="stats-toolbar"><h4 style="margin:0">Report Filters</h4><button class="btn" data-action="add-report-filter">+ Filter</button></div>${filters.map((f,i)=>`<div class="grid" style="margin-top:7px"><select data-filter-field="${i}"><option value="">Field</option>${catalog.map(x=>`<option value="${esc(x.field)}" ${x.field===f.field?"selected":""}>${esc(x.field)}</option>`).join("")}</select><div class="row"><input data-filter-value="${i}" value="${esc(f.value||"")}" placeholder="Value"><button class="btn danger" data-action="drop-report-filter" data-index="${i}">Remove</button></div></div>`).join("")||'<div class="small">No filters.</div>'}</div>`;
  }

  function reportEditor(){
    const e=rootState.editor;if(!e||e.type!=="report")return""; const r=e.value||{}; const cfg=r.source_config||{}; const run=r.runtime||{};
    const sources=rootState.sources; const sourceId=r.source_id||sources[0]?.id||""; const books=e.workbooks||[]; const views=e.views||[];
    return `<div class="stats-editor"><div class="stats-toolbar"><h3>${r.id?"Edit Report":"Add Report"}</h3><button class="btn" data-action="close-editor">Close</button></div>
      <div class="grid"><div><label>Name</label><input data-edit="report-name" value="${esc(r.name||"New Report")}"></div><div><label>Source</label><select data-edit="report-source">${sources.map(s=>`<option value="${esc(s.id)}" ${s.id===sourceId?"selected":""}>${esc(s.name)}</option>`).join("")}</select></div><div><label>Workbook</label><select data-edit="report-workbook"><option value="">Choose workbook</option>${books.map(b=>`<option value="${esc(b.content_url)}" ${b.content_url===cfg.workbook?"selected":""}>${esc(b.name||b.content_url)}</option>`).join("")}</select></div><div><label>Report / View</label><select data-edit="report-sheet"><option value="">Choose report</option>${views.map(v=>`<option value="${esc(v.content_url)}" ${v.content_url===cfg.sheet?"selected":""}>${esc(v.name||v.content_url)}</option>`).join("")}</select></div><div><label>Export</label><select data-edit="report-export"><option value="auto" ${cfg.export==="auto"?"selected":""}>Auto</option><option value="csv" ${cfg.export==="csv"?"selected":""}>CSV</option><option value="crosstab" ${cfg.export==="crosstab"?"selected":""}>Crosstab</option></select></div><div><label>Date</label><select data-edit="report-date-mode"><option value="current_month" ${run.date_mode!=="custom"?"selected":""}>Current month</option><option value="custom" ${run.date_mode==="custom"?"selected":""}>Custom range</option></select></div><div><label>Start</label><input type="date" data-edit="report-start" value="${esc(run.date_start||"")}"></div><div><label>End</label><input type="date" data-edit="report-end" value="${esc(run.date_end||"")}"></div></div>
      ${r.kind==="product_close"?`<div style="margin-top:10px"><label>Market</label><input data-edit="report-market" value="${esc(run.market||"Olympia")}"></div>`:`<div class="stats-actions"><button class="btn" data-action="load-workbooks">Load Workbooks</button><button class="btn" data-action="read-report">Read Report</button><button class="btn" data-action="preview-report">Preview Data</button></div>${mappingEditor(r)}${filterEditor(r)}`}
      <div class="stats-actions"><button class="btn primary" data-action="save-report">Save Report</button>${r.id?`<button class="btn" data-action="refresh-report">Pull Now</button>`:""}</div></div>`;
  }

  function dataView(){
    return `<div class="stats-toolbar"><div><h2 style="margin:0">Data</h2><div class="small">Sources connect once. Reports define what data Stats reads from each source.</div></div><button class="btn primary" data-action="new-source">+ Source</button></div>${sourceEditor()}${reportEditor()}<div class="stats-stack">${rootState.sources.map(s=>`<div class="stats-item"><div class="stats-toolbar"><div><h3>${esc(s.name)}</h3><div class="stats-meta">${esc(s.adapter)} · ${esc(s.connection?.server||"No server")} · ${s.connection?.secret_configured?"credentials saved":"credentials missing"}</div></div><div class="row"><button class="btn" data-action="edit-source" data-id="${esc(s.id)}">Edit</button><button class="btn" data-action="test-source-card" data-id="${esc(s.id)}">Test</button><button class="btn" data-action="new-report" data-id="${esc(s.id)}">+ Report</button></div></div><div class="stats-report-grid">${(s.reports||[]).map(r=>`<div class="stats-subcard"><strong>${esc(r.name)}</strong><div class="stats-meta">${esc(r.kind)} · ${esc(r.status||"Not refreshed")}${r.last_refresh?` · ${esc(r.last_refresh)}`:""}</div><div class="stats-actions"><button class="btn" data-action="edit-report" data-id="${esc(r.id)}">Edit</button><button class="btn primary" data-action="refresh-report-card" data-id="${esc(r.id)}">Pull Now</button>${!["report-reps","report-products"].includes(r.id)?`<button class="btn danger" data-action="delete-report" data-id="${esc(r.id)}">Delete</button>`:""}</div></div>`).join("")||'<div class="small">No reports yet.</div>'}</div></div>`).join("")||'<div class="small">No sources configured.</div>'}</div>`;
  }

  function filterRow(screen,f,i){
    const selectedReports=screen.reports||[]; const allFields=[]; selectedReports.forEach(id=>fieldsFor(id).forEach(x=>{if(!allFields.some(y=>y.key===x.key))allFields.push(x);}));
    return `<div class="stats-subcard"><div class="grid"><div><label>Scope</label><select data-screen-filter="scope:${i}"><option value="screen" ${f.scope!=="report"?"selected":""}>Whole screen</option><option value="report" ${f.scope==="report"?"selected":""}>One report</option></select></div><div><label>Report</label><select data-screen-filter="report_id:${i}"><option value="">All matching reports</option>${selectedReports.map(id=>`<option value="${esc(id)}" ${f.report_id===id?"selected":""}>${esc(reportBy(id)?.name||id)}</option>`).join("")}</select></div><div><label>Field</label><select data-screen-filter="field:${i}"><option value="">Choose field</option>${allFields.map(x=>`<option value="${esc(x.key)}" ${f.field===x.key?"selected":""}>${esc(x.label||x.key)}</option>`).join("")}</select></div><div><label>Rule</label><select data-screen-filter="operator:${i}">${[["equals","Equals"],["not_equals","Not equal"],["contains","Contains"],["not_contains","Does not contain"]].map(([v,l])=>`<option value="${v}" ${f.operator===v?"selected":""}>${l}</option>`).join("")}</select></div><div><label>Value</label><input data-screen-filter="value:${i}" value="${esc(f.value||"")}"></div><div style="display:flex;align-items:end"><button class="btn danger" data-action="drop-screen-filter" data-index="${i}">Remove</button></div></div></div>`;
  }

  function tableEditor(screen,reportId){
    const fields=fieldsFor(reportId); let t=(screen.tables||[]).find(x=>x.report_id===reportId)||{report_id:reportId,columns:fields.slice(0,8).map(x=>x.key),sort_field:"",sort_direction:"desc",limit:100};
    return `<div class="stats-subcard"><h4>${esc(reportBy(reportId)?.name||reportId)}</h4><div class="stats-columns">${fields.map(f=>`<label class="stats-check"><input type="checkbox" data-table-column="${esc(reportId)}:${esc(f.key)}" ${t.columns?.includes(f.key)?"checked":""}><span>${esc(f.label||f.key)}</span></label>`).join("")}</div><div class="grid" style="margin-top:9px"><div><label>Sort</label><select data-table-setting="sort_field:${esc(reportId)}"><option value="">Source order</option>${fields.map(f=>`<option value="${esc(f.key)}" ${t.sort_field===f.key?"selected":""}>${esc(f.label||f.key)}</option>`).join("")}</select></div><div><label>Direction</label><select data-table-setting="sort_direction:${esc(reportId)}"><option value="desc" ${t.sort_direction!=="asc"?"selected":""}>Highest first</option><option value="asc" ${t.sort_direction==="asc"?"selected":""}>Lowest first</option></select></div><div><label>Rows</label><input type="number" min="1" max="500" data-table-setting="limit:${esc(reportId)}" value="${Number(t.limit||100)}"></div></div></div>`;
  }

  function previewHTML(){
    const p=rootState.preview;if(!p)return'<div class="small">Preview updates here.</div>'; const sections=p.sections||[];
    return sections.map(s=>`<div class="stats-subcard"><strong>${esc(s.report_name)}</strong><table><thead><tr>${(s.fields||[]).map(f=>`<th>${esc(f.label||f.key)}</th>`).join("")}</tr></thead><tbody>${(s.rows||[]).slice(0,8).map(row=>`<tr>${(s.fields||[]).map(f=>`<td>${esc(row[f.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`).join("")||'<div class="small">No matching rows.</div>';
  }

  function screenEditor(){
    const e=rootState.editor;if(!e||e.type!=="screen")return""; const s=e.value;
    return `<div class="stats-editor"><div class="stats-toolbar"><h3>${s.id?"Edit Screen":"Create Screen"}</h3><button class="btn" data-action="close-editor">Close</button></div><div class="grid"><div><label>Name</label><input data-edit="screen-name" value="${esc(s.name||"New Screen")}"></div><div><label>Theme</label><select data-edit="screen-theme"><option value="inherited" ${s.theme_mode!=="custom"?"selected":""}>Inherited from winning team</option><option value="custom" ${s.theme_mode==="custom"?"selected":""}>Custom screen theme</option></select></div></div><h4>Reports</h4><div class="stats-columns">${rootState.reports.map(r=>`<label class="stats-check"><input type="checkbox" data-screen-report="${esc(r.id)}" ${(s.reports||[]).includes(r.id)?"checked":""}><span>${esc(r.name)}</span></label>`).join("")}</div><div class="stats-toolbar" style="margin-top:12px"><h4 style="margin:0">Filters</h4><button class="btn" data-action="add-screen-filter">+ Filter</button></div>${(s.filters||[]).map((f,i)=>filterRow(s,f,i)).join("")||'<div class="small">No screen filters.</div>'}<h4>Tables</h4>${(s.reports||[]).map(id=>tableEditor(s,id)).join("")}<div class="stats-actions"><button class="btn" data-action="preview-screen">Preview</button><button class="btn primary" data-action="save-screen">Save Screen</button>${s.id&&s.theme_mode==="custom"?`<button class="btn" data-action="edit-screen-theme">Theme Editor</button>`:""}</div><div class="stats-preview">${previewHTML()}</div></div>`;
  }

  function themeEditor(){
    const e=rootState.editor;if(!e||e.type!=="theme")return""; const t=e.value.theme||{}; const m=e.value.manifest||{};
    return `<div class="stats-editor"><div class="stats-toolbar"><h3>Theme · ${esc(screenBy(e.screenId)?.name||e.screenId)}</h3><button class="btn" data-action="close-editor">Close</button></div><div class="grid"><div><label>Preset</label><select data-theme="base">${(m.presets||[]).map(p=>`<option value="${esc(p.key)}" ${p.key===t.base?"selected":""}>${esc(p.label)}</option>`).join("")}</select></div><div><label class="row"><input type="checkbox" data-theme="enabled" ${t.enabled!==false?"checked":""}> Enabled</label></div></div><h4>Colors</h4><div class="stats-theme-colors">${(m.colors||[]).map(c=>`<label class="stats-theme-color"><input type="color" data-theme-color="${esc(c.key)}" value="${esc(t.colors?.[c.key]||"#111111")}"><span>${esc(c.label)}</span></label>`).join("")}</div><h4>Artwork</h4>${(m.assets||[]).map(a=>`<div class="stats-subcard"><div class="stats-toolbar"><strong>${esc(a.label)}</strong>${t.assets?.[a.key]?`<span class="small">Applied</span>`:'<span class="small">None</span>'}</div><div class="row"><input type="file" accept="image/png,image/jpeg,image/webp" data-theme-file="${esc(a.key)}"><button class="btn danger" data-action="reset-theme-asset" data-key="${esc(a.key)}">Reset</button></div></div>`).join("")}<div class="stats-actions"><button class="btn primary" data-action="save-screen-theme">Save Theme</button><button class="btn danger" data-action="reset-screen-theme">Reset Theme</button></div></div>`;
  }

  function screensView(){
    return `<div class="stats-toolbar"><div><h2 style="margin:0">Screens</h2><div class="small">A screen combines one or more reports, filters each report, and decides how its tables look.</div></div><button class="btn primary" data-action="new-screen">+ Screen</button></div>${screenEditor()}${themeEditor()}<div class="stats-stack">${rootState.screens.map(s=>`<div class="stats-item"><div class="stats-toolbar"><div><h3>${esc(s.name)}</h3><div class="stats-meta">${s.kind==="builtin"?"Built-in screen":`${(s.reports||[]).length} report(s) · ${esc(s.theme_mode||"inherited")} theme`}</div></div><div class="row">${s.kind!=="builtin"?`<button class="btn" data-action="edit-screen" data-id="${esc(s.id)}">Edit</button><button class="btn danger" data-action="delete-screen" data-id="${esc(s.id)}">Delete</button>`:""}<button class="btn primary" data-action="show-screen" data-id="${esc(s.id)}">Show on TV</button></div></div></div>`).join("")}</div>`;
  }

  function displayView(){
    const d=rootState.display; const rotation=d.rotation_screen_ids||[];
    return `<div class="stats-toolbar"><div><h2 style="margin:0">Display</h2><div class="small">Choose what is live now or build an automatic screen rotation.</div></div><button class="btn primary" data-action="save-display">Save Display</button></div><div class="stats-editor"><div class="grid"><div><label>Live Screen</label><select data-display="active_screen_id">${rootState.screens.map(s=>`<option value="${esc(s.id)}" ${s.id===d.active_screen_id?"selected":""}>${esc(s.name)}</option>`).join("")}</select></div><div><label>Seconds per screen</label><input type="number" min="5" max="3600" data-display="rotation_seconds" value="${Number(d.rotation_seconds||15)}"></div></div><label class="row" style="margin-top:12px"><input type="checkbox" data-display="rotation_enabled" ${d.rotation_enabled?"checked":""}><span>Rotate through selected screens automatically</span></label><h4>Rotation Order</h4><div class="stats-stack">${rootState.screens.map(s=>{const i=rotation.indexOf(s.id);return`<div class="stats-order"><input type="checkbox" data-rotation="${esc(s.id)}" ${i>=0?"checked":""}><span>${i>=0?`${i+1}. `:""}${esc(s.name)}</span><div class="stats-actions">${i>0?`<button class="btn" data-action="rotation-up" data-id="${esc(s.id)}">↑</button>`:""}${i>=0&&i<rotation.length-1?`<button class="btn" data-action="rotation-down" data-id="${esc(s.id)}">↓</button>`:""}</div></div>`;}).join("")}</div><div class="stats-meta" style="margin-top:12px">Current: ${esc(d.current_screen_id||d.active_screen_id||"")}</div></div>`;
  }

  function render(){
    if(!root)return; root.querySelectorAll(".stats-tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===rootState.tab));
    const body=root.querySelector("#statsWorkspaceBody"); body.innerHTML=(rootState.tab==="data"?dataView():rootState.tab==="screens"?screensView():displayView())+`<div class="stats-status">${esc(rootState.message||"")}</div>`;
  }

  function editorUpdate(target){
    const e=rootState.editor;if(!e)return; const key=target.dataset.edit;
    if(key==="source-name")e.value.name=target.value;
    if(key==="source-server")e.value.connection.server=target.value;
    if(key==="source-site")e.value.connection.site=target.value;
    if(key==="source-pat")e.value.connection.pat_name=target.value;
    if(key==="source-secret")e.secret=target.value;
    if(key==="report-name")e.value.name=target.value;
    if(key==="report-source")e.value.source_id=target.value;
    if(key==="report-workbook"){e.value.source_config.workbook=target.value;e.value.source_config.sheet="";e.views=[];loadViews(target.value);}
    if(key==="report-sheet")e.value.source_config.sheet=target.value;
    if(key==="report-export")e.value.source_config.export=target.value;
    if(key==="report-date-mode")e.value.runtime.date_mode=target.value;
    if(key==="report-start")e.value.runtime.date_start=target.value;
    if(key==="report-end")e.value.runtime.date_end=target.value;
    if(key==="report-market")e.value.runtime.market=target.value;
    if(key==="screen-name")e.value.name=target.value;
    if(key==="screen-theme")e.value.theme_mode=target.value;
  }

  async function openReport(report){
    const r=JSON.parse(JSON.stringify(report||{source_id:rootState.sources[0]?.id||"",name:"New Report",kind:"table",source_config:{export:"auto",filters:[],mapping:{metrics:{}}},runtime:{date_mode:"current_month",date_start:"",date_end:""}}));
    r.source_config=r.source_config||{};r.source_config.filters=r.source_config.filters||[];r.source_config.mapping=r.source_config.mapping||{metrics:{}};r.runtime=r.runtime||{};
    rootState.editor={type:"report",value:r,workbooks:[],views:[]};rootState.columns=null;rootState.preview=null;render();
    if(r.source_id) await loadWorkbooks(); if(r.source_config.workbook) await loadViews(r.source_config.workbook);
  }
  async function loadWorkbooks(){const e=rootState.editor;if(e?.type!=="report")return;rootState.message="Loading workbooks…";render();try{const d=await api(`/api/data/sources/${encodeURIComponent(e.value.source_id)}/workbooks`);e.workbooks=d.workbooks||[];rootState.message="";}catch(err){rootState.message=err.message;}render();}
  async function loadViews(workbook){const e=rootState.editor;if(e?.type!=="report"||!workbook)return;try{const d=await api(`/api/data/sources/${encodeURIComponent(e.value.source_id)}/workbooks/${encodeURIComponent(workbook)}/views`);e.views=d.views||[];}catch(err){rootState.message=err.message;}render();}

  function reportPayload(){const e=rootState.editor,r=e.value;return {id:r.id,source_id:r.source_id,name:r.name,kind:r.kind,source_config:r.source_config,runtime:r.runtime};}
  function screenPayload(){return JSON.parse(JSON.stringify(rootState.editor.value));}

  async function previewScreen(){const e=rootState.editor;if(e?.type!=="screen")return;clearTimeout(previewTimer);try{const d=await api("/api/screens/preview",json("POST",screenPayload()));rootState.preview=d.payload;rootState.message="Preview updated.";}catch(err){rootState.message=err.message;}render();}
  function schedulePreview(){if(rootState.editor?.type!=="screen")return;clearTimeout(previewTimer);previewTimer=setTimeout(previewScreen,350);}

  async function handleClick(ev){const b=ev.target.closest("[data-action],[data-tab]");if(!b)return;
    if(b.dataset.tab){rootState.tab=b.dataset.tab;rootState.editor=null;rootState.preview=null;render();return;}
    const a=b.dataset.action;try{
      if(a==="close-editor"){rootState.editor=null;rootState.columns=null;rootState.preview=null;rootState.message="";render();return;}
      if(a==="new-source"){rootState.editor={type:"source",value:{name:"Tableau",adapter:"tableau",connection:{}},secret:""};render();}
      if(a==="edit-source"){rootState.editor={type:"source",value:JSON.parse(JSON.stringify(sourceBy(b.dataset.id))),secret:""};render();}
      if(a==="save-source"){const e=rootState.editor,s=e.value;const body={id:s.id,name:s.name,adapter:"tableau",connection:s.connection};if(e.secret!=="")body.secret=e.secret;const d=await api(s.id?`/api/data/sources/${encodeURIComponent(s.id)}`:"/api/data/sources",json(s.id?"PUT":"POST",body));rootState.message="Source saved.";rootState.editor={type:"source",value:d.source,secret:""};await loadAll();render();}
      if(a==="test-source"||a==="test-source-card"){const id=b.dataset.id||rootState.editor?.value?.id;if(!id)throw new Error("Save the source first.");const d=await api(`/api/data/sources/${encodeURIComponent(id)}/test`,json("POST",{}));rootState.message=d.message||"Connected.";render();}
      if(a==="new-report"){await openReport({source_id:b.dataset.id,name:"New Report",kind:"table",source_config:{export:"auto",filters:[],mapping:{metrics:{}}},runtime:{date_mode:"current_month"}});}
      if(a==="edit-report"){await openReport(reportBy(b.dataset.id));}
      if(a==="load-workbooks"){await loadWorkbooks();}
      if(a==="read-report"){const e=rootState.editor;if(!e.value.id){const d=await api("/api/data/reports",json("POST",reportPayload()));e.value=d.report;}const d=await api(`/api/data/reports/${encodeURIComponent(e.value.id)}/columns`,json("POST",{...e.value.source_config,data_date_mode:e.value.runtime.date_mode,data_date_start:e.value.runtime.date_start,data_date_end:e.value.runtime.date_end}));rootState.columns=d;rootState.message=`Read ${d.headers?.length||d.choices?.length||0} fields.`;render();}
      if(a==="add-report-filter"){rootState.editor.value.source_config.filters.push({field:"",value:""});render();}
      if(a==="drop-report-filter"){rootState.editor.value.source_config.filters.splice(Number(b.dataset.index),1);render();}
      if(a==="save-report"){const e=rootState.editor;const d=await api(e.value.id?`/api/data/reports/${encodeURIComponent(e.value.id)}`:"/api/data/reports",json(e.value.id?"PUT":"POST",reportPayload()));e.value=d.report;await loadAll();rootState.message="Report saved.";render();}
      if(a==="refresh-report"||a==="refresh-report-card"){const id=b.dataset.id||rootState.editor?.value?.id;if(!id)throw new Error("Save the report first.");await api(`/api/data/reports/${encodeURIComponent(id)}/refresh`,json("POST",{}));await loadAll();rootState.message="Report refreshed.";render();}
      if(a==="preview-report"){const e=rootState.editor;if(!e.value.id)throw new Error("Save the report first.");const d=await api(`/api/data/reports/${encodeURIComponent(e.value.id)}/preview`,json("POST",{...e.value.source_config,data_date_mode:e.value.runtime.date_mode,data_date_start:e.value.runtime.date_start,data_date_end:e.value.runtime.date_end}));rootState.message=d.reps?`${d.reps} rows in preview.`:`Preview loaded.`;render();}
      if(a==="delete-report"){if(confirm("Delete this report?")){await api(`/api/data/reports/${encodeURIComponent(b.dataset.id)}`,{method:"DELETE"});await loadAll();render();}}
      if(a==="new-screen"){rootState.editor={type:"screen",value:{name:"New Screen",reports:rootState.reports.slice(0,1).map(r=>r.id),filters:[],tables:[],theme_mode:"inherited"}};rootState.preview=null;render();schedulePreview();}
      if(a==="edit-screen"){rootState.editor={type:"screen",value:JSON.parse(JSON.stringify(screenBy(b.dataset.id)))};rootState.preview=null;render();schedulePreview();}
      if(a==="add-screen-filter"){rootState.editor.value.filters.push({scope:"screen",report_id:"",field:"",operator:"equals",value:""});render();}
      if(a==="drop-screen-filter"){rootState.editor.value.filters.splice(Number(b.dataset.index),1);render();schedulePreview();}
      if(a==="preview-screen"){await previewScreen();}
      if(a==="save-screen"){const s=screenPayload();const d=await api(s.id?`/api/screens/${encodeURIComponent(s.id)}`:"/api/screens",json(s.id?"PUT":"POST",s));rootState.editor.value=d.screen;await loadAll();rootState.message="Screen saved.";render();}
      if(a==="delete-screen"){if(confirm("Delete this screen?")){await api(`/api/screens/${encodeURIComponent(b.dataset.id)}`,{method:"DELETE"});await loadAll();render();}}
      if(a==="show-screen"){rootState.display.active_screen_id=b.dataset.id;rootState.display.rotation_enabled=false;await api("/api/display",json("PUT",rootState.display));await loadAll();rootState.message="TV switched to this screen.";render();}
      if(a==="edit-screen-theme"){const id=rootState.editor.value.id;const d=await api(`/api/screen-themes/${encodeURIComponent(id)}`);rootState.editor={type:"theme",screenId:id,value:d};render();}
      if(a==="save-screen-theme"){const e=rootState.editor,t=e.value.theme;const d=await api(`/api/screen-themes/${encodeURIComponent(e.screenId)}`,json("PUT",t));e.value.theme=d.theme;rootState.message="Theme saved.";render();}
      if(a==="reset-screen-theme"){const e=rootState.editor;const d=await api(`/api/screen-themes/${encodeURIComponent(e.screenId)}`,{method:"DELETE"});e.value.theme=d.theme;render();}
      if(a==="reset-theme-asset"){const e=rootState.editor;const d=await api(`/api/screen-themes/${encodeURIComponent(e.screenId)}/assets/${encodeURIComponent(b.dataset.key)}`,{method:"DELETE"});e.value.theme=d.theme;render();}
      if(a==="rotation-up"||a==="rotation-down"){const arr=rootState.display.rotation_screen_ids||[],i=arr.indexOf(b.dataset.id),j=a==="rotation-up"?i-1:i+1;if(i>=0&&j>=0&&j<arr.length){[arr[i],arr[j]]=[arr[j],arr[i]];render();}}
      if(a==="save-display"){await api("/api/display",json("PUT",rootState.display));await loadAll();rootState.message="Display saved.";render();}
    }catch(err){rootState.message=err.message;render();}
  }

  function handleInput(ev){const t=ev.target;
    if(t.dataset.edit){editorUpdate(t);if(rootState.editor?.type==="screen")schedulePreview();return;}
    if(t.dataset.map){const r=rootState.editor.value,m=r.source_config.mapping||(r.source_config.mapping={metrics:{}});if(t.dataset.map.startsWith("metric:")){m.metrics=m.metrics||{};m.metrics[t.dataset.map.slice(7)]=t.value;}else m[t.dataset.map]=t.value;return;}
    if(t.dataset.filterField!==undefined){rootState.editor.value.source_config.filters[Number(t.dataset.filterField)].field=t.value;return;}
    if(t.dataset.filterValue!==undefined){rootState.editor.value.source_config.filters[Number(t.dataset.filterValue)].value=t.value;return;}
    if(t.dataset.screenReport){const s=rootState.editor.value,id=t.dataset.screenReport;s.reports=s.reports||[];if(t.checked&&!s.reports.includes(id))s.reports.push(id);if(!t.checked)s.reports=s.reports.filter(x=>x!==id);s.tables=(s.tables||[]).filter(x=>s.reports.includes(x.report_id));render();schedulePreview();return;}
    if(t.dataset.screenFilter){const [key,index]=t.dataset.screenFilter.split(":"),f=rootState.editor.value.filters[Number(index)];f[key]=t.value;render();schedulePreview();return;}
    if(t.dataset.tableColumn){const [rid,key]=t.dataset.tableColumn.split(":"),s=rootState.editor.value;s.tables=s.tables||[];let table=s.tables.find(x=>x.report_id===rid);if(!table){table={report_id:rid,columns:[],sort_field:"",sort_direction:"desc",limit:100};s.tables.push(table);}if(t.checked&&!table.columns.includes(key))table.columns.push(key);if(!t.checked)table.columns=table.columns.filter(x=>x!==key);schedulePreview();return;}
    if(t.dataset.tableSetting){const [setting,rid]=t.dataset.tableSetting.split(":"),s=rootState.editor.value;s.tables=s.tables||[];let table=s.tables.find(x=>x.report_id===rid);if(!table){table={report_id:rid,columns:fieldsFor(rid).slice(0,8).map(x=>x.key),sort_field:"",sort_direction:"desc",limit:100};s.tables.push(table);}table[setting]=setting==="limit"?Number(t.value):t.value;schedulePreview();return;}
    if(t.dataset.display){const k=t.dataset.display;rootState.display[k]=k==="rotation_enabled"?t.checked:k==="rotation_seconds"?Number(t.value):t.value;return;}
    if(t.dataset.rotation){let a=rootState.display.rotation_screen_ids||(rootState.display.rotation_screen_ids=[]);if(t.checked&&!a.includes(t.dataset.rotation))a.push(t.dataset.rotation);if(!t.checked)a.splice(a.indexOf(t.dataset.rotation),1);render();return;}
    if(t.dataset.theme){rootState.editor.value.theme[t.dataset.theme]=t.dataset.theme==="enabled"?t.checked:t.value;return;}
    if(t.dataset.themeColor){rootState.editor.value.theme.colors=rootState.editor.value.theme.colors||{};rootState.editor.value.theme.colors[t.dataset.themeColor]=t.value;return;}
    if(t.dataset.themeFile&&t.files?.[0]) uploadThemeAsset(t.dataset.themeFile,t.files[0]);
  }

  async function uploadThemeAsset(key,file){const e=rootState.editor;if(e?.type!=="theme")return;const fd=new FormData();fd.append("asset",file);try{const r=await fetch(`/api/screen-themes/${encodeURIComponent(e.screenId)}/assets/${encodeURIComponent(key)}`,{method:"POST",body:fd});const d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.error||"Upload failed");e.value.theme=d.theme;rootState.message="Artwork applied.";}catch(err){rootState.message=err.message;}render();}

  function mount(){
    if(root)return;const app=document.getElementById("appWrap");if(!app)return;removeLegacyDataUI();const holder=document.createElement("div");holder.innerHTML=shell();root=holder.firstElementChild;const note=app.querySelector(".persist-note");(note||app.firstElementChild).insertAdjacentElement("afterend",root);root.addEventListener("click",handleClick);root.addEventListener("input",handleInput);root.addEventListener("change",handleInput);
    loadAll().then(render).catch(err=>{rootState.message=err.message;render();});
  }
  function wait(){const app=document.getElementById("appWrap");if(app&&getComputedStyle(app).display!=="none")mount();else setTimeout(wait,200);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",wait,{once:true});else wait();
})();
