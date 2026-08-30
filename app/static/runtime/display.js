/* Display runtime -- data to DOM.

   The screens themselves: the classic table, the single-team
   broadcast, the comparison cards and the whole-office board.

   Consolidated from the versioned patch stack. Each section below was its own
   file, wrapping the previous one by reassigning render(). They now register
   ordered stages instead, so this grouping is presentation only -- the
   execution order is the numbers, not the file boundaries. */


/* ------------------------------------------------------------------
   team-leads.js   (stage/style order 20)
   ------------------------------------------------------------------ */
/* v46 per-team display rule.
   Presentation only: the saved Team Builder leader is not part of the numbered
   competition. The existing backend still supplies/sorts/calculates everything.
   This layer only moves that already-rendered rep row to the bottom and marks it TL. */
(function(){
  if(typeof render!=="function") return;
  const norm=value=>String(value||"").trim().toLowerCase();

  function savedLeaderName(data){
    const leads=data?.team_summary?.leads;
    if(!Array.isArray(leads)||!leads.length) return "";
    return String(leads[0]?.lead_name||"").trim();
  }

  function applyTeamLeadPresentation(data){
    if(data?.mode!=="per_team") return;
    const leader=savedLeaderName(data);
    if(!leader) return;

    const table=document.querySelector("#scaleRoot table");
    const tbody=table?.querySelector("tbody");
    if(!tbody) return;

    const rows=[...tbody.querySelectorAll("tr:not(.total-row)")];
    const dataRows=Array.isArray(data.rows)?data.rows:[];
    rows.forEach((row,index)=>{
      row.dataset.repName=String(dataRows[index]?.rep_name||"");
      row.classList.remove("team-lead-row");
    });

    const leaderIndex=dataRows.findIndex(row=>norm(row?.rep_name)===norm(leader));
    if(leaderIndex<0||leaderIndex>=rows.length) return;

    const leadRow=rows[leaderIndex];
    const totalRow=tbody.querySelector("tr.total-row");
    leadRow.classList.add("team-lead-row");
    if(totalRow) tbody.insertBefore(leadRow,totalRow); else tbody.appendChild(leadRow);

    const rankIndex=(data.metrics||[]).indexOf("rank");
    if(rankIndex>=0){
      let rank=1;
      [...tbody.querySelectorAll("tr:not(.total-row)")].forEach(row=>{
        const cell=row.cells[rankIndex];
        if(!cell) return;
        if(row===leadRow){
          cell.textContent="TL";
          cell.classList.add("rank","team-lead-rank");
        }else{
          cell.textContent=String(rank++);
          cell.classList.remove("team-lead-rank");
        }
      });
    }
  }

  Display.stage(20, function(data, next){
    const result=next(data);
    applyTeamLeadPresentation(data);
    return result;
  });
})();


/* ------------------------------------------------------------------
   whole-office-cleanup.js   (stage/style order 80)
   ------------------------------------------------------------------ */
/* v50 Whole Office presentation cleanup.
   Data/ranking remain owned by the existing renderer. This layer only removes
   the redundant mode label and adds a small team identity asset beside Team. */
(function(){
  if(typeof render!=="function") return;
  const STYLE_ID="v50WholeOfficeIdentityStyles";

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      #scaleRoot td.v50-team-cell{padding-top:5px;padding-bottom:5px}
      #scaleRoot .v50-team-identity{display:inline-flex;align-items:center;gap:8px;min-width:0;vertical-align:middle}
      #scaleRoot .v50-team-logo{width:clamp(36px,3vw,56px);height:clamp(24px,2.4vw,42px);object-fit:contain;flex:0 0 auto}
      #scaleRoot .v50-team-name{white-space:nowrap}
    `;
    document.head.appendChild(style);
  }

  function teamTheme(data,name){
    return data?.theme_state?.by_name?.[String(name||"").trim().toLowerCase()]||null;
  }

  function decorateWholeOffice(data){
    if(data?.mode!=="whole_office") return;
    const mode=document.getElementById("modeLabel");
    if(mode) mode.textContent="";

    const metrics=Array.isArray(data.metrics)?data.metrics:[];
    const teamIndex=metrics.indexOf("team");
    if(teamIndex<0) return;

    const table=document.querySelector("#scaleRoot table");
    if(!table) return;
    ensureStyles();

    table.querySelectorAll("tbody tr:not(.total-row)").forEach(row=>{
      const cell=row.cells[teamIndex];
      if(!cell) return;
      const teamName=String(cell.textContent||"").trim();
      if(!teamName) return;
      const theme=teamTheme(data,teamName);
      const teamId=Number(theme?.team_id||0);
      const small=theme?.assets?.logo_small||null;
      const fallback=teamId?`/api/teams/${teamId}/logo?v=${Number(data.organization_version||0)}`:null;
      const src=small||fallback;
      if(!src) return;

      cell.classList.add("v50-team-cell");
      cell.textContent="";
      const wrap=document.createElement("span");
      wrap.className="v50-team-identity";
      const img=document.createElement("img");
      img.className="v50-team-logo";
      img.src=src;
      img.alt="";
      img.addEventListener("error",()=>img.remove(),{once:true});
      const label=document.createElement("span");
      label.className="v50-team-name";
      label.textContent=teamName;
      wrap.append(img,label);
      cell.appendChild(wrap);
    });
  }

  Display.stage(80, function(data, next){
    const result=next(data);
    decorateWholeOffice(data);
    return result;
  });
})();


/* ------------------------------------------------------------------
   comparison-team-cards.js   (stage/style order 90)
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   team-totals-footer.js   (stage/style order 100)
   ------------------------------------------------------------------ */
/* v54 presentation-only team totals placement.
   Keep the per-team totals strip attached to the rep table instead of letting
   the flexing broadcast shell push it to the bottom edge of the TV. */
(function(){
  if(typeof render!=="function") return;

  const STYLE_ID="teamTotalsTableFooterV54Styles";

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      #themedTeamBroadcast .bt-board > .bt-footer{
        width:100%!important;
        margin:clamp(4px,.65vh,9px) 0 0!important;
        flex:0 0 auto!important;
        align-self:stretch!important;
      }
    `;
    document.head.appendChild(style);
  }

  function attachTotalsToTable(){
    const root=document.getElementById("themedTeamBroadcast");
    if(!root) return;
    const board=root.querySelector(".bt-board");
    const footer=root.querySelector(":scope > .bt-footer");
    if(board&&footer) board.appendChild(footer);
  }

  Display.stage(100, function(data, next){
    const result=next(data);
    if(data?.mode==="per_team"){
      ensureStyles();
      attachTotalsToTable();
    }
    return result;
  });
})();


