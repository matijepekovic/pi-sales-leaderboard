/* Production Settings shell. */
(function(){
  function addBackButton(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("backToStats")) return !!app;
    const row=document.createElement("div");
    row.id="statsSettingsBackRow";
    row.style.cssText="display:flex;justify-content:flex-start;margin:0 0 12px";
    const button=document.createElement("button");
    button.id="backToStats";
    button.type="button";
    button.className="btn";
    button.textContent="← Back to Stats";
    button.setAttribute("aria-label","Back to Stats");
    button.addEventListener("click",()=>window.location.assign("/"));
    row.appendChild(button);
    app.insertBefore(row,app.firstChild);
    return true;
  }
  function start(){
    let tries=0;
    (function attempt(){
      if(addBackButton()) return;
      if(++tries<60) setTimeout(attempt,50);
    })();
  }
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();
})();
