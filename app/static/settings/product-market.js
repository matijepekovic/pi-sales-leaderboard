/* v115 Product Close Rates market selector.
   The legacy product card still owns icons/preview/manual refresh. This patch
   adds one phone-friendly market dropdown and promotes the card out of beta. */
(function(){
  const $=id=>document.getElementById(id);
  let lastMarket="";

  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  function paintRows(rows){
    const box=$("v75ProductRows");
    if(!box) return;
    if(!rows||!rows.length){
      box.innerHTML='<div class="small">No product data pulled yet.</div>';
      return;
    }
    box.innerHTML=rows.map(row=>`
      <div class="row" style="justify-content:space-between;padding:7px 0;border-bottom:1px solid #262626">
        <span>${esc(row.product)}</span>
        <strong>${Number(row.close_rate||0).toFixed(2)}%</strong>
      </div>`).join("");
  }

  function statusFor(data){
    if(data?.temporary){
      const minutes=Math.max(1,Math.ceil(Number(data.seconds_left||0)/60));
      return `${data.market} · temporary ${data.start} to ${data.end} · about ${minutes} min left`;
    }
    if(data?.market && data?.start && data?.end){
      return `${data.market} · ${data.start} to ${data.end}${data.updated_at?` · updated ${data.updated_at}`:""}`;
    }
    return data?.status||"";
  }

  async function loadCurrent(){
    try{
      const response=await fetch("/api/product-close",{cache:"no-store"});
      if(!response.ok) return;
      const data=await response.json();
      paintRows(data.rows||[]);
      lastMarket=String(data.market||lastMarket||"");
      const select=$("v115ProductMarket");
      if(select&&lastMarket&&Array.from(select.options).some(o=>o.value===lastMarket)){
        select.value=lastMarket;
      }
      const status=$("v75ProductStatus");
      if(status) status.textContent=statusFor(data);
    }catch(_){ }
  }

  async function loadMarkets(){
    const select=$("v115ProductMarket"),status=$("v75ProductStatus");
    if(!select) return;
    select.disabled=true;
    try{
      const response=await fetch("/api/product-markets",{cache:"no-store"});
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false) throw new Error(data.error||"Could not load markets.");
      const markets=(data.markets||[]).map(String).filter(Boolean);
      select.innerHTML=markets.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join("");
      lastMarket=String(data.selected||lastMarket||markets[0]||"");
      if(lastMarket) select.value=lastMarket;
      if(data.warning&&status) status.textContent=`Using saved market list. ${data.warning}`;
    }catch(e){
      if(status) status.textContent=e.message||"Could not load markets.";
    }finally{
      select.disabled=false;
    }
  }

  async function chooseMarket(){
    const select=$("v115ProductMarket"),status=$("v75ProductStatus");
    if(!select||!select.value) return;
    const previous=lastMarket;
    const market=select.value;
    select.disabled=true;
    if(status) status.textContent=`Pulling ${market} from Tableau…`;
    try{
      const response=await fetch("/api/product-market",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({market})
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false) throw new Error(data.error||`Could not load ${market}.`);
      lastMarket=String(data.market||market);
      select.value=lastMarket;
      paintRows(data.rows||[]);
      if(status) status.textContent=statusFor(data);
    }catch(e){
      if(previous) select.value=previous;
      if(status) status.textContent=e.message||"Could not change market.";
    }finally{
      select.disabled=false;
    }
  }

  function mount(){
    const card=$("v75ProductCard");
    if(!card||$("v115ProductMarket")) return !!$("v115ProductMarket");

    const heading=card.querySelector("h2");
    if(heading) heading.textContent="Product Close Rates";
    const intro=heading?.nextElementSibling;
    if(intro&&intro.classList.contains("small")){
      intro.textContent="Choose a market. Temporary Date Override applies here too, and this screen is available in TV rotation.";
    }

    const block=document.createElement("div");
    block.id="v115ProductMarketBlock";
    block.style.marginTop="14px";
    block.innerHTML=`
      <label for="v115ProductMarket">Market</label>
      <select id="v115ProductMarket"><option>Loading markets…</option></select>`;
    if(intro) intro.insertAdjacentElement("afterend",block);
    else card.insertBefore(block,card.firstChild);

    $("v115ProductMarket").addEventListener("change",chooseMarket);
    loadMarkets().then(loadCurrent);
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(mount()) return;
      if(++tries<120) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
