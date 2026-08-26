/* v119: Starter is the default theme pack; Classic remains the plain option. */
(function(){
  function install(){
    const select=document.getElementById("tdPreset");
    if(!select) return false;

    if(!select.querySelector('option[value="starter"]')){
      const option=document.createElement("option");
      option.value="starter";
      option.textContent="Starter";
      select.insertBefore(option,select.firstChild);
    }

    const classic=select.querySelector('option[value="classic"]');
    if(classic) classic.textContent="Plain";
    const legacy=select.querySelector('option[value="undisputed"]');
    if(legacy) legacy.textContent="UNDISPUTED (existing)";
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(install()) return;
      if(++tries<160) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(start,0),{once:true});
  }else{
    setTimeout(start,0);
  }
})();
