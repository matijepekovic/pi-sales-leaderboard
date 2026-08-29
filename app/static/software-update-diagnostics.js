/* Windows update diagnostics UI.
   Owns only the diagnostics surface. Updater actions stay in software-manual-v107.js. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  function softwareCard(){
    const anchor=document.getElementById("v107SoftwareManual")
      ||document.getElementById("softwareVersionCurrent")
      ||document.getElementById("softwareVersion");
    return anchor?.closest(".card,.v98-inner-card")||null;
  }

  function formatResult(data){
    const lines=[];
    lines.push(`Installed version: ${data?.installed_version||"unknown"}`);
    const env=data?.environment||{};
    lines.push(`Packaged build: ${env.packaged?"yes":"no"}`);
    lines.push(`TLS: ${env.openssl||"unknown"}`);
    lines.push(`Default CA file available: ${env.default_cafile_available?"yes":"no"}`);
    lines.push(`Default CA path available: ${env.default_capath_available?"yes":"no"}`);
    lines.push("");
    lines.push("Update checks:");
    (data?.checks||[]).forEach(item=>{
      const mark=item.ok?"PASS":"FAIL";
      const detail=item.ok?(item.detail||"OK"):(item.error||"Unknown error");
      lines.push(`${mark} — ${item.name}: ${detail}`);
    });
    return lines.join("\n");
  }

  function install(){
    const card=softwareCard();
    if(!card)return false;
    if(document.getElementById("softwareUpdateDiagnostics"))return true;

    const box=document.createElement("div");
    box.id="softwareUpdateDiagnostics";
    box.style.cssText="margin-top:12px;padding-top:12px;border-top:1px solid #303030";
    box.innerHTML=`
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button id="runUpdateDiagnostics" class="btn" type="button">Run Update Diagnostics</button>
        <button id="copyUpdateDiagnostics" class="btn" type="button" style="display:none">Copy Results</button>
      </div>
      <pre id="updateDiagnosticsResult" style="display:none;margin:10px 0 0;padding:10px;white-space:pre-wrap;overflow-wrap:anywhere;background:#0b0b0b;border:1px solid #303030;color:#ddd;font-size:12px;line-height:1.4"></pre>`;
    card.appendChild(box);

    const run=document.getElementById("runUpdateDiagnostics");
    const copy=document.getElementById("copyUpdateDiagnostics");
    const result=document.getElementById("updateDiagnosticsResult");

    run.addEventListener("click",async()=>{
      run.disabled=true;
      run.textContent="Running Diagnostics…";
      copy.style.display="none";
      result.style.display="block";
      result.textContent="Checking updater stages…";
      try{
        const response=await fetch("/api/windows/update/diagnostics",{cache:"no-store"});
        const data=await response.json().catch(()=>({}));
        if(!response.ok)throw new Error(data.error||`Diagnostic request failed (${response.status})`);
        result.textContent=formatResult(data);
        copy.style.display="inline-block";
      }catch(err){
        result.textContent=`Diagnostics request failed: ${err?.message||err}`;
      }finally{
        run.disabled=false;
        run.textContent="Run Update Diagnostics";
      }
    });

    copy.addEventListener("click",async()=>{
      try{
        await navigator.clipboard.writeText(result.textContent||"");
        copy.textContent="Copied";
        setTimeout(()=>{copy.textContent="Copy Results";},1200);
      }catch(_){
        copy.textContent="Copy Failed";
        setTimeout(()=>{copy.textContent="Copy Results";},1200);
      }
    });
    return true;
  }

  let tries=0;(function attempt(){
    if(install())return;
    if(++tries<120)setTimeout(attempt,50);
  })();
})();
