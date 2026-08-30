/* v59 Whole Office team-column runtime hotfix.
   PRESENTATION ONLY. Keeps the v58 Sales Rep / Team split, but makes the DOM
   patch idempotent and only reacts to newly rendered leaderboard structures.
   This prevents the observer from reacting to its own mutations. */
(function(){
  const ROOT_ID="v55OfficeBroadcast";
  const STYLE_ID="v59WholeOfficeTeamColumn";
  let scheduled=false;

  function directChildWithClass(parent,className){
    if(!parent) return null;
    for(const child of parent.children){
      if(child.classList && child.classList.contains(className)) return child;
    }
    return null;
  }

  function directTeamCell(row){
    return directChildWithClass(row,"v59-office-team-cell") ||
           directChildWithClass(row,"v58-office-team-cell");
  }

  function ensureStyle(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      #${ROOT_ID} .v55-office-head,
      #${ROOT_ID} .v55-office-row,
      #${ROOT_ID} .v55-office-footer{
        grid-template-columns:
          clamp(64px,4.2vw,165px)
          minmax(300px,2.45fr)
          clamp(80px,5.2vw,190px)
          repeat(var(--v55-office-cols),minmax(0,1fr))!important;
      }

      #${ROOT_ID} .v55-office-head .rep{
        text-align:left!important;
        padding-left:10px!important;
      }
      #${ROOT_ID} .v59-team-head,
      #${ROOT_ID} .v58-team-head{
        text-align:center!important;
        color:var(--v55-muted)!important;
      }

      #${ROOT_ID} .v55-office-rep{
        display:block!important;
        min-width:0!important;
        padding:2px clamp(8px,.55vw,22px)!important;
      }
      #${ROOT_ID} .v55-office-name,
      #${ROOT_ID} .champion .v55-office-name{
        display:block!important;
        max-width:100%!important;
        width:100%!important;
        white-space:nowrap!important;
        overflow:hidden!important;
        text-overflow:ellipsis!important;
      }

      #${ROOT_ID} .v59-office-team-cell,
      #${ROOT_ID} .v58-office-team-cell{
        align-self:stretch!important;
        min-width:0!important;
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;
        overflow:hidden!important;
        border-left:1px solid rgba(255,255,255,.08)!important;
        border-right:1px solid rgba(255,255,255,.08)!important;
        padding:1px 4px!important;
      }
      #${ROOT_ID} .v59-office-team-cell .v55-office-team-logo,
      #${ROOT_ID} .v58-office-team-cell .v55-office-team-logo{
        display:block!important;
        flex:0 0 auto!important;
        width:clamp(38px,2.35vw,92px)!important;
        height:clamp(38px,2.35vw,92px)!important;
        max-width:95%!important;
        max-height:95%!important;
        object-fit:contain!important;
        margin:0!important;
        filter:drop-shadow(0 2px 5px rgba(0,0,0,.85))!important;
      }

      #${ROOT_ID} .v55-office-footer-spacer{
        grid-column:span 3!important;
      }
    `;
    Display.placeStyle(130, style);
  }

  function patch(root){
    if(!root) return;
    ensureStyle();

    const head=root.querySelector(".v55-office-head");
    if(head){
      const repHead=head.children[1];
      if(repHead){
        if(repHead.textContent.trim()!=="Sales Rep") repHead.textContent="Sales Rep";
        if(!repHead.classList.contains("rep")) repHead.classList.add("rep");

        let teamHead=head.querySelector(".v59-team-head, .v58-team-head");
        if(!teamHead){
          teamHead=document.createElement("div");
          teamHead.className="v59-team-head";
          teamHead.textContent="Team";
          repHead.insertAdjacentElement("afterend",teamHead);
        }else{
          if(!teamHead.classList.contains("v59-team-head")) teamHead.classList.add("v59-team-head");
          if(teamHead.textContent.trim()!=="Team") teamHead.textContent="Team";
        }
      }
    }

    root.querySelectorAll(".v55-office-row").forEach(row=>{
      const rep=directChildWithClass(row,"v55-office-rep");
      if(!rep) return;

      let cell=directTeamCell(row);
      if(!cell){
        cell=document.createElement("div");
        cell.className="v59-office-team-cell";
        rep.insertAdjacentElement("afterend",cell);
      }else if(!cell.classList.contains("v59-office-team-cell")){
        cell.classList.add("v59-office-team-cell");
      }

      const oldTeam=rep.querySelector(".v55-office-team");
      if(!oldTeam) return;

      const logo=oldTeam.querySelector(".v55-office-team-logo");
      if(logo){
        const src=String(logo.getAttribute("src")||"");
        // Whole Office Team column intentionally accepts Logo Small only.
        if(src && !src.includes("/api/teams/")){
          if(cell.firstElementChild!==logo || cell.children.length!==1){
            cell.replaceChildren(logo);
          }else{
            cell.appendChild(logo);
          }
        }else if(cell.childNodes.length){
          cell.replaceChildren();
        }
      }else if(cell.childNodes.length){
        cell.replaceChildren();
      }
      oldTeam.remove();
    });
  }

  function apply(){
    patch(document.getElementById(ROOT_ID));
  }

  function scheduleApply(){
    if(scheduled) return;
    scheduled=true;
    requestAnimationFrame(()=>{
      scheduled=false;
      apply();
    });
  }

  ensureStyle();
  apply();

  const observer=new MutationObserver(mutations=>{
    let relevant=false;
    outer:
    for(const mutation of mutations){
      for(const node of mutation.addedNodes){
        if(node.nodeType!==1) continue;
        const el=node;
        if(el.id===ROOT_ID ||
           (el.classList && (el.classList.contains("v55-office-head") || el.classList.contains("v55-office-row"))) ||
           (el.querySelector && el.querySelector(`#${ROOT_ID}, .v55-office-head, .v55-office-row`))){
          relevant=true;
          break outer;
        }
      }
    }
    if(relevant) scheduleApply();
  });

  if(document.body) observer.observe(document.body,{childList:true,subtree:true});
})();
