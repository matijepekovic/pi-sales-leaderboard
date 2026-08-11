/* v46 per-team display rule.
   Presentation only: the saved Team Builder leader is not part of the numbered
   competition. The existing backend still supplies/sorts/calculates everything.
   This layer only moves that already-rendered rep row to the bottom and marks it TL. */
(function(){
  if(typeof render!=="function") return;
  const previousRender=render;

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
        }
      });
    }
  }

  render=function(data){
    const result=previousRender(data);
    applyTeamLeadPresentation(data);
    return result;
  };
})();
