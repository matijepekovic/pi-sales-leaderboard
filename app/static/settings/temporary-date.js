/* Temporary data override controls. This changes Report date windows, not Screen filters. */
(function(){
  const $=id=>document.getElementById(id);
  let pollTimer=null;

  function mount(){
    const host=$("settingsTemporaryDateControls");if(!host||$("temporaryDateCard"))return false;
    host.innerHTML=`<div class="card" id="temporaryDateCard">
      <h2>Temporary Data Override</h2>
      <p class="small">Temporarily replace the TV date window without changing scheduled Report configuration or Display Filters.</p>
      <div class="grid">
        <div><label for="temporaryDateMode">Mode</label><select id="temporaryDateMode"><option value="ytd">Year to Date</option><option value="custom">Custom Range</option></select></div>
        <div><label for="temporaryDateMinutes">Duration on screen (minutes)</label><input id="temporaryDateMinutes" type="number" min="1" max="60" step="1" value="15" inputmode="numeric"></div>
      </div>
      <div id="temporaryCustomDates" class="grid" style="margin-top:12px;display:none">
        <div><label for="temporaryDateStart">Start</label><input id="temporaryDateStart" type="date"></div>
        <div><label for="temporaryDateEnd">End</label><input id="temporaryDateEnd" type="date"></div>
      </div>
      <div class="row" style="margin-top:12px">
        <button id="temporaryDateApply" class="btn primary" type="button">Apply</button>
        <button id="temporaryDateCancel" class="btn" type="button">Cancel Override</button>
      </div>
      <div id="temporaryDateStatus" class="small settings-status"></div>
    </div>`;
    $("temporaryDateMode").addEventListener("change",paintMode);
    $("temporaryDateApply").addEventListener("click",apply);
    $("temporaryDateCancel").addEventListener("click",cancel);
    paintMode();refresh();pollTimer=setInterval(refresh,10000);return true;
  }

  function paintMode(){if($("temporaryCustomDates"))$("temporaryCustomDates").style.display=$("temporaryDateMode")?.value==="custom"?"grid":"none";}
  function minutesLeft(seconds){return Math.max(1,Math.ceil(Number(seconds||0)/60));}
  function label(state){return state.mode==="ytd"?`Year to Date (${state.start} to ${state.end})`:`${state.start} to ${state.end}`;}

  function paintState(state){
    const status=$("temporaryDateStatus"),cancelButton=$("temporaryDateCancel");if(!status)return;
    if(!state?.active){status.textContent="No temporary override active.";if(cancelButton)cancelButton.disabled=true;return;}
    if(cancelButton)cancelButton.disabled=false;
    status.textContent=`Active: ${label(state)} · about ${minutesLeft(state.seconds_left)} min left`;
    $("temporaryDateMode").value=state.mode||"ytd";
    $("temporaryDateMinutes").value=String(state.minutes||15);
    if(state.mode==="custom"){$("temporaryDateStart").value=state.start||"";$("temporaryDateEnd").value=state.end||"";}
    paintMode();
  }

  async function refresh(){
    try{
      const response=await fetch("/api/temporary-date-override",{cache:"no-store"});
      if(!response.ok)return;
      const data=await response.json();paintState(data.override||{});
    }catch(_){ }
  }

  async function apply(){
    const button=$("temporaryDateApply"),status=$("temporaryDateStatus");
    const mode=$("temporaryDateMode").value,minutes=Number($("temporaryDateMinutes").value);
    if(!Number.isInteger(minutes)||minutes<1||minutes>60){status.textContent="Enter a duration from 1 to 60 minutes.";return;}
    const payload={mode,minutes};
    if(mode==="custom"){
      payload.start=$("temporaryDateStart").value;payload.end=$("temporaryDateEnd").value;
      if(!payload.start||!payload.end){status.textContent="Choose both Start and End dates.";return;}
      if(payload.start>payload.end){status.textContent="Start date must be before or equal to End date.";return;}
    }
    button.disabled=true;status.textContent="Loading temporary data…";
    try{
      const response=await fetch("/api/temporary-date-override",{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false)throw new Error(data.error||"Could not apply temporary data override.");
      paintState(data.override||{});
    }catch(err){status.textContent=err.message||"Could not apply temporary data override.";}
    finally{button.disabled=false;}
  }

  async function cancel(){
    const button=$("temporaryDateCancel"),status=$("temporaryDateStatus");button.disabled=true;status.textContent="Cancelling…";
    try{
      const response=await fetch("/api/temporary-date-override",{method:"DELETE"});
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false)throw new Error(data.error||"Could not cancel temporary data override.");
      paintState(data.override||{});
    }catch(err){status.textContent=err.message||"Could not cancel temporary data override.";button.disabled=false;}
  }

  function start(){let tries=0;(function attempt(){if(mount())return;if(++tries<80)setTimeout(attempt,50);})();}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
