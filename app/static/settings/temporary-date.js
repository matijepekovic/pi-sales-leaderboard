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
