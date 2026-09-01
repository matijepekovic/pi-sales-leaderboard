/* Screens Settings owns Screen composition and live data preview. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const S={screens:[],reports:[],editor:null,step:0,preview:null,message:""};
  let loaded=false,timer=null;
  const report=id=>S.reports.find(x=>String(x.id)===String(id))||null;
  const screen=id=>S.screens.find(x=>String(x.id)===String(id))||null;

  async function load(){
    const [screens,reports]=await Promise.all([R.api("/api/screens"),R.api("/api/data/reports")]);
    S.screens=screens.screens||[];S.reports=reports.reports||[];loaded=true;render();
  }
  const blank=()=>({name:"New Screen",reports:[],filter_ids:[],tables:[],theme_mode:"inherited"});

  function normalizeTables(value){
    const selected=new Set(value.reports||[]);value.tables=(value.tables||[]).filter(t=>selected.has(t.report_id));
    for(const id of value.reports||[]){
      if(value.tables.some(t=>t.report_id===id))continue;
      const fields=report(id)?.fields||[];
      value.tables.push({report_id:id,columns:fields.slice(0,8).map(f=>f.key),sort_field:"",sort_direction:"desc",limit:100});
    }
  }

  function listHtml(){
    return `<div class="card"><div class="toolbar"><div><h2>Screens</h2><div class="small">Screens choose Reports, Display Values, presentation and Theme. Data Filters stay with the Report.</div></div><button class="btn primary" data-action="new">+ Screen</button></div><div class="stack" style="margin-top:12px">${S.screens.map(x=>`<div class="subcard"><div class="toolbar"><div><strong>${esc(x.name)}</strong><div class="small">${(x.reports||[]).length} Report${(x.reports||[]).length===1?"":"s"} · ${(x.tables||[]).reduce((n,t)=>n+(t.columns||[]).length,0)} Display Values · ${x.theme_mode==="custom"?"Custom Theme":"Inherited Theme"}</div></div><div class="row"><button class="btn" data-action="edit" data-id="${esc(x.id)}">Edit</button><button class="btn" data-action="open-preview" data-id="${esc(x.id)}">Display Preview</button><button class="btn danger" data-action="delete" data-id="${esc(x.id)}">Delete</button></div></div></div>`).join("")||'<div class="small">No Screens yet.</div>'}</div></div>`;
  }

  function steps(){return `<div class="steps">${["1. Data","2. Display Values","3. Theme"].map((n,i)=>`<button class="step ${i===S.step?"active":""}" data-step="${i}" type="button">${n}</button>`).join("")}</div>`;}
  function dataStep(v){return `<div><h3>Choose Data</h3><div class="small">Choose the pulled Reports this Screen will use.</div><div class="stack" style="margin-top:10px">${S.reports.map(r=>`<label class="choice"><input type="checkbox" data-report="${esc(r.id)}" ${(v.reports||[]).includes(r.id)?"checked":""}><span><strong>${esc(r.name)}</strong><br><span class="small">${esc(r.status||"Not pulled yet")} · ${(r.fields||[]).length} Display Values</span></span></label>`).join("")||'<div class="small">Create and pull a Report in Data first.</div>'}</div></div>`;}

  function table(t){
    const r=report(t.report_id),fields=r?.fields||[];
    return `<div class="subcard"><h4>${esc(r?.name||t.report_id)}</h4><div class="small" style="margin-bottom:8px">Choose the Display Values this Screen should show.</div><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">${fields.map(f=>`<label class="choice"><input type="checkbox" data-column="${esc(t.report_id)}" value="${esc(f.key)}" ${(t.columns||[]).includes(f.key)?"checked":""}><span><strong>${esc(f.label||f.key)}</strong><br><span class="small">${esc(f.key)}</span></span></label>`).join("")||'<div class="small">No Display Values yet. Refresh the Report in Data.</div>'}</div><div class="grid" style="margin-top:10px"><div><label>Rank / Sort By</label><select data-sort="${esc(t.report_id)}"><option value="">Source order</option>${fields.map(f=>`<option value="${esc(f.key)}" ${t.sort_field===f.key?"selected":""}>${esc(f.label||f.key)}</option>`).join("")}</select></div><div><label>Direction</label><select data-direction="${esc(t.report_id)}"><option value="desc" ${t.sort_direction!=="asc"?"selected":""}>Highest first</option><option value="asc" ${t.sort_direction==="asc"?"selected":""}>Lowest first</option></select></div><div><label>Rows</label><input type="number" min="1" max="500" data-limit="${esc(t.report_id)}" value="${Number(t.limit||100)}"></div></div></div>`;
  }
  function displayValuesStep(v){normalizeTables(v);return `<div><div class="toolbar"><div><h3>Display Values</h3><div class="small">Every option below comes directly from a field in the selected Report.</div></div><button class="btn" data-action="refresh-preview">Refresh Preview</button></div><div class="stack" style="margin-top:10px">${(v.tables||[]).map(table).join("")||'<div class="small">Choose Reports first.</div>'}</div></div>`;}

  function themeStep(v){
    const custom=v.theme_mode==="custom";
    return `<div><h3>Theme</h3><div class="small">Inherited uses the Stats base design. Custom gives this Screen its own visual design and assets.</div><div class="stack" style="margin-top:10px"><label class="choice"><input type="radio" name="screenTheme" data-theme="inherited" ${!custom?"checked":""}><span><strong>Inherited</strong></span></label><label class="choice"><input type="radio" name="screenTheme" data-theme="custom" ${custom?"checked":""}><span><strong>Custom</strong></span></label></div>${custom?`<div class="subcard" style="margin-top:12px"><strong>Custom Theme</strong><div class="small" style="margin-top:4px">Colors, backgrounds, row art, hero art and other visual assets are owned by Theme.</div><div class="row" style="margin-top:10px">${v.id?`<button class="btn" data-action="edit-theme">Edit Theme & Assets</button><button class="btn" data-action="open-preview" data-id="${esc(v.id)}">Display Preview</button>`:'<button class="btn primary" data-action="save-theme">Save Screen & Edit Theme</button>'}</div></div>`:""}</div>`;
  }

  function previewHtml(){
    const p=S.preview;if(!p)return'<div class="preview"><strong>Live Preview</strong><div class="small" style="margin-top:6px">Choose data to preview the real Screen output.</div></div>';
    if(p.error)return`<div class="preview"><strong>Live Preview</strong><div class="danger-text small">${esc(p.error)}</div></div>`;
    return `<div class="preview"><strong>${esc(p.screen_name||"Preview")}</strong>${(p.sections||[]).map(s=>`<div class="preview-section"><h4>${esc(s.report_name)} · ${Number(s.total_rows||0)} rows</h4><div class="data-table"><table><thead><tr>${(s.fields||[]).map(f=>`<th>${esc(f.label||f.key)}</th>`).join("")}</tr></thead><tbody>${(s.rows||[]).slice(0,20).map(row=>`<tr>${(s.fields||[]).map(f=>`<td>${esc(row[f.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${Math.max(1,(s.fields||[]).length)}">No rows.</td></tr>`}</tbody></table></div></div>`).join("")}</div>`;
  }

  function editorHtml(){
    if(!S.editor)return"";const body=[dataStep,displayValuesStep,themeStep][S.step](S.editor);
    return `<div class="card"><div class="toolbar"><div><h2>${S.editor.id?"Edit":"Create"} Screen</h2><div class="small">A Screen uses pulled Reports and their Display Values. It does not create another Filter layer.</div></div><button class="btn" data-action="close">Close</button></div><div style="margin-top:10px"><label>Screen Name</label><input data-name value="${esc(S.editor.name||"")}"></div>${steps()}<div class="screen-layout"><div>${body}<div class="row" style="justify-content:space-between;margin-top:14px"><button class="btn" data-action="back" ${S.step===0?"disabled":""}>Back</button><div class="row">${S.step<2?'<button class="btn primary" data-action="next">Next</button>':'<button class="btn primary" data-action="save">Save Screen</button>'}</div></div><div class="status">${esc(S.message)}</div></div>${previewHtml()}</div></div>`;
  }
  function render(){const host=$("settingsScreensHost");if(host){host.innerHTML=listHtml()+editorHtml();bind();}}

  function sync(){
    const host=$("settingsScreensHost");if(!host||!S.editor)return;const name=host.querySelector("[data-name]");if(name)S.editor.name=name.value;S.editor.filter_ids=[];
    const reports=host.querySelectorAll("[data-report]");if(reports.length){S.editor.reports=[...reports].filter(i=>i.checked).map(i=>i.dataset.report);normalizeTables(S.editor);}
    host.querySelectorAll("[data-sort]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.sort);if(t)t.sort_field=i.value;});
    host.querySelectorAll("[data-direction]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.direction);if(t)t.sort_direction=i.value;});
    host.querySelectorAll("[data-limit]").forEach(i=>{const t=S.editor.tables.find(x=>x.report_id===i.dataset.limit);if(t)t.limit=Number(i.value||100);});
    const columns=new Map();host.querySelectorAll("[data-column]").forEach(i=>{if(!columns.has(i.dataset.column))columns.set(i.dataset.column,[]);if(i.checked)columns.get(i.dataset.column).push(i.value);});for(const [id,list] of columns){const t=S.editor.tables.find(x=>x.report_id===id);if(t)t.columns=list;}
    const theme=host.querySelector("[data-theme]:checked");if(theme)S.editor.theme_mode=theme.dataset.theme;
  }

  function schedule(){clearTimeout(timer);timer=setTimeout(preview,250);}
  async function preview(){if(!S.editor)return;sync();if(!(S.editor.reports||[]).length){S.preview=null;render();return;}try{const d=await R.api("/api/screens/preview",R.json("POST",S.editor));S.preview=d.payload;S.message="";}catch(e){S.preview={error:e.message};}render();}
  async function open(id=null){if(!loaded)await load();S.editor=id?JSON.parse(JSON.stringify(screen(id))):blank();S.editor.filter_ids=[];S.step=0;S.preview=null;S.message="";normalizeTables(S.editor);render();schedule();}

  async function save(openTheme=false){
    sync();S.editor.filter_ids=[];S.message="Saving Screen…";render();
    try{const url=S.editor.id?`/api/screens/${encodeURIComponent(S.editor.id)}`:"/api/screens",method=S.editor.id?"PUT":"POST";const d=await R.api(url,R.json(method,S.editor));const saved=d.screen;S.message="Screen saved.";await load();R.emit("screens-changed");if(openTheme){S.editor=JSON.parse(JSON.stringify(saved));S.editor.filter_ids=[];S.step=2;render();await window.StatsThemeManager.open(saved.id);}else{S.editor=null;S.preview=null;render();}}catch(e){S.message=e.message;render();}
  }

  function bind(){
    const host=$("settingsScreensHost");if(!host)return;
    host.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",async()=>{
      const a=b.dataset.action,id=b.dataset.id;sync();
      if(a==="new")return open();if(a==="edit")return open(id);if(a==="close"){S.editor=null;S.preview=null;render();return;}if(a==="back"){S.step=Math.max(0,S.step-1);render();schedule();return;}if(a==="next"){S.step=Math.min(2,S.step+1);render();schedule();return;}if(a==="save")return save(false);if(a==="save-theme")return save(true);if(a==="refresh-preview")return preview();if(a==="open-preview"){window.open(`/?screen_id=${encodeURIComponent(id||S.editor?.id||"")}`,"_blank");return;}if(a==="edit-theme")return window.StatsThemeManager.open(S.editor.id);
      if(a==="delete"){if(!confirm("Delete this Screen?"))return;try{await R.api(`/api/screens/${encodeURIComponent(id)}`,{method:"DELETE"});S.message="Screen deleted.";await load();R.emit("screens-changed");}catch(e){S.message=e.message;render();}}
    }));
    host.querySelectorAll("[data-step]").forEach(b=>b.addEventListener("click",()=>{sync();S.step=Number(b.dataset.step);render();schedule();}));
    host.querySelectorAll("input,select").forEach(i=>i.addEventListener("change",()=>{sync();render();schedule();}));
  }

  R.on("section",id=>{if(id==="settingsScreens"&&!loaded)load().catch(e=>{S.message=e.message;render();});});R.on("unlocked",()=>{loaded=false;});R.on("data-changed",()=>{loaded=false;});
})();
