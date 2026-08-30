/* v60 corner adjustment runtime.
   Applies Theme Studio size/crop settings after the existing render stack so
   the same corner configuration works in Team, Whole Office, Team vs Team and
   All Teams without changing data/layout logic. */
(function(){
  if(typeof render!=="function")return;
  const CORNERS={
    corner_tl:{pos:"tl",sx:-1,sy:-1,origin:"left top"},
    corner_tr:{pos:"tr",sx:1,sy:-1,origin:"right top"},
    corner_bl:{pos:"bl",sx:-1,sy:1,origin:"left bottom"},
    corner_br:{pos:"br",sx:1,sy:1,origin:"right bottom"}
  };
  const norm=v=>String(v||"").trim().toLowerCase();

  function themeFor(data,teamName,teamId){
    const state=data?.theme_state||{};
    if(teamId!==undefined&&teamId!==null&&state.teams?.[String(teamId)])return state.teams[String(teamId)];
    return teamName&&state.by_name?.[norm(teamName)]||null;
  }

  function cfg(theme,key){
    const raw=theme?.corner_settings?.[key]||{};
    const n=(v,d)=>{v=Number(v);return Number.isFinite(v)?v:d;};
    return {size:n(raw.size,100),crop_x:n(raw.crop_x,0),crop_y:n(raw.crop_y,0)};
  }

  function applyOne(img,key,theme){
    const info=CORNERS[key];if(!img||!info)return;
    const c=cfg(theme,key);
    img.style.transformOrigin=info.origin;
    img.style.transform=`translate(${info.sx*c.crop_x}%,${info.sy*c.crop_y}%) scale(${c.size/100})`;
    img.style.willChange="transform";
  }

  function applySet(container,selectorPrefix,theme){
    if(!container||!theme)return;
    Object.entries(CORNERS).forEach(([key,info])=>{
      container.querySelectorAll(`${selectorPrefix}.${info.pos}`).forEach(img=>applyOne(img,key,theme));
    });
  }

  function wholeOfficeTheme(data){
    const root=document.getElementById("v55OfficeBroadcast");if(!root)return null;
    const repName=String(root.querySelector(".v55-office-row .v55-office-name")?.textContent||"").trim();
    const source=(data?.rows||[]).find(r=>repName&&norm(r?.rep_name)===norm(repName))||null;
    return source?themeFor(data,source.team,source.assigned_team_id||source.team_id):null;
  }

  function apply(data){
    if(!data)return;
    if(data.mode==="per_team"){
      const s=data.team_summary||{};
      const theme=themeFor(data,s.team,s.team_id);
      // themed-team-layout.js removes .theme-corner and draws .bt-corner in
      // its place, so matching only the old class silently adjusted nothing.
      applySet(document,".theme-corner",theme);
      applySet(document,".bt-corner",theme);
      return;
    }
    if(data.mode==="whole_office"){
      applySet(document.getElementById("v55OfficeBroadcast"),".v55-office-corner",wholeOfficeTheme(data));
      return;
    }
    if(data.mode==="team_vs_team"||data.mode==="all_teams"){
      document.querySelectorAll(".v69-team-card").forEach(card=>{
        const name=String(card.dataset.team||"").trim();
        const teamId=Number(card.dataset.teamId||0)||null;
        applySet(card,".v69-corner",themeFor(data,name,teamId));
      });
    }
  }

  Display.stage(140, function(data, next){
    const result=next(data);
    apply(data);
    requestAnimationFrame(()=>apply(data));
    setTimeout(()=>apply(data),80);
    return result;
  });
})();
