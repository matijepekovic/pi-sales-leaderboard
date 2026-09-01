/* Filters Settings owns reusable Display Filter definitions and testing. */
(function(){
  const runtime=window.StatsSettings,$=id=>document.getElementById(id),esc=runtime.esc;
  const state={filters:[],reports:[],inspections:{},editor:null,focusRule:0,preview:null,message:"",afterCreate:null};
  let loaded=false;

  async function load(){
    const [filters,reports]=await Promise.all([runtime.api("/api/filters"),runtime.api("/api/data/reports")]);
    state.filters=filters.filters||[];state.reports=reports.reports||[];loaded=true;renderList();
    runtime.emit("filters-changed",state.filters.slice());
  }
  const reportBy=id=>state.reports.find(item=>String(item.id)===String(id))||null;
  const filterBy=id=>state.filters.find(item=>String(item.id)===String(id))||null;

  async function inspection(reportId){
    if(!reportId)return null;if(state.inspections[reportId])return state.inspections[reportId];
    const data=await runtime.api(`/api/data/reports/${encodeURIComponent(reportId)}/inspect`);state.inspections[reportId]=data;return data;
  }

  function renderList(){
    const host=$("settingsFiltersHost");if(!host)return;
    host.innerHTML=`<div class="card"><div class="toolbar"><div><h2>Display Filters</h2><div class="small">Reusable filters applied to data after it has been pulled into Stats.</div></div><button class="btn primary" data-filter-action="new">+ Filter</button></div><div class="stack" style="margin-top:12px">${state.filters.map(item=>`<div class="subcard"><div class="toolbar"><div><strong>${esc(item.name)}</strong><div class="small">${(item.rules||[]).length} rule${(item.rules||[]).length===1?"":"s"}</div></div><div class="row"><button class="btn" data-filter-action="edit" data-id="${esc(item.id)}">Edit / Test</button><button class="btn danger" data-filter-action="delete" data-id="${esc(item.id)}">Delete</button></div></div>${(item.rules||[]).map(rule=>`<div class="small" style="margin-top:5px">${esc(reportBy(rule.report_id)?.name||rule.report_id)} · ${esc(rule.field)} · ${esc(rule.operator)} · ${esc(rule.value)}</div>`).join("")}</div>`).join("")||'<div class="small">No Display Filters yet.</div>'}</div><div class="status">${esc(state.message||"")}</div></div>`;
    host.querySelectorAll("[data-filter-action]").forEach(button=>button.addEventListener("click",()=>handleList(button.dataset.filterAction,button.dataset.id)));
  }

  function ensureOverlay(){
    if($("displayFilterOverlay"))return;
    const overlay=document.createElement("div");overlay.id="displayFilterOverlay";overlay.className="overlay";overlay.setAttribute("aria-hidden","true");document.body.appendChild(overlay);
  }
  function closeEditor(){state.editor=null;state.preview=null;state.afterCreate=null;const overlay=$("displayFilterOverlay");if(overlay){overlay.classList.remove("open");overlay.setAttribute("aria-hidden","true");}}

  async function openEditor(item=null,afterCreate=null){
    if(!loaded)await load();ensureOverlay();state.editor=item?JSON.parse(JSON.stringify(item)):{name:"",rules:[{report_id:state.reports[0]?.id||"",field:"",operator:"equals",value:""}]};state.focusRule=0;state.preview=null;state.message="";state.afterCreate=afterCreate||null;
    for(const rule of state.editor.rules||[]){if(rule.report_id)try{await inspection(rule.report_id);}catch(_){ }}
    renderEditor();$("displayFilterOverlay").classList.add("open");$("displayFilterOverlay").setAttribute("aria-hidden","false");
  }

  function syncEditor(){
    const overlay=$("displayFilterOverlay");if(!overlay||!state.editor)return;
    const name=overlay.querySelector('[data-filter-name]');if(name)state.editor.name=name.value;
    overlay.querySelectorAll('[data-rule-report]').forEach(el=>{const i=Number(el.dataset.ruleReport);if(state.editor.rules[i])state.editor.rules[i].report_id=el.value;});
    overlay.querySelectorAll('[data-rule-field]').forEach(el=>{const i=Number(el.dataset.ruleField);if(state.editor.rules[i])state.editor.rules[i].field=el.value;});
    overlay.querySelectorAll('[data-rule-operator]').forEach(el=>{const i=Number(el.dataset.ruleOperator);if(state.editor.rules[i])state.editor.rules[i].operator=el.value;});
    overlay.querySelectorAll('[data-rule-value]').forEach(el=>{const i=Number(el.dataset.ruleValue);if(state.editor.rules[i])state.editor.rules[i].value=el.value;});
  }

  function ruleHtml(rule,index){
    const report=reportBy(rule.report_id),inspect=state.inspections[rule.report_id],fields=inspect?.fields||[];const field=fields.find(item=>String(item.key)===String(rule.field));const listId=`filter-values-${index}`;
    return `<div class="rule-row" data-rule-index="${index}" style="margin-top:10px"><div><label>Report</label><select data-rule-report="${index}"><option value="">Choose Report…</option>${state.reports.map(item=>`<option value="${esc(item.id)}" ${item.id===rule.report_id?"selected":""}>${esc(item.name)}</option>`).join("")}</select></div><div><label>Field</label><select data-rule-field="${index}"><option value="">Choose field…</option>${fields.map(item=>`<option value="${esc(item.key)}" ${item.key===rule.field?"selected":""}>${esc(item.label||item.key)}</option>`).join("")}</select></div><div><label>Match</label><select data-rule-operator="${index}"><option value="equals" ${rule.operator==="equals"?"selected":""}>Equals</option><option value="not_equals" ${rule.operator==="not_equals"?"selected":""}>Does not equal</option><option value="contains" ${rule.operator==="contains"?"selected":""}>Contains</option><option value="not_contains" ${rule.operator==="not_contains"?"selected":""}>Does not contain</option></select></div><div><label>Value</label><input data-rule-value="${index}" list="${listId}" value="${esc(rule.value||"")}" placeholder="Choose or type value"><datalist id="${listId}">${(field?.sample_values||[]).map(value=>`<option value="${esc(value)}"></option>`).join("")}</datalist></div><button class="btn danger" data-filter-action="remove-rule" data-index="${index}">Remove</button></div>${report&&!inspect?'<div class="small">Loading pulled data…</div>':""}`;
  }

  function dataPreview(){
    if(!state.editor?.rules?.length)return"";const rule=state.editor.rules[Math.min(state.focusRule,state.editor.rules.length-1)]||{},inspect=state.inspections[rule.report_id];
    if(!rule.report_id)return'<div class="subcard"><strong>Pulled Report Data</strong><div class="small">Choose a Report in a rule to inspect its actual data.</div></div>';
    if(!inspect)return'<div class="subcard"><strong>Pulled Report Data</strong><div class="small">Loading…</div></div>';
    const fields=inspect.fields||[],rows=inspect.sample_rows||[];
    return `<div class="subcard"><div class="toolbar"><div><strong>${esc(inspect.report_name)}</strong><div class="small">${Number(inspect.total_rows||0)} pulled rows. Click a rule to inspect the data it targets.</div></div><button class="btn" data-filter-action="refresh-inspection" data-report-id="${esc(rule.report_id)}">Reload Data</button></div><div class="data-table" style="margin-top:10px"><table><thead><tr>${fields.map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${fields.map(field=>`<td>${esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(1,fields.length)}">No pulled rows.</td></tr>`}</tbody></table></div><div class="stack" style="margin-top:10px">${fields.map(field=>`<div class="field-card"><strong>${esc(field.label||field.key)}</strong><div class="field-key">${esc(field.key)}</div><div class="chips">${(field.sample_values||[]).slice(0,60).map(value=>`<span class="chip">${esc(value)}</span>`).join("")||'<span class="small">No values</span>'}</div></div>`).join("")}</div></div>`;
  }

  function testPreview(){
    if(!state.preview)return"";return `<div class="subcard"><strong>Filter Test</strong><div class="small">This uses the same server-side Filter engine Screens use.</div><div class="stack" style="margin-top:10px">${(state.preview.reports||[]).map(report=>`<div class="preview-section"><h4>${esc(report.report_name)} · ${Number(report.matched_rows||0)} / ${Number(report.total_rows||0)} rows match</h4><div class="data-table"><table><thead><tr>${(report.fields||[]).map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${(report.rows||[]).map(row=>`<tr>${(report.fields||[]).map(field=>`<td>${esc(row[field.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(1,(report.fields||[]).length)}">No matching rows.</td></tr>`}</tbody></table></div></div>`).join("")}</div></div>`;
  }

  function renderEditor(){
    ensureOverlay();const overlay=$("displayFilterOverlay");if(!state.editor)return;
    overlay.innerHTML=`<div class="panel" style="width:min(1300px,100%)"><div class="toolbar"><div><h2>${state.editor.id?"Edit":"Create"} Display Filter</h2><div class="small">Build the existing Filter rules against actual pulled Report data.</div></div><button class="btn" data-filter-action="close">Close</button></div><div class="screen-layout" style="margin-top:14px"><div><label>Filter Name</label><input data-filter-name value="${esc(state.editor.name||"")}" placeholder="Example: Olympia Sales"><div class="subcard" style="margin-top:12px"><div class="toolbar"><div><strong>Rules</strong><div class="small">Rules inside a Filter are combined. A rule only affects its selected Report.</div></div><button class="btn" data-filter-action="add-rule">+ Rule</button></div>${(state.editor.rules||[]).map(ruleHtml).join("")||'<div class="small">No rules yet.</div>'}</div><div class="row" style="margin-top:14px"><button class="btn" data-filter-action="test">Test Filter</button><button class="btn primary" data-filter-action="save">Save Filter</button></div><div class="status">${esc(state.message||"")}</div>${testPreview()}</div><div>${dataPreview()}</div></div></div>`;
    bindEditor();
  }

  function bindEditor(){
    const overlay=$("displayFilterOverlay");if(!overlay)return;
    overlay.querySelectorAll("[data-filter-action]").forEach(button=>button.addEventListener("click",async()=>{
      const action=button.dataset.filterAction,index=Number(button.dataset.index||0);
      if(action==="close")return closeEditor();
      syncEditor();
      if(action==="add-rule"){state.editor.rules.push({report_id:state.reports[0]?.id||"",field:"",operator:"equals",value:""});state.focusRule=state.editor.rules.length-1;if(state.editor.rules[state.focusRule].report_id)try{await inspection(state.editor.rules[state.focusRule].report_id);}catch(error){state.message=error.message;}renderEditor();return;}
      if(action==="remove-rule"){state.editor.rules.splice(index,1);state.focusRule=Math.max(0,Math.min(state.focusRule,state.editor.rules.length-1));renderEditor();return;}
      if(action==="refresh-inspection"){delete state.inspections[button.dataset.reportId];try{await inspection(button.dataset.reportId);state.message="Pulled data reloaded.";}catch(error){state.message=error.message;}renderEditor();return;}
      if(action==="test"){state.message="Testing Filter…";renderEditor();try{state.preview=await runtime.api("/api/filters/preview",runtime.json("POST",state.editor));state.message="Filter test complete.";}catch(error){state.preview=null;state.message=error.message;}renderEditor();return;}
      if(action==="save"){await saveEditor();return;}
    }));
    overlay.querySelectorAll("[data-rule-index]").forEach(row=>row.addEventListener("click",()=>{state.focusRule=Number(row.dataset.ruleIndex);syncEditor();renderEditor();}));
    overlay.querySelectorAll("[data-rule-report]").forEach(select=>select.addEventListener("change",async event=>{event.stopPropagation();syncEditor();const i=Number(select.dataset.ruleReport);state.editor.rules[i].report_id=select.value;state.editor.rules[i].field="";state.editor.rules[i].value="";state.focusRule=i;if(select.value)try{await inspection(select.value);}catch(error){state.message=error.message;}renderEditor();}));
    overlay.querySelectorAll("[data-rule-field]").forEach(select=>select.addEventListener("change",event=>{event.stopPropagation();syncEditor();state.focusRule=Number(select.dataset.ruleField);renderEditor();}));
    overlay.querySelectorAll("[data-rule-operator],[data-rule-value],[data-filter-name]").forEach(input=>input.addEventListener("click",event=>event.stopPropagation()));
  }

  async function saveEditor(){
    syncEditor();const wasNew=!state.editor.id;state.message="Saving Filter…";renderEditor();
    try{const url=state.editor.id?`/api/filters/${encodeURIComponent(state.editor.id)}`:"/api/filters";const method=state.editor.id?"PUT":"POST";const data=await runtime.api(url,runtime.json(method,state.editor));const created=data.filter;const callback=state.afterCreate;closeEditor();state.message="Filter saved.";await load();if(wasNew&&callback)callback(created);runtime.emit("filter-saved",created);}catch(error){state.message=error.message;renderEditor();}
  }

  async function handleList(action,id){
    if(action==="new")return openEditor();if(action==="edit")return openEditor(filterBy(id));if(action==="delete"){if(!confirm("Delete this Filter?"))return;try{await runtime.api(`/api/filters/${encodeURIComponent(id)}`,{method:"DELETE"});state.message="Filter deleted.";await load();}catch(error){state.message=error.message;renderList();}}
  }

  runtime.on("section",id=>{if(id==="settingsFilters"&&!loaded)load().catch(error=>{state.message=error.message;renderList();});});
  runtime.on("unlocked",()=>{loaded=false;});
  runtime.on("data-changed",()=>{loaded=false;state.inspections={};});
  runtime.on("create-filter",detail=>openEditor(null,detail?.afterCreate).catch(error=>{state.message=error.message;renderList();}));
  window.StatsFilterManager=Object.freeze({openCreate:afterCreate=>openEditor(null,afterCreate),reload:load});
})();
