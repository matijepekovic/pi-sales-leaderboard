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
