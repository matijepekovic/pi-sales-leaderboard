/* v46 purpose-built individual-team broadcast renderer.
   DESIGN/PRESENTATION ONLY: the existing leaderboard renderer remains the sole
   source of filtering, selected columns, values, calculations and totals.
   The saved Team Builder lead has already been moved to the bottom by
   team-lead-display.js; this file only re-composes that display into the theme. */
(function(){
  if(typeof render!=="function") return;
  const ROOT_ID="themedTeamBroadcast";
  const STYLE_ID="themedTeamBroadcastStyles";
  const TEXT_METRICS=new Set(["rank","rep_name","team","home_branch","title","hire_date"]);
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

  function teamTheme(data){
    const s=data.team_summary||{}, state=data.theme_state||{};
    if(s.team_id!=null && state.teams?.[String(s.team_id)]) return state.teams[String(s.team_id)];
    const key=String(s.team||data.selected_team||"").trim().toLowerCase();
    return state.by_name?.[key]||null;
  }

  function activeTheme(data){
    const theme=teamTheme(data);
    return data.mode==="per_team" && theme?.enabled && theme?.colors ? theme : null;
  }

  function removeBroadcast(){
    document.getElementById(ROOT_ID)?.remove();
    document.body.classList.remove("broadcast-team-active");
  }

  function clearLegacyDecor(){
    document.querySelectorAll(".theme-frame,.theme-corner,.theme-hero,.theme-medallion,.theme-total-mark").forEach(el=>el.remove());
  }

  function extractClassicDisplay(data){
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
      rows:bodyRows.map(tr=>{
        const out=readCells(tr);
        out.rep_name=String(tr.dataset.repName||out.rep_name||"").trim();
        out.__team_lead=tr.classList.contains("team-lead-row");
        return out;
      }),
      total:readCells(totalRow)
    };
  }

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      body.broadcast-team-active{padding:0!important;overflow:hidden!important;background:#070706!important}
      body.broadcast-team-active>header,body.broadcast-team-active>#content,body.broadcast-team-active>#status{visibility:hidden!important}
      #${ROOT_ID}{--bt-primary:#c58a2a;--bt-bright:#e1ad48;--bt-dark:#6f4612;--bt-secondary:#8b130c;--bt-bg:#070706;--bt-panel:#11100d;--bt-text:#e8d6ad;--bt-muted:#a3946f;--bt-champ:#f7e7ae;position:fixed;inset:0;z-index:120;overflow:hidden;display:flex;flex-direction:column;color:var(--bt-text);background:var(--bt-bg);font-family:"Arial Narrow","Roboto Condensed",Impact,Arial,sans-serif}
      #${ROOT_ID} *{box-sizing:border-box}
      #${ROOT_ID} .bt-bg{position:absolute;inset:0;z-index:0;background-position:center;background-size:cover;background-repeat:no-repeat}
      #${ROOT_ID} .bt-atmosphere{position:absolute;inset:0;z-index:1;background:radial-gradient(60% 46% at 50% 5%,color-mix(in srgb,var(--bt-bright) 8%,transparent),transparent 62%),radial-gradient(60% 50% at 100% 100%,color-mix(in srgb,var(--bt-secondary) 22%,transparent),transparent 62%),radial-gradient(60% 50% at 0% 100%,color-mix(in srgb,var(--bt-secondary) 18%,transparent),transparent 62%),linear-gradient(rgba(7,7,6,.86),rgba(7,7,6,.91));pointer-events:none}
      #${ROOT_ID} .bt-frame{position:absolute;inset:10px;z-index:30;pointer-events:none;border:2px solid var(--bt-primary);box-shadow:inset 0 0 0 1px #000,inset 0 0 0 5px color-mix(in srgb,var(--bt-primary) 35%,transparent),inset 0 0 70px rgba(0,0,0,.75)}
      #${ROOT_ID} .bt-corner{position:absolute;z-index:31;width:clamp(60px,7vw,120px);height:auto;object-fit:contain;pointer-events:none;filter:drop-shadow(0 2px 5px #000)}
      #${ROOT_ID} .bt-corner.tl{top:6px;left:6px}#${ROOT_ID} .bt-corner.tr{top:6px;right:6px}#${ROOT_ID} .bt-corner.bl{bottom:6px;left:6px}#${ROOT_ID} .bt-corner.br{bottom:6px;right:6px}
      #${ROOT_ID} .bt-header{position:relative;z-index:4;flex:0 0 auto;text-align:center;padding:clamp(6px,1vh,14px) clamp(28px,3vw,50px) 2px}
      #${ROOT_ID} .bt-hero{display:block;width:min(72vw,1160px);height:clamp(185px,38vh,420px);margin:0 auto;object-fit:contain;filter:drop-shadow(0 5px 14px rgba(0,0,0,.9))}
      #${ROOT_ID}.dense .bt-hero{height:clamp(130px,28vh,285px);width:min(64vw,920px)}#${ROOT_ID}.very-dense .bt-hero{height:clamp(100px,22vh,230px);width:min(58vw,800px)}
      #${ROOT_ID} .bt-wordmark{height:clamp(130px,29vh,310px);display:flex;align-items:center;justify-content:center;font-family:Impact,"Arial Narrow",sans-serif;font-size:clamp(54px,8vw,138px);letter-spacing:.035em;text-transform:uppercase;color:var(--bt-bright);text-shadow:0 3px 0 #000,0 0 16px color-mix(in srgb,var(--bt-bright) 30%,transparent)}
      #${ROOT_ID}.dense .bt-wordmark{height:clamp(100px,22vh,225px);font-size:clamp(46px,6.5vw,108px)}
      #${ROOT_ID} .bt-side{position:absolute;top:clamp(16px,2vh,28px);right:clamp(24px,3vw,52px);z-index:8;text-align:right;text-transform:uppercase;line-height:1.45;letter-spacing:.2em;font-weight:800;text-shadow:0 2px 4px #000}
      #${ROOT_ID} .bt-side .top{font-size:clamp(9px,.9vw,15px);color:var(--bt-muted)}#${ROOT_ID} .bt-side .bottom{font-size:clamp(10px,1.05vw,17px);color:var(--bt-bright);max-width:300px}
      #${ROOT_ID} .bt-main{position:relative;z-index:4;flex:1 1 auto;min-height:0;width:min(94.5%,1810px);margin:0 auto;display:flex;flex-direction:column}
      #${ROOT_ID} .bt-head,#${ROOT_ID} .bt-row,#${ROOT_ID} .bt-footer{display:grid;grid-template-columns:clamp(58px,4.2vw,82px) minmax(220px,2.45fr) repeat(var(--bt-cols),minmax(0,1fr));align-items:center}
      #${ROOT_ID} .bt-head{flex:0 0 auto;color:var(--bt-bright);text-transform:uppercase;letter-spacing:.12em;text-align:center;font-size:clamp(8px,.72vw,12px);font-weight:800;padding:7px 0;border-top:1px solid color-mix(in srgb,var(--bt-primary) 48%,transparent);border-bottom:1px solid color-mix(in srgb,var(--bt-primary) 48%,transparent);background:rgba(6,6,5,.92);text-shadow:0 1px 3px #000}
      #${ROOT_ID} .bt-head .rep{text-align:left;padding-left:10px;color:var(--bt-muted)}
      #${ROOT_ID} .bt-board{flex:1 1 auto;min-height:0;overflow:hidden;display:flex;flex-direction:column;gap:1px}
      #${ROOT_ID} .bt-row{position:relative;flex:1 1 0;min-height:0;max-height:none;background-position:center;background-size:100% 100%;background-repeat:no-repeat;border-bottom:1px solid color-mix(in srgb,var(--bt-primary) 13%,transparent);overflow:hidden}
      #${ROOT_ID}.dense .bt-row{min-height:38px;max-height:67px}#${ROOT_ID}.very-dense .bt-row{min-height:31px;max-height:55px}
      #${ROOT_ID} .bt-row:before{content:"";position:absolute;inset:0;z-index:0;background:rgba(4,4,3,.56);pointer-events:none}#${ROOT_ID} .bt-row>*{position:relative;z-index:1}
      #${ROOT_ID} .bt-rank{font-family:Impact,"Arial Narrow",sans-serif;text-align:center;color:var(--bt-bright);font-size:clamp(23px,2.65vw,46px);font-weight:900;text-shadow:0 2px 4px #000;min-width:0}
      #${ROOT_ID}.dense .bt-rank{font-size:clamp(20px,2.15vw,36px)}
      #${ROOT_ID} .bt-rep{padding:4px 10px;min-width:0;overflow:hidden}#${ROOT_ID} .bt-name{font-family:Impact,"Arial Narrow",sans-serif;color:var(--bt-bright);font-size:clamp(14px,1.32vw,23px);letter-spacing:.02em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 2px 3px #000}
      #${ROOT_ID}.dense .bt-name{font-size:clamp(12px,1.12vw,19px)}
      #${ROOT_ID} .bt-stat{align-self:stretch;display:flex;align-items:center;justify-content:center;text-align:center;border-left:1px solid color-mix(in srgb,var(--bt-primary) 24%,transparent);font-variant-numeric:tabular-nums;font-weight:800;font-size:clamp(10px,.88vw,16px);text-shadow:0 2px 3px #000;white-space:nowrap;overflow:hidden;padding:0 3px}#${ROOT_ID}.dense .bt-stat{font-size:clamp(9px,.76vw,13px)}
      #${ROOT_ID} .bt-stat.money{color:var(--bt-bright)}#${ROOT_ID} .bt-stat.primary{color:var(--bt-champ);font-weight:900;position:relative}
      #${ROOT_ID} .champion{flex:1.18 1 0;min-height:0;max-height:none;margin:4px 0;border:2px solid var(--bt-bright);border-radius:7px;box-shadow:0 0 34px color-mix(in srgb,var(--bt-bright) 34%,transparent),inset 0 0 0 1px color-mix(in srgb,var(--bt-champ) 28%,transparent),0 4px 26px rgba(0,0,0,.82)}
      #${ROOT_ID} .champion:before{background:rgba(30,4,3,.12)}#${ROOT_ID} .champion:after{content:"";position:absolute;top:0;bottom:0;width:28%;z-index:2;background:linear-gradient(105deg,transparent,color-mix(in srgb,var(--bt-champ) 15%,transparent),transparent);animation:btShimmer 8s linear infinite;pointer-events:none}@keyframes btShimmer{from{left:-35%}to{left:135%}}
      #${ROOT_ID} .champion .bt-name{color:var(--bt-champ);font-size:clamp(15px,1.45vw,25px)}#${ROOT_ID} .bt-medal{display:block;width:clamp(48px,5.2vw,88px);height:clamp(48px,7.2vh,88px);object-fit:contain;margin:auto;filter:drop-shadow(0 3px 10px rgba(0,0,0,.9))}#${ROOT_ID}.dense .bt-medal{width:clamp(38px,4.2vw,64px);height:clamp(38px,5.6vh,64px)}
      #${ROOT_ID} .champion .bt-stat.primary:after{content:"";position:absolute;left:16%;right:16%;bottom:18%;height:2px;background:linear-gradient(90deg,transparent,var(--bt-bright),transparent);box-shadow:0 0 8px color-mix(in srgb,var(--bt-bright) 85%,transparent)}
      #${ROOT_ID} .team-lead{flex:1 1 0;min-height:0;max-height:none;margin-top:2px;border-top:1px solid color-mix(in srgb,var(--bt-primary) 42%,transparent)}
      #${ROOT_ID} .team-lead .bt-name{color:var(--bt-text)}
      #${ROOT_ID} .bt-tl-mark{display:block;width:clamp(38px,4.6vw,74px);height:clamp(30px,5.7vh,64px);object-fit:contain;margin:auto;filter:drop-shadow(0 2px 7px #000)}
      #${ROOT_ID} .bt-footer{position:relative;z-index:4;flex:0 0 auto;width:min(94.5%,1810px);margin:clamp(4px,.65vh,9px) auto clamp(9px,1.4vh,18px);border-top:2px solid var(--bt-primary);background:rgba(0,0,0,.62);padding:clamp(6px,.9vh,11px) 0;min-height:54px}
      #${ROOT_ID} .bt-footer-spacer{grid-column:span 2;align-self:stretch}
      #${ROOT_ID} .bt-total{text-align:center;border-left:1px solid color-mix(in srgb,var(--bt-primary) 28%,transparent);padding:0 4px;min-width:0}#${ROOT_ID} .bt-total-v{color:var(--bt-bright);font-size:clamp(12px,1.18vw,21px);font-weight:900;white-space:nowrap;overflow:hidden;font-variant-numeric:tabular-nums;text-shadow:0 2px 3px #000}#${ROOT_ID} .bt-total-l{color:var(--bt-muted);font-size:clamp(6px,.54vw,9px);letter-spacing:.12em;text-transform:uppercase;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      @media(prefers-reduced-motion:reduce){#${ROOT_ID} .champion:after{animation:none}}
    `;
    document.head.appendChild(style);
  }

  function setVars(root,c={}){
    const map={primary:"--bt-primary",primary_bright:"--bt-bright",primary_dark:"--bt-dark",secondary:"--bt-secondary",background:"--bt-bg",panel:"--bt-panel",text:"--bt-text",muted:"--bt-muted",champion_text:"--bt-champ"};
    Object.entries(map).forEach(([key,name])=>{if(c[key])root.style.setProperty(name,c[key]);});
  }

  function cssUrl(url){return `url("${String(url||"").replace(/["\\\n\r]/g,"")}")`;}

  function selectedStats(data,display){
    return display.metrics.filter(k=>!TEXT_METRICS.has(k) && (typeof isNumber!=="function"||isNumber(data.metric_types?.[k])));
  }

  function rowHTML(row,rank,data,theme,stats){
    const a=theme.assets||{};
    const isLead=!!row.__team_lead;
    const champion=!isLead && rank===1;
    const bg=champion?(a.champion||a.row):a.row;
    const name=row.rep_name || (isLead?"TEAM LEAD":`REP ${rank||""}`);
    let rankHTML="";
    if(isLead){
      rankHTML=a.totals_mark?`<img class="bt-tl-mark" src="${esc(a.totals_mark)}" alt="TL">`:"TL";
    }else if(champion&&a.medallion){
      rankHTML=`<img class="bt-medal" src="${esc(a.medallion)}" alt="Champion">`;
    }else{
      rankHTML=String(rank);
    }
    return `<div class="bt-row ${champion?"champion":""} ${isLead?"team-lead":""}" style="${bg?`background-image:${cssUrl(bg)}`:""}"><div class="bt-rank">${rankHTML}</div><div class="bt-rep"><div class="bt-name">${esc(name)}</div></div>${stats.map(k=>`<div class="bt-stat ${data.metric_types?.[k]==="currency"?"money":""} ${k===data.sort_metric?"primary":""}">${esc(row[k]||"")}</div>`).join("")}</div>`;
  }

  function build(data,theme,display){
    ensureStyles();
    removeBroadcast();
    clearLegacyDecor();
    const a=theme.assets||{}, c=theme.colors||{}, stats=selectedStats(data,display);
    const summary=data.team_summary||{}, teamName=summary.team||data.selected_team||data.title||"TEAM";
    const customHero=a.hero&&String(a.hero).includes("/api/theme-assets/");
    const hero=customHero?a.hero:(String(teamName).trim().toLowerCase()==="undisputed"&&a.hero?a.hero:summary.logo_url||null);
    const root=document.createElement("section");
    root.id=ROOT_ID;
    root.style.setProperty("--bt-cols",Math.max(stats.length,1));
    setVars(root,c);

    let competitiveRank=0;
    const rowsHTML=display.rows.map(row=>{
      const rank=row.__team_lead?null:++competitiveRank;
      return rowHTML(row,rank,data,theme,stats);
    }).join("");

    root.innerHTML=`<div class="bt-bg"></div><div class="bt-atmosphere"></div><div class="bt-frame"></div>${[["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]].map(([k,p])=>a[k]?`<img class="bt-corner ${p}" src="${esc(a[k])}" alt="">`:"").join("")}<header class="bt-header">${hero?`<img class="bt-hero" src="${esc(hero)}" alt="${esc(teamName)}">`:`<div class="bt-wordmark">${esc(teamName)}</div>`}<div class="bt-side"><div class="bottom">${esc(data.subtitle||"")}</div></div></header><main class="bt-main"><div class="bt-head"><div></div><div class="rep">Rep</div>${stats.map(k=>`<div>${esc(data.metric_labels?.[k]||k)}</div>`).join("")}</div><div class="bt-board">${rowsHTML}</div></main>${stats.length?`<footer class="bt-footer"><div class="bt-footer-spacer"></div>${stats.map(k=>`<div class="bt-total"><div class="bt-total-v">${esc(display.total[k]||"")}</div><div class="bt-total-l">${esc(data.metric_labels?.[k]||k)}</div></div>`).join("")}</footer>`:""}`;

    const bg=root.querySelector(".bt-bg");
    bg.style.backgroundColor=c.background||"#070706";
    if(a.background) bg.style.backgroundImage=cssUrl(a.background);
    document.body.classList.add("broadcast-team-active");
    document.body.appendChild(root);
  }

  Display.stage(50, function(data, next){
    const result=next(data); // all existing app functionality runs first
    const theme=activeTheme(data);
    if(!theme){removeBroadcast();return result;}
    const display=extractClassicDisplay(data); // consume exactly what Classic rendered
    if(display) build(data,theme,display); else removeBroadcast();
    return result;
  });
})();
