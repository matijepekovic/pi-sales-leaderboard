/* v60 settings presentation cleanup.
   VISUAL ONLY: legacy title/subtitle/TV polling values remain in config, but
   are no longer shown in Settings. TV Controls is moved to the top. */
(function(){
  function fieldWrap(id){
    const el=document.getElementById(id);
    if(!el) return null;
    const parent=el.parentElement;
    return parent && parent !== document.body ? parent : el;
  }

  function apply(){
    const app=document.getElementById("appWrap");
    if(!app) return;

    ["title","subtitle","refresh"].forEach(id=>{
      const wrap=fieldWrap(id);
      if(wrap) wrap.style.display="none";
    });

    const active=document.getElementById("activeMode");
    if(active?.parentElement){
      active.parentElement.style.gridColumn="1 / -1";
    }

    const tvCard=[...app.querySelectorAll(":scope > .card")].find(card=>
      card.querySelector("h2")?.textContent.trim()==="TV Controls"
    );
    const note=app.querySelector(".persist-note");
    if(tvCard && note && note.nextElementSibling!==tvCard){
      note.insertAdjacentElement("afterend",tvCard);
    }

    const dataCard=[...app.querySelectorAll(":scope > .card")].find(card=>
      card.querySelector("h2")?.textContent.trim()==="Data Source"
    );
    if(dataCard && !document.getElementById("v60TableauScheduleNote")){
      const schedule=document.createElement("div");
      schedule.id="v60TableauScheduleNote";
      schedule.className="small";
      schedule.style.margin="10px 0 0";
      schedule.innerHTML="Automatic Tableau pulls: <strong>6:00 AM</strong> and <strong>2:00 PM</strong> every day (Pi local time).";
      const heading=dataCard.querySelector("h2");
      if(heading) heading.insertAdjacentElement("afterend",schedule);
    }
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",apply,{once:true});
  else apply();
})();
