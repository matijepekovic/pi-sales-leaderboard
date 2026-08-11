/* v43 card-theme ordering guard.
   The v36 display layer can remove/reorder teams after excluding reps without a
   local Pi assignment. Match the final DOM card by rendered team name so a theme
   can never be applied to a neighboring team after that filtering step. */
(function(){
  if(typeof render!=="function") return;
  const previousRender=render;

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

  render=function(data){
    const result=previousRender(data);
    correctFinalCards(data);
    return result;
  };
})();
