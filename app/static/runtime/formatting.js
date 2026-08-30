/* Formatting runtime -- how numbers read from across the room.

   Font sizing measured off live row height, the tracked-stat
   underline, and the per-screen number scale. The order inside
   this file is load-bearing: number-scale multiplies the
   variables table-readability computes rather than replacing
   them, and outranks its !important rules by doubling class
   selectors.

   Consolidated from the versioned patch stack. Each section below was its own
   file, wrapping the previous one by reassigning render(). They now register
   ordered stages instead, so this grouping is presentation only -- the
   execution order is the numbers, not the file boundaries. */


/* ------------------------------------------------------------------
   runtime/formatting.js   (order 10 -- the value formatter itself)
   ------------------------------------------------------------------ */
/* Display formatting runtime.
   Preserve Tableau precision: split counts may be fractional, rates use two
   decimals and currency calculations retain cents. */
fmt = function(v, type, symbol="$" ){
  const n = Number(v || 0);
  if(type === "currency"){
    return symbol + n.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }
  if(type === "percent") return n.toFixed(2) + "%";
  if(type === "number"){
    return n.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2
    });
  }
  return esc(v);
};


/* ------------------------------------------------------------------
   totals-font.js   (stage/style order 60)
   ------------------------------------------------------------------ */
/* v47 presentation-only totals sizing.
   Team totals use the exact same font-size rules as rep stat cells so long
   currency values cannot overflow simply because totals were oversized. */
(function(){
  const style=document.createElement("style");
  style.id="v47TotalsFontFix";
  style.textContent=`
    #themedTeamBroadcast .bt-total-v{
      font-size:clamp(10px,.88vw,16px)!important;
    }
    #themedTeamBroadcast.dense .bt-total-v{
      font-size:clamp(9px,.76vw,13px)!important;
    }
  `;
  Display.placeStyle(60, style);
})();


/* ------------------------------------------------------------------
   table-readability.js   (stage/style order 260)
   ------------------------------------------------------------------ */
/* v72 table readability and table-bound totals.
   Presentation only. Row height remains bounded by v71; this layer makes text
   scale with the rendered row, removes old 1810/1870px width caps, reduces
   cell padding, and keeps comparison totals directly under the last row. */
