/* v69 theme extras.
   Applies the two new theme-owned presentation settings after the existing
   render stack: alternating row tint and per-team hero scale. Defaults are
   deliberately no-op (stripe strength 0, hero 100%). */
(function(){
  if(typeof render!=="function")return;
  const previousRender=render;
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

  render=function(data){
    const result=previousRender(data);
    apply(data);
    requestAnimationFrame(()=>apply(data));
    setTimeout(()=>apply(data),80);
    return result;
  };
})();
