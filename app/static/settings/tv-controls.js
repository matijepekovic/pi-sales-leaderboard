/* Controls settings owns operational TV actions only. */
(function(){
  const $=id=>document.getElementById(id);
  const status=text=>{if($("tvControlStatus"))$("tvControlStatus").textContent=text||"";};

  async function post(path){
    const response=await fetch(path,{method:"POST",cache:"no-store"});
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false)throw new Error(data.error||`Request failed (${response.status})`);
    return data;
  }

  async function refreshTV(){
    const button=$("refreshTV");button.disabled=true;status("Refreshing TV…");
    try{await post("/api/tv/refresh");status("TV refresh sent.");}
    catch(err){status(err.message||"Refresh failed.");}
    finally{button.disabled=false;}
  }

  async function fullscreen(){
    const button=$("fullscreenTV");button.disabled=true;status("Relaunching fullscreen TV…");
    try{await post("/api/tv/fullscreen");status("TV is relaunching in fullscreen mode.");}
    catch(err){status(err.message||"Fullscreen failed.");}
    finally{setTimeout(()=>{button.disabled=false;},2500);}
  }

  async function restart(){
    if(!confirm("Restart Stats?"))return;
    const button=$("restartTV");button.disabled=true;status("Restart command sent…");
    try{await fetch("/api/tv/restart",{method:"POST"});}catch(_){ }
    let sawOffline=false;
    for(let i=0;i<60;i++){
      await new Promise(resolve=>setTimeout(resolve,1000));
      try{
        const response=await fetch(`/health?ts=${Date.now()}`,{cache:"no-store"});
        if(response.ok&&(sawOffline||i>3)){status("Stats restarted.");button.disabled=false;return;}
      }catch(_){sawOffline=true;status("Stats offline… waiting…");}
    }
    status("Restart requested, but Stats did not return within 60 seconds.");button.disabled=false;
  }

  function bind(){
    $("refreshTV")?.addEventListener("click",refreshTV);
    $("fullscreenTV")?.addEventListener("click",fullscreen);
    $("restartTV")?.addEventListener("click",restart);
    $("openTV")?.addEventListener("click",()=>window.open("/","_blank"));
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",bind,{once:true});else bind();
})();
