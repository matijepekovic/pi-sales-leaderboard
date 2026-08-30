/* v54 presentation-only team totals placement.
   Keep the per-team totals strip attached to the rep table instead of letting
   the flexing broadcast shell push it to the bottom edge of the TV. */
(function(){
  if(typeof render!=="function") return;

  const STYLE_ID="teamTotalsTableFooterV54Styles";

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      #themedTeamBroadcast .bt-board > .bt-footer{
        width:100%!important;
        margin:clamp(4px,.65vh,9px) 0 0!important;
        flex:0 0 auto!important;
        align-self:stretch!important;
      }
    `;
    document.head.appendChild(style);
  }

  function attachTotalsToTable(){
    const root=document.getElementById("themedTeamBroadcast");
    if(!root) return;
    const board=root.querySelector(".bt-board");
    const footer=root.querySelector(":scope > .bt-footer");
    if(board&&footer) board.appendChild(footer);
  }

  Display.stage(100, function(data, next){
    const result=next(data);
    if(data?.mode==="per_team"){
      ensureStyles();
      attachTotalsToTable();
    }
    return result;
  });
})();
