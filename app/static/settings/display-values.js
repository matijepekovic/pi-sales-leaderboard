/* Display Values owns user-facing names for normalized Report fields. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const S={values:[],reports:[],message:""};
  let loaded=false;
  const report=id=>S.reports.find(item=>String(item.id)===String(id))||null;

  async function load(){
    const [values,reports]=await Promise.all([R.api("/api/display-values"),R.api("/api/data/reports")]);
    S.values=values.display_values||[];S.reports=reports.reports||[];loaded=true;render();
    R.emit("display-values-changed",S.values.slice());
  }

  function reportCard(r){
    const values=S.values.filter(value=>String(value.report_id)===String(r.id));
    return `<div class="card"><div class="toolbar"><div><h2>${esc(r.name)}</h2><div class="small">Every pulled Report field is automatically a Display Value.</div></div></div>${values.length?`<div class="data-table" style="margin-top:12px"><table><thead><tr><th>Report Field</th><th>Display Value</th><th>Type</th><th></th></tr></thead><tbody>${values.map(value=>`<tr><td><strong>${esc(value.source_name||value.field_key)}</strong><div class="field-key">${esc(value.field_key)}</div></td><td><input data-display-value-name="${esc(value.id)}" value="${esc(value.name)}"></td><td>${esc(value.type||"text")}</td><td><button class="btn primary" data-display-value-save="${esc(value.id)}">Save</button></td></tr>`).join("")}</tbody></table></div>`:'<div class="small" style="margin-top:12px">No pulled fields yet. Pull this Report in Data and its fields will appear here automatically.</div>'}</div>`;
  }

  function render(){
    const host=$("settingsDisplayValuesHost");if(!host)return;
    host.innerHTML=`<div class="card"><h2>Display Values</h2><div class="small">Stats creates one Display Value for every Report field. Rename only what people should see; the original Report field stays bound underneath.</div></div>${S.reports.map(reportCard).join("")||'<div class="card"><div class="small">Create a Report in Data first.</div></div>'}<div class="status">${esc(S.message||"")}</div>`;
    host.querySelectorAll("[data-display-value-save]").forEach(button=>button.addEventListener("click",()=>save(button.dataset.displayValueSave)));
  }

  async function save(id){
    const input=document.querySelector(`[data-display-value-name="${CSS.escape(id)}"]`);if(!input)return;
    S.message="Saving Display Value…";render();
    try{
      await R.api(`/api/display-values/${encodeURIComponent(id)}`,R.json("PUT",{name:input.value}));
      S.message="Display Value saved.";await load();
    }catch(error){S.message=error.message;render();}
  }

  function open(){
    const button=document.querySelector('[data-settings-target="settingsDisplayValues"]');
    if(button)button.click();
  }

  R.on("section",id=>{if(id==="settingsDisplayValues"&&!loaded)load().catch(error=>{S.message=error.message;render();});});
  R.on("unlocked",()=>{loaded=false;});
  R.on("data-changed",()=>{loaded=false;});
  window.StatsDisplayValueManager=Object.freeze({reload:load,open});
})();
