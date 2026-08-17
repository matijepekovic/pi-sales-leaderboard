/* v79 Report picker: choose which Tableau report the rep board reads.

   Save is deliberately gated behind a successful Test. The rep parser needs
   Tableau's long format -- SR-Name, Measure Names, Measure Values -- and a
   sheet without those raises rather than producing wrong numbers. Testing
   first means that shows up here, not at 6am with a stale board on the wall. */
(function(){
  const CARD=`
    <div class="card" id="v79SourceCard">
      <h2>Report Source</h2>
      <div class="small">Which Tableau report the leaderboard reads.
        A report has to pass a test pull before it can be used.</div>
      <div id="v79Current" class="small" style="margin-top:10px"></div>

      <div class="grid" style="margin-top:14px">
        <div>
          <label for="v79Workbook">Workbook</label>
          <select id="v79Workbook"><option value="">Loading…</option></select>
        </div>
        <div>
          <label for="v79Sheet">Sheet</label>
          <select id="v79Sheet"><option value="">Pick a workbook first</option></select>
        </div>
      </div>

      <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
        <button id="v79Test" class="btn" type="button">Test This Report</button>
        <button id="v79Use" class="btn primary" type="button" disabled>Use This Report</button>
        <button id="v79Reset" class="btn danger" type="button">Reset to Default</button>
      </div>
      <div id="v79Status" class="small" style="margin-top:10px"></div>

      <div id="v79MapWrap" style="display:none;margin-top:20px">
        <h3 style="margin:0 0 4px">Map the stats</h3>
        <div class="small">Which column feeds which board stat. Guessed from the
          names — change anything that looks wrong.</div>
        <div id="v79MapRows" style="margin-top:10px"></div>
        <div id="v79Unmapped" class="small" style="margin-top:10px"></div>

        <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
          <button id="v79PreviewTv" class="btn primary" type="button">Preview on TV</button>
          <button id="v79PreviewStop" class="btn" type="button">Stop Preview</button>
        </div>
        <div id="v79PreviewStatus" class="small" style="margin-top:8px"></div>
      </div>
    </div>`;

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  // The last combination that actually passed a test or preview.
  let proven=null;
  // The report's mappable columns and the current mapping.
  let choices=[], mapping=null, shape="";

  const DIMENSIONS=[["rep_name","Sales Rep name"],["home_branch","Home Branch"],
                    ["team","Team Lead"]];

  function statList(){
    // The board's own numeric stats, in the order it defines them.
    return (typeof metrics!=="undefined"?metrics:[])
      .filter(m=>["number","percent","currency"].includes(m.type))
      .map(m=>[m.key,m.label]);
  }

  function options(selected){
    return '<option value="">— not mapped —</option>'+
      choices.map(c=>`<option value="${esc(c)}"${c===selected?" selected":""}>${esc(c)}</option>`).join("");
  }

  function paintMapping(){
    if(!mapping){$("v79MapWrap").style.display="none";return;}
    $("v79MapWrap").style.display="";
    const rows=[];
    DIMENSIONS.forEach(([key,label])=>{
      rows.push(`<div class="row" style="justify-content:space-between;align-items:center;gap:10px;padding:6px 0">
        <span style="min-width:120px">${esc(label)}</span>
        <select class="v79Dim" data-key="${key}" style="flex:1 1 auto">${options(mapping[key])}</select>
      </div>`);
    });
    statList().forEach(([key,label])=>{
      rows.push(`<div class="row" style="justify-content:space-between;align-items:center;gap:10px;padding:6px 0;border-top:1px solid #262626">
        <span style="min-width:120px">${esc(label)}</span>
        <select class="v79Stat" data-key="${key}" style="flex:1 1 auto">${options((mapping.metrics||{})[key])}</select>
      </div>`);
    });
    $("v79MapRows").innerHTML=rows.join("");
    $("v79MapRows").querySelectorAll(".v79Dim").forEach(sel=>
      sel.addEventListener("change",()=>{mapping[sel.dataset.key]=sel.value;proven=null;setUseEnabled();paintUnmapped();}));
    $("v79MapRows").querySelectorAll(".v79Stat").forEach(sel=>
      sel.addEventListener("change",()=>{
        mapping.metrics=mapping.metrics||{};
        if(sel.value) mapping.metrics[sel.dataset.key]=sel.value;
        else delete mapping.metrics[sel.dataset.key];
        proven=null;setUseEnabled();paintUnmapped();
      }));
    paintUnmapped();
  }

  function paintUnmapped(){
    const used=new Set([mapping.rep_name,mapping.home_branch,mapping.team,
      ...Object.values(mapping.metrics||{})].filter(Boolean));
    const left=choices.filter(c=>!used.has(c));
    $("v79Unmapped").textContent=left.length
      ? `Not used: ${left.join(", ")}`
      : "Every column is mapped.";
  }

  async function loadColumns(){
    const workbook=$("v79Workbook").value.trim(), sheet=$("v79Sheet").value.trim();
    mapping=null; choices=[]; paintMapping();
    if(!workbook||!sheet) return;
    $("v79Status").textContent="Reading that report's columns…";
    try{
      const {r,d}=await request("/api/source/columns",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({workbook,sheet})});
      if(!r.ok||!d.ok){$("v79Status").textContent=d.error||"Could not read that report.";return;}
      choices=d.choices||[]; shape=d.shape; mapping=d.suggested||{metrics:{}};
      mapping.metrics=mapping.metrics||{};
      paintMapping();
      $("v79Status").textContent=
        `${shape==="long"?"Pivoted":"One row per rep"} report, ${choices.length} columns. `+
        `${Object.keys(mapping.metrics).length} stats matched automatically.`;
    }catch(e){
      if(e.message!=="locked") $("v79Status").textContent="Could not reach the Pi.";
    }
  }

  async function previewOnTv(on_tv){
    const workbook=$("v79Workbook").value.trim(), sheet=$("v79Sheet").value.trim();
    const status=$("v79PreviewStatus");
    status.textContent=on_tv?"Pulling and putting it on the TV…":"Pulling…";
    try{
      const {r,d}=await request("/api/source/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({workbook,sheet,mapping,on_tv})});
      if(!r.ok||!d.ok){status.innerHTML=`<strong>Preview failed.</strong><br>${esc(d.error||"")}`;return;}
      proven={workbook,sheet}; setUseEnabled();
      const scaled=(d.notes&&d.notes.scaled||[]).length
        ? ` Rates were fractions, scaled to percent.` : "";
      status.innerHTML=`<strong>${d.reps} reps</strong>, ${esc(d.start)} to ${esc(d.end)}.`+
        esc(scaled)+(d.on_tv?` <br>Showing on the TV for ${Math.round((d.preview.seconds_left||0)/60)} minutes — it reverts on its own.`:"");
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }
  }

  async function stopPreview(){
    try{
      await request("/api/source/preview/stop",{method:"POST"});
      $("v79PreviewStatus").textContent="Preview stopped. The TV is back on the real numbers.";
    }catch(e){}
  }

  function setUseEnabled(){
    const wb=$("v79Workbook").value, sh=$("v79Sheet").value;
    $("v79Use").disabled=!(proven && proven.workbook===wb && proven.sheet===sh);
  }

  async function paintCurrent(){
    try{
      const {r,d}=await request("/api/source/report",{cache:"no-store"});
      if(!r.ok) return;
      $("v79Current").innerHTML=d.is_default
        ? `Currently reading the default report: <strong>${esc(d.workbook)} / ${esc(d.sheet)}</strong>`
        : `Currently reading: <strong>${esc(d.workbook)} / ${esc(d.sheet)}</strong>`;
    }catch(e){}
  }

  async function loadWorkbooks(){
    const select=$("v79Workbook");
    try{
      const {r,d}=await request("/api/source/workbooks",{cache:"no-store"});
      if(!r.ok||!d.workbooks||!d.workbooks.length){
        // A token that cannot enumerate content still works fine -- the Test
        // button is what matters -- so fall back to typing the names.
        typedFallback(d&&d.error);
        return;
      }
      select.innerHTML='<option value="">Choose a workbook…</option>'+
        d.workbooks.map(w=>
          `<option value="${esc(w.content_url)}">${esc(w.name||w.content_url)}</option>`).join("");
      const current=(typeof config!=="undefined"&&config&&config.tableau_workbook)||"";
      if(current) { select.value=current; loadViews(); }
    }catch(e){
      if(e.message!=="locked") typedFallback("Could not reach the Pi.");
    }
  }

  function typedFallback(why){
    const wrap=$("v79Workbook").parentElement.parentElement;
    wrap.innerHTML=`
      <div><label for="v79Workbook">Workbook</label>
        <input id="v79Workbook" type="text" placeholder="8-SalesRepLevelData"></div>
      <div><label for="v79Sheet">Sheet</label>
        <input id="v79Sheet" type="text" placeholder="RepTotalsNEW3"></div>`;
    $("v79Status").textContent=
      (why?why+" ":"")+"Enter the workbook and sheet names instead; Test still works.";
    ["v79Workbook","v79Sheet"].forEach(id=>
      $(id).addEventListener("input",()=>{proven=null;setUseEnabled();}));
  }

  async function loadViews(){
    const workbook=$("v79Workbook").value;
    const select=$("v79Sheet");
    if(!select||select.tagName!=="SELECT") return;
    if(!workbook){select.innerHTML='<option value="">Pick a workbook first</option>';return;}
    select.innerHTML='<option value="">Loading…</option>';
    try{
      const {r,d}=await request(
        `/api/source/workbooks/${encodeURIComponent(workbook)}/views`,{cache:"no-store"});
      if(!r.ok||!d.views){
        select.innerHTML='<option value="">Could not list sheets</option>';
        $("v79Status").textContent=(d&&d.error)||"Could not list sheets.";
        return;
      }
      // Sheet display names differ from their URL names, so show the name
      // and store the content URL.
      select.innerHTML='<option value="">Choose a sheet…</option>'+
        d.views.map(v=>
          `<option value="${esc(v.content_url)}">${esc(v.name||v.content_url)}</option>`).join("");
    }catch(e){
      if(e.message!=="locked") $("v79Status").textContent="Could not reach the Pi.";
    }
  }

  async function test(){
    const workbook=$("v79Workbook").value.trim();
    const sheet=$("v79Sheet").value.trim();
    const status=$("v79Status"), button=$("v79Test");
    if(!workbook||!sheet){status.textContent="Pick a workbook and a sheet first.";return;}
    proven=null; setUseEnabled();
    button.disabled=true;
    status.textContent="Pulling from that report… this takes a few seconds.";
    try{
      const {r,d}=await request("/api/source/test-view",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({workbook,sheet})});
      if(!r.ok||!d.ok){
        status.innerHTML=`<strong>That report will not work.</strong><br>${esc(d.error||"Test failed.")}`;
        return;
      }
      proven={workbook,sheet};
      setUseEnabled();
      status.innerHTML=
        `<strong>Looks good.</strong> ${d.reps} reps, ${esc(d.start)} to ${esc(d.end)}`+
        (d.offices&&d.offices.length?`, office ${esc(d.offices.join(", "))}`:"")+
        `.<br><span class="small">${d.metrics.length} metrics with values`+
        (d.sample&&d.sample.length?` · e.g. ${esc(d.sample.join(", "))}`:"")+
        `</span>`;
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }finally{
      button.disabled=false;
    }
  }

  async function save(workbook,sheet,message){
    const status=$("v79Status");
    status.textContent="Saving…";
    try{
      const {r,d}=await request("/api/config",{
        method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...config,tableau_workbook:workbook,tableau_sheet:sheet,
          source_mapping:workbook?(mapping||{}):{}})});
      if(!r.ok){status.textContent=d.error||"Could not save.";return;}
      config=d.settings;
      await paintCurrent();
      status.textContent=message;
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }
  }

  function mount(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("v79SourceCard")) return;
    app.insertAdjacentHTML("beforeend",CARD);
    $("v79Workbook").addEventListener("change",()=>{proven=null;setUseEnabled();loadViews();});
    $("v79Sheet").addEventListener("change",()=>{proven=null;setUseEnabled();loadColumns();});
    $("v79Test").addEventListener("click",test);
    $("v79PreviewTv").addEventListener("click",()=>previewOnTv(true));
    $("v79PreviewStop").addEventListener("click",stopPreview);
    $("v79Use").addEventListener("click",()=>{
      if(!proven) return;
      save(proven.workbook,proven.sheet,
        "Saved. The next pull reads that report — press Pull Now to try it straight away.");
    });
    $("v79Reset").addEventListener("click",()=>{
      proven=null; setUseEnabled();
      mapping=null; choices=[]; paintMapping();
      stopPreview();
      save("","","Back to the default report.");
    });
    paintCurrent();
    loadWorkbooks();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
