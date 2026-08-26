/* v90 Data Source: one card for the whole pull.

   Where to connect, which report, which filters to send, which column feeds
   which board stat — all of it settings, none of it compiled in. The old
   split (a "Data Source" card describing a fixed view, and a separate report
   picker) is gone. No report is selected until the user tests and saves one.

   Ids stay v79* so the existing source endpoints and mapping hooks keep working.

   Nothing here touches the display: the board still receives the same rep
   rows it always has, so themes, table formatting and the number-size
   controls are unaffected by whichever report feeds them. */
(function(){
  const CARD=`
    <div class="card" id="v90SourceCard">
      <h2>Tableau Report</h2>
      <div class="small">Choose one report, map it, verify the numbers, then save it.
        The saved report is the source used by every automatic refresh.</div>

      <div style="margin-top:12px;padding:12px;border:1px solid #2b2b2b;border-radius:6px">
        <div id="v79Current" class="small"></div>
        <div id="v97Schedule" class="small" style="margin-top:5px;opacity:.78">
          Automatic refresh: <strong>6:00 AM and 2:00 PM</strong> · Pi local time
        </div>
        <div id="v97LastRefresh" class="small" style="margin-top:3px;opacity:.68"></div>
      </div>

      <div style="margin-top:20px">
        <div class="small" style="opacity:.62;text-transform:uppercase;letter-spacing:.08em">Step 1</div>
        <h3 style="margin:3px 0 5px">Choose the report</h3>
        <div class="small">Pick a published workbook and report. Dashboard-only worksheets
          shown in Tableau's Download &gt; Crosstab menu must be published as a view before the Pi can pull them.</div>
        <div class="grid" style="margin-top:10px">
          <div>
            <label for="v79Workbook">Workbook</label>
            <select id="v79Workbook"><option value="">Loading…</option></select>
          </div>
          <div>
            <label for="v79Sheet">Report</label>
            <select id="v79Sheet"><option value="">Pick a workbook first</option></select>
          </div>
        </div>
        <div style="margin-top:10px">
          <label for="v90Export">Data to map</label>
          <select id="v90Export">
            <option value="auto">Automatic</option>
            <option value="csv">View data (CSV)</option>
            <option value="crosstab">Crosstab (Download &gt; Crosstab)</option>
          </select>
          <div id="v90ExportNote" class="small" style="margin-top:5px;opacity:.72"></div>
        </div>
        <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
          <button id="v79Load" class="btn primary" type="button">Read Report</button>
        </div>
        <div id="v79Status" class="small" style="margin-top:8px"></div>
      </div>

      <div id="v79MapWrap" style="display:none;margin-top:22px">
        <div class="small" style="opacity:.62;text-transform:uppercase;letter-spacing:.08em">Step 2</div>
        <h3 style="margin:3px 0 5px">Map the columns</h3>
        <div class="small">Choose which returned Tableau column feeds each leaderboard field.
          Example values are shown under the dropdowns. Nothing is saved yet.</div>
        <div id="v79MapRows" style="margin-top:10px"></div>
        <div id="v79Unmapped" class="small" style="margin-top:10px"></div>
      </div>

      <div style="margin-top:22px;padding-top:18px;border-top:1px solid #262626">
        <div class="small" style="opacity:.62;text-transform:uppercase;letter-spacing:.08em">Step 3</div>
        <h3 style="margin:3px 0 5px">Verify and activate</h3>
        <div class="small">Check the numbers first. After a clean check, <strong>Save for Auto Refresh</strong>
          activates this exact report for the 6 AM and 2 PM pulls and keeps it through restarts and updates.</div>
        <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
          <button id="v79Check" class="btn" type="button">Check The Numbers</button>
          <button id="v79PreviewTv" class="btn" type="button">Preview on TV</button>
          <button id="v79PreviewStop" class="btn" type="button">Stop Preview</button>
        </div>
        <div id="v79PreviewStatus" class="small" style="margin-top:8px"></div>
        <div id="v79PreviewRows" style="margin-top:8px"></div>
        <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
          <button id="v79Use" class="btn primary" type="button" disabled>Save for Auto Refresh</button>
        </div>
      </div>

      <details id="v97Advanced" style="margin-top:22px;padding-top:14px;border-top:1px solid #262626">
        <summary style="cursor:pointer;font-weight:600">Advanced source options</summary>
        <div class="small" style="margin-top:6px;opacity:.7">Only change these when the selected report needs them.</div>

        <h3 style="margin:16px 0 5px">Connection</h3>
        <div class="grid">
          <div><label for="v90Server">Server</label>
            <input id="v90Server" type="text" placeholder="Tableau server"></div>
          <div><label for="v90Site">Site</label>
            <input id="v90Site" type="text" placeholder="Site"></div>
          <div><label for="v90PatName">Token name</label>
            <input id="v90PatName" type="text" placeholder="Token name"></div>
        </div>
        <div class="small" style="margin-top:5px;opacity:.68">The PAT secret remains write-only in Tableau Data Source.</div>

        <h3 style="margin:16px 0 5px">Date range</h3>
        <label class="row" style="margin-bottom:6px">
          <input type="radio" name="v90DateMode" id="v90DateMonth" value="current_month">
          <span>Current calendar month, rolling</span></label>
        <label class="row">
          <input type="radio" name="v90DateMode" id="v90DateCustom" value="custom">
          <span>A range I choose</span></label>
        <div id="v90DateRow" class="grid" style="margin-top:10px;display:none">
          <div><label for="v90RangeStart">Start</label><input id="v90RangeStart" type="date"></div>
          <div><label for="v90RangeEnd">End</label><input id="v90RangeEnd" type="date"></div>
        </div>
        <div id="v90DateResolved" class="small" style="margin-top:7px;opacity:.72"></div>
        <div class="grid" style="margin-top:10px">
          <div><label for="v90DateStart">Start date field</label><input id="v90DateStart" type="text" placeholder="Optional"></div>
          <div><label for="v90DateEnd">End date field</label><input id="v90DateEnd" type="text" placeholder="Optional"></div>
        </div>

        <h3 style="margin:16px 0 5px">Tableau filters</h3>
        <div class="small">Leave empty to pull the report exactly as Tableau saved it.</div>
        <div id="v90Filters" style="margin-top:8px"></div>
        <button id="v90AddFilter" class="btn" type="button" style="margin-top:6px">Add Filter</button>

        <h3 style="margin:16px 0 5px">Keep only</h3>
        <div class="small">Optional safety check after Tableau returns the rows.</div>
        <div class="grid" style="margin-top:8px">
          <div><label for="v90KeepColumn">Column</label><select id="v90KeepColumn"></select></div>
          <div><label for="v90KeepValue">Value</label><input id="v90KeepValue" type="text" placeholder="Optional"></div>
        </div>

        <div style="margin-top:18px;padding-top:12px;border-top:1px solid #262626">
          <button id="v79Reset" class="btn danger" type="button">Clear Active Report</button>
          <div class="small" style="margin-top:5px;opacity:.68">This keeps the current leaderboard data but stops future Tableau pulls until another report is saved.</div>
        </div>
      </details>
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
      export:$("v90Export").value,
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
  function touched(){ proven=null; paintDates(); paintExport(); setUseEnabled(); }
  function setUseEnabled(){ $("v79Use").disabled=!(proven && same(proven,payload())); }

  const EXPORT_NOTE={
    auto:"Asks for the view's own data export, and only falls back to Crosstab "
        +"if that comes back with nothing.",
    csv:"Asks for the view's data export and nothing else. An empty answer is "
       +"reported rather than quietly swapped for the Crosstab.",
    crosstab:"Asks for the finished Crosstab table — the same one Download > "
            +"Crosstab gives you, one row per rep. Use this when the view's "
            +"data export combines worksheets.",
  };

  function paintExport(){
    $("v90ExportNote").textContent=EXPORT_NOTE[$("v90Export").value]||"";
  }

  async function paintScheduleState(){
    const el=$("v97LastRefresh");
    if(!el) return;
    try{
      const {r,d}=await request("/api/state",{cache:"no-store"});
      if(r.ok){
        el.textContent=d.last_source_refresh
          ? `Last successful Tableau pull: ${d.last_source_refresh}`
          : "No successful Tableau pull recorded yet.";
      }
    }catch(e){}
  }

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
    $("v90Export").value=source.export||"auto";
    paintExport();
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
      $("v79Current").innerHTML=(d.workbook&&d.sheet)
        ? `<strong>Active scheduled report:</strong> ${esc(d.workbook)} / ${esc(d.sheet)} · ${esc(d.export||"auto")}`
        : `<strong>No active report.</strong> Automatic refresh will keep the existing leaderboard data until you save one.`;
      fill(d, d.row_filter_columns);
      paintScheduleState();
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
        <input id="v79Workbook" type="text" value="${esc(workbook)}" placeholder="Workbook content URL"></div>
      <div><label for="v79Sheet">Sheet</label>
        <input id="v79Sheet" type="text" value="${esc(sheet)}" placeholder="Sheet content URL"></div>`;
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
    const sourceCard=$("v90SourceCard");
    const cards=[...app.querySelectorAll(":scope > .card")];
    const pullCard=cards.find(card=>card.querySelector("h2")?.textContent.trim()==="Pull Status");
    const tvCard=cards.find(card=>card.querySelector("h2")?.textContent.trim()==="TV Controls");
    if(pullCard&&tvCard&&tvCard.nextElementSibling!==pullCard) tvCard.insertAdjacentElement("afterend",pullCard);
    if(sourceCard&&pullCard&&pullCard.nextElementSibling!==sourceCard) pullCard.insertAdjacentElement("afterend",sourceCard);

    ["v90Server","v90Site","v90PatName","v90DateStart","v90DateEnd","v90KeepValue"]
      .forEach(id=>$(id).addEventListener("input",touched));
    $("v90KeepColumn").addEventListener("change",touched);
    $("v90Export").addEventListener("change",()=>{
      // The columns you map against depend on which export answers, so a
      // change here invalidates what is on screen.
      mapping=null; headers=[]; choices=[]; samples={}; paintMapping(); touched();
    });
    ["v90DateMonth","v90DateCustom","v90RangeStart","v90RangeEnd"]
      .forEach(id=>$(id).addEventListener("change",touched));
    $("v90AddFilter").addEventListener("click",()=>{
      filters.push({field:"",value:""}); paintFilters(); touched();
    });
    $("v79Workbook").addEventListener("change",()=>{touched();loadViews();});
    $("v79Sheet").addEventListener("change",()=>{
      mapping=null; headers=[]; choices=[]; samples={}; paintMapping(); touched();
      $("v79Status").textContent=$("v79Sheet").value
        ? "Report selected. Press Read Report to see the columns." : "";
    });
    $("v79Load").addEventListener("click",loadColumns);
    $("v79Check").addEventListener("click",()=>runPreview(false));
    $("v79PreviewTv").addEventListener("click",()=>runPreview(true));
    $("v79PreviewStop").addEventListener("click",stopPreview);
    $("v79Use").addEventListener("click",()=>{
      if(!proven) return;
      save(proven,"Saved for automatic refresh. This exact report will be used at 6:00 AM and 2:00 PM, and after restarts or updates.");
    });
    $("v79Reset").addEventListener("click",()=>{
      touched(); mapping=null; headers=[]; choices=[]; samples={}; paintMapping();
      $("v79PreviewRows").innerHTML=""; $("v79PreviewStatus").textContent="";
      stopPreview();
      $("v90DateMonth").checked=true; $("v90DateCustom").checked=false;
      $("v90RangeStart").value=""; $("v90RangeEnd").value=""; paintDates();
      const workbook=$("v79Workbook"), sheet=$("v79Sheet");
      if(workbook) workbook.value="";
      if(sheet&&sheet.tagName==="SELECT")
        sheet.innerHTML='<option value="">Pick a workbook first</option>';
      else if(sheet) sheet.value="";
      save({
        server:$("v90Server").value.trim(),
        site:$("v90Site").value.trim(),
        pat_name:$("v90PatName").value.trim(),
        workbook:"", sheet:"", export:"auto", filters:[],
        date_start_field:"", date_end_field:"", mapping:{},
        row_filter:{column:"",value:""},
        data_date_mode:"current_month",data_date_start:"",data_date_end:""
      }, "Active report cleared. Existing leaderboard data stays in place; automatic pulls wait until you save another report.");
    });

    paintCurrent().then(loadWorkbooks);
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
