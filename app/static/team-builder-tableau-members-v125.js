/* v125 Team Builder members come from the latest Tableau pull.

   The base Team Builder already knows how to search/select reps and persist
   their rep_key assignments. This layer only keeps its `reps` pool current:
   - refresh persisted reps from /api/config whenever Team Builder opens or
     the Members step is shown;
   - use rows from a successful Tableau Check Numbers / Preview pull
     immediately, even before that candidate report is saved;
   - fall back to a clear empty-state instead of a blank box.

   No second assignment model is introduced. save_team_builder() still owns
   all team membership persistence. */
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
        return {
          ...row,
          rep_key,
          rep_name,
          tableau_team,
          effective_team,
          assigned_team_id:row.assigned_team_id??row.effective_team_id??null,
        };
      })
      .filter(Boolean)
      .sort((a,b)=>a.rep_name.localeCompare(b.rep_name));
  }

  function memberStepVisible(){
    return overlay.classList.contains("open") && Number(builderStep)===2;
  }

  function paintEmptyState(){
    if(Array.isArray(reps)&&reps.length) return;
    memberList.innerHTML=`
      <div class="small" id="tableauMemberEmptyV125" style="grid-column:1/-1;border:1px solid #2b2b2b;background:#0c0c0c;padding:14px;line-height:1.45">
        <strong style="color:var(--text)">No Tableau reps loaded yet.</strong><br>
        Pull or preview a Tableau report first. The names from that Tableau data will appear here automatically.
      </div>`;
    const count=document.getElementById("selectedMemberCount");
    if(count) count.textContent=`${builderMembers.size} member${builderMembers.size===1?"":"s"}`;
  }

  function renderCurrentPool(){
    originalRenderBuilderMembers();
    paintEmptyState();
  }

  renderBuilderMembers=function(){
    renderCurrentPool();
  };

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
      const persisted=normalizeRows(d.reps||[]);
      // A successful candidate preview is the newest Tableau pull in this
      // Settings session, so prefer it until a real source refresh succeeds.
      applyPool(previewPool&&previewPool.length?previewPool:persisted);
    }catch(e){
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
      applyPool(previewPool);
      window.dispatchEvent(new CustomEvent("stats-tableau-reps-updated",{
        detail:{source:"preview",count:previewPool.length}
      }));
    }

    if(cleanPath==="/api/source/refresh" && result?.r?.ok){
      // Pull Now writes the source rows into SQLite. Drop any older candidate
      // preview so the freshly persisted rows become Team Builder's source.
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

  // If Settings loaded with no reps and a pull finishes later, the next Team
  // Builder open will refresh. If reps were already loaded, this keeps the
  // existing immediate behavior unchanged.
  if(!Array.isArray(reps)||!reps.length) paintEmptyState();
})();
