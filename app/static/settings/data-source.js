/* Data source -- connecting to Tableau, choosing a report, mapping its
   columns, and the accordion those controls are arranged into.

   Consolidated from the settings patch stack. Each section below was its own
   file and they are concatenated in their original load order, so what runs
   when is unchanged -- several of these mount by polling for a node the
   previous one creates. */


/* ------------------------------------------------------------------
   data-source.js
   ------------------------------------------------------------------ */
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

      <div style="padding:8px 0 12px;border-bottom:1px solid #2b2b2b">
        <div id="v79Current" class="small"></div>
        <div class="small" style="margin-top:4px;opacity:.72">
          <span id="v97Schedule">Auto: <strong>6 AM · 2 PM</strong></span> ·
          <span id="v97LastRefresh"></span>
        </div>
      </div>

      <section style="margin-top:16px">
        <h3 style="margin:0 0 9px">1. Report</h3>
        <div class="grid">
          <div><label for="v79Workbook">Workbook</label><select id="v79Workbook"><option value="">Loading…</option></select></div>
          <div><label for="v79Sheet">Report</label><select id="v79Sheet"><option value="">Pick a workbook first</option></select></div>
        </div>
        <div style="margin-top:10px">
          <label for="v90Export">Export</label>
          <select id="v90Export">
            <option value="auto">Auto</option>
            <option value="csv">CSV</option>
            <option value="crosstab">Crosstab</option>
          </select>
          <div id="v90ExportNote" class="small" style="display:none"></div>
        </div>
        <div class="row" style="margin-top:10px"><button id="v79Load" class="btn primary" type="button">Read Report</button></div>
        <div id="v79Status" class="small" style="margin-top:7px"></div>
      </section>

      <div id="v79MapWrap" style="display:none;margin-top:18px;padding-top:15px;border-top:1px solid #262626">
        <h3 style="margin:0 0 8px">2. Map</h3>
        <div id="v79MapRows"></div>
        <div id="v79Unmapped" class="small" style="margin-top:7px"></div>
      </div>

      <section style="margin-top:18px;padding-top:15px;border-top:1px solid #262626">
        <h3 style="margin:0 0 8px">3. Verify</h3>
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <button id="v79Check" class="btn" type="button">Check Numbers</button>
          <button id="v79PreviewTv" class="btn" type="button">Preview TV</button>
          <button id="v79PreviewStop" class="btn" type="button">Stop</button>
        </div>
        <div id="v79PreviewStatus" class="small" style="margin-top:7px"></div>
        <div id="v79PreviewRows" style="margin-top:7px"></div>
        <div class="row" style="margin-top:10px"><button id="v79Use" class="btn primary" type="button" disabled>Save for Auto Refresh</button></div>
      </section>

      <details id="v97Advanced" style="margin-top:18px;padding-top:12px;border-top:1px solid #262626">
        <summary style="cursor:pointer;font-weight:700">Advanced</summary>

        <h3 style="margin:15px 0 6px">Connection</h3>
        <div class="grid">
          <div><label for="v90Server">Server</label><input id="v90Server" type="text" placeholder="Tableau server"></div>
          <div><label for="v90Site">Site</label><input id="v90Site" type="text" placeholder="Site"></div>
          <div><label for="v90PatName">Token name</label><input id="v90PatName" type="text" placeholder="Token name"></div>
        </div>

        <h3 style="margin:15px 0 6px">Date</h3>
        <label class="row" style="margin-bottom:6px"><input type="radio" name="v90DateMode" id="v90DateMonth" value="current_month"><span>Current month</span></label>
        <label class="row"><input type="radio" name="v90DateMode" id="v90DateCustom" value="custom"><span>Custom range</span></label>
        <div id="v90DateRow" class="grid" style="margin-top:9px;display:none">
          <div><label for="v90RangeStart">Start</label><input id="v90RangeStart" type="date"></div>
          <div><label for="v90RangeEnd">End</label><input id="v90RangeEnd" type="date"></div>
        </div>
        <div id="v90DateResolved" class="small" style="margin-top:6px;opacity:.72"></div>
        <div class="grid" style="margin-top:9px">
          <div><label for="v90DateStart">Start field</label><input id="v90DateStart" type="text" placeholder="Optional"></div>
          <div><label for="v90DateEnd">End field</label><input id="v90DateEnd" type="text" placeholder="Optional"></div>
        </div>

        <h3 style="margin:15px 0 6px">Report Filters</h3>
        <div id="v90Filters"></div>
        <button id="v90AddFilter" class="btn" type="button" style="margin-top:6px" disabled>Add Filter</button>

        <div style="margin-top:16px;padding-top:11px;border-top:1px solid #262626">
          <button id="v79Reset" class="btn danger" type="button">Clear Active Report</button>
        </div>
      </details>
    </div>`;

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  let proven=null;                       // the config that last pulled cleanly
  let headers=[], choices=[], samples={}, mapping=null, shape="";
  let filters=[], filterFields=[], defaults={};

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
      row_filter:{},
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
    $("v90DateResolved").textContent=bad ? "Fix the date range." : `${from} → ${to}`;
  }

  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  function touched(){ proven=null; paintDates(); paintExport(); setUseEnabled(); }
  function setUseEnabled(){ $("v79Use").disabled=!(proven && same(proven,payload())); }

  const EXPORT_NOTE={auto:"",csv:"",crosstab:""};

  function paintExport(){
    $("v90ExportNote").textContent=EXPORT_NOTE[$("v90Export").value]||"";
  }

  async function paintScheduleState(){
    const el=$("v97LastRefresh");
    if(!el) return;
    try{
      const {r,d}=await request("/api/state",{cache:"no-store"});
      if(r.ok){
        el.textContent=d.last_source_refresh?`Last: ${d.last_source_refresh}`:"Last: —";
      }
    }catch(e){}
  }

  function filterFieldOptions(selected){
    const fields=filterFields.map(f=>String(f.field||"")).filter(Boolean);
    if(selected&&!fields.includes(selected)) fields.unshift(selected);
    return '<option value="">Choose field…</option>'+fields.map(field=>
      `<option value="${esc(field)}"${field===selected?" selected":""}>${esc(field)}</option>`
    ).join("");
  }

  function filterValueControl(filter,index){
    const entry=filterFields.find(item=>item.field===filter.field);
    const values=(entry?.values||[]).map(value=>String(value));
    const current=String(filter.value||"");
    if(values.length&&!entry?.truncated){
      const known=values.slice();
      if(current&&!known.includes(current)) known.unshift(current);
      return `<select class="v100FValue" data-i="${index}" style="flex:1 1 auto">`+
        '<option value="">Choose value…</option>'+known.map(value=>
          `<option value="${esc(value)}"${value===current?" selected":""}>${esc(value)}</option>`
        ).join("")+`</select>`;
    }
    const placeholder=filter.field?(entry?.truncated?"Type exact value":"No values returned"):"Choose field first";
    return `<input class="v100FValue" data-i="${index}" type="text" value="${esc(current)}" `+
      `placeholder="${esc(placeholder)}" style="flex:1 1 auto">`;
  }

  function paintFilters(){
    const add=$("v90AddFilter");
    if(add) add.disabled=!filterFields.length;
    if(!filterFields.length){
      const saved=filters.filter(f=>f.field).map(f=>`${f.field}${f.value?` = ${f.value}`:""}`).join(" · ");
      $("v90Filters").innerHTML=`<div class="small">${saved?`Saved: ${esc(saved)} · `:""}Read Report to load filters.</div>`;
      return;
    }

    // A field absent from the selected report is stale configuration from a
    // different report. Do not silently send it to Tableau.
    filters=filters.filter(f=>filterFields.some(item=>item.field===f.field));
    $("v90Filters").innerHTML=filters.map((f,i)=>`
      <div class="row" style="gap:8px;align-items:center;margin-bottom:8px">
        <select class="v100FField" data-i="${i}" style="flex:1 1 auto">${filterFieldOptions(f.field)}</select>
        ${filterValueControl(f,i)}
        <button class="btn danger v100FDrop" data-i="${i}" type="button">Remove</button>
      </div>`).join("") || '<div class="small">No filters.</div>';

    $("v90Filters").querySelectorAll(".v100FField").forEach(el=>
      el.addEventListener("change",()=>{
        const i=Number(el.dataset.i);
        filters[i].field=el.value; filters[i].value=""; paintFilters(); touched();
      }));
    $("v90Filters").querySelectorAll(".v100FValue").forEach(el=>{
      const sync=()=>{filters[Number(el.dataset.i)].value=el.value;touched();};
      el.addEventListener("change",sync);
      if(el.tagName==="INPUT") el.addEventListener("input",sync);
    });
    $("v90Filters").querySelectorAll(".v100FDrop").forEach(el=>
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
    const note=!mapping.rep_name?"Rep not mapped. ":"";
    $("v79Unmapped").textContent=note+(left.length?`Unused: ${left.join(", ")}`:"");
  }

  async function loadColumns(){
    mapping=null; headers=[]; choices=[]; samples={}; filterFields=[]; paintMapping(); paintFilters();
    touched();
    $("v79PreviewRows").innerHTML=""; $("v79PreviewStatus").textContent="";
    $("v79Status").textContent="Reading…";
    try{
      const {r,d}=await request("/api/source/columns",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload())});
      if(!r.ok||!d.ok){$("v79Status").textContent=d.error||"Could not read that report.";return;}
      headers=d.headers||[]; choices=d.choices||[]; samples=d.samples||{}; shape=d.shape;
      filterFields=d.filter_fields||[];
      mapping=d.suggested||{}; mapping.metrics=mapping.metrics||{};
      paintMapping(); paintFilters();
      const matched=Object.keys(mapping.metrics).length;
      $("v79Status").textContent=`${d.export||""} · ${choices.length} columns`+(matched?` · ${matched} matched`:"");
    }catch(e){
      if(e.message!=="locked") $("v79Status").textContent="Could not reach the Pi.";
    }
  }

  function paintPreviewRows(rows){
    const wrap=$("v79PreviewRows");
    // Keep the report table inside the phone viewport. The table itself stays
    // at its natural width; the user pans across it instead of Safari shrinking
    // the whole settings page to make every metric fit at once.
    wrap.style.minWidth="0";
    wrap.style.width="100%";
    wrap.style.maxWidth="100%";
    wrap.style.overflow="hidden";
    if(!rows||!rows.length){wrap.innerHTML="";return;}
    const stats=statList().filter(([key])=>rows.some(r=>
      Object.prototype.hasOwnProperty.call(r,key)
      && r[key]!==null && r[key]!==undefined && r[key]!==""));
    const head=["Rep","Team",...stats.map(([,label])=>label)];
    const num=v=>typeof v==="number"
      ? v.toLocaleString(undefined,{maximumFractionDigits:2}) : String(v??"");
    const body=rows.map(rep=>
      `<tr>${[esc(rep.rep_name||""),esc(rep.team||"")]
        .concat(stats.map(([key])=>esc(num(rep[key]))))
        .map(c=>`<td style="padding:6px 12px 6px 0;white-space:nowrap">${c}</td>`).join("")}</tr>`).join("");
    wrap.innerHTML=`<div class="v101-number-preview" style="box-sizing:border-box;width:100%;max-width:100%;max-height:55vh;overflow:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y">
      <table class="small" style="border-collapse:collapse;width:max-content;min-width:max-content;white-space:nowrap">
      <tr>${head.map(h=>`<th style="position:sticky;top:0;z-index:2;background:#111;text-align:left;padding:6px 12px 6px 0;white-space:nowrap">${esc(h)}</th>`).join("")}</tr>
      ${body}</table></div>`;
  }

  async function runPreview(on_tv){
    const status=$("v79PreviewStatus");
    status.textContent="Pulling…";
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
      const scaled=(notes.scaled||[]).length?" · % formatted":"";
      status.textContent=`${d.reps} reps · ${d.start} → ${d.end} · ${notes.export||""}${cost}${scaled}`+(d.on_tv?" · TV preview active":"");
      paintPreviewRows(d.rows);
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }
  }

  async function stopPreview(){
    try{
      await request("/api/source/preview/stop",{method:"POST"});
      $("v79PreviewStatus").textContent="Preview stopped.";
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
    filterFields=[];
    filters=(source.filters||[]).map(f=>({field:f.field||"",value:f.value||""}));
    paintFilters();
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
        ? `<strong>Active:</strong> ${esc(d.workbook)} / ${esc(d.sheet)} · ${esc(d.export||"auto")}`
        : `<strong>No active report.</strong>`;
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
      (why?why+" ":"")+"Type workbook and report names.";
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

    ["v90Server","v90Site","v90PatName","v90DateStart","v90DateEnd"]
      .forEach(id=>$(id).addEventListener("input",touched));
    $("v90Export").addEventListener("change",()=>{
      // The columns you map against depend on which export answers, so a
      // change here invalidates what is on screen.
      mapping=null; headers=[]; choices=[]; samples={}; filterFields=[]; filters=[]; paintMapping(); paintFilters(); touched();
    });
    ["v90DateMonth","v90DateCustom","v90RangeStart","v90RangeEnd"]
      .forEach(id=>$(id).addEventListener("change",touched));
    $("v90AddFilter").addEventListener("click",()=>{
      if(!filterFields.length) return;
      const used=new Set(filters.map(f=>f.field));
      const next=filterFields.find(item=>!used.has(item.field))||filterFields[0];
      filters.push({field:next?.field||"",value:""}); paintFilters(); touched();
    });
    $("v79Workbook").addEventListener("change",()=>{
      filterFields=[]; filters=[]; paintFilters(); touched(); loadViews();
    });
    $("v79Sheet").addEventListener("change",()=>{
      mapping=null; headers=[]; choices=[]; samples={}; filterFields=[]; filters=[]; paintMapping(); paintFilters(); touched();
      $("v79Status").textContent=$("v79Sheet").value
        ? "Selected. Tap Read Report." : "";
    });
    $("v79Load").addEventListener("click",loadColumns);
    $("v79Check").addEventListener("click",()=>runPreview(false));
    $("v79PreviewTv").addEventListener("click",()=>runPreview(true));
    $("v79PreviewStop").addEventListener("click",stopPreview);
    $("v79Use").addEventListener("click",()=>{
      if(!proven) return;
      save(proven,"Saved for auto refresh · 6 AM / 2 PM.");
    });
    $("v79Reset").addEventListener("click",()=>{
      touched(); mapping=null; headers=[]; choices=[]; samples={}; filterFields=[]; filters=[]; paintMapping(); paintFilters();
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
      }, "Active report cleared.");
    });

    paintCurrent().then(loadWorkbooks);
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();


/* ------------------------------------------------------------------
   tableau-team-members.js
   ------------------------------------------------------------------ */
/* v126 Team Builder member availability.

   Tableau remains the source of candidate rep names, while Stats owns local
   team assignments. A rep can belong to only one local team at a time:
   - creating a team shows only unassigned Tableau reps;
   - editing a team shows its existing members plus unassigned reps;
   - reps assigned to any other team are hidden completely.

   Successful Tableau preview rows are merged with the persisted assignment
   metadata from /api/config before they reach the picker, so a fresh preview
   cannot accidentally make already-assigned people available again. */
(function(){
  if(typeof request!=="function" ||
     typeof renderBuilderMembers!=="function" ||
     typeof openTeamBuilder!=="function" ||
     typeof setBuilderStep!=="function") return;

  const memberList=document.getElementById("builderMembers");
  const overlay=document.getElementById("teamBuilderOverlay");
  if(!memberList||!overlay) return;

  const originalRequest=request;
  const originalRenderBuilderMembers=renderBuilderMembers;
  const originalOpenTeamBuilder=openTeamBuilder;
  const originalSetBuilderStep=setBuilderStep;

  let previewPool=null;
  let persistedPool=[];
  let refreshSequence=0;

  function repKeyFromName(name){
    return String(name||"")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g,"-")
      .replace(/^-+|-+$/g,"") || "unknown";
  }

  function normalizeRows(rows){
    const seen=new Set();
    return (Array.isArray(rows)?rows:[])
      .map(row=>{
        row=row&&typeof row==="object"?row:{};
        const rep_name=String(row.rep_name||row.name||"").trim();
        const rep_key=String(row.rep_key||repKeyFromName(rep_name)).trim();
        if(!rep_name||!rep_key||seen.has(rep_key)) return null;
        seen.add(rep_key);
        const tableau_team=String(row.tableau_team||row.team||"Unassigned").trim()||"Unassigned";
        const effective_team=String(row.effective_team||row.team||row.tableau_team||"Unassigned").trim()||"Unassigned";
        const assigned=Number(row.assigned_team_id||0);
        return {
          ...row,
          rep_key,
          rep_name,
          tableau_team,
          effective_team,
          // Only an explicit Pi assignment counts as occupied. Tableau's own
          // team text/effective fallback must never hide a candidate rep.
          assigned_team_id:assigned>0?assigned:null,
        };
      })
      .filter(Boolean)
      .sort((a,b)=>a.rep_name.localeCompare(b.rep_name));
  }

  function mergeAssignments(rows,persisted){
    const byKey=new Map();
    const byName=new Map();
    normalizeRows(persisted).forEach(rep=>{
      byKey.set(String(rep.rep_key),rep);
      byName.set(String(rep.rep_name||"").trim().toLowerCase(),rep);
    });
    return normalizeRows(rows).map(rep=>{
      const saved=byKey.get(String(rep.rep_key)) ||
        byName.get(String(rep.rep_name||"").trim().toLowerCase());
      if(!saved) return rep;
      const assigned=Number(saved.assigned_team_id||0);
      return {
        ...rep,
        assigned_team_id:assigned>0?assigned:null,
        effective_team:assigned>0
          ? String(saved.effective_team||rep.effective_team||"Unassigned")
          : rep.effective_team,
        local_team_override:!!saved.local_team_override,
      };
    });
  }

  function memberStepVisible(){
    return overlay.classList.contains("open") && Number(builderStep)===2;
  }

  function eligibleRows(rows){
    const current=Number(builderTeamId||0);
    return normalizeRows(rows).filter(rep=>{
      const assigned=Number(rep.assigned_team_id||0);
      return !assigned || (current>0 && assigned===current);
    });
  }

  function paintEmptyState(fullPool,eligible){
    if(eligible.length) return;
    const hasTableau=Array.isArray(fullPool)&&fullPool.length>0;
    memberList.innerHTML=hasTableau
      ? `<div class="small" id="tableauMemberEmptyV126" style="grid-column:1/-1;border:1px solid #2b2b2b;background:#0c0c0c;padding:14px;line-height:1.45">
          <strong style="color:var(--text)">No unassigned Tableau reps available.</strong><br>
          Everyone in the current Tableau pull is already assigned to another team.
        </div>`
      : `<div class="small" id="tableauMemberEmptyV126" style="grid-column:1/-1;border:1px solid #2b2b2b;background:#0c0c0c;padding:14px;line-height:1.45">
          <strong style="color:var(--text)">No Tableau reps loaded yet.</strong><br>
          Pull or preview a Tableau report first. The names from that Tableau data will appear here automatically.
        </div>`;
    const count=document.getElementById("selectedMemberCount");
    if(count) count.textContent=`${builderMembers.size} member${builderMembers.size===1?"":"s"}`;
  }

  function renderCurrentPool(){
    const full=Array.isArray(reps)?reps:[];
    const eligible=eligibleRows(full);
    // Reuse the established checklist/search renderer rather than introducing
    // a second membership UI. Restore the full pool immediately afterward so
    // review and Team Lead selection still resolve every selected member.
    reps=eligible;
    try{originalRenderBuilderMembers();}
    finally{reps=full;}
    paintEmptyState(full,eligible);
  }

  renderBuilderMembers=function(){renderCurrentPool();};

  function applyPool(rows){
    reps=normalizeRows(rows);
    if(memberStepVisible()) renderCurrentPool();
  }

  async function refreshPersistedPool(){
    const sequence=++refreshSequence;
    if(memberStepVisible() && (!Array.isArray(reps)||!reps.length)){
      memberList.innerHTML='<div class="small" style="grid-column:1/-1;padding:12px">Loading reps from Tableau…</div>';
    }
    try{
      const {r,d}=await originalRequest("/api/config",{cache:"no-store"});
      if(sequence!==refreshSequence||!r.ok) return;
      persistedPool=normalizeRows(d.reps||[]);
      const current=previewPool&&previewPool.length
        ?mergeAssignments(previewPool,persistedPool)
        :persistedPool;
      applyPool(current);
    }catch(_){
      if(sequence!==refreshSequence) return;
      if(memberStepVisible()) renderCurrentPool();
    }
  }

  request=async function(path,options={}){
    const result=await originalRequest(path,options);
    const cleanPath=String(path||"").split("?",1)[0];

    if(cleanPath==="/api/source/preview" &&
       result?.r?.ok && result?.d?.ok && Array.isArray(result.d.rows)){
      previewPool=normalizeRows(result.d.rows);
      applyPool(mergeAssignments(previewPool,persistedPool));
      // Re-read Pi-owned assignments after the preview so even a Settings page
      // that was open for hours cannot offer somebody already claimed elsewhere.
      setTimeout(refreshPersistedPool,0);
      window.dispatchEvent(new CustomEvent("stats-tableau-reps-updated",{
        detail:{source:"preview",count:previewPool.length}
      }));
    }

    if(cleanPath==="/api/source/refresh" && result?.r?.ok){
      previewPool=null;
      setTimeout(refreshPersistedPool,0);
    }

    return result;
  };

  openTeamBuilder=function(id=null){
    originalOpenTeamBuilder(id);
    refreshPersistedPool();
  };

  setBuilderStep=function(n){
    originalSetBuilderStep(n);
    if(Number(builderStep)===2) refreshPersistedPool();
  };

  if(!Array.isArray(reps)||!reps.length) paintEmptyState([],[]);
})();


/* ------------------------------------------------------------------
   windows-tableau-login.js
   ------------------------------------------------------------------ */
/* v124 Windows Tableau Login layout.
   Move the existing connection inputs out of Tableau Report > Advanced and
   into the existing Tableau Login dialog. The same DOM inputs and config APIs
   are reused so report discovery/mapping logic keeps one source of truth. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  let mounted=false;
  let wrapped=false;

  function addStyles(){
    if(document.getElementById("windowsTableauLoginV124Styles"))return;
    const style=document.createElement("style");
    style.id="windowsTableauLoginV124Styles";
    style.textContent=`
      #dataSourceOverlay .tableau-login-note{margin:8px 0 18px;color:var(--muted);font-size:13px;line-height:1.45}
      #dataSourceOverlay .tableau-login-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px}
      #dataSourceOverlay .tableau-login-grid .tableau-login-wide{grid-column:1/-1}
      #dataSourceOverlay .tableau-login-secret{margin-top:14px}
      #dataSourceOverlay .tableau-login-actions{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;margin-top:16px}
      #dataSourceOverlay #testDataSource{min-width:132px}
      @media(max-width:720px){#dataSourceOverlay .tableau-login-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function connectionValues(){
    return {
      server:String(document.getElementById("v90Server")?.value||"").trim(),
      site:String(document.getElementById("v90Site")?.value||"").trim(),
      pat_name:String(document.getElementById("v90PatName")?.value||"").trim(),
    };
  }

  function mount(){
    if(mounted)return true;
    const overlay=document.getElementById("dataSourceOverlay");
    const panel=overlay?.querySelector(".panel");
    const server=document.getElementById("v90Server");
    const site=document.getElementById("v90Site");
    const patName=document.getElementById("v90PatName");
    const secret=document.getElementById("tabPatSecret");
    const save=document.getElementById("saveDataSource");
    if(!panel||!server||!site||!patName||!secret||!save)return false;

    addStyles();
    mounted=true;

    const oldGrid=server.closest(".grid");
    const oldHeading=oldGrid?.previousElementSibling?.tagName==="H3"?oldGrid.previousElementSibling:null;

    const header=panel.querySelector(":scope > .row");
    const note=document.createElement("div");
    note.className="tableau-login-note";
    note.textContent="These credentials control the Tableau connection. Report, mapping, filters and dates are configured separately in Tableau Report.";
    header?.insertAdjacentElement("afterend",note);

    const grid=document.createElement("div");
    grid.id="tableauLoginConnectionV124";
    grid.className="tableau-login-grid";
    [server,site,patName].forEach(input=>{
      const field=input.parentElement;
      if(field)grid.appendChild(field);
    });
    note.insertAdjacentElement("afterend",grid);

    const secretHeading=secret.previousElementSibling;
    if(secretHeading?.tagName==="H3"){
      secretHeading.textContent="PAT secret";
      secretHeading.classList.add("tableau-login-secret");
    }

    if(oldGrid&&oldGrid.children.length===0)oldGrid.remove();
    if(oldHeading)oldHeading.remove();

    const originalActions=save.parentElement;
    originalActions?.classList.add("tableau-login-actions");
    if(originalActions)originalActions.style.justifyContent="flex-end";

    const test=document.createElement("button");
    test.id="testDataSource";
    test.className="btn";
    test.type="button";
    test.textContent="Test Connection";
    test.addEventListener("click",testConnection);
    originalActions?.insertBefore(test,save);

    wrapExistingLoginFunctions();
    applyDataSourceForm();
    return true;
  }

  function wrapExistingLoginFunctions(){
    if(wrapped)return;
    wrapped=true;

    const previousApply=applyDataSourceForm;
    applyDataSourceForm=function(){
      previousApply();
      const source=(config&&config.source&&typeof config.source==="object")?config.source:{};
      const server=document.getElementById("v90Server");
      const site=document.getElementById("v90Site");
      const patName=document.getElementById("v90PatName");
      if(server&&source.server!==undefined)server.value=source.server||"";
      if(site&&source.site!==undefined)site.value=source.site||"";
      if(patName&&source.pat_name!==undefined)patName.value=source.pat_name||"";
    };

    collectDataSource=function(){
      const values=connectionValues();
      const current=(config&&config.source&&typeof config.source==="object")?config.source:{};
      const payload={source:{...current,...values}};
      const secret=String(document.getElementById("tabPatSecret")?.value||"").trim();
      if(secret)payload.tableau_pat_secret=secret;
      return payload;
    };

    const previousSave=saveDataSource;
    saveDataSource=async function(closeAfter=false){
      const ok=await previousSave(false);
      if(!ok)return false;
      try{window.config=config;}catch(_){ }
      window.dispatchEvent(new CustomEvent("stats-tableau-login-saved",{detail:connectionValues()}));
      const status=document.getElementById("dataSourceStatus");
      if(status)status.textContent=closeAfter?"Login saved. Refreshing Tableau Report…":"Login saved.";
      if(closeAfter)setTimeout(()=>location.reload(),450);
      return true;
    };
  }

  async function testConnection(){
    const status=document.getElementById("dataSourceStatus");
    const test=document.getElementById("testDataSource");
    const save=document.getElementById("saveDataSource");
    const values=connectionValues();
    const pat_secret=String(document.getElementById("tabPatSecret")?.value||"").trim();
    if(!values.server||!values.site||!values.pat_name){
      if(status)status.textContent="Enter Server, Site and PAT Token Name first.";
      return;
    }
    if(status)status.textContent="Testing Tableau login…";
    if(test)test.disabled=true;
    if(save)save.disabled=true;
    try{
      const {r,d}=await request("/api/windows/tableau-login/test",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...values,pat_secret})
      });
      if(status){
        status.classList.toggle("ok",!!r.ok&&!!d.ok);
        status.textContent=(r.ok&&d.ok)?"Connection successful.":(d.error||"Connection failed.");
      }
    }catch(e){
      if(e.message!=="locked"&&status)status.textContent="Could not test the Tableau connection.";
    }finally{
      if(test)test.disabled=false;
      if(save)save.disabled=false;
    }
  }

  function boot(){
    if(mount())return;
    const observer=new MutationObserver(()=>{if(mount())observer.disconnect();});
    observer.observe(document.documentElement,{childList:true,subtree:true});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();


/* ------------------------------------------------------------------
   flow.js
   ------------------------------------------------------------------ */
/* v102 Tableau settings workflow.
   UX ONLY: keep the report setup in dependency order.
   - Read Report first.
   - Report Filters appear immediately after Read Report.
   - Everything else that lived under Advanced moves into Tableau Login.
   Existing DOM nodes are moved intact so current listeners and API behavior stay unchanged. */
(function(){
  const $=id=>document.getElementById(id);

  function setStepHeading(container,text){
    const heading=container?.querySelector('h3');
    if(heading) heading.textContent=text;
  }

  function organize(){
    const source=$('v90SourceCard');
    const advanced=$('v97Advanced');
    const loginPanel=$('dataSourceOverlay')?.querySelector('.panel');
    const readButton=$('v79Load');
    const filtersWrap=$('v90Filters');
    const addFilter=$('v90AddFilter');
    if(!source||!advanced||!loginPanel||!readButton||!filtersWrap||!addFilter) return false;
    if($('v102FiltersStep')) return true;

    const reportSection=readButton.closest('section');
    const mapWrap=$('v79MapWrap');
    if(!reportSection||!mapWrap) return false;

    // Filters depend on Read Report, so make them the next visible step.
    const filterHeading=Array.from(advanced.querySelectorAll(':scope > h3'))
      .find(h=>/report filters/i.test(h.textContent||''));
    if(filterHeading) filterHeading.remove();

    const filterSection=document.createElement('section');
    filterSection.id='v102FiltersStep';
    filterSection.style.cssText='margin-top:18px;padding-top:15px;border-top:1px solid #262626';
    filterSection.innerHTML='<h3 style="margin:0 0 8px">2. Filters</h3><div class="small" style="margin-bottom:9px">Read Report first, then choose the report filters to send to Tableau.</div>';
    filterSection.append(filtersWrap,addFilter);
    reportSection.insertAdjacentElement('afterend',filterSection);

    // Renumber the remaining report flow so the screen matches the real dependency order.
    setStepHeading(mapWrap,'3. Map');
    const verifySection=$('v79Check')?.closest('section');
    setStepHeading(verifySection,'4. Verify');

    // Move every remaining Advanced control into the existing Tableau Login overlay.
    const loginExtras=document.createElement('section');
    loginExtras.id='v102LoginExtras';
    loginExtras.style.cssText='margin-top:18px;padding-top:15px;border-top:1px solid #2b2b2b';
    const note=document.createElement('div');
    note.className='small';
    note.style.marginBottom='10px';
    note.textContent='Connection and date defaults for this Tableau source.';
    loginExtras.appendChild(note);

    Array.from(advanced.children).forEach(node=>{
      if(node.tagName==='SUMMARY') return;
      loginExtras.appendChild(node);
    });

    const status=$('dataSourceStatus');
    if(status) loginPanel.insertBefore(loginExtras,status);
    else loginPanel.appendChild(loginExtras);
    advanced.remove();

    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(organize()) return;
      if(++tries<50) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();


/* ------------------------------------------------------------------
   accordion.js
   ------------------------------------------------------------------ */
/* v98 remote settings accordion.
   UX ONLY: moves existing controls into clearer collapsible groups without
   changing any API calls, source logic, scheduler behavior, team logic, or TV
   rendering. Existing DOM nodes are moved intact so their event listeners and
   saved settings behavior stay exactly as shipped. */
(function(){
  const $=id=>document.getElementById(id);
  const app=()=>$("appWrap");
  const STATE_KEY="leaderboard.settings.v98.open";
  let state={};
  try{ state=JSON.parse(localStorage.getItem(STATE_KEY)||"{}"); }catch(_){ state={}; }

  function saveState(){
    try{ localStorage.setItem(STATE_KEY,JSON.stringify(state)); }catch(_){ }
  }

  function injectStyles(){
    if($("v98AccordionStyles")) return;
    const style=document.createElement("style");
    style.id="v98AccordionStyles";
    style.textContent=`
      #v98Sections{display:grid;gap:10px;margin-top:14px}
      .v98-section{background:var(--card);border:1px solid var(--line);margin:0}
      .v98-section>summary,.v98-subsection>summary{
        list-style:none;cursor:pointer;user-select:none;display:flex;align-items:center;
        justify-content:space-between;gap:12px;font-weight:900
      }
      .v98-section>summary::-webkit-details-marker,.v98-subsection>summary::-webkit-details-marker{display:none}
      .v98-section>summary{font-size:19px;padding:15px 17px}
      .v98-section>summary::after,.v98-subsection>summary::after{
        content:"+";font-size:22px;line-height:1;color:var(--muted);font-weight:400
      }
      .v98-section[open]>summary::after,.v98-subsection[open]>summary::after{content:"−"}
      .v98-section[open]>summary{border-bottom:1px solid var(--line)}
      .v98-section-body{padding:16px 17px 18px}
      .v98-inner-card{margin:0!important;padding:0!important;border:0!important;background:transparent!important}
      .v98-inner-card>h2:first-child{display:none!important}
      .v98-subsection{border:1px solid #2b2b2b;background:#101010;margin:10px 0}
      .v98-subsection>summary{padding:11px 12px;font-size:15px}
      .v98-subsection[open]>summary{border-bottom:1px solid #292929}
      .v98-subsection-body{padding:12px}
      .v98-inline-block{margin:10px 0;padding:10px;border:1px solid #2b2b2b;background:#101010}
      .v98-inline-block>h3{margin:0 0 8px}
      .v98-view-mode{margin-bottom:10px}
      .v98-view-help{margin:0 0 12px}
      .v98-save-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px;padding-top:12px;border-top:1px solid #262626}
      #v98LegacyModeCard{display:none!important}
      @media(max-width:760px){
        #v98Sections{gap:8px}
        .v98-section>summary{padding:14px 13px;font-size:18px}
        .v98-section-body{padding:13px}
      }
    `;
    document.head.appendChild(style);
  }

  function keyOf(label){
    return String(label||"section").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")||"section";
  }

  function buildDetails(label,key,sub=false){
    const details=document.createElement("details");
    details.className=sub?"v98-subsection":"v98-section";
    details.dataset.v98Key=key;
    details.open=!!state[key];
    const summary=document.createElement("summary");
    summary.textContent=label;
    const body=document.createElement("div");
    body.className=sub?"v98-subsection-body":"v98-section-body";
    details.append(summary,body);
    details.addEventListener("toggle",()=>{state[key]=details.open;saveState();});
    return {details,body};
  }

  function directCards(){
    const root=app();
    if(!root) return [];
    return Array.from(root.children).filter(el=>el.classList&&el.classList.contains("card"));
  }

  function directCardWith(selector){
    return directCards().find(card=>card.querySelector(selector))||null;
  }

  function headingOf(card){
    return String(card?.querySelector("h2")?.textContent||"").replace(/\s+/g," ").trim();
  }

  function putCardInBody(card,body){
    if(!card||!body) return;
    card.classList.remove("card");
    card.classList.add("v98-inner-card");
    body.appendChild(card);
  }

  function wrapSimpleCard(card,label,stack){
    if(!card||card.dataset.v98Wrapped) return null;
    const key=keyOf(label);
    const {details,body}=buildDetails(label,key,false);
    card.dataset.v98Wrapped="1";
    putCardInBody(card,body);
    stack.appendChild(details);
    return details;
  }

  function makeNestedCard(card,label,key,parentBody){
    if(!card) return null;
    const {details,body}=buildDetails(label,key,true);
    putCardInBody(card,body);
    parentBody.appendChild(details);
    return details;
  }

  function prepareView(stack){
    const displayCard=directCardWith("#displaySettingsTitle");
    const modeCard=directCardWith("#activeMode");
    if(!displayCard) return null;

    const {details,body}=buildDetails("View","view",false);

    if(modeCard){
      modeCard.id="v98LegacyModeCard";
      const active=$("activeMode");
      const field=active?.parentElement;
      if(field){
        field.classList.add("v98-view-mode");
        body.appendChild(field);
      }
      const help=$("activeModeHelp");
      if(help){ help.classList.add("v98-view-help"); body.appendChild(help); }
    }

    const filters=buildDetails("Filters","view-filters",true);
    const shownHeading=Array.from(displayCard.querySelectorAll("h3"))
      .find(h=>/data shown on tv/i.test(h.textContent||""));
    if(shownHeading) shownHeading.textContent="Fields shown on TV";
    putCardInBody(displayCard,filters.body);
    body.appendChild(filters.details);

    const numCard=directCardWith("#v75NumCard")||$("v75NumCard");
    if(numCard) makeNestedCard(numCard,"Number Size","view-number-size",body);

    const actions=document.querySelector("#appWrap > .actions");
    const save=$("save"), saved=$("saved");
    if(save||saved){
      const row=document.createElement("div");
      row.className="v98-save-row";
      if(save){ save.textContent="Save View"; row.appendChild(save); }
      if(saved) row.appendChild(saved);
      body.appendChild(row);
    }

    stack.appendChild(details);
    return {details,actions};
  }

  function prepareTv(stack,actions){
    const tvCard=directCards().find(card=>/TV Controls/i.test(headingOf(card)))||directCardWith("#refreshTV");
    if(!tvCard) return null;
    const openTv=$("openTV");
    if(openTv){
      openTv.textContent="Open TV View";
      const row=tvCard.querySelector(".row")||tvCard;
      row.appendChild(openTv);
    }
    const wrapped=wrapSimpleCard(tvCard,"TV Remote",stack);
    if(actions && !actions.querySelector("button")) actions.style.display="none";
    return wrapped;
  }

  function prepareTeam(stack){
    const card=directCards().find(card=>/Team Builder/i.test(headingOf(card)))||directCardWith("#newTeamBuilder");
    return wrapSimpleCard(card,"Team Builder",stack);
  }

  function movePullStatusIntoReport(sourceCard){
    if(!sourceCard||$("v98PullStatus")) return;
    const pullCard=directCardWith("#sourceStatusLine");
    if(!pullCard) return;
    const block=document.createElement("section");
    block.id="v98PullStatus";
    block.className="v98-inline-block";
    const h=document.createElement("h3");
    h.textContent="Status";
    block.appendChild(h);
    Array.from(pullCard.childNodes).forEach(node=>{
      if(node.nodeType===1 && node.tagName==="H2") return;
      block.appendChild(node);
    });
    const current=$("v79Current");
    const scheduleBox=current?.parentElement;
    if(scheduleBox&&scheduleBox.parentElement===sourceCard) scheduleBox.insertAdjacentElement("afterend",block);
    else sourceCard.insertBefore(block,sourceCard.children[2]||null);
    pullCard.remove();
  }

  function prepareData(stack){
    const sourceCard=$("v90SourceCard");
    if(!sourceCard) return null;
    movePullStatusIntoReport(sourceCard);

    const {details,body}=buildDetails("Data","data",false);
    makeNestedCard(sourceCard,"Tableau Report","data-tableau-report",body);

    const product=$("v75ProductCard");
    if(product) makeNestedCard(product,"Close Rate by Product — Beta","data-product",body);

    stack.appendChild(details);
    return details;
  }

  function organize(){
    const root=app();
    if(!root||$("v98Sections")) return !!$("v98Sections");
    const source=$("v90SourceCard");
    if(!source) return false; // wait until the v97 report card has mounted

    injectStyles();
    const stack=document.createElement("div");
    stack.id="v98Sections";
    const note=root.querySelector(".persist-note");
    if(note) note.insertAdjacentElement("afterend",stack); else root.prepend(stack);

    const view=prepareView(stack);
    prepareTv(stack,view?.actions||null);
    prepareTeam(stack);
    prepareData(stack);

    // Everything else remains functionally untouched, but gets the same
    // collapsible shell so the phone page stays compact.
    const leftovers=directCards().filter(card=>card.id!=="v98LegacyModeCard");
    leftovers.forEach(card=>{
      const raw=headingOf(card)||"Settings";
      let label=raw;
      if(/Software Update/i.test(raw)) label="Software";
      else if(/Settings Lock/i.test(raw)) label="Security";
      wrapSimpleCard(card,label,stack);
    });

    const actions=document.querySelector("#appWrap > .actions");
    if(actions && !actions.querySelector("button")) actions.style.display="none";
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(organize()) return;
      if(++tries<40) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();


/* ------------------------------------------------------------------
   preview-scroll.js
   ------------------------------------------------------------------ */
/* v103 iPhone settings preview containment.
   The Check Numbers table is intentionally wider than the phone, but that
   intrinsic width must never widen the settings page itself. Only the preview
   shell may scroll horizontally. */
(function(){
  function install(){
    if(document.getElementById('v103PreviewContainment')) return;
    const style=document.createElement('style');
    style.id='v103PreviewContainment';
    style.textContent=`
      html,body{
        max-width:100%;
        overflow-x:hidden;
      }
      #appWrap,
      #v98Sections,
      .v98-section,
      .v98-section-body,
      .v98-subsection,
      .v98-subsection-body,
      #v90SourceCard,
      #v90SourceCard>section,
      #v79PreviewRows{
        min-width:0!important;
        max-width:100%!important;
      }
      #v79PreviewRows{
        width:100%!important;
        overflow:hidden!important;
      }
      #v79PreviewRows>.v101-number-preview{
        box-sizing:border-box!important;
        display:block!important;
        width:100%!important;
        min-width:0!important;
        max-width:100%!important;
        overflow-x:auto!important;
        overflow-y:auto!important;
        overscroll-behavior:contain;
        -webkit-overflow-scrolling:touch;
        touch-action:pan-x pan-y;
        contain:inline-size;
      }
      #v79PreviewRows>.v101-number-preview>table{
        width:max-content!important;
        min-width:max-content!important;
        max-width:none!important;
      }
    `;
    document.head.appendChild(style);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install,{once:true});
  else install();
})();


/* ------------------------------------------------------------------
   date-filter.js
   ------------------------------------------------------------------ */
/* v104: Date belongs with report filters, not Tableau login.
   UX ONLY. Move the existing date controls after v102 has organized the page.
   Existing DOM nodes keep their event listeners and saved-setting behavior. */
(function(){
  const $=id=>document.getElementById(id);

  function organize(){
    const filtersStep=$('v102FiltersStep');
    const loginExtras=$('v102LoginExtras');
    if(!filtersStep||!loginExtras) return false;
    if($('v104DateFilters')) return true;

    const month=$('v90DateMonth')?.closest('label');
    const custom=$('v90DateCustom')?.closest('label');
    const range=$('v90DateRow');
    const resolved=$('v90DateResolved');
    const fields=$('v90DateStart')?.closest('.grid');
    if(!month||!custom||!range||!resolved||!fields) return false;

    // Remove the old Date heading from Tableau Login.
    const dateHeading=Array.from(loginExtras.querySelectorAll('h3'))
      .find(h=>/^date$/i.test((h.textContent||'').trim()));
    if(dateHeading) dateHeading.remove();

    const dateBlock=document.createElement('div');
    dateBlock.id='v104DateFilters';
    dateBlock.style.cssText='margin:12px 0 15px;padding-bottom:15px;border-bottom:1px solid #262626';

    const heading=document.createElement('h4');
    heading.textContent='Date';
    heading.style.margin='0 0 8px';
    dateBlock.append(heading,month,custom,range,resolved,fields);

    const reportFilters=$('v90Filters');
    if(reportFilters) filtersStep.insertBefore(dateBlock,reportFilters);
    else filtersStep.appendChild(dateBlock);

    const help=filtersStep.querySelector('.small');
    if(help) help.textContent='Set the date window, then choose report filters loaded by Read Report.';

    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(organize()) return;
      if(++tries<60) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();


/* ------------------------------------------------------------------
   date-simple.js
   ------------------------------------------------------------------ */
/* v106: the date picker is the only date setup the user sees.
   Tableau's Start / End filter keys are internal implementation details.
   Keep the legacy hidden controls pinned to those standard keys so existing
   preview/save logic continues to work without exposing a mapping UI. */
(function(){
  const $=id=>document.getElementById(id);

  function install(){
    const startField=$('v90DateStart');
    const endField=$('v90DateEnd');
    if(!startField||!endField) return false;

    startField.value='Start';
    endField.value='End';

    const legacyGrid=startField.closest('.grid');
    if(legacyGrid) legacyGrid.style.display='none';

    // Clean up any v105 UI if a cached page happened to create it.
    $('v105DateFieldChooser')?.remove();
    $('v105DateFieldStatus')?.remove();

    // Existing preview/save code listens to these hidden controls.
    startField.dispatchEvent(new Event('input',{bubbles:true}));
    endField.dispatchEvent(new Event('input',{bubbles:true}));
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(install()) return;
      if(++tries<80) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
