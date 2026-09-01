/* Security Settings owns PIN changes; the shell owns the lock gate. */
(function(){
  const runtime=window.StatsSettings,$=id=>document.getElementById(id);
  async function savePin(){const button=$("savePin"),status=$("pinStatus");button.disabled=true;status.textContent="Saving…";try{const data=await runtime.api("/api/auth/pin",runtime.json("POST",{current_pin:String($("pinCurrent")?.value||"").trim(),new_pin:String($("pinNew")?.value||"").trim()}));$("pinCurrent").value="";$("pinNew").value="";status.textContent=data.pin_set?"PIN saved.":"PIN removed.";}catch(error){status.textContent=error.message;}finally{button.disabled=false;}}
  async function lockNow(){try{await fetch("/api/auth/lock",{method:"POST"});}catch(_){ }document.dispatchEvent(new CustomEvent("stats:settings-locked"));location.reload();}
  function bind(){$("savePin")?.addEventListener("click",savePin);$("lockNow")?.addEventListener("click",lockNow);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",bind,{once:true});else bind();
})();
