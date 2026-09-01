/* Teams settings owns team CRUD and the Team Builder. */
(function(){
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  let teams=[],reps=[],leaderCandidates=[];
  let builderTeamId=null,builderStep=0,builderExistingLogo=null,builderRemoveLogo=false;
  let builderMembers=new Set();
  let started=false;

  async function api(url,options={}){
    const response=await fetch(url,{cache:"no-store",...options});
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false)throw new Error(data.error||`Request failed (${response.status})`);
    return data;
  }

  function setStatus(text){const el=$("teamBuilderStatus");if(el)el.textContent=text||"";}
  function openOverlay(id){const el=$(id);if(!el)return;el.classList.add("open");el.setAttribute("aria-hidden","false");}
  function closeOverlay(id){const el=$(id);if(!el)return;el.classList.remove("open");el.setAttribute("aria-hidden","true");}
  function teamById(id){return teams.find(team=>Number(team.team_id)===Number(id))||null;}
  function selectedMembers(){return reps.filter(rep=>builderMembers.has(String(rep.rep_key))).sort((a,b)=>String(a.rep_name||"").localeCompare(String(b.rep_name||"")));}

  async function refresh(){
    const data=await api("/api/organization");
    teams=data.teams||[];reps=data.reps||[];leaderCandidates=data.leader_candidates||[];
    renderTeamList();
    document.dispatchEvent(new CustomEvent("stats:teams-rendered"));
    return data;
  }

  function renderTeamList(){
    const list=$("teamBuilderList");if(!list)return;
    list.innerHTML=teams.map(team=>{
      const lead=team.leader||(team.leads||[])[0];
      const logo=team.logo_url
        ?`<img class="team-logo" src="${esc(team.logo_url)}" alt="${esc(team.name)} logo">`
        :'<div class="team-logo placeholder">NO<br>LOGO</div>';
      return `<div class="team-summary" data-team-row="${Number(team.team_id)}">${logo}<div><div class="team-title">${esc(team.name)}</div><div class="small">${Number(team.rep_count||0)} members</div><div class="small">${lead?`Lead: ${esc(lead.lead_name)} · ${esc(lead.lead_role)}`:"No team lead"}</div></div><div class="team-actions"><button class="btn editTeam" data-team-edit="${Number(team.team_id)}" type="button">Edit Team</button><button class="btn designTeam" data-team-design="${Number(team.team_id)}" type="button">Design</button><button class="btn danger" data-team-delete="${Number(team.team_id)}" type="button">Delete Team</button></div></div>`;
    }).join("")||'<div class="small">No teams created yet.</div>';
  }

  function availableForBuilder(rep){
    const assigned=Number(rep.assigned_team_id||0);
    return !assigned||(builderTeamId&&assigned===Number(builderTeamId));
  }

  function renderMembers(){
    const host=$("builderMembers");if(!host)return;
    const query=String($("memberSearch")?.value||"").trim().toLowerCase();
    const visible=reps.filter(rep=>availableForBuilder(rep)).filter(rep=>{
      if(!query)return true;
      return [rep.rep_name,rep.source_team,rep.effective_team].some(value=>String(value||"").toLowerCase().includes(query));
    }).sort((a,b)=>String(a.rep_name||"").localeCompare(String(b.rep_name||"")));
    host.innerHTML=visible.map(rep=>{
      const key=String(rep.rep_key||"");
      const checked=builderMembers.has(key);
      const source=String(rep.source_team||"Unassigned");
      const current=String(rep.effective_team||"Unassigned");
      const context=current!==source?`Stats team: ${esc(current)} · Source team: ${esc(source)}`:`Source team: ${esc(source)}`;
      return `<label class="member-option"><input class="builderMember" type="checkbox" value="${esc(key)}" ${checked?"checked":""}><span><strong>${esc(rep.rep_name||key)}</strong><br><span class="small">${context}</span></span></label>`;
    }).join("")||'<div class="small">No unassigned reps match this search.</div>';
    $("selectedMemberCount").textContent=`${builderMembers.size} member${builderMembers.size===1?"":"s"}`;
    renderLeader();
  }

  function renderLeader(preferred){
    const select=$("builderLeader");if(!select)return;
    const members=selectedMembers();
    const previous=preferred!==undefined?String(preferred||""):String(select.value||"");
    select.innerHTML='<option value="">No Leader</option>'+members.map(rep=>`<option value="${esc(rep.rep_name)}">${esc(rep.rep_name)}</option>`).join("");
    select.value=members.some(rep=>String(rep.rep_name)===previous)?previous:"";
  }

  function setStep(next){
    builderStep=Math.max(0,Math.min(4,Number(next)||0));
    document.querySelectorAll("[data-team-builder-page]").forEach(page=>page.classList.toggle("active",Number(page.dataset.teamBuilderPage)===builderStep));
    document.querySelectorAll("[data-team-step-indicator]").forEach(item=>item.classList.toggle("active",Number(item.dataset.teamStepIndicator)===builderStep));
    if($("builderBack"))$("builderBack").style.visibility=builderStep===0?"hidden":"visible";
    if($("builderNext"))$("builderNext").hidden=builderStep===4;
    if($("builderSave"))$("builderSave").hidden=builderStep!==4;
    if($("builderDesign"))$("builderDesign").hidden=builderStep!==4;
    if(builderStep===2)renderMembers();
    if(builderStep===3)renderLeader();
    if(builderStep===4)renderReview();
  }

  function openBuilder(id=null){
    const team=id?teamById(id):null;
    builderTeamId=team?Number(team.team_id):null;
    builderStep=0;builderRemoveLogo=false;builderMembers=new Set((team?.member_rep_keys||[]).map(String));
    builderExistingLogo=team?.logo_url||null;
    $("builderTitle").textContent=team?`Edit ${team.name}`:"Create Team";
    $("builderTeamName").value=team?.name||"";
    $("builderLogo").value="";
    if(builderExistingLogo){$("builderLogoPreview").src=builderExistingLogo;$("builderLogoPreview").hidden=false;$("removeBuilderLogo").hidden=false;}
    else{$("builderLogoPreview").hidden=true;$("removeBuilderLogo").hidden=true;}
    $("memberSearch").value="";
    $("builderLeaderRole").value=(team?.leader||team?.leads?.[0])?.lead_role||"Sales Manager";
    renderMembers();
    renderLeader((team?.leader||team?.leads?.[0])?.lead_name||"");
    $("builderStatus").textContent="";
    setStep(0);openOverlay("teamBuilderOverlay");
  }

  function renderReview(){
    const host=$("builderReview");if(!host)return;
    const memberNames=selectedMembers().map(rep=>rep.rep_name);
    const logo=builderRemoveLogo?"Remove existing logo":$("builderLogo").files?.[0]?.name|| (builderExistingLogo?"Keep existing logo":"No logo");
    host.innerHTML=`<div class="card" style="margin:0"><div><strong>Team:</strong> ${esc($("builderTeamName").value.trim()||"Unnamed Team")}</div><div style="margin-top:8px"><strong>Logo:</strong> ${esc(logo)}</div><div style="margin-top:8px"><strong>Lead:</strong> ${esc($("builderLeader").value||"No Leader")}</div><div style="margin-top:8px"><strong>Members (${memberNames.length}):</strong></div><div class="small" style="margin-top:6px">${memberNames.length?memberNames.map(esc).join(", "):"No members selected"}</div></div>`;
  }

  async function uploadLogo(teamId){
    if(builderRemoveLogo){await api(`/api/teams/${teamId}/logo`,{method:"DELETE"});return;}
    const file=$("builderLogo").files?.[0];if(!file)return;
    const form=new FormData();form.append("logo",file);
    const response=await fetch(`/api/teams/${teamId}/logo`,{method:"POST",body:form});
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false)throw new Error(data.error||"Could not save team logo.");
  }

  async function saveCurrent({close=true}={}){
    const name=String($("builderTeamName")?.value||"").trim();
    if(!name){setStep(0);$("builderStatus").textContent="Choose a team name.";return null;}
    const leader=String($("builderLeader")?.value||"").trim();
    if(leader&&!selectedMembers().some(rep=>String(rep.rep_name)===leader)){
      setStep(3);$("builderStatus").textContent="Choose the team lead from this team's members.";return null;
    }
    const button=$("builderSave");if(button)button.disabled=true;$("builderStatus").textContent="Saving…";
    try{
      const result=await api("/api/team-builder/save",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          team_id:builderTeamId,name,
          leader_name:leader,leader_role:$("builderLeaderRole").value,
          member_rep_keys:Array.from(builderMembers)
        })
      });
      builderTeamId=Number(result.team_id);
      await uploadLogo(builderTeamId);
      await refresh();
      $("builderStatus").textContent="Team saved.";
      if(close)setTimeout(()=>closeOverlay("teamBuilderOverlay"),250);
      return builderTeamId;
    }catch(err){$("builderStatus").textContent=err.message||"Could not save team.";return null;}
    finally{if(button)button.disabled=false;}
  }

  async function openDesign(teamId){
    if(typeof window.openTeamDesign!=="function"){setStatus("Theme Editor is still loading. Try again in a moment.");return;}
    window.openTeamDesign(Number(teamId));
  }

  async function designFromBuilder(){
    let id=builderTeamId;
    if(!id)id=await saveCurrent({close:false});
    if(id)await openDesign(id);
  }

  async function openDelete(id){
    const team=teamById(id);if(!team)return;
    const memberKeys=new Set((team.member_rep_keys||[]).map(String));
    const members=reps.filter(rep=>memberKeys.has(String(rep.rep_key))).sort((a,b)=>String(a.rep_name||"").localeCompare(String(b.rep_name||"")));
    const destinations=teams.filter(item=>Number(item.team_id)!==Number(id));
    if(!members.length){
      if(!confirm(`Delete ${team.name}?`))return;
      try{await api(`/api/teams/${id}`,{method:"DELETE",headers:{"Content-Type":"application/json"},body:JSON.stringify({reassignments:[]})});await refresh();}
      catch(err){setStatus(err.message||"Could not delete team.");}
      return;
    }
    $("deleteTeamTitle").textContent=`Delete ${team.name}`;
    $("deleteTeamMessage").textContent=`${members.length} reps must be reassigned first.`;
    const host=$("deleteTeamAssignments");
    if(!destinations.length){host.innerHTML='<div class="card"><strong>Create another team first.</strong></div>';$("confirmDeleteTeam").disabled=true;}
    else{
      $("confirmDeleteTeam").disabled=false;
      const options=destinations.map(dest=>`<option value="${Number(dest.team_id)}">${esc(dest.name)}</option>`).join("");
      host.innerHTML=members.map(rep=>`<div class="assignment"><strong>${esc(rep.rep_name)}</strong><select class="deleteDestination" data-rep-key="${esc(rep.rep_key)}"><option value="">Choose team…</option>${options}</select></div>`).join("");
    }
    $("deleteTeamOverlay").dataset.teamId=String(id);$("deleteTeamStatus").textContent="";openOverlay("deleteTeamOverlay");
  }

  async function confirmDelete(){
    const id=Number($("deleteTeamOverlay")?.dataset.teamId||0);if(!id)return;
    const selects=Array.from(document.querySelectorAll(".deleteDestination"));
    if(selects.some(select=>!select.value)){$("deleteTeamStatus").textContent="Choose a destination for every rep.";return;}
    const button=$("confirmDeleteTeam");button.disabled=true;$("deleteTeamStatus").textContent="Deleting…";
    try{
      await api(`/api/teams/${id}`,{method:"DELETE",headers:{"Content-Type":"application/json"},body:JSON.stringify({reassignments:selects.map(select=>({rep_key:select.dataset.repKey,team_id:Number(select.value)}))})});
      await refresh();closeOverlay("deleteTeamOverlay");
    }catch(err){$("deleteTeamStatus").textContent=err.message||"Could not delete team.";}
    finally{button.disabled=false;}
  }

  function nextStep(){
    if(builderStep===0&&!String($("builderTeamName")?.value||"").trim()){$("builderStatus").textContent="Choose a team name first.";return;}
    if(builderStep===2&&!builderMembers.size){$("builderStatus").textContent="Choose at least one member.";return;}
    $("builderStatus").textContent="";setStep(builderStep+1);
  }

  function bind(){
    $("newTeamBuilder")?.addEventListener("click",()=>openBuilder());
    $("closeBuilder")?.addEventListener("click",()=>closeOverlay("teamBuilderOverlay"));
    $("builderBack")?.addEventListener("click",()=>setStep(builderStep-1));
    $("builderNext")?.addEventListener("click",nextStep);
    $("builderSave")?.addEventListener("click",()=>saveCurrent());
    $("builderDesign")?.addEventListener("click",designFromBuilder);
    $("memberSearch")?.addEventListener("input",renderMembers);
    $("builderMembers")?.addEventListener("change",event=>{
      const input=event.target.closest(".builderMember");if(!input)return;
      input.checked?builderMembers.add(String(input.value)):builderMembers.delete(String(input.value));
      renderMembers();
    });
    $("builderLogo")?.addEventListener("change",()=>{
      builderRemoveLogo=false;const file=$("builderLogo").files?.[0];if(!file)return;
      $("builderLogoPreview").src=URL.createObjectURL(file);$("builderLogoPreview").hidden=false;$("removeBuilderLogo").hidden=false;
    });
    $("removeBuilderLogo")?.addEventListener("click",()=>{builderRemoveLogo=true;$("builderLogo").value="";$("builderLogoPreview").hidden=true;$("removeBuilderLogo").hidden=true;});
    $("teamBuilderList")?.addEventListener("click",event=>{
      const edit=event.target.closest("[data-team-edit]");if(edit){openBuilder(Number(edit.dataset.teamEdit));return;}
      const design=event.target.closest("[data-team-design]");if(design){openDesign(Number(design.dataset.teamDesign));return;}
      const del=event.target.closest("[data-team-delete]");if(del)openDelete(Number(del.dataset.teamDelete));
    });
    $("cancelDeleteTeam")?.addEventListener("click",()=>closeOverlay("deleteTeamOverlay"));
    $("confirmDeleteTeam")?.addEventListener("click",confirmDelete);
  }

  async function start(){
    if(started)return;started=true;bind();
    try{await refresh();}catch(err){setStatus(err.message||"Could not load teams.");}
  }

  window.StatsTeams=Object.freeze({
    list:()=>teams.map(team=>({...team})),
    currentBuilderTeamId:()=>builderTeamId,
    findByName:name=>teams.find(team=>String(team.name||"").trim().toLowerCase()===String(name||"").trim().toLowerCase())||null,
    saveCurrent:options=>saveCurrent(options),
    refresh
  });

  document.addEventListener("stats:settings-ready",start);
  if(window.StatsSettingsReady)start();
})();
