/* v69 comparison presentation.
   Team vs Team and All Teams now use the same information model as individual
   team view: every enabled metric, one column per metric, themed rows and a
   totals footer. Teams stack vertically at full width, winner first.

   PRESENTATION ONLY. Existing server payloads remain authoritative for
   assignments, member ordering, values, calculations and selected metrics. */
(function(){
  if(typeof render!=="function") return;

  const STYLE_ID="comparisonTeamCardsV69Styles";
  const ROOT_CLASS="v69-comparison-board";
  const comparisonModes=new Set(["team_vs_team","all_teams"]);
  const TEXT_METRICS=new Set(["rank","rep_name","team","home_branch","title","hire_date"]);
  const assigned=row=>Number(row?.assigned_team_id||0)>0;
  const norm=value=>String(value||"").trim().toLowerCase();

  function node(tag,className,text){
    const el=document.createElement(tag);
    if(className)el.className=className;
    if(text!==undefined&&text!==null)el.textContent=String(text);
    return el;
  }

  function clamp(value,min,max){
    value=Number(value);
    return Number.isFinite(value)?Math.min(max,Math.max(min,value)):min;
  }

  function metricKeys(data){
    return (Array.isArray(data?.metrics)?data.metrics:[]).filter(key=>!TEXT_METRICS.has(key));
  }

  function formatValue(data,key,value){
    if(typeof fmt==="function")return fmt(value,data?.metric_types?.[key],data?.currency_symbol);
    return String(value??"");
  }

  function themeFor(data,summary){
    const state=data?.theme_state||{};
    const teamId=summary?.team_id;
    if(teamId!==undefined&&teamId!==null&&state.teams?.[String(teamId)])return state.teams[String(teamId)];
    return state.by_name?.[norm(summary?.team)]||null;
  }

  function setThemeVars(card,colors={}){
    const map={
      primary:"--v69-primary",primary_bright:"--v69-bright",primary_dark:"--v69-dark",
      secondary:"--v69-secondary",background:"--v69-bg",panel:"--v69-panel",
      text:"--v69-text",muted:"--v69-muted",champion_text:"--v69-champ"
    };
    Object.entries(map).forEach(([key,name])=>{if(colors[key])card.style.setProperty(name,colors[key]);});
  }

  function ensureStyles(){
    if(document.getElementById(STYLE_ID))return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      #title,#subtitle{display:none!important}
      body.v69-comparison-active{padding:8px!important;background:#050505!important;overflow:hidden!important}
      body.v69-comparison-active header{display:none!important}
      body.v69-comparison-active #content{height:calc(100vh - 16px)!important;overflow:hidden!important}
      body.v69-comparison-active #scaleRoot{width:100%!important;height:100%!important;transform:none!important;transform-origin:top left!important}

      .${ROOT_CLASS}{width:100%;height:100%;min-width:0;min-height:0;display:flex;flex-direction:column;gap:8px;overflow:hidden}
      .v69-team-card{
        --v69-primary:#d8b34a;--v69-bright:#e6c760;--v69-dark:#705b20;--v69-secondary:#303030;
        --v69-bg:#080808;--v69-panel:#111;--v69-text:#f5f5f5;--v69-muted:#9c9c9c;--v69-champ:#fff;
        position:relative;flex:1 1 0;min-height:0;width:100%;overflow:hidden;display:flex;flex-direction:column;
        color:var(--v69-text);background:var(--v69-bg);border:2px solid var(--v69-primary);
        box-shadow:inset 0 0 0 1px #000,inset 0 0 0 4px color-mix(in srgb,var(--v69-primary) 26%,transparent),inset 0 0 40px rgba(0,0,0,.72);
        font-family:"Arial Narrow","Roboto Condensed",Impact,Arial,sans-serif;
      }
      .v69-team-card *{box-sizing:border-box}
      .v69-card-bg{position:absolute;inset:0;z-index:0;width:100%;height:100%;object-fit:cover;opacity:.68}
      .v69-card-atmosphere{position:absolute;inset:0;z-index:1;pointer-events:none;background:linear-gradient(rgba(5,5,5,.40),rgba(5,5,5,.66))}
      .v69-card-frame{position:absolute;inset:5px;z-index:18;pointer-events:none;border:1px solid color-mix(in srgb,var(--v69-primary) 70%,transparent)}
      .v69-corner{position:absolute;z-index:20;width:clamp(60px,7vw,120px);height:auto;object-fit:contain;pointer-events:none;filter:drop-shadow(0 2px 5px #000)}
      .v69-corner.tl{top:0;left:0}.v69-corner.tr{top:0;right:0}.v69-corner.bl{bottom:0;left:0}.v69-corner.br{bottom:0;right:0}

      .v69-brand{position:relative;z-index:3;flex:0 0 var(--v69-brand-h,92px);min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4px 34px 2px;text-align:center;overflow:hidden}
      .v69-hero{display:block;width:min(72vw,1160px);height:calc(100% - 14px);max-width:92%;object-fit:contain;filter:drop-shadow(0 4px 10px rgba(0,0,0,.86))}
      .v69-team-name{font-family:Impact,"Arial Narrow",sans-serif;color:var(--v69-bright);font-size:clamp(20px,2.1vw,42px);letter-spacing:.045em;text-transform:uppercase;text-shadow:0 3px 7px #000;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:90%}
      .v69-ranked{flex:0 0 auto;color:var(--v69-muted);font-size:clamp(6px,.46vw,10px);font-weight:800;letter-spacing:.14em;text-transform:uppercase;text-shadow:0 2px 3px #000;white-space:nowrap}

      .v69-main{position:relative;z-index:3;flex:1 1 auto;min-height:0;width:min(96%,1870px);margin:0 auto;display:flex;flex-direction:column}
      .v69-head,.v69-row,.v69-footer{display:grid;grid-template-columns:clamp(50px,3.6vw,72px) minmax(210px,2.45fr) repeat(var(--v69-cols),minmax(0,1fr));align-items:center}
      .v69-head{flex:0 0 auto;min-height:24px;color:var(--v69-bright);text-transform:uppercase;letter-spacing:.09em;text-align:center;font-size:clamp(6px,.48vw,10px);font-weight:800;border-top:1px solid color-mix(in srgb,var(--v69-primary) 48%,transparent);border-bottom:1px solid color-mix(in srgb,var(--v69-primary) 48%,transparent);background:rgba(6,6,5,.91);text-shadow:0 1px 3px #000}
      .v69-head .rep{text-align:left;padding-left:9px;color:var(--v69-muted)}
      .v69-rows{flex:1 1 auto;min-height:0;overflow:hidden;display:flex;flex-direction:column;gap:1px}
      .v69-row{position:relative;flex:1 1 0;min-height:0;max-height:none;overflow:hidden;border-bottom:1px solid color-mix(in srgb,var(--v69-primary) 14%,transparent);background-position:center;background-size:100% 100%;background-repeat:no-repeat}
      .v69-row:before{content:"";position:absolute;inset:0;z-index:0;background:rgba(4,4,3,.54);pointer-events:none}.v69-row>*{position:relative;z-index:1}
      .v69-row.champion{flex:1.15 1 0;border:2px solid var(--v69-bright);border-radius:4px;box-shadow:0 0 20px color-mix(in srgb,var(--v69-bright) 26%,transparent)}
      .v69-row.champion:before{background:rgba(22,3,3,.18)}
      .v69-rank{font-family:Impact,"Arial Narrow",sans-serif;text-align:center;color:var(--v69-bright);font-size:var(--v69-rank-font,20px);font-weight:900;text-shadow:0 2px 3px #000;min-width:0}
      .v69-medal{display:block;width:min(70%,54px);height:min(88%,54px);object-fit:contain;margin:auto;filter:drop-shadow(0 2px 6px #000)}
      .v69-rep{min-width:0;padding:1px 9px;overflow:hidden}
      .v69-rep-name{font-family:Impact,"Arial Narrow",sans-serif;color:var(--v69-bright);font-size:var(--v69-name-font,15px);font-weight:900;letter-spacing:.02em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 2px 3px #000}
      .v69-row.champion .v69-rep-name{color:var(--v69-champ)}
      .v69-stat{align-self:stretch;display:flex;align-items:center;justify-content:center;text-align:center;border-left:1px solid color-mix(in srgb,var(--v69-primary) 24%,transparent);font-variant-numeric:tabular-nums;font-weight:800;font-size:var(--v69-stat-font,11px);text-shadow:0 2px 3px #000;white-space:nowrap;overflow:hidden;padding:0 2px}
      .v69-stat.money{color:var(--v69-bright)}.v69-stat.primary{color:var(--v69-champ);font-weight:900}
      .v69-empty{flex:1 1 auto;display:grid;place-items:center;color:var(--v69-muted);font-size:12px}

      .v69-footer{position:relative;z-index:3;flex:0 0 auto;min-height:38px;border-top:2px solid var(--v69-primary);background:rgba(0,0,0,.62);padding:3px 0;margin-top:2px}
      .v69-footer-spacer{grid-column:span 2;align-self:stretch}
      .v69-total{min-width:0;text-align:center;border-left:1px solid color-mix(in srgb,var(--v69-primary) 28%,transparent);padding:0 3px}
      .v69-total-v{color:var(--v69-bright);font-size:var(--v69-total-font,11px);font-weight:900;white-space:nowrap;overflow:hidden;font-variant-numeric:tabular-nums;text-shadow:0 2px 3px #000}
      .v69-total-l{color:var(--v69-muted);font-size:clamp(5px,.38vw,7px);letter-spacing:.07em;text-transform:uppercase;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      @media(max-width:1150px){.${ROOT_CLASS}{gap:6px}.v69-main{width:97%}.v69-head,.v69-row,.v69-footer{grid-template-columns:40px minmax(145px,2.1fr) repeat(var(--v69-cols),minmax(0,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function cleanup(){
    document.body.classList.remove("v69-comparison-active","v53-comparison-mode");
    document.querySelector(`.${ROOT_CLASS}`)?.remove();
  }

  function visibleTeams(data){
    return (Array.isArray(data?.teams)?data.teams:[]).filter(team=>(team?.members||[]).some(assigned));
  }

  function rankedTeams(data){
    const key=data?.sort_metric;
    return visibleTeams(data).map((team,index)=>({team,index})).sort((a,b)=>{
      const av=Number(a.team?.summary?.[key]??0),bv=Number(b.team?.summary?.[key]??0);
      const an=Number.isFinite(av)?av:0,bn=Number.isFinite(bv)?bv:0;
      if(bn!==an)return bn-an;
      return a.index-b.index;
    }).map(item=>item.team);
  }

  function addCorners(card,assets){
    [["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]].forEach(([key,pos])=>{
      if(!assets?.[key])return;
      const img=node("img",`v69-corner ${pos}`);img.src=assets[key];img.alt="";card.appendChild(img);
    });
  }

  function mainLogo(data,summary){
    if(summary?.logo_url)return summary.logo_url;
    const id=Number(summary?.team_id||0);
    return id?`/api/teams/${id}/logo?v=${Number(data?.organization_version||0)}`:null;
  }

  function heroFor(data,summary,theme){
    const assets=theme?.assets||{};
    return assets.hero||mainLogo(data,summary)||null;
  }

  function buildCard(team,data,metrics){
    const summary=team?.summary||{};
    const theme=themeFor(data,summary)||{};
    const colors=theme.colors||{};
    const assets=theme.assets||{};
    const members=(Array.isArray(team?.members)?team.members:[]).filter(assigned);
    const card=node("section","v69-team-card");
    card.dataset.team=String(summary.team||"");
    card.dataset.teamId=String(summary.team_id??"");
    setThemeVars(card,colors);
    card.style.setProperty("--v69-cols",String(Math.max(metrics.length,1)));

    const heroScale=clamp(theme.hero_scale??100,50,200)/100;
    const baseBrand=Math.max(62,Math.min(112,window.innerHeight*.085));
    card.style.setProperty("--v69-brand-h",`${Math.round(baseBrand*heroScale)}px`);
    const count=Math.max(members.length,1);
    card.style.setProperty("--v69-name-font",`${count>=11?9:count>=8?11:count>=5?13:15}px`);
    card.style.setProperty("--v69-rank-font",`${count>=11?12:count>=8?15:count>=5?18:21}px`);
    card.style.setProperty("--v69-stat-font",`${count>=11?8:count>=8?9:count>=5?10:11}px`);
    card.style.setProperty("--v69-total-font",`${metrics.length>=10?8:metrics.length>=7?9:11}px`);

    if(assets.background){const bg=node("img","v69-card-bg");bg.src=assets.background;bg.alt="";card.appendChild(bg);}
    card.appendChild(node("div","v69-card-atmosphere"));
    card.appendChild(node("div","v69-card-frame"));
    addCorners(card,assets);

    const brand=node("div","v69-brand");
    const heroSrc=heroFor(data,summary,theme);
    if(heroSrc){
      const hero=node("img","v69-hero");hero.src=heroSrc;hero.alt=String(summary.team||"Team");
      hero.addEventListener("error",()=>{hero.remove();brand.insertBefore(node("div","v69-team-name",summary.team||"Team"),brand.firstChild);},{once:true});
      brand.appendChild(hero);
    }else brand.appendChild(node("div","v69-team-name",summary.team||"Team"));
    brand.appendChild(node("div","v69-ranked",`Ranked by ${data?.metric_labels?.[data?.sort_metric]||data?.sort_metric||"score"}`));
    card.appendChild(brand);

    const main=node("main","v69-main");
    const head=node("div","v69-head");
    head.appendChild(node("div","",""));head.appendChild(node("div","rep","Rep"));
    metrics.forEach(key=>head.appendChild(node("div","",data?.metric_labels?.[key]||key)));
    main.appendChild(head);

    if(members.length){
      const rows=node("div","v69-rows");
      members.forEach((rep,index)=>{
        const champion=index===0;
        const row=node("div",`v69-row${champion?" champion":""}`);
        const art=champion?(assets.champion||assets.row):assets.row;
        if(art)row.style.backgroundImage=`url("${String(art).replace(/["\\\n\r]/g,"")}")`;
        const rank=node("div","v69-rank");
        if(champion&&assets.medallion){const medal=node("img","v69-medal");medal.src=assets.medallion;medal.alt="1";rank.appendChild(medal);}else rank.textContent=String(index+1);
        row.appendChild(rank);
        const repBox=node("div","v69-rep");repBox.appendChild(node("div","v69-rep-name",rep?.rep_name||""));row.appendChild(repBox);
        metrics.forEach(key=>row.appendChild(node("div",`v69-stat${data?.metric_types?.[key]==="currency"?" money":""}${key===data?.sort_metric?" primary":""}`,formatValue(data,key,rep?.[key]))));
        rows.appendChild(row);
      });
      main.appendChild(rows);
    }else main.appendChild(node("div","v69-empty","No assigned reps"));

    const footer=node("footer","v69-footer");
    footer.appendChild(node("div","v69-footer-spacer"));
    metrics.forEach(key=>{
      const item=node("div","v69-total");
      item.appendChild(node("div","v69-total-v",formatValue(data,key,summary?.[key])));
      item.appendChild(node("div","v69-total-l",data?.metric_labels?.[key]||key));
      footer.appendChild(item);
    });
    main.appendChild(footer);
    card.appendChild(main);
    return card;
  }

  function renderComparison(data){
    ensureStyles();
    const teams=rankedTeams(data),metrics=metricKeys(data);
    if(!teams.length)return false;
    const scaleRoot=document.getElementById("scaleRoot");if(!scaleRoot)return false;
    const board=node("div",ROOT_CLASS);
    teams.forEach(team=>board.appendChild(buildCard(team,data,metrics)));
    scaleRoot.innerHTML="";scaleRoot.appendChild(board);
    document.body.classList.add("v69-comparison-active");
    if(typeof fitLeaderboard==="function")setTimeout(fitLeaderboard,0);
    return true;
  }

  Display.stage(90, function(data, next){
    const result=next(data);
    cleanup();
    if(comparisonModes.has(data?.mode))renderComparison(data);
    return result;
  });
})();
