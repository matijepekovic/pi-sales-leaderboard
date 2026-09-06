/* Central Fields owner plus the shared Report Field editor used as a shortcut elsewhere. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const TYPES=[["number","Number"],["text","Text"],["percent","Percentage"]];
  const typeLabel=type=>({text:"Text",number:"Number",percent:"Percentage",asset:"Asset"})[String(type||"text").toLowerCase()]||String(type||"Text");
  const kindLabel=kind=>({report:"Report",calculated:"Calculated",group:"Group",table:"Table"})[kind]||kind;
  const defaultDecimals=type=>type==="percent"?1:type==="number"?2:0;
  function percentInput(field,attribute){
    const choices=[["auto","Automatic (existing behavior)"],["fraction","0.143 → 14.3%"],["points","14.3 → 14.3%"]];
    return `<div data-percent-input ${field.type==="percent"?"":"hidden"} style="margin-top:10px"><label>Percentage values</label><select ${attribute}>${choices.map(([value,label])=>`<option value="${value}" ${value===(field.percent_input_scale||"auto")?"selected":""}>${label}</option>`).join("")}</select></div>`;
  }

  const formatValue=window.StatsFieldValues.format;
  function typeOptions(field){
    const current=String(field.type||"text"),source=String(field.source_type||"text");
    return TYPES.filter(([value])=>source!=="text"||value==="text").map(([value,label])=>`<option value="${value}" ${current===value?"selected":""}>${label}</option>`).join("");
  }
  function reportForm(reportId,field){
    if(!field)return"";
    if(String(field.kind||"report")!=="report"){
      return `<div class="display-value-inline"><div class="toolbar"><div><strong>${esc(field.label||field.key)}</strong><div class="small">This is a ${esc(kindLabel(field.kind))} Field and is edited in Fields.</div></div><button class="btn" type="button" data-open-central-field data-report-id="${esc(reportId)}" data-field-key="${esc(field.key)}">Open in Fields</button></div></div>`;
    }
    const key=String(field.key||""),label=String(field.label||key),sourceLabel=String(field.source_label||key),sourceType=String(field.source_type||"text"),textOnly=sourceType==="text";
    return `<div class="display-value-inline" data-field-card data-report-id="${esc(reportId)}" data-field-key="${esc(key)}" data-source-label="${esc(sourceLabel)}" data-source-type="${esc(sourceType)}"><div class="toolbar"><div><strong>Edit ${esc(label)}</strong><div class="field-key">Report Field · global</div></div></div><div class="display-value-form"><div class="grid" style="grid-template-columns:minmax(180px,1fr) minmax(130px,.45fr) minmax(120px,.35fr)"><div><label>Name</label><input data-field-name value="${esc(label)}"></div><div><label>Display</label><select data-field-type ${textOnly?'disabled title="Text Report Fields stay Text."':""}>${typeOptions(field)}</select></div><div><label>Rounding decimals</label><input data-field-decimals type="number" min="0" max="8" value="${Number(field.decimals??defaultDecimals(field.type))}" ${textOnly?"disabled":""}></div></div>${percentInput(field,"data-field-percent-scale")}<div class="toolbar" style="margin-top:9px"><div><div class="field-key">Source: ${esc(sourceLabel)} · ${esc(sourceType)}</div><div class="small" data-field-status></div></div><div class="row">${field.customized?'<button class="btn" type="button" data-reset-report-field>Reset</button>':""}<button class="btn" type="button" data-close-report-field>Cancel</button><button class="btn primary" type="button" data-save-report-field>Save globally</button></div></div></div></div>`;
  }
  async function saveReportField(button,reset,onSaved){
    const card=button.closest("[data-field-card]");if(!card)return;
    const status=card.querySelector("[data-field-status]"),sourceType=card.dataset.sourceType;
    const payload={kind:"report",label:reset?card.dataset.sourceLabel:card.querySelector("[data-field-name]").value,type:reset?sourceType:card.querySelector("[data-field-type]").value,decimals:reset?defaultDecimals(sourceType):Number(card.querySelector("[data-field-decimals]")?.value||0)};
    if(payload.type==="percent")payload.percent_input_scale=reset?"auto":card.querySelector("[data-field-percent-scale]")?.value||"auto";
    card.querySelectorAll("button").forEach(item=>item.disabled=true);if(status)status.textContent="Saving…";
    try{
      const data=await R.api(`/api/fields/${encodeURIComponent(card.dataset.reportId)}/${encodeURIComponent(card.dataset.fieldKey)}`,R.json("PUT",payload));
      if(onSaved)onSaved({reportId:card.dataset.reportId,field:data.field});
      R.emit("fields-changed",{report_id:card.dataset.reportId,field:data.field});R.emit("data-changed");
    }catch(error){if(status)status.textContent=error.message||"Could not save Field.";card.querySelectorAll("button").forEach(item=>item.disabled=false);}
  }
  function bindShared(host,options={}){
    if(!host)return;
    host.querySelectorAll("[data-field-type],[data-custom-type]").forEach(input=>input.addEventListener("change",()=>{const editor=input.closest("[data-field-card]")||host,choices=editor.querySelector("[data-percent-input]");if(choices)choices.hidden=input.value!=="percent";}));
    host.querySelectorAll("[data-save-report-field]").forEach(button=>button.addEventListener("click",()=>saveReportField(button,false,options.onSaved)));
    host.querySelectorAll("[data-reset-report-field]").forEach(button=>button.addEventListener("click",()=>saveReportField(button,true,options.onSaved)));
    host.querySelectorAll("[data-close-report-field]").forEach(button=>button.addEventListener("click",()=>{const card=button.closest("[data-field-card]");if(options.onClose)options.onClose({reportId:card.dataset.reportId,key:card.dataset.fieldKey});}));
    host.querySelectorAll("[data-open-central-field]").forEach(button=>button.addEventListener("click",()=>R.emit("open-field",{report_id:button.dataset.reportId,field_key:button.dataset.fieldKey})));
  }
  function openById(fieldId,reports,host,options={}){
    const report=(reports||[]).find(item=>(item.fields||[]).some(field=>String(field.id)===String(fieldId))),field=report?.fields?.find(item=>String(item.id)===String(fieldId));
    if(!host)return;
    if(!field){host.innerHTML='<div class="small danger-text">Field is unavailable. Refresh the Field catalog.</div>';return;}
    host.innerHTML=reportForm(report.id,field);bindShared(host,options);
    host.scrollIntoView({block:"nearest",behavior:"smooth"});
  }
  window.StatsFieldEditor=Object.freeze({form:reportForm,bind:bindShared,openById,formatValue,typeLabel});

  async function openMatching(options={}){
    const dialog=document.createElement("dialog");
    dialog.setAttribute("aria-label","Match rows in Fields");
    dialog.style.cssText="width:min(820px,calc(100vw - 32px));max-height:90vh;padding:0;border:1px solid #687588;border-radius:12px;background:#101a29;color:#edf2f9;overflow:auto";
    dialog.innerHTML='<div class="card"><div class="toolbar"><h2>Match rows</h2><button class="btn" data-match-close>Close</button></div><p>Loading Fields…</p></div>';
    document.body.append(dialog);dialog.showModal();
    const close=()=>{dialog.close();dialog.remove();};
    dialog.addEventListener("close",()=>dialog.remove(),{once:true});
    dialog.querySelector("[data-match-close]").addEventListener("click",close);
    let catalog,rules,revision=0,verified=null,editing="";
    try{const data=await Promise.all([R.api("/api/fields/catalog"),R.api("/api/fields/matches")]);catalog=data[0].reports||[];rules=data[1].rules||[];}catch(error){if(dialog.isConnected){dialog.querySelector("p").textContent=error.message||"Could not load Fields.";}return;}
    if(!dialog.isConnected)return;
    const requested=new Set(options.fieldIds||[]),preferred=catalog.filter(report=>(report.fields||[]).some(field=>requested.has(field.id)));
    let leftReport=preferred[0]?.id||catalog[0]?.id||"",rightReport=preferred[1]?.id||catalog.find(report=>report.id!==leftReport)?.id||"",leftField="",rightField="",name="";
    const eligible=reportId=>(catalog.find(report=>report.id===reportId)?.fields||[]).filter(field=>field.kind==="report"&&["text","number"].includes(field.type));
    function formPayload(){return {id:editing,name,left_field_id:leftField,right_field_id:rightField};}
    function status(message){const node=dialog.querySelector("[data-match-status]");if(node)node.textContent=message;}
    function invalidate(){revision++;verified=null;dialog.querySelector("[data-match-save]").disabled=true;dialog.querySelector("[data-match-preview]").innerHTML="";status("");}
    async function check(){
      const turn=++revision;verified=null;dialog.querySelector("[data-match-save]").disabled=true;status("Checking current rows…");
      try{const data=await R.api("/api/fields/matches/preview",R.json("POST",formPayload()));if(!dialog.isConnected||turn!==revision)return;verified=data;
        const counts=data.counts||{};
        dialog.querySelector("[data-match-preview]").innerHTML=`<p><strong>${Number(counts.matched_rows||0)} matched</strong> · ${Number(counts.left_only_rows||0)} only on the left · ${Number(counts.right_only_rows||0)} only on the right</p><div class="data-table" style="max-height:260px;overflow:auto"><table><thead><tr><th>Left value</th><th>Right value</th><th>Result</th></tr></thead><tbody>${(data.rows||[]).map(row=>`<tr><td>${esc(row.left??"—")}</td><td>${esc(row.right??"—")}</td><td>${row.status==="matched"?"Matched":"Kept, unmatched"}</td></tr>`).join("")||'<tr><td colspan="3">No cached rows yet. The match is checked again whenever data is used.</td></tr>'}</tbody></table></div>`;
        status("Unmatched rows stay visible. Text matches exactly after trimming spaces; blank keys never match.");dialog.querySelector("[data-match-save]").disabled=false;
      }catch(error){if(turn===revision&&dialog.isConnected)status(error.message||"Could not check this match.");}
    }
    async function save(){
      if(!verified)return;
      dialog.querySelector("[data-match-save]").disabled=true;status("Saving reusable match…");
      try{const data=await R.api(editing?`/api/fields/matches/${encodeURIComponent(editing)}`:"/api/fields/matches",R.json(editing?"PUT":"POST",formPayload()));
        R.emit("field-matches-changed",{rule:data.rule});R.emit("fields-changed",{matching_rule:data.rule});
        if(options.onSaved){close();await options.onSaved({rule:data.rule});}
        else{rules=(await R.api("/api/fields/matches")).rules||[];editing="";leftField="";rightField="";name="";renderMatching();status("Saved. Other Widgets can use this match.");}
      }catch(error){if(dialog.isConnected){status(error.message||"Could not save match.");dialog.querySelector("[data-match-save]").disabled=false;}}
    }
    function renderMatching(){
      revision++;verified=null;
      const reports=(selected,exclude)=>catalog.filter(report=>report.id!==exclude).map(report=>`<option value="${esc(report.id)}" ${report.id===selected?"selected":""}>${esc(report.name||report.id)}</option>`).join("");
      const choices=(reportId,selected)=>`<option value="">Choose matching Field…</option>${eligible(reportId).map(field=>`<option value="${esc(field.id)}" ${field.id===selected?"selected":""}>${esc(field.label)} · ${esc(typeLabel(field.type))}</option>`).join("")}`;
      dialog.innerHTML=`<div class="card" style="margin:0"><div class="toolbar"><div><h2>Match rows</h2><div class="small">Fields · saved for reuse across Widgets</div></div><button class="btn" data-match-close>Close</button></div>${catalog.length<2?'<p>Pull another Report in Data before matching Reports.</p>':`<p>Choose the Fields that identify the same row in each Report.</p><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px"><div><label>Left Report</label><select data-match-report="left">${reports(leftReport,rightReport)}</select><label>Match this Field</label><select data-match-field="left">${choices(leftReport,leftField)}</select></div><div><label>Right Report</label><select data-match-report="right">${reports(rightReport,leftReport)}</select><label>With this Field</label><select data-match-field="right">${choices(rightReport,rightField)}</select></div></div><label style="margin-top:12px">Match name (optional)</label><input data-match-name value="${esc(name)}" placeholder="Name this reusable match"><div class="row" style="margin-top:12px"><button class="btn" data-match-check>Check match</button><button class="btn primary" data-match-save disabled>Save match</button>${editing?'<button class="btn" data-match-new>New match</button>':""}</div><div data-match-preview></div>`}<div class="status" data-match-status role="status"></div>${rules.length?`<details style="margin-top:16px"><summary>Saved matches (${rules.length})</summary>${rules.map(rule=>`<div class="toolbar" style="margin-top:10px"><div><strong>${esc(rule.name)}</strong><div class="small">${esc(rule.left?.field?.label||"Missing Field")} ↔ ${esc(rule.right?.field?.label||"Missing Field")}</div></div><div class="row"><button class="btn" data-match-edit="${esc(rule.id)}">Edit</button><button class="btn danger" data-match-delete="${esc(rule.id)}">Delete</button></div></div>`).join("")}</details>`:""}</div>`;
      dialog.querySelector("[data-match-close]").addEventListener("click",close);
      dialog.querySelectorAll("[data-match-report]").forEach(input=>input.addEventListener("change",()=>{if(input.dataset.matchReport==="left"){leftReport=input.value;leftField="";}else{rightReport=input.value;rightField="";}renderMatching();}));
      dialog.querySelectorAll("[data-match-field]").forEach(input=>input.addEventListener("change",()=>{if(input.dataset.matchField==="left")leftField=input.value;else rightField=input.value;invalidate();}));
      dialog.querySelector("[data-match-name]")?.addEventListener("input",event=>{name=event.target.value;});
      dialog.querySelector("[data-match-check]")?.addEventListener("click",check);
      dialog.querySelector("[data-match-save]")?.addEventListener("click",save);
      dialog.querySelector("[data-match-new]")?.addEventListener("click",()=>{editing="";leftField="";rightField="";name="";renderMatching();});
      dialog.querySelectorAll("[data-match-edit]").forEach(button=>button.addEventListener("click",()=>{const rule=rules.find(item=>item.id===button.dataset.matchEdit);if(!rule||rule.status!=="ready"){status("A matching Field is unavailable. Remove the broken match first.");return;}editing=rule.id;name=rule.name;leftReport=rule.left.report.id;rightReport=rule.right.report.id;leftField=rule.left_field_id;rightField=rule.right_field_id;renderMatching();}));
      dialog.querySelectorAll("[data-match-delete]").forEach(button=>button.addEventListener("click",async()=>{const rule=rules.find(item=>item.id===button.dataset.matchDelete);if(!rule||!confirm(`Delete the reusable match “${rule.name}”?`))return;try{await R.api(`/api/fields/matches/${encodeURIComponent(rule.id)}`,{method:"DELETE"});rules=rules.filter(item=>item.id!==rule.id);editing="";leftField="";rightField="";renderMatching();R.emit("field-matches-changed",{deleted:rule.id});R.emit("fields-changed",{matching_rule_id:rule.id});}catch(error){status(error.message);}}));
    }
    renderMatching();
  }
  window.StatsFields=Object.freeze({openMatching});

  const S={reports:[],reportId:"",catalog:null,search:"",selectedKey:"",creating:"",message:""};
  let loaded=false;
  const selectedReport=()=>S.reports.find(item=>String(item.id)===String(S.reportId))||null;
  const fields=()=>S.catalog?.fields||[];
  const selectedField=()=>fields().find(field=>String(field.key)===String(S.selectedKey))||null;
  async function loadReports(){const data=await R.api("/api/fields");S.reports=data.reports||[];if(!S.reports.some(item=>String(item.id)===String(S.reportId)))S.reportId=S.reports[0]?.id||"";loaded=true;await loadCatalog();}
  async function loadCatalog(){S.catalog=S.reportId?await R.api(`/api/fields/${encodeURIComponent(S.reportId)}`):null;render();}

  function reportChoices(){return S.reports.map(report=>`<option value="${esc(report.id)}" ${String(report.id)===String(S.reportId)?"selected":""}>${esc(report.name||report.id)}</option>`).join("");}
  function fieldRows(){
    const query=S.search.trim().toLowerCase();
    const rows=fields().filter(field=>!query||`${field.label} ${field.key} ${field.kind}`.toLowerCase().includes(query));
    return rows.map(field=>`<tr class="${String(field.key)===String(S.selectedKey)?"field-editing":""}"><td><button class="table-field-button" type="button" data-select-field="${esc(field.key)}"><strong>${esc(field.label||field.key)}</strong><span>${esc(field.key)}</span></button></td><td>${esc(kindLabel(field.kind))}</td><td>${esc(typeLabel(field.type))}</td><td>${field.type==="number"||field.type==="percent"?Number(field.decimals??defaultDecimals(field.type)):"—"}</td></tr>`).join("")||'<tr><td colspan="4">No matching Fields.</td></tr>';
  }
  function typeSelect(value){return TYPES.map(([key,label])=>`<option value="${key}" ${value===key?"selected":""}>${label}</option>`).join("");}
  function calculatedEditor(field={}){
    const sourceFields=fields().filter(item=>item.kind==="report");
    return `<div class="card"><div class="toolbar"><div><h3>${field.key?"Edit":"Add"} Calculated Field</h3><div class="small">This calculation belongs to ${esc(selectedReport()?.name||"the selected Report")}.</div></div><button class="btn" data-action="close-field-editor">Close</button></div><div class="grid"><div><label>Field name</label><input data-custom-name value="${esc(field.label||"")}" placeholder="Average Net Sale"></div><div><label>Display</label><select data-custom-type>${typeSelect(field.type||"number")}</select></div><div><label>Rounding decimals</label><input data-custom-decimals type="number" min="0" max="8" value="${Number(field.decimals??2)}"></div></div>${percentInput(field,"data-custom-percent-scale")}<div style="margin-top:10px"><label>Formula</label><textarea data-custom-formula rows="3" placeholder="[Net] ÷ [Sold Leads]">${esc(field.formula||"")}</textarea><div class="row" style="margin-top:7px"><select data-formula-field style="width:auto;min-width:220px">${sourceFields.map(item=>`<option value="${esc(item.key)}">${esc(item.label||item.key)}</option>`).join("")}</select><button class="btn" type="button" data-action="insert-formula-field">Insert Field</button><span class="small strong">Operator</span>${[[" + ","+"],[" − ","−"],[" × ","×"],[" ÷ ","÷"]].map(([value,label])=>`<button class="btn" type="button" data-formula-token="${value}">${label}</button>`).join("")}</div></div><div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-calculated">Save Field</button>${field.key?'<button class="btn danger" data-action="delete-field">Delete</button>':""}</div></div>`;
  }
  function groupEditor(field={}){
    const types=S.catalog?.group_types||[],properties=S.catalog?.group_properties||[];
    return `<div class="card"><div class="toolbar"><div><h3>${field.key?"Edit":"Add"} Group Field</h3><div class="small">Each row inherits this property from the named Group containing that member.</div></div><button class="btn" data-action="close-field-editor">Close</button></div>${types.length?`<div class="grid"><div><label>Field name</label><input data-custom-name value="${esc(field.label||"")}" placeholder="Team Logo"></div><div><label>Group Type</label><select data-group-type>${types.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===String(field.group_type_id)?"selected":""}>${esc(item.name)}</option>`).join("")}</select></div><div><label>Inherited property</label><select data-group-property>${properties.map(item=>`<option value="${esc(item.key)}" ${String(item.key)===String(field.property)?"selected":""}>${esc(item.label)}</option>`).join("")}</select></div></div><div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-group-field">Save Field</button>${field.key?'<button class="btn danger" data-action="delete-field">Delete</button>':""}</div>`:'<div class="small">Create a Group Type for this Report before adding a Group Field.</div>'}</div>`;
  }
  function rankEditor(field){
    const types=S.catalog?.group_types||[],assets=(S.catalog?.group_properties||[]).filter(item=>String(item.key).startsWith("asset:"));
    return `<div class="card"><div class="toolbar"><div><h3>Edit Rank</h3><div class="small">Rank follows the current table order after sorting and filtering.</div></div><button class="btn" data-action="close-field-editor">Close</button></div><div class="grid"><div><label>Field name</label><input data-custom-name value="${esc(field.label||"Rank")}"></div><div><label>First-place Group Type</label><select data-group-type><option value="">Show 1 as a number</option>${types.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===String(field.group_type_id)?"selected":""}>${esc(item.name)}</option>`).join("")}</select></div><div><label>First-place asset</label><select data-rank-asset>${assets.map(item=>{const key=String(item.key).slice(6);return`<option value="${esc(key)}" ${key===String(field.first_place_asset)?"selected":""}>${esc(item.label)}</option>`;}).join("")}</select></div></div><div class="row" style="margin-top:14px"><button class="btn primary" data-action="save-rank">Save Field</button></div></div>`;
  }
  function reportEditor(field){return `<div class="card"><div class="toolbar"><div><h3>Report Field</h3><div class="small">Name, display, and rounding changes apply everywhere this Field is used.</div></div><button class="btn" data-action="close-field-editor">Close</button></div>${reportForm(S.reportId,field)}</div>`;}
  function editor(){
    if(S.creating==="calculated")return calculatedEditor();
    if(S.creating==="group")return groupEditor();
    const field=selectedField();if(!field)return'<div class="card"><strong>Select a Field</strong><div class="small" style="margin-top:6px">Its global definition will open here.</div></div>';
    if(field.kind==="report")return reportEditor(field);
    if(field.kind==="calculated")return calculatedEditor(field);
    if(field.kind==="group")return groupEditor(field);
    return rankEditor(field);
  }
  function sample(){
    const catalog=S.catalog||{},previewFields=fields(),rows=catalog.sample_rows||[];
    const cell=(row,field)=>{const value=row[field.key];if((row.__invalid_fields||[]).includes(field.key)||(field.kind==="calculated"&&value===null))return "Unavailable";if(field.type==="asset")return value?`<img class="field-asset-preview" src="${esc(value)}" alt="">`:"";const asset=row.__field_assets?.[field.key];return asset?`<img class="field-asset-preview" src="${esc(asset)}" alt="1">`:esc(formatValue(value,field.type,field.decimals,field.percent_input_scale));};
    return `<div class="card"><div class="toolbar"><div><h3>Field Preview</h3><div class="small">All Fields from ${esc(catalog.report?.name||"the Report")}.</div></div></div><div class="data-table" style="margin-top:10px"><table><thead><tr>${previewFields.map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${previewFields.map(field=>`<td>${cell(row,field)}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(1,previewFields.length)}">No pulled rows.</td></tr>`}</tbody></table></div></div>`;
  }
  function render(){
    const host=$("settingsFieldsHost");if(!host)return;
    if(!S.reports.length){host.innerHTML='<div class="card"><h2>Fields</h2><div class="small">Save and pull a Report in Data first.</div></div>';return;}
    host.innerHTML=`<div class="card"><div class="toolbar"><div><h2>Fields</h2><div class="small">One global Field definition for every Data view and Screen.</div></div><div class="row"><button class="btn" data-action="match-rows">Match rows</button><button class="btn" data-new-field="calculated">+ Calculated Field</button><button class="btn" data-new-field="group">+ Group Field</button></div></div><div class="grid" style="margin-top:12px"><div><label>Report</label><select id="fieldsReport">${reportChoices()}</select></div><div><label>Search</label><input id="fieldsSearch" type="search" value="${esc(S.search)}" placeholder="Search Fields…"></div></div><div class="fields-layout" style="margin-top:14px"><div class="data-table"><table><thead><tr><th>Field</th><th>Kind</th><th>Display</th><th>Decimals</th></tr></thead><tbody>${fieldRows()}</tbody></table></div><div>${editor()}</div></div><div class="status">${esc(S.message)}</div></div>${sample()}`;
    bind();
  }
  async function refresh(keepKey=""){await loadReports();S.selectedKey=keepKey;S.creating="";S.message="";render();}
  async function saveCustom(kind){
    const host=$("settingsFieldsHost"),field=selectedField(),editing=field&&field.kind===kind,payload={kind,label:host.querySelector("[data-custom-name]")?.value||""};
    if(kind==="calculated")Object.assign(payload,{formula:host.querySelector("[data-custom-formula]")?.value||"",type:host.querySelector("[data-custom-type]")?.value||"number",decimals:Number(host.querySelector("[data-custom-decimals]")?.value||0)});
    if(kind==="calculated"&&payload.type==="percent")payload.percent_input_scale=host.querySelector("[data-custom-percent-scale]")?.value||"auto";
    if(kind==="group")Object.assign(payload,{group_type_id:host.querySelector("[data-group-type]")?.value||"",property:host.querySelector("[data-group-property]")?.value||""});
    try{const data=await R.api(editing?`/api/fields/${encodeURIComponent(S.reportId)}/${encodeURIComponent(field.key)}`:`/api/fields/${encodeURIComponent(S.reportId)}`,R.json(editing?"PUT":"POST",payload));await refresh(data.field.key);S.message=`${data.field.label} saved globally.`;render();R.emit("fields-changed",{report_id:S.reportId,field:data.field});R.emit("data-changed");}catch(error){S.message=error.message;render();}
  }
  async function saveRank(){const host=$("settingsFieldsHost"),field=selectedField(),payload={kind:"table",label:host.querySelector("[data-custom-name]")?.value||"Rank",group_type_id:host.querySelector("[data-group-type]")?.value||"",first_place_asset:host.querySelector("[data-rank-asset]")?.value||"medallion"};try{const data=await R.api(`/api/fields/${encodeURIComponent(S.reportId)}/${encodeURIComponent(field.key)}`,R.json("PUT",payload));await refresh(data.field.key);S.message="Rank saved globally.";render();R.emit("fields-changed",{report_id:S.reportId,field:data.field});}catch(error){S.message=error.message;render();}}
  async function deleteField(){const field=selectedField();if(!field||!confirm(`Delete ${field.label}?`))return;try{await R.api(`/api/fields/${encodeURIComponent(S.reportId)}/${encodeURIComponent(field.key)}`,{method:"DELETE"});await refresh();S.message="Field deleted.";render();R.emit("fields-changed",{report_id:S.reportId});R.emit("data-changed");}catch(error){S.message=error.message;render();}}
  function bind(){
    const host=$("settingsFieldsHost");if(!host)return;bindShared(host,{onSaved:async({field})=>{await refresh(field.key);S.message=`${field.label} saved globally.`;render();},onClose:()=>{S.selectedKey="";render();}});
    $("fieldsReport")?.addEventListener("change",async event=>{S.reportId=event.target.value;S.selectedKey="";S.creating="";await loadCatalog();});
    $("fieldsSearch")?.addEventListener("input",event=>{S.search=event.target.value;render();requestAnimationFrame(()=>$("fieldsSearch")?.focus());});
    host.querySelectorAll("[data-select-field]").forEach(button=>button.addEventListener("click",()=>{S.selectedKey=button.dataset.selectField;S.creating="";render();}));
    host.querySelectorAll("[data-new-field]").forEach(button=>button.addEventListener("click",()=>{S.creating=button.dataset.newField;S.selectedKey="";render();}));
    host.querySelector('[data-action="match-rows"]')?.addEventListener("click",()=>openMatching());
    host.querySelectorAll("[data-formula-token]").forEach(button=>button.addEventListener("click",()=>{const area=host.querySelector("[data-custom-formula]");if(!area)return;const token=button.dataset.formulaToken||"",start=area.selectionStart??area.value.length;area.value=area.value.slice(0,start)+token+area.value.slice(area.selectionEnd??start);area.focus();area.selectionStart=area.selectionEnd=start+token.length;}));
    host.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",()=>{const action=button.dataset.action;if(action==="close-field-editor"){S.selectedKey="";S.creating="";render();}else if(action==="save-calculated")saveCustom("calculated");else if(action==="save-group-field")saveCustom("group");else if(action==="save-rank")saveRank();else if(action==="delete-field")deleteField();else if(action==="insert-formula-field"){const area=host.querySelector("[data-custom-formula]"),select=host.querySelector("[data-formula-field]");if(area&&select){const token=`[${select.value}]`,start=area.selectionStart??area.value.length;area.value=area.value.slice(0,start)+token+area.value.slice(area.selectionEnd??start);area.focus();area.selectionStart=area.selectionEnd=start+token.length;}}}));
  }
  R.on("section",id=>{if(id==="settingsFields"){if(!loaded)loadReports().catch(error=>{S.message=error.message;render();});else render();}});
  R.on("unlocked",()=>{loaded=false;});R.on("data-changed",()=>{loaded=false;});R.on("groups-changed",()=>{loaded=false;});
  R.on("open-field",async detail=>{document.querySelector('[data-settings-target="settingsFields"]')?.click();if(!loaded)await loadReports();if(detail?.report_id&&S.reports.some(item=>String(item.id)===String(detail.report_id))){S.reportId=detail.report_id;await loadCatalog();}S.selectedKey=detail?.field_key||"";S.creating="";render();});
})();
