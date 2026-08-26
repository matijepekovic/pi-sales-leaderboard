/* v112 remote organization + five dropdown Map Keys controls.
   View owns which screens rotate. Controls owns TV controls, Number Size,
   QR Code, and Map Keys. Keyboard and mouse inputs use the same dropdowns. */
(function(){
  const $=id=>document.getElementById(id);
  let snapshot=null;

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

  function viewChoices(data){
    const teams=(data?.team_definitions||[])
      .map(team=>String(team?.name||"").trim())
      .filter(Boolean);
    return [
      {value:"whole_office",label:"Whole Office"},
      {value:"team_vs_team",label:"Team vs Team"},
      {value:"all_teams",label:"All Teams"},
      ...teams.map(name=>({value:`per_team::${name}`,label:`Team — ${name}`}))
    ];
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
      const response=await fetch("/api/config",{cache:"no-store"});
      if(!response.ok) throw new Error("Could not load controls.");
      snapshot=await response.json();
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
    if(!list||!snapshot) return;
    const choices=viewChoices(snapshot);
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
