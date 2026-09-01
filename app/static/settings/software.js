/* Software settings owns version identity and signed Windows updates. */
(function(){
  const $=id=>document.getElementById(id);
  let remoteVersion="";

  async function json(url,options={}){
    const response=await fetch(url,{cache:"no-store",...options});
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false)throw new Error(data.error||`Request failed (${response.status})`);
    return data;
  }

  function status(text){if($("softwareUpdateStatus"))$("softwareUpdateStatus").textContent=text||"";}

  async function loadVersion(){
    try{
      const data=await json("/api/system/version");
      $("softwareVersionCurrent").textContent=`Software version: ${String(data.version||"unknown")}`;
    }catch(_){$("softwareVersionCurrent").textContent="Software version: unavailable";}
  }

  async function check(){
    const button=$("softwareCheckUpdate"),update=$("softwareInstallUpdate");
    button.disabled=true;update.disabled=true;remoteVersion="";status("Checking for updates…");
    try{
      const data=await json("/api/windows/update/check",{method:"POST"});
      if(data.available){
        remoteVersion=String(data.latest||"");
        status(remoteVersion?`Stats ${remoteVersion} is available.`:"Update available.");
        update.disabled=false;
      }else status("Stats is up to date.");
    }catch(err){status(err.message||"Update check failed.");}
    finally{button.disabled=false;}
  }

  async function waitForRestart(){
    status("Installing update…");let sawOffline=false;
    for(let i=0;i<100;i++){
      await new Promise(resolve=>setTimeout(resolve,1200));
      try{
        const response=await fetch(`/health?ts=${Date.now()}`,{cache:"no-store"});
        if(response.ok&&(sawOffline||i>8)){location.reload();return true;}
      }catch(_){sawOffline=true;}
    }
    return false;
  }

  async function install(){
    if(!remoteVersion)return;
    const checkButton=$("softwareCheckUpdate"),button=$("softwareInstallUpdate");
    checkButton.disabled=true;button.disabled=true;status(`Downloading Stats ${remoteVersion}…`);
    try{
      const data=await json("/api/windows/update/install",{method:"POST"});
      if(data.installed||data.installing){
        if(await waitForRestart())return;
        status("Install started, but Stats did not return yet.");
      }else{
        remoteVersion="";status("Stats is up to date.");
      }
    }catch(err){status(err.message||"Update failed.");}
    finally{checkButton.disabled=false;button.disabled=!remoteVersion;}
  }

  function bind(){
    $("softwareCheckUpdate")?.addEventListener("click",check);
    $("softwareInstallUpdate")?.addEventListener("click",install);
    loadVersion();
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",bind,{once:true});else bind();
})();
