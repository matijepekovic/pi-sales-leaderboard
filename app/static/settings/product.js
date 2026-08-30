/* Product -- the Product Close Rates panel and its market picker.

   Consolidated from the settings patch stack. Each section below was its own
   file and they are concatenated in their original load order, so what runs
   when is unchanged -- several of these mount by polling for a node the
   previous one creates. */


/* ------------------------------------------------------------------
   product-settings.js
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   product-market.js
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   number-size.js
   ------------------------------------------------------------------ */
/* v75 Number Size control (remote side).

   Per-screen +/- for the size of the numbers on the TV. Writes
   number_font_scale[<active mode>] through the ordinary /api/config save,
   which bumps settings_version — already part of the display's render
   signature — so the board picks it up on its next poll.

   The display half of this lives in number-scale-v75.js. */
(function(){
  const MIN=60,MAX=300,STEP=10;

  const CARD=`
    <div class="card" id="v75NumCard">
      <h2>Number Size</h2>
      <div class="small">Sizes the numbers on the TV only — names, headings
        and the table layout are untouched. Saved per screen.</div>
      <div class="row" style="align-items:center;gap:12px;margin-top:12px">
        <button id="v75NumMinus" class="btn" type="button" aria-label="Smaller numbers">Font −</button>
        <div id="v75NumValue" class="strong" style="min-width:150px;text-align:center">100%</div>
        <button id="v75NumPlus" class="btn" type="button" aria-label="Bigger numbers">Font +</button>
      </div>
      <div id="v75NumScreen" class="small" style="margin-top:8px"></div>
      <div id="v75NumStatus" class="small" style="margin-top:4px"></div>
    </div>`;

  const $=id=>document.getElementById(id);

  function configReady(){
    return typeof config!=="undefined" && config && config.active_mode;
  }

  function activeMode(){
    try{ return parseActive(config.active_mode).mode||"whole_office"; }
    catch(_){ return "whole_office"; }
  }

  function currentScale(){
    const map=(config&&config.number_font_scale)||{};
    const value=Number(map[activeMode()]);
    return Number.isFinite(value)?Math.min(Math.max(value,MIN),MAX):100;
  }

  function paintScale(){
    const box=$("v75NumValue");
    if(!box||!configReady()) return;
    const value=currentScale();
    box.textContent=`${value}%`;
    $("v75NumMinus").disabled=value<=MIN;
    $("v75NumPlus").disabled=value>=MAX;
    // Name the screen being changed, so it is never ambiguous which one
    // these buttons are moving. This is the *saved* active mode -- the
    // screen actually on the TV -- not an unsaved dropdown selection.
    $("v75NumScreen").textContent=
      `Applies to: ${activeLabel(config.active_mode)}`;
  }

  /* The settings page fetches its config after load, so this can mount
     before there is anything to show. Paint as soon as it lands. */
  function paintWhenReady(){
    let tries=0;
    (function attempt(){
      if(configReady()){ paintScale(); return; }
      if(++tries>60) return;
      setTimeout(attempt,150);
    })();
  }

  async function nudge(delta){
    const next=Math.min(Math.max(currentScale()+delta,MIN),MAX);
    const mode=activeMode();
    const status=$("v75NumStatus");
    status.textContent="Saving…";
    const payload={...config,
      number_font_scale:{...(config.number_font_scale||{}),[mode]:next}};
    try{
      const {r,d}=await request("/api/config",{
        method:"PUT",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload)});
      if(!r.ok){status.textContent=d.error||"Could not save.";return;}
      config=d.settings;
      paintScale();
      status.textContent="Saved. The TV updates on its next refresh.";
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }
  }

  function mount(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("v75NumCard")) return;
    app.insertAdjacentHTML("beforeend",CARD);
    $("v75NumMinus").addEventListener("click",()=>nudge(-STEP));
    $("v75NumPlus").addEventListener("click",()=>nudge(STEP));
    paintWhenReady();
  }

  // Saving from the main Settings button can move the active screen, and the
  // size is per screen, so re-read once that save has landed.
  document.addEventListener("click",event=>{
    if(event.target && event.target.id==="save") setTimeout(paintScale,900);
  });

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
