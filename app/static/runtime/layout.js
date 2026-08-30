/* Layout runtime -- how much room things get.

   Row height bounds, whole-office compaction, the hero/table
   trade-off, and reporting the TV's real viewport back to the Pi.

   Consolidated from the versioned patch stack. Each section below was its own
   file, wrapping the previous one by reassigning render(). They now register
   ordered stages instead, so this grouping is presentation only -- the
   execution order is the numbers, not the file boundaries. */


/* ------------------------------------------------------------------
   whole-office-inline-team.js   (stage/style order 120)
   ------------------------------------------------------------------ */
/* v57 Whole Office identity compaction.
   PRESENTATION ONLY. Keep rep and team on one horizontal line to save row height
   while balancing their visual weight for TV readability. */
(function(){
  const style=document.createElement("style");
  style.id="v57WholeOfficeInlineTeam";
  style.textContent=`
    #v55OfficeBroadcast .v55-office-rep{
      display:flex!important;
      align-items:center!important;
      gap:clamp(10px,.65vw,26px)!important;
      min-width:0!important;
      padding:2px clamp(8px,.55vw,22px)!important;
    }
    #v55OfficeBroadcast .v55-office-name{
      flex:0 1 auto!important;
      max-width:62%!important;
      min-width:0!important;
      font-size:clamp(14px,.72vw,29px)!important;
      line-height:1!important;
      white-space:nowrap!important;
      overflow:hidden!important;
      text-overflow:ellipsis!important;
    }
    #v55OfficeBroadcast .champion .v55-office-name{
      font-size:clamp(15px,.78vw,31px)!important;
    }
    #v55OfficeBroadcast .v55-office-team{
      flex:1 1 auto!important;
      min-width:0!important;
      margin-top:0!important;
      gap:clamp(6px,.34vw,14px)!important;
      font-size:clamp(11px,.55vw,22px)!important;
      line-height:1!important;
      letter-spacing:.035em!important;
    }
    #v55OfficeBroadcast .v55-office-team span{
      min-width:0!important;
      overflow:hidden!important;
      text-overflow:ellipsis!important;
      white-space:nowrap!important;
    }
    #v55OfficeBroadcast .v55-office-team-logo{
      width:clamp(25px,1.15vw,46px)!important;
      height:clamp(22px,1.02vw,41px)!important;
      flex:0 0 auto!important;
    }
  `;
  Display.placeStyle(120, style);
})();


/* ------------------------------------------------------------------
   tv-preview.js   (stage/style order 220)
   ------------------------------------------------------------------ */
/* v63 display-side preview mode + TV geometry reporting.

   Two jobs, both read-only as far as the TV is concerned:

   1. Normally (no ?preview), report this browser's viewport to the Pi. The
      kiosk runs fullscreen on the TV, so its viewport IS the usable TV shape,
      overscan included — a better answer than any mode table, and it lets the
      settings page frame its preview at the real aspect ratio.

   2. With ?preview=team-<id>, render THAT team's board instead of whatever the
      TV is set to, so the settings page can embed this page in an iframe. It
      writes nothing and never touches the saved display mode. */
