/* v57 Whole Office identity compaction.
   PRESENTATION ONLY. Keep rep and team on one horizontal line to save row height
   while balancing their visual weight for TV readability. */
(function(){
  const style=document.createElement("style");
  style.id="v57WholeOfficeInlineTeam";
  style.textContent=`
    #v55OfficeBroadcast .v55-office-row{
      height:clamp(34px,3.05vh,70px)!important;
    }
    #v55OfficeBroadcast .v55-office-row.champion{
      height:clamp(42px,3.70vh,86px)!important;
    }
    #v55OfficeBroadcast .v55-office-rep{
      display:flex!important;
      align-items:center!important;
      gap:clamp(10px,.65vw,26px)!important;
      min-width:0!important;
      padding:2px clamp(8px,.55vw,22px)!important;
    }
    #v55OfficeBroadcast .v55-office-name{
      flex:0 1 auto!important;
      max-width:62%!important;
      min-width:0!important;
      font-size:clamp(14px,.72vw,29px)!important;
      line-height:1!important;
      white-space:nowrap!important;
      overflow:hidden!important;
      text-overflow:ellipsis!important;
    }
    #v55OfficeBroadcast .champion .v55-office-name{
      font-size:clamp(15px,.78vw,31px)!important;
    }
    #v55OfficeBroadcast .v55-office-team{
      flex:1 1 auto!important;
      min-width:0!important;
      margin-top:0!important;
      gap:clamp(6px,.34vw,14px)!important;
      font-size:clamp(11px,.55vw,22px)!important;
      line-height:1!important;
      letter-spacing:.035em!important;
    }
    #v55OfficeBroadcast .v55-office-team span{
      min-width:0!important;
      overflow:hidden!important;
      text-overflow:ellipsis!important;
      white-space:nowrap!important;
    }
    #v55OfficeBroadcast .v55-office-team-logo{
      width:clamp(25px,1.15vw,46px)!important;
      height:clamp(22px,1.02vw,41px)!important;
      flex:0 0 auto!important;
    }
  `;
  document.head.appendChild(style);
})();