/* ------------------------------------------------------------------
   broadcast-views.js   (stage/style order 110)
   ------------------------------------------------------------------ */
/* v55 broadcast presentation upgrade.
   PRESENTATION ONLY: existing app renderers remain authoritative for filtering,
   sorting, selected metrics, values, totals, assignments and calculations.
   This final layer re-composes those values for Whole Office, Team vs Team and
   All Teams using the owning team themes. */
(function(){
  if(typeof render!=="function") return;

  const OFFICE_ROOT="v55OfficeBroadcast";
  const STYLE_ID="v55BroadcastViewsStyles";
  const TEXT_METRICS=new Set(["rank","rep_name","team","home_branch","title","hire_date"]);
  const comparisonModes=new Set();
  const norm=v=>String(v||"").trim().toLowerCase();
  const assigned=row=>Number(row?.assigned_team_id||0)>0;

  function node(tag,className,text){
    const el=document.createElement(tag);
    if(className) el.className=className;
    if(text!==undefined&&text!==null) el.textContent=String(text);
    return el;
  }

  function numericMetric(data,key){
    const type=data?.metric_types?.[key];
    return type==="number"||type==="currency"||type==="percent";
  }

  function numericMetrics(data){
    return (Array.isArray(data.metrics)?data.metrics:[])
      .filter(key=>!TEXT_METRICS.has(key)&&numericMetric(data,key));
  }

  function formatValue(data,key,value){
    if(typeof fmt==="function") return fmt(value,data?.metric_types?.[key],data?.currency_symbol);
    return String(value??"");
  }

  function themeFor(data,teamName,teamId){
    const state=data?.theme_state||{};
    if(teamId!==undefined&&teamId!==null&&state.teams?.[String(teamId)]){
      return state.teams[String(teamId)];
    }
    return state.by_name?.[norm(teamName)]||null;
  }

  function sourceRow(data,repName,teamName){
    return (data?.rows||[]).find(row=>{
      if(repName&&norm(row?.rep_name)!==norm(repName)) return false;
      if(teamName&&norm(row?.team)!==norm(teamName)) return false;
      return !!(repName||teamName);
    })||null;
  }

  function mainLogo(data,teamName,teamId,summary){
    if(summary?.logo_url) return summary.logo_url;
    const id=Number(teamId||0);
    if(!id) return null;
    return `/api/teams/${id}/logo?v=${Number(data?.organization_version||0)}`;
  }

  function smallLogo(data,teamName,teamId){
    const theme=themeFor(data,teamName,teamId);
    if(theme?.assets?.logo_small) return theme.assets.logo_small;
    return mainLogo(data,teamName,teamId,null);
  }

  function currentClassicDisplay(data){
    const table=document.querySelector("#scaleRoot table");
    if(!table) return null;
    const metrics=Array.isArray(data.metrics)?data.metrics.slice():[];
    const bodyRows=[...table.querySelectorAll("tbody tr:not(.total-row)")];
    const totalRow=table.querySelector("tbody tr.total-row");
    const readCells=tr=>{
      const out={};
      if(!tr) return out;
      [...tr.cells].forEach((cell,index)=>{
        const key=metrics[index];
        if(key) out[key]=String(cell.textContent||"").trim();
      });
      return out;
    };
    return {
      metrics,
      rows:bodyRows.map(tr=>readCells(tr)),
      total:readCells(totalRow)
    };
  }

  function winningTeam(data,display){
    const first=display?.rows?.[0];
    if(!first) return null;
    const repName=String(first.rep_name||"").trim();
    let teamName=String(first.team||"").trim();
    const source=sourceRow(data,repName,teamName);
    if(!teamName&&source) teamName=String(source.team||"").trim();
    if(!teamName) return null;
    return {
      teamName,
      teamId:source?.assigned_team_id||source?.team_id||null,
      repName,
      source
    };
  }

  function clearLegacyOfficeDecor(){
    document.querySelectorAll(".theme-frame,.theme-corner,.theme-hero,.theme-office-logo,.theme-medallion,.theme-total-mark").forEach(el=>el.remove());
    document.body.classList.remove("team-theme-full");
    document.body.style.removeProperty("background-image");
  }

  function clearV55(){
    document.getElementById(OFFICE_ROOT)?.remove();
    document.body.classList.remove("v55-office-active","v55-comparison-active");
  }

  function setThemeVars(target,colors,prefix){
    const map={
      primary:"primary",primary_bright:"bright",primary_dark:"dark",
      secondary:"secondary",background:"bg",panel:"panel",text:"text",
      muted:"muted",champion_text:"champ"
    };
    Object.entries(map).forEach(([key,name])=>{
      if(colors?.[key]) target.style.setProperty(`${prefix}${name}`,colors[key]);
    });
  }

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      body.v55-office-active{padding:0!important;overflow:hidden!important;background:#070706!important}
      body.v55-office-active>header,body.v55-office-active>#content,body.v55-office-active>#status{visibility:hidden!important}
      #${OFFICE_ROOT}{
        --v55-primary:#c58a2a;--v55-bright:#e1ad48;--v55-dark:#6f4612;
        --v55-secondary:#8b130c;--v55-bg:#070706;--v55-panel:#11100d;
        --v55-text:#e8d6ad;--v55-muted:#a3946f;--v55-champ:#f7e7ae;
        position:fixed;inset:0;z-index:160;overflow:hidden;display:flex;flex-direction:column;
        color:var(--v55-text);background:var(--v55-bg);
        font-family:"Arial Narrow","Roboto Condensed",Impact,Arial,sans-serif;
      }
      #${OFFICE_ROOT} *{box-sizing:border-box}
      #${OFFICE_ROOT} .v55-office-bg{position:absolute;inset:0;z-index:0;background-position:center;background-size:cover;background-repeat:no-repeat}
      #${OFFICE_ROOT} .v55-office-atmosphere{position:absolute;inset:0;z-index:1;pointer-events:none;background:radial-gradient(60% 46% at 50% 5%,color-mix(in srgb,var(--v55-bright) 8%,transparent),transparent 62%),radial-gradient(60% 50% at 100% 100%,color-mix(in srgb,var(--v55-secondary) 22%,transparent),transparent 62%),radial-gradient(60% 50% at 0% 100%,color-mix(in srgb,var(--v55-secondary) 18%,transparent),transparent 62%),linear-gradient(rgba(7,7,6,.82),rgba(7,7,6,.90))}
      #${OFFICE_ROOT} .v55-office-frame{position:absolute;inset:10px;z-index:30;pointer-events:none;border:2px solid var(--v55-primary);box-shadow:inset 0 0 0 1px #000,inset 0 0 0 5px color-mix(in srgb,var(--v55-primary) 35%,transparent),inset 0 0 70px rgba(0,0,0,.75)}
      #${OFFICE_ROOT} .v55-office-corner{position:absolute;z-index:31;width:clamp(60px,7vw,120px);height:auto;object-fit:contain;pointer-events:none;filter:drop-shadow(0 2px 5px #000)}
      #${OFFICE_ROOT} .v55-office-corner.tl{top:6px;left:6px}#${OFFICE_ROOT} .v55-office-corner.tr{top:6px;right:6px}#${OFFICE_ROOT} .v55-office-corner.bl{bottom:6px;left:6px}#${OFFICE_ROOT} .v55-office-corner.br{bottom:6px;right:6px}
      #${OFFICE_ROOT} .v55-office-brand{position:relative;z-index:4;flex:0 0 auto;height:var(--v55-office-brand-h,150px);display:flex;align-items:center;justify-content:center;padding:8px 40px 2px}
      #${OFFICE_ROOT} .v55-office-hero{display:block;width:min(78vw,1680px);height:100%;object-fit:contain;filter:drop-shadow(0 5px 14px rgba(0,0,0,.9))}
      #${OFFICE_ROOT} .v55-office-wordmark{font-family:Impact,"Arial Narrow",sans-serif;font-size:clamp(54px,8vw,138px);letter-spacing:.035em;text-transform:uppercase;color:var(--v55-bright);text-shadow:0 3px 0 #000,0 0 16px color-mix(in srgb,var(--v55-bright) 30%,transparent)}
      #${OFFICE_ROOT} .v55-office-main{position:relative;z-index:4;width:min(96%,1870px);margin:0 auto;flex:0 0 auto;min-height:0}
      #${OFFICE_ROOT} .v55-office-head,#${OFFICE_ROOT} .v55-office-row,#${OFFICE_ROOT} .v55-office-footer{display:grid;grid-template-columns:clamp(52px,3.8vw,76px) minmax(260px,2.7fr) repeat(var(--v55-office-cols),minmax(0,1fr));align-items:center}
      #${OFFICE_ROOT} .v55-office-head{height:30px;color:var(--v55-bright);text-transform:uppercase;letter-spacing:.10em;text-align:center;font-size:clamp(7px,.58vw,10px);font-weight:800;border-top:1px solid color-mix(in srgb,var(--v55-primary) 48%,transparent);border-bottom:1px solid color-mix(in srgb,var(--v55-primary) 48%,transparent);background:rgba(6,6,5,.92);text-shadow:0 1px 3px #000}
      #${OFFICE_ROOT} .v55-office-head .rep{text-align:left;padding-left:10px;color:var(--v55-muted)}
      #${OFFICE_ROOT} .v55-office-board{display:flex;flex-direction:column;gap:1px;overflow:hidden}
      #${OFFICE_ROOT} .v55-office-row{position:relative;height:var(--v55-office-row-h,42px);min-height:25px;overflow:hidden;border-bottom:1px solid color-mix(in srgb,var(--v55-primary) 14%,transparent)}
      #${OFFICE_ROOT} .v55-office-row-art{position:absolute;inset:0;width:100%;height:100%;z-index:0;object-fit:fill;opacity:.78}
      #${OFFICE_ROOT} .v55-office-row-shade{position:absolute;inset:0;z-index:1;background:rgba(4,4,3,.50);pointer-events:none}
      #${OFFICE_ROOT} .v55-office-row>*:not(.v55-office-row-art):not(.v55-office-row-shade){position:relative;z-index:2}
      #${OFFICE_ROOT} .v55-office-row.champion{height:calc(var(--v55-office-row-h,42px) * 1.18);border:2px solid var(--v55-bright);border-radius:5px;box-shadow:0 0 24px color-mix(in srgb,var(--v55-bright) 28%,transparent),0 3px 18px rgba(0,0,0,.72)}
      #${OFFICE_ROOT} .v55-office-row.champion .v55-office-row-shade{background:rgba(20,3,3,.16)}
      #${OFFICE_ROOT} .v55-office-rank{font-family:Impact,"Arial Narrow",sans-serif;text-align:center;color:var(--v55-bright);font-size:clamp(15px,1.65vw,30px);font-weight:900;text-shadow:0 2px 4px #000;min-width:0}
      #${OFFICE_ROOT} .v55-office-medal{display:block;width:min(72%,52px);height:min(82%,52px);object-fit:contain;margin:auto;filter:drop-shadow(0 3px 8px #000)}
      #${OFFICE_ROOT} .v55-office-rep{min-width:0;padding:2px 10px;overflow:hidden}
      #${OFFICE_ROOT} .v55-office-name{font-family:Impact,"Arial Narrow",sans-serif;color:var(--v55-bright);font-size:clamp(10px,.92vw,17px);letter-spacing:.02em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 2px 3px #000}
      #${OFFICE_ROOT} .champion .v55-office-name{color:var(--v55-champ);font-size:clamp(11px,1vw,19px)}
      #${OFFICE_ROOT} .v55-office-team{display:flex;align-items:center;gap:5px;color:var(--v55-muted);font-size:clamp(6px,.48vw,9px);letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
      #${OFFICE_ROOT} .v55-office-team-logo{width:clamp(14px,1.25vw,23px);height:clamp(12px,1.1vw,20px);object-fit:contain;flex:0 0 auto}
      #${OFFICE_ROOT} .v55-office-stat{align-self:stretch;display:flex;align-items:center;justify-content:center;text-align:center;border-left:1px solid color-mix(in srgb,var(--v55-primary) 24%,transparent);font-variant-numeric:tabular-nums;font-weight:800;font-size:clamp(7px,.60vw,11px);text-shadow:0 2px 3px #000;white-space:nowrap;overflow:hidden;padding:0 2px}
      #${OFFICE_ROOT} .v55-office-stat.money{color:var(--v55-bright)}#${OFFICE_ROOT} .v55-office-stat.primary{color:var(--v55-champ);font-weight:900}
      #${OFFICE_ROOT} .v55-office-footer{height:48px;margin-top:3px;border-top:2px solid var(--v55-primary);background:rgba(0,0,0,.62)}
      #${OFFICE_ROOT} .v55-office-footer-spacer{grid-column:span 2}
      #${OFFICE_ROOT} .v55-office-total{text-align:center;border-left:1px solid color-mix(in srgb,var(--v55-primary) 28%,transparent);padding:0 3px;min-width:0}
      #${OFFICE_ROOT} .v55-office-total-v{color:var(--v55-bright);font-size:clamp(7px,.60vw,11px);font-weight:900;white-space:nowrap;overflow:hidden;font-variant-numeric:tabular-nums;text-shadow:0 2px 3px #000}
      #${OFFICE_ROOT} .v55-office-total-l{color:var(--v55-muted);font-size:clamp(5px,.38vw,7px);letter-spacing:.08em;text-transform:uppercase;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

      body.v55-comparison-active{padding:8px!important;background:#050505!important;overflow:hidden!important}
      body.v55-comparison-active header{display:none!important}
      body.v55-comparison-active #content{height:calc(100vh - 16px)!important;overflow:hidden!important}
      body.v55-comparison-active #scaleRoot{width:100%!important;height:100%!important;transform:none!important}
      .v55-comparison-board{width:100%;height:100%;display:grid;grid-template-columns:repeat(var(--v55-cols),minmax(0,1fr));grid-template-rows:repeat(var(--v55-rows),minmax(0,1fr));gap:8px;min-width:0;min-height:0}
      .v55-team-card{--c-primary:#d8b34a;--c-bright:#e6c760;--c-dark:#705b20;--c-secondary:#303030;--c-bg:#080808;--c-panel:#111;--c-text:#f5f5f5;--c-muted:#9c9c9c;--c-champ:#fff;position:relative;min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;color:var(--c-text);background:var(--c-bg);border:2px solid var(--c-primary);box-shadow:inset 0 0 0 1px #000,inset 0 0 0 4px color-mix(in srgb,var(--c-primary) 26%,transparent),inset 0 0 40px rgba(0,0,0,.72)}
      .v55-team-card-bg{position:absolute;inset:0;z-index:0;width:100%;height:100%;object-fit:cover;opacity:.66}
      .v55-team-card-shade{position:absolute;inset:0;z-index:1;background:linear-gradient(rgba(5,5,5,.40),rgba(5,5,5,.61));pointer-events:none}
      .v55-card-corner{position:absolute;z-index:20;width:min(14%,70px);height:auto;object-fit:contain;pointer-events:none}
      .v55-card-corner.tl{top:0;left:0}.v55-card-corner.tr{top:0;right:0}.v55-card-corner.bl{bottom:0;left:0}.v55-card-corner.br{bottom:0;right:0}
      .v55-card-brand{position:relative;z-index:3;flex:0 0 var(--v55-brand-share,23%);min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:8px 14px 4px;text-align:center}
      .v55-card-logo{display:block;width:min(84%,420px);height:min(84%,210px);object-fit:contain;filter:drop-shadow(0 5px 12px rgba(0,0,0,.82))}
      .v55-card-fallback-name{font-family:Impact,"Arial Narrow",sans-serif;font-size:clamp(23px,2.1vw,44px);text-transform:uppercase;color:var(--c-bright);letter-spacing:.045em;text-shadow:0 3px 7px #000}
      .v55-card-ranked{margin-top:2px;color:var(--c-muted);font-size:clamp(6px,.48vw,10px);font-weight:800;letter-spacing:.14em;text-transform:uppercase;text-shadow:0 2px 3px #000}
      .v55-card-reps{position:relative;z-index:3;flex:1 1 auto;min-height:0;padding:0 9px;display:grid;grid-template-rows:repeat(var(--v55-card-reps),minmax(0,1fr));gap:1px}
      .v55-card-rep{position:relative;min-width:0;min-height:0;overflow:hidden;display:grid;grid-template-columns:clamp(25px,2vw,40px) minmax(105px,1.2fr) minmax(0,1.8fr);align-items:center;gap:6px;border-bottom:1px solid color-mix(in srgb,var(--c-primary) 18%,transparent)}
      .v55-card-rep.champion{border:2px solid var(--c-bright);border-radius:4px;box-shadow:0 0 18px color-mix(in srgb,var(--c-bright) 27%,transparent)}
      .v55-card-row-art{position:absolute;inset:0;z-index:0;width:100%;height:100%;object-fit:fill;opacity:.82}
      .v55-card-row-shade{position:absolute;inset:0;z-index:1;background:rgba(4,4,3,.51);pointer-events:none}.v55-card-rep.champion .v55-card-row-shade{background:rgba(18,3,3,.17)}
      .v55-card-rep>*:not(.v55-card-row-art):not(.v55-card-row-shade){position:relative;z-index:2}
      .v55-card-rank{font-family:Impact,"Arial Narrow",sans-serif;text-align:center;color:var(--c-bright);font-size:clamp(12px,1vw,21px);font-weight:900;text-shadow:0 2px 3px #000}
      .v55-card-medal{display:block;width:clamp(24px,2.4vw,46px);height:clamp(24px,2.4vw,46px);object-fit:contain;margin:auto;filter:drop-shadow(0 2px 6px #000)}
      .v55-card-rep-name{min-width:0;padding:0 3px;font-family:Impact,"Arial Narrow",sans-serif;font-size:clamp(10px,.88vw,18px);font-weight:900;letter-spacing:.02em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 2px 3px #000}
      .v55-card-rep.champion .v55-card-rep-name{color:var(--c-champ)}
      .v55-card-kpis{min-width:0;height:100%;display:grid;grid-template-columns:repeat(var(--v55-card-kpi-count),minmax(0,1fr));align-items:stretch}
      .v55-card-kpi{min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;border-left:1px solid color-mix(in srgb,var(--c-primary) 22%,transparent);padding:1px 3px;text-align:center}
      .v55-card-kpi-v{color:var(--c-bright);font-size:clamp(8px,.68vw,14px);font-weight:900;white-space:nowrap;overflow:hidden;max-width:100%;font-variant-numeric:tabular-nums;text-shadow:0 2px 3px #000}
      .v55-card-kpi-l{color:var(--c-muted);font-size:clamp(5px,.34vw,7px);letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;margin-top:1px}
      .v55-card-footer{position:relative;z-index:3;flex:0 0 auto;display:grid;grid-template-columns:repeat(var(--v55-card-total-count),minmax(0,1fr));margin:6px 9px 8px;border-top:2px solid var(--c-primary);padding-top:5px;min-height:42px}
      .v55-card-total{min-width:0;text-align:center;border-right:1px solid color-mix(in srgb,var(--c-primary) 24%,transparent);padding:0 4px}.v55-card-total:last-child{border-right:0}
      .v55-card-total-v{color:var(--c-bright);font-size:clamp(8px,.70vw,15px);font-weight:900;white-space:nowrap;overflow:hidden;font-variant-numeric:tabular-nums;text-shadow:0 2px 3px #000}
      .v55-card-total-l{color:var(--c-muted);font-size:clamp(5px,.35vw,7px);letter-spacing:.07em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}

      .v55-comparison-board.cols-2{--v55-brand-share:25%}.v55-comparison-board.cols-2 .v55-card-logo{width:min(88%,470px);height:min(88%,235px)}
      .v55-comparison-board.cols-3{--v55-brand-share:24%}.v55-comparison-board.cols-3 .v55-card-logo{width:min(88%,350px);height:min(86%,205px)}
      .v55-comparison-board.rows-2{--v55-brand-share:27%}.v55-comparison-board.rows-2 .v55-card-logo{width:min(82%,280px);height:min(83%,125px)}
      .v55-comparison-board.cols-4 .v55-card-rep{grid-template-columns:24px minmax(85px,1fr) minmax(0,1.5fr);gap:4px}.v55-comparison-board.cols-4 .v55-card-rep-name{font-size:clamp(8px,.60vw,12px)}
      .v55-comparison-board.rows-3{--v55-brand-share:25%}.v55-comparison-board.rows-3 .v55-card-logo{height:min(80%,92px)}
      @media(max-width:1150px){.v55-comparison-board{gap:6px}.v55-card-reps{padding-left:6px;padding-right:6px}.v55-card-footer{margin-left:6px;margin-right:6px}.v55-card-rep{gap:4px}}
    `;
    document.head.appendChild(style);
  }

  function cornerImages(container,assets,className){
    [["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]].forEach(([key,pos])=>{
      if(!assets?.[key]) return;
      const img=node("img",`${className} ${pos}`);
      img.src=assets[key];img.alt="";
      container.appendChild(img);
    });
  }

  function officeRow(data,theme,displayRow,index,stats){
    const assets=theme?.assets||{};
    const champion=index===0;
    const row=node("div",`v55-office-row${champion?" champion":""}`);
    const artSrc=champion?(assets.champion||assets.row):assets.row;
    if(artSrc){
      const art=node("img","v55-office-row-art");art.src=artSrc;art.alt="";row.appendChild(art);
    }
    row.appendChild(node("div","v55-office-row-shade"));

    const rank=node("div","v55-office-rank");
    if(champion&&assets.medallion){
      const medal=node("img","v55-office-medal");medal.src=assets.medallion;medal.alt="1";rank.appendChild(medal);
    }else{
      rank.textContent=displayRow.rank||String(index+1);
    }
    row.appendChild(rank);

    const rep=node("div","v55-office-rep");
    rep.appendChild(node("div","v55-office-name",displayRow.rep_name||""));
    const src=sourceRow(data,displayRow.rep_name,displayRow.team);
    const teamName=displayRow.team||src?.team||"";
    if(teamName){
      const teamLine=node("div","v55-office-team");
      const logoSrc=smallLogo(data,teamName,src?.assigned_team_id||src?.team_id||null);
      if(logoSrc){
        const img=node("img","v55-office-team-logo");img.src=logoSrc;img.alt="";
        img.addEventListener("error",()=>img.remove(),{once:true});
        teamLine.appendChild(img);
      }
      teamLine.appendChild(node("span","",teamName));
      rep.appendChild(teamLine);
    }
    row.appendChild(rep);

    stats.forEach(key=>{
      const cell=node("div",`v55-office-stat${data.metric_types?.[key]==="currency"?" money":""}${key===data.sort_metric?" primary":""}`,displayRow[key]||"");
      row.appendChild(cell);
    });
    return row;
  }

  function renderWholeOffice(data){
    if(data?.mode!=="whole_office") return false;
    const display=currentClassicDisplay(data);
    const winner=winningTeam(data,display);
    if(!display||!winner) return false;
    const rawTheme=themeFor(data,winner.teamName,winner.teamId);
    const theme=rawTheme?.enabled&&rawTheme?.colors?rawTheme:null;
    if(!theme) return false;

    ensureStyles();
    clearLegacyOfficeDecor();
    document.getElementById(OFFICE_ROOT)?.remove();

    const assets=theme.assets||{};
    const colors=theme.colors||{};
    const stats=display.metrics.filter(key=>!TEXT_METRICS.has(key)&&numericMetric(data,key));
    if(!stats.length) return false;

    const root=node("section","");root.id=OFFICE_ROOT;
    setThemeVars(root,colors,"--v55-");
    root.style.setProperty("--v55-office-cols",String(stats.length));

    const rowCount=Math.max(display.rows.length,1);
    const heroScale=Math.max(.5,Math.min(2,Number(theme.hero_scale||100)/100));
    // v67 Whole Office used a 19vh hero at this TV size. Keep that 100%
    // baseline, then let the theme multiplier own artwork size while rows take
    // every remaining pixel.
    const baseBrandHeight=Math.max(190,Math.min(420,window.innerHeight*.19));
    const brandHeight=baseBrandHeight*heroScale;
    const available=Math.max(120,window.innerHeight-brandHeight-30-48-20);
    const rowHeight=Math.max(12,available/(rowCount+(rowCount?0.18:0)));
    root.style.setProperty("--v55-office-brand-h",`${brandHeight.toFixed(2)}px`);
    root.style.setProperty("--v55-office-row-h",`${rowHeight.toFixed(2)}px`);

    const bg=node("div","v55-office-bg");
    bg.style.backgroundColor=colors.background||"#070706";
    if(assets.background) bg.style.backgroundImage=`url("${assets.background}")`;
    root.appendChild(bg);
    root.appendChild(node("div","v55-office-atmosphere"));
    root.appendChild(node("div","v55-office-frame"));
    cornerImages(root,assets,"v55-office-corner");

    const brand=node("div","v55-office-brand");
    const heroSrc=assets.hero||mainLogo(data,winner.teamName,winner.teamId,null);
    if(heroSrc){
      const hero=node("img","v55-office-hero");hero.src=heroSrc;hero.alt=winner.teamName;
      hero.addEventListener("error",()=>{hero.remove();brand.appendChild(node("div","v55-office-wordmark",winner.teamName));},{once:true});
      brand.appendChild(hero);
    }else brand.appendChild(node("div","v55-office-wordmark",winner.teamName));
    root.appendChild(brand);

    const main=node("main","v55-office-main");
    const head=node("div","v55-office-head");
    head.appendChild(node("div","",""));
    head.appendChild(node("div","rep","Sales Rep / Team"));
    stats.forEach(key=>head.appendChild(node("div","",data.metric_labels?.[key]||key)));
    main.appendChild(head);

    const board=node("div","v55-office-board");
    display.rows.forEach((row,index)=>board.appendChild(officeRow(data,theme,row,index,stats)));
    main.appendChild(board);

    if(Object.keys(display.total||{}).length){
      const footer=node("div","v55-office-footer");
      footer.appendChild(node("div","v55-office-footer-spacer"));
      stats.forEach(key=>{
        const item=node("div","v55-office-total");
        item.appendChild(node("div","v55-office-total-v",display.total[key]||""));
        item.appendChild(node("div","v55-office-total-l",data.metric_labels?.[key]||key));
        footer.appendChild(item);
      });
      main.appendChild(footer);
    }

    root.appendChild(main);
    document.body.classList.add("v55-office-active");
    document.body.appendChild(root);
    return true;
  }

  function layoutFor(count){
    if(count<=1) return {cols:1,rows:1};
    if(count===2) return {cols:2,rows:1};
    if(count===3) return {cols:3,rows:1};
    if(count===4) return {cols:2,rows:2};
    if(count<=6) return {cols:3,rows:2};
    if(count<=8) return {cols:4,rows:2};
    if(count<=9) return {cols:3,rows:3};
    if(count<=12) return {cols:4,rows:3};
    const cols=Math.max(4,Math.ceil(Math.sqrt(count*16/9)));
    return {cols,rows:Math.ceil(count/cols)};
  }

  function orderedTeams(data){
    const source=(Array.isArray(data?.teams)?data.teams:[]).filter(team=>(team.members||[]).some(assigned));
    const byName=new Map(source.map(team=>[norm(team?.summary?.team),team]));
    const rendered=[...document.querySelectorAll(".v53-card")].map(card=>String(card.dataset.team||"").trim()).filter(Boolean);
    if(!rendered.length) return source;
    const out=[];const used=new Set();
    rendered.forEach(name=>{
      const team=byName.get(norm(name));
      if(team&&!used.has(team)){out.push(team);used.add(team);}
    });
    source.forEach(team=>{if(!used.has(team)) out.push(team);});
    return out;
  }

  function selectedCardKeys(data,count){
    const all=numericMetrics(data);
    const primary=data.sort_metric;
    const ordered=[];
    if(primary&&all.includes(primary)) ordered.push(primary);
    all.forEach(key=>{if(!ordered.includes(key)) ordered.push(key);});
    const rowLimit=count<=2?4:count===3?3:2;
    const totalLimit=count<=2?6:count===3?5:4;
    return {row:ordered.slice(0,rowLimit),total:ordered.slice(0,totalLimit)};
  }

  function buildTeamCard(team,data,keys){
    const summary=team.summary||{};
    const members=(team.members||[]).filter(assigned);
    const rawTheme=themeFor(data,summary.team,summary.team_id);
    const theme=rawTheme?.enabled&&rawTheme?.colors?rawTheme:null;
    const colors=theme?.colors||{};
    const assets=theme?.assets||{};

    const card=node("section","v55-team-card");
    card.dataset.team=String(summary.team||"");
    setThemeVars(card,colors,"--c-");

    if(assets.background){
      const bg=node("img","v55-team-card-bg");bg.src=assets.background;bg.alt="";card.appendChild(bg);
    }
    card.appendChild(node("div","v55-team-card-shade"));
    cornerImages(card,assets,"v55-card-corner");

    const brand=node("div","v55-card-brand");
    const logoSrc=mainLogo(data,summary.team,summary.team_id,summary);
    if(logoSrc){
      const logo=node("img","v55-card-logo");logo.src=logoSrc;logo.alt=`${summary.team||"Team"} logo`;
      logo.addEventListener("error",()=>{logo.remove();brand.insertBefore(node("div","v55-card-fallback-name",summary.team||"Team"),brand.firstChild);},{once:true});
      brand.appendChild(logo);
    }else brand.appendChild(node("div","v55-card-fallback-name",summary.team||"Team"));
    brand.appendChild(node("div","v55-card-ranked",`Ranked by ${data.metric_labels?.[data.sort_metric]||data.sort_metric||"score"}`));
    card.appendChild(brand);

    const reps=node("div","v55-card-reps");
    reps.style.setProperty("--v55-card-reps",String(Math.max(members.length,1)));
    reps.style.setProperty("--v55-card-kpi-count",String(Math.max(keys.row.length,1)));
    if(members.length){
      members.forEach((rep,index)=>{
        const row=node("div",`v55-card-rep${index===0?" champion":""}`);
        const artSrc=index===0?(assets.champion||assets.row):assets.row;
        if(artSrc){
          const art=node("img","v55-card-row-art");art.src=artSrc;art.alt="";row.appendChild(art);
        }
        row.appendChild(node("div","v55-card-row-shade"));

        const rank=node("div","v55-card-rank");
        if(index===0&&assets.medallion){
          const medal=node("img","v55-card-medal");medal.src=assets.medallion;medal.alt="1";rank.appendChild(medal);
        }else rank.textContent=String(index+1);
        row.appendChild(rank);
        row.appendChild(node("div","v55-card-rep-name",rep.rep_name||""));

        const kpis=node("div","v55-card-kpis");
        keys.row.forEach(key=>{
          const item=node("div","v55-card-kpi");
          item.appendChild(node("div","v55-card-kpi-v",formatValue(data,key,rep?.[key])));
          item.appendChild(node("div","v55-card-kpi-l",data.metric_labels?.[key]||key));
          kpis.appendChild(item);
        });
        row.appendChild(kpis);
        reps.appendChild(row);
      });
    }else reps.appendChild(node("div","v55-card-rep","No assigned reps"));
    card.appendChild(reps);

    const footer=node("div","v55-card-footer");
    footer.style.setProperty("--v55-card-total-count",String(Math.max(keys.total.length,1)));
    keys.total.forEach(key=>{
      const item=node("div","v55-card-total");
      item.appendChild(node("div","v55-card-total-v",formatValue(data,key,summary?.[key])));
      item.appendChild(node("div","v55-card-total-l",data.metric_labels?.[key]||key));
      footer.appendChild(item);
    });
    card.appendChild(footer);
    return card;
  }

  function renderComparison(data){
    if(!comparisonModes.has(data?.mode)) return false;
    ensureStyles();
    const teams=orderedTeams(data);
    if(!teams.length) return false;

    const layout=layoutFor(teams.length);
    const keys=selectedCardKeys(data,teams.length);
    const board=node("div",`v55-comparison-board cols-${layout.cols} rows-${layout.rows}`);
    board.style.setProperty("--v55-cols",String(layout.cols));
    board.style.setProperty("--v55-rows",String(layout.rows));
    teams.forEach(team=>board.appendChild(buildTeamCard(team,data,keys)));

    const scaleRoot=document.getElementById("scaleRoot");
    if(!scaleRoot) return false;
    scaleRoot.innerHTML="";
    scaleRoot.appendChild(board);
    document.body.classList.add("v55-comparison-active");
    if(typeof fitLeaderboard==="function") setTimeout(fitLeaderboard,0);
    return true;
  }

  Display.stage(110, function(data, next){
    const result=next(data);
    clearV55();

    if(data?.mode==="whole_office"){
      renderWholeOffice(data);
      return result;
    }
    if(comparisonModes.has(data?.mode)){
      renderComparison(data);
      return result;
    }
    return result;
  });
})();


/* ------------------------------------------------------------------
   whole-office-team-column.js   (stage/style order 130)
   ------------------------------------------------------------------ */
/* v59 Whole Office team-column runtime hotfix.
   PRESENTATION ONLY. Keeps the v58 Sales Rep / Team split, but makes the DOM
   patch idempotent and only reacts to newly rendered leaderboard structures.
   This prevents the observer from reacting to its own mutations. */
(function(){
  const ROOT_ID="v55OfficeBroadcast";
  const STYLE_ID="v59WholeOfficeTeamColumn";
  let scheduled=false;

  function directChildWithClass(parent,className){
    if(!parent) return null;
    for(const child of parent.children){
      if(child.classList && child.classList.contains(className)) return child;
    }
    return null;
  }

  function directTeamCell(row){
    return directChildWithClass(row,"v59-office-team-cell") ||
           directChildWithClass(row,"v58-office-team-cell");
  }

  function ensureStyle(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      #${ROOT_ID} .v55-office-head,
      #${ROOT_ID} .v55-office-row,
      #${ROOT_ID} .v55-office-footer{
        grid-template-columns:
          clamp(64px,4.2vw,165px)
          minmax(300px,2.45fr)
          clamp(80px,5.2vw,190px)
          repeat(var(--v55-office-cols),minmax(0,1fr))!important;
      }

      #${ROOT_ID} .v55-office-head .rep{
        text-align:left!important;
        padding-left:10px!important;
      }
      #${ROOT_ID} .v59-team-head,
      #${ROOT_ID} .v58-team-head{
        text-align:center!important;
        color:var(--v55-muted)!important;
      }

      #${ROOT_ID} .v55-office-rep{
        display:block!important;
        min-width:0!important;
        padding:2px clamp(8px,.55vw,22px)!important;
      }
      #${ROOT_ID} .v55-office-name,
      #${ROOT_ID} .champion .v55-office-name{
        display:block!important;
        max-width:100%!important;
        width:100%!important;
        white-space:nowrap!important;
        overflow:hidden!important;
        text-overflow:ellipsis!important;
      }

      #${ROOT_ID} .v59-office-team-cell,
      #${ROOT_ID} .v58-office-team-cell{
        align-self:stretch!important;
        min-width:0!important;
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;
        overflow:hidden!important;
        border-left:1px solid rgba(255,255,255,.08)!important;
        border-right:1px solid rgba(255,255,255,.08)!important;
        padding:1px 4px!important;
      }
      #${ROOT_ID} .v59-office-team-cell .v55-office-team-logo,
      #${ROOT_ID} .v58-office-team-cell .v55-office-team-logo{
        display:block!important;
        flex:0 0 auto!important;
        width:clamp(38px,2.35vw,92px)!important;
        height:clamp(38px,2.35vw,92px)!important;
        max-width:95%!important;
        max-height:95%!important;
        object-fit:contain!important;
        margin:0!important;
        filter:drop-shadow(0 2px 5px rgba(0,0,0,.85))!important;
      }

      #${ROOT_ID} .v55-office-footer-spacer{
        grid-column:span 3!important;
      }
    `;
    Display.placeStyle(130, style);
  }

  function patch(root){
    if(!root) return;
    ensureStyle();

    const head=root.querySelector(".v55-office-head");
    if(head){
      const repHead=head.children[1];
      if(repHead){
        if(repHead.textContent.trim()!=="Sales Rep") repHead.textContent="Sales Rep";
        if(!repHead.classList.contains("rep")) repHead.classList.add("rep");

        let teamHead=head.querySelector(".v59-team-head, .v58-team-head");
        if(!teamHead){
          teamHead=document.createElement("div");
          teamHead.className="v59-team-head";
          teamHead.textContent="Team";
          repHead.insertAdjacentElement("afterend",teamHead);
        }else{
          if(!teamHead.classList.contains("v59-team-head")) teamHead.classList.add("v59-team-head");
          if(teamHead.textContent.trim()!=="Team") teamHead.textContent="Team";
        }
      }
    }

    root.querySelectorAll(".v55-office-row").forEach(row=>{
      const rep=directChildWithClass(row,"v55-office-rep");
      if(!rep) return;

      let cell=directTeamCell(row);
      if(!cell){
        cell=document.createElement("div");
        cell.className="v59-office-team-cell";
        rep.insertAdjacentElement("afterend",cell);
      }else if(!cell.classList.contains("v59-office-team-cell")){
        cell.classList.add("v59-office-team-cell");
      }

      const oldTeam=rep.querySelector(".v55-office-team");
      if(!oldTeam) return;

      const logo=oldTeam.querySelector(".v55-office-team-logo");
      if(logo){
        const src=String(logo.getAttribute("src")||"");
        // Whole Office Team column intentionally accepts Logo Small only.
        if(src && !src.includes("/api/teams/")){
          if(cell.firstElementChild!==logo || cell.children.length!==1){
            cell.replaceChildren(logo);
          }else{
            cell.appendChild(logo);
          }
        }else if(cell.childNodes.length){
          cell.replaceChildren();
        }
      }else if(cell.childNodes.length){
        cell.replaceChildren();
      }
      oldTeam.remove();
    });
  }

  function apply(){
    patch(document.getElementById(ROOT_ID));
  }

  function scheduleApply(){
    if(scheduled) return;
    scheduled=true;
    requestAnimationFrame(()=>{
      scheduled=false;
      apply();
    });
  }

  ensureStyle();
  apply();

  const observer=new MutationObserver(mutations=>{
    let relevant=false;
    outer:
    for(const mutation of mutations){
      for(const node of mutation.addedNodes){
        if(node.nodeType!==1) continue;
        const el=node;
        if(el.id===ROOT_ID ||
           (el.classList && (el.classList.contains("v55-office-head") || el.classList.contains("v55-office-row"))) ||
           (el.querySelector && el.querySelector(`#${ROOT_ID}, .v55-office-head, .v55-office-row`))){
          relevant=true;
          break outer;
        }
      }
    }
    if(relevant) scheduleApply();
  });

  if(document.body) observer.observe(document.body,{childList:true,subtree:true});
})();
