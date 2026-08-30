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
