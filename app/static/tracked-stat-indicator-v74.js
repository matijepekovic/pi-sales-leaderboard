/* v74 tracked-stat indicator.
   Presentation only. Single Team already marks the champion's active sort
   metric with a glowing underline; apply the same treatment to Whole Office,
   Team vs Team, and All Teams. */
(function(){
  const style=document.createElement("style");
  style.id="trackedStatIndicatorV74";
  style.textContent=`
    #v55OfficeBroadcast .v55-office-row.champion .v55-office-stat.primary,
    .v69-team-card .v69-row.champion .v69-stat.primary{
      position:relative!important;
    }

    #v55OfficeBroadcast .v55-office-row.champion .v55-office-stat.primary:after{
      content:"";
      position:absolute;
      left:16%;
      right:16%;
      bottom:18%;
      height:2px;
      background:linear-gradient(90deg,transparent,var(--v55-bright),transparent);
      box-shadow:0 0 8px color-mix(in srgb,var(--v55-bright) 85%,transparent);
      pointer-events:none;
    }

    .v69-team-card .v69-row.champion .v69-stat.primary:after{
      content:"";
      position:absolute;
      left:16%;
      right:16%;
      bottom:18%;
      height:2px;
      background:linear-gradient(90deg,transparent,var(--v69-bright),transparent);
      box-shadow:0 0 8px color-mix(in srgb,var(--v69-bright) 85%,transparent);
      pointer-events:none;
    }
  `;
  document.head.appendChild(style);
})();
