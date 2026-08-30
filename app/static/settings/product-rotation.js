/* v115: add Product Close Rates to View > Screens in Rotation.
   controls-v112 owns the existing save button, so this only contributes the
   extra checkbox and lets the same backend save path handle it. */
(function(){
  const VALUE="product_close";
  let selected=true;
  let list=null;

  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  async function readSelected(){
    try{
      const response=await fetch("/api/config",{cache:"no-store"});
      if(!response.ok) return;
      const data=await response.json();
      const raw=data?.settings?.keyboard_cycle_views;
      selected=!Array.isArray(raw)||!raw.length||raw.map(String).includes(VALUE);
    }catch(_){ }
  }

  function ensure(){
    list=document.getElementById("v112RotationList");
    if(!list) return false;
    if(list.querySelector(`input[value="${VALUE}"]`)) return true;

    const label=document.createElement("label");
    label.className="check";
    label.style.margin="0";
    label.innerHTML=`<input class="v112RotationView" type="checkbox" value="${esc(VALUE)}" ${selected?"checked":""}>
      <span>Product Close Rates</span>`;

    const teamRow=Array.from(list.querySelectorAll("label.check")).find(row=>
      String(row.textContent||"").trim().startsWith("Team —")
    );
    if(teamRow) list.insertBefore(label,teamRow);
    else list.appendChild(label);
    return true;
  }

  function start(){
    readSelected().finally(()=>{
      let tries=0;
      (function attempt(){
        if(ensure()){
          const observer=new MutationObserver(()=>ensure());
          observer.observe(list,{childList:true});
          return;
        }
        if(++tries<140) setTimeout(attempt,50);
      })();
    });
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();
})();
