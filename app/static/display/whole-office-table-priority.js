/* v73 Whole Office table-first vertical sizing.
   Whole Office only. The saved Hero Size remains the preferred size, but the
   hero yields vertical room before readable table rows do. Other views are
   intentionally untouched. */
(function(){
  if(typeof render!=="function") return;

  const clamp=(value,min,max)=>Math.min(max,Math.max(min,Number(value)||min));
  const px=value=>{
    const n=parseFloat(value);
    return Number.isFinite(n)?n:0;
  };

  function applyOfficePriority(){
    const root=document.getElementById("v55OfficeBroadcast");
    if(!root) return;
    const rows=[...root.querySelectorAll(".v55-office-row")];
    if(!rows.length) return;

    const viewport=Math.max(window.innerHeight||0,480);
    if(!root.dataset.v73PreferredBrand){
      const requested=px(root.style.getPropertyValue("--v55-office-brand-h"));
      root.dataset.v73PreferredBrand=String(requested||Math.max(190,Math.min(420,viewport*.19)));
    }
    const preferredHero=px(root.dataset.v73PreferredBrand);

    /* On the 4K TV this targets about 65px normal rows. At lower resolutions
       it bottoms out at 56px. v71 still owns the absolute 38-82px safety
       bounds if the office ever contains more reps than can fit even after the
       hero reaches its minimum. */
    const targetRow=clamp(viewport*.03,56,68);
    const minimumHero=Math.min(preferredHero,clamp(viewport*.07,96,160));

    const head=root.querySelector(".v55-office-head");
    const footer=root.querySelector(".v55-office-footer");
    const headHeight=head?.getBoundingClientRect().height||30;
    const footerHeight=footer?.getBoundingClientRect().height||0;
    let footerMargins=0;
    if(footer){
      const css=getComputedStyle(footer);
      footerMargins=px(css.marginTop)+px(css.marginBottom);
    }

    const championCount=rows.filter(row=>row.classList.contains("champion")).length;
    const rowWeight=rows.length+(championCount*.18);
    const safety=Math.max(12,viewport*.008);
    const fixedHeight=headHeight+footerHeight+footerMargins+safety;

    /* First ask how much hero can remain while preserving the target table
       size. Only if that answer is smaller than the theme request do we shrink
       the hero. */
    const heroRoomForTarget=viewport-fixedHeight-(targetRow*rowWeight);
    const heroHeight=Math.min(preferredHero,Math.max(minimumHero,heroRoomForTarget));

    /* After the hero has yielded, let the normal adaptive row calculation use
       all remaining table room. v71 clamps the final visual row size. */
    const availableForRows=Math.max(1,viewport-heroHeight-fixedHeight);
    const rowHeight=availableForRows/Math.max(rowWeight,1);

    root.style.setProperty("--v55-office-brand-h",`${heroHeight.toFixed(2)}px`);
    root.style.setProperty("--v55-office-row-h",`${rowHeight.toFixed(2)}px`);
  }

  Display.stage(250, function(data, next){
    const result=next(data);
    if(data?.mode==="whole_office") applyOfficePriority();
    return result;
  });

  window.addEventListener("resize",()=>requestAnimationFrame(applyOfficePriority));
})();
