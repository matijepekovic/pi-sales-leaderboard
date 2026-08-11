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
      body.team-theme-full header.theme-office-logo-active>div:first-child{
        display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:auto auto;
        column-gap:16px;align-items:center;min-width:0;
      }
      body.team-theme-full header.theme-office-logo-active #title{
        grid-column:2;grid-row:1;align-self:end;
      }
      body.team-theme-full header.theme-office-logo-active .subtitle{
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
    document.head.appendChild(style);
  }

  const baseRender=render;

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
    if(data.mode==="whole_office") injectOfficeLogo(data,theme);

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
      applyFullTheme(data,winningTheme);
    }else{
      applyComparisonThemes(data);
    }
    if(typeof fitLeaderboard==="function") setTimeout(fitLeaderboard,0);
  }

  render=function(data){
    baseRender(data);
    applyTheme(data);
  };
})();
