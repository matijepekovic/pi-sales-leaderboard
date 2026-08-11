/* v53 comparison presentation.
   Team vs Team and All Teams are rendered as self-contained team design cards.
   Existing data/filtering/sorting remains authoritative; this layer only
   re-composes the already-selected teams into a TV-friendly card grid. */
(function(){
  if(typeof render!=="function") return;

  const previousRender=render;
  const STYLE_ID="comparisonTeamCardsV53Styles";
  const comparisonModes=new Set(["team_vs_team","all_teams"]);
  const assigned=row=>Number(row?.assigned_team_id||0)>0;
  const norm=value=>String(value||"").trim().toLowerCase();

  function node(tag,className,text){
    const el=document.createElement(tag);
    if(className) el.className=className;
    if(text!==undefined&&text!==null) el.textContent=String(text);
    return el;
  }

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      /* The shared TV title/subtitle are redundant now that the views carry
         their own team identity. Keep the header itself available to modes
         that inject artwork/logo into it. */
      #title,#subtitle{display:none!important}

      body.v53-comparison-mode{padding:10px!important;background-color:#050505!important}
      body.v53-comparison-mode header{display:none!important}
      body.v53-comparison-mode #content{height:calc(100vh - 20px)!important;overflow:hidden!important}
      body.v53-comparison-mode #scaleRoot{width:100%;height:100%;transform-origin:top left}

      .v53-board{
        width:100%;height:100%;min-width:0;min-height:0;
        display:grid;
        grid-template-columns:repeat(var(--v53-cols),minmax(0,1fr));
        grid-template-rows:repeat(var(--v53-rows),minmax(0,1fr));
        gap:10px;
      }
      .v53-card{
        --v53-primary:#d8b34a;--v53-bright:#e6c760;--v53-panel:#0b0b0b;
        --v53-text:#f5f5f5;--v53-muted:#9c9c9c;--v53-champion:#fff;
        min-width:0;min-height:0;width:100%;height:100%;overflow:hidden;
        position:relative;display:flex;flex-direction:column;
        color:var(--v53-text);background-color:var(--v53-panel);
        background-position:center;background-size:cover;background-repeat:no-repeat;
        border:2px solid var(--v53-primary);
        box-shadow:inset 0 0 0 1px rgba(0,0,0,.9),inset 0 0 36px rgba(0,0,0,.72);
      }
      .v53-card::after{
        content:"";position:absolute;inset:4px;pointer-events:none;z-index:20;
        border:1px solid color-mix(in srgb,var(--v53-primary) 45%,transparent);
      }
      .v53-corner{position:absolute;z-index:21;width:min(15%,76px);height:auto;object-fit:contain;pointer-events:none}
      .v53-corner.tl{top:0;left:0}.v53-corner.tr{top:0;right:0}
      .v53-corner.bl{bottom:0;left:0}.v53-corner.br{bottom:0;right:0}

      .v53-brand{
        position:relative;z-index:2;flex:0 0 25%;min-height:82px;max-height:230px;
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        padding:12px 16px 6px;text-align:center;
      }
      .v53-logo{display:block;width:min(72%,330px);height:min(78%,190px);object-fit:contain;filter:drop-shadow(0 5px 10px rgba(0,0,0,.7))}
      .v53-name{font-weight:900;font-size:clamp(20px,2vw,42px);letter-spacing:.05em;color:var(--v53-bright);text-transform:uppercase}
      .v53-ranked-by{margin-top:4px;font-size:clamp(7px,.53vw,11px);letter-spacing:.16em;text-transform:uppercase;color:var(--v53-muted);font-weight:800}

      .v53-reps{
        position:relative;z-index:2;flex:1 1 auto;min-height:0;
        display:grid;grid-template-rows:repeat(var(--v53-rep-count),minmax(0,1fr));
        padding:0 12px;
      }
      .v53-rep{
        position:relative;min-width:0;min-height:0;overflow:hidden;
        display:grid;grid-template-columns:clamp(24px,2.1vw,42px) minmax(0,1fr) auto;
        align-items:center;gap:8px;padding:4px 7px;
        border-bottom:1px solid color-mix(in srgb,var(--v53-primary) 19%,transparent);
        background-position:center;background-size:100% 100%;background-repeat:no-repeat;
      }
      .v53-rep:first-child{color:var(--v53-champion);font-weight:900}
      .v53-rank{font-size:clamp(12px,1.05vw,22px);font-weight:900;text-align:center;color:var(--v53-bright)}
      .v53-medallion{display:block;width:clamp(23px,2.2vw,42px);height:clamp(23px,2.2vw,42px);object-fit:contain;margin:auto}
      .v53-rep-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:clamp(10px,.9vw,18px);font-weight:800;letter-spacing:.02em}
      .v53-rep-value{white-space:nowrap;text-align:right;font-size:clamp(10px,.86vw,18px);font-weight:900;color:var(--v53-bright);font-variant-numeric:tabular-nums}
      .v53-empty{display:grid;place-items:center;color:var(--v53-muted);font-size:12px;padding:16px}

      .v53-totals{
        position:relative;z-index:2;flex:0 0 auto;
        display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
        margin:8px 10px 8px;padding-top:7px;
        border-top:2px solid var(--v53-primary);
      }
      .v53-total{min-width:0;text-align:center;padding:1px 5px;border-right:1px solid color-mix(in srgb,var(--v53-primary) 22%,transparent)}
      .v53-total:last-child{border-right:0}
      .v53-total-value{white-space:nowrap;overflow:hidden;text-overflow:clip;color:var(--v53-bright);font-size:clamp(8px,.72vw,15px);font-weight:900;font-variant-numeric:tabular-nums}
      .v53-total-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;color:var(--v53-muted);font-size:clamp(5px,.4vw,8px);letter-spacing:.11em;text-transform:uppercase}

      .v53-board.v53-narrow .v53-brand{flex-basis:22%;min-height:66px;padding-top:8px}
      .v53-board.v53-narrow .v53-logo{width:min(78%,220px);height:min(80%,135px)}
      .v53-board.v53-narrow .v53-reps{padding:0 7px}
      .v53-board.v53-narrow .v53-rep{grid-template-columns:24px minmax(0,1fr) auto;gap:5px;padding:3px 4px}
      .v53-board.v53-narrow .v53-rep-name,.v53-board.v53-narrow .v53-rep-value{font-size:clamp(8px,.65vw,13px)}
      .v53-board.v53-narrow .v53-totals{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:5px;margin:6px 7px 7px}
      .v53-board.v53-narrow .v53-total:nth-child(2){border-right:0}

      .v53-board.v53-dense .v53-brand{flex-basis:20%;min-height:60px}
      .v53-board.v53-dense .v53-rep{padding-top:2px;padding-bottom:2px}
      .v53-board.v53-dense .v53-rep-name,.v53-board.v53-dense .v53-rep-value{font-size:clamp(7px,.58vw,12px)}

      @media(max-width:1100px){
        .v53-board{gap:7px}.v53-brand{padding-left:9px;padding-right:9px}
        .v53-reps{padding-left:7px;padding-right:7px}.v53-totals{margin-left:7px;margin-right:7px}
      }
    `;
    document.head.appendChild(style);
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

  function visibleTeamNames(mode){
    const selector=mode==="team_vs_team"?".vs-card .vs-name":".all-card .all-name";
    return [...document.querySelectorAll(selector)]
      .map(el=>String(el.textContent||"").trim())
      .filter(Boolean);
  }

  function visibleTeams(data){
    const source=Array.isArray(data.teams)?data.teams:[];
    const byName=new Map(source.map(team=>[norm(team?.summary?.team),team]));
    const names=visibleTeamNames(data.mode);
    const ordered=[];
    const used=new Set();

    names.forEach(name=>{
      const team=byName.get(norm(name));
      if(team&&!used.has(team)){
        ordered.push(team);used.add(team);
      }
    });

    if(ordered.length) return ordered;
    return source.filter(team=>(team.members||[]).some(assigned));
  }

  function themeFor(data,summary){
    const state=data?.theme_state||{};
    const teamId=summary?.team_id;
    if(teamId!==undefined&&teamId!==null&&state.teams?.[String(teamId)]) return state.teams[String(teamId)];
    return state.by_name?.[norm(summary?.team)]||null;
  }

  function formatValue(data,key,value){
    if(typeof fmt==="function") return fmt(value,data.metric_types?.[key],data.currency_symbol);
    return String(value??"");
  }

  function totalKeys(data){
    const selected=(Array.isArray(data.metrics)?data.metrics:[]).filter(k=>!["rank","rep_name","team"].includes(k));
    const preferred=["gross_split","pending_split","net_split","sold_leads","issued_leads","pitched_leads","close_rate","pitched_rate","dpl","sales_retention","avg_gross_sale","avg_net_sale"];
    const out=[];
    preferred.forEach(k=>{if(selected.includes(k)&&!out.includes(k)) out.push(k);});
    selected.forEach(k=>{if(!out.includes(k)) out.push(k);});
    const primary=data.sort_metric;
    let result=out.slice(0,4);
    if(primary&&selected.includes(primary)&&!result.includes(primary)){
      if(result.length<4) result.push(primary);
      else result[result.length-1]=primary;
    }
    return result;
  }

  function addCorners(card,assets){
    [["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]].forEach(([key,pos])=>{
      if(!assets?.[key]) return;
      const img=node("img",`v53-corner ${pos}`);
      img.src=assets[key];img.alt="";
      card.appendChild(img);
    });
  }

  function buildCard(team,data){
    const summary=team.summary||{};
    const rawTheme=themeFor(data,summary);
    const theme=rawTheme&&rawTheme.enabled&&rawTheme.colors?rawTheme:null;
    const colors=theme?.colors||{};
    const assets=theme?.assets||{};
    const members=(Array.isArray(team.members)?team.members:[]).filter(assigned);
    const primary=data.sort_metric;

    const card=node("section","v53-card");
    card.dataset.team=String(summary.team||"");
    if(colors.primary) card.style.setProperty("--v53-primary",colors.primary);
    if(colors.primary_bright) card.style.setProperty("--v53-bright",colors.primary_bright);
    if(colors.panel) card.style.setProperty("--v53-panel",colors.panel);
    if(colors.text) card.style.setProperty("--v53-text",colors.text);
    if(colors.muted) card.style.setProperty("--v53-muted",colors.muted);
    if(colors.champion_text) card.style.setProperty("--v53-champion",colors.champion_text);
    if(assets.background){
      card.style.backgroundImage=`linear-gradient(rgba(4,4,4,.64),rgba(4,4,4,.64)),url("${assets.background}")`;
    }
    addCorners(card,assets);

    const brand=node("div","v53-brand");
    const logoSrc=summary.logo_url||null;
    if(logoSrc){
      const logo=node("img","v53-logo");logo.src=logoSrc;logo.alt=`${summary.team||"Team"} logo`;
      logo.addEventListener("error",()=>{
        logo.remove();
        if(!brand.querySelector(".v53-name")) brand.insertBefore(node("div","v53-name",summary.team||"Team"),brand.firstChild);
      },{once:true});
      brand.appendChild(logo);
    }else{
      brand.appendChild(node("div","v53-name",summary.team||"Team"));
    }
    const ranked=node("div","v53-ranked-by",`Ranked by ${data.metric_labels?.[primary]||primary||"score"}`);
    brand.appendChild(ranked);
    card.appendChild(brand);

    if(members.length){
      const reps=node("div","v53-reps");
      reps.style.setProperty("--v53-rep-count",String(members.length));
      members.forEach((rep,index)=>{
        const row=node("div","v53-rep");
        const rowAsset=index===0?assets.champion:assets.row;
        if(rowAsset){
          const shade=index===0 ? .30 : .48;
          row.style.backgroundImage=`linear-gradient(rgba(0,0,0,${shade}),rgba(0,0,0,${shade})),url("${rowAsset}")`;
        }
        const rank=node("div","v53-rank");
        if(index===0&&assets.medallion){
          const medal=node("img","v53-medallion");medal.src=assets.medallion;medal.alt="1";rank.appendChild(medal);
        }else rank.textContent=String(index+1);
        row.appendChild(rank);
        row.appendChild(node("div","v53-rep-name",rep.rep_name||""));
        row.appendChild(node("div","v53-rep-value",formatValue(data,primary,rep?.[primary])));
        reps.appendChild(row);
      });
      card.appendChild(reps);
    }else{
      const empty=node("div","v53-empty","No assigned reps");empty.style.flex="1 1 auto";card.appendChild(empty);
    }

    const totals=node("div","v53-totals");
    totalKeys(data).forEach(key=>{
      const item=node("div","v53-total");
      item.appendChild(node("div","v53-total-value",formatValue(data,key,summary?.[key])));
      item.appendChild(node("div","v53-total-label",data.metric_labels?.[key]||key));
      totals.appendChild(item);
    });
    card.appendChild(totals);
    return {card,memberCount:members.length};
  }

  function clearComparisonMode(){
    document.body.classList.remove("v53-comparison-mode");
  }

  function renderComparison(data){
    ensureStyles();
    if(!comparisonModes.has(data?.mode)){
      clearComparisonMode();
      return;
    }

    const teams=visibleTeams(data);
    const layout=layoutFor(Math.max(teams.length,1));
    const board=node("div","v53-board");
    board.style.setProperty("--v53-cols",String(layout.cols));
    board.style.setProperty("--v53-rows",String(layout.rows));
    if(layout.cols>=4) board.classList.add("v53-narrow");

    let maxMembers=0;
    teams.forEach(team=>{
      const built=buildCard(team,data);
      maxMembers=Math.max(maxMembers,built.memberCount);
      board.appendChild(built.card);
    });
    if(maxMembers>=7||layout.rows>=3) board.classList.add("v53-dense");

    document.body.classList.add("v53-comparison-mode");
    const root=document.getElementById("scaleRoot");
    if(!root) return;
    root.style.transform="";
    root.innerHTML="";
    if(teams.length) root.appendChild(board);
    else root.appendChild(node("div","empty","No teams with assigned reps"));

    if(typeof fitLeaderboard==="function") setTimeout(fitLeaderboard,0);
  }

  render=function(data){
    const result=previousRender(data);
    renderComparison(data);
    return result;
  };
})();
