/* Screens Settings owns templates, composition and live data preview. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const S={templates:[],screens:[],reports:[],values:[],editor:null,step:0,preview:null,message:"",groupChoices:[]};
  let loaded=false,timer=null;
  const report=id=>S.reports.find(x=>String(x.id)===String(id))||null;
  const screen=id=>S.screens.find(x=>String(x.id)===String(id))||null;
  const template=key=>S.templates.find(x=>String(x.key)===String(key))||null;
  const valuesForReport=id=>S.values.filter(x=>String(x.report_id)===String(id));
  const groupedTemplate=key=>["per_team","team_vs_team","all_teams"].includes(String(key||""));

  async function load(){
    const [templates,screens,reports,values]=await Promise.all([
      R.api("/api/screens/templates"),R.api("/api/screens"),R.api("/api/data/reports"),R.api("/api/display-values")
    ]);
    S.templates=templates.templates||[];S.screens=screens.screens||[];S.reports=reports.reports||[];S.values=values.display_values||[];loaded=true;render();
  }

  const blank=t=>({
    name:t?.name||"New Screen",template_key:t?.key||"",reports:[],
    group_by_display_value_id:"",group_values:[],tables:[],theme_mode:"inherited"
  });

  function normalizeTables(value){
    const selected=new Set(value.reports||[]);
    value.tables=(value.tables||[]).filter(t=>selected.has(t.report_id));
    for(const id of value.reports||[]){
      const values=valuesForReport(id);
      let table=value.tables.find(t=>t.report_id===id);
      if(!table){
        table={report_id:id,display_value_ids:values.slice(0,8).map(v=>v.id),sort_display_value_id:"",sort_direction:"desc",limit:100};
        value.tables.push(table);
      }else{
        if(!Array.isArray(table.display_value_ids))table.display_value_ids=values.slice(0,8).map(v=>v.id);
        if(typeof table.sort_display_value_id!=="string")table.sort_display_value_id="";
      }
    }
    if(value.group_by_display_value_id && !S.values.some(v=>v.id===value.group_by_display_value_id && selected.has(v.report_id))){
      value.group_by_display_value_id="";value.group_values=[];S.groupChoices=[];
    }
  }

  function templateCards(){
    return `<div class="card"><div class="toolbar"><div><h2>Screen Templates</h2><div class="small">Start with a competitive layout, then choose your Reports, Display Values and Theme.</div></div><button class="btn" data-action="new">+ Blank Screen</button></div><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(210px,1fr));margin-top:12px">${S.templates.map(t=>`<div class="subcard"><strong>${esc(t.name)}</strong><div class="small" style="margin-top:5px;min-height:38px">${esc(t.description||"")}</div><button class="btn primary" style="margin-top:10px" data-action="use-template" data-template="${esc(t.key)}">Use Template</button></div>`).join("")||'<div class="small">No Screen Templates available.</div>'}</div></div>`;
  }

  function listHtml(){
    return `${templateCards()}<div class="card"><div class="toolbar"><div><h2>My Screens</h2><div class="small">Saved Screens are fully editable.</div></div></div><div class="stack" style="margin-top:12px">${S.screens.map(x=>{const t=template(x.template_key);return `<div class="subcard"><div class="toolbar"><div><strong>${esc(x.name)}</strong><div class="small">${t?`${esc(t.name)} Template · `:""}${(x.reports||[]).length} Reports · ${x.theme_mode==="custom"?"Custom Theme":"Inherited Theme"}</div></div><div class="row"><button class="btn" data-action="edit" data-id="${esc(x.id)}">Edit</button><button class="btn" data-action="open-preview" data-id="${esc(x.id)}">Display Preview</button><button class="btn danger" data-action="delete" data-id="${esc(x.id)}">Delete</button></div></div></div>`;}).join("")||'<div class="small">No Screens yet.</div>'}</div></div>`;
  }

  function steps(){return `<div class="steps">${["1. Data","2. Display Values","3. Display","4. Theme"].map((n,i)=>`<button class="step ${i===S.step?"active":""}" data-step="${i}" type="button">${n}</button>`).join("")}</div>`;}

  function dataStep(v){
    const t=template(v.template_key);
    return `<div><h3>Choose Data</h3><div class="small">${t?`${esc(t.name)} is the layout. `:""}Choose the pulled Reports this Screen will use.</div><div class="stack" style="margin-top:10px">${S.reports.map(r=>`<label class="choice"><input type="checkbox" data-report="${esc(r.id)}" ${(v.reports||[]).includes(r.id)?"checked":""}><span><strong>${esc(r.name)}</strong><br><span class="small">${esc(r.status||"Not pulled yet")} · ${valuesForReport(r.id).length} Display Values</span></span></label>`).join("")||'<div class="small">Create and pull a Report in Data first.</div>'}</div></div>`;
  }

  function valueRows(v){
    return (v.reports||[]).map(reportId=>{
      const r=report(reportId),values=valuesForReport(reportId);
      return `<div class="subcard"><strong>${esc(r?.name||reportId)}</strong><div class="stack" style="margin-top:8px">${values.map(value=>`<div class="toolbar"><div><strong>${esc(value.name)}</strong><div class="small">Report field: ${esc(value.source_name||value.field_key)}</div></div><span class="chip">${esc(value.type||"text")}</span></div>`).join("")||'<div class="small">No Display Values yet. Pull this Report in Data first.</div>'}</div></div>`;
    }).join("");
  }

  function groupingHtml(v){
    const t=template(v.template_key);
    if(!groupedTemplate(v.template_key))return"";
    const available=(v.reports||[]).flatMap(valuesForReport);
    const max=v.template_key==="per_team"?1:v.template_key==="team_vs_team"?2:100;
    return `<div class="subcard" style="margin-top:12px"><h4>Competition Groups</h4><div class="small">${esc(t?.group_hint||"")}</div><div style="margin-top:10px"><label>Group By</label><select data-group-by><option value="">Choose Display Value…</option>${available.map(value=>`<option value="${esc(value.id)}" ${value.id===v.group_by_display_value_id?"selected":""}>${esc(value.report_name)} · ${esc(value.name)}</option>`).join("")}</select></div>${v.group_by_display_value_id?`<div style="margin-top:12px"><label>${v.template_key==="all_teams"?"Included Values (leave all unchecked for every value)":`Choose ${max===1?"one value":"up to two values"}`}</label><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-top:7px">${S.groupChoices.map(choice=>`<label class="choice"><input type="checkbox" data-group-value value="${esc(choice)}" ${(v.group_values||[]).includes(choice)?"checked":""}><span>${esc(choice)}</span></label>`).join("")||'<div class="small">No values found in pulled data.</div>'}</div></div>`:""}</div>`;
  }

  function displayValuesStep(v){
    return `<div><div class="toolbar"><div><h3>Display Values</h3><div class="small">Every Report field is already a Display Value. Rename it once and every Screen uses the clean name.</div></div><button class="btn" data-action="manage-display-values">Manage Display Values</button></div><div class="stack" style="margin-top:10px">${valueRows(v)||'<div class="small">Choose Reports first.</div>'}</div>${groupingHtml(v)}</div>`;
  }

  function tableHtml(t){
    const r=report(t.report_id),values=valuesForReport(t.report_id);
    return `<div class="subcard"><h4>${esc(r?.name||t.report_id)}</h4><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">${values.map(value=>`<label class="choice"><input type="checkbox" data-column="${esc(t.report_id)}" value="${esc(value.id)}" ${(t.display_value_ids||[]).includes(value.id)?"checked":""}><span>${esc(value.name)}</span></label>`).join("")||'<div class="small">No Display Values available.</div>'}</div><div class="grid" style="margin-top:10px"><div><label>Rank / Sort By</label><select data-sort="${esc(t.report_id)}"><option value="">Source order</option>${values.map(value=>`<option value="${esc(value.id)}" ${t.sort_display_value_id===value.id?"selected":""}>${esc(value.name)}</option>`).join("")}</select></div><div><label>Direction</label><select data-direction="${esc(t.report_id)}"><option value="desc" ${t.sort_direction!=="asc"?"selected":""}>Highest first</option><option value="asc" ${t.sort_direction==="asc"?"selected":""}>Lowest first</option></select></div><div><label>Rows</label><input type="number" min="1" max="500" data-limit="${esc(t.report_id)}" value="${Number(t.limit||100)}"></div></div></div>`;
  }

  function displayStep(v){const t=template(v.template_key);normalizeTables(v);return `<div><div class="toolbar"><div><h3>Create Display</h3><div class="small">${t?`${esc(t.name)} layout · `:""}Choose Display Values, ranking and row count. Live Preview uses the real pulled data.</div></div><button class="btn" data-action="refresh-preview">Refresh Preview</button></div><div class="stack" style="margin-top:10px">${(v.tables||[]).map(tableHtml).join("")||'<div class="small">Choose Reports first.</div>'}</div></div>`;}

  function themeStep(v){
    const custom=v.theme_mode==="custom";
    return `<div><h3>Theme</h3><div class="small">Inherited uses the Stats base design. Custom gives this Screen its own visual design and assets.</div><div class="stack" style="margin-top:10px"><label class="choice"><input type="radio" name="screenTheme" data-theme="inherited" ${!custom?"checked":""}><span><strong>Inherited</strong></span></label><label class="choice"><input type="radio" name="screenTheme" data-theme="custom" ${custom?"checked":""}><span><strong>Custom</strong></span></label></div>${custom?`<div class="subcard" style="margin-top:12px"><strong>Custom Theme</strong><div class="small" style="margin-top:4px">Colors, backgrounds, row art, hero art and other visual assets are owned by Theme.</div><div class="row" style="margin-top:10px">${v.id?`<button class="btn" data-action="edit-theme">Edit Theme & Assets</button><button class="btn" data-action="open-preview" data-id="${esc(v.id)}">Display Preview</button>`:'<button class="btn primary" data-action="save-theme">Save Screen & Edit Theme</button>'}</div></div>`:""}</div>`;
  }

  function previewHtml(){
    const p=S.preview;if(!p)return'<div class="preview"><strong>Live Preview</strong><div class="small" style="margin-top:6px">Choose data to preview the real Screen output.</div></div>';
    if(p.error)return`<div class="preview"><strong>Live Preview</strong><div class="danger-text small">${esc(p.error)}</div></div>`;
    return `<div class="preview"><strong>${esc(p.screen_name||"Preview")}</strong><div class="small">${esc(template(p.template_key)?.name||"Blank Screen")}${p.group_by?` · Grouped by ${esc(p.group_by.name)}`:""}</div>${(p.sections||[]).map(s=>`<div class="preview-section"><h4>${esc(s.report_name)} · ${Number(s.total_rows||0)} rows</h4><div class="data-table"><table><thead><tr>${(s.fields||[]).map(f=>`<th>${esc(f.label||f.key)}</th>`).join("")}</tr></thead><tbody>${(s.rows||[]).slice(0,20).map(row=>`<tr>${(s.fields||[]).map(f=>`<td>${esc(row[f.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(1,(s.fields||[]).length)}">No rows.</td></tr>`}</tbody></table></div></div>`).join("")}</div>`;
  }

  function editorHtml(){
    if(!S.editor)return"";const body=[dataStep,displayValuesStep,displayStep,themeStep][S.step](S.editor),t=template(S.editor.template_key);
    return `<div class="card"><div class="toolbar"><div><h2>${S.editor.id?"Edit":"Create"} Screen</h2><div class="small">${t?`Template: ${esc(t.name)}. `:"Blank Screen. "}The saved Screen is fully editable.</div></div><button class="btn" data-action="close">Close</button></div><div style="margin-top:10px"><label>Screen Name</label><input data-name value="${esc(S.editor.name||"")}"></div>${steps()}<div class="screen-layout"><div>${body}<div class="row" style="justify-content:space-between;margin-top:14px"><button class="btn" data-action="back" ${S.step===0?"disabled":""}>Back</button><div class="row">${S.step<3?'<button class="btn primary" data-action="next">Next</button>':'<button class="btn primary" data-action="save">Save Screen</button>'}</div></div><div class="status">${esc(S.message)}</div></div>${previewHtml()}</div></div>`;
  }

  function render(){const host=$("settingsScreensHost");if(host){host.innerHTML=listHtml()+editorHtml();bind();}}

  function sync(){
    const host=$("settingsScreensHost");if(!host||!S.editor)return;
    const name=host.querySelector("[data-name]");if(name)S.editor.name=name.value;
    const reports=host.querySelectorAll("[data-report]");if(reports.length){S.editor.reports=[...reports].filter(i=>i.checked).map(i=>i.dataset.report);normalizeTables(S.editor);}
    const groupBy=host.querySelector("[data-group-by]");if(groupBy)S.editor.group_by_display_value_id=groupBy.value;
    const groupInputs=host.querySelectorAll("[data-group-value]");
    if(groupInputs.length){const selected=[...groupInputs].filter(i=>i.checked).map(i=>i.value),max=S.editor.template_key==="per_team"?1:S.editor.template_key==="team_vs_team"?2:100;S.editor.group_values=selected.slice(0,max);}
    host.querySelectorAll("[data-sort]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.sort);if(t)t.sort_display_value_id=i.value;});
    host.querySelectorAll("[data-direction]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.direction);if(t)t.sort_direction=i.value;});
    host.querySelectorAll("[data-limit]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.limit);if(t)t.limit=Number(i.value||100);});
    const columns=new Map();host.querySelectorAll("[data-column]").forEach(i=>{if(!columns.has(i.dataset.column))columns.set(i.dataset.column,[]);if(i.checked)columns.get(i.dataset.column).push(i.value);});
    for(const [id,list] of columns){const t=S.editor.tables.find(x=>x.report_id===id);if(t)t.display_value_ids=list;}
    const theme=host.querySelector("[data-theme]:checked");if(theme)S.editor.theme_mode=theme.dataset.theme;
  }

  async function loadGroupChoices(){
    S.groupChoices=[];const id=S.editor?.group_by_display_value_id;if(!id)return;
    try{const d=await R.api(`/api/display-values/${encodeURIComponent(id)}/values`);S.groupChoices=d.values||[];}catch(error){S.message=error.message;}
  }

  function schedule(){clearTimeout(timer);timer=setTimeout(preview,250);}
  async function preview(){if(!S.editor)return;sync();if(!(S.editor.reports||[]).length){S.preview=null;render();return;}try{const d=await R.api("/api/screens/preview",R.json("POST",S.editor));S.preview=d.payload;S.message="";}catch(e){S.preview={error:e.message};}render();}
  async function open(id=null,t=null){if(!loaded)await load();S.editor=id?JSON.parse(JSON.stringify(screen(id))):blank(t);S.step=0;S.preview=null;S.message="";normalizeTables(S.editor);await loadGroupChoices();render();schedule();}

  async function save(openTheme=false){
    sync();S.message="Saving Screen…";render();
    try{const url=S.editor.id?`/api/screens/${encodeURIComponent(S.editor.id)}`:"/api/screens",method=S.editor.id?"PUT":"POST",d=await R.api(url,R.json(method,S.editor)),saved=d.screen;S.message="Screen saved.";await load();R.emit("screens-changed");if(openTheme){S.editor=JSON.parse(JSON.stringify(saved));S.step=3;render();await window.StatsThemeManager.open(saved.id);}else{S.editor=null;S.preview=null;render();}}catch(e){S.message=e.message;render();}
  }

  function bind(){
    const host=$("settingsScreensHost");if(!host)return;
    host.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",async()=>{
      const a=b.dataset.action,id=b.dataset.id;sync();
      if(a==="new")return open();if(a==="use-template")return open(null,template(b.dataset.template));if(a==="edit")return open(id);if(a==="close"){S.editor=null;S.preview=null;render();return;}if(a==="back"){S.step=Math.max(0,S.step-1);render();schedule();return;}if(a==="next"){S.step=Math.min(3,S.step+1);render();schedule();return;}if(a==="save")return save(false);if(a==="save-theme")return save(true);if(a==="refresh-preview")return preview();if(a==="manage-display-values"){window.StatsDisplayValueManager?.open();return;}if(a==="open-preview"){window.open(`/?screen_id=${encodeURIComponent(id||S.editor?.id||"")}`,"_blank");return;}if(a==="edit-theme")return window.StatsThemeManager.open(S.editor.id);
      if(a==="delete"){if(!confirm("Delete this Screen?"))return;try{await R.api(`/api/screens/${encodeURIComponent(id)}`,{method:"DELETE"});S.message="Screen deleted.";await load();R.emit("screens-changed");}catch(e){S.message=e.message;render();}}
    }));
    host.querySelectorAll("[data-step]").forEach(b=>b.addEventListener("click",()=>{sync();S.step=Number(b.dataset.step);render();schedule();}));
    host.querySelectorAll("[data-group-by]").forEach(select=>select.addEventListener("change",async()=>{sync();S.editor.group_by_display_value_id=select.value;S.editor.group_values=[];await loadGroupChoices();render();schedule();}));
    host.querySelectorAll("input,select").forEach(i=>{if(i.hasAttribute("data-group-by"))return;i.addEventListener(i.hasAttribute("data-name")?"input":"change",()=>{sync();render();schedule();});});
  }

  R.on("section",id=>{if(id==="settingsScreens"&&!loaded)load().catch(e=>{S.message=e.message;render();});});
  R.on("unlocked",()=>{loaded=false;});R.on("data-changed",()=>{loaded=false;});
  R.on("display-values-changed",values=>{S.values=values||[];if(S.editor){normalizeTables(S.editor);render();schedule();}});
})();
