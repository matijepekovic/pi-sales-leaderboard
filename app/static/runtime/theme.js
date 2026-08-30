/* Theme runtime -- team identity on top of the screens.

   Artwork, colours, corners and transforms, plus the Theme Builder
   preview, which only wakes up under ?themeEditor=1.

   Consolidated from the versioned patch stack. Each section below was its own
   file, wrapping the previous one by reassigning render(). They now register
   ordered stages instead, so this grouping is presentation only -- the
   execution order is the numbers, not the file boundaries. */


/* ------------------------------------------------------------------
   theme-runtime.js   (stage/style order 30)
   ------------------------------------------------------------------ */
/* Team theme runtime.
   The existing leaderboard renderer remains responsible for data/layout.
   This layer applies persistent team identity after each normal render. */
(function(){
  if(typeof render !== "function") return;

  const STYLE_ID="pi-theme-runtime-style";
  if(!document.getElementById(STYLE_ID)){
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      :root{
        --theme-primary:var(--gold,#d8b34a);
        --theme-primary-bright:#e6c760;
        --theme-primary-dark:#705b20;
        --theme-secondary:#303030;
        --theme-bg:var(--bg,#080808);
        --theme-panel:var(--panel,#111111);
        --theme-text:var(--text,#f5f5f5);
        --theme-muted:var(--muted,#9c9c9c);
        --theme-champion-text:#fff;
      }
      body.team-theme-full{
        color:var(--theme-text);
        background-color:var(--theme-bg)!important;
        background-position:center!important;
        background-size:cover!important;
        background-repeat:no-repeat!important;
      }
      body.team-theme-full header{
        position:relative;z-index:20;border-bottom-color:color-mix(in srgb,var(--theme-primary) 55%,transparent);
      }
      body.team-theme-full #title{color:var(--theme-primary-bright)}
      body.team-theme-full .subtitle{color:var(--theme-muted)}
      body.team-theme-full .mode{color:var(--theme-primary-bright)}
      body.team-theme-full th{color:var(--theme-muted);border-bottom-color:color-mix(in srgb,var(--theme-primary) 45%,transparent)}
      body.team-theme-full td{border-bottom-color:color-mix(in srgb,var(--theme-primary) 16%,transparent)}
      body.team-theme-full .rank{color:var(--theme-primary-bright)}
      body.team-theme-full .total-row td{
        color:var(--theme-primary-bright)!important;
        border-top-color:var(--theme-primary)!important;
        background:color-mix(in srgb,var(--theme-bg) 84%,black)!important;
      }
      .theme-frame{
        position:fixed;inset:10px;z-index:80;pointer-events:none;
        border:2px solid var(--theme-primary);
        box-shadow:inset 0 0 0 1px #000,
          inset 0 0 0 5px color-mix(in srgb,var(--theme-primary) 32%,transparent),
          inset 0 0 70px rgba(0,0,0,.72);
      }
      .theme-corner{
        position:fixed;z-index:81;width:clamp(58px,7vw,120px);pointer-events:none;
        object-fit:contain;filter:drop-shadow(0 2px 5px rgba(0,0,0,.8));
      }
      .theme-corner.tl{top:6px;left:6px}.theme-corner.tr{top:6px;right:6px}
      .theme-corner.bl{bottom:6px;left:6px}.theme-corner.br{bottom:6px;right:6px}
      .theme-hero{
        display:block;max-height:clamp(72px,15vh,180px);max-width:min(56vw,900px);
        object-fit:contain;filter:drop-shadow(0 4px 10px rgba(0,0,0,.8));
        margin:0 18px 0 0;
      }
      .theme-office-logo{
        grid-column:1;grid-row:1 / 3;
        width:clamp(86px,9vw,170px);height:clamp(66px,10vh,128px);
        object-fit:contain;align-self:center;justify-self:start;
        filter:drop-shadow(0 4px 10px rgba(0,0,0,.8));
      }
      header.theme-office-logo-active>div:first-child{
        display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:auto auto;
        column-gap:16px;align-items:center;min-width:0;
      }
      header.theme-office-logo-active #title{
        grid-column:2;grid-row:1;align-self:end;
      }
      header.theme-office-logo-active .subtitle{
        grid-column:2;grid-row:2;align-self:start;
      }
      body.team-theme-full header.theme-has-hero #title{display:none}
      body.team-theme-full header.theme-has-hero>div:first-child{
        display:flex;align-items:center;gap:14px;min-width:0;
      }
      body.team-theme-full tbody tr.theme-standard-row td{
        background-image:linear-gradient(rgba(4,4,3,.57),rgba(4,4,3,.57)),var(--theme-row-image);
        background-size:100% 100%;background-position:center;
      }
      body.team-theme-full tbody tr.theme-champion-row td{
        color:var(--theme-champion-text)!important;
        background-image:var(--theme-champion-image)!important;
        background-size:100% 100%!important;background-position:center!important;
        border-top:2px solid var(--theme-primary-bright)!important;
        border-bottom:2px solid var(--theme-primary-bright)!important;
        box-shadow:0 0 22px color-mix(in srgb,var(--theme-primary-bright) 28%,transparent);
        font-weight:900;
      }
      .theme-medallion{display:block;width:clamp(34px,3vw,62px);height:clamp(34px,3vw,62px);object-fit:contain;margin:auto;filter:drop-shadow(0 3px 8px #000)}
      .theme-total-mark{height:30px;max-width:90px;object-fit:contain;vertical-align:middle;margin-right:8px}

      /* Per-team identity in comparison modes. These do not recolor the office shell. */
      .team-themed-card{
        --card-primary:#d8b34a;--card-bright:#e6c760;--card-panel:#111;--card-text:#f5f5f5;--card-muted:#9c9c9c;
        border-color:var(--card-primary)!important;
        color:var(--card-text)!important;
        box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--card-primary) 20%,transparent),0 0 22px rgba(0,0,0,.35)!important;
        background-color:var(--card-panel)!important;
        background-position:center!important;background-size:cover!important;
      }
      .team-themed-card .vs-head,.team-themed-card .team-head{
        background:color-mix(in srgb,var(--card-panel) 88%,black)!important;
        border-color:color-mix(in srgb,var(--card-primary) 30%,transparent)!important;
      }
      .team-themed-card .vs-name,.team-themed-card .team-name,.team-themed-card .all-name{color:var(--card-bright)!important}
      .team-themed-card .vs-leader,.team-themed-card .all-leader,.team-themed-card .all-stat-label,.team-themed-card .all-mvp-kicker{color:var(--card-muted)!important}
      .team-themed-card .vs-rank-rule,.team-themed-card .vs-rep-rank,.team-themed-card .all-rank-pill,.team-themed-card .all-stat-value,.team-themed-card .all-mvp-score{color:var(--card-bright)!important}
      .all-card.team-themed-card{border-color:var(--card-primary)!important;background-color:var(--card-panel)!important}
      .team-themed-card .all-top,.team-themed-card .all-mvp{border-color:color-mix(in srgb,var(--card-primary) 30%,transparent)!important}
    `;
    Display.placeStyle(30, style);
  }


  function hexTheme(theme){
    return theme && theme.enabled && theme.colors ? theme : null;
  }

  function setVars(target,colors,prefix="--theme-"){
    const map={
      primary:"primary",primary_bright:"primary-bright",primary_dark:"primary-dark",
      secondary:"secondary",background:"bg",panel:"panel",text:"text",muted:"muted",
      champion_text:"champion-text"
    };
    Object.entries(map).forEach(([key,name])=>{
      if(colors && colors[key]) target.style.setProperty(prefix+name,colors[key]);
    });
  }

  function removeDecor(){
    document.querySelectorAll(".theme-frame,.theme-corner,.theme-hero,.theme-office-logo").forEach(el=>el.remove());
    document.body.classList.remove("team-theme-full");
    const header=document.querySelector("header");
    if(header) header.classList.remove("theme-has-hero","theme-office-logo-active");
    document.documentElement.style.removeProperty("--theme-row-image");
    document.documentElement.style.removeProperty("--theme-champion-image");
    document.querySelectorAll(".theme-standard-row,.theme-champion-row").forEach(el=>{
      el.classList.remove("theme-standard-row","theme-champion-row");
    });
    document.querySelectorAll(".theme-medallion,.theme-total-mark").forEach(el=>el.remove());
    document.querySelectorAll(".team-themed-card").forEach(el=>{
      el.classList.remove("team-themed-card");
      ["--card-primary","--card-bright","--card-panel","--card-text","--card-muted"].forEach(k=>el.style.removeProperty(k));
      el.style.removeProperty("background-image");
    });
  }

  function lookupTheme(data,teamName,teamId){
    const state=data.theme_state||{};
    if(teamId!==undefined && teamId!==null && state.teams && state.teams[String(teamId)]){
      return state.teams[String(teamId)];
    }
    if(teamName && state.by_name){
      return state.by_name[String(teamName).trim().toLowerCase()]||null;
    }
    return null;
  }

  function injectFrame(theme){
    const a=theme.assets||{};
    const frame=document.createElement("div");frame.className="theme-frame";document.body.appendChild(frame);
    [["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]].forEach(([key,pos])=>{
      if(!a[key]) return;
      const img=document.createElement("img");img.className=`theme-corner ${pos}`;img.src=a[key];img.alt="";document.body.appendChild(img);
    });
  }

  function chooseHero(data,theme){
    if(data.mode==="whole_office") return null;
    const assets=theme.assets||{};
    const selected=String(data.selected_team||"").trim();
    const summary=data.team_summary||{};
    const customHero=assets.hero && String(assets.hero).includes("/api/theme-assets/");
    if(customHero) return assets.hero;
    if(selected.toLowerCase()==="undisputed" && assets.hero) return assets.hero;
    if(summary.logo_url) return summary.logo_url;
    return null;
  }

  function renderedOfficeWinner(data){
    const metrics=Array.isArray(data.metrics)?data.metrics:[];
    const first=document.querySelector("#scaleRoot table tbody tr:not(.total-row)");
    if(!first) return null;

    let teamName="";
    const teamIndex=metrics.indexOf("team");
    if(teamIndex>=0 && first.cells[teamIndex]){
      teamName=String(first.cells[teamIndex].textContent||"").trim();
    }

    let repName="";
    const repIndex=metrics.indexOf("rep_name");
    if(repIndex>=0 && first.cells[repIndex]){
      repName=String(first.cells[repIndex].textContent||"").trim();
    }

    const source=(data.rows||[]).find(row=>{
      if(repName && String(row?.rep_name||"").trim()!==repName) return false;
      if(teamName && String(row?.team||"").trim()!==teamName) return false;
      return !!(repName||teamName);
    })||null;
    if(!teamName && source) teamName=String(source.team||"").trim();
    if(!teamName) return null;

    return {
      team_name:teamName,
      team_id:source?.assigned_team_id||source?.team_id||null,
      rep_name:repName||source?.rep_name||""
    };
  }

  function injectOfficeLogo(data,theme){
    const teamId=Number(theme?.team_id||0);
    if(!teamId) return;
    const header=document.querySelector("header");
    const first=header&&header.querySelector(":scope > div:first-child");
    if(!header||!first) return;
    const img=document.createElement("img");
    img.className="theme-office-logo";
    img.src=`/api/teams/${teamId}/logo?v=${Number(data.organization_version||0)}`;
    img.alt=theme.team_name||"Leading team";
    img.addEventListener("error",()=>{img.remove();header.classList.remove("theme-office-logo-active");},{once:true});
    first.insertBefore(img,first.firstChild);
    header.classList.add("theme-office-logo-active");
  }

  function applyFullTheme(data,theme){
    theme=hexTheme(theme);if(!theme) return;
    document.body.classList.add("team-theme-full");
    setVars(document.documentElement,theme.colors);
    const assets=theme.assets||{};
    if(assets.background){
      document.body.style.backgroundImage=`linear-gradient(rgba(7,7,6,.88),rgba(7,7,6,.88)),url("${assets.background}")`;
    }else{
      document.body.style.backgroundImage="none";
    }
    injectFrame(theme);

    const header=document.querySelector("header");
    const first=header && header.querySelector(":scope > div:first-child");
    const hero=chooseHero(data,theme);
    if(first && hero){
      const img=document.createElement("img");img.className="theme-hero";img.src=hero;img.alt="Team branding";
      first.insertBefore(img,first.firstChild);header.classList.add("theme-has-hero");
    }

    if(assets.row) document.documentElement.style.setProperty("--theme-row-image",`url("${assets.row}")`);
    else document.documentElement.style.setProperty("--theme-row-image","none");
    if(assets.champion) document.documentElement.style.setProperty("--theme-champion-image",`url("${assets.champion}")`);
    else document.documentElement.style.setProperty("--theme-champion-image","none");

    const rows=[...document.querySelectorAll("table tbody tr:not(.total-row)")];
    rows.forEach((row,index)=>row.classList.add(index===0?"theme-champion-row":"theme-standard-row"));

    if(rows.length && assets.medallion){
      const rankIndex=(data.metrics||[]).indexOf("rank");
      if(rankIndex>=0 && rows[0].cells[rankIndex]){
        const cell=rows[0].cells[rankIndex];
        cell.innerHTML="";
        const img=document.createElement("img");img.className="theme-medallion";img.src=assets.medallion;img.alt="Champion";cell.appendChild(img);
      }
    }

    if(assets.totals_mark && data.mode==="per_team"){
      const total=document.querySelector("tr.total-row");
      if(total && total.cells.length){
        const img=document.createElement("img");img.className="theme-total-mark";img.src=assets.totals_mark;img.alt="";total.cells[0].prepend(img);
      }
    }
  }

  function cardTheme(card,theme){
    theme=hexTheme(theme);if(!card||!theme) return;
    card.classList.add("team-themed-card");
    const c=theme.colors||{};
    if(c.primary) card.style.setProperty("--card-primary",c.primary);
    if(c.primary_bright) card.style.setProperty("--card-bright",c.primary_bright);
    if(c.panel) card.style.setProperty("--card-panel",c.panel);
    if(c.text) card.style.setProperty("--card-text",c.text);
    if(c.muted) card.style.setProperty("--card-muted",c.muted);
    const bg=theme.assets && (theme.assets.row||theme.assets.background);
    if(bg) card.style.backgroundImage=`linear-gradient(rgba(5,5,5,.76),rgba(5,5,5,.76)),url("${bg}")`;
  }

  function applyComparisonThemes(data){
    if(data.mode==="team_vs_team"){
      const cards=[...document.querySelectorAll(".vs-card")];
      (data.teams||[]).slice(0,cards.length).forEach((team,i)=>{
        const s=team.summary||{};cardTheme(cards[i],lookupTheme(data,s.team,s.team_id));
      });
    }else if(data.mode==="all_teams"){
      const cards=[...document.querySelectorAll(".all-card")];
      (data.teams||[]).slice(0,cards.length).forEach((team,i)=>{
        const s=team.summary||{};cardTheme(cards[i],lookupTheme(data,s.team,s.team_id));
      });
    }
  }

  function applyTheme(data){
    removeDecor();
    document.body.style.removeProperty("background-image");
    if(data.mode==="per_team"){
      const summary=data.team_summary||{};
      applyFullTheme(data,lookupTheme(data,summary.team,summary.team_id));
    }else if(data.mode==="whole_office"){
      const winner=renderedOfficeWinner(data);
      const winningTheme=winner?lookupTheme(data,winner.team_name,winner.team_id):null;
      if(winningTheme) injectOfficeLogo(data,winningTheme);
      applyFullTheme(data,winningTheme);
    }else{
      applyComparisonThemes(data);
    }
    if(typeof fitLeaderboard==="function") setTimeout(fitLeaderboard,0);
  }

  Display.stage(30, function(data, next){
    next(data);
    applyTheme(data);
  });
})();


/* ------------------------------------------------------------------
   theme-team-cards.js   (stage/style order 40)
   ------------------------------------------------------------------ */
/* v43 card-theme ordering guard.
   The v36 display layer can remove/reorder teams after excluding reps without a
   local Pi assignment. Match the final DOM card by rendered team name so a theme
   can never be applied to a neighboring team after that filtering step. */
(function(){
  if(typeof render!=="function") return;

  function themeForName(data,name){
    const key=String(name||"").trim().toLowerCase();
    return data?.theme_state?.by_name?.[key]||null;
  }

  function resetCard(card){
    if(!card) return;
    card.classList.remove("team-themed-card");
    ["--card-primary","--card-bright","--card-panel","--card-text","--card-muted"].forEach(k=>card.style.removeProperty(k));
    card.style.removeProperty("background-image");
  }

  function applyCard(card,theme){
    resetCard(card);
    if(!card||!theme||!theme.enabled||!theme.colors) return;
    const c=theme.colors;
    card.classList.add("team-themed-card");
    if(c.primary) card.style.setProperty("--card-primary",c.primary);
    if(c.primary_bright) card.style.setProperty("--card-bright",c.primary_bright);
    if(c.panel) card.style.setProperty("--card-panel",c.panel);
    if(c.text) card.style.setProperty("--card-text",c.text);
    if(c.muted) card.style.setProperty("--card-muted",c.muted);
    const bg=theme.assets&&(theme.assets.row||theme.assets.background);
    if(bg) card.style.backgroundImage=`linear-gradient(rgba(5,5,5,.76),rgba(5,5,5,.76)),url("${bg}")`;
  }

  function correctFinalCards(data){
    if(data.mode==="team_vs_team"){
      document.querySelectorAll(".vs-card").forEach(card=>{
        const name=card.querySelector(".vs-name")?.textContent?.trim()||"";
        applyCard(card,themeForName(data,name));
      });
    }else if(data.mode==="all_teams"){
      document.querySelectorAll(".all-card").forEach(card=>{
        const name=card.querySelector(".all-name")?.textContent?.trim()||"";
        applyCard(card,themeForName(data,name));
      });
    }
  }

  Display.stage(40, function(data, next){
    const result=next(data);
    correctFinalCards(data);
    return result;
  });
})();


/* ------------------------------------------------------------------
   theme-team-layout.js   (stage/style order 50)
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   champion-row-assets.js   (stage/style order 70)
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   theme-corners.js   (stage/style order 140)
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   theme-extras.js   (stage/style order 150)
   ------------------------------------------------------------------ */
/* v69 theme extras.
   Applies the two new theme-owned presentation settings after the existing
   render stack: alternating row tint and per-team hero scale. Defaults are
   deliberately no-op (stripe strength 0, hero 100%). */
(function(){
  if(typeof render!=="function")return;
  const STYLE_ID="themeExtrasV69Styles";
  const norm=v=>String(v||"").trim().toLowerCase();

  function clamp(value,min,max,def){
    value=Number(value);
    return Number.isFinite(value)?Math.min(max,Math.max(min,value)):def;
  }

  function ensureStyles(){
    if(document.getElementById(STYLE_ID))return;
    const style=document.createElement("style");style.id=STYLE_ID;
    style.textContent=`
      #themedTeamBroadcast.v69-stripe-on .bt-row:nth-child(even):before{
        background:color-mix(in srgb,var(--v69-stripe-color) var(--v69-stripe-strength),rgba(4,4,3,.56));
      }
      #v55OfficeBroadcast.v69-stripe-on .v55-office-row:nth-child(even) .v55-office-row-shade{
        background:color-mix(in srgb,var(--v69-stripe-color) var(--v69-stripe-strength),rgba(4,4,3,.50));
      }
      .v69-team-card.v69-stripe-on .v69-row:nth-child(even):before{
        background:color-mix(in srgb,var(--v69-stripe-color) var(--v69-stripe-strength),rgba(4,4,3,.54));
      }
      #themedTeamBroadcast .bt-hero{height:var(--v69-team-hero-height,clamp(185px,38vh,420px))!important}
    `;
    document.head.appendChild(style);
  }

  function themeFor(data,teamName,teamId){
    const state=data?.theme_state||{};
    if(teamId!==undefined&&teamId!==null&&state.teams?.[String(teamId)])return state.teams[String(teamId)];
    return teamName?state.by_name?.[norm(teamName)]||null:null;
  }

  function stripeConfig(theme){
    const raw=theme?.row_stripe||{};
    const strength=clamp(raw.strength,0,100,0);
    const color=String(raw.color||theme?.colors?.primary||"#d8b34a").trim();
    return {color,strength};
  }

  function applyStripe(root,theme){
    if(!root)return;
    const cfg=stripeConfig(theme);
    root.style.setProperty("--v69-stripe-color",cfg.color);
    root.style.setProperty("--v69-stripe-strength",`${cfg.strength}%`);
    root.classList.toggle("v69-stripe-on",cfg.strength>0);
  }

  function wholeOfficeTheme(data){
    const root=document.getElementById("v55OfficeBroadcast");if(!root)return null;
    const repName=String(root.querySelector(".v55-office-row .v55-office-name")?.textContent||"").trim();
    const source=(data?.rows||[]).find(row=>repName&&norm(row?.rep_name)===norm(repName))||null;
    return source?themeFor(data,source.team,source.assigned_team_id||source.team_id):null;
  }

  function applyPerTeam(data){
    const root=document.getElementById("themedTeamBroadcast");if(!root)return;
    const summary=data?.team_summary||{};
    const theme=themeFor(data,summary.team,summary.team_id);
    applyStripe(root,theme);
    const scale=clamp(theme?.hero_scale,50,200,100)/100;
    const base=Math.max(185,Math.min(420,window.innerHeight*.38));
    root.style.setProperty("--v69-team-hero-height",`${(base*scale).toFixed(2)}px`);
  }

  function apply(data){
    ensureStyles();
    if(data?.mode==="per_team"){
      applyPerTeam(data);
      return;
    }
    if(data?.mode==="whole_office"){
      const root=document.getElementById("v55OfficeBroadcast");
      applyStripe(root,wholeOfficeTheme(data));
      return;
    }
    if(data?.mode==="team_vs_team"||data?.mode==="all_teams"){
      document.querySelectorAll(".v69-team-card").forEach(card=>{
        const id=Number(card.dataset.teamId||0)||null;
        applyStripe(card,themeFor(data,card.dataset.team,id));
      });
    }
  }

  Display.stage(150, function(data, next){
    const result=next(data);
    apply(data);
    requestAnimationFrame(()=>apply(data));
    setTimeout(()=>apply(data),80);
    return result;
  });
})();


/* ------------------------------------------------------------------
   theme-colors.js   (stage/style order 160)
   ------------------------------------------------------------------ */
/* v127 color semantics for team themes.
   The stored color model already contains these values; this layer makes the
   previously weak/unused dark and panel colors visibly meaningful without
   changing theme data or the leaderboard renderer. */
(function(){
  const STYLE_ID="themeColorRuntimeV127Styles";
  if(document.getElementById(STYLE_ID))return;
  const style=document.createElement("style");
  style.id=STYLE_ID;
  style.textContent=`
    #themedTeamBroadcast .bt-frame{
      box-shadow:
        inset 0 0 0 1px #000,
        inset 0 0 0 5px color-mix(in srgb,var(--bt-primary) 35%,transparent),
        inset 0 0 72px color-mix(in srgb,var(--bt-dark) 58%,black),
        0 0 28px color-mix(in srgb,var(--bt-secondary) 22%,transparent)!important
    }
    #themedTeamBroadcast .bt-head{
      background:color-mix(in srgb,var(--bt-panel) 90%,black)!important
    }
    #themedTeamBroadcast .bt-row{
      background-color:var(--bt-panel)!important
    }
    #themedTeamBroadcast .bt-row:before{
      background:color-mix(in srgb,var(--bt-panel) 48%,rgba(4,4,3,.56))
    }
    #themedTeamBroadcast .champion:before{
      background:color-mix(in srgb,var(--bt-dark) 34%,transparent)!important
    }
    #themedTeamBroadcast .bt-footer{
      background:color-mix(in srgb,var(--bt-panel) 82%,black)!important
    }
    body.team-theme-full .theme-frame{
      box-shadow:
        inset 0 0 0 1px #000,
        inset 0 0 0 5px color-mix(in srgb,var(--theme-primary) 32%,transparent),
        inset 0 0 70px color-mix(in srgb,var(--theme-primary-dark) 55%,black),
        0 0 26px color-mix(in srgb,var(--theme-secondary) 20%,transparent)!important
    }
    body.team-theme-full tbody tr.theme-standard-row td{
      background-color:var(--theme-panel)!important
    }
    body.team-theme-full .total-row td{
      background:color-mix(in srgb,var(--theme-panel) 88%,black)!important
    }
  `;
  Display.placeStyle(160, style);
})();


/* ------------------------------------------------------------------
   theme-transforms.js   (stage/style order 170)
   ------------------------------------------------------------------ */
/* v122 Windows visual-theme transform runtime.
   Theme Studio still owns artwork, colors, corner seating and hero scale. This
   layer only adds the direct-canvas transform values saved by the Windows
   editor: move, resize, rotate and opacity. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform) || typeof render!=="function") return;

  const DEFAULT={x:0,y:0,scale_x:100,scale_y:100,rotation:0,opacity:100};
  let teams={};
  let loaded=false;
  let loading=null;
  let currentData=null;
  let lastSettingsVersion=null;

  const clamp=(v,a,b,d)=>{v=Number(v);return Number.isFinite(v)?Math.min(b,Math.max(a,v)):d;};
  function clean(raw){
    raw=raw&&typeof raw==="object"?raw:{};
    return {
      x:clamp(raw.x,-300,300,0),y:clamp(raw.y,-300,300,0),
      scale_x:clamp(raw.scale_x,20,500,100),scale_y:clamp(raw.scale_y,20,500,100),
      rotation:clamp(raw.rotation,-180,180,0),opacity:clamp(raw.opacity,0,100,100)
    };
  }
  function teamId(data){
    return Number(data?.team_summary?.team_id||0)||null;
  }
  function cfg(team,key){
    return clean(teams?.[String(team)]?.[key]||DEFAULT);
  }
  function transformText(c){
    return `translate(${c.x}%,${c.y}%) scale(${c.scale_x/100},${c.scale_y/100}) rotate(${c.rotation}deg)`;
  }

  function ensureStyles(){
    if(document.getElementById("themeTransformRuntimeV122Styles")) return;
    const style=document.createElement("style");
    style.id="themeTransformRuntimeV122Styles";
    style.textContent=`
      #themedTeamBroadcast .bt-row.te-transform-row{background-image:none!important}
      #themedTeamBroadcast .bt-row.te-transform-row::after{
        content:"";position:absolute;inset:0;z-index:0;pointer-events:none;
        background-image:var(--te-row-image,none);background-position:center;
        background-size:100% 100%;background-repeat:no-repeat;
        transform-origin:center center;transform:var(--te-row-transform,none);
        opacity:var(--te-row-opacity,1);will-change:transform,opacity;
        animation:none!important
      }
      #themedTeamBroadcast .bt-row.te-transform-row::before{z-index:1}
      #themedTeamBroadcast .bt-row.te-transform-row>*{z-index:2}
    `;
    document.head.appendChild(style);
  }

  function applyElement(el,c,key){
    if(!el) return;
    if(el.dataset.teBaseTransform===undefined){
      el.dataset.teBaseTransform=String(el.style.transform||"");
      el.dataset.teBaseOpacity=String(el.style.opacity||"");
    }
    const base=String(el.dataset.teBaseTransform||"").trim();
    el.style.transformOrigin=el.style.transformOrigin||"center center";
    el.style.transform=`${base?base+" ":""}${transformText(c)}`;
    el.style.opacity=String(c.opacity/100);
    el.style.willChange="transform,opacity";
    el.dataset.themeEditKey=key;
  }

  function rowImage(row){
    const inline=String(row.style.backgroundImage||"").trim();
    if(inline&&inline!=="none") return inline;
    const saved=String(row.style.getPropertyValue("--te-row-image")||"").trim();
    return saved||"none";
  }
  function applyRow(row,c,key){
    if(!row) return;
    const image=rowImage(row);
    if(image&&image!=="none") row.style.setProperty("--te-row-image",image);
    row.style.backgroundImage="none";
    row.style.setProperty("--te-row-transform",transformText(c));
    row.style.setProperty("--te-row-opacity",String(c.opacity/100));
    row.classList.add("te-transform-row");
    row.dataset.themeEditKey=key;
  }

  function apply(data){
    ensureStyles();
    const tid=teamId(data);
    const root=document.getElementById("themedTeamBroadcast");
    if(!tid||!root) return;

    applyElement(root.querySelector(".bt-bg"),cfg(tid,"background"),"background");
    const hero=root.querySelector(".bt-hero");
    if(hero) applyElement(hero,cfg(tid,"hero"),"hero");

    const corners={corner_tl:"tl",corner_tr:"tr",corner_bl:"bl",corner_br:"br"};
    Object.entries(corners).forEach(([key,pos])=>{
      applyElement(root.querySelector(`.bt-corner.${pos}`),cfg(tid,key),key);
    });

    root.querySelectorAll(".bt-row").forEach(row=>{
      const key=row.classList.contains("champion")?"champion":"row";
      if(!row.classList.contains("team-lead")) applyRow(row,cfg(tid,key),key);
    });
    root.querySelectorAll(".bt-medal").forEach(el=>applyElement(el,cfg(tid,"medallion"),"medallion"));
    root.querySelectorAll(".bt-tl-mark").forEach(el=>applyElement(el,cfg(tid,"totals_mark"),"totals_mark"));
  }

  async function reload(force=false){
    if(loading&&!force) return loading;
    loading=(async()=>{
      try{
        const r=await fetch("/api/windows/theme-transforms",{cache:"no-store"});
        if(!r.ok) return false;
        const d=await r.json();
        if(d&&d.ok!==false){teams=d.teams||{};loaded=true;return true;}
      }catch(_){ }
      return false;
    })();
    try{return await loading;}finally{loading=null;}
  }

  function setLocal(tid,key,value){
    const id=String(Number(tid)||0);
    if(!id||id==="0") return;
    if(!teams[id]) teams[id]={};
    teams[id][key]=clean(value);
    if(currentData&&teamId(currentData)===Number(tid)) apply(currentData);
  }
  function getLocal(tid,key){return cfg(Number(tid)||0,key);}

  Display.stage(170, function(data, next){
    const result=next(data);
    currentData=data;
    apply(data);
    const version=Number(data?.settings_version||0);
    if(!loaded||version!==lastSettingsVersion){
      lastSettingsVersion=version;
      reload().then(()=>{if(currentData)apply(currentData);});
    }
    requestAnimationFrame(()=>{if(currentData===data)apply(data);});
    return result;
  });

  window.StatsThemeTransforms={get:getLocal,setLocal,apply:()=>currentData&&apply(currentData),reload};
  reload().then(()=>{if(currentData)apply(currentData);});
})();


/* ------------------------------------------------------------------
   theme-editor-preview.js   (stage/style order 180)
   ------------------------------------------------------------------ */
/* v122 visual Theme Builder preview.
   Only runs inside the Windows Theme Builder iframe. It feeds stable fake sales
   data through the real leaderboard renderer, then adds direct mouse editing
   over theme-owned artwork. Real reps and real TV data are never modified. */
(function(){
  const params=new URLSearchParams(location.search);
  if(params.get("themeEditor")!=="1") return;
  const match=/^team-(\d+)$/.exec(String(params.get("preview")||""));
  if(!match) return;

  const teamId=Number(match[1]);
  const sampleSeed=Number(params.get("sample")||1)||1;
  const nativeFetch=window.fetch.bind(window);
  const DEFAULT={x:0,y:0,scale_x:100,scale_y:100,rotation:0,opacity:100};
  const LABELS={
    background:"Background",hero:"Hero / Header Art",row:"Leaderboard Row",
    champion:"Champion Row",medallion:"Champion Medallion",corner_tl:"Top Left Corner",
    corner_tr:"Top Right Corner",corner_bl:"Bottom Left Corner",corner_br:"Bottom Right Corner",
    totals_mark:"Totals Mark"
  };
  let selectedKey="";
  let selectedTarget=null;
  let selection=null;
  let menu=null;
  let drag=null;

  document.documentElement.dataset.themeEditor="1";

  function rng(seed){
    let a=(seed>>>0)||1;
    return function(){
      a|=0;a=a+0x6D2B79F5|0;
      let t=Math.imul(a^a>>>15,1|a);
      t=t+Math.imul(t^t>>>7,61|t)^t;
      return ((t^t>>>14)>>>0)/4294967296;
    };
  }
  function sampleNames(random){
    const first=["Jordan","Alex","Taylor","Casey","Riley","Cameron","Morgan","Avery","Drew","Jamie","Parker","Reese"];
    const last=["Lee","Morgan","Reed","Brooks","Adams","Hayes","Bennett","Cole","Price","Stone","Foster","Grant"];
    const names=[];
    while(names.length<7){
      const name=`${first[Math.floor(random()*first.length)]} ${last[Math.floor(random()*last.length)]}`;
      if(!names.includes(name)) names.push(name);
    }
    return names;
  }
  function makeFake(base){
    const random=rng((teamId*7919)+(sampleSeed*104729));
    const names=sampleNames(random);
    const leaderName=names.pop();
    const teamName=String(base?.team_summary?.team||base?.selected_team||`Team ${teamId}`);
    const makeRow=(name,index)=>{
      const issued=Math.round(32+random()*48);
      const pitched=Math.max(1,Math.round(issued*(0.68+random()*.25)));
      const sold=Math.max(1,Math.round(pitched*(0.24+random()*.36)));
      const gross=Math.round((sold*(4100+random()*3700))*100)/100;
      const pending=Math.round(gross*(.04+random()*.18)*100)/100;
      const net=Math.round((gross-pending*(.45+random()*.35))*100)/100;
      return {
        rep_key:`theme-preview-${sampleSeed}-${index}`,
        rep_name:name,team:teamName,team_id:teamId,assigned_team_id:teamId,
        issued_leads:issued,pitched_leads:pitched,pitched_rate:pitched/issued*100,
        sold_leads:sold,close_rate:sold/issued*100,gross_split:gross,pending_split:pending,
        net_split:net,dpl:net/issued,sales_retention:gross?net/gross*100:0,
        avg_gross_sale:sold?gross/sold:0,avg_net_sale:sold?net/sold:0
      };
    };
    const rows=names.map(makeRow);
    const leader=makeRow(leaderName,99);
    rows.push(leader);
    rows.sort((a,b)=>b.net_split-a.net_split);
    const sum=key=>rows.reduce((total,row)=>total+Number(row[key]||0),0);
    const issued=sum("issued_leads"),pitched=sum("pitched_leads"),sold=sum("sold_leads");
    const gross=sum("gross_split"),pending=sum("pending_split"),net=sum("net_split");
    const originalSummary=base?.team_summary||{};
    const summary={
      ...originalSummary,team:teamName,team_id:teamId,rep_count:rows.length,
      logo_url:originalSummary.logo_url||null,
      leads:[{lead_name:leaderName,lead_role:"Sales Manager"}],
      issued_leads:issued,pitched_leads:pitched,sold_leads:sold,
      pitched_rate:issued?pitched/issued*100:0,close_rate:issued?sold/issued*100:0,
      gross_split:gross,pending_split:pending,net_split:net,dpl:issued?net/issued:0,
      sales_retention:gross?net/gross*100:0,avg_gross_sale:sold?gross/sold:0,
      avg_net_sale:sold?net/sold:0
    };
    const metrics=["rank","rep_name","issued_leads","pitched_leads","sold_leads","close_rate","net_split"];
    return {
      ...base,mode:"per_team",mode_label:"Per Team",selected_team:teamName,
      rows,team_summary:summary,teams:[],metrics,sort_metric:"net_split",rank_direction:"desc",
      metric_types:{...(base?.metric_types||{}),rank:"system",rep_name:"text",issued_leads:"number",
        pitched_leads:"number",sold_leads:"number",close_rate:"percent",net_split:"currency"},
      metric_labels:{...(base?.metric_labels||{}),rank:"Rank",rep_name:"Sales Rep",issued_leads:"Issued",
        pitched_leads:"Pitched",sold_leads:"Sold",close_rate:"Close Rate",net_split:"Net Split"},
      theme_editor_sample:true
    };
  }

  window.fetch=async function(input,init){
    const url=typeof input==="string"?input:input?.url||"";
    if(url.startsWith("/api/leaderboard")){
      const response=await nativeFetch(input,init);
      if(!response.ok) return response;
      try{
        const base=await response.clone().json();
        const fake=makeFake(base);
        return new Response(JSON.stringify(fake),{
          status:response.status,statusText:response.statusText,
          headers:{"Content-Type":"application/json","Cache-Control":"no-store"}
        });
      }catch(_){return response;}
    }
    return nativeFetch(input,init);
  };

  function injectStyles(){
    if(document.getElementById("themeEditorPreviewV122Styles")) return;
    const style=document.createElement("style");
    style.id="themeEditorPreviewV122Styles";
    style.textContent=`
      html[data-theme-editor="1"],html[data-theme-editor="1"] body{user-select:none}
      html[data-theme-editor="1"] [data-theme-edit-key]{pointer-events:auto!important}
      .te-placeholder{position:absolute;z-index:45;display:grid;place-items:center;
        border:2px dashed rgba(80,190,255,.78);background:rgba(15,35,50,.38);color:#bfeaff;
        font:700 13px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;
        text-align:center;pointer-events:auto!important;box-sizing:border-box}
      .te-placeholder.te-hero{left:50%;top:8px;transform:translateX(-50%);width:min(52vw,760px);height:150px}
      .te-placeholder.te-corner{width:92px;height:92px;font-size:10px}
      .te-placeholder.te-corner.tl{left:7px;top:7px}.te-placeholder.te-corner.tr{right:7px;top:7px}
      .te-placeholder.te-corner.bl{left:7px;bottom:7px}.te-placeholder.te-corner.br{right:7px;bottom:7px}
      .te-placeholder.te-medal,.te-placeholder.te-totalmark{position:relative;inset:auto;width:58px;height:46px;
        margin:auto;font-size:8px;border-width:1px;background:rgba(15,35,50,.28)}
      #teSelection{position:fixed;z-index:2147483639;box-sizing:border-box;border:1px solid #43bfff;
        box-shadow:0 0 0 1px rgba(0,0,0,.6);pointer-events:auto;cursor:move;display:none}
      #teSelection::before{content:attr(data-label);position:absolute;left:0;bottom:calc(100% + 8px);
        padding:4px 7px;background:#07131c;color:#bfeaff;border:1px solid #43bfff;border-radius:4px;
        font:700 11px Arial,sans-serif;white-space:nowrap;pointer-events:none}
      .te-handle{position:absolute;width:12px;height:12px;background:#07131c;border:2px solid #43bfff;
        box-sizing:border-box;border-radius:2px;z-index:2}
      .te-handle.nw{left:-7px;top:-7px;cursor:nwse-resize}.te-handle.ne{right:-7px;top:-7px;cursor:nesw-resize}
      .te-handle.sw{left:-7px;bottom:-7px;cursor:nesw-resize}.te-handle.se{right:-7px;bottom:-7px;cursor:nwse-resize}
      .te-handle.n{left:50%;top:-7px;margin-left:-6px;cursor:ns-resize}.te-handle.s{left:50%;bottom:-7px;margin-left:-6px;cursor:ns-resize}
      .te-handle.w{left:-7px;top:50%;margin-top:-6px;cursor:ew-resize}.te-handle.e{right:-7px;top:50%;margin-top:-6px;cursor:ew-resize}
      .te-rotate-line{position:absolute;left:50%;bottom:100%;width:1px;height:28px;background:#43bfff;pointer-events:none}
      .te-rotate{position:absolute;left:50%;bottom:calc(100% + 23px);width:15px;height:15px;margin-left:-7px;
        border:2px solid #43bfff;border-radius:50%;background:#07131c;cursor:crosshair;z-index:3}
      #teContext{position:fixed;z-index:2147483640;min-width:215px;padding:7px;background:#111b23;color:#fff;
        border:1px solid #3a596d;border-radius:8px;box-shadow:0 14px 38px rgba(0,0,0,.5);font:13px Arial,sans-serif;display:none}
      #teContext button{width:100%;min-height:38px;padding:8px 10px;border:0;border-radius:5px;background:transparent;
        color:#fff;text-align:left;font:600 13px Arial,sans-serif;cursor:pointer}
      #teContext button:hover{background:#203546}
      #teContext .te-danger{color:#ffb4b4}
      #teContext .te-opacity{padding:8px 10px;border-top:1px solid #2e4657;border-bottom:1px solid #2e4657;margin:4px 0}
      #teContext .te-opacity-row{display:flex;justify-content:space-between;gap:10px;margin-bottom:5px;color:#c9d7e1}
      #teContext input[type=range]{width:100%;accent-color:#43bfff}
      #teEditorTip{position:fixed;left:16px;bottom:14px;z-index:2147483638;padding:7px 10px;border-radius:6px;
        background:rgba(6,14,20,.78);border:1px solid rgba(67,191,255,.35);color:#b9cad5;
        font:12px Arial,sans-serif;pointer-events:none}
    `;
    document.head.appendChild(style);
  }

  function post(action,key=selectedKey){
    try{
      if(window.parent!==window&&window.parent.StatsThemeEditorHost?.action){
        window.parent.StatsThemeEditorHost.action(action,key,teamId);
        return;
      }
    }catch(_){ }
    try{window.parent.postMessage({type:"stats-theme-editor",action,key,teamId},location.origin);}catch(_){ }
  }
  function currentCfg(key=selectedKey){
    return window.StatsThemeTransforms?.get?.(teamId,key)||{...DEFAULT};
  }
  function setLocal(key,value){
    window.StatsThemeTransforms?.setLocal?.(teamId,key,value);
    const target=(selectedKey===key&&selectedTarget)?selectedTarget:null;
    if(target?.classList.contains("te-placeholder")){
      const base=target.dataset.tePlaceholderBase||"";
      target.style.opacity=String(value.opacity/100);
      target.style.transform=`${base?base+" ":""}translate(${value.x}%,${value.y}%) scale(${value.scale_x/100},${value.scale_y/100}) rotate(${value.rotation}deg)`;
    }
  }
  async function persist(key,value){
    try{
      await nativeFetch(`/api/windows/theme-transforms/${teamId}`,{
        method:"PUT",headers:{"Content-Type":"application/json"},cache:"no-store",
        body:JSON.stringify({asset:key,transform:value})
      });
    }catch(_){ }
  }
  async function resetTransform(key){
    try{await nativeFetch(`/api/windows/theme-transforms/${teamId}/${encodeURIComponent(key)}`,{method:"DELETE",cache:"no-store"});}catch(_){ }
    setLocal(key,{...DEFAULT});
    if(selectedKey===key) updateSelection();
  }

  function ensureSelection(){
    if(selection) return selection;
    selection=document.createElement("div");
    selection.id="teSelection";
    selection.innerHTML=`
      <span class="te-handle nw" data-handle="nw"></span><span class="te-handle n" data-handle="n"></span>
      <span class="te-handle ne" data-handle="ne"></span><span class="te-handle e" data-handle="e"></span>
      <span class="te-handle se" data-handle="se"></span><span class="te-handle s" data-handle="s"></span>
      <span class="te-handle sw" data-handle="sw"></span><span class="te-handle w" data-handle="w"></span>
      <span class="te-rotate-line"></span><span class="te-rotate" data-handle="rotate" title="Rotate"></span>`;
    document.body.appendChild(selection);
    selection.addEventListener("pointerdown",startDrag);
    selection.addEventListener("contextmenu",e=>{e.preventDefault();showMenu(e.clientX,e.clientY,selectedKey,selectedTarget);});
    return selection;
  }
  function ensureMenu(){
    if(menu) return menu;
    menu=document.createElement("div");menu.id="teContext";
    menu.innerHTML=`
      <button type="button" data-action="upload">Upload New Asset…</button>
      <button type="button" data-action="color">Change Color…</button>
      <div class="te-opacity"><div class="te-opacity-row"><span>Opacity</span><strong id="teOpacityValue">100%</strong></div>
        <input id="teOpacity" type="range" min="0" max="100" step="1" value="100"></div>
      <button type="button" data-action="reset-transform">Reset Position / Size</button>
      <button type="button" class="te-danger" data-action="remove">Remove Asset</button>`;
    document.body.appendChild(menu);
    menu.addEventListener("click",e=>{
      const button=e.target.closest("button[data-action]");if(!button)return;
      const action=button.dataset.action;
      if(action==="upload")post("upload");
      if(action==="color")post("color");
      if(action==="remove")post("remove");
      if(action==="reset-transform")resetTransform(selectedKey);
      hideMenu();
    });
    const opacity=menu.querySelector("#teOpacity");
    opacity.addEventListener("input",()=>{
      if(!selectedKey)return;
      const value={...currentCfg(),opacity:Number(opacity.value)};
      menu.querySelector("#teOpacityValue").textContent=`${Math.round(value.opacity)}%`;
      setLocal(selectedKey,value);updateSelection();
    });
    opacity.addEventListener("change",()=>{if(selectedKey)persist(selectedKey,currentCfg());});
    return menu;
  }
  function hideMenu(){if(menu)menu.style.display="none";}
  function showMenu(x,y,key,target){
    if(!key)return;
    select(key,target);
    const m=ensureMenu(),c=currentCfg(key);
    m.querySelector("#teOpacity").value=String(Math.round(c.opacity));
    m.querySelector("#teOpacityValue").textContent=`${Math.round(c.opacity)}%`;
    m.style.display="block";
    const w=m.offsetWidth,h=m.offsetHeight;
    m.style.left=`${Math.max(8,Math.min(innerWidth-w-8,x))}px`;
    m.style.top=`${Math.max(8,Math.min(innerHeight-h-8,y))}px`;
  }

  function findTarget(key){
    const all=[...document.querySelectorAll(`[data-theme-edit-key="${CSS.escape(key)}"]`)];
    if(!all.length)return null;
    if(key==="row")return all.find(el=>el.classList.contains("bt-row")&&!el.classList.contains("champion"))||all[0];
    return all[0];
  }
  function select(key,target){
    selectedKey=key||"";
    selectedTarget=target||findTarget(selectedKey);
    const box=ensureSelection();
    if(!selectedKey||!selectedTarget){box.style.display="none";return;}
    box.dataset.label=LABELS[selectedKey]||selectedKey;
    box.style.display="block";
    updateSelection();
    post("selected");
  }
  function updateSelection(){
    if(!selection||!selectedTarget||!selectedTarget.isConnected){
      if(selectedKey){selectedTarget=findTarget(selectedKey);}
      if(!selectedTarget){if(selection)selection.style.display="none";return;}
    }
    const rect=selectedTarget.getBoundingClientRect();
    if(rect.width<2||rect.height<2){selection.style.display="none";return;}
    selection.style.display="block";
    selection.style.left=`${rect.left}px`;selection.style.top=`${rect.top}px`;
    selection.style.width=`${rect.width}px`;selection.style.height=`${rect.height}px`;
  }

  function startDrag(e){
    if(!selectedKey||!selectedTarget)return;
    e.preventDefault();hideMenu();
    const handle=e.target.dataset.handle||"move";
    const rect=selectedTarget.getBoundingClientRect();
    const cfg={...currentCfg()};
    drag={pointerId:e.pointerId,handle,startX:e.clientX,startY:e.clientY,rect,cfg,
      centerX:rect.left+rect.width/2,centerY:rect.top+rect.height/2};
    try{selection.setPointerCapture(e.pointerId);}catch(_){ }
  }
  function moveDrag(e){
    if(!drag||e.pointerId!==drag.pointerId)return;
    e.preventDefault();
    const dx=e.clientX-drag.startX,dy=e.clientY-drag.startY;
    const c={...drag.cfg};
    const w=Math.max(24,drag.rect.width),h=Math.max(24,drag.rect.height);
    if(drag.handle==="move"){
      c.x=drag.cfg.x+dx/w*100;c.y=drag.cfg.y+dy/h*100;
    }else if(drag.handle==="rotate"){
      const a0=Math.atan2(drag.startY-drag.centerY,drag.startX-drag.centerX);
      const a1=Math.atan2(e.clientY-drag.centerY,e.clientX-drag.centerX);
      c.rotation=drag.cfg.rotation+(a1-a0)*180/Math.PI;
      while(c.rotation>180)c.rotation-=360;while(c.rotation<-180)c.rotation+=360;
    }else{
      const hasE=drag.handle.includes("e"),hasW=drag.handle.includes("w");
      const hasS=drag.handle.includes("s"),hasN=drag.handle.includes("n");
      if(hasE||hasW){
        const sign=hasE?1:-1;
        const factor=Math.max(.2,1+(dx*sign)/w);
        c.scale_x=Math.max(20,Math.min(500,drag.cfg.scale_x*factor));
        c.x=drag.cfg.x+dx/(2*w)*100;
      }
      if(hasS||hasN){
        const sign=hasS?1:-1;
        const factor=Math.max(.2,1+(dy*sign)/h);
        c.scale_y=Math.max(20,Math.min(500,drag.cfg.scale_y*factor));
        c.y=drag.cfg.y+dy/(2*h)*100;
      }
      if(e.shiftKey&&(hasE||hasW)&&(hasS||hasN)){
        const scale=Math.max(c.scale_x,c.scale_y);
        c.scale_x=scale;c.scale_y=scale;
      }
    }
    c.x=Math.max(-300,Math.min(300,c.x));c.y=Math.max(-300,Math.min(300,c.y));
    c.rotation=Math.max(-180,Math.min(180,c.rotation));
    setLocal(selectedKey,c);
    requestAnimationFrame(updateSelection);
  }
  function endDrag(e){
    if(!drag||e.pointerId!==drag.pointerId)return;
    const key=selectedKey,value={...currentCfg()};
    drag=null;
    try{selection.releasePointerCapture(e.pointerId);}catch(_){ }
    persist(key,value);updateSelection();
  }

  function editableFromEvent(e){
    const direct=e.target.closest?.("[data-theme-edit-key]");
    if(direct)return direct;
    const root=document.getElementById("themedTeamBroadcast");
    if(root&&root.contains(e.target))return root.querySelector(".bt-bg");
    return null;
  }
  function bindEvents(){
    document.addEventListener("dblclick",e=>{
      const target=editableFromEvent(e);if(!target)return;
      e.preventDefault();e.stopPropagation();select(target.dataset.themeEditKey||"background",target);
    },true);
    document.addEventListener("contextmenu",e=>{
      const target=editableFromEvent(e);if(!target)return;
      e.preventDefault();e.stopPropagation();showMenu(e.clientX,e.clientY,target.dataset.themeEditKey||"background",target);
    },true);
    document.addEventListener("pointerdown",e=>{
      if(menu&&menu.style.display==="block"&&!menu.contains(e.target))hideMenu();
      if(selection&&selection.style.display==="block"&&!selection.contains(e.target)&&!e.target.closest?.("[data-theme-edit-key]")){
        selectedKey="";selectedTarget=null;selection.style.display="none";
      }
    },true);
    document.addEventListener("pointermove",moveDrag,true);
    document.addEventListener("pointerup",endDrag,true);
    document.addEventListener("pointercancel",endDrag,true);
    document.addEventListener("keydown",e=>{
      if(e.key==="Escape"){hideMenu();selectedKey="";selectedTarget=null;if(selection)selection.style.display="none";}
    });
    window.addEventListener("resize",()=>requestAnimationFrame(updateSelection));
  }

  function placeholder(parent,key,className,text){
    if(parent.querySelector(`.te-placeholder[data-theme-edit-key="${key}"]`))return;
    const el=document.createElement("div");el.className=`te-placeholder ${className}`;
    el.dataset.themeEditKey=key;el.textContent=text||LABELS[key]||key;
    if(className.includes("te-hero"))el.dataset.tePlaceholderBase="translateX(-50%)";
    parent.appendChild(el);
    setLocal(key,currentCfg(key));
  }
  function decorate(){
    injectStyles();
    const root=document.getElementById("themedTeamBroadcast");if(!root)return;
    const bg=root.querySelector(".bt-bg");if(bg)bg.dataset.themeEditKey="background";
    const hero=root.querySelector(".bt-hero");
    if(hero)hero.dataset.themeEditKey="hero";else placeholder(root.querySelector(".bt-header")||root,"hero","te-hero","Hero / Logo");

    const corners={corner_tl:"tl",corner_tr:"tr",corner_bl:"bl",corner_br:"br"};
    Object.entries(corners).forEach(([key,pos])=>{
      const el=root.querySelector(`.bt-corner.${pos}`);
      if(el)el.dataset.themeEditKey=key;else placeholder(root,key,`te-corner ${pos}`,LABELS[key]);
    });

    root.querySelectorAll(".bt-row").forEach(row=>{
      if(row.classList.contains("team-lead"))return;
      row.dataset.themeEditKey=row.classList.contains("champion")?"champion":"row";
    });
    const champion=root.querySelector(".bt-row.champion");
    if(champion){
      const medal=champion.querySelector(".bt-medal");
      if(medal)medal.dataset.themeEditKey="medallion";
      else placeholder(champion.querySelector(".bt-rank")||champion,"medallion","te-medal","Medal");
    }
    const lead=root.querySelector(".bt-row.team-lead");
    if(lead){
      const mark=lead.querySelector(".bt-tl-mark");
      if(mark)mark.dataset.themeEditKey="totals_mark";
      else placeholder(lead.querySelector(".bt-rank")||lead,"totals_mark","te-totalmark","Totals Mark");
    }

    if(!document.getElementById("teEditorTip")){
      const tip=document.createElement("div");tip.id="teEditorTip";
      tip.textContent="Double-click artwork to resize / rotate • Right-click to change it";
      document.body.appendChild(tip);
    }
    if(selectedKey){selectedTarget=findTarget(selectedKey);requestAnimationFrame(updateSelection);}
    post("ready","");
  }

  injectStyles();bindEvents();ensureSelection();ensureMenu();
  Display.stage(180, function(data, next){
    const result=next(data);
    decorate();requestAnimationFrame(decorate);setTimeout(decorate,80);
    return result;
  });
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>setTimeout(decorate,0),{once:true});
  else setTimeout(decorate,0);
})();


/* ------------------------------------------------------------------
   theme-editor-data-policy.js   (stage/style order 190)
   ------------------------------------------------------------------ */
/* v126 Theme Builder preview data policy.

   The visual editor still uses the real leaderboard renderer. This layer fixes
   two product rules:
   - a team with real, locally assigned reps always previews its real names and
     real stats; fake sample rows are never allowed to replace populated data;
   - an empty team gets a clearly marked mock preview so Theme Builder still has
     rows and artwork targets to design against.

   Theme Builder previews are also intentionally static while the editor is
   open. The normal TV refresh loop is stopped after one corrected load; Theme
   Studio explicitly reloads the iframe when a theme change needs a refresh.
   This removes the repeated full-board rerender loop that could make Chromium
   report the Settings page as unresponsive on Windows laptops. */
(function(){
  const params=new URLSearchParams(location.search);
  if(params.get("themeEditor")!=="1") return;

  const previousFetch=window.fetch.bind(window);
  let mockMode=false;

  function urlOf(input){
    try{return new URL(typeof input==="string"?input:(input?.url||""),location.href);}
    catch(_){return null;}
  }

  function assignedRows(data){
    return (Array.isArray(data?.rows)?data.rows:[]).filter(row=>Number(row?.assigned_team_id||0)>0);
  }

  function responseFrom(data,status=200,statusText="OK"){
    return new Response(JSON.stringify(data),{
      status,statusText,
      headers:{"Content-Type":"application/json","Cache-Control":"no-store"}
    });
  }

  /* Use XHR for the real-data probe so it bypasses the older visual-editor
     fetch wrapper, which deliberately manufactures sample rows. */
  function readRealLeaderboard(url){
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open("GET",`${url.pathname}${url.search}`,true);
      xhr.setRequestHeader("Cache-Control","no-store");
      xhr.onload=()=>{
        try{
          if(xhr.status<200||xhr.status>=300)throw new Error("leaderboard probe failed");
          resolve({data:JSON.parse(xhr.responseText||"{}"),status:xhr.status,statusText:xhr.statusText||"OK"});
        }catch(error){reject(error);}
      };
      xhr.onerror=()=>reject(new Error("leaderboard probe failed"));
      xhr.send();
    });
  }

  function setMockMode(on){
    mockMode=!!on;
    if(mockMode)document.documentElement.dataset.themeEditorMock="1";
    else delete document.documentElement.dataset.themeEditorMock;
  }

  window.fetch=async function(input,init){
    const url=urlOf(input);
    if(url&&url.origin===location.origin&&url.pathname==="/api/leaderboard"){
      try{
        const real=await readRealLeaderboard(url);
        if(assignedRows(real.data).length){
          setMockMode(false);
          return responseFrom(real.data,real.status,real.statusText);
        }
        // No locally assigned reps: let the existing v122 editor create its
        // stable fake rows so the canvas remains useful for a brand-new team.
        setMockMode(true);
        return previousFetch(input,init);
      }catch(_){
        return previousFetch(input,init);
      }
    }
    return previousFetch(input,init);
  };

  function injectStyles(){
    if(document.getElementById("themeEditorDataPolicyV126Styles"))return;
    const style=document.createElement("style");
    style.id="themeEditorDataPolicyV126Styles";
    style.textContent=`
      html[data-theme-editor="1"] *,html[data-theme-editor="1"] *::before,html[data-theme-editor="1"] *::after{
        animation-duration:0s!important;animation-delay:0s!important
      }
      html[data-theme-editor-mock="1"] #themedTeamBroadcast .bt-bg.te-mock-bg{
        background-image:
          radial-gradient(circle at 18% 18%,rgba(216,179,74,.20),transparent 34%),
          radial-gradient(circle at 82% 12%,rgba(216,179,74,.12),transparent 30%),
          linear-gradient(145deg,#070707 0%,#131313 54%,#080808 100%)!important
      }
      html[data-theme-editor-mock="1"] .te-placeholder{
        background:
          linear-gradient(135deg,rgba(216,179,74,.16),rgba(18,35,46,.58))!important;
        border-color:rgba(216,179,74,.78)!important;color:#f5df9a!important
      }
      #teMockBadgeV126{position:fixed;left:16px;top:14px;z-index:2147483638;
        padding:7px 10px;border:1px solid rgba(216,179,74,.58);border-radius:6px;
        background:rgba(12,10,5,.88);color:#f4dda0;font:700 11px Arial,sans-serif;
        letter-spacing:.04em;pointer-events:none}
    `;
    document.head.appendChild(style);
  }

  function decorateMockPreview(){
    injectStyles();
    const root=document.getElementById("themedTeamBroadcast");
    let badge=document.getElementById("teMockBadgeV126");
    if(!mockMode){
      if(badge)badge.remove();
      root?.querySelector(".bt-bg")?.classList.remove("te-mock-bg");
      return;
    }

    if(root){
      const bg=root.querySelector(".bt-bg");
      if(bg){
        const image=getComputedStyle(bg).backgroundImage;
        bg.classList.toggle("te-mock-bg",!image||image==="none");
      }
    }
    if(!badge){
      badge=document.createElement("div");badge.id="teMockBadgeV126";
      badge.textContent="MOCK PREVIEW · no assigned reps yet";
      document.body.appendChild(badge);
    }
  }

  if(typeof render==="function"){
    Display.stage(190, function(data, next){
      const result=next(data);
      requestAnimationFrame(decorateMockPreview);
      return result;
    });
  }

  /* The base display script has already scheduled one refresh timer by the time
     this file loads. Replace getRefresh so that timer performs one last load and
     then stops instead of scheduling forever inside the editor iframe. */
  if(typeof getRefresh==="function"&&typeof load==="function"){
    getRefresh=async function(){
      try{await load();}catch(_){ }
    };
    setTimeout(()=>{try{load();}catch(_){ }},0);
  }

  injectStyles();
})();


/* ------------------------------------------------------------------
   theme-editor-force-theme.js   (stage/style order 200)
   ------------------------------------------------------------------ */
/* v122 editor-only render guard.
   A team may have its theme disabled on the live TV while it is being built.
   Theme Builder still needs the complete themed canvas, so preview mode clones
   the theme state and turns on only the selected team's effective theme. */
(function(){
  const params=new URLSearchParams(location.search);
  if(params.get("themeEditor")!=="1" || typeof render!=="function") return;
  const match=/^team-(\d+)$/.exec(String(params.get("preview")||""));
  if(!match) return;
  const teamId=Number(match[1]);

  function editorData(data){
    if(!data||data.mode!=="per_team")return data;
    const state=data.theme_state||{};
    const teams={...(state.teams||{})};
    const original=teams[String(teamId)];
    if(!original)return data;
    const theme={...original,enabled:true};
    teams[String(teamId)]=theme;
    const byName={...(state.by_name||{})};
    const teamName=String(data.team_summary?.team||data.selected_team||theme.team_name||"").trim().toLowerCase();
    if(teamName)byName[teamName]=theme;
    return {...data,theme_state:{...state,teams,by_name:byName}};
  }

  Display.stage(200, function(data, next){return next(editorData(data));});
})();


/* ------------------------------------------------------------------
   theme-editor-controls.js   (stage/style order 210)
   ------------------------------------------------------------------ */
/* v127 Theme Builder discoverability hotfix.
   The previous observer rewrote menu text on every DOM mutation. Setting
   textContent itself creates a child mutation, so Chromium could get trapped
   in a self-triggering observer loop and mark the entire Settings page
   unresponsive. All decoration below is idempotent and observer work is
   coalesced to one animation frame. */
(function(){
  const params=new URLSearchParams(location.search);
  if(params.get("themeEditor")!=="1") return;

  const LABELS={
    background:"Background",hero:"Hero / Header Art",row:"Leaderboard Row",
    champion:"Champion Row",medallion:"Champion Medallion",corner_tl:"Top Left Corner",
    corner_tr:"Top Right Corner",corner_bl:"Bottom Left Corner",corner_br:"Bottom Right Corner",
    totals_mark:"Totals Mark"
  };
  const COACH_KEY="stats.themeEditor.coach.v123.dismissed";
  let decorateQueued=false;

  function injectStyles(){
    if(document.getElementById("themeEditorIntuitiveV123Styles"))return;
    const style=document.createElement("style");
    style.id="themeEditorIntuitiveV123Styles";
    style.textContent=`
      html[data-theme-editor="1"] [data-theme-edit-key]:not(.bt-bg):hover{
        outline:1px dashed rgba(102,205,255,.9);outline-offset:-2px;cursor:pointer
      }
      html[data-theme-editor="1"] .bt-bg[data-theme-edit-key]{cursor:pointer}
      html[data-theme-editor="1"] .te-placeholder{
        transition:border-color .12s ease,background .12s ease,box-shadow .12s ease
      }
      html[data-theme-editor="1"] .te-placeholder:hover{
        border-color:#8bd8ff;background:rgba(25,57,76,.55);box-shadow:0 0 0 2px rgba(67,191,255,.12)
      }
      html[data-theme-editor="1"] .te-placeholder .te-empty-label{display:block;font-size:10px;line-height:1.15}
      html[data-theme-editor="1"] .te-placeholder .te-empty-action{
        display:block;margin-top:4px;font-size:9px;line-height:1.1;color:#fff;letter-spacing:.02em;text-transform:none
      }
      #teSelection::before{font-size:12px!important;font-weight:800!important}
      #teSelection .te-rotate{width:20px!important;height:20px!important;margin-left:-10px!important;
        bottom:calc(100% + 21px)!important;border-radius:50%!important;background:#10222e!important;
        display:grid!important;place-items:center!important;cursor:grab!important}
      #teSelection .te-rotate:active{cursor:grabbing!important}
      #teSelection .te-rotate::after{content:"↻";color:#d9f3ff;font:700 13px/1 Arial,sans-serif;pointer-events:none}
      #teSelection .te-rotate-line{height:27px!important}
      #teCoachV123{position:fixed;inset:0;z-index:2147483646;display:grid;place-items:center;
        padding:24px;background:rgba(0,0,0,.46);font-family:Arial,sans-serif}
      #teCoachV123 .te-coach-card{width:min(430px,calc(100vw - 40px));padding:20px 22px;border-radius:12px;
        background:#101820;color:#fff;border:1px solid #416a80;box-shadow:0 22px 70px rgba(0,0,0,.55)}
      #teCoachV123 h2{margin:0 0 8px;font-size:20px}
      #teCoachV123 p{margin:0;color:#c7d5de;font-size:14px;line-height:1.5}
      #teCoachV123 .te-coach-main{margin-top:13px;padding:12px;border-radius:8px;background:#172630;
        color:#e9f7ff;font-weight:700;line-height:1.55}
      #teCoachV123 button{margin-top:16px;min-width:96px;min-height:40px;border:1px solid #62c9ff;
        border-radius:7px;background:#16384b;color:#fff;font-weight:800;cursor:pointer}
    `;
    document.head.appendChild(style);
  }

  function setTextIfChanged(el,text){
    if(el&&el.textContent!==text)el.textContent=text;
  }

  function simplifyMenu(){
    const menu=document.getElementById("teContext");if(!menu)return;
    const names={upload:"Replace Image…",color:"Color…","reset-transform":"Reset",remove:"Remove"};
    Object.entries(names).forEach(([action,label])=>{
      setTextIfChanged(menu.querySelector(`button[data-action="${action}"]`),label);
    });
    setTextIfChanged(menu.querySelector(".te-opacity-row span"),"Opacity");
  }

  function decorateEditable(){
    document.querySelectorAll("[data-theme-edit-key]").forEach(el=>{
      const key=String(el.dataset.themeEditKey||"");
      const label=LABELS[key]||key;
      const title=label?`Double-click to edit ${label}`:"";
      if(title&&!el.title)el.title=title;
    });

    document.querySelectorAll(".te-placeholder[data-theme-edit-key]").forEach(el=>{
      const key=String(el.dataset.themeEditKey||"");
      const label=LABELS[key]||key;
      if(el.dataset.v123Empty!=="1"){
        el.dataset.v123Empty="1";
        el.innerHTML=`<span class="te-empty-label">${label}</span><span class="te-empty-action">Double-click to add</span>`;
      }
      const title=`Double-click to add ${label}`;
      if(el.title!==title)el.title=title;
    });
    simplifyMenu();
  }

  function scheduleDecorate(){
    if(decorateQueued)return;
    decorateQueued=true;
    requestAnimationFrame(()=>{
      decorateQueued=false;
      decorateEditable();
    });
  }

  function showCoach(force=false){
    if(document.getElementById("teCoachV123"))return;
    if(!force){
      try{if(localStorage.getItem(COACH_KEY)==="1")return;}catch(_){ }
    }
    const overlay=document.createElement("div");overlay.id="teCoachV123";
    overlay.innerHTML=`<div class="te-coach-card" role="dialog" aria-modal="true" aria-label="Theme Builder mouse controls">
      <h2>Edit the preview directly</h2>
      <p>Move your mouse over artwork to see what can be edited.</p>
      <div class="te-coach-main">Double-click artwork to edit<br>Right-click artwork for options<br>Drag the box to move • handles resize • ↻ rotates</div>
      <button type="button">Got it</button>
    </div>`;
    document.body.appendChild(overlay);
    const dismiss=()=>{
      try{localStorage.setItem(COACH_KEY,"1");}catch(_){ }
      overlay.remove();
    };
    overlay.querySelector("button").addEventListener("click",dismiss);
    overlay.addEventListener("pointerdown",e=>{if(e.target===overlay)dismiss();});
  }

  window.addEventListener("message",event=>{
    if(event.origin!==location.origin||event.data?.type!=="stats-theme-editor-help")return;
    showCoach(true);
  });

  function boot(){
    injectStyles();
    decorateEditable();
    const observer=new MutationObserver(scheduleDecorate);
    observer.observe(document.documentElement,{
      childList:true,subtree:true,attributes:true,attributeFilter:["data-theme-edit-key"]
    });
    setTimeout(()=>showCoach(false),450);
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
