/* v126 Team Builder member availability.

   Tableau remains the source of candidate rep names, while Stats owns local
   team assignments. A rep can belong to only one local team at a time:
   - creating a team shows only unassigned Tableau reps;
   - editing a team shows its existing members plus unassigned reps;
   - reps assigned to any other team are hidden completely.

   Successful Tableau preview rows are merged with the persisted assignment
   metadata from /api/config before they reach the picker, so a fresh preview
   cannot accidentally make already-assigned people available again. */
(function(){
  if(typeof request!=="function" ||
     typeof renderBuilderMembers!=="function" ||
     typeof openTeamBuilder!=="function" ||
     typeof setBuilderStep!=="function") return;

  const memberList=document.getElementById("builderMembers");
  const overlay=document.getElementById("teamBuilderOverlay");
  if(!memberList||!overlay) return;

  const originalRequest=request;
  const originalRenderBuilderMembers=renderBuilderMembers;
  const originalOpenTeamBuilder=openTeamBuilder;
  const originalSetBuilderStep=setBuilderStep;

  let previewPool=null;
  let persistedPool=[];
  let refreshSequence=0;

  function repKeyFromName(name){
    return String(name||"")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g,"-")
      .replace(/^-+|-+$/g,"") || "unknown";
  }

  function normalizeRows(rows){
    const seen=new Set();
    return (Array.isArray(rows)?rows:[])
      .map(row=>{
        row=row&&typeof row==="object"?row:{};
        const rep_name=String(row.rep_name||row.name||"").trim();
        const rep_key=String(row.rep_key||repKeyFromName(rep_name)).trim();
        if(!rep_name||!rep_key||seen.has(rep_key)) return null;
        seen.add(rep_key);
        const tableau_team=String(row.tableau_team||row.team||"Unassigned").trim()||"Unassigned";
        const effective_team=String(row.effective_team||row.team||row.tableau_team||"Unassigned").trim()||"Unassigned";
        const assigned=Number(row.assigned_team_id||0);
        return {
          ...row,
          rep_key,
          rep_name,
          tableau_team,
          effective_team,
          // Only an explicit Pi assignment counts as occupied. Tableau's own
          // team text/effective fallback must never hide a candidate rep.
          assigned_team_id:assigned>0?assigned:null,
        };
      })
      .filter(Boolean)
      .sort((a,b)=>a.rep_name.localeCompare(b.rep_name));
  }

  function mergeAssignments(rows,persisted){
    const byKey=new Map();
    const byName=new Map();
    normalizeRows(persisted).forEach(rep=>{
      byKey.set(String(rep.rep_key),rep);
      byName.set(String(rep.rep_name||"").trim().toLowerCase(),rep);
    });
    return normalizeRows(rows).map(rep=>{
      const saved=byKey.get(String(rep.rep_key)) ||
        byName.get(String(rep.rep_name||"").trim().toLowerCase());
      if(!saved) return rep;
      const assigned=Number(saved.assigned_team_id||0);
      return {
        ...rep,
        assigned_team_id:assigned>0?assigned:null,
        effective_team:assigned>0
          ? String(saved.effective_team||rep.effective_team||"Unassigned")
          : rep.effective_team,
        local_team_override:!!saved.local_team_override,
      };
    });
  }

  function memberStepVisible(){
    return overlay.classList.contains("open") && Number(builderStep)===2;
  }

  function eligibleRows(rows){
    const current=Number(builderTeamId||0);
    return normalizeRows(rows).filter(rep=>{
      const assigned=Number(rep.assigned_team_id||0);
      return !assigned || (current>0 && assigned===current);
    });
  }

  function paintEmptyState(fullPool,eligible){
    if(eligible.length) return;
    const hasTableau=Array.isArray(fullPool)&&fullPool.length>0;
    memberList.innerHTML=hasTableau
      ? `<div class="small" id="tableauMemberEmptyV126" style="grid-column:1/-1;border:1px solid #2b2b2b;background:#0c0c0c;padding:14px;line-height:1.45">
          <strong style="color:var(--text)">No unassigned Tableau reps available.</strong><br>
          Everyone in the current Tableau pull is already assigned to another team.
        </div>`
      : `<div class="small" id="tableauMemberEmptyV126" style="grid-column:1/-1;border:1px solid #2b2b2b;background:#0c0c0c;padding:14px;line-height:1.45">
          <strong style="color:var(--text)">No Tableau reps loaded yet.</strong><br>
          Pull or preview a Tableau report first. The names from that Tableau data will appear here automatically.
        </div>`;
    const count=document.getElementById("selectedMemberCount");
    if(count) count.textContent=`${builderMembers.size} member${builderMembers.size===1?"":"s"}`;
  }

  function renderCurrentPool(){
    const full=Array.isArray(reps)?reps:[];
    const eligible=eligibleRows(full);
    // Reuse the established checklist/search renderer rather than introducing
    // a second membership UI. Restore the full pool immediately afterward so
    // review and Team Lead selection still resolve every selected member.
    reps=eligible;
    try{originalRenderBuilderMembers();}
    finally{reps=full;}
    paintEmptyState(full,eligible);
  }

  renderBuilderMembers=function(){renderCurrentPool();};

  function applyPool(rows){
    reps=normalizeRows(rows);
    if(memberStepVisible()) renderCurrentPool();
  }

  async function refreshPersistedPool(){
    const sequence=++refreshSequence;
    if(memberStepVisible() && (!Array.isArray(reps)||!reps.length)){
      memberList.innerHTML='<div class="small" style="grid-column:1/-1;padding:12px">Loading reps from Tableau…</div>';
    }
    try{
      const {r,d}=await originalRequest("/api/config",{cache:"no-store"});
      if(sequence!==refreshSequence||!r.ok) return;
      persistedPool=normalizeRows(d.reps||[]);
      const current=previewPool&&previewPool.length
        ?mergeAssignments(previewPool,persistedPool)
        :persistedPool;
      applyPool(current);
    }catch(_){
      if(sequence!==refreshSequence) return;
      if(memberStepVisible()) renderCurrentPool();
    }
  }

  request=async function(path,options={}){
    const result=await originalRequest(path,options);
    const cleanPath=String(path||"").split("?",1)[0];

    if(cleanPath==="/api/source/preview" &&
       result?.r?.ok && result?.d?.ok && Array.isArray(result.d.rows)){
      previewPool=normalizeRows(result.d.rows);
      applyPool(mergeAssignments(previewPool,persistedPool));
      // Re-read Pi-owned assignments after the preview so even a Settings page
      // that was open for hours cannot offer somebody already claimed elsewhere.
      setTimeout(refreshPersistedPool,0);
      window.dispatchEvent(new CustomEvent("stats-tableau-reps-updated",{
        detail:{source:"preview",count:previewPool.length}
      }));
    }

    if(cleanPath==="/api/source/refresh" && result?.r?.ok){
      previewPool=null;
      setTimeout(refreshPersistedPool,0);
    }

    return result;
  };

  openTeamBuilder=function(id=null){
    originalOpenTeamBuilder(id);
    refreshPersistedPool();
  };

  setBuilderStep=function(n){
    originalSetBuilderStep(n);
    if(Number(builderStep)===2) refreshPersistedPool();
  };

  if(!Array.isArray(reps)||!reps.length) paintEmptyState([],[]);
})();
