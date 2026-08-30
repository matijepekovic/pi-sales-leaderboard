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
