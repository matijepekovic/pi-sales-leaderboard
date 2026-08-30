/* v127 color semantics for team themes.
   The stored color model already contains these values; this layer makes the
   previously weak/unused dark and panel colors visibly meaningful without
   changing theme data or the leaderboard renderer. */
(function(){
  const STYLE_ID="themeColorRuntimeV127Styles";
  if(document.getElementById(STYLE_ID))return;
  const style=document.createElement("style");
  style.id=STYLE_ID;
  style.textContent=`
    #themedTeamBroadcast .bt-frame{
      box-shadow:
        inset 0 0 0 1px #000,
        inset 0 0 0 5px color-mix(in srgb,var(--bt-primary) 35%,transparent),
        inset 0 0 72px color-mix(in srgb,var(--bt-dark) 58%,black),
        0 0 28px color-mix(in srgb,var(--bt-secondary) 22%,transparent)!important
    }
    #themedTeamBroadcast .bt-head{
      background:color-mix(in srgb,var(--bt-panel) 90%,black)!important
    }
    #themedTeamBroadcast .bt-row{
      background-color:var(--bt-panel)!important
    }
    #themedTeamBroadcast .bt-row:before{
      background:color-mix(in srgb,var(--bt-panel) 48%,rgba(4,4,3,.56))
    }
    #themedTeamBroadcast .champion:before{
      background:color-mix(in srgb,var(--bt-dark) 34%,transparent)!important
    }
    #themedTeamBroadcast .bt-footer{
      background:color-mix(in srgb,var(--bt-panel) 82%,black)!important
    }
    body.team-theme-full .theme-frame{
      box-shadow:
        inset 0 0 0 1px #000,
        inset 0 0 0 5px color-mix(in srgb,var(--theme-primary) 32%,transparent),
        inset 0 0 70px color-mix(in srgb,var(--theme-primary-dark) 55%,black),
        0 0 26px color-mix(in srgb,var(--theme-secondary) 20%,transparent)!important
    }
    body.team-theme-full tbody tr.theme-standard-row td{
      background-color:var(--theme-panel)!important
    }
    body.team-theme-full .total-row td{
      background:color-mix(in srgb,var(--theme-panel) 88%,black)!important
    }
  `;
  Display.placeStyle(160, style);
})();
