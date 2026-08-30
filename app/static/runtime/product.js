/* Product runtime -- the Product Close Rates screen.

   A full-screen overlay. Its stage is the outermost one and it
   returns without calling next(), so in product mode none of the
   screen, theme or layout passes run against a hidden board.

   Consolidated from the versioned patch stack. Each section below was its own
   file, wrapping the previous one by reassigning render(). They now register
   ordered stages instead, so this grouping is presentation only -- the
   execution order is the numbers, not the file boundaries. */


/* ------------------------------------------------------------------
   product-screen.js   (stage/style order 290)
   ------------------------------------------------------------------ */
/* v78 Product Close Rates screen.

   Standalone on purpose: one function draws the whole screen into a
   container. Today it is only mounted by the preview page. Promoting it to
   the TV later is a MODES entry plus a call to this same function -- no
   rework, and nothing here assumes it is or isn't on the board.

   Everything is sized in viewport units. The rest of the board caps its
   fonts with absolute pixels (table-readability-v72.js uses
   clamp(h*.245, 11, 19)), which is why it renders half-size on a 4K panel.
   This screen must not repeat that. */
(function(){
  const OVERALL="Overall";

  /* Card order and colour. Overall last, and deliberately not rate-ranked --
     these are fixed product lines, not a leaderboard. Siding's teal is the
     one colour the mockup did not specify. */
  const CARDS=[
    {key:"bath",    label:"Bath",    colour:"#1f7ae0"},
    {key:"siding",  label:"Siding",  colour:"#0f9b8e"},
    {key:"windows", label:"Windows", colour:"#2e9e3f"},
    {key:"gutters", label:"Gutters", colour:"#8b5cf6"},
    {key:"roof",    label:"Roofs",   colour:"#e8821e"},
    {key:"overall", label:"Overall", colour:"#5b6b80", muted:true},
  ];

  /* Tableau's product names differ from the card labels ("Roof" vs
     "Roofs"), so match on a normalised key rather than the display text. */
  const norm=s=>String(s||"").toLowerCase().replace(/[^a-z]/g,"");
  const ALIASES={bath:"bath",baths:"bath",siding:"siding",window:"windows",
    windows:"windows",gutter:"gutters",gutters:"gutters",roof:"roof",
    roofs:"roof",roofing:"roof",overall:"overall",all:"overall"};

  /* Inline SVG so the glyphs stay sharp at 4K with nothing to upload.
     Single-path shapes, drawn on a 24-unit grid, filled with currentColor. */
  const GLYPHS={
    bath:'<path d="M4 12V6a2 2 0 0 1 4 0v1M2 12h20v2a5 5 0 0 1-5 5H7a5 5 0 0 1-5-5v-2Zm3 7-1 2m15-2 1 2"/>',
    siding:'<path d="M3 5h18M3 10h18M3 15h18M3 20h18M8 5v5m8-5v5M12 10v5m-6 5v-5m12 5v-5"/>',
    windows:'<path d="M4 4h16v16H4zM12 4v16M4 12h16"/>',
    gutters:'<path d="M3 7h18v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Zm4 6v3m5-3v5m5-5v3"/>',
    roof:'<path d="M2 13 12 5l10 8M6 13v7h12v-7"/>',
    overall:'<path d="M5 20V10m7 10V4m7 16v-7"/>',
  };

  function icon(key,url){
    if(url) return `<img class="v78-icon-img" src="${url}" alt="">`;
    return `<svg class="v78-icon-svg" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="1.9" stroke-linecap="round"
      stroke-linejoin="round" aria-hidden="true">${GLYPHS[key]||GLYPHS.overall}</svg>`;
  }

  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  /* "2026-08-01","2026-08-31" -> "Aug 1 – Aug 31, 2026" */
  function rangeLabel(start,end){
    const MONTHS=["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"];
    const part=iso=>{
      const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso||"").trim());
      if(!m) return null;
      return {y:m[1], t:`${MONTHS[Number(m[2])-1]} ${Number(m[3])}`};
    };
    const a=part(start), b=part(end);
    if(!a||!b) return "";
    return a.y===b.y ? `${a.t} – ${b.t}, ${a.y}`
                     : `${a.t}, ${a.y} – ${b.t}, ${b.y}`;
  }

  const STYLE=`
    .v78-screen{
      --v78-pad:3.2vh;
      position:absolute;inset:0;display:flex;flex-direction:column;
      box-sizing:border-box;padding:var(--v78-pad) 3.2vw;
      background:#0b1220;color:#fff;
      font-family:Arial,Helvetica,sans-serif;overflow:hidden}
    .v78-title{font-size:4.4vh;font-weight:900;letter-spacing:.02em;margin:0}
    .v78-range{display:flex;align-items:center;gap:.9vh;
      margin-top:1.1vh;font-size:2.1vh;color:#8fa3bf}
    .v78-range svg{width:2.1vh;height:2.1vh}

    .v78-cards{
      flex:1 1 auto;display:grid;gap:1.6vw;margin-top:4vh;
      /* Cards take their content height and the row sits centred in the
         space below the header, rather than stretching to the floor. */
      align-content:center;
      grid-template-columns:repeat(var(--v78-count,6),minmax(0,1fr))}
    .v78-card{
      display:flex;flex-direction:column;align-items:center;
      justify-content:flex-start;gap:2.2vh;
      padding:3.4vh 1vw;border-radius:1.6vh;
      background:#111c2e;border:1px solid #1e2c43;min-width:0}
    .v78-card.is-overall{background:#0e1726}

    .v78-icon{
      display:grid;place-items:center;
      width:9.5vh;height:9.5vh;border-radius:2vh;color:#fff}
    .v78-icon-svg{width:5.6vh;height:5.6vh}
    .v78-icon-img{width:6.4vh;height:6.4vh;object-fit:contain}

    .v78-name{font-size:2.4vh;font-weight:800;letter-spacing:.06em;
      text-transform:uppercase;text-align:center;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
    .v78-value{display:flex;align-items:baseline;justify-content:center;
      font-weight:900;line-height:1}
    .v78-num{font-size:9vh;font-variant-numeric:tabular-nums}
    .v78-pct{font-size:4.2vh;margin-left:.4vh}
    .v78-caption{font-size:1.9vh;letter-spacing:.08em;color:#8fa3bf;
      text-transform:uppercase}
    .v78-empty{margin:auto;font-size:2.6vh;color:#8fa3bf}
  `;

  const CALENDAR='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'+
    ' stroke-width="2" stroke-linecap="round"><rect x="3" y="5" width="18"'+
    ' height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></svg>';

  function ensureStyle(doc){
    if(doc.getElementById("v78-style")) return;
    const style=doc.createElement("style");
    style.id="v78-style";
    style.textContent=STYLE;
    doc.head.appendChild(style);
  }

  /* data: { rows:[{product, close_rate}], start, end, icons:{key:url} } */
  function renderProductScreen(container,data){
    if(!container) return;
    ensureStyle(container.ownerDocument||document);

    const byKey={};
    ((data&&data.rows)||[]).forEach(row=>{
      const key=ALIASES[norm(row.product)];
      if(key) byKey[key]=row;
    });
    const icons=(data&&data.icons)||{};

    const present=CARDS.filter(card=>byKey[card.key]);
    const range=rangeLabel(data&&data.start,data&&data.end);

    const header=
      `<h1 class="v78-title">PRODUCT CLOSE RATES</h1>`+
      (range?`<div class="v78-range">${CALENDAR}<span>${esc(range)}</span></div>`:"");

    if(!present.length){
      container.innerHTML=
        `<div class="v78-screen">${header}`+
        `<div class="v78-empty">No product data pulled yet.</div></div>`;
      return;
    }

    const cards=present.map(card=>{
      const value=Number(byKey[card.key].close_rate||0);
      return `
        <div class="v78-card${card.muted?" is-overall":""}">
          <div class="v78-icon" style="background:${card.colour}">
            ${icon(card.key,icons[card.key])}
          </div>
          <div class="v78-name" style="color:${card.muted?"#c7d3e3":card.colour}">
            ${esc(card.label)}
          </div>
          <div class="v78-value">
            <span class="v78-num">${value.toFixed(1)}</span><span class="v78-pct">%</span>
          </div>
          <div class="v78-caption">Close Rate</div>
        </div>`;
    }).join("");

    container.innerHTML=
      `<div class="v78-screen">${header}`+
      `<div class="v78-cards" style="--v78-count:${present.length}">${cards}</div>`+
      `</div>`;
  }

  window.renderProductScreen=renderProductScreen;
})();


