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
