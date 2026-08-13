/* v75 Close Rate by Product — BETA, remote only.

   Deliberately not a TV screen: there is no MODES entry for it, so
   /api/leaderboard has no code path to this data, and its endpoints are
   absent from PUBLIC_ENDPOINTS, so the settings lock covers them. This
   panel is the only way to see it until it is promoted. */
(function(){
  const CARD=`
    <div class="card" id="v75ProductCard">
      <h2>Close Rate by Product <span class="small">— BETA</span></h2>
      <div class="small">Not on the TV yet. Olympia, same date range as the
        board.</div>
      <div id="v75ProductRows" style="margin-top:12px"></div>
      <div class="row" style="margin-top:12px;gap:10px">
        <button id="v75ProductRefresh" class="btn" type="button">Refresh Products</button>
      </div>
      <div id="v75ProductStatus" class="small" style="margin-top:8px"></div>
    </div>`;

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  function paintProducts(rows){
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

  async function loadProducts(){
    try{
      const {r,d}=await request("/api/product-close",{cache:"no-store"});
      if(!r.ok) return;
      paintProducts(d.rows);
      $("v75ProductStatus").textContent=
        d.updated_at?`Last updated ${d.updated_at}.`:(d.status||"");
    }catch(e){}
  }

  async function refreshProducts(){
    const status=$("v75ProductStatus");
    const button=$("v75ProductRefresh");
    button.disabled=true;
    status.textContent="Pulling from Tableau…";
    try{
      const {r,d}=await request("/api/product-close/refresh",{method:"POST"});
      if(!r.ok){status.textContent=d.error||"Pull failed.";return;}
      paintProducts(d.rows);
      status.textContent=d.updated_at?`Last updated ${d.updated_at}.`:"Updated.";
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }finally{
      button.disabled=false;
    }
  }

  function mount(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("v75ProductCard")) return;
    app.insertAdjacentHTML("beforeend",CARD);
    $("v75ProductRefresh").addEventListener("click",refreshProducts);
    loadProducts();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
