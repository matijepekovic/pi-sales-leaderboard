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