(function(){
  if(typeof render!=="function") return;
  const STYLE_ID="tableReadabilityV72Styles";
  let scheduled=false;

  const clamp=(v,a,b)=>Math.min(b,Math.max(a,Number(v)||a));
  const median=values=>{
    const xs=values.filter(Number.isFinite).sort((a,b)=>a-b);
    if(!xs.length)return 0;
    const i=Math.floor(xs.length/2);
    return xs.length%2?xs[i]:(xs[i-1]+xs[i])/2;
  };
  const rowHeight=(root,selector,championSelector)=>{
    const normal=[...root.querySelectorAll(selector)]
      .filter(el=>!championSelector||!el.matches(championSelector))
      .map(el=>el.getBoundingClientRect().height)
      .filter(h=>h>1);
    if(normal.length)return median(normal);
    const champ=championSelector?root.querySelector(championSelector):null;
    const h=champ?.getBoundingClientRect().height||0;
    return h>1?h/1.16:0;
  };
  const setPx=(root,name,value)=>root.style.setProperty(name,`${value.toFixed(2)}px`);

  function ensureStyles(){
    if(document.getElementById(STYLE_ID))return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      /* Background art is always the back plane. Hero/logo and table content
         live in explicit higher stacking contexts so background artwork can
         never visually layer over the team identity. A soft theme-colour
         shield behind the hero prevents busy background detail showing through
         transparent logo margins. */
      #themedTeamBroadcast,#v55OfficeBroadcast,.v69-team-card{isolation:isolate!important}
      #themedTeamBroadcast .bt-bg,#v55OfficeBroadcast .v55-office-bg,.v69-team-card .v69-card-bg{z-index:0!important;pointer-events:none!important}
      #themedTeamBroadcast .bt-atmosphere,#v55OfficeBroadcast .v55-office-atmosphere,.v69-team-card .v69-card-atmosphere{z-index:1!important;pointer-events:none!important}
      #themedTeamBroadcast .bt-header,#v55OfficeBroadcast .v55-office-brand,.v69-team-card .v69-brand{isolation:isolate!important;z-index:6!important}
      #themedTeamBroadcast .bt-main,#v55OfficeBroadcast .v55-office-main,.v69-team-card .v69-main{z-index:5!important}
      #themedTeamBroadcast .bt-header:before,#v55OfficeBroadcast .v55-office-brand:before,.v69-team-card .v69-brand:before{
        content:"";position:absolute;inset:0 16%;z-index:0;pointer-events:none;
        background:radial-gradient(ellipse at center,color-mix(in srgb,currentColor 0%,var(--bt-bg,#070706)) 0%,color-mix(in srgb,var(--bt-bg,#070706) 78%,transparent) 54%,transparent 82%)
      }
      #v55OfficeBroadcast .v55-office-brand:before{background:radial-gradient(ellipse at center,var(--v55-bg) 0%,color-mix(in srgb,var(--v55-bg) 78%,transparent) 54%,transparent 82%)}
      .v69-team-card .v69-brand:before{background:radial-gradient(ellipse at center,var(--v69-bg) 0%,color-mix(in srgb,var(--v69-bg) 78%,transparent) 54%,transparent 82%)}
      #themedTeamBroadcast .bt-hero,#themedTeamBroadcast .bt-wordmark,#v55OfficeBroadcast .v55-office-hero,#v55OfficeBroadcast .v55-office-wordmark,.v69-team-card .v69-hero,.v69-team-card .v69-team-name,.v69-team-card .v69-ranked{position:relative;z-index:2!important}

      /* Use the TV width instead of the old fixed 1810/1870px ceilings. */
      #themedTeamBroadcast .bt-main{width:96.5vw!important;max-width:none!important}
      #v55OfficeBroadcast .v55-office-main{width:97vw!important;max-width:none!important}
      .v69-team-card .v69-main{width:98%!important;max-width:none!important}

      /* Give every enabled metric a real readable floor before sharing extra width. */
      #themedTeamBroadcast .bt-head,#themedTeamBroadcast .bt-row,#themedTeamBroadcast .bt-footer{
        grid-template-columns:clamp(48px,3.5vw,78px) minmax(220px,2.2fr) repeat(var(--bt-cols),minmax(86px,1fr))!important
      }
      #v55OfficeBroadcast .v55-office-head,#v55OfficeBroadcast .v55-office-row,#v55OfficeBroadcast .v55-office-footer{
        grid-template-columns:clamp(56px,3.8vw,105px) minmax(260px,2.25fr) clamp(70px,4.8vw,150px) repeat(var(--v55-office-cols),minmax(84px,1fr))!important
      }
      .v69-team-card .v69-head,.v69-team-card .v69-row,.v69-team-card .v69-footer{
        grid-template-columns:clamp(42px,3vw,68px) minmax(190px,2.1fr) repeat(var(--v69-cols),minmax(82px,1fr))!important
      }

      /* Text size follows actual bounded row height. */
      #themedTeamBroadcast .bt-name{font-size:var(--v72-team-name,16px)!important}
      #themedTeamBroadcast .champion .bt-name{font-size:calc(var(--v72-team-name,16px) * 1.08)!important}
      #themedTeamBroadcast .bt-rank{font-size:var(--v72-team-rank,24px)!important}
      #themedTeamBroadcast .bt-stat,#themedTeamBroadcast .bt-total-v{font-size:var(--v72-team-stat,12px)!important}
      #themedTeamBroadcast .bt-head{font-size:var(--v72-team-head,10px)!important}

      #v55OfficeBroadcast .v55-office-name,#v55OfficeBroadcast .champion .v55-office-name{font-size:var(--v72-office-name,15px)!important}
      #v55OfficeBroadcast .v55-office-rank{font-size:var(--v72-office-rank,22px)!important}
      #v55OfficeBroadcast .v55-office-stat,#v55OfficeBroadcast .v55-office-total-v{font-size:var(--v72-office-stat,11px)!important}
      #v55OfficeBroadcast .v55-office-head{font-size:var(--v72-office-head,9px)!important}

      .v69-team-card .v69-rep-name{font-size:var(--v72-comp-name,12px)!important}
      .v69-team-card .v69-rank{font-size:var(--v72-comp-rank,17px)!important}
      .v69-team-card .v69-stat,.v69-team-card .v69-total-v{font-size:var(--v72-comp-stat,10px)!important}
      .v69-team-card .v69-head{font-size:var(--v72-comp-head,9px)!important}

      /* Smaller cell padding gives the text the width instead of whitespace. */
      #themedTeamBroadcast .bt-rep{padding:1px 4px!important}
      #themedTeamBroadcast .bt-stat,#themedTeamBroadcast .bt-total{padding-left:1px!important;padding-right:1px!important}
      #themedTeamBroadcast .bt-head>div{padding-left:1px!important;padding-right:1px!important;line-height:1.05;white-space:normal}

      #v55OfficeBroadcast .v55-office-rep{padding:1px 4px!important}
      #v55OfficeBroadcast .v55-office-stat,#v55OfficeBroadcast .v55-office-total{padding-left:1px!important;padding-right:1px!important}
      #v55OfficeBroadcast .v55-office-head>div{padding-left:1px!important;padding-right:1px!important;line-height:1.05;white-space:normal}
      #v55OfficeBroadcast .v59-office-team-cell,#v55OfficeBroadcast .v58-office-team-cell{padding:0 1px!important}

      .v69-team-card .v69-rep{padding:1px 4px!important}
      .v69-team-card .v69-stat,.v69-team-card .v69-total{padding-left:1px!important;padding-right:1px!important}
      .v69-team-card .v69-head>div{padding-left:1px!important;padding-right:1px!important;line-height:1.05;white-space:normal}

      /* When moved inside the rows area, comparison totals finish the table
         immediately after the final rep rather than sitting at card bottom. */
      .v69-team-card .v69-rows>.v69-footer{
        width:100%!important;flex:0 0 auto!important;align-self:stretch!important;margin:2px 0 0!important
      }
    `;
    Display.placeStyle(260, style);
  }

  function applyPerTeam(root){
    const h=rowHeight(root,'.bt-row','.bt-row.champion');
    if(!h)return;
    setPx(root,'--v72-team-name',clamp(h*.36,14,28));
    setPx(root,'--v72-team-rank',clamp(h*.52,22,42));
    setPx(root,'--v72-team-stat',clamp(h*.245,11,19));
    setPx(root,'--v72-team-head',clamp(h*.20,9,15));
  }

  function applyOffice(root){
    const h=rowHeight(root,'.v55-office-row','.v55-office-row.champion');
    if(!h)return;
    setPx(root,'--v72-office-name',clamp(h*.36,14,28));
    setPx(root,'--v72-office-rank',clamp(h*.50,20,40));
    setPx(root,'--v72-office-stat',clamp(h*.24,10.5,19));
    setPx(root,'--v72-office-head',clamp(h*.20,9,15));
  }

  function applyComparison(card){
    const rows=card.querySelector('.v69-rows');
    const footer=card.querySelector('.v69-footer');
    if(rows&&footer&&footer.parentElement!==rows)rows.appendChild(footer);
    const h=rowHeight(card,'.v69-row','.v69-row.champion');
    if(!h)return;
    setPx(card,'--v72-comp-name',clamp(h*.36,12,23));
    setPx(card,'--v72-comp-rank',clamp(h*.48,16,34));
    setPx(card,'--v72-comp-stat',clamp(h*.24,10,16.5));
    setPx(card,'--v72-comp-head',clamp(h*.21,8.5,14));
  }

  function apply(){
    ensureStyles();
    const team=document.getElementById('themedTeamBroadcast');if(team)applyPerTeam(team);
    const office=document.getElementById('v55OfficeBroadcast');if(office)applyOffice(office);
    document.querySelectorAll('.v69-team-card').forEach(applyComparison);
  }
  function schedule(){
    if(scheduled)return;
    scheduled=true;
    requestAnimationFrame(()=>requestAnimationFrame(()=>{scheduled=false;apply();}));
  }

  Display.stage(260, function(data, next){const result=next(data);schedule();setTimeout(schedule,90);return result;});
  window.addEventListener('resize',schedule);
  const observer=new MutationObserver(mutations=>{
    for(const m of mutations){
      if([...m.addedNodes].some(n=>n.nodeType===1)){schedule();break;}
    }
  });
  if(document.body)observer.observe(document.body,{childList:true,subtree:true});
  ensureStyles();schedule();
})();


/* ------------------------------------------------------------------
   tracked-stat-indicator.js   (stage/style order 270)
   ------------------------------------------------------------------ */
/* v74 tracked-stat indicator.
   Presentation only. Single Team already marks the champion's active sort
   metric with a glowing underline; apply the same treatment to Whole Office,
   Team vs Team, and All Teams. */
(function(){
  const style=document.createElement("style");
  style.id="trackedStatIndicatorV74";
  style.textContent=`
    #v55OfficeBroadcast .v55-office-row.champion .v55-office-stat.primary,
    .v69-team-card .v69-row.champion .v69-stat.primary{
      position:relative!important;
    }

    #v55OfficeBroadcast .v55-office-row.champion .v55-office-stat.primary:after{
      content:"";
      position:absolute;
      left:16%;
      right:16%;
      bottom:18%;
      height:2px;
      background:linear-gradient(90deg,transparent,var(--v55-bright),transparent);
      box-shadow:0 0 8px color-mix(in srgb,var(--v55-bright) 85%,transparent);
      pointer-events:none;
    }

    .v69-team-card .v69-row.champion .v69-stat.primary:after{
      content:"";
      position:absolute;
      left:16%;
      right:16%;
      bottom:18%;
      height:2px;
      background:linear-gradient(90deg,transparent,var(--v69-bright),transparent);
      box-shadow:0 0 8px color-mix(in srgb,var(--v69-bright) 85%,transparent);
      pointer-events:none;
    }
  `;
  Display.placeStyle(270, style);
})();


/* ------------------------------------------------------------------
   number-scale.js   (stage/style order 280)
   ------------------------------------------------------------------ */
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
  const MIN=60,MAX=300;
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

  Display.stage(280, function(data, next){
    const result=next(data);
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
  });
})();
