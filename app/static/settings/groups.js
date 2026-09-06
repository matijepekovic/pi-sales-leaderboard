/* Groups owns reusable row assignments and Group themes; Screens own presentation. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc,FieldEditor=window.StatsFieldEditor;
  const S={types:[],groups:[],reports:[],themes:[],openTypes:new Set(),editor:null,typeRows:null,message:"",loaded:false};
  const typeBy=id=>S.types.find(item=>String(item.id)===String(id))||null;
  const groupBy=id=>S.groups.find(item=>String(item.id)===String(id))||null;
  const reportBy=id=>S.reports.find(item=>String(item.id)===String(id))||null;
  const singular=name=>{const value=String(name||"Group").trim();if(/ies$/i.test(value))return value.slice(0,-3)+"y";if(/s$/i.test(value)&&!/ss$/i.test(value))return value.slice(0,-1);return value;};

  async function load(){
    const [types,groups,reports,themes]=await Promise.all([R.api("/api/group-types"),R.api("/api/groups"),R.api("/api/data/reports"),R.api("/api/themes")]);
    S.types=types.group_types||[];S.groups=groups.groups||[];S.reports=reports.reports||[];S.themes=themes.themes||[];S.loaded=true;render();
  }

  function roleEditor(rows,labelKey){
    const roles=S.editor.value.roles||[];
    return `<div class="subcard" style="margin-top:12px"><div class="toolbar"><strong>Roles</strong><button class="btn" type="button" data-action="add-role">+ Role</button></div>${roles.map((role,index)=>`<div class="grid" data-role-index="${index}" style="margin-top:10px"><div><label>Role name</label><input data-role-name value="${esc(role.name||"")}" placeholder="Manager, Lead, Right hand…"></div><div><label>Member</label><select data-role-member><option value="">Choose member…</option>${rows.map(row=>{const key=String(row._stats_member_key||"");return `<option value="${esc(key)}" ${String(role.member_key||"")===key?"selected":""}>${esc(String(row[labelKey]??key))}</option>`;}).join("")}</select></div><div><button class="btn" type="button" data-action="remove-role" data-index="${index}">Remove role</button></div></div>`).join("")||'<div class="small" style="margin-top:8px">No roles assigned.</div>'}</div>`;
  }

  function typeEditor(){
    if(S.editor?.kind!=="type")return"";
    const value=S.editor.value;
    return `<div class="card"><div class="toolbar"><div><h2>${value.id?"Rename":"Create"} Group Type</h2><div class="small">A Group Type is only a category, such as Teams, Products, or Offices.</div></div><button class="btn" data-action="cancel-editor">Cancel</button></div><div style="margin-top:12px"><label>Group Type Name</label><input data-type-name value="${esc(value.name||"")}" placeholder="Example: Teams"></div><div class="small" style="margin-top:8px">You will choose the Report, column, and members when you add the first named Group.</div><div class="row" style="margin-top:12px"><button class="btn primary" data-action="save-type">Save Group Type</button></div></div>`;
  }

  function memberTable(){
    if(S.editor?.kind!=="group"||!S.typeRows)return"";
    const definition=S.typeRows.type||{},fields=S.typeRows.fields||[],members=S.editor.members;
    const labelKey=String(definition.member_label_field||definition.member_key_field||"");
    const orderedFields=[...fields.filter(field=>String(field.key)===labelKey),...fields.filter(field=>String(field.key)!==labelKey)];
    const allRows=S.typeRows.rows||[],currentId=String(S.editor.value.id||"");
    const rows=allRows.filter(row=>members.has(String(row._stats_member_key||""))||!(row._stats_groups||[]).some(group=>String(group.id)!==currentId));
    const unavailableCount=allRows.length-rows.length;
    const selectedRows=rows.filter(row=>members.has(String(row._stats_member_key||"")));
    for(const key of members)if(!selectedRows.some(row=>String(row._stats_member_key)===String(key)))selectedRows.push({_stats_member_key:key,[labelKey]:key});
    const leaderPicker=roleEditor(selectedRows,labelKey);
    const sourcePicker=S.editor.typeWasConfigured?`<div class="small" style="margin-top:10px">Members come from <strong>${esc(definition.report_name||"")}</strong>.</div>`:`<div style="margin-top:12px"><label>Choose members from</label><select data-group-report>${S.reports.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===String(S.editor.sourceReportId)?"selected":""}>${esc(item.name)}</option>`).join("")}</select><div class="small" style="margin-top:5px">Tick the rows directly in the table below.</div></div>`;
    return `<div class="card"><div class="toolbar"><div><h2>${S.editor.value.id?"Edit":"Create"} ${esc(definition.name||"Group")}</h2><div class="small">Choose a Report, then tick the members directly. Every column on each checked row comes with them automatically.</div></div><button class="btn" data-action="cancel-editor">Cancel</button></div><div style="margin-top:12px"><label>Group Name</label><input data-group-name value="${esc(S.editor.value.name||"")}" placeholder="Example: Olympia Team"></div>${sourcePicker}<div class="toolbar" style="margin-top:12px"><div><label for="groupMemberSearch">Find available members</label><input id="groupMemberSearch" placeholder="Search names or any column" style="min-width:260px"></div><div><strong data-selected-count>${members.size} selected</strong>${unavailableCount?`<div class="small">${unavailableCount} already assigned elsewhere in ${esc(definition.name)} and hidden</div>`:""}</div></div><div class="data-table group-member-table" style="margin-top:10px"><table><thead><tr><th>Select</th>${orderedFields.map(field=>`<th>${esc(field.label||field.key)}<div class="field-key">${esc(field.type||"text")}</div></th>`).join("")}</tr></thead><tbody>${rows.map(row=>{const key=String(row._stats_member_key||""),search=fields.map(field=>String(row[field.key]??"")).join(" ").toLowerCase();return `<tr data-member-row data-search="${esc(search)}"><td><input type="checkbox" data-member-key="${esc(key)}" ${members.has(key)?"checked":""} aria-label="Select ${esc(String(row[definition.member_label_field]??key))}"></td>${orderedFields.map(field=>`<td>${esc(FieldEditor.formatValue(row[field.key],field.type,field.decimals,field.percent_input_scale))}</td>`).join("")}</tr>`;}).join("")||`<tr><td colspan="${orderedFields.length+1}">No unassigned members are available in this Report.</td></tr>`}</tbody></table></div>${leaderPicker}<div class="row" style="margin-top:12px"><button class="btn primary" data-action="save-group">Save Group</button></div></div>`;
  }

  function typeCard(definition){
    const groups=S.groups.filter(group=>String(group.type_id)===String(definition.id)),open=S.openTypes.has(String(definition.id));
    const source=definition.report_id?`${esc(definition.report_name)} → ${esc(definition.member_label_field||definition.member_key_field)}`:"Choose data in the first Group";
    const cards=groups.map(group=>`<div class="subcard"><div class="toolbar"><div><strong>${esc(group.name)}</strong><div class="small">${Number(group.member_count||0)} members · ${(group.roles||[]).length} roles</div></div><div class="row"><button class="btn" data-action="edit-group" data-id="${esc(group.id)}">Members & Roles</button><button class="btn" data-action="theme" data-id="${esc(group.id)}">Theme & Assets</button><button class="btn danger" data-action="delete-group" data-id="${esc(group.id)}">Delete</button></div></div><div style="margin-top:10px"><label>Theme</label><select data-group-theme="${esc(group.id)}">${S.themes.map(theme=>`<option value="${esc(theme.id)}" ${String(group.appearance?.theme_id||"starter")===String(theme.id)?"selected":""}>${esc(theme.name)}</option>`).join("")}</select></div></div>`).join("");
    return `<details class="card" data-group-type="${esc(definition.id)}" ${open?"open":""}><summary style="cursor:pointer"><strong>${esc(definition.name)}</strong><span class="small"> · ${source} · ${groups.length}</span></summary><div class="toolbar" style="margin-top:12px;justify-content:flex-end"><div class="row"><button class="btn primary" data-action="new-group" data-type-id="${esc(definition.id)}">+ ${esc(singular(definition.name))}</button><button class="btn" data-action="edit-type" data-id="${esc(definition.id)}">Rename Type</button><button class="btn danger" data-action="delete-type" data-id="${esc(definition.id)}">Delete Type</button></div></div><div class="stack" style="margin-top:10px">${cards||'<div class="small">No entries yet.</div>'}</div></details>`;
  }

  function render(){
    const host=$("settingsGroupsHost");if(!host)return;
    const editor=typeEditor()||memberTable();
    host.innerHTML=`${editor}<div class="card"><div class="toolbar"><div><h2>Group Types</h2><div class="small">Create a type such as Teams or Products, then create named Groups and assign members to them.</div></div><button class="btn primary" data-action="new-type">+ Group Type</button></div></div>${S.types.map(typeCard).join("")||'<div class="card"><div class="small">No Group Types yet. Create Teams, Products, Offices, or another category.</div></div>'}<div class="status">${esc(S.message)}</div>`;
    bind();
  }

  function syncType(){
    const host=$("settingsGroupsHost"),value=S.editor?.value;if(!host||S.editor?.kind!=="type")return;
    value.name=host.querySelector("[data-type-name]")?.value||"";
  }

  async function saveType(){
    syncType();const value=S.editor.value;S.message="Saving Group Type…";render();
    try{await R.api(value.id?`/api/group-types/${encodeURIComponent(value.id)}`:"/api/group-types",R.json(value.id?"PUT":"POST",value));S.editor=null;S.typeRows=null;S.message="Group Type saved.";await load();R.emit("groups-changed");}catch(error){S.message=error.message;render();}
  }

  async function openGroup(typeId,id=""){
    S.openTypes.add(String(typeId));S.message="Loading Report rows…";render();
    try{const definition=typeBy(typeId),existing=id?groupBy(id):null,typeWasConfigured=!!definition?.report_id,sourceReportId=definition?.report_id||S.reports[0]?.id||"";S.editor={kind:"group",value:existing?JSON.parse(JSON.stringify(existing)):{type_id:typeId,name:"",member_keys:[],roles:[]},members:new Set((existing?.member_keys||[]).map(String)),typeWasConfigured,sourceReportId};await reloadGroupRows(false);S.message="";}catch(error){S.message=error.message;}
    render();
  }

  async function reloadGroupRows(clearMembers=true){
    if(S.editor?.kind!=="group")return;
    if(clearMembers)S.editor.members.clear();
    const query=S.editor.typeWasConfigured?"":`?report_id=${encodeURIComponent(S.editor.sourceReportId)}`;
    S.typeRows=await R.api(`/api/group-types/${encodeURIComponent(S.editor.value.type_id)}/rows${query}`);
  }

  async function saveGroup(){
    const value=S.editor?.value;if(!value)return;syncGroupDraft();value.member_keys=[...S.editor.members];value.report_id=S.editor.sourceReportId;S.message="Saving Group…";render();
    try{await R.api(value.id?`/api/groups/${encodeURIComponent(value.id)}`:"/api/groups",R.json(value.id?"PUT":"POST",value));S.editor=null;S.typeRows=null;S.message="Group saved. Its rows now keep every current Report column.";await load();R.emit("groups-changed");}catch(error){S.message=error.message;render();}
  }

  function syncGroupDraft(host=$("settingsGroupsHost")){
    if(!host||S.editor?.kind!=="group")return;
    S.editor.value.name=host.querySelector("[data-group-name]")?.value||S.editor.value.name;
    host.querySelectorAll("[data-role-index]").forEach(row=>{const role=S.editor.value.roles[Number(row.dataset.roleIndex)];if(role){role.name=row.querySelector("[data-role-name]").value;role.member_key=row.querySelector("[data-role-member]").value;}});
  }

  async function removeType(id){if(!confirm("Delete this Group Type?"))return;try{await R.api(`/api/group-types/${encodeURIComponent(id)}`,{method:"DELETE"});S.message="Group Type deleted.";await load();R.emit("groups-changed");}catch(error){S.message=error.message;render();}}
  async function removeGroup(id){if(!confirm("Delete this named Group?"))return;try{await R.api(`/api/groups/${encodeURIComponent(id)}`,{method:"DELETE"});S.message="Group deleted.";await load();R.emit("groups-changed");}catch(error){S.message=error.message;render();}}

  function bind(){
    const host=$("settingsGroupsHost");if(!host)return;
    host.querySelectorAll("[data-group-theme]").forEach(select=>select.addEventListener("change",async()=>{try{await R.api(`/api/groups/${encodeURIComponent(select.dataset.groupTheme)}/appearance`,R.json("PUT",{theme_id:select.value}));await load();R.emit("theme-changed",{owner:"group",id:select.dataset.groupTheme});}catch(error){S.message=error.message;render();}}));
    host.querySelectorAll("[data-group-type]").forEach(details=>details.addEventListener("toggle",()=>{details.open?S.openTypes.add(String(details.dataset.groupType)):S.openTypes.delete(String(details.dataset.groupType));}));
    host.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",()=>{
      const action=button.dataset.action,id=button.dataset.id,typeId=button.dataset.typeId;
      if(action==="new-type"){S.editor={kind:"type",value:{name:""}};S.typeRows=null;render();return;}
      if(action==="edit-type"){S.editor={kind:"type",value:JSON.parse(JSON.stringify(typeBy(id)))};S.typeRows=null;S.openTypes.add(String(id));render();return;}
      if(action==="cancel-editor"){S.editor=null;S.typeRows=null;S.message="";render();return;}
      if(action==="save-type")return saveType();
      if(action==="new-group")return openGroup(typeId);
      if(action==="edit-group")return openGroup(groupBy(id)?.type_id,id);
      if(action==="save-group")return saveGroup();
      if(action==="delete-type")return removeType(id);
      if(action==="delete-group")return removeGroup(id);
      if(action==="theme")return window.StatsThemeManager.openGroup(id);
      if(action==="add-role"){syncGroupDraft(host);S.editor.value.roles.push({name:"",member_key:""});render();return;}
      if(action==="remove-role"){syncGroupDraft(host);S.editor.value.roles.splice(Number(button.dataset.index),1);render();return;}
    }));
    host.querySelector("[data-group-report]")?.addEventListener("change",async event=>{syncGroupDraft(host);S.editor.sourceReportId=event.target.value;S.message="Loading members…";render();try{await reloadGroupRows();S.message="";}catch(error){S.message=error.message;}render();});
    host.querySelectorAll("[data-member-key]").forEach(input=>input.addEventListener("change",()=>{syncGroupDraft(host);input.checked?S.editor.members.add(input.dataset.memberKey):S.editor.members.delete(input.dataset.memberKey);for(const role of S.editor.value.roles||[])if(!S.editor.members.has(String(role.member_key||"")))role.member_key="";render();}));
    host.querySelector("#groupMemberSearch")?.addEventListener("input",event=>{const query=event.target.value.trim().toLowerCase();host.querySelectorAll("[data-member-row]").forEach(row=>row.hidden=!!query&&!String(row.dataset.search||"").includes(query));});
  }

  R.on("section",id=>{if(id==="settingsGroups"&&!S.loaded)load().catch(error=>{S.message=error.message;render();});});
  R.on("unlocked",()=>{S.loaded=false;});
  R.on("data-changed",()=>{S.loaded=false;});
  R.on("theme-changed",()=>{S.loaded=false;});
})();
