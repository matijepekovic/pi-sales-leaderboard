/* v106: the date picker is the only date setup the user sees.
   Tableau's Start / End filter keys are internal implementation details.
   Keep the legacy hidden controls pinned to those standard keys so existing
   preview/save logic continues to work without exposing a mapping UI. */
(function(){
  const $=id=>document.getElementById(id);

  function install(){
    const startField=$('v90DateStart');
    const endField=$('v90DateEnd');
    if(!startField||!endField) return false;

    startField.value='Start';
    endField.value='End';

    const legacyGrid=startField.closest('.grid');
    if(legacyGrid) legacyGrid.style.display='none';

    // Clean up any v105 UI if a cached page happened to create it.
    $('v105DateFieldChooser')?.remove();
    $('v105DateFieldStatus')?.remove();

    // Existing preview/save code listens to these hidden controls.
    startField.dispatchEvent(new Event('input',{bubbles:true}));
    endField.dispatchEvent(new Event('input',{bubbles:true}));
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
