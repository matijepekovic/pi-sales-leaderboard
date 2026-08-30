/* v48 presentation-only champion artwork fix.
   The selected Champion Row asset is rendered as a real full-width image layer
   inside the themed champion row instead of relying on CSS background stacking. */
(function(){
  if(typeof render!=="function") return;

  function teamTheme(data){
    const summary=data?.team_summary||{};
    const state=data?.theme_state||{};
    if(summary.team_id!=null && state.teams?.[String(summary.team_id)]){
      return state.teams[String(summary.team_id)];
    }
    const key=String(summary.team||data?.selected_team||"").trim().toLowerCase();
    return state.by_name?.[key]||null;
  }

  function ensureStyle(){
    if(document.getElementById("v48ChampionAssetStyle")) return;
    const style=document.createElement("style");
    style.id="v48ChampionAssetStyle";
    style.textContent=`
      #themedTeamBroadcast .champion{isolation:isolate;background-image:none!important;}
      #themedTeamBroadcast .champion .bt-champion-art{
        position:absolute!important;
        inset:0!important;
        width:100%!important;
        height:100%!important;
        object-fit:fill!important;
        display:block!important;
        z-index:0!important;
        pointer-events:none!important;
      }
      #themedTeamBroadcast .champion::before{z-index:1!important;}
      #themedTeamBroadcast .champion>.bt-rank,
      #themedTeamBroadcast .champion>.bt-rep,
      #themedTeamBroadcast .champion>.bt-stat{z-index:2!important;}
      #themedTeamBroadcast .champion::after{z-index:3!important;}
    `;
    document.head.appendChild(style);
  }

  function applyChampionAsset(data){
    if(data?.mode!=="per_team") return;
    const row=document.querySelector("#themedTeamBroadcast .bt-row.champion");
    if(!row) return;
    const asset=teamTheme(data)?.assets?.champion;
    if(!asset) return;

    ensureStyle();
    let img=row.querySelector(":scope > .bt-champion-art");
    if(!img){
      img=document.createElement("img");
      img.className="bt-champion-art";
      img.alt="";
      row.insertBefore(img,row.firstChild);
    }
    if(img.getAttribute("src")!==asset) img.setAttribute("src",asset);
    row.style.backgroundImage="none";
  }

  Display.stage(70, function(data, next){
    const result=next(data);
    applyChampionAsset(data);
    return result;
  });
})();
