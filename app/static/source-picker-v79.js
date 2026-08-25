/* Report picker: choose which Tableau report the rep board reads, and match
   its columns to the board's stats by hand.

   v81 hands the matching to you. Earlier versions ran a shape test first and
   refused anything that was not the board's own long-format export, which is
   most reports. Now the report is only ever read and described -- every
   column is offered in a dropdown, with an example value beside it, and you
   decide what feeds what. The only check left is your own: pull it through
   your mapping and look at the numbers before saving. */
(function(){
  const CARD=`
    <div class="card" id="v79SourceCard">
      <h2>Report Source</h2>
      <div class="small">Which Tableau report the leaderboard reads. Pick one,
        match its columns to the board's stats, then check the numbers before
        you switch.</div>
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
        <button id="v79Load" class="btn" type="button">Read Its Columns</button>
        <button id="v79Use" class="btn primary" type="button" disabled>Use This Report</button>
        <button id="v79Reset" class="btn danger" type="button">Reset to Default</button>
      </div>
      <div id="v79Status" class="small" style="margin-top:10px"></div>

      <div id="v79MapWrap" style="display:none;margin-top:20px">
        <h3 style="margin:0 0 4px">Match the columns</h3>
        <div class="small">Anything the names made obvious is filled in
          already. Everything is yours to change — the example value under
          each dropdown is what that column actually holds.</div>
        <div id="v79MapRows" style="margin-top:10px"></div>
        <div id="v79Unmapped" class="small" style="margin-top:10px"></div>

        <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
          <button id="v79Check" class="btn" type="button">Check The Numbers</button>
          <button id="v79PreviewTv" class="btn primary" type="button">Preview on TV</button>
          <button id="v79PreviewStop" class="btn" type="button">Stop Preview</button>
        </div>
        <div id="v79PreviewStatus" class="small" style="margin-top:8px"></div>
        <div id="v79PreviewRows" style="margin-top:8px"></div>
      </div>
    </div>`;

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  // The last combination that was actually pulled through its mapping.
  let proven=null;
  // What the report offers: real columns, mappable metric names, examples.
  let headers=[], choices=[], samples={}, mapping=null, shape="";

  const DIMENSIONS=[["rep_name","Sales Rep name"],["home_branch","Home Branch"],
                    ["team","Team Lead"]];

  function statList(){
    // The board's own numeric stats, in the order it defines them.
    return (typeof metrics!=="undefined"?metrics:[])
      .filter(m=>["number","percent","currency"].includes(m.type))
      .map(m=>[m.key,m.label]);
  }

  function options(list,selected){
    const known=list.slice();
    // A mapping saved against an older export can name something this pull
    // did not return. Keep it in the list rather than silently dropping it.
    if(selected&&!known.includes(selected)) known.unshift(selected);
    return '<option value="">— not mapped —</option>'+
      known.map(c=>`<option value="${esc(c)}"${c===selected?" selected":""}>${esc(c)}</option>`).join("");
  }

  function sampleLine(name){
    const value=name?samples[name]:"";
    return value?`<div class="small" style="opacity:.65;margin-top:2px">e.g. ${esc(value)}</div>`:"";
  }

  function row(cls,key,label,list,selected){
    return `<div style="padding:8px 0;border-top:1px solid #262626">
      <div class="row" style="justify-content:space-between;align-items:center;gap:10px">
        <span style="min-width:120px">${esc(label)}</span>
        <select class="${cls}" data-key="${key}" style="flex:1 1 auto">${options(list,selected)}</select>
      </div>
      <div data-sample-for="${key}">${sampleLine(selected)}</div>
    </div>`;
  }

  function paintMapping(){
    if(!mapping){$("v79MapWrap").style.display="none";return;}
    $("v79MapWrap").style.display="";
    const rows=[];
    // Rep, branch and team live in real columns whatever the report's shape.
    // The stats live in `choices`, which on a pivoted report are the measure
    // names -- offering headers there would be offering nothing usable.
    DIMENSIONS.forEach(([key,label])=>
      rows.push(row("v79Dim",key,label,headers,mapping[key])));
    statList().forEach(([key,label])=>
      rows.push(row("v79Stat",key,label,choices,(mapping.metrics||{})[key])));
    $("v79MapRows").innerHTML=rows.join("");

    const touched=sel=>{
      const hint=$("v79MapRows").querySelector(`[data-sample-for="${sel.dataset.key}"]`);
      if(hint) hint.innerHTML=sampleLine(sel.value);
      proven=null; setUseEnabled(); paintUnmapped();
    };
    $("v79MapRows").querySelectorAll(".v79Dim").forEach(sel=>
      sel.addEventListener("change",()=>{mapping[sel.dataset.key]=sel.value;touched(sel);}));
    $("v79MapRows").querySelectorAll(".v79Stat").forEach(sel=>
      sel.addEventListener("change",()=>{
        mapping.metrics=mapping.metrics||{};
        if(sel.value) mapping.metrics[sel.dataset.key]=sel.value;
        else delete mapping.metrics[sel.dataset.key];
        touched(sel);
      }));
    paintUnmapped();
  }

  function paintUnmapped(){
    const used=new Set([mapping.rep_name,mapping.home_branch,mapping.team,
      ...Object.values(mapping.metrics||{})].filter(Boolean));
    const left=choices.filter(c=>!used.has(c));
    const missing=!mapping.rep_name
      ? "<strong>Match the Sales Rep name first — nothing can be read without it.</strong><br>" : "";
    $("v79Unmapped").innerHTML=missing+(left.length
      ? `Not used: ${esc(left.join(", "))}`
      : "Every column is being used.");
  }

  async function loadColumns(){
    const workbook=$("v79Workbook").value.trim(), sheet=$("v79Sheet").value.trim();
    mapping=null; headers=[]; choices=[]; samples={}; paintMapping();
    proven=null; setUseEnabled();
    $("v79PreviewRows").innerHTML=""; $("v79PreviewStatus").textContent="";
    if(!workbook||!sheet){$("v79Status").textContent="Pick a workbook and a sheet first.";return;}
    $("v79Status").textContent="Reading that report's columns…";
    try{
      const {r,d}=await request("/api/source/columns",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({workbook,sheet})});
      if(!r.ok||!d.ok){$("v79Status").textContent=d.error||"Could not read that report.";return;}
      headers=d.headers||[]; choices=d.choices||[]; samples=d.samples||{}; shape=d.shape;
      mapping=d.suggested||{}; mapping.metrics=mapping.metrics||{};
      // The mapping section opens whatever the guess managed, including
      // nothing at all -- an unrecognised report is one you match by hand,
      // not one that gets refused.
      paintMapping();
      const matched=Object.keys(mapping.metrics).length;
      $("v79Status").textContent=
        `${shape==="long"?"Pivoted":"One row per rep"} report, `+
        `${choices.length} column${choices.length===1?"":"s"}. `+
        (matched?`${matched} stat${matched===1?"":"s"} matched by name — check them and fill in the rest.`
                :"Nothing matched by name — match them below.");
    }catch(e){
      if(e.message!=="locked") $("v79Status").textContent="Could not reach the Pi.";
    }
  }

  function paintPreviewRows(rows){
    const wrap=$("v79PreviewRows");
    if(!rows||!rows.length){wrap.innerHTML="";return;}
    const stats=statList().filter(([key])=>(mapping.metrics||{})[key]);
    const head=["Rep",...stats.map(([,label])=>label)];
    const num=v=>typeof v==="number"
      ? v.toLocaleString(undefined,{maximumFractionDigits:2}) : String(v??"");
    const body=rows.slice(0,5).map(rep=>{
      const cells=[esc(rep.rep_name||rep.name||"")]
        .concat(stats.map(([key])=>esc(num(rep[key]))));
      return `<tr>${cells.map(c=>`<td style="padding:3px 8px 3px 0">${c}</td>`).join("")}</tr>`;
    }).join("");
    wrap.innerHTML=`<div style="overflow-x:auto"><table class="small" style="border-collapse:collapse">
      <tr>${head.map(h=>`<th style="text-align:left;padding:3px 8px 3px 0">${esc(h)}</th>`).join("")}</tr>
      ${body}</table></div>`;
  }

  async function runPreview(on_tv){
    const workbook=$("v79Workbook").value.trim(), sheet=$("v79Sheet").value.trim();
    const status=$("v79PreviewStatus");
    if(!mapping||!mapping.rep_name){
      status.textContent="Match the Sales Rep name first.";return;
    }
    status.textContent=on_tv?"Pulling and putting it on the TV…":"Pulling…";
    try{
      const {r,d}=await request("/api/source/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({workbook,sheet,mapping,on_tv})});
      if(!r.ok||!d.ok){
        status.innerHTML=`<strong>That pull failed.</strong><br>${esc(d.error||"")}`;
        $("v79PreviewRows").innerHTML="";
        return;
      }
      proven={workbook,sheet}; setUseEnabled();
      const scaled=(d.notes&&d.notes.scaled||[]).length
        ? " Rates came back as fractions and were scaled to percent." : "";
      status.innerHTML=`<strong>${d.reps} reps</strong>, ${esc(d.start)} to ${esc(d.end)}.`+
        esc(scaled)+
        (d.on_tv?` <br>Showing on the TV for ${Math.round((d.preview.seconds_left||0)/60)} minutes — it reverts on its own.`
                :" <br>Nothing was saved or shown on the TV.");
      paintPreviewRows(d.rows);
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
        // A token that cannot enumerate content can still read a report it is
        // pointed at, so fall back to typing the names.
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
      (why?why+" ":"")+"Type the workbook and sheet names instead, then Read Its Columns.";
    // Typed names have to reach the mapper too, so the same change/blur that
    // a dropdown fires is wired here.
    ["v79Workbook","v79Sheet"].forEach(id=>{
      $(id).addEventListener("input",()=>{proven=null;setUseEnabled();});
      $(id).addEventListener("change",()=>{if($("v79Sheet").value.trim()) loadColumns();});
    });
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
    $("v79Load").addEventListener("click",loadColumns);
    $("v79Check").addEventListener("click",()=>runPreview(false));
    $("v79PreviewTv").addEventListener("click",()=>runPreview(true));
    $("v79PreviewStop").addEventListener("click",stopPreview);
    $("v79Use").addEventListener("click",()=>{
      if(!proven) return;
      save(proven.workbook,proven.sheet,
        "Saved. The next pull reads that report — press Pull Now to try it straight away.");
    });
    $("v79Reset").addEventListener("click",()=>{
      proven=null; setUseEnabled();
      mapping=null; headers=[]; choices=[]; samples={}; paintMapping();
      $("v79PreviewRows").innerHTML=""; $("v79PreviewStatus").textContent="";
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
