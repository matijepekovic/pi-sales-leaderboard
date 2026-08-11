/* v55 broadcast presentation upgrade.
   PRESENTATION ONLY: existing app renderers remain authoritative for filtering,
   sorting, selected metrics, values, totals, assignments and calculations.
   This final layer re-composes those values for Whole Office, Team vs Team and
   All Teams using the owning team themes. */
(function(){
  if(typeof render!=="function") return;

  const previousRender=render;
  const OFFICE_ROOT="v55OfficeBroadcast";
  const STYLE_ID="v55BroadcastViewsStyles";
  const TEXT_METRICS=new Set(["rank","rep_name","team","home_branch","title","hire_date"]);
  const comparisonModes=new Set(["team_vs_team","all_teams"]);
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
      #${OFFICE_ROOT} .v55-office-hero{display:block;width:min(70vw,1080px);height:100%;object-fit:contain;filter:drop-shadow(0 5px 14px rgba(0,0,0,.9))}
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
    const brandHeight=rowCount>=14?112:rowCount>=10?132:rowCount>=7?160:220;
    const available=Math.max(300,window.innerHeight-brandHeight-30-48-34);
    const rowHeight=Math.max(25,Math.min(68,Math.floor(available/(rowCount+(rowCount?0.18:0)))));
    root.style.setProperty("--v55-office-brand-h",`${brandHeight}px`);
    root.style.setProperty("--v55-office-row-h",`${rowHeight}px`);

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

  render=function(data){
    const result=previousRender(data);
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
  };
})();
