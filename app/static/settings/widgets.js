/* Widgets owns Field selections and calculations; matching, sources and global formatting have other owners. */
(function(){
  const R=window.StatsSettings,Renderer=window.StatsWidgetRenderer,esc=R.esc,copy=value=>JSON.parse(JSON.stringify(value));
  const S={widgets:[],reports:[],draft:null,verified:null,payload:null,inspectionPayload:null,history:[],message:"",previewError:"",pendingLabel:"",loading:false,saving:false,
    expanded:new Set(),search:"",dataView:false,panel:null};
  const host=()=>document.getElementById("settingsWidgetsHost");
  let loaded=false,previewTimer=null,previewController=null,requestVersion=0,disposeFormula=null;
  let indexedCatalog=null,fieldIndex=new Map();
  const field=id=>{if(indexedCatalog!==S.reports){indexedCatalog=S.reports;fieldIndex=new Map(S.reports.flatMap(report=>report.fields||[]).map(item=>[String(item.id),item]));}return fieldIndex.get(String(id));};
  const numeric=item=>item&&["number","percent"].includes(item.type)&&item.kind!=="table";
  const selected=()=>S.draft.field_ids.map(field).filter(Boolean),label=id=>field(id)?.label||field(id)?.name||"Missing Field";
  const calculationFields=()=>selected().filter(item=>item.type!=="asset"&&item.kind!=="table");
  const labelFields=()=>selected().filter(item=>item.type!=="asset"&&item.kind!=="table");
  const blankChart=()=>({dimension_field_id:"",measure_field_ids:[],aggregation:"none",measure_settings:{},layout:"separate",pie_mode:"auto",category_order:"source"});
  const blank=()=>({name:"New Widget",kind:"table",field_ids:[],filters:[],chart:blankChart()});
  const definition=()=>copy(S.draft),fingerprint=value=>JSON.stringify(value);
  const setting=(id,draft=S.draft)=>{
    const chart=draft.chart,config={aggregation:chart.aggregation||"none",...Object.fromEntries(["denominator_field_id","result_type","ratio_mode"].filter(key=>chart[key]!==undefined).map(key=>[key,chart[key]])),...chart.measure_settings?.[id]};
    if(config.aggregation==="ratio"){config.ratio_mode=config.ratio_mode||"totals";config.result_type=config.result_type||"percent";}return config;
  };
  const operators=[["equals","Equals"],["not_equals","Does not equal"],["contains","Contains"],["not_contains","Does not contain"],["greater_than","Greater than"],["greater_or_equal","At least"],["less_than","Less than"],["less_or_equal","At most"]];
  const options=(items,value,empty="Choose Field…")=>`<option value="">${esc(empty)}</option>${items.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===String(value)?"selected":""}>${esc(item.label||item.name||item.id)}</option>`).join("")}`;
  function normalize(value){const draft=copy(value);draft.chart={...blankChart(),...(draft.chart&&!draft.chart.layout?{layout:"shared"}:{}),...draft.chart};draft.chart.measure_settings={...draft.chart.measure_settings};draft.field_ids=draft.field_ids||[];draft.filters=draft.filters||[];return draft;}
  function calculationLabel(config){return config.aggregation==="ratio"?({individual:"Divide each row",row_average:"Average of row ratios",totals:"Divide totals"}[config.ratio_mode||"totals"]):({none:"Individual values",sum:"Total",average:"Average",count:"Count"}[config.aggregation]||"Individual values");}
  function validation(draft=S.draft){
    if(!draft?.field_ids.length)return "Browse Fields to begin.";
    if(draft.kind==="table")return "";
    const values=draft.chart.measure_field_ids||[];
    if(!values.length)return "Choose a numeric Field to compare, or count a selected Field.";
    for(const id of values){
      const item=field(id),config=setting(id,draft);
      if(!draft.field_ids.includes(id))return `${label(id)} is no longer selected. Restore it or remove that chart value.`;
      if(config.aggregation!=="count"&&!numeric(item))return `${label(id)} is ${item?.type||"unavailable"}, not numeric. Edit its type in Fields if necessary, or choose Count.`;
      if(config.aggregation==="sum"&&item?.type==="percent")return "Percentages cannot be added into a combined rate. Choose Average or calculate from underlying values.";
      if(config.aggregation==="ratio"&&(!numeric(field(config.denominator_field_id))||!draft.field_ids.includes(config.denominator_field_id)))return `Choose a selected numeric Field to divide ${label(id)} by.`;
    }
    return "";
  }
  function saveError(){return (["formula","global"].includes(S.panel?.kind)?"Finish or close the Field edit before saving this Widget.":"")||(S.panel?.kind==="column"&&S.panel.config?.aggregation==="ratio"&&!S.panel.config.denominator_field_id?"Choose a field to divide by.":"")||validation()||(S.saving?"Saving Widget…":"")||(S.loading?"Wait for the requested real-data preview.":"")||S.previewError||(!S.payload||!S.verified||fingerprint(S.verified)!==fingerprint(definition())?"Verify the current changes before saving.":"");}
  async function load(){const [widgets,catalog]=await Promise.all([R.api("/api/widgets"),R.api("/api/fields/catalog")]);S.widgets=widgets.widgets||[];S.reports=catalog.reports||[];loaded=true;render();}
  function library(){return `<div class="card"><div class="toolbar"><h2>Widgets</h2><button class="btn primary" data-widget-action="new">+ Widget</button></div>${S.draft?"":`<div class="stack">${S.widgets.map(item=>`<div class="subcard toolbar"><div><strong>${esc(item.name)}</strong><div class="small">${esc(item.kind)} · ${(item.field_ids||[]).length} Fields</div></div><div class="row"><button class="btn" data-widget-action="edit" data-id="${esc(item.id)}">Edit</button><button class="btn danger" data-widget-action="delete" data-id="${esc(item.id)}">Delete</button></div></div>`).join("")||'<div class="small">Start with Fields. Inspect the data, then decide what to show.</div>'}</div>`}</div>`;}
  function catalogMarkup(){
    const chosen=new Set(S.draft.field_ids),search=S.search.trim().toLocaleLowerCase();
    return S.reports.map(report=>{
      const items=(report.fields||[]).filter(item=>!search||`${item.label} ${item.type}`.toLocaleLowerCase().includes(search));if(!items.length)return "";
      return `<details class="widget-source-fields" data-widget-catalog="${esc(report.id)}" ${search||S.expanded.has(report.id)?"open":""}><summary>${esc(report.name)} <span class="small" data-widget-selection-count>${items.filter(item=>chosen.has(item.id)).length} / ${items.length}</span></summary><div class="widget-catalog-actions"><button class="btn widget-small-button" data-widget-action="select-fields" data-id="${esc(report.id)}" ${items.every(item=>chosen.has(item.id))?"disabled":""}>${search?"Select matches":"Select all"}</button><button class="btn widget-small-button" data-widget-action="clear-fields" data-id="${esc(report.id)}" ${items.some(item=>chosen.has(item.id))?"":"disabled"}>${search?"Clear matches":"Clear"}</button></div><div class="widget-field-catalog">${items.map(item=>`<label class="choice"><input type="checkbox" data-widget-field="${esc(item.id)}" ${chosen.has(item.id)?"checked":""}><span><strong>${esc(item.label)}</strong><span class="field-key">${esc(item.type)}</span></span></label>`).join("")}</div></details>`;
    }).join("")||`<div class="small">${search?"No matching Fields.":"Pull data in Data to make Fields available."}</div>`;
  }
  function fieldShelf(){return `<div class="widget-field-shelf">${S.draft.field_ids.map(id=>{
    const config=setting(id),isMeasure=S.draft.chart.measure_field_ids.includes(id);
    return `<div class="widget-field-chip" data-widget-drop="${esc(id)}"><span class="column-drag-handle" draggable="true" data-widget-drag="${esc(id)}" title="Drag to reorder">⋮⋮</span><button class="widget-chip-main" data-widget-action="inspect" data-id="${esc(id)}"><strong>${esc(label(id))}</strong><span>${esc(S.draft.chart.dimension_field_id===id?"Labels":isMeasure?calculationLabel(config):field(id)?.type||"unavailable")}</span></button><button class="btn widget-small-button" data-widget-action="remove-field" data-id="${esc(id)}" aria-label="Remove ${esc(label(id))}">×</button></div>`;
  }).join("")}<button class="btn" data-widget-action="browse">+ Field</button></div>`;}

  function contextMarkup(){
    if(!S.payload)return "";
    const shown=S.inspectionPayload||S.payload,count=shown.total_rows??shown.rows?.length??0;
    return `<span>${count} ${S.inspectionPayload?"contributing rows":"rows"} · Saved Data timeframe</span>${S.loading||S.previewError?'<span class="widget-pending-label">Showing the last verified result.</span>':""}`;
  }
  function resultPayload(){
    if(S.inspectionPayload)return S.inspectionPayload;
    return S.dataView&&S.payload?{...S.payload,kind:"table"}:S.payload;
  }
  function previewMarkup(){
    const payload=resultPayload();
    if(!payload)return `<div class="widget-empty">${esc(S.loading?"Loading…":S.previewError||"Pick fields to see your data.")}</div>`;
    return Renderer.render(payload,{fit:{font_size:14,row_height:34,padding:7},editableFields:"context"});
  }
  function inspectPoint(point){
    if(!S.payload||!window.StatsWidgetCharts?.inspect)return;
    const inspection=window.StatsWidgetCharts.inspect(S.payload,point);if(!inspection)return;
    closePanel();S.inspectionPayload=inspection;updatePanel();updatePreview();
  }
  function toolbarMarkup(){
    if(!S.draft.field_ids.length)return "";
    const kind=S.draft.kind==="pie"&&S.draft.chart.pie_mode==="percentage"?"Circles":{table:"Table",bar:"Bars",pie:"Pie",line:"Line"}[S.draft.kind];
    return `<button class="btn" data-widget-action="representation">Show as: ${kind}</button><button class="btn" data-widget-action="filters">Filters${S.draft.filters.length?` (${S.draft.filters.length})`:""}</button>${S.draft.kind!=="table"?`<button class="btn" data-widget-action="data-view">${S.dataView||S.inspectionPayload?"Back to chart":"View data"}</button><button class="btn" data-widget-action="labels">Labels / order</button>`:""}`;
  }
  function visualOptions(){
    const draft=definition();
    const types=draft.chart.measure_field_ids.map(id=>{const config=setting(id,draft);return config.aggregation==="ratio"?config.result_type:config.aggregation==="count"?"number":field(id)?.type;});
    return [["table","Table"],...(types.length?[["bar","Bars"],["line","Line"],
      ...(types.every(type=>type==="percent")?[["percentage","Percentage circles"]]:[]),
      ...(types.every(type=>type==="number")&&!compositionLimitation()?[["pie","Pie"]]:[])]:[])];
  }

  function issueMarkup(){return !S.loading&&!S.previewError?"":`<div class="widget-pending" role="status"><strong>${esc(S.pendingLabel||"Pending change")}</strong><p>${esc(S.loading?"Checking this change against real data…":S.previewError)}</p>${!S.loading&&/match|dataset|compatible|relationship/i.test(S.previewError)&&window.StatsFields?.openMatching?'<button class="btn" data-widget-action="matching">Match Fields…</button>':""}${S.verified?'<button class="btn" data-widget-action="cancel-pending">Keep verified result</button>':""}</div>`;}

  function columnMarkup(){
    const id=S.panel.id,item=field(id),config=S.panel.config||setting(id);
    if(!item)return "";
    const choices=[["off","Not used"],...(numeric(item)?[["none","Individual values"],...(item.type==="percent"?[]:[["sum","Total"]]),["average","Average"]]:[]),["count","Count"],...(item.type==="number"?[["ratio","Divide by another field"]]:[])];
    const current=S.panel.config?config.aggregation:S.draft.chart.measure_field_ids.includes(id)?config.aggregation:"off";
    const canFormula=item.type!=="asset"&&item.kind!=="table"&&S.reports.some(report=>report.fields?.some(entry=>entry.id===id)&&report.fields.some(entry=>entry.kind==="report"&&entry.type==="number"));
    return `<div class="toolbar"><h3>${esc(label(id))} <span class="small">${esc(item.type)}</span></h3><button class="btn" data-widget-action="dismiss-panel">Close</button></div><div class="row"><button class="btn" data-widget-action="global-field" data-id="${esc(id)}">Edit Field globally</button>${canFormula?`<button class="btn" data-widget-action="calculate" data-id="${esc(id)}">Calculate</button>`:""}<button class="btn" data-widget-action="remove-field" data-id="${esc(id)}">Remove</button></div>${calculationFields().some(entry=>entry.id===id)?`<div class="widget-column-controls"><label>In charts<select data-widget-measure="aggregation">${choices.map(([value,title])=>`<option value="${value}" ${current===value?"selected":""}>${title}</option>`).join("")}</select></label><button class="btn" data-widget-action="use-label" data-id="${esc(id)}">Use as labels</button></div>${current==="ratio"?`<div class="widget-column-controls"><label>Divide by<select data-widget-measure="denominator_field_id">${options(selected().filter(entry=>entry.type==="number"&&entry.kind!=="table"),config.denominator_field_id)}</select></label><label>Calculate<select data-widget-measure="ratio_mode">${[["totals","Divide totals"],["individual","Divide each row"],["row_average","Average of row ratios"]].map(([value,title])=>`<option value="${value}" ${(config.ratio_mode||"totals")===value?"selected":""}>${title}</option>`).join("")}</select></label><label>Display<select data-widget-measure="result_type"><option value="number" ${config.result_type!=="percent"?"selected":""}>Number</option><option value="percent" ${config.result_type==="percent"?"selected":""}>Percentage</option></select></label></div>`:""}`:""}`;
  }
  function updateColumn(part,value){
    if(S.saving||S.panel?.kind!=="column")return;
    const id=S.panel.id,config={...(S.panel.config||setting(id)),[part]:value};
    if(part==="aggregation"&&value!=="ratio")for(const key of ["denominator_field_id","ratio_mode","result_type"])delete config[key];
    if(config.aggregation==="ratio"){
      config.ratio_mode=config.ratio_mode||"totals";config.result_type=config.result_type||"number";
      if(!config.denominator_field_id){S.panel.config=config;updatePanel();updatePreview(false);return;}
    }
    S.panel.config=config;
    change(draft=>{
      if(config.aggregation==="off"){draft.chart.measure_field_ids=draft.chart.measure_field_ids.filter(value=>value!==id);delete draft.chart.measure_settings[id];}
      else{if(!draft.chart.measure_field_ids.includes(id))draft.chart.measure_field_ids.push(id);draft.chart.measure_settings[id]=copy(config);}
    },`Updating ${label(id)}`);
  }

  function orderMarkup(){return `<label>Order values by<select data-widget-order ${S.draft.chart.dimension_field_id?"":"disabled"}>${[["source","Current table order"],["number","Number · smallest first"],["date","Date · oldest first (YYYY-MM-DD)"]].map(([value,title])=>`<option value="${value}" ${(S.draft.chart.category_order||"source")===value?"selected":""}>${title}</option>`).join("")}</select></label>`;}
  function panelMarkup(){
    const panel=S.panel;if(!panel)return "";if(panel.kind==="column")return columnMarkup();
    if(panel.kind==="filters")return filterSettings();
    if(panel.kind==="global")return '<div class="toolbar"><h3>Edit Field</h3><button class="btn" data-widget-action="dismiss-panel">Close</button></div><div data-widget-global-editor></div>';
    if(panel.kind==="formula")return '<div data-widget-formula-host></div>';

    if(panel.kind==="labels")return `<div class="toolbar"><h3>Labels &amp; grouping</h3><button class="btn" data-widget-action="dismiss-panel">Close</button></div><label>Label values with<select data-widget-dimension>${options(labelFields(),S.draft.chart.dimension_field_id,"Row order / one summary")}</select></label><p class="small">Individual values stay separate even when labels repeat. Totals, averages and counts combine rows with the same label.</p>${orderMarkup()}`;

    if(panel.kind==="representation")return `<div class="toolbar"><h3>Show as</h3><button class="btn" data-widget-action="dismiss-panel">Close</button></div><label>Chart<select data-widget-representation><option value="">Choose…</option>${visualOptions().map(([id,title])=>`<option value="${id}">${title}</option>`).join("")}</select></label>${visualOptions().length===1?'<p class="small">Add a number field, or choose Count on a text column, to make a chart.</p>':""}${S.draft.chart.measure_field_ids.length>1?`<label>Scales<select data-widget-layout><option value="separate" ${S.draft.chart.layout==="separate"?"selected":""}>Separate</option><option value="shared" ${S.draft.chart.layout==="shared"?"selected":""}>Shared</option></select></label>`:""}${panel.requested==="line"?`<label>Date or sequence Field<select data-widget-dimension>${options(labelFields(),S.draft.chart.dimension_field_id)}</select></label>${orderMarkup()}`:""}${panel.question?`<p>${esc(panel.question)}</p>${panel.blocked?"":`<button class="btn" data-widget-action="confirm-visual" data-id="${esc(panel.requested)}">${panel.requested==="pie"?"These are parts of one whole":"Connect in this order"}</button>`}`:""}`;

    return "";
  }
  function filterDisplayValue(rule){return field(rule.field_id)?.type!=="percent"||["contains","not_contains"].includes(rule.operator)?rule.value:window.StatsFieldValues.format(rule.value,"percent",8,"auto").replace(/\.0+%$/,"%").replace(/(\.\d*?[1-9])0+%$/,"$1%");}
  function enteredFilterValue(rule,value){const text=String(value).trim();return field(rule.field_id)?.type==="percent"&&!["contains","not_contains"].includes(rule.operator)&&text&&!text.endsWith("%")&&Number.isFinite(Number(text.replace(/,/g,"")))?`${text}%`:value;}
  function filterSettings(){
    return `<div class="widget-filter-list"><div class="toolbar"><h3>Filters</h3><button class="btn" data-widget-action="dismiss-panel">Close</button></div>${S.draft.filters.map((rule,index)=>`<div class="widget-filter-row" data-widget-filter="${index}"><select data-filter-part="field_id" aria-label="Filter Field">${options(selected(),rule.field_id)}</select><select data-filter-part="operator" aria-label="Filter condition">${operators.map(([value,title])=>`<option value="${value}" ${rule.operator===value?"selected":""}>${title}</option>`).join("")}</select><input data-filter-part="value" value="${esc(filterDisplayValue(rule))}" ${field(rule.field_id)?.type==="percent"?'placeholder="e.g. 14.3%"':""} aria-label="Filter value"><button class="btn" data-widget-action="remove-filter" data-index="${index}" aria-label="Remove filter">×</button></div>`).join("")}<button class="btn" data-widget-action="add-filter">+ Filter</button></div>`;
  }

  function editor(){
    if(!S.draft)return "";
    return `<div class="card widget-editor"><div class="toolbar"><label class="widget-name-label">Widget name<input data-widget-name value="${esc(S.draft.name)}"></label><div class="row"><button class="btn" data-widget-action="undo" ${S.history.length?"":"disabled"}>Undo</button><button class="btn" data-widget-action="close">Close</button></div></div><div class="widget-workbench has-browser"><aside class="widget-browser"><h3>Fields</h3><input data-widget-search type="search" value="${esc(S.search)}" placeholder="Find a Field…" aria-label="Find a Field"><div class="stack" data-widget-catalog-list>${catalogMarkup()}</div></aside><main class="widget-working-canvas">${fieldShelf()}<div class="row widget-result-tools" data-widget-toolbar>${toolbarMarkup()}</div><div class="widget-inline-panel" data-widget-panel ${S.panel?"":"hidden"}>${panelMarkup()}</div><div data-widget-issue>${issueMarkup()}</div><div class="widget-preview-context" data-widget-context>${contextMarkup()}</div><div class="widget-builder-preview" data-widget-preview aria-live="polite">${previewMarkup()}</div><button class="btn" data-widget-action="theme-preview" ${saveError()?"disabled":""}>Preview in Theme Editor</button></main></div><div class="status" role="status" data-widget-message>${esc(S.message)}</div><div class="row"><button class="btn primary" data-widget-action="save" ${saveError()?"disabled":""}>${S.saving?"Saving…":"Save Widget"}</button><button class="btn" data-widget-action="close">Cancel</button></div></div>`;
  }
  function render(){const element=host();if(!element)return;element.innerHTML=library()+editor();bind();requestAnimationFrame(()=>Renderer.fit(element));}
  function message(text){S.message=text;const element=host()?.querySelector("[data-widget-message]");if(element)element.textContent=text;}
  function updatePreview(content=true){
    const element=host();if(!element||!S.draft)return;
    const updates=[["[data-widget-context]",contextMarkup()],["[data-widget-issue]",issueMarkup()]];
    if(content)updates.push(["[data-widget-preview]",previewMarkup()]);
    const toolbar=element.querySelector("[data-widget-toolbar]");if(toolbar)toolbar.innerHTML=toolbarMarkup();
    element.querySelector("[data-widget-preview]")?.classList.toggle("is-table",resultPayload()?.kind==="table");
    for(const [selector,markup] of updates){const node=element.querySelector(selector);if(node){const viewport=node.querySelector?.(".widget-table-viewport"),position=viewport?{top:viewport.scrollTop,left:viewport.scrollLeft}:null;node.innerHTML=markup;if(content){Renderer.fit(node);const next=node.querySelector?.(".widget-table-viewport");if(next&&position){next.scrollTop=position.top;next.scrollLeft=position.left;}}}}
    ["save","theme-preview"].forEach(name=>{const button=element.querySelector(`[data-widget-action="${name}"]`);if(button)button.disabled=!!saveError();});
  }
  function schedule(description="Checking changes",delay=200){
    clearTimeout(previewTimer);previewController?.abort();previewController=null;const version=++requestVersion;S.pendingLabel=description;S.previewError=validation();S.loading=!S.previewError;
    if(!S.draft?.field_ids.length&&!S.verified)S.previewError="";
    updatePreview(false);if(S.loading)previewTimer=setTimeout(()=>preview(version),delay);
  }
  async function preview(version){
    if(!S.draft||version!==requestVersion)return;const draft=definition(),controller=new AbortController();previewController=controller;let changed=false;
    try{const result=await R.api("/api/widgets/preview",{...R.json("POST",{widget:draft}),signal:controller.signal});if(version!==requestVersion||!S.draft)return;if(result.payload?.error)throw new Error(result.payload.error);if(!result.payload||typeof result.payload!=="object"||!Array.isArray(result.payload.rows))throw new Error("The real-data preview returned no verifiable result.");S.payload=result.payload;S.inspectionPayload=null;S.verified=draft;S.previewError="";S.pendingLabel="";changed=true;message("");}
    catch(error){if(version!==requestVersion||!S.draft)return;S.previewError=error.message;}
    finally{if(previewController===controller)previewController=null;if(version===requestVersion&&S.draft){S.loading=false;updatePreview(changed);}}
  }
  function change(mutator,description,{selection=false}={}){if(S.saving)return;S.history.push(definition());if(S.history.length>40)S.history.shift();mutator(S.draft);S.message="";schedule(description,selection?400:200);updateSelection();}
  function setFields(ids,checked){
    if(S.saving)return;const changed=ids.filter(id=>!!field(id)&&S.draft.field_ids.includes(id)!==checked);if(!changed.length)return;
    if(checked&&S.draft.field_ids.length+changed.length>100){message("Choose up to 100 Fields per Widget.");syncCatalog();return;}
    const removed=new Set(checked?[]:changed);if(S.panel?.kind!=="formula")closePanel();
    change(draft=>{
      if(checked){draft.field_ids.push(...changed);for(const id of changed)if(numeric(field(id))&&!draft.chart.measure_field_ids.includes(id)){draft.chart.measure_field_ids.push(id);draft.chart.measure_settings[id]={aggregation:"none"};}}
      else{draft.field_ids=draft.field_ids.filter(id=>!removed.has(id));draft.chart.measure_field_ids=draft.chart.measure_field_ids.filter(id=>!removed.has(id));for(const id of removed)delete draft.chart.measure_settings[id];if(removed.has(draft.chart.dimension_field_id)){draft.chart.dimension_field_id="";draft.chart.category_order="source";}draft.filters=draft.filters.filter(rule=>!removed.has(rule.field_id));}
    },`${checked?"Adding":"Removing"} ${changed.length===1?label(changed[0]):`${changed.length} Fields`}`,{selection:true});
  }
  function refreshCatalog(){
    const element=host(),list=element?.querySelector("[data-widget-catalog-list]");if(!list)return;
    const browser=element.querySelector(".widget-browser"),top=browser?.scrollTop||0;
    list.innerHTML=catalogMarkup();bindCatalog(list);if(browser)browser.scrollTop=top;
  }
  function syncCatalog(){
    const element=host(),chosen=new Set(S.draft.field_ids);if(!element)return;
    element.querySelectorAll("[data-widget-catalog]").forEach(details=>{const inputs=[...details.querySelectorAll("[data-widget-field]")];inputs.forEach(input=>{input.checked=chosen.has(input.dataset.widgetField);});const count=inputs.filter(input=>input.checked).length;details.querySelector("[data-widget-selection-count]").textContent=`${count} / ${inputs.length}`;details.querySelector('[data-widget-action="select-fields"]').disabled=count===inputs.length;details.querySelector('[data-widget-action="clear-fields"]').disabled=!count;});
  }
  function updateSelection(){
    const element=host();if(!element)return;
    const shelf=element.querySelector(".widget-field-shelf"),left=shelf?.scrollLeft||0;if(shelf){shelf.outerHTML=fieldShelf();element.querySelector(".widget-field-shelf").scrollLeft=left;}bindShelf(element);
    const toolbar=element.querySelector("[data-widget-toolbar]");if(toolbar)toolbar.innerHTML=toolbarMarkup();
    updatePanel();
    const undo=element.querySelector('[data-widget-action="undo"]');if(undo)undo.disabled=!S.history.length;
    syncCatalog();message("");
  }
  function edit(id){
    closePanel();clearTimeout(previewTimer);previewController?.abort();previewController=null;requestVersion++;S.draft=normalize(S.widgets.find(item=>String(item.id)===String(id))||blank());S.verified=null;S.payload=null;S.inspectionPayload=null;S.history=[];S.message="";S.previewError="";S.pendingLabel="";S.loading=false;S.saving=false;S.search="";S.dataView=false;S.panel=null;render();schedule();
  }
  function compositionLimitation(){
    const draft=definition();const ids=draft.chart.measure_field_ids;
    if(ids.length!==1||draft.chart.dimension_field_id)return "";
    const config=setting(ids[0],draft),individual=config.aggregation==="none"||config.aggregation==="ratio"&&config.ratio_mode==="individual";
    return individual?"":"One combined number does not define parts of a total. Keep the current visual, or choose labels or another value to define the parts.";
  }
  function chooseVisual(type,confirmed=false){
    const limitation=type==="pie"?compositionLimitation():"";
    closePanel();
    if(type!=="table"&&!S.draft.chart.measure_field_ids.length){S.panel={kind:"representation",question:"Choose a column to use in charts first.",blocked:true};updatePanel();return;}
    if(limitation){S.panel={kind:"representation",question:limitation,blocked:true};updatePanel();return;}
    if(type==="line"&&confirmed&&!S.draft.chart.dimension_field_id){S.panel={kind:"representation",requested:"line",question:"Choose the date or sequence Field before connecting values."};updatePanel();return;}
    if(["pie","line"].includes(type)&&!confirmed){S.panel={kind:"representation",requested:type,question:type==="pie"?"Are these separate parts of the same whole?":"Choose a date or sequence field and its order."};updatePanel();return;}
    S.dataView=false;S.inspectionPayload=null;
    change(draft=>{draft.kind=type==="percentage"?"pie":type;draft.chart.pie_mode=type==="percentage"?"percentage":type==="pie"?"composition":"auto";},`Requested ${type==="percentage"?"percentage circles":type} visual`);
  }

  function updatePanel(){
    const preview=host()?.querySelector("[data-widget-preview]");if(preview){const wasHidden=preview.hidden;preview.hidden=S.panel?.kind==="formula";if(wasHidden&&!preview.hidden)Renderer.fit(preview);}
    for(const name of ["save","theme-preview"]){const button=host()?.querySelector(`[data-widget-action="${name}"]`);if(button)button.disabled=!!saveError();}
    if(S.panel?.kind==="formula"&&disposeFormula||S.panel?.kind==="global"&&S.panel.mounted)return;
    const panel=host()?.querySelector("[data-widget-panel]");
    if(panel){panel.hidden=!S.panel;panel.innerHTML=panelMarkup();bindPanel(panel);}
  }
  function closePanel(){disposeFormula?.();disposeFormula=null;S.panel=null;}
  function openColumn(id){
    if(!field(id)||!S.draft.field_ids.includes(id))return;
    closePanel();S.panel={kind:"column",id};updatePanel();
  }

  function openFormula(id){
    if(!window.StatsFieldFormulas)return;closePanel();const panel=S.panel={kind:"formula",id};updatePanel();
    const container=host()?.querySelector("[data-widget-formula-host]"),draft=S.draft;if(!container)return;
    disposeFormula=window.StatsFieldFormulas.open({host:container,fieldId:id,reports:S.reports,onClose:()=>{if(S.panel===panel){closePanel();updatePanel();}},onSaved:async(saved,catalog)=>{
      S.reports=catalog;if(S.draft!==draft)return;refreshCatalog();
      if(S.panel!==panel){message("Field created. It is available in the Field list.");return;}closePanel();
      if(saved)setFields([saved.id],true);else{updatePanel();message("Field created. Find it in the Field list to add it.");}
    }});
  }

  function openGlobalField(id){
    closePanel();const panel=S.panel={kind:"global",id},draft=S.draft;updatePanel();
    const container=host()?.querySelector("[data-widget-global-editor]");if(!container)return;
    panel.mounted=true;
    window.StatsFieldEditor.openById(id,S.reports,container,{onClose:()=>{if(S.panel===panel){closePanel();updatePanel();}},onSaved:async()=>{
      S.reports=(await R.api("/api/fields/catalog")).reports||[];if(S.draft!==draft)return;
      refreshCatalog();if(S.panel===panel)closePanel();schedule("Global Field updated; verifying this Widget");updateSelection();
    }});
  }

  async function action(button){
    const name=button.dataset.widgetAction,id=button.dataset.id;if(S.saving)return;
    if(name==="new"||name==="edit")return edit(id);
    if(name==="close"){closePanel();clearTimeout(previewTimer);previewController?.abort();previewController=null;requestVersion++;S.draft=null;S.payload=null;S.loading=false;render();return;}
    if(name==="delete"){const widget=S.widgets.find(item=>item.id===id);if(!confirm(`Delete Widget "${widget?.name||""}"?`))return;try{await R.api(`/api/widgets/${encodeURIComponent(id)}`,{method:"DELETE"});await load();R.emit("widgets-changed");}catch(error){alert(error.message);}return;}
    if(name==="save"){
      const error=saveError();if(error){message(error);return;}closePanel();S.saving=true;updateSelection();updatePreview(false);
      try{const draft=definition(),result=await R.api(draft.id?`/api/widgets/${encodeURIComponent(draft.id)}`:"/api/widgets",R.json(draft.id?"PUT":"POST",draft));clearTimeout(previewTimer);requestVersion++;S.draft=null;S.payload=null;await load();R.emit("widgets-changed",result.widget);}catch(error){message(error.message);}finally{S.saving=false;render();}return;
    }
    if(name==="theme-preview"){if(saveError())return;try{await window.StatsThemeManager.preview({widget:definition(),context:{}});}catch(error){message(error.message);}return;}
    if(name==="undo"){if(!S.history.length)return;closePanel();S.draft=normalize(S.history.pop());schedule("Undoing the last change");updateSelection();return;}
    if(name==="cancel-pending"){if(!S.verified)return;closePanel();S.history.push(definition());S.draft=normalize(S.verified);schedule("Restoring the verified result");updateSelection();return;}
    if(name==="browse"){host()?.querySelector("[data-widget-search]")?.focus({preventScroll:true});return;}
    if(name==="data-view"){closePanel();S.dataView=!(S.dataView||S.inspectionPayload);S.inspectionPayload=null;updatePanel();updatePreview();return;}

    if(name==="filters"||name==="labels"||name==="representation"){const same=S.panel?.kind===name;closePanel();if(!same)S.panel={kind:name};updatePanel();return;}
    if(name==="inspect")return openColumn(id);
    if(name==="calculate")return openFormula(id);

    if(name==="global-field")return openGlobalField(id);

    if(name==="dismiss-panel"){closePanel();updatePanel();updatePreview(false);return;}

    if(name==="confirm-visual")return chooseVisual(id,true);
    if(name==="matching"){if(!window.StatsFields?.openMatching)return;window.StatsFields.openMatching({fieldIds:[...S.draft.field_ids],onSaved:async()=>{S.reports=(await R.api("/api/fields/catalog")).reports||[];refreshCatalog();schedule("Checking the saved Field match");updateSelection();}});return;}
    if(name==="use-label"){if(!labelFields().some(item=>item.id===id))return;closePanel();change(draft=>{draft.chart.dimension_field_id=id;},`Labels from ${label(id)}`);return;}
    if(name==="remove-field")return setFields([id],false);
    if(name==="select-fields"||name==="clear-fields"){const search=S.search.trim().toLocaleLowerCase(),report=S.reports.find(item=>String(item.id)===String(id)),ids=(report?.fields||[]).filter(item=>!search||`${item.label} ${item.type}`.toLocaleLowerCase().includes(search)).map(item=>item.id);return setFields(ids,name==="select-fields");}
    if(name==="add-filter"){change(draft=>{draft.filters.push({field_id:draft.field_ids[0],operator:"equals",value:""});},"New filter");return;}
    if(name==="remove-filter")change(draft=>{draft.filters.splice(Number(button.dataset.index),1);},"Removing filter");
  }
  function bindCatalog(element){
    element.querySelectorAll("[data-widget-catalog]").forEach(details=>details.addEventListener("toggle",()=>{if(details.open)S.expanded.add(details.dataset.widgetCatalog);else S.expanded.delete(details.dataset.widgetCatalog);}));
    element.querySelectorAll("[data-widget-field]").forEach(input=>input.addEventListener("change",()=>setFields([input.dataset.widgetField],input.checked)));
  }

  function bindPanel(element){
    bindFilters(element);
    element.querySelectorAll("[data-widget-measure]").forEach(input=>input.addEventListener("change",()=>updateColumn(input.dataset.widgetMeasure,input.value)));

    element.querySelector("[data-widget-dimension]")?.addEventListener("change",event=>change(draft=>{draft.chart.dimension_field_id=event.target.value;if(!event.target.value)draft.chart.category_order="source";},"Changing labels and grouping"));
    element.querySelector("[data-widget-order]")?.addEventListener("change",event=>change(draft=>{draft.chart.category_order=event.target.value;},"Changing chart order"));
    element.querySelector("[data-widget-representation]")?.addEventListener("change",event=>{if(event.target.value)chooseVisual(event.target.value);});
    element.querySelector("[data-widget-layout]")?.addEventListener("change",event=>change(draft=>{draft.chart.layout=event.target.value;},"Changing the scale layout"));
  }
  function bind(){
    const element=host();element.onclick=event=>{const button=event.target.closest("[data-widget-action]");if(button){action(button);return;}const point=event.target.closest("[data-chart-point]");if(point){inspectPoint(point);return;}const heading=event.target.closest("[data-widget-field-editor]");if(heading)openColumn(heading.dataset.widgetFieldEditor);};
    element.onkeydown=event=>{const point=event.target.closest("[data-chart-point]");if(point&&["Enter"," "].includes(event.key)){event.preventDefault();inspectPoint(point);}};
    bindCatalog(element);bindPanel(element);
    element.querySelector("[data-widget-name]")?.addEventListener("input",event=>{if(S.saving)return;S.draft.name=event.target.value;schedule("Updating Widget name");});
    element.querySelector("[data-widget-search]")?.addEventListener("input",event=>{S.search=event.target.value;const catalog=element.querySelector("[data-widget-catalog-list]");catalog.innerHTML=catalogMarkup();bindCatalog(catalog);});
    bindShelf(element);
  }
  function bindFilters(element){
    element.querySelectorAll("[data-filter-part]").forEach(input=>input.addEventListener(input.tagName==="INPUT"?"input":"change",()=>{const index=Number(input.closest("[data-widget-filter]").dataset.widgetFilter),part=input.dataset.filterPart,rule=S.draft.filters[index];if(!rule)return;S.history.push(definition());rule[part]=part==="value"?enteredFilterValue(rule,input.value):input.value;if(part==="field_id")rule.value="";schedule("Updating filter");if(part==="field_id")updatePanel();}));
  }
  function bindShelf(element){
    let dragging="";
    element.querySelectorAll("[data-widget-drag]").forEach(item=>item.addEventListener("dragstart",event=>{dragging=item.dataset.widgetDrag;event.dataTransfer.setData("text/plain",dragging);event.dataTransfer.effectAllowed="move";}));
    element.querySelectorAll("[data-widget-drop]").forEach(item=>{item.addEventListener("dragover",event=>{if(dragging)event.preventDefault();});item.addEventListener("drop",event=>{event.preventDefault();const before=item.dataset.widgetDrop;if(dragging&&before!==dragging)change(draft=>{const ids=draft.field_ids.filter(id=>id!==dragging);ids.splice(ids.indexOf(before),0,dragging);draft.field_ids=ids;draft.chart.measure_field_ids=ids.filter(id=>draft.chart.measure_field_ids.includes(id));},"Reordering Fields");dragging="";});});
  }
  R.on("section",id=>{if(id==="settingsWidgets"&&!loaded)load().catch(error=>{host().innerHTML=`<div class="card danger-text">${esc(error.message)}</div>`;});});
  ["fields-changed","data-changed","unlocked"].forEach(name=>R.on(name,()=>{loaded=false;}));
})();