/* ------------------------------------------------------------------
   product-market.js   (stage/style order 300)
   ------------------------------------------------------------------ */
/* v115: annotate the existing Product Close Rates renderer with market context. */
(function(){
  if(typeof window.renderProductScreen!=="function") return;
  const base=window.renderProductScreen;

  function ensureStyle(doc){
    if(doc.getElementById("v115-product-context-style")) return;
    const style=doc.createElement("style");
    style.id="v115-product-context-style";
    style.textContent=`
      .v115-product-context{position:absolute;top:3.2vh;right:3.2vw;
        display:flex;align-items:center;gap:.8vh;max-width:38vw;
        padding:.75vh 1.05vw;border:1px solid #263852;border-radius:999px;
        background:rgba(9,18,32,.88);color:#d7e4f6;font-size:1.85vh;
        font-weight:800;letter-spacing:.04em;white-space:nowrap;overflow:hidden;
        text-overflow:ellipsis}
      .v115-product-temp{color:#f4c95d}
    `;
    doc.head.appendChild(style);
  }

  window.renderProductScreen=function(container,data){
    base(container,data);
    if(!container) return;
    const doc=container.ownerDocument||document;
    ensureStyle(doc);
    const screen=container.querySelector(".v78-screen");
    if(!screen) return;
    const market=String(data?.market||"").trim();
    if(!market) return;
    const badge=doc.createElement("div");
    badge.className="v115-product-context";
    const temp=data?.temporary?'<span class="v115-product-temp">TEMP</span> · ':"";
    badge.innerHTML=`${temp}<span>${String(market).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}</span>`;
    screen.appendChild(badge);
  };
})();


