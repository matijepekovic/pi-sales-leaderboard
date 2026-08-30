/* v75/v78 Close Rate by Product — BETA, remote only.

   Deliberately not a TV screen: there is no MODES entry for it, so the
   display has no code path to this data. This panel and the /preview/products
   page are the only ways to see it until it is promoted. */
(function(){
  /* Card key -> label and the asset-library key its override is stored under.
     Matches the cards in product-screen-v78.js. */
  const CARDS=[
    ["bath","Bath"],["siding","Siding"],["windows","Windows"],
    ["gutters","Gutters"],["roof","Roofs"],["overall","Overall"],
  ];
  const libKey=card=>`product_${card}`;

  const CARD=`
    <div class="card" id="v75ProductCard">
      <h2>Close Rate by Product <span class="small">— BETA</span></h2>
      <div class="small">Not on the TV yet. Olympia, same date range as the
        board.</div>
      <div id="v75ProductRows" style="margin-top:12px"></div>
      <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
        <button id="v75ProductRefresh" class="btn" type="button">Refresh Products</button>
        <button id="v78OpenPreview" class="btn primary" type="button">Open Preview</button>
      </div>
      <div id="v75ProductStatus" class="small" style="margin-top:8px"></div>

      <h3 style="margin:22px 0 4px">Card Icons</h3>
      <div class="small">Built-in icons are used unless you upload your own.
        PNG with transparency works best.</div>
      <div id="v78IconRows" style="margin-top:10px"></div>
      <div id="v78IconStatus" class="small" style="margin-top:8px"></div>
    </div>`;

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  // ------------------------------------------------------------- the rates
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
      paintIcons(d.icons||{});
      $("v75ProductStatus").textContent=
        d.updated_at?`Last updated ${d.updated_at}.`:(d.status||"");
    }catch(e){}
  }

  async function refreshProducts(){
    const status=$("v75ProductStatus"), button=$("v75ProductRefresh");
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

  // ------------------------------------------------------------- the icons
  function currentIcons(){
    return (typeof config!=="undefined"&&config&&config.product_icons)||{};
  }

  function paintIcons(icons){
    const box=$("v78IconRows");
    if(!box) return;
    const chosen=Object.keys(icons||{}).length?icons:currentIcons();
    box.innerHTML=CARDS.map(([card,label])=>{
      const url=chosen[card];
      const thumb=url
        ? `<img src="${esc(url)}" alt="" style="width:30px;height:30px;object-fit:contain">`
        : `<span class="small">built-in</span>`;
      return `
        <div class="row" style="justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #262626">
          <span style="display:flex;align-items:center;gap:10px;min-width:0">
            ${thumb}<span>${esc(label)}</span>
          </span>
          <span style="display:flex;gap:8px">
            <button class="btn v78IconPick" type="button" data-card="${card}">Upload</button>
            ${url?`<button class="btn danger v78IconClear" type="button" data-card="${card}">Clear</button>`:""}
          </span>
        </div>`;
    }).join("");
    box.querySelectorAll(".v78IconPick").forEach(b=>
      b.addEventListener("click",()=>pickIcon(b.dataset.card)));
    box.querySelectorAll(".v78IconClear").forEach(b=>
      b.addEventListener("click",()=>saveIcon(b.dataset.card,"")));
  }

  async function saveIcon(card,url){
    const status=$("v78IconStatus");
    const icons={...currentIcons()};
    if(url) icons[card]=url; else delete icons[card];
    status.textContent="Saving…";
    try{
      const {r,d}=await request("/api/config",{
        method:"PUT",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...config,product_icons:icons})});
      if(!r.ok){status.textContent=d.error||"Could not save.";return;}
      config=d.settings;
      paintIcons(config.product_icons||{});
      status.textContent=url?"Icon saved.":"Back to the built-in icon.";
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }
  }

  /* Upload straight into the existing asset library, then point the card at
     the URL it returns. No new storage, no new endpoint. */
  function pickIcon(card){
    const status=$("v78IconStatus");
    const input=document.createElement("input");
    input.type="file";
    // The library accepts PNG, JPG and WEBP only (themes.py VALID_EXTENSIONS).
    input.accept="image/png,image/jpeg,image/webp";
    input.style.display="none";
    document.body.appendChild(input);
    input.addEventListener("change",async()=>{
      const file=input.files&&input.files[0];
      input.remove();
      if(!file) return;
      status.textContent=`Uploading ${file.name}…`;
      try{
        const form=new FormData();
        // The library endpoint reads the "asset" field (themes.py:463).
        form.append("asset",file);
        form.append("label",file.name);
        const {r,d}=await request(`/api/asset-library/${libKey(card)}`,
          {method:"POST",body:form});
        if(!r.ok||!d.url){status.textContent=d.error||"Upload failed.";return;}
        await saveIcon(card,d.url);
      }catch(e){
        if(e.message!=="locked") status.textContent="Could not reach the Pi.";
      }
    });
    input.click();
  }

  // ------------------------------------------------------------------ mount
  function mount(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("v75ProductCard")) return;
    app.insertAdjacentHTML("beforeend",CARD);
    $("v75ProductRefresh").addEventListener("click",refreshProducts);
    $("v78OpenPreview").addEventListener("click",()=>
      window.open("/preview/products","_blank"));
    paintIcons({});
    loadProducts();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
