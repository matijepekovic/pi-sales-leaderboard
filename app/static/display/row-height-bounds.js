/* v71 bounded adaptive row heights.
   Presentation only. Renderers may still choose an adaptive row size, but the
   TV clamps that size to proven readable ranges instead of stretching rows to
   consume every available pixel or shrinking them into unreadable slivers. */
(function(){
  const style=document.createElement("style");
  style.id="rowHeightBoundsV71";
  style.textContent=`
    /* Individual team: restore the pre-v69 readable bounds. */
    #themedTeamBroadcast .bt-board{
      justify-content:flex-start!important;
    }
    #themedTeamBroadcast .bt-row{
      min-height:44px!important;
      max-height:82px!important;
    }
    #themedTeamBroadcast .bt-row.champion{
      min-height:58px!important;
      max-height:100px!important;
    }
    #themedTeamBroadcast .bt-row.team-lead{
      min-height:44px!important;
      max-height:82px!important;
    }

    /* Whole Office: keep the v69 computed height, but only inside the old
       high-resolution working range. Extra room stays below the table. */
    #v55OfficeBroadcast .v55-office-row{
      height:clamp(38px,var(--v55-office-row-h,42px),82px)!important;
      min-height:38px!important;
      max-height:82px!important;
    }
    #v55OfficeBroadcast .v55-office-row.champion{
      height:clamp(48px,calc(var(--v55-office-row-h,42px) * 1.18),98px)!important;
      min-height:48px!important;
      max-height:98px!important;
    }

    /* Stacked comparison boards need the denser pre-v69 safe range because
       more than one full-width team can share the same 1080p screen. */
    .v69-team-card .v69-rows{
      justify-content:flex-start!important;
    }
    .v69-team-card .v69-row{
      min-height:31px!important;
      max-height:67px!important;
    }
    .v69-team-card .v69-row.champion{
      min-height:38px!important;
      max-height:78px!important;
    }
  `;
  document.head.appendChild(style);
})();
