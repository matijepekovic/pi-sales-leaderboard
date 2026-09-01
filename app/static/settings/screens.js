/* Screens Settings owns Screen templates, composition and live data preview. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const S={templates:[],screens:[],reports:[],filters:[],editor:null,step:0,preview:null,message:""};
  let loaded=false,timer=null;
  const report=id=>S.reports.find(x=>String(x.id)===String(id))||null;
  const screen=id=>S.screens.find(x=>String(x.id)===String(id))||null;
  const template=key=>S.templates.find(x=>String(x.key)===String(key))||null;

  async function load(){
    const [templates,screens,reports,filters]=await Promise.all([R.api("/api/screens/templates"),R.api("/api/screens"),R.api("/api/data/reports"),R.api("/api/filters")]);
    S.templates=templates.templates||[];S.screens=screens.screens||[];S.reports=reports.reports||[];S.filters=filters.filters||[];loaded=true;render();
  }
  const blank=t=>({name:t?.name||"New Screen",template_key:t?.key||"",reports:[],filter_ids:[],tables:[],theme_mode:"inherited"});

  function normalizeTables(value){
    const selected=new Set(value.reports||[]);value.tables=(value.tables||[]).filter(t=>selected.has(t.report_id));
    for(const id of value.reports||[]){if(value.tables.some(t=>t.report_id===id))continue;const fields=report(id)?.fields||[];value.tables.push({report_id:id,columns:fields.slice(0,8).map(f=>f.key),sort_field:"",sort_direction:"desc",limit:100});}
  }

  function templateCards(){
    return `<div class="card"><div class="toolbar"><div><h2>Screen Templates</h2><div class="small">Start with one of the original Stats competitive screens, then choose your own Data, Filters, columns and Theme.</div></div><button class="btn" data-action="new">+ Blank Screen</button></div><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(210px,1fr));margin-top:12px">${S.templates.map(t=>`<div class="subcard"><strong>${esc(t.name)}</strong><div class="small" style="margin-top:5px;min-height:38px">${esc(t.description||"")}</div><button class="btn primary" style="margin-top:10px" data-action="use-template" data-template="${esc(t.key)}">Use Template</button></div>`).join("")||'<div class="small">No Screen Templates available.</div>'}</div></div>`;
  }

  function listHtml(){
    return `${templateCards()}<div class="card"><div class="toolbar"><div><h2>My Screens</h2><div class="small">Saved Screens are normal editable Screens, whether they started blank or from a template.</div></div></div><div class="stack" style="margin-top:12px">${S.screens.map(x=>{const t=template(x.template_key);return `<div class="subcard"><div class="toolbar"><div><strong>${esc(x.name)}</strong><div class="small">${t?`${esc(t.name)} Template · `:""}${(x.reports||[]).length} Reports · ${(x.filter_ids||[]).length} Filters · ${x.theme_mode==="custom"?"Custom Theme":"Inherited Theme"}</div></div><div class="row"><button class="btn" data-action="edit" data-id="${esc(x.id)}">Edit</button><button class="btn" data-action="open-preview" data-id="${esc(x.id)}">Display Preview</button><button class="btn danger" data-action="delete" data-id="${esc(x.id)}">Delete</button></div></div></div>`;}).join("")||'<div class="small">No Screens yet.</div>'}</div></div>`;
  }

  function steps(){return `<div class="steps">${["1. Data","2. Filters","3. Display","4. Theme"].map((n,i)=>`<button class="step ${i===S.step?"active":""}" data-step="${i}" type="button">${n}</button>`).join("")}</div>`;}
  function dataStep(v){const t=template(v.template_key);return `<div><h3>Choose Data</h3><div class="small">${t?`${esc(t.name)} is the layout. `:""}Choose the pulled Reports this Screen will use.</div><div class="stack" style="margin-top:10px">${S.reports.map(r=>`<label class="choice"><input type="checkbox" data-report="${esc(r.id)}" ${(v.reports||[]).includes(r.id)?"checked":""}><span><strong>${esc(r.name)}</strong><br><span class="small">${esc(r.status||"Not pulled yet")} · ${(r.fields||[]).length} fields</span></span></label>`).join("")||'<div class="small">Create and pull a Report in Data first.</div>'}</div></div>`;}
  function filtersStep(v){const t=template(v.template_key);return `<div><div class="toolbar"><div><h3>Assign Filters</h3><div class="small">${esc(t?.filter_hint||"Select the reusable Filters this Screen applies.")}</div></div><button class="btn" data-action="create-filter">+ Create Filter</button></div><div class="stack" style="margin-top:10px">${S.filters.map(f=>`<label class="choice"><input type="checkbox" data-filter="${esc(f.id)}" ${(v.filter_ids||[]).includes(f.id)?"checked":""}><span><strong>${esc(f.name)}</strong>${(f.rules||[]).map(rule=>`<br><span class="small">${esc(report(rule.report_id)?.name||rule.report_id)} · ${esc(rule.field)} ${esc(rule.operator)} ${esc(rule.value)}</span>`).join("")}</span></label>`).join("")||'<div class="small">No Filters yet. Create one here.</div>'}</div></div>`;}

  function table(t){
    const r=report(t.report_id),fields=r?.fields||[];
    return `<div class="subcard"><h4>${esc(r?.name||t.report_id)}</h4><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">${fields.map(f=>`<label class="choice"><input type="checkbox" data-column="${esc(t.report_id)}" value="${esc(f.key)}" ${(t.columns||[]).includes(f.key)?"checked":""}><span>${esc(f.label||f.key)}</span></label>`).join("")}</div><div class="grid" style="margin-top:10px"><div><label>Rank / Sort By</label><select data-sort="${esc(t.report_id)}"><option value="">Source order</option>${fields.map(f=>`<option value="${esc(f.key)}" ${t.sort_field===f.key?"selected":""}>${esc(f.label||f.key)}</option>`).join("")}</select></div><div><label>Direction</label><select data-direction="${esc(t.report_id)}"><option value="desc" ${t.sort_direction!=="asc"?"selected":""}>Highest first</option><option value="asc" ${t.sort_direction==="asc"?"selected":""}>Lowest first</option></select></div><div><label>Rows</label><input type="number" min="1" max="500" data-limit="${esc(t.report_id)}" value="${Number(t.limit||100)}"></div></div></div>`;
  }
  function displayStep(v){const t=template(v.template_key);normalizeTables(v);return `<div><div class="toolbar"><div><h3>Create Display</h3><div class="small">${t?`${esc(t.name)} layout · `:""}Choose columns, ranking and row count. Live Preview uses the real pulled data and selected Filters.</div></div><button class="btn" data-action="refresh-preview">Refresh Preview</button></div><div class="stack" style="margin-top:10px">${(v.tables||[]).map(table).join("")||'<div class="small">Choose Reports first.</div>'}</div></div>`;}

  function themeStep(v){
    const custom=v.theme_mode==="custom";
    return `<div><h3>Theme</h3><div class="small">Inherited uses the Stats base design. Custom gives this Screen its own visual design and assets.</div><div class="stack" style="margin-top:10px"><label class="choice"><input type="radio" name="screenTheme" data-theme="inherited" ${!custom?"checked":""}><span><strong>Inherited</strong></span></label><label class="choice"><input type="radio" name="screenTheme" data-theme="custom" ${custom?"checked":""}><span><strong>Custom</strong></span></label></div>${custom?`<div class="subcard" style="margin-top:12px"><strong>Custom Theme</strong><div class="small" style="margin-top:4px">Colors, backgrounds, row art, hero art and other visual assets are owned by Theme.</div><div class="row" style="margin-top:10px">${v.id?`<button class="btn" data-action="edit-theme">Edit Theme & Assets</button><button class="btn" data-action="open-preview" data-id="${esc(v.id)}">Display Preview</button>`:'<button class="btn primary" data-action="save-theme">Save Screen & Edit Theme</button>'}</div></div>`:""}</div>`;
  }

  function previewHtml(){
    const p=S.preview;if(!p)return'<div class="preview"><strong>Live Preview</strong><div class="small" style="margin-top:6px">Choose data to preview the real Screen output.</div></div>';
    if(p.error)return`<div class="preview"><strong>Live Preview</strong><div class="danger-text small">${esc(p.error)}</div></div>`;
    return `<div class="preview"><strong>${esc(p.screen_name||"Preview")}</strong><div class="small">${esc(template(p.template_key)?.name||"Blank Screen")}${(p.display_filters||[]).length?` · ${(p.display_filters||[]).map(f=>esc(f.name)).join(" · ")}`:""}</div>${(p.sections||[]).map(s=>`<div class="preview-section"><h4>${esc(s.report_name)} · ${Number(s.total_rows||0)} matching rows</h4><div class="data-table"><table><thead><tr>${(s.fields||[]).map(f=>`<th>${esc(f.label||f.key)}</th>`).join("")}</tr></thead><tbody>${(s.rows||[]).slice(0,20).map(row=>`<tr>${(s.fields||[]).map(f=>`<td>${esc(row[f.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(1,(s.fields||[]).length)}">No matching rows.</td></tr>`}</tbody></table></div></div>`).join("")}</div>`;
  }

  function editorHtml(){
    if(!S.editor)return"";const body=[dataStep,filtersStep,displayStep,themeStep][S.step](S.editor),t=template(S.editor.template_key);
    return `<div class="card"><div class="toolbar"><div><h2>${S.editor.id?"Edit":"Create"} Screen</h2><div class="small">${t?`Template: ${esc(t.name)}. `:"Blank Screen. "}The saved Screen is fully editable.</div></div><button class="btn" data-action="close">Close</button></div><div style="margin-top:10px"><label>Screen Name</label><input data-name value="${esc(S.editor.name||"")}"></div>${steps()}<div class="screen-layout"><div>${body}<div class="row" style="justify-content:space-between;margin-top:14px"><button class="btn" data-action="back" ${S.step===0?"disabled":""}>Back</button><div class="row">${S.step<3?'<button class="btn primary" data-action="next">Next</button>':'<button class="btn primary" data-action="save">Save Screen</button>'}</div></div><div class="status">${esc(S.message)}</div></div>${previewHtml()}</div></div>`;
  }
  function render(){const host=$("settingsScreensHost");if(host){host.innerHTML=listHtml()+editorHtml();bind();}}

  function sync(){
    const host=$("settingsScreensHost");if(!host||!S.editor)return;const name=host.querySelector("[data-name]");if(name)S.editor.name=name.value;
    const reports=host.querySelectorAll("[data-report]");if(reports.length){S.editor.reports=[...reports].filter(i=>i.checked).map(i=>i.dataset.report);normalizeTables(S.editor);}
    const filters=host.querySelectorAll("[data-filter]");if(filters.length)S.editor.filter_ids=[...filters].filter(i=>i.checked).map(i=>i.dataset.filter);
    host.querySelectorAll("[data-sort]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.sort);if(t)t.sort_field=i.value;});
    host.querySelectorAll("[data-direction]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.direction);if(t)t.sort_direction=i.value;});
    host.querySelectorAll("[data-limit]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.limit);if(t)t.limit=Number(i.value||100);});
    const columns=new Map();host.querySelectorAll("[data-column]").forEach(i=>{if(!columns.has(i.dataset.column))columns.set(i.dataset.column,[]);if(i.checked)columns.get(i.dataset.column).push(i.value);});for(const [id,list] of columns){const t=S.editor.tables.find(x=>x.report_id===id);if(t)t.columns=list;}
    const theme=host.querySelector("[data-theme]:checked");if(theme)S.editor.theme_mode=theme.dataset.theme;
  }

  function schedule(){clearTimeout(timer);timer=setTimeout(preview,250);}
  async function preview(){if(!S.editor)return;sync();if(!(S.editor.reports||[]).length){S.preview=null;render();return;}try{const d=await R.api("/api/screens/preview",R.json("POST",S.editor));S.preview=d.payload;S.message="";}catch(e){S.preview={error:e.message};}render();}
  async function open(id=null,t=null){if(!loaded)await load();S.editor=id?JSON.parse(JSON.stringify(screen(id))):blank(t);S.step=0;S.preview=null;S.message="";normalizeTables(S.editor);render();schedule();}

  async function save(openTheme=false){
    sync();S.message="Saving Screen…";render();
    try{const url=S.editor.id?`/api/screens/${encodeURIComponent(S.editor.id)}`:"/api/screens",method=S.editor.id?"PUT":"POST";const d=await R.api(url,R.json(method,S.editor));const saved=d.screen;S.message="Screen saved.";await load();R.emit("screens-changed");if(openTheme){S.editor=JSON.parse(JSON.stringify(saved));S.step=3;render();await window.StatsThemeManager.open(saved.id);}else{S.editor=null;S.preview=null;render();}}catch(e){S.message=e.message;render();}
  }

  function bind(){
    const host=$("settingsScreensHost");if(!host)return;
    host.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",async()=>{
      const a=b.dataset.action,id=b.dataset.id;sync();
      if(a==="new")return open();if(a==="use-template")return open(null,template(b.dataset.template));if(a==="edit")return open(id);if(a==="close"){S.editor=null;S.preview=null;render();return;}if(a==="back"){S.step=Math.max(0,S.step-1);render();schedule();return;}if(a==="next"){S.step=Math.min(3,S.step+1);render();schedule();return;}if(a==="save")return save(false);if(a==="save-theme")return save(true);if(a==="refresh-preview")return preview();if(a==="open-preview"){window.open(`/?screen_id=${encodeURIComponent(id||S.editor?.id||"")}`,"_blank");return;}if(a==="edit-theme")return window.StatsThemeManager.open(S.editor.id);
      if(a==="create-filter")return window.StatsFilterManager.openCreate(async created=>{S.editor.filter_ids=[...(S.editor.filter_ids||[]),created.id].filter((v,i,a)=>a.indexOf(v)===i);S.filters=(await R.api("/api/filters")).filters||[];render();schedule();});
      if(a==="delete"){if(!confirm("Delete this Screen?"))return;try{await R.api(`/api/screens/${encodeURIComponent(id)}`,{method:"DELETE"});S.message="Screen deleted.";await load();R.emit("screens-changed");}catch(e){S.message=e.message;render();}}
    }));
    host.querySelectorAll("[data-step]").forEach(b=>b.addEventListener("click",()=>{sync();S.step=Number(b.dataset.step);render();schedule();}));
    host.querySelectorAll("input,select").forEach(i=>i.addEventListener(i.dataset.name!==undefined?"input":"change",()=>{sync();render();schedule();}));
  }

  R.on("section",id=>{if(id==="settingsScreens"&&!loaded)load().catch(e=>{S.message=e.message;render();});});
  R.on("unlocked",()=>{loaded=false;});R.on("data-changed",()=>{loaded=false;});R.on("filters-changed",f=>{S.filters=f||[];if(S.editor)render();});
})();
