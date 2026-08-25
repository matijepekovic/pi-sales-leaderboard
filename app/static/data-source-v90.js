/* v90 Data Source: one card for the whole pull.

   Where to connect, which report, which filters to send, which column feeds
   which board stat — all of it settings, none of it compiled in. The old
   split (a "Data Source" card describing a fixed Olympia view, and a separate
   "Report Source" picker that took over once you chose something) is gone;
   the shipped report is now just the configuration this card starts with.

   Ids stay v79* so the v83 search helper keeps attaching to the two selects.

   Nothing here touches the display: the board still receives the same rep
   rows it always has, so themes, table formatting and the number-size
   controls are unaffected by whichever report feeds them. */
(function(){
  const CARD=`
    <div class="card" id="v90SourceCard">
      <h2>Data Source</h2>
      <div class="small">Everything the morning pull uses. Change the report,
        the filters or the mapping here — check the numbers, then switch.</div>
      <div id="v79Current" class="small" style="margin-top:10px"></div>

      <h3 style="margin:18px 0 4px">Connection</h3>
      <div class="grid">
        <div><label for="v90Server">Server</label>
          <input id="v90Server" type="text" placeholder="https://10ay.online.tableau.com"></div>
        <div><label for="v90Site">Site</label>
          <input id="v90Site" type="text" placeholder="dabella"></div>
        <div><label for="v90PatName">Token name</label>
          <input id="v90PatName" type="text" placeholder="leaderboard"></div>
      </div>
      <div class="small" style="margin-top:6px;opacity:.7">The token secret
        stays where it was, under Tableau Data Source. It is never shown back.</div>

      <h3 style="margin:18px 0 4px">Report</h3>
      <div class="grid">
        <div>
          <label for="v79Workbook">Workbook</label>
          <select id="v79Workbook"><option value="">Loading…</option></select>
        </div>
        <div>
          <label for="v79Sheet">Sheet</label>
          <select id="v79Sheet"><option value="">Pick a workbook first</option></select>
        </div>
      </div>

      <h3 style="margin:18px 0 4px">Date range</h3>
      <label class="row" style="margin-bottom:6px">
        <input type="radio" name="v90DateMode" id="v90DateMonth" value="current_month">
        <span>Current calendar month, rolling</span></label>
      <label class="row">
        <input type="radio" name="v90DateMode" id="v90DateCustom" value="custom">
        <span>A range I choose</span></label>
      <div id="v90DateRow" class="grid" style="margin-top:10px;display:none">
        <div><label for="v90RangeStart">Start</label>
          <input id="v90RangeStart" type="date"></div>
        <div><label for="v90RangeEnd">End</label>
          <input id="v90RangeEnd" type="date"></div>
      </div>
      <div id="v90DateResolved" class="small" style="margin-top:8px;opacity:.75"></div>

      <h3 style="margin:18px 0 4px">Filters sent to Tableau</h3>
      <div class="small">What the Pi puts in the request. Remove them all and
        the report is pulled exactly as it is saved in Tableau.</div>
      <div id="v90Filters" style="margin-top:8px"></div>
      <div class="row" style="margin-top:8px;gap:10px;flex-wrap:wrap">
        <button id="v90AddFilter" class="btn" type="button">Add Filter</button>
      </div>
      <div class="grid" style="margin-top:12px">
        <div><label for="v90DateStart">Start date field</label>
          <input id="v90DateStart" type="text" placeholder="Start"></div>
        <div><label for="v90DateEnd">End date field</label>
          <input id="v90DateEnd" type="text" placeholder="End"></div>
      </div>

      <h3 style="margin:18px 0 4px">Keep only</h3>
      <div class="small">A last check on what came back, applied here rather
        than in Tableau. Leave the column blank to keep every row.</div>
      <div class="grid" style="margin-top:8px">
        <div><label for="v90KeepColumn">Column</label>
          <select id="v90KeepColumn"></select></div>
        <div><label for="v90KeepValue">Value</label>
          <input id="v90KeepValue" type="text" placeholder="Olympia"></div>
      </div>

      <div class="row" style="margin-top:16px;gap:10px;flex-wrap:wrap">
        <button id="v79Load" class="btn" type="button">Read Its Columns</button>
        <button id="v79Use" class="btn primary" type="button" disabled>Use This Source</button>
        <button id="v79Reset" class="btn danger" type="button">Reset to Default</button>
      </div>
      <div id="v79Status" class="small" style="margin-top:10px"></div>

      <div id="v79MapWrap" style="display:none;margin-top:20px">
        <h3 style="margin:0 0 4px">Match the columns</h3>
        <div class="small">Anything the names made obvious is filled in
          already. The example under each dropdown is what that column holds.
          Leave every stat unmapped to read a report shaped like the board's
          own.</div>
        <div id="v79MapRows" style="margin-top:10px"></div>
        <div id="v79Unmapped" class="small" style="margin-top:10px"></div>
      </div>

      <div class="row" style="margin-top:14px;gap:10px;flex-wrap:wrap">
        <button id="v79Check" class="btn" type="button">Check The Numbers</button>
        <button id="v79PreviewTv" class="btn primary" type="button">Preview on TV</button>
        <button id="v79PreviewStop" class="btn" type="button">Stop Preview</button>
      </div>
      <div id="v79PreviewStatus" class="small" style="margin-top:8px"></div>
      <div id="v79PreviewRows" style="margin-top:8px"></div>
    </div>`;

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  let proven=null;                       // the config that last pulled cleanly
  let headers=[], choices=[], samples={}, mapping=null, shape="";
  let filters=[], defaults={};

  const DIMENSIONS=[["rep_name","Sales Rep name"],["home_branch","Home Branch"],
                    ["team","Team Lead"]];

  function statList(){
    return (typeof metrics!=="undefined"?metrics:[])
      .filter(m=>["number","percent","currency"].includes(m.type))
      .map(m=>[m.key,m.label]);
  }


  // The candidate configuration, exactly as the API takes it.
  function candidate(){
    return {
      server:$("v90Server").value.trim(),
      site:$("v90Site").value.trim(),
      pat_name:$("v90PatName").value.trim(),
      workbook:$("v79Workbook").value.trim(),
      sheet:$("v79Sheet").value.trim(),
      filters:filters.filter(f=>f.field.trim()).map(f=>({field:f.field.trim(),value:f.value})),
      date_start_field:$("v90DateStart").value.trim(),
      date_end_field:$("v90DateEnd").value.trim(),
      row_filter:{column:$("v90KeepColumn").value,value:$("v90KeepValue").value.trim()},
      mapping:mapping||{},
    };
  }

  // The window is stored as its own settings keys, not inside `source`, so
  // it travels beside the configuration rather than in it.
  function dates(){
    return {
      data_date_mode: $("v90DateCustom").checked ? "custom" : "current_month",
      data_date_start: $("v90RangeStart").value,
      data_date_end: $("v90RangeEnd").value,
    };
  }

  const payload=()=>({...candidate(), ...dates()});

  function monthRange(){
    const now=new Date();
    const pad=n=>String(n).padStart(2,"0");
    const last=new Date(now.getFullYear(), now.getMonth()+1, 0).getDate();
    return [`${now.getFullYear()}-${pad(now.getMonth()+1)}-01`,
            `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(last)}`];
  }

  function paintDates(){
    const d=dates();
    const custom=d.data_date_mode==="custom";
    $("v90DateRow").style.display=custom?"":"none";
    // resolve_dates() falls back to the current month unless BOTH ends are
    // filled in, so say which window the pull will really use.
    const complete=custom&&d.data_date_start&&d.data_date_end;
    const [from,to]=complete?[d.data_date_start,d.data_date_end]:monthRange();
    const bad=complete&&d.data_date_start>d.data_date_end;
    $("v90DateResolved").innerHTML=bad
      ? '<strong>Start is after end — fix that before saving.</strong>'
      : `The next pull asks for <strong>${esc(from)}</strong> to <strong>${esc(to)}</strong>`
        +(custom&&!complete?" — fill in both dates to override the month." : "");
  }

  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  function touched(){ proven=null; paintDates(); setUseEnabled(); }
  function setUseEnabled(){ $("v79Use").disabled=!(proven && same(proven,payload())); }

  function paintFilters(){
    $("v90Filters").innerHTML=filters.map((f,i)=>`
      <div class="row" style="gap:8px;align-items:center;margin-bottom:6px">
        <input class="v90FField" data-i="${i}" type="text" value="${esc(f.field)}"
               placeholder="Field name" style="flex:1 1 auto">
        <input class="v90FValue" data-i="${i}" type="text" value="${esc(f.value)}"
               placeholder="Value" style="flex:1 1 auto">
        <button class="btn danger v90FDrop" data-i="${i}" type="button">Remove</button>
      </div>`).join("")
      || '<div class="small" style="opacity:.7">No filters — the report comes back as saved.</div>';
    $("v90Filters").querySelectorAll(".v90FField").forEach(el=>
      el.addEventListener("input",()=>{filters[el.dataset.i].field=el.value;touched();}));
    $("v90Filters").querySelectorAll(".v90FValue").forEach(el=>
      el.addEventListener("input",()=>{filters[el.dataset.i].value=el.value;touched();}));
    $("v90Filters").querySelectorAll(".v90FDrop").forEach(el=>
      el.addEventListener("click",()=>{filters.splice(Number(el.dataset.i),1);paintFilters();touched();}));
  }

  function options(list,selected){
    const known=list.slice();
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
    // Rep, branch and team are real columns whatever the report's shape; the
    // stats are the measure names on a pivoted report.
    DIMENSIONS.forEach(([key,label])=>
      rows.push(row("v79Dim",key,label,headers,mapping[key])));
    statList().forEach(([key,label])=>
      rows.push(row("v79Stat",key,label,choices,(mapping.metrics||{})[key])));
    $("v79MapRows").innerHTML=rows.join("");

    const after=sel=>{
      const hint=$("v79MapRows").querySelector(`[data-sample-for="${sel.dataset.key}"]`);
      if(hint) hint.innerHTML=sampleLine(sel.value);
      touched(); paintUnmapped();
    };
    $("v79MapRows").querySelectorAll(".v79Dim").forEach(sel=>
      sel.addEventListener("change",()=>{mapping[sel.dataset.key]=sel.value;after(sel);}));
    $("v79MapRows").querySelectorAll(".v79Stat").forEach(sel=>
      sel.addEventListener("change",()=>{
        mapping.metrics=mapping.metrics||{};
        if(sel.value) mapping.metrics[sel.dataset.key]=sel.value;
        else delete mapping.metrics[sel.dataset.key];
        after(sel);
      }));
    paintUnmapped();
  }

  function paintUnmapped(){
    const used=new Set([mapping.rep_name,mapping.home_branch,mapping.team,
      ...Object.values(mapping.metrics||{})].filter(Boolean));
    const left=choices.filter(c=>!used.has(c));
    const note=!mapping.rep_name
      ? "No rep column mapped — this report will be read by the board's own parser.<br>" : "";
    $("v79Unmapped").innerHTML=note+(left.length
      ? `Not used: ${esc(left.join(", "))}` : "Every column is being used.");
  }

  async function loadColumns(){
    mapping=null; headers=[]; choices=[]; samples={}; paintMapping();
    touched();
    $("v79PreviewRows").innerHTML=""; $("v79PreviewStatus").textContent="";
    $("v79Status").textContent="Reading that report…";
    try{
      const {r,d}=await request("/api/source/columns",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload())});
      if(!r.ok||!d.ok){$("v79Status").textContent=d.error||"Could not read that report.";return;}
      headers=d.headers||[]; choices=d.choices||[]; samples=d.samples||{}; shape=d.shape;
      mapping=d.suggested||{}; mapping.metrics=mapping.metrics||{};
      paintMapping();
      const matched=Object.keys(mapping.metrics).length;
      $("v79Status").textContent=
        `${esc(d.export||"")} · ${shape==="long"?"pivoted":"one row per rep"}, `+
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
    const stats=statList().filter(([key])=>rows.some(r=>Number(r[key])));
    const head=["Rep","Team",...stats.map(([,label])=>label)];
    const num=v=>typeof v==="number"
      ? v.toLocaleString(undefined,{maximumFractionDigits:2}) : String(v??"");
    const body=rows.slice(0,5).map(rep=>
      `<tr>${[esc(rep.rep_name||""),esc(rep.team||"")]
        .concat(stats.map(([key])=>esc(num(rep[key]))))
        .map(c=>`<td style="padding:3px 8px 3px 0">${c}</td>`).join("")}</tr>`).join("");
    wrap.innerHTML=`<div style="overflow-x:auto"><table class="small" style="border-collapse:collapse">
      <tr>${head.map(h=>`<th style="text-align:left;padding:3px 8px 3px 0">${esc(h)}</th>`).join("")}</tr>
      ${body}</table></div>`;
  }

  async function runPreview(on_tv){
    const status=$("v79PreviewStatus");
    status.textContent=on_tv?"Pulling and putting it on the TV…":"Pulling…";
    try{
      const {r,d}=await request("/api/source/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...payload(),on_tv})});
      if(!r.ok||!d.ok){
        status.innerHTML=`<strong>That pull failed.</strong><br>${esc(d.error||"")}`;
        $("v79PreviewRows").innerHTML=""; return;
      }
      proven=payload(); setUseEnabled();
      const notes=d.notes||{};
      const cost=notes.seconds!==undefined?` · ${notes.seconds}s`:"";
      const scaled=(notes.scaled||[]).length
        ? " Rates came back as fractions and were scaled to percent." : "";
      status.innerHTML=`<strong>${d.reps} reps</strong>, ${esc(d.start)} to ${esc(d.end)}`+
        ` · ${esc(notes.export||"")}${esc(cost)}.`+esc(scaled)+
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

  function fill(source, columns){
    $("v90Server").value=source.server||"";
    $("v90Site").value=source.site||"";
    $("v90PatName").value=source.pat_name||"";
    $("v90DateStart").value=source.date_start_field||"";
    $("v90DateEnd").value=source.date_end_field||"";
    filters=(source.filters||[]).map(f=>({field:f.field||"",value:f.value||""}));
    paintFilters();
    const keep=source.row_filter||{};
    // The columns a keep-only rule may name come from the API: the page's own
    // metric list is not filled in yet when this card first paints.
    $("v90KeepColumn").innerHTML='<option value="">— keep every row —</option>'+
      (columns||[]).map(c=>
        `<option value="${esc(c.key)}"${c.key===keep.column?" selected":""}>${esc(c.label)}</option>`).join("");
    $("v90KeepValue").value=keep.value||"";
    mapping=(source.mapping&&source.mapping.rep_name)?{...source.mapping}:null;

    const saved=window.config||{};
    const custom=(saved.data_date_mode||"current_month")==="custom";
    $("v90DateCustom").checked=custom;
    $("v90DateMonth").checked=!custom;
    $("v90RangeStart").value=saved.data_date_start||"";
    $("v90RangeEnd").value=saved.data_date_end||"";
    paintDates();
  }

  async function paintCurrent(){
    try{
      const {r,d}=await request("/api/source/report",{cache:"no-store"});
      if(!r.ok) return;
      defaults=d.defaults||{};
      $("v79Current").innerHTML=d.is_default
        ? `Currently reading the shipped default: <strong>${esc(d.workbook)} / ${esc(d.sheet)}</strong>`
        : `Currently reading: <strong>${esc(d.workbook)} / ${esc(d.sheet)}</strong>`;
      fill(d, d.row_filter_columns);
      if(d.workbook){
        const select=$("v79Workbook");
        if(select&&select.tagName==="SELECT"&&!select.value){
          select.innerHTML=`<option value="${esc(d.workbook)}" selected>${esc(d.workbook)}</option>`;
        }
        const sheet=$("v79Sheet");
        if(sheet&&sheet.tagName==="SELECT"&&!sheet.value){
          sheet.innerHTML=`<option value="${esc(d.sheet)}" selected>${esc(d.sheet)}</option>`;
        }
      }
    }catch(e){}
  }

  async function loadWorkbooks(){
    const select=$("v79Workbook");
    try{
      const {r,d}=await request("/api/source/workbooks",{cache:"no-store"});
      if(!r.ok||!d.workbooks||!d.workbooks.length){ typedFallback(d&&d.error); return; }
      const current=$("v79Workbook").value;
      select.innerHTML='<option value="">Choose a workbook…</option>'+
        d.workbooks.map(w=>
          `<option value="${esc(w.content_url)}"${w.content_url===current?" selected":""}>${esc(w.name||w.content_url)}</option>`).join("");
      if(current) loadViews();
    }catch(e){
      if(e.message!=="locked") typedFallback("Could not reach the Pi.");
    }
  }

  function typedFallback(why){
    const wrap=$("v79Workbook").parentElement.parentElement;
    const workbook=$("v79Workbook").value, sheet=$("v79Sheet").value;
    wrap.innerHTML=`
      <div><label for="v79Workbook">Workbook</label>
        <input id="v79Workbook" type="text" value="${esc(workbook)}" placeholder="8-SalesRepLevelData"></div>
      <div><label for="v79Sheet">Sheet</label>
        <input id="v79Sheet" type="text" value="${esc(sheet)}" placeholder="RepTotalsNEW3"></div>`;
    $("v79Status").textContent=
      (why?why+" ":"")+"Type the workbook and sheet names instead, then Read Its Columns.";
    ["v79Workbook","v79Sheet"].forEach(id=>{
      $(id).addEventListener("input",touched);
      $(id).addEventListener("change",()=>{if($("v79Sheet").value.trim()) loadColumns();});
    });
  }

  async function loadViews(){
    const workbook=$("v79Workbook").value;
    const select=$("v79Sheet");
    if(!select||select.tagName!=="SELECT") return;
    if(!workbook){select.innerHTML='<option value="">Pick a workbook first</option>';return;}
    const current=select.value;
    select.innerHTML='<option value="">Loading…</option>';
    try{
      const {r,d}=await request(
        `/api/source/workbooks/${encodeURIComponent(workbook)}/views`,{cache:"no-store"});
      if(!r.ok||!d.views){
        select.innerHTML='<option value="">Could not list sheets</option>';
        $("v79Status").textContent=(d&&d.error)||"Could not list sheets.";
        return;
      }
      select.innerHTML='<option value="">Choose a sheet…</option>'+
        d.views.map(v=>{
          const tail=String(v.content_url||"").split("/").pop();
          const sel=(tail===current||v.content_url===current)?" selected":"";
          return `<option value="${esc(tail)}"${sel}>${esc(v.name||tail)}</option>`;
        }).join("");
    }catch(e){
      if(e.message!=="locked") $("v79Status").textContent="Could not reach the Pi.";
    }
  }

  async function save(chosen,message){
    const {data_date_mode,data_date_start,data_date_end}=chosen||dates();
    const source={...(chosen||{})};
    ["data_date_mode","data_date_start","data_date_end"].forEach(k=>delete source[k]);
    const status=$("v79Status");
    status.textContent="Saving…";
    try{
      const {r,d}=await request("/api/config",{
        method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...(window.config||{}), source,
          data_date_mode, data_date_start, data_date_end})});
      if(!r.ok){status.textContent=d.error||"Could not save.";return;}
      window.config=d.settings;
      await paintCurrent();
      status.textContent=message;
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }
  }

  function mount(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("v90SourceCard")) return;
    app.insertAdjacentHTML("beforeend",CARD);

    ["v90Server","v90Site","v90PatName","v90DateStart","v90DateEnd","v90KeepValue"]
      .forEach(id=>$(id).addEventListener("input",touched));
    $("v90KeepColumn").addEventListener("change",touched);
    ["v90DateMonth","v90DateCustom","v90RangeStart","v90RangeEnd"]
      .forEach(id=>$(id).addEventListener("change",touched));
    $("v90AddFilter").addEventListener("click",()=>{
      filters.push({field:"",value:""}); paintFilters(); touched();
    });
    $("v79Workbook").addEventListener("change",()=>{touched();loadViews();});
    $("v79Sheet").addEventListener("change",()=>{touched();loadColumns();});
    $("v79Load").addEventListener("click",loadColumns);
    $("v79Check").addEventListener("click",()=>runPreview(false));
    $("v79PreviewTv").addEventListener("click",()=>runPreview(true));
    $("v79PreviewStop").addEventListener("click",stopPreview);
    $("v79Use").addEventListener("click",()=>{
      if(!proven) return;
      save(proven,"Saved. The next pull uses this source — press Pull From Tableau Now to try it straight away.");
    });
    $("v79Reset").addEventListener("click",()=>{
      touched(); mapping=null; headers=[]; choices=[]; samples={}; paintMapping();
      $("v79PreviewRows").innerHTML=""; $("v79PreviewStatus").textContent="";
      stopPreview();
      $("v90DateMonth").checked=true; $("v90DateCustom").checked=false;
      $("v90RangeStart").value=""; $("v90RangeEnd").value=""; paintDates();
      save({data_date_mode:"current_month",data_date_start:"",data_date_end:""},
           "Back to the shipped default source, on the current month.");
    });

    paintCurrent().then(loadWorkbooks);
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
