/* v56 Whole Office TV scale correction.
   PRESENTATION ONLY. v55 remains authoritative for the rendered values/order.
   Removes 1080p pixel caps so the broadcast fills high-resolution TV viewports. */
(function(){
  const style=document.createElement("style");
  style.id="v56WholeOfficeScale";
  style.textContent=`
    #v55OfficeBroadcast .v55-office-main{
      width:94vw!important;
      max-width:none!important;
    }
    #v55OfficeBroadcast .v55-office-brand{
      height:clamp(190px,19vh,420px)!important;
      padding:clamp(8px,1vh,20px) 4vw 0!important;
    }
    #v55OfficeBroadcast .v55-office-hero{
      width:min(58vw,2200px)!important;
      max-width:none!important;
      height:100%!important;
    }
    #v55OfficeBroadcast .v55-office-head,
    #v55OfficeBroadcast .v55-office-row,
    #v55OfficeBroadcast .v55-office-footer{
      grid-template-columns:clamp(64px,4.2vw,165px) minmax(340px,2.7fr) repeat(var(--v55-office-cols),minmax(0,1fr))!important;
    }
    #v55OfficeBroadcast .v55-office-head{
      height:clamp(36px,3.4vh,74px)!important;
      font-size:clamp(10px,.60vw,24px)!important;
      letter-spacing:.075em!important;
    }
    #v55OfficeBroadcast .v55-office-row{
      height:clamp(38px,3.55vh,82px)!important;
      min-height:0!important;
    }
    #v55OfficeBroadcast .v55-office-row.champion{
      height:clamp(48px,4.25vh,98px)!important;
    }
    #v55OfficeBroadcast .v55-office-rank{
      font-size:clamp(20px,1.20vw,48px)!important;
    }
    #v55OfficeBroadcast .v55-office-medal{
      width:clamp(38px,2.35vw,92px)!important;
      height:clamp(38px,2.35vw,92px)!important;
    }
    #v55OfficeBroadcast .v55-office-rep{
      padding:3px clamp(8px,.55vw,22px)!important;
    }
    #v55OfficeBroadcast .v55-office-name{
      font-size:clamp(17px,.95vw,38px)!important;
      line-height:1.05!important;
    }
    #v55OfficeBroadcast .champion .v55-office-name{
      font-size:clamp(19px,1.04vw,42px)!important;
    }
    #v55OfficeBroadcast .v55-office-team{
      gap:clamp(5px,.28vw,12px)!important;
      font-size:clamp(9px,.46vw,18px)!important;
      letter-spacing:.055em!important;
    }
    #v55OfficeBroadcast .v55-office-team-logo{
      width:clamp(22px,1.35vw,54px)!important;
      height:clamp(20px,1.20vw,48px)!important;
    }
    #v55OfficeBroadcast .v55-office-stat{
      font-size:clamp(11px,.62vw,25px)!important;
      padding:0 clamp(2px,.15vw,6px)!important;
    }
    #v55OfficeBroadcast .v55-office-footer{
      height:clamp(52px,5vh,104px)!important;
      margin-top:clamp(3px,.3vh,7px)!important;
    }
    #v55OfficeBroadcast .v55-office-total-v{
      font-size:clamp(11px,.62vw,25px)!important;
    }
    #v55OfficeBroadcast .v55-office-total-l{
      font-size:clamp(7px,.40vw,16px)!important;
      letter-spacing:.065em!important;
    }
    #v55OfficeBroadcast .v55-office-corner{
      width:clamp(72px,7vw,270px)!important;
    }
  `;
  document.head.appendChild(style);
})();
