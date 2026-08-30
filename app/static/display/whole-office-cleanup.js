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
