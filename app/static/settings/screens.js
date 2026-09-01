/* Screens Settings owns Screen composition and live preview. */
(function(){
  const runtime=window.StatsSettings,$=id=>document.getElementById(id),esc=runtime.esc;
  const state={screens:[],reports:[],filters:[],editor:null,step:0,preview:null,message:""};
  let loaded=false,previewTimer=null;
  const reportBy=id=>state.reports.find(item=>String(item.id)===String(id))||null;
  const filterBy=id=>state.filters.find(item=>String(item.id)===String(id))||null;
  const screenBy=id=>state.screens.find(item=>String(item.id)===String(id))||null;

  async function load(){
    const [screens,reports,filters]=await Promise.all([runtime.api("/api/screens"),runtime.api("/api/data/reports"),runtime.api("/api/filters")]);
    state.screens=screens.screens||[];state.reports=reports.reports||[];state.filters=filters.filters||[];loaded=true;render();
  }

  function blank(){return {name:"New Screen",reports:[],filter_ids:[],tables:[],theme_mode:"inherited"};}
  function normalizeTables(screen){
    const selected=new Set(screen.reports||[]);screen.tables=(screen.tables||[]).filter(table=>selected.has(table.report_id));
    for(const reportId of screen.reports||[]){if(screen.tables.some(table=>table.report_id===reportId))continue;const fields=reportBy(reportId)?.fields||[];screen.tables.push({report_id:reportId,columns:fields.slice(0,8).map(field=>field.key),sort_field:"",sort_direction:"desc",limit:100});}
  }

  function listHtml(){
    return `<div class="card"><div class="toolbar"><div><h2>Screens</h2><div class="small">Screens choose Reports, reusable Filters and presentation.</div></div><button class="btn primary" data-screen-action="new">+ Screen</button></div><div class="stack" style="margin-top:12px">${state.screens.map(screen=>`<div class="subcard"><div class="toolbar"><div><strong>${esc(screen.name)}</strong><div class="small">${screen.kind==="builtin"?"Built-in":"Custom Screen"}${screen.kind!=="builtin"?` · ${(screen.reports||[]).length} Reports · ${(screen.filter_ids||[]).length} Filters`:""}</div></div><div class="row">${screen.kind!=="builtin"?`<button class="btn" data-screen-action="edit" data-id="${esc(screen.id)}">Edit</button><button class="btn" data-screen-action="preview-saved" data-id="${esc(screen.id)}">Preview</button><button class="btn danger" data-screen-action="delete" data-id="${esc(screen.id)}">Delete</button>`:`<button class="btn" data-screen-action="preview-saved" data-id="${esc(screen.id)}">Preview</button>`}</div></div></div>`).join("")||'<div class="small">No Screens.</div>'}</div></div>`;
  }

  function steps(){const names=["1. Data","2. Filters","3. Display","4. Theme"];return `<div class="steps">${names.map((name,index)=>`<button class="step ${index===state.step?"active":""}" type="button" data-screen-step="${index}">${name}</button>`).join("")}</div>`;}

  function dataStep(screen){
    return `<div><h3>Choose Data</h3><div class="small">Choose the pulled Reports this Screen can display.</div><div class="stack" style="margin-top:10px">${state.reports.map(report=>`<label class="choice"><input type="checkbox" data-screen-report="${esc(report.id)}" ${(screen.reports||[]).includes(report.id)?"checked":""}><span><strong>${esc(report.name)}</strong><br><span class="small">${esc(report.status||"Not pulled yet")} · ${(report.fields||[]).length} fields</span></span></label>`).join("")||'<div class="small">Create a Report in Data first.</div>'}</div></div>`;
  }

  function filtersStep(screen){
    return `<div><div class="toolbar"><div><h3>Assign Filters</h3><div class="small">Choose reusable Display Filters for this Screen.</div></div><button class="btn" data-screen-action="create-filter">+ Create Filter</button></div><div class="stack" style="margin-top:10px">${state.filters.map(filter=>`<label class="choice"><input type="checkbox" data-screen-filter="${esc(filter.id)}" ${(screen.filter_ids||[]).includes(filter.id)?"checked":""}><span><strong>${esc(filter.name)}</strong>${(filter.rules||[]).map(rule=>`<br><span class="small">${esc(reportBy(rule.report_id)?.name||rule.report_id)} · ${esc(rule.field)} ${esc(rule.operator)} ${esc(rule.value)}</span>`).join("")}</span></label>`).join("")||'<div class="small">No Filters yet. Create one here.</div>'}</div></div>`;
  }

  function tableEditor(table){
    const report=reportBy(table.report_id),fields=report?.fields||[];
    return `<div class="subcard"><h4>${esc(report?.name||table.report_id)}</h4><div class="small">Columns</div><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr));margin-top:7px">${fields.map(field=>`<label class="choice"><input type="checkbox" data-table-column="${esc(table.report_id)}" value="${esc(field.key)}" ${(table.columns||[]).includes(field.key)?"checked":""}><span>${esc(field.label||field.key)}</span></label>`).join("")}</div><div class="grid" style="margin-top:10px"><div><label>Rank / sort by</label><select data-table-sort="${esc(table.report_id)}"><option value="">Source order</option>${fields.map(field=>`<option value="${esc(field.key)}" ${table.sort_field===field.key?"selected":""}>${esc(field.label||field.key)}</option>`).join("")}</select></div><div><label>Direction</label><select data-table-direction="${esc(table.report_id)}"><option value="desc" ${table.sort_direction!=="asc"?"selected":""}>Highest first</option><option value="asc" ${table.sort_direction==="asc"?"selected":""}>Lowest first</option></select></div><div><label>Rows</label><input type="number" min="1" max="500" data-table-limit="${esc(table.report_id)}" value="${Number(table.limit||100)}"></div></div></div>`;
  }
  function displayStep(screen){normalizeTables(screen);return `<div><div class="toolbar"><div><h3>Create Display</h3><div class="small">Choose columns, ranking and row count. Preview uses current pulled data and assigned Filters.</div></div><button class="btn" data-screen-action="refresh-preview">Refresh Preview</button></div><div class="stack" style="margin-top:10px">${(screen.tables||[]).map(tableEditor).join("")||'<div class="small">Choose Reports first.</div>'}</div></div>`;}
  function themeStep(screen){return `<div><h3>Theme</h3><div class="small">Inherited uses Stats theme resolution. Custom gives this Screen its own Theme Editor scope.</div><div class="stack" style="margin-top:10px"><label class="choice"><input type="radio" name="screenTheme" data-screen-theme="inherited" ${screen.theme_mode!=="custom"?"checked":""}><span><strong>Inherited</strong><br><span class="small">Use the appropriate team/theme context.</span></span></label><label class="choice"><input type="radio" name="screenTheme" data-screen-theme="custom" ${screen.theme_mode==="custom"?"checked":""}><span><strong>Custom</strong><br><span class="small">Use this Screen's own theme.</span></span></label></div></div>`;}

  function previewHtml(){
    const data=state.preview;if(!data)return'<div class="preview"><strong>Live Preview</strong><div class="small" style="margin-top:6px">Choose data, then Stats will render this Screen with the same server-side Screen + Filter engine used by the TV.</div></div>';
    if(data.error)return`<div class="preview"><strong>Live Preview</strong><div class="danger-text small" style="margin-top:6px">${esc(data.error)}</div></div>`;
    return `<div class="preview"><div class="toolbar"><div><strong>${esc(data.screen_name||data.mode_label||"Preview")}</strong><div class="small">${(data.display_filters||[]).map(filter=>filter.name).join(" · ")||"No Display Filters"}</div></div></div>${(data.sections||[]).map(section=>`<div class="preview-section"><h4>${esc(section.report_name)} · ${Number(section.total_rows||0)} matching rows</h4><div class="data-table"><table><thead><tr>${(section.fields||[]).map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${(section.rows||[]).slice(0,20).map(row=>`<tr>${(section.fields||[]).map(field=>`<td>${esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(1,(section.fields||[]).length)}">No matching rows.</td></tr>`}</tbody></table></div></div>`).join("")||'<div class="small">No sections.</div>'}</div>`;
  }

  function editorHtml(){
    if(!state.editor)return"";const screen=state.editor;const body=[dataStep,filtersStep,displayStep,themeStep][state.step](screen);
    return `<div class="card"><div class="toolbar"><div><h2>${screen.id?"Edit":"Create"} Screen</h2><div class="small">Screen owns presentation. Filters remain reusable Filter definitions.</div></div><button class="btn" data-screen-action="close-editor">Close</button></div><div style="margin-top:10px"><label>Screen Name</label><input data-screen-name value="${esc(screen.name||"")}"></div>${steps()}<div class="screen-layout"><div>${body}<div class="row" style="justify-content:space-between;margin-top:14px"><button class="btn" data-screen-action="back" ${state.step===0?"disabled":""}>Back</button><div class="row">${state.step<3?'<button class="btn primary" data-screen-action="next">Next</button>':'<button class="btn primary" data-screen-action="save">Save Screen</button>'}</div></div><div class="status">${esc(state.message||"")}</div></div>${previewHtml()}</div></div>`;
  }

  function render(){const host=$("settingsScreensHost");if(!host)return;host.innerHTML=listHtml()+editorHtml();bind();}

  function sync(){
    const host=$("settingsScreensHost");if(!host||!state.editor)return;const name=host.querySelector('[data-screen-name]');if(name)state.editor.name=name.value;
    const reportChecks=host.querySelectorAll('[data-screen-report]');if(reportChecks.length){state.editor.reports=Array.from(reportChecks).filter(input=>input.checked).map(input=>input.dataset.screenReport);normalizeTables(state.editor);}
    const filterChecks=host.querySelectorAll('[data-screen-filter]');if(filterChecks.length)state.editor.filter_ids=Array.from(filterChecks).filter(input=>input.checked).map(input=>input.dataset.screenFilter);
    host.querySelectorAll('[data-table-sort]').forEach(el=>{const table=state.editor.tables.find(item=>item.report_id===el.dataset.tableSort);if(table)table.sort_field=el.value;});host.querySelectorAll('[data-table-direction]').forEach(el=>{const table=state.editor.tables.find(item=>item.report_id===el.dataset.tableDirection);if(table)table.sort_direction=el.value;});host.querySelectorAll('[data-table-limit]').forEach(el=>{const table=state.editor.tables.find(item=>item.report_id===el.dataset.tableLimit);if(table)table.limit=Number(el.value||100);});
    const columnGroups=new Map();host.querySelectorAll('[data-table-column]').forEach(input=>{if(!columnGroups.has(input.dataset.tableColumn))columnGroups.set(input.dataset.tableColumn,[]);if(input.checked)columnGroups.get(input.dataset.tableColumn).push(input.value);});for(const [reportId,columns] of columnGroups){const table=state.editor.tables.find(item=>item.report_id===reportId);if(table)table.columns=columns;}
    const theme=host.querySelector('[data-screen-theme]:checked');if(theme)state.editor.theme_mode=theme.dataset.screenTheme;
  }

  function schedulePreview(){clearTimeout(previewTimer);previewTimer=setTimeout(runPreview,250);}
  async function runPreview(){if(!state.editor)return;sync();if(!(state.editor.reports||[]).length){state.preview=null;render();return;}try{const data=await runtime.api("/api/screens/preview",runtime.json("POST",state.editor));state.preview=data.payload||null;state.message="";}catch(error){state.preview={error:error.message};}render();}

  async function openEditor(id=null){if(!loaded)await load();state.editor=id?JSON.parse(JSON.stringify(screenBy(id))):blank();state.step=0;state.preview=null;state.message="";normalizeTables(state.editor);render();schedulePreview();}
  async function save(){sync();state.message="Saving Screen…";render();try{const url=state.editor.id?`/api/screens/${encodeURIComponent(state.editor.id)}`:"/api/screens";const method=state.editor.id?"PUT":"POST";await runtime.api(url,runtime.json(method,state.editor));state.editor=null;state.preview=null;state.message="Screen saved.";await load();runtime.emit("screens-changed");}catch(error){state.message=error.message;render();}}
  async function previewSaved(id){try{const data=await runtime.api(`/api/screens/${encodeURIComponent(id)}/preview`);state.editor=null;state.preview=data.payload;state.message=`Previewing ${screenBy(id)?.name||id}.`;render();}catch(error){state.message=error.message;render();}}

  function bind(){
    const host=$("settingsScreensHost");if(!host)return;
    host.querySelectorAll('[data-screen-action]').forEach(button=>button.addEventListener("click",async()=>{
      const action=button.dataset.screenAction,id=button.dataset.id;sync();
      if(action==="new")return openEditor();if(action==="edit")return openEditor(id);if(action==="close-editor"){state.editor=null;state.preview=null;render();return;}if(action==="back"){state.step=Math.max(0,state.step-1);render();schedulePreview();return;}if(action==="next"){state.step=Math.min(3,state.step+1);render();schedulePreview();return;}if(action==="save")return save();if(action==="refresh-preview")return runPreview();if(action==="preview-saved")return previewSaved(id);
      if(action==="create-filter"){const manager=window.StatsFilterManager;if(!manager){state.message="Filter editor is still loading.";render();return;}manager.openCreate(async created=>{if(!state.editor)return;state.editor.filter_ids=[...(state.editor.filter_ids||[]),created.id].filter((value,index,array)=>array.indexOf(value)===index);const data=await runtime.api("/api/filters");state.filters=data.filters||[];render();schedulePreview();});return;}
      if(action==="delete"){if(!confirm("Delete this Screen?"))return;try{await runtime.api(`/api/screens/${encodeURIComponent(id)}`,{method:"DELETE"});state.message="Screen deleted.";await load();runtime.emit("screens-changed");}catch(error){state.message=error.message;render();}return;}
    }));
    host.querySelectorAll('[data-screen-step]').forEach(button=>button.addEventListener("click",()=>{sync();state.step=Number(button.dataset.screenStep);render();schedulePreview();}));
    host.querySelectorAll('input,select').forEach(input=>{if(input.dataset.screenName!==undefined)input.addEventListener("input",()=>{sync();schedulePreview();});else input.addEventListener("change",()=>{sync();render();schedulePreview();});});
  }

  runtime.on("section",id=>{if(id==="settingsScreens"&&!loaded)load().catch(error=>{state.message=error.message;render();});});
  runtime.on("unlocked",()=>{loaded=false;});runtime.on("data-changed",()=>{loaded=false;});runtime.on("filters-changed",filters=>{state.filters=filters||[];if(state.editor)render();});
})();
