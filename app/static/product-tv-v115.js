/* v115: promote the existing Product Close Rates preview renderer to the TV.
   It is a full-screen overlay so none of the rep/team layout rules can affect
   the product cards. The QR overlay remains above it. */
(function(){
  if(typeof window.renderProductScreen!=="function"||typeof window.render!=="function") return;
  const baseRender=window.render;
  let overlay=null;

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

  window.render=function(data){
    if(data?.mode==="product_close"){
      const root=ensureOverlay();
      root.style.display="block";
      window.renderProductScreen(root,{
        rows:data.rows||[],
        start:data.product_start||"",
        end:data.product_end||"",
        market:data.product_market||"",
        icons:data.product_icons||{},
        temporary:!!data.product_temporary
      });
      return;
    }
    if(overlay) overlay.style.display="none";
    return baseRender(data);
  };
})();
