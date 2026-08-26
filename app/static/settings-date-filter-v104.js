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
