/* v58 Whole Office team column.
   PRESENTATION ONLY. Split Sales Rep and Team into separate columns. Team uses
   Logo Small only, with no team-name text, at champion-medallion visual scale. */
(function(){
  const ROOT_ID="v55OfficeBroadcast";
  const STYLE_ID="v58WholeOfficeTeamColumn";

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

      #${ROOT_ID} .v58-office-team-cell{
        align-self:stretch!important;
        min-width:0!important;
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;
        overflow:hidden!important;
        border-left:1px solid color-mix(in srgb,var(--v55-primary) 20%,transparent)!important;
        border-right:1px solid color-mix(in srgb,var(--v55-primary) 20%,transparent)!important;
        padding:1px 4px!important;
      }
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
    document.head.appendChild(style);
  }

  function patch(root){
    if(!root) return;
    ensureStyle();

    const head=root.querySelector(".v55-office-head");
    if(head){
      const repHead=head.children[1];
      if(repHead){
        repHead.textContent="Sales Rep";
        repHead.classList.add("rep");
        if(!head.querySelector(".v58-team-head")){
          const teamHead=document.createElement("div");
          teamHead.className="v58-team-head";
          teamHead.textContent="Team";
          repHead.insertAdjacentElement("afterend",teamHead);
        }
      }
    }

    root.querySelectorAll(".v55-office-row").forEach(row=>{
      if(row.querySelector(":scope > .v58-office-team-cell")) return;
      const rep=row.querySelector(":scope > .v55-office-rep");
      if(!rep) return;

      const oldTeam=rep.querySelector(".v55-office-team");
      const cell=document.createElement("div");
      cell.className="v58-office-team-cell";

      if(oldTeam){
        const logo=oldTeam.querySelector(".v55-office-team-logo");
        if(logo){
          const src=String(logo.getAttribute("src")||"");
          // v55 falls back to the Team Builder main logo when Logo Small is
          // missing. Whole Office v58 intentionally shows Logo Small only.
          if(!src.includes("/api/teams/")) cell.appendChild(logo);
        }
        oldTeam.remove();
      }

      rep.insertAdjacentElement("afterend",cell);
    });
  }

  function apply(){ patch(document.getElementById(ROOT_ID)); }

  ensureStyle();
  apply();

  const observer=new MutationObserver(()=>apply());
  observer.observe(document.body,{childList:true,subtree:true});
})();
