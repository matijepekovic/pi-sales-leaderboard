/* v128 Windows OTA recovery/status note.
   A failed detached install must never disappear without telling the user what
   happened after Stats reopens. The helper writes a small persistent result;
   this layer shows only the latest failure in the Software card. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  const $=id=>document.getElementById(id);
  function card(){
    return $("v107SoftwareManual")?.closest(".card,.v98-inner-card")||null;
  }
  function ensureNote(){
    const host=card();if(!host)return null;
    let note=$("v128UpdateStatus");
    if(note)return note;
    note=document.createElement("div");
    note.id="v128UpdateStatus";
    note.style.cssText="display:none;flex:1 1 100%;margin-top:8px;padding:9px 11px;border:1px solid #744;border-radius:7px;background:#211;color:#f2c4c4;font-size:12px;line-height:1.35";
    $("v107SoftwareManual")?.insertAdjacentElement("afterend",note);
    return note;
  }
  async function refresh(){
    const note=ensureNote();if(!note)return false;
    try{
      const response=await fetch("/api/windows/update/status",{cache:"no-store"});
      const data=await response.json();
      const status=data?.status;
      if(!response.ok||!data?.ok||!status||status.state!=="failed"){
        note.style.display="none";return true;
      }
      const version=status.version?` ${status.version}`:"";
      const code=status.exit_code!==undefined&&status.exit_code!==null?` (code ${status.exit_code})`:"";
      note.textContent=`Last update${version} failed${code}. Stats reopened on the previous version. You can try Update again.`;
      note.style.display="block";
      return true;
    }catch(_){return true;}
  }
  function boot(){
    let tries=0;(function attempt(){
      if(card()){refresh();return;}
      if(++tries<120)setTimeout(attempt,50);
    })();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
