/* Fields-owned inline formula authoring. All arithmetic is evaluated by the Fields API. */
(function(){
  const R=window.StatsSettings,esc=R.esc;
  function expression(tokens){return tokens.map(token=>token.key?`[${token.key}]`:token.value).join(" ");}
  function open({host,fieldId,reports,onSaved,onClose}){
    const report=reports.find(item=>item.fields?.some(field=>field.id===fieldId));
    if(!report){host.innerHTML='<p>Choose an existing Field first.</p>';return ()=>{};}
    const fields=report.fields.filter(field=>field.kind==="report"&&field.type==="number"),anchor=fields.find(field=>field.id===fieldId);
    let tokens=anchor?[{key:anchor.key,label:anchor.label}]:[],revision=0,timer=null,controller=null,verified="",saving=false,closed=false,createdKey=null;
    const query=selector=>host.querySelector(selector);
    const body=()=>({kind:"calculated",label:query("[data-formula-name]").value.trim()||"Calculation preview",type:query("[data-formula-type]").value,decimals:Number(query("[data-formula-decimals]").value),percent_input_scale:"fraction",formula:expression(tokens)});
    const saveState=()=>{query("[data-formula-save]").disabled=saving||!query("[data-formula-name]").value.trim()||verified!==JSON.stringify(body());};
    function tokenMarkup(){query("[data-formula-expression]").innerHTML=tokens.map(token=>`<span class="formula-token ${token.key?"is-field":""}">${esc(token.label||token.value)}</span>`).join("")||'<span class="small">Choose a Field below</span>';}
    async function preview(turn){
      if(closed||turn!==revision)return;const incoming=body();controller=new AbortController();
      try{
        const result=await R.api(`/api/fields/${encodeURIComponent(report.id)}/preview`,{...R.json("POST",incoming),signal:controller.signal});
        if(closed||turn!==revision)return;const payload=result.payload;
        if(!payload||!Array.isArray(payload.rows))throw new Error("No calculation preview returned.");
        query("[data-formula-result]").innerHTML=window.StatsWidgetRenderer.render(payload,{fit:{font_size:14,row_height:34,padding:7}});
        window.StatsWidgetRenderer.fit(query("[data-formula-result]"));
        verified=JSON.stringify(incoming);query("[data-formula-status]").textContent=payload.unavailable_rows?`${payload.unavailable_rows} rows unavailable (invalid inputs or division by zero).`:payload.rows.length?"":"No cached rows. Pull data before checking the result.";
        if(!payload.rows.length)verified="";
      }catch(error){if(closed||turn!==revision)return;query("[data-formula-status]").textContent=error.message;query("[data-formula-result]").innerHTML="";}
      finally{if(!closed&&turn===revision)saveState();}
    }
    function schedule(){
      clearTimeout(timer);controller?.abort();verified="";const turn=++revision;saveState();
      query("[data-formula-result]").innerHTML="";query("[data-formula-status]").textContent=tokens.length?"Checking real data…":"";
      if(tokens.length)timer=setTimeout(()=>preview(turn),350);
    }
    const dispose=()=>{closed=true;revision++;clearTimeout(timer);controller?.abort();};
    host.innerHTML=`<div class="toolbar"><h3>New calculated Field</h3><button class="btn" data-formula-close>Close</button></div><p class="small">Each row · ${esc(report.name)}. Saved in Fields for reuse. Widget filters apply after adding it.</p><div class="formula-expression" data-formula-expression aria-label="Formula"></div><div class="row formula-operators">${["+","−","×","÷","(",")"].map(value=>`<button class="btn" data-formula-operator="${value}" aria-label="Insert ${value}">${value}</button>`).join("")}<button class="btn" data-formula-backspace aria-label="Remove last formula item">⌫</button><button class="btn" data-formula-clear>Clear</button></div><input type="search" data-formula-search placeholder="Find a number Field…" aria-label="Find a formula Field"><div class="formula-fields">${fields.map(field=>`<button class="btn" data-formula-field="${esc(field.id)}">${esc(field.label)}</button>`).join("")||'<p>No numeric Report Fields available.</p>'}</div><div class="row"><input data-formula-constant type="number" step="any" placeholder="Number" aria-label="Constant number"><button class="btn" data-formula-add-number>Add number</button></div><div class="formula-settings"><label>Name your result<input data-formula-name maxlength="120" placeholder="Name your calculation"></label><label>Display<select data-formula-type><option value="number">Number</option><option value="percent">Percentage</option></select></label><label>Decimals<input data-formula-decimals type="number" min="0" max="8" value="2"></label></div><div class="status" data-formula-status role="status"></div><div class="formula-result" data-formula-result></div><button class="btn primary" data-formula-save disabled>Create Field &amp; add</button>`;
    tokenMarkup();
    host.querySelectorAll("[data-formula-field]").forEach(button=>button.addEventListener("click",()=>{const field=fields.find(item=>item.id===button.dataset.formulaField);tokens.push({key:field.key,label:field.label});tokenMarkup();schedule();}));
    host.querySelectorAll("[data-formula-operator]").forEach(button=>button.addEventListener("click",()=>{tokens.push({value:button.dataset.formulaOperator});tokenMarkup();schedule();}));
    query("[data-formula-backspace]").onclick=()=>{tokens.pop();tokenMarkup();schedule();};
    query("[data-formula-clear]").onclick=()=>{tokens=[];tokenMarkup();schedule();};
    query("[data-formula-add-number]").onclick=()=>{const value=query("[data-formula-constant]").value;if(value.trim()&&Number.isFinite(Number(value))){tokens.push({value});query("[data-formula-constant]").value="";tokenMarkup();schedule();}};
    query("[data-formula-search]").oninput=event=>host.querySelectorAll("[data-formula-field]").forEach(button=>{button.hidden=!button.textContent.toLocaleLowerCase().includes(event.target.value.trim().toLocaleLowerCase());});
    ["name","type","decimals"].forEach(key=>query(`[data-formula-${key}]`).addEventListener(key==="type"?"change":"input",schedule));
    query("[data-formula-close]").onclick=()=>{if(saving)return;dispose();onClose?.();};
    query("[data-formula-save]").onclick=async()=>{
      if(saving||!verified||verified!==JSON.stringify(body())||!query("[data-formula-name]").value.trim())return;
      saving=true;host.querySelectorAll("input,select,button").forEach(node=>{node.disabled=true;});
      try{
        if(!createdKey){const result=await R.api(`/api/fields/${encodeURIComponent(report.id)}`,R.json("POST",body()));createdKey=result.field.key;}
        const catalog=(await R.api("/api/fields/catalog")).reports||[];const saved=catalog.find(item=>item.id===report.id)?.fields?.find(item=>item.key===createdKey);
        if(!saved)throw new Error("Field was created, but its catalog entry could not be loaded. Retry adding it.");
        dispose();R.emit("fields-changed");await onSaved?.(saved,catalog);
      }catch(error){if(!closed){query("[data-formula-status]").textContent=error.message;saving=false;if(createdKey){query("[data-formula-save]").textContent="Retry adding created Field";query("[data-formula-close]").disabled=false;}else host.querySelectorAll("input,select,button").forEach(node=>{node.disabled=false;});saveState();}}
    };
    schedule();return dispose;
  }
  window.StatsFieldFormulas=Object.freeze({open,expression});
})();