(function(){
  const params=new URLSearchParams(location.search);
  const preview=String(params.get("preview")||"").trim();
  const match=/^team-(\d+)$/.exec(preview);

  if(!match){
    // --- normal kiosk: report the real TV viewport -------------------------
    let last="";
    let timer=null;
    const report=()=>{
      const w=Math.round(window.innerWidth);
      const h=Math.round(window.innerHeight);
      const key=`${w}x${h}`;
      if(!w||!h||key===last)return;
      last=key;
      fetch("/api/tv/geometry",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({w,h}),keepalive:true
      }).catch(()=>{});
    };
    const debounced=()=>{clearTimeout(timer);timer=setTimeout(report,600);};
    if(document.readyState==="loading")
      document.addEventListener("DOMContentLoaded",report,{once:true});
    else report();
    window.addEventListener("resize",debounced);
    return;
  }

  // --- preview mode --------------------------------------------------------
  const teamId=Number(match[1]);
  let teamName="";

  /* /api/leaderboard already accepts ?mode=per_team::<name>. Point this tab's
     fetches at the requested team; every other request is left alone. */
  const nativeFetch=window.fetch.bind(window);
  window.fetch=function(input,init){
    try{
      const url=typeof input==="string"?input:input?.url||"";
      if(url.startsWith("/api/leaderboard")&&!url.includes("mode=")&&teamName){
        const join=url.includes("?")?"&":"?";
        const next=`${url}${join}mode=${encodeURIComponent(`per_team::${teamName}`)}`;
        return nativeFetch(typeof input==="string"?next:new Request(next,input),init);
      }
    }catch(e){}
    return nativeFetch(input,init);
  };

  /* The board reloads itself when the app restarts or the TV is refreshed.
     Inside the studio's iframe that would navigate the preview away, so in
     preview mode those reloads are disabled. */
  const stopReload=()=>{
    try{
      const replace=location.replace.bind(location);
      location.replace=url=>{
        const target=String(url||"");
        // The two self-reloads the board performs: app restart and TV refresh.
        if(target.includes("/?restart=")||target.includes("/?refresh="))return;
        replace(url);
      };
    }catch(e){/* some browsers refuse to patch location; harmless here */}
    window.addEventListener("beforeunload",e=>{e.stopImmediatePropagation();},true);
  };

  async function start(){
    stopReload();
    try{
      const r=await nativeFetch("/api/config",{cache:"no-store"});
      const d=await r.json();
      const team=(d.team_definitions||[]).find(t=>Number(t.team_id)===teamId);
      teamName=String(team?.name||"").trim();
    }catch(e){}
    document.documentElement.dataset.preview="1";
    if(typeof window.load==="function")window.load();
  }

  if(document.readyState==="loading")
    document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();
})();


/* ------------------------------------------------------------------
   row-height-bounds.js   (stage/style order 240)
   ------------------------------------------------------------------ */
/* v71 bounded adaptive row heights.
   Presentation only. Renderers may still choose an adaptive row size, but the
   TV clamps that size to proven readable ranges instead of stretching rows to
   consume every available pixel or shrinking them into unreadable slivers. */
(function(){
  const style=document.createElement("style");
  style.id="rowHeightBoundsV71";
  style.textContent=`
    /* Individual team: restore the pre-v69 readable bounds. */
    #themedTeamBroadcast .bt-board{
      justify-content:flex-start!important;
    }
    #themedTeamBroadcast .bt-row{
      min-height:44px!important;
      max-height:82px!important;
    }
    #themedTeamBroadcast .bt-row.champion{
      min-height:58px!important;
      max-height:100px!important;
    }
    #themedTeamBroadcast .bt-row.team-lead{
      min-height:44px!important;
      max-height:82px!important;
    }

    /* Whole Office: keep the v69 computed height, but only inside the old
       high-resolution working range. Extra room stays below the table. */
    #v55OfficeBroadcast .v55-office-row{
      height:clamp(38px,var(--v55-office-row-h,42px),82px)!important;
      min-height:38px!important;
      max-height:82px!important;
    }
    #v55OfficeBroadcast .v55-office-row.champion{
      height:clamp(48px,calc(var(--v55-office-row-h,42px) * 1.18),98px)!important;
      min-height:48px!important;
      max-height:98px!important;
    }

    /* Stacked comparison boards need the denser pre-v69 safe range because
       more than one full-width team can share the same 1080p screen. */
    .v69-team-card .v69-rows{
      justify-content:flex-start!important;
    }
    .v69-team-card .v69-row{
      min-height:31px!important;
      max-height:67px!important;
    }
    .v69-team-card .v69-row.champion{
      min-height:38px!important;
      max-height:78px!important;
    }
  `;
  Display.placeStyle(240, style);
})();


/* ------------------------------------------------------------------
   whole-office-table-priority.js   (stage/style order 250)
   ------------------------------------------------------------------ */
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
