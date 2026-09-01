/* Physical input mapping for Stats TV controls. Display owns screen rotation. */
(function(){
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

  const DEFAULT_KEYS={
    previous:"ArrowLeft",
    next:"ArrowRight",
    pair:"ArrowUp",
    sort_prev:"MouseWheelUp",
    sort_next:"MouseWheelDown"
  };
  const ACTIONS=[
    ["previous","Previous Screen"],
    ["next","Next Screen"],
    ["pair","Next Team Matchup"],
    ["sort_prev","Previous Measuring Stat"],
    ["sort_next","Next Measuring Stat"]
  ];
  const INPUTS=[
    ["Keyboard",[
      ["ArrowLeft","Arrow Left"],["ArrowRight","Arrow Right"],["ArrowUp","Arrow Up"],["ArrowDown","Arrow Down"],
      ...Array.from({length:26},(_,index)=>[String.fromCharCode(97+index),String.fromCharCode(65+index)]),
      ...Array.from({length:10},(_,index)=>[String(index),String(index)]),
      ["PageUp","Page Up"],["PageDown","Page Down"],["Home","Home"],["End","End"],["Enter","Enter"],[" ","Space"],["[","["],["]","]"]
    ]],
    ["Mouse",[
      ["MouseWheelUp","Mouse Wheel Up"],["MouseWheelDown","Mouse Wheel Down"],
      ["MouseLeft","Mouse Left Click"],["MouseRight","Mouse Right Click"],["MouseMiddle","Mouse Middle Click"]
    ]]
  ];
  const allowed=new Set(INPUTS.flatMap(([,items])=>items.map(([value])=>value)));

  function options(){
    return INPUTS.map(([label,items])=>`<optgroup label="${esc(label)}">${items.map(([value,name])=>`<option value="${esc(value)}">${esc(name)}</option>`).join("")}</optgroup>`).join("");
  }

  function mount(){
    const host=$("settingsMapKeysControls");
    if(!host||$("mapKeysCard"))return false;
    host.innerHTML=`<div class="card" id="mapKeysCard">
      <h2>Map Keys</h2>
      <p class="small">Map keyboard or mouse inputs to TV actions. Which Screens rotate is configured in Display.</p>
      <div class="grid" id="mapKeysFields">
        ${ACTIONS.map(([key,label])=>`<div><label for="mapKey_${key}">${esc(label)}</label><select id="mapKey_${key}" data-map-action="${key}">${options()}</select></div>`).join("")}
      </div>
      <div class="row" style="margin-top:12px"><button id="saveMapKeys" class="btn primary" type="button">Save Map Keys</button></div>
      <div id="mapKeysStatus" class="small settings-status"></div>
    </div>`;
    $("saveMapKeys").addEventListener("click",save);
    load();
    return true;
  }

  async function load(){
    const status=$("mapKeysStatus");
    try{
      const response=await fetch("/api/config",{cache:"no-store"});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(data.error||"Could not load controls.");
      const saved=data.settings?.keyboard_cycle_keys||{};
      ACTIONS.forEach(([key])=>{
        const value=allowed.has(saved[key])?saved[key]:DEFAULT_KEYS[key];
        $(`mapKey_${key}`).value=value;
      });
      status.textContent="";
    }catch(err){status.textContent=err.message||"Could not load controls.";}
  }

  async function save(){
    const button=$("saveMapKeys"),status=$("mapKeysStatus");
    const keys={};ACTIONS.forEach(([key])=>{keys[key]=$(`mapKey_${key}`).value;});
    if(new Set(Object.values(keys)).size!==ACTIONS.length){status.textContent="Each TV action needs a different input.";return;}
    button.disabled=true;status.textContent="Saving…";
    try{
      const response=await fetch("/api/keyboard-controls",{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({keys})
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false)throw new Error(data.error||"Could not save controls.");
      const saved=data.keyboard?.keys||keys;
      ACTIONS.forEach(([key])=>{$(`mapKey_${key}`).value=saved[key]||DEFAULT_KEYS[key];});
      status.textContent="Saved.";
    }catch(err){status.textContent=err.message||"Could not save controls.";}
    finally{button.disabled=false;}
  }

  function start(){
    let tries=0;(function attempt(){if(mount())return;if(++tries<80)setTimeout(attempt,50);})();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
