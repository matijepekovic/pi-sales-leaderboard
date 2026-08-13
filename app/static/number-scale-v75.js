/* v75 number size, per screen.

   Resizes the stat numbers and nothing else — not the rank, not the rep
   names, not the column headings, not the titles.

   Two things this has to work around:

   1. fmt() is not a usable seam. It returns a plain string that some views
      interpolate into innerHTML but others hand to el.textContent
      (comparison-team-cards-v53.js:22 builds its cells that way), so markup
      wrapped around a number shows up as literal "<span ...>" text there.

   2. table-readability-v72.js sizes the themed views with !important rules
      driven by its own --v72-* variables, which it recomputes from the live
      row height after every render. An inline font-size loses to those, and
      pinning one would defeat v72's fitting.

   So this is pure CSS that *multiplies* whatever those rules resolve to.
   It composes with v72 instead of fighting it: v72 keeps deciding the base
   size for the current row height, and this scales that result.

   At 100% every declaration below computes to exactly the value it has
   today, so the board is unchanged until the size is actually moved. */
(function(){
  const MIN=60,MAX=160;
  const STYLE_ID="v75-number-scale";

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      /* Themed views: multiply the size v72 computed for the stat cells.
         The doubled class raises specificity above v72's own !important
         rule, so this wins no matter which stylesheet lands first. Name,
         rank and head rules are deliberately not repeated — those keep
         v72's size untouched. */
      #themedTeamBroadcast .bt-stat.bt-stat,
      #themedTeamBroadcast .bt-total-v.bt-total-v{
        font-size:calc(var(--v72-team-stat,12px) * var(--v75-num-scale,1))!important}

      #v55OfficeBroadcast .v55-office-stat.v55-office-stat,
      #v55OfficeBroadcast .v55-office-total-v.v55-office-total-v{
        font-size:calc(var(--v72-office-stat,11px) * var(--v75-num-scale,1))!important}

      .v69-team-card .v69-stat.v69-stat,
      .v69-team-card .v69-total-v.v69-total-v{
        font-size:calc(var(--v72-comp-stat,10px) * var(--v75-num-scale,1))!important}

    `;
    document.head.appendChild(style);
  }

  /* Value cells that v72 does not manage: the classic table's number cells
     and the whole-office team-card KPIs. Their size comes from ordinary
     rules with no !important, so an inline style wins cleanly — and reading
     the computed size gives the exact base rather than a restated guess.
     render() rebuilds these nodes every pass, so the value read here is
     always the layout's own, never a previous pass's inline result. */
  const PLAIN_SELECTOR="#content td.number,.v55-card-kpi-v";

  function scalePlainCells(factor){
    if(factor===1) return;          /* at 100% nothing is written at all */
    document.querySelectorAll(PLAIN_SELECTOR).forEach(el=>{
      const base=parseFloat(getComputedStyle(el).fontSize);
      if(Number.isFinite(base)) el.style.fontSize=(base*factor)+"px";
    });
  }

  function scaleFromData(data){
    let percent=Number(data&&data.number_font_scale);
    if(!Number.isFinite(percent)) percent=100;
    return Math.min(Math.max(percent,MIN),MAX)/100;
  }

  const baseRender=window.render;
  if(typeof baseRender==="function"){
    window.render=function(data){
      const result=baseRender.apply(this,arguments);
      try{
        const factor=scaleFromData(data);
        /* Inject nothing at all while the size is untouched, so a board at
           100% is byte-for-byte what it was before this file existed. */
        if(factor!==1) ensureStyles();
        document.documentElement.style.setProperty("--v75-num-scale",factor);
        scalePlainCells(factor);
        /* The board auto-fits itself; re-run that now the numbers have
           their final size. */
        if(factor!==1&&typeof fitLeaderboard==="function") setTimeout(fitLeaderboard,0);
      }catch(_){}
      return result;
    };
  }
})();
