/* v106: date is a normal report control, not a mapping task.
   Keep only Current month / Custom range + Start / End date pickers visible.
   Tableau's standard Start / End filter keys stay internal. */
(function(){
  const $=id=>document.getElementById(id);

  function install(){
    const startField=$('v90DateStart');
    const endField=$('v90DateEnd');
    const chooser=$('v105DateFieldChooser');
    const status=$('v105DateFieldStatus');
    if(!startField||!endField) return false;

    // Candidate previews/saves still read these legacy hidden controls.
    // Keep them pinned to the standard Tableau date filter keys.
    if(startField.value!=='Start'){
      startField.value='Start';
      startField.dispatchEvent(new Event('input',{bubbles:true}));
    }
    if(endField.value!=='End'){
      endField.value='End';
      endField.dispatchEvent(new Event('input',{bubbles:true}));
    }

    const legacyGrid=startField.closest('.grid');
    if(legacyGrid) legacyGrid.style.display='none';
    if(chooser) chooser.remove();
    if(status) status.remove();

    const dateBlock=$('v104DateFilters');
    if(dateBlock){
      const helper=dateBlock.querySelector('.v106-date-helper');
      if(!helper){
        const note=document.createElement('div');
        note.className='small v106-date-helper';
        note.style.marginTop='8px';
        note.textContent='';
        dateBlock.appendChild(note);
      }
    }
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(install()) return;
      if(++tries<80) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
