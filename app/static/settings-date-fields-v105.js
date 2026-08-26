/* v105: replace raw date-field text inputs with report-aware selectors.
   The backend still uses the existing v90DateStart/v90DateEnd values. This UI
   keeps those inputs hidden, syncs selectors into them, and guesses likely
   start/end date fields after Read Report loads the report columns. */
(function(){
  const $=id=>document.getElementById(id);

  function norm(value){
    return String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  }

  function score(field,kind){
    const n=norm(field);
    let s=0;
    if(/date/.test(n)) s+=20;
    if(kind==='start'){
      if(/\bstart date\b|\bdate start\b/.test(n)) s+=100;
      if(/\bstart\b/.test(n)) s+=60;
      if(/\bfrom\b|\bbegin\b|\bbeginning\b/.test(n)) s+=35;
    }else{
      if(/\bend date\b|\bdate end\b/.test(n)) s+=100;
      if(/\bend\b/.test(n)) s+=60;
      if(/\bthrough\b|\buntil\b|\bto date\b/.test(n)) s+=35;
    }
    return s;
  }

  function reportFields(){
    const select=document.querySelector('#v79MapRows .v79Dim');
    if(!select) return [];
    return Array.from(select.options)
      .map(option=>String(option.value||'').trim())
      .filter(Boolean);
  }

  function setHidden(input,value){
    const next=String(value||'');
    if(input.value===next) return;
    input.value=next;
    input.dispatchEvent(new Event('input',{bubbles:true}));
  }

  function buildOptions(select,fields,current){
    const values=fields.slice();
    if(current&&!values.includes(current)) values.unshift(current);
    select.innerHTML='<option value="">Choose from report…</option>'+values.map(value=>
      `<option value="${String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')}">${String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;')}</option>`
    ).join('');
    select.value=current||'';
  }

  function best(fields,kind){
    return fields
      .map(field=>({field,score:score(field,kind)}))
      .sort((a,b)=>b.score-a.score)[0]||null;
  }

  function organize(){
    const dateBlock=$('v104DateFilters');
    const startInput=$('v90DateStart');
    const endInput=$('v90DateEnd');
    if(!dateBlock||!startInput||!endInput) return false;
    if($('v105DateFieldChooser')) return true;

    const legacyGrid=startInput.closest('.grid');
    if(!legacyGrid) return false;
    legacyGrid.style.display='none';

    const status=document.createElement('div');
    status.id='v105DateFieldStatus';
    status.className='small';
    status.style.margin='10px 0 4px';

    const chooser=document.createElement('details');
    chooser.id='v105DateFieldChooser';
    chooser.style.marginTop='6px';
    chooser.innerHTML=`
      <summary style="cursor:pointer;font-weight:700">Date filter fields</summary>
      <div class="grid" style="margin-top:9px">
        <div><label for="v105DateStartSelect">Start date field</label><select id="v105DateStartSelect"></select></div>
        <div><label for="v105DateEndSelect">End date field</label><select id="v105DateEndSelect"></select></div>
      </div>
      <div class="small" style="margin-top:6px">Loaded from the selected report. Usually these are detected automatically.</div>`;

    legacyGrid.insertAdjacentElement('afterend',status);
    status.insertAdjacentElement('afterend',chooser);

    const startSelect=$('v105DateStartSelect');
    const endSelect=$('v105DateEndSelect');
    startSelect.addEventListener('change',()=>setHidden(startInput,startSelect.value));
    endSelect.addEventListener('change',()=>setHidden(endInput,endSelect.value));

    function refresh(autoGuess=false){
      const fields=reportFields();
      let start=startInput.value.trim();
      let end=endInput.value.trim();

      if(fields.length&&autoGuess){
        if(!start){
          const guess=best(fields,'start');
          if(guess&&guess.score>=55){ start=guess.field; setHidden(startInput,start); }
        }
        if(!end){
          const guess=best(fields,'end');
          if(guess&&guess.score>=55){ end=guess.field; setHidden(endInput,end); }
        }
      }

      buildOptions(startSelect,fields,start);
      buildOptions(endSelect,fields,end);

      if(!fields.length){
        status.textContent=(start||end)
          ? `Saved date fields: ${start||'—'} → ${end||'—'}. Read Report to refresh choices.`
          : 'Read Report to detect the date filter fields.';
        chooser.open=!(start&&end);
        return;
      }

      if(start&&end){
        status.textContent=`Using ${start} → ${end}.`;
        chooser.open=false;
      }else{
        status.textContent='Choose the report fields Tableau uses for the start and end dates.';
        chooser.open=true;
      }
    }

    function refreshAfterRead(){
      let tries=0;
      (function wait(){
        if(reportFields().length){ refresh(true); return; }
        if(++tries<80) setTimeout(wait,100);
      })();
    }

    $('v79Load')?.addEventListener('click',refreshAfterRead);
    $('v79Workbook')?.addEventListener('change',()=>setTimeout(()=>refresh(false),0));
    $('v79Sheet')?.addEventListener('change',()=>setTimeout(()=>refresh(false),0));

    refresh(false);
    setTimeout(()=>refresh(false),500);
    setTimeout(()=>refresh(false),1500);
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(organize()) return;
      if(++tries<80) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
