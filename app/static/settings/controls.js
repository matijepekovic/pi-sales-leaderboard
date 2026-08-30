/* Controls -- TV controls, the QR overlay, and the temporary date window.

   Consolidated from the settings patch stack. Each section below was its own
   file and they are concatenated in their original load order, so what runs
   when is unchanged -- several of these mount by polling for a node the
   previous one creates. */


/* ------------------------------------------------------------------
   qr.js
   ------------------------------------------------------------------ */
/* v110 remote: dedicated QR Code section with drag-to-position + size control. */
(function(){
  const DEFAULT={size:68,x:100,y:0};
  const MIN_SIZE=36,MAX_SIZE=180;
  let value={...DEFAULT};
  let stage=null,qr=null,sizeInput=null,sizeValue=null,status=null;
  let dragging=false,pointerId=null;

  const $=id=>document.getElementById(id);
  const clamp=(v,a,b)=>Math.min(b,Math.max(a,Number(v)||0));

  function styles(){
    if($('v110QrStyles')) return;
    const style=document.createElement('style');
    style.id='v110QrStyles';
    style.textContent=`
      #v110QrStage{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;
        border:1px solid #353535;background:#080808;
        background-image:linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px),
                         linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px);
        background-size:10% 10%;touch-action:none;user-select:none}
      #v110QrPreview{position:absolute;box-sizing:border-box;padding:3px;background:#fff;
        border-radius:4px;box-shadow:0 0 0 1px rgba(0,0,0,.4);cursor:grab;touch-action:none;line-height:0}
      #v110QrPreview.dragging{cursor:grabbing}
      #v110QrPreview img{display:block;width:100%;height:100%}
      #v110QrSize{padding:0;accent-color:var(--accent)}
      .v110-qr-nudges{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:10px}
      .v110-qr-nudges .btn{min-height:44px;padding:8px}
      .v110-qr-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
      .v110-qr-actions .btn{flex:1 1 150px;min-height:46px}
    `;
    document.head.appendChild(style);
  }

  function makeSection(){
    const stack=$('v98Sections');
    if(!stack||$('v110QrSection')) return !!$('v110QrSection');
    styles();

    const section=document.createElement('details');
    section.id='v110QrSection';
    section.className='v98-section';
    section.innerHTML=`
      <summary>QR Code</summary>
      <div class="v98-section-body">
        <div class="small" style="margin-bottom:10px">Drag the QR anywhere on the TV preview, then set its size.</div>
        <div id="v110QrStage" aria-label="QR position preview">
          <div id="v110QrPreview" role="img" aria-label="QR code position"><img src="/static/remote-qr-v109.svg?v=109" alt=""></div>
        </div>
        <div style="margin-top:14px">
          <div class="row" style="justify-content:space-between"><label for="v110QrSize" style="margin:0">Size</label><strong id="v110QrSizeValue">68 px</strong></div>
          <input id="v110QrSize" type="range" min="${MIN_SIZE}" max="${MAX_SIZE}" step="1" value="68">
        </div>
        <div class="v110-qr-nudges">
          <button class="btn" type="button" data-qr-nudge="left">←</button>
          <button class="btn" type="button" data-qr-nudge="up">↑</button>
          <button class="btn" type="button" data-qr-nudge="down">↓</button>
          <button class="btn" type="button" data-qr-nudge="right">→</button>
        </div>
        <div class="v110-qr-actions">
          <button id="v110QrReset" class="btn" type="button">Reset Top Right</button>
          <button id="v110QrSave" class="btn primary" type="button">Save QR</button>
        </div>
        <div id="v110QrStatus" class="small" style="margin-top:10px"></div>
      </div>`;

    const tvSection=Array.from(stack.querySelectorAll(':scope > .v98-section')).find(el=>
      String(el.querySelector(':scope > summary')?.textContent||'').trim()==='TV Remote'
    );
    if(tvSection) tvSection.insertAdjacentElement('afterend',section);
    else stack.appendChild(section);

    stage=$('v110QrStage');
    qr=$('v110QrPreview');
    sizeInput=$('v110QrSize');
    sizeValue=$('v110QrSizeValue');
    status=$('v110QrStatus');

    sizeInput.addEventListener('input',()=>{
      value.size=clamp(sizeInput.value,MIN_SIZE,MAX_SIZE);
      draw();
    });

    qr.addEventListener('pointerdown',e=>{
      dragging=true;pointerId=e.pointerId;qr.setPointerCapture(pointerId);
      qr.classList.add('dragging');
      moveFromPointer(e);
    });
    qr.addEventListener('pointermove',e=>{if(dragging&&e.pointerId===pointerId) moveFromPointer(e);});
    const stop=e=>{
      if(e.pointerId!==pointerId) return;
      dragging=false;pointerId=null;qr.classList.remove('dragging');
    };
    qr.addEventListener('pointerup',stop);
    qr.addEventListener('pointercancel',stop);

    section.querySelectorAll('[data-qr-nudge]').forEach(button=>button.addEventListener('click',()=>{
      const dir=button.dataset.qrNudge;
      if(dir==='left') value.x-=2;
      if(dir==='right') value.x+=2;
      if(dir==='up') value.y-=2;
      if(dir==='down') value.y+=2;
      value.x=clamp(value.x,0,100);value.y=clamp(value.y,0,100);draw();
    }));

    $('v110QrReset').addEventListener('click',()=>{value={...DEFAULT};draw();status.textContent='Top-right default restored. Press Save QR.';});
    $('v110QrSave').addEventListener('click',save);
    window.addEventListener('resize',draw);
    load();
    return true;
  }

  function previewSize(){
    if(!stage) return 18;
    const scale=Math.max(.12,stage.clientWidth/1920);
    return Math.max(16,Math.min(stage.clientWidth*.25,value.size*scale));
  }

  function draw(){
    if(!stage||!qr) return;
    value.size=clamp(value.size,MIN_SIZE,MAX_SIZE);
    value.x=clamp(value.x,0,100);value.y=clamp(value.y,0,100);
    const size=previewSize();
    const travelX=Math.max(0,stage.clientWidth-size);
    const travelY=Math.max(0,stage.clientHeight-size);
    qr.style.width=`${size}px`;
    qr.style.height=`${size}px`;
    qr.style.left=`${travelX*value.x/100}px`;
    qr.style.top=`${travelY*value.y/100}px`;
    if(sizeInput) sizeInput.value=String(Math.round(value.size));
    if(sizeValue) sizeValue.textContent=`${Math.round(value.size)} px`;
  }

  function moveFromPointer(e){
    const rect=stage.getBoundingClientRect();
    const size=qr.getBoundingClientRect().width;
    const travelX=Math.max(1,rect.width-size);
    const travelY=Math.max(1,rect.height-size);
    const left=clamp(e.clientX-rect.left-size/2,0,travelX);
    const top=clamp(e.clientY-rect.top-size/2,0,travelY);
    value.x=left/travelX*100;
    value.y=top/travelY*100;
    draw();
  }

  async function load(){
    try{
      const response=await fetch('/api/config',{cache:'no-store'});
      if(!response.ok) throw new Error('Could not load QR settings.');
      const data=await response.json();
      const settings=data.settings||{};
      value={
        size:clamp(settings.qr_overlay_size??DEFAULT.size,MIN_SIZE,MAX_SIZE),
        x:clamp(settings.qr_overlay_x??DEFAULT.x,0,100),
        y:clamp(settings.qr_overlay_y??DEFAULT.y,0,100)
      };
      draw();
    }catch(e){
      if(status) status.textContent=e.message||'Could not load QR settings.';
      draw();
    }
  }

  async function save(){
    const button=$('v110QrSave');
    button.disabled=true;status.textContent='Saving…';
    try{
      const response=await fetch('/api/qr-overlay',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({size:Math.round(value.size),x:value.x,y:value.y})
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false) throw new Error(data.error||'Could not save QR settings.');
      const saved=data.qr_overlay||{};
      value={
        size:clamp(saved.size??value.size,MIN_SIZE,MAX_SIZE),
        x:clamp(saved.x??value.x,0,100),
        y:clamp(saved.y??value.y,0,100)
      };
      draw();status.textContent='Saved. The TV QR will move automatically.';
    }catch(e){status.textContent=e.message||'Could not save QR settings.';}
    finally{button.disabled=false;}
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(makeSection()) return;
      if(++tries<100) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();


/* ------------------------------------------------------------------
   controls.js
   ------------------------------------------------------------------ */
/* v112 remote organization + five dropdown Map Keys controls.
   View owns which screens rotate. Controls owns TV controls, Number Size,
   QR Code, and Map Keys. Keyboard and mouse inputs use the same dropdowns. */
(function(){
  const $=id=>document.getElementById(id);
  let snapshot=null;
  let vocabulary=null;

  const DEFAULT_KEYS={
    previous:"ArrowLeft",
    next:"ArrowRight",
    pair:"ArrowUp",
    sort_prev:"MouseWheelUp",
    sort_next:"MouseWheelDown"
  };

  const ACTION_ROWS=[
    {key:"previous",label:"Previous Screen"},
    {key:"next",label:"Next Screen"},
    {key:"pair",label:"Next Team Matchup"},
    {key:"sort_prev",label:"Previous Measuring Stat"},
    {key:"sort_next",label:"Next Measuring Stat"}
  ];

  const INPUT_GROUPS=[
    ["Keyboard",[
      ["ArrowLeft","Arrow Left"],["ArrowRight","Arrow Right"],
      ["ArrowUp","Arrow Up"],["ArrowDown","Arrow Down"],
      ...Array.from({length:26},(_,i)=>[String.fromCharCode(97+i),String.fromCharCode(65+i)]),
      ...Array.from({length:10},(_,i)=>[String(i),String(i)]),
      ["PageUp","Page Up"],["PageDown","Page Down"],
      ["Home","Home"],["End","End"],["Enter","Enter"],[" ","Space"],
      ["[","["],["]","]"]
    ]],
    ["Mouse",[
      ["MouseWheelUp","Mouse Wheel Up"],
      ["MouseWheelDown","Mouse Wheel Down"],
      ["MouseLeft","Mouse Left Click"],
      ["MouseRight","Mouse Right Click"],
      ["MouseMiddle","Mouse Middle Click"]
    ]]
  ];

  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({
    "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
  }[ch]));

  const allInputValues=()=>new Set(INPUT_GROUPS.flatMap(group=>group[1].map(item=>item[0])));

  function topSection(label){
    const stack=$("v98Sections");
    if(!stack) return null;
    return Array.from(stack.querySelectorAll(":scope > .v98-section")).find(section=>
      String(section.querySelector(":scope > summary")?.textContent||"").trim()===label
    )||null;
  }

  function nested(label,key){
    const details=document.createElement("details");
    details.className="v98-subsection";
    details.dataset.v98Key=key;
    const summary=document.createElement("summary");
    summary.textContent=label;
    const body=document.createElement("div");
    body.className="v98-subsection-body";
    details.append(summary,body);
    return {details,body};
  }

  function moveExistingControls(){
    const view=topSection("View");
    const remote=topSection("TV Remote")||topSection("Controls");
    if(!view||!remote) return false;

    const remoteSummary=remote.querySelector(":scope > summary");
    if(remoteSummary) remoteSummary.textContent="Controls";
    remote.dataset.v98Key="controls";
    const controlsBody=remote.querySelector(":scope > .v98-section-body");
    if(!controlsBody) return false;

    const numberDetails=$("v75NumCard")?.closest(".v98-subsection");
    if(numberDetails && numberDetails.parentElement!==controlsBody){
      numberDetails.dataset.v98Key="controls-number-size";
      controlsBody.appendChild(numberDetails);
    }

    const qr=$("v110QrSection");
    if(qr && qr.parentElement!==controlsBody){
      qr.classList.remove("v98-section");
      qr.classList.add("v98-subsection");
      qr.dataset.v98Key="controls-qr";
      const qrBody=qr.querySelector(":scope > .v98-section-body");
      if(qrBody){
        qrBody.classList.remove("v98-section-body");
        qrBody.classList.add("v98-subsection-body");
      }
      controlsBody.appendChild(qr);
    }
    return true;
  }

  // The screen list comes from the server. This file used to write its own,
  // which is why it silently missed Product Close Rates and needed a separate
  // script to inject that one checkbox afterwards.
  function viewChoices(){
    return (vocabulary?.available_views||[]).map(item=>({
      value:String(item?.value??""),
      label:String(item?.label??item?.value??"")
    })).filter(item=>item.value);
  }

  function installRotationSection(){
    if($("v112Rotation")) return;
    const view=topSection("View");
    const body=view?.querySelector(":scope > .v98-section-body");
    if(!body) return;
    const made=nested("Screens in Rotation","view-screen-rotation");
    made.details.id="v112Rotation";
    made.body.innerHTML=`
      <div class="small">Choose the screens the Previous / Next controls rotate through.</div>
      <div id="v112RotationList" class="builder-list" style="margin-top:10px"></div>
      <div class="row" style="margin-top:12px">
        <button id="v112RotationSave" class="btn primary" type="button">Save Rotation</button>
      </div>
      <div id="v112RotationStatus" class="small" style="margin-top:8px"></div>`;
    const filters=body.querySelector('[data-v98-key="view-filters"]');
    if(filters) body.insertBefore(made.details,filters); else body.appendChild(made.details);
    $("v112RotationSave").addEventListener("click",saveRotation);
  }

  function optionMarkup(){
    return INPUT_GROUPS.map(([group,items])=>
      `<optgroup label="${esc(group)}">${items.map(([value,label])=>
        `<option value="${esc(value)}">${esc(label)}</option>`
      ).join("")}</optgroup>`
    ).join("");
  }

  function installMapKeys(){
    if($("v112MapKeys")) return;
    const controls=topSection("Controls");
    const body=controls?.querySelector(":scope > .v98-section-body");
    if(!body) return;
    const made=nested("Map Keys","controls-map-keys");
    made.details.id="v112MapKeys";
    made.body.innerHTML=`
      <div class="small">Choose one keyboard or mouse input for each TV control.</div>
      <div class="builder-list" style="margin-top:12px">
        ${ACTION_ROWS.map(row=>`
          <div>
            <label for="v112Map_${row.key}">${esc(row.label)}</label>
            <select id="v112Map_${row.key}" data-v112-action="${row.key}">${optionMarkup()}</select>
          </div>`).join("")}
      </div>
      <div class="row" style="margin-top:12px">
        <button id="v112KeysSave" class="btn primary" type="button">Save Map Keys</button>
      </div>
      <div id="v112KeysStatus" class="small" style="margin-top:8px"></div>`;
    body.appendChild(made.details);
    $("v112KeysSave").addEventListener("click",saveKeys);
  }

  async function loadConfig(){
    try{
      const [config,controls]=await Promise.all([
        fetch("/api/config",{cache:"no-store"}),
        fetch("/api/keyboard-controls",{cache:"no-store"})
      ]);
      if(!config.ok||!controls.ok) throw new Error("Could not load controls.");
      snapshot=await config.json();
      vocabulary=(await controls.json())?.keyboard||null;
      paintRotation();
      paintKeys();
    }catch(e){
      const a=$("v112RotationStatus"),b=$("v112KeysStatus");
      if(a) a.textContent=e.message||"Could not load controls.";
      if(b) b.textContent=e.message||"Could not load controls.";
    }
  }

  function paintRotation(){
    const list=$("v112RotationList");
    if(!list||!snapshot||!vocabulary) return;
    const choices=viewChoices();
    const raw=snapshot.settings?.keyboard_cycle_views;
    const selected=Array.isArray(raw)&&raw.length?new Set(raw.map(String)):new Set(choices.map(item=>item.value));
    list.innerHTML=choices.map(item=>`
      <label class="check" style="margin:0">
        <input class="v112RotationView" type="checkbox" value="${esc(item.value)}" ${selected.has(item.value)?"checked":""}>
        <span>${esc(item.label)}</span>
      </label>`).join("");
  }

  function paintKeys(){
    if(!snapshot) return;
    const allowed=allInputValues();
    const raw=snapshot.settings?.keyboard_cycle_keys||{};
    ACTION_ROWS.forEach(row=>{
      const select=$(`v112Map_${row.key}`);
      if(!select) return;
      const value=allowed.has(raw[row.key])?raw[row.key]:DEFAULT_KEYS[row.key];
      select.value=value;
    });
  }

  async function postKeyboard(payload){
    const response=await fetch("/api/keyboard-controls",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false) throw new Error(data.error||"Could not save controls.");
    snapshot=snapshot||{settings:{}};
    snapshot.settings=snapshot.settings||{};
    if(data.keyboard?.views) snapshot.settings.keyboard_cycle_views=data.keyboard.views;
    if(data.keyboard?.keys) snapshot.settings.keyboard_cycle_keys=data.keyboard.keys;
    return data;
  }

  async function saveRotation(){
    const button=$("v112RotationSave"),status=$("v112RotationStatus");
    const views=Array.from(document.querySelectorAll(".v112RotationView:checked")).map(el=>el.value);
    if(!views.length){status.textContent="Select at least one screen.";return;}
    button.disabled=true;status.textContent="Saving…";
    try{
      await postKeyboard({views});
      status.textContent="Saved. Rotation now uses only these screens.";
    }catch(e){status.textContent=e.message||"Could not save rotation.";}
    finally{button.disabled=false;}
  }

  async function saveKeys(){
    const button=$("v112KeysSave"),status=$("v112KeysStatus");
    const keys={};
    ACTION_ROWS.forEach(row=>{keys[row.key]=$(`v112Map_${row.key}`).value;});
    if(new Set(Object.values(keys)).size!==ACTION_ROWS.length){
      status.textContent="Each control needs a different input.";
      return;
    }
    button.disabled=true;status.textContent="Saving…";
    try{
      const data=await postKeyboard({keys});
      const saved=data.keyboard?.keys||keys;
      ACTION_ROWS.forEach(row=>{$(`v112Map_${row.key}`).value=saved[row.key]||DEFAULT_KEYS[row.key];});
      status.textContent="Saved. The TV uses these controls automatically.";
    }catch(e){status.textContent=e.message||"Could not save Map Keys.";}
    finally{button.disabled=false;}
  }

  function organize(){
    if(!$("v98Sections")||!$("v110QrSection")||!$("v75NumCard")) return false;
    if(!moveExistingControls()) return false;
    installRotationSection();
    installMapKeys();
    loadConfig();
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(organize()) return;
      if(++tries<120) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();


/* ------------------------------------------------------------------
   qr-style.js
   ------------------------------------------------------------------ */
/* v113: one permanent QR appearance in the remote preview. */
(function(){
  function apply(){
    const preview=document.getElementById('v110QrPreview');
    if(!preview) return false;
    preview.style.background='#000';
    preview.style.borderRadius='7px';
    preview.style.boxShadow='0 0 0 1px rgba(255,255,255,.10)';
    const image=preview.querySelector('img');
    if(image){
      image.src='/static/remote-qr-v109.svg?v=113';
      image.style.borderRadius='4px';
    }
    return true;
  }

  let tries=0;
  (function attempt(){
    if(apply()) return;
    if(++tries<120) setTimeout(attempt,50);
  })();
})();


/* ------------------------------------------------------------------
   temporary-date.js
   ------------------------------------------------------------------ */
/* v113 View: temporary date override without touching scheduled rows. */
(function(){
  const $=id=>document.getElementById(id);
  let pollTimer=null;

  function topSection(label){
    const stack=$('v98Sections');
    if(!stack) return null;
    return Array.from(stack.querySelectorAll(':scope > .v98-section')).find(section=>
      String(section.querySelector(':scope > summary')?.textContent||'').trim()===label
    )||null;
  }

  function nested(label,key){
    const details=document.createElement('details');
    details.className='v98-subsection';
    details.dataset.v98Key=key;
    const summary=document.createElement('summary');
    summary.textContent=label;
    const body=document.createElement('div');
    body.className='v98-subsection-body';
    details.append(summary,body);
    return {details,body};
  }

  function mount(){
    if($('v113DateOverride')) return true;
    const view=topSection('View');
    const body=view?.querySelector(':scope > .v98-section-body');
    if(!body) return false;

    const made=nested('Temporary Date Override','view-temporary-date');
    made.details.id='v113DateOverride';
    made.body.innerHTML=`
      <div class="small">Temporarily replace the TV numbers without changing the regular scheduled data.</div>
      <div class="grid" style="margin-top:12px">
        <div>
          <label for="v113DateMode">Mode</label>
          <select id="v113DateMode">
            <option value="ytd">Year to Date</option>
            <option value="custom">Custom Range</option>
          </select>
        </div>
        <div>
          <label for="v113DateMinutes">Duration on screen (minutes)</label>
          <input id="v113DateMinutes" type="number" min="1" max="60" step="1" value="15" inputmode="numeric">
        </div>
      </div>
      <div id="v113CustomDates" class="grid" style="margin-top:12px;display:none">
        <div>
          <label for="v113DateStart">Start</label>
          <input id="v113DateStart" type="date">
        </div>
        <div>
          <label for="v113DateEnd">End</label>
          <input id="v113DateEnd" type="date">
        </div>
      </div>
      <div class="row" style="margin-top:12px">
        <button id="v113DateApply" class="btn primary" type="button">Apply</button>
      </div>
      <div id="v113DateStatus" class="small" style="margin-top:8px"></div>`;

    const rotation=$('v112Rotation');
    if(rotation&&rotation.parentElement===body) rotation.insertAdjacentElement('afterend',made.details);
    else body.appendChild(made.details);

    $('v113DateMode').addEventListener('change',paintMode);
    $('v113DateApply').addEventListener('click',applyOverride);
    paintMode();
    refreshState();
    pollTimer=setInterval(refreshState,10000);
    return true;
  }

  function paintMode(){
    const custom=$('v113CustomDates');
    if(custom) custom.style.display=$('v113DateMode')?.value==='custom'?'grid':'none';
  }

  function minutesLeft(seconds){
    return Math.max(1,Math.ceil(Number(seconds||0)/60));
  }

  function prettyRange(state){
    if(state.mode==='ytd') return `Year to Date (${state.start} to ${state.end})`;
    return `${state.start} to ${state.end}`;
  }

  function paintState(state){
    const status=$('v113DateStatus');
    if(!status) return;
    if(!state?.active){
      status.textContent='No temporary override active.';
      return;
    }
    status.textContent=`Active: ${prettyRange(state)} · about ${minutesLeft(state.seconds_left)} min left`;
  }

  async function refreshState(){
    try{
      const response=await fetch('/api/temporary-date-override',{cache:'no-store'});
      if(!response.ok) return;
      const data=await response.json();
      const state=data.override||{};
      paintState(state);
      if(state.active){
        $('v113DateMode').value=state.mode||'ytd';
        $('v113DateMinutes').value=String(state.minutes||15);
        if(state.mode==='custom'){
          $('v113DateStart').value=state.start||'';
          $('v113DateEnd').value=state.end||'';
        }
        paintMode();
      }
    }catch(_){ }
  }

  async function applyOverride(){
    const status=$('v113DateStatus');
    const button=$('v113DateApply');
    const mode=$('v113DateMode').value;
    const minutes=Number($('v113DateMinutes').value);

    if(!Number.isInteger(minutes)||minutes<1||minutes>60){
      status.textContent='Enter a duration from 1 to 60 minutes.';
      return;
    }

    const payload={mode,minutes};
    if(mode==='custom'){
      payload.start=$('v113DateStart').value;
      payload.end=$('v113DateEnd').value;
      if(!payload.start||!payload.end){
        status.textContent='Choose both Start and End dates.';
        return;
      }
      if(payload.start>payload.end){
        status.textContent='Start date must be before or equal to End date.';
        return;
      }
    }

    button.disabled=true;
    status.textContent='Loading temporary numbers…';
    try{
      const response=await fetch('/api/temporary-date-override',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload)
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false) throw new Error(data.error||'Could not apply temporary date override.');
      paintState(data.override||{});
    }catch(e){
      status.textContent=e.message||'Could not apply temporary date override.';
    }finally{
      button.disabled=false;
    }
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(mount()) return;
      if(++tries<120) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
