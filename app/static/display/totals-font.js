/* v47 presentation-only totals sizing.
   Team totals use the exact same font-size rules as rep stat cells so long
   currency values cannot overflow simply because totals were oversized. */
(function(){
  const style=document.createElement("style");
  style.id="v47TotalsFontFix";
  style.textContent=`
    #themedTeamBroadcast .bt-total-v{
      font-size:clamp(10px,.88vw,16px)!important;
    }
    #themedTeamBroadcast.dense .bt-total-v{
      font-size:clamp(9px,.76vw,13px)!important;
    }
  `;
  Display.placeStyle(60, style);
})();
