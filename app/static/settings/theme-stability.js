/* v126 Windows Theme Builder stability/policy hints.
   Preview data selection happens inside the iframe. This host-side layer keeps
   the desktop controls simple and avoids exposing the old fake-sample cycler. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform)) return;

  function addStyles(){
    if(document.getElementById("windowsThemeStabilityV126Styles"))return;
    const style=document.createElement("style");
    style.id="windowsThemeStabilityV126Styles";
    style.textContent=`
      #teamDesignOverlay #tdNewSample{display:none!important}
      #teamDesignOverlay #tdPreviewPolicyV126{
        color:#9a9a9a;font-size:10px;line-height:1.25;margin-top:3px;
        max-width:280px;white-space:normal
      }
    `;
    document.head.appendChild(style);
  }

  function installNote(){
    const sub=document.querySelector("#teamDesignOverlay .td-who-sub");
    if(!sub)return false;
    if(document.getElementById("tdPreviewPolicyV126"))return true;
    const note=document.createElement("div");
    note.id="tdPreviewPolicyV126";
    note.textContent="Real team stats are used when members exist. Empty teams use a mock design preview.";
    sub.insertAdjacentElement("afterend",note);
    return true;
  }

  function boot(){
    addStyles();
    let tries=0;
    (function attempt(){
      if(installNote())return;
      if(++tries<120)setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
