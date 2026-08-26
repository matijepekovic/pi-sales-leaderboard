/* v111 remote organization + keyboard rotation settings.
   View owns which screens rotate. Controls owns TV controls, Number Size,
   QR Code, and Map Keys. Existing controls are moved intact. */
(function(){
  const $=id=>document.getElementById(id);
  let snapshot=null;
  let captureTarget=null;

  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({
    "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
  }[ch]));

  function canonicalKey(value){
    value=String(value??"").trim();
    const aliases={
      left:"ArrowLeft",arrowleft:"ArrowLeft",
      right:"ArrowRight",arrowright:"ArrowRight",
      up:"ArrowUp",arrowup:"ArrowUp",
      down:"ArrowDown",arrowdown:"ArrowDown",
      pageup:"PageUp",pagedown:"PageDown",
      enter:"Enter",return:"Enter",
      space:" ",spacebar:" ",
      tab:"Tab",escape:"Escape",esc:"Escape"
    };
    const lowered=value.toLowerCase();
    if(aliases[lowered]) return aliases[lowered];
    return value.length===1?value.toLowerCase():value;
  }

  function prettyKey(value){
    value=String(value??"");
    if(value===" ") return "Space";
    return value;
  }

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

    // v98 originally nested Number Size under View. Move that exact details
    // node so its existing +/- listeners and per-screen save behavior survive.
    const numberDetails=$("v75NumCard")?.closest(".v98-subsection");
    if(numberDetails && numberDetails.parentElement!==controlsBody){
      numberDetails.dataset.v98Key="controls-number-size";
      controlsBody.appendChild(numberDetails);
    }

    // v110 mounted QR as its own top-level tab. Convert that same node into a
    // nested Controls section; drag/resize/save listeners stay attached.
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
    if($("v111Rotation")) return;
    const view=topSection("View");
    const body=view?.querySelector(":scope > .v98-section-body");
    if(!body) return;
    const made=nested("Screens in Rotation","view-screen-rotation");
    made.details.id="v111Rotation";
    made.body.innerHTML=`
      <div class="small">Choose the screens the Previous / Next keyboard controls rotate through.</div>
      <div id="v111RotationList" class="builder-list" style="margin-top:10px"></div>
      <div class="row" style="margin-top:12px">
        <button id="v111RotationSave" class="btn primary" type="button">Save Rotation</button>
      </div>
      <div id="v111RotationStatus" class="small" style="margin-top:8px"></div>`;
    const filters=body.querySelector('[data-v98-key="view-filters"]');
    if(filters) body.insertBefore(made.details,filters); else body.appendChild(made.details);
    $("v111RotationSave").addEventListener("click",saveRotation);
  }

  function installMapKeys(){
    if($("v111MapKeys")) return;
    const controls=topSection("Controls");
    const body=controls?.querySelector(":scope > .v98-section-body");
    if(!body) return;
    const made=nested("Map Keys","controls-map-keys");
    made.details.id="v111MapKeys";
    made.body.innerHTML=`
      <div class="small">Keys used to rotate backward and forward through the selected TV screens.</div>
      <div class="grid" style="margin-top:12px">
        <div>
          <label for="v111KeyPrevious">Previous screen</label>
          <div class="row" style="align-items:stretch">
            <input id="v111KeyPrevious" type="text" autocomplete="off" spellcheck="false" style="flex:1 1 160px">
            <button class="btn" type="button" data-v111-capture="previous">Press key</button>
          </div>
        </div>
        <div>
          <label for="v111KeyNext">Next screen</label>
          <div class="row" style="align-items:stretch">
            <input id="v111KeyNext" type="text" autocomplete="off" spellcheck="false" style="flex:1 1 160px">
            <button class="btn" type="button" data-v111-capture="next">Press key</button>
          </div>
        </div>
      </div>
      <div class="row" style="margin-top:12px">
        <button id="v111KeysSave" class="btn primary" type="button">Save Keys</button>
      </div>
      <div id="v111KeysStatus" class="small" style="margin-top:8px"></div>`;
    body.appendChild(made.details);
    made.details.querySelectorAll("[data-v111-capture]").forEach(button=>
      button.addEventListener("click",()=>startCapture(button.dataset.v111Capture,button))
    );
    $("v111KeysSave").addEventListener("click",saveKeys);
  }

  function startCapture(which,button){
    captureTarget=which;
    document.querySelectorAll("[data-v111-capture]").forEach(el=>{
      el.textContent=el===button?"Press a key…":"Press key";
    });
    const status=$("v111KeysStatus");
    if(status) status.textContent="Press the key you want to use.";
  }

  document.addEventListener("keydown",event=>{
    if(!captureTarget) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const input=captureTarget==="previous"?$("v111KeyPrevious"):$("v111KeyNext");
    if(input) input.value=prettyKey(event.key);
    captureTarget=null;
    document.querySelectorAll("[data-v111-capture]").forEach(el=>el.textContent="Press key");
    const status=$("v111KeysStatus");
    if(status) status.textContent="Captured. Press Save Keys.";
  },true);

  async function loadConfig(){
    try{
      const response=await fetch("/api/config",{cache:"no-store"});
      if(!response.ok) throw new Error("Could not load controls.");
      snapshot=await response.json();
      paintRotation();
      paintKeys();
    }catch(e){
      const a=$("v111RotationStatus"),b=$("v111KeysStatus");
      if(a) a.textContent=e.message||"Could not load controls.";
      if(b) b.textContent=e.message||"Could not load controls.";
    }
  }

  function paintRotation(){
    const list=$("v111RotationList");
    if(!list||!snapshot) return;
    const choices=viewChoices(snapshot);
    const raw=snapshot.settings?.keyboard_cycle_views;
    const selected=Array.isArray(raw)&&raw.length?new Set(raw.map(String)):new Set(choices.map(item=>item.value));
    list.innerHTML=choices.map(item=>`
      <label class="check" style="margin:0">
        <input class="v111RotationView" type="checkbox" value="${esc(item.value)}" ${selected.has(item.value)?"checked":""}>
        <span>${esc(item.label)}</span>
      </label>`).join("");
  }

  function paintKeys(){
    if(!snapshot) return;
    const map=snapshot.settings?.keyboard_cycle_keys||{};
    const previous=map.previous||"ArrowLeft";
    const next=map.next||"ArrowRight";
    if($("v111KeyPrevious")) $("v111KeyPrevious").value=prettyKey(previous);
    if($("v111KeyNext")) $("v111KeyNext").value=prettyKey(next);
  }

  async function postKeyboard(payload){
    const response=await fetch("/api/keyboard-controls",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false) throw new Error(data.error||"Could not save controls.");
    // Keep the page snapshot coherent without waiting for the next full load.
    snapshot=snapshot||{settings:{}};
    snapshot.settings=snapshot.settings||{};
    if(data.keyboard?.views) snapshot.settings.keyboard_cycle_views=data.keyboard.views;
    if(data.keyboard?.keys) snapshot.settings.keyboard_cycle_keys=data.keyboard.keys;
    return data;
  }

  async function saveRotation(){
    const button=$("v111RotationSave"),status=$("v111RotationStatus");
    const views=Array.from(document.querySelectorAll(".v111RotationView:checked")).map(el=>el.value);
    if(!views.length){status.textContent="Select at least one screen.";return;}
    button.disabled=true;status.textContent="Saving…";
    try{
      await postKeyboard({views});
      status.textContent="Saved. Keyboard rotation now uses only these screens.";
    }catch(e){status.textContent=e.message||"Could not save rotation.";}
    finally{button.disabled=false;}
  }

  async function saveKeys(){
    const button=$("v111KeysSave"),status=$("v111KeysStatus");
    const previous=canonicalKey($("v111KeyPrevious").value);
    const next=canonicalKey($("v111KeyNext").value);
    if(!previous||!next){status.textContent="Both keys are required.";return;}
    if(previous===next){status.textContent="Previous and Next must use different keys.";return;}
    button.disabled=true;status.textContent="Saving…";
    try{
      const data=await postKeyboard({keys:{previous,next}});
      const keys=data.keyboard?.keys||{previous,next};
      $("v111KeyPrevious").value=prettyKey(keys.previous);
      $("v111KeyNext").value=prettyKey(keys.next);
      status.textContent="Saved. The TV uses these keys immediately.";
    }catch(e){status.textContent=e.message||"Could not save keys.";}
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