/* ------------------------------------------------------------------
   product-tv.js   (stage/style order 310)
   ------------------------------------------------------------------ */
/* v115: promote the existing Product Close Rates preview renderer to the TV.
   It is a full-screen overlay so none of the rep/team layout rules can affect
   the product cards. The QR overlay remains above it. */
(function(){
  if(typeof window.renderProductScreen!=="function"||typeof window.render!=="function") return;
  let overlay=null;
  let lastProductSignature="";

  function ensureOverlay(){
    if(overlay) return overlay;
    overlay=document.createElement("div");
    overlay.id="productTvV115";
    overlay.style.cssText=[
      "position:fixed","inset:0","z-index:2147482000","display:none",
      "background:#0b1220","pointer-events:none","overflow:hidden"
    ].join(";");
    overlay.setAttribute("aria-hidden","true");
    document.body.appendChild(overlay);
    return overlay;
  }

  Display.stage(310, function(data, next){
    if(data?.mode==="product_close"){
      const root=ensureOverlay();
      root.style.display="block";
      const productData={
        rows:data.rows||[],
        start:data.product_start||"",
        end:data.product_end||"",
        market:data.product_market||"",
        icons:data.product_icons||{},
        temporary:!!data.product_temporary
      };
      const signature=JSON.stringify([
        productData.rows.map(row=>[row.product,Number(row.close_rate||0)]),
        productData.start,productData.end,productData.market,
        productData.icons,productData.temporary
      ]);
      if(signature!==lastProductSignature){
        window.renderProductScreen(root,productData);
        lastProductSignature=signature;
      }
      return;
    }
    lastProductSignature="";
    if(overlay) overlay.style.display="none";
    return next(data);
  });
})();
