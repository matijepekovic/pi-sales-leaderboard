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
