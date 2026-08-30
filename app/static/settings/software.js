/* Software -- version, update actions, and updater diagnostics.

   Consolidated from the settings patch stack. Each section below was its own
   file and they are concatenated in their original load order, so what runs
   when is unchanged -- several of these mount by polling for a node the
   previous one creates. */


/* ------------------------------------------------------------------
   software-manual.js
   ------------------------------------------------------------------ */
/* Software stays user-controlled: Check for Updates + Update.
   On the packaged Windows build, both actions go through the signed public
   installer update API. Download, signature/hash verification, silent install,
   shutdown, and relaunch happen automatically after Update is pressed. */
(function(){
  const $=id=>document.getElementById(id);
  let remoteVersion=null;

  async function forceManualOnly(){
    const legacy=$('githubAutoUpdate');
    if(legacy) legacy.checked=false;
    try{
      if(typeof config==='object'&&config) config.github_auto_update=false;
    }catch(_){ }
    try{
      await fetch('/api/config',{
        method:'PUT',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({github_auto_update:false})
      });
    }catch(_){ }
  }

  function softwareCard(){
    const anchor=$('softwareVersion')||$('checkGithub')||$('updateFile');
    if(!anchor) return null;
    return anchor.closest('.card,.v98-inner-card');
  }

  async function waitForRestart(button){
    button.textContent='Installing…';
    let sawOffline=false;
    for(let i=0;i<100;i++){
      await new Promise(resolve=>setTimeout(resolve,1200));
      try{
        const r=await fetch('/health?ts='+Date.now(),{cache:'no-store'});
        if(r.ok&&(sawOffline||i>8)){
          location.reload();
          return;
        }
      }catch(_){
        sawOffline=true;
      }
    }
    button.textContent='Update';
    button.disabled=false;
  }

  function install(){
    const card=softwareCard();
    if(!card) return false;
    if($('v107SoftwareManual')) return true;

    Array.from(card.children).forEach(child=>{
      if(child.tagName!=='H2') child.style.display='none';
    });

    const box=document.createElement('div');
    box.id='v107SoftwareManual';
    box.style.display='flex';
    box.style.gap='10px';
    box.style.flexWrap='wrap';
    box.innerHTML=`
      <button id="v107CheckUpdate" class="btn" type="button">Check for Updates</button>
      <button id="v107InstallUpdate" class="btn primary" type="button" disabled>Update</button>`;
    card.appendChild(box);

    const check=$('v107CheckUpdate');
    const update=$('v107InstallUpdate');

    check.addEventListener('click',async()=>{
      remoteVersion=null;
      check.disabled=true;
      update.disabled=true;
      check.textContent='Checking…';
      try{
        const r=await fetch('/api/windows/update/check',{
          method:'POST',
          cache:'no-store'
        });
        const d=await r.json();
        if(!r.ok||!d.ok) throw new Error(d.error||'check failed');
        if(d.available){
          remoteVersion=String(d.latest||'');
          check.textContent='Update Available';
          update.disabled=false;
        }else{
          check.textContent='Up to Date';
          setTimeout(()=>{check.textContent='Check for Updates';},1600);
        }
      }catch(_){
        check.textContent='Check Failed';
        setTimeout(()=>{check.textContent='Check for Updates';},1800);
      }finally{
        check.disabled=false;
      }
    });

    update.addEventListener('click',async()=>{
      if(!remoteVersion) return;
      check.disabled=true;
      update.disabled=true;
      update.textContent='Downloading…';
      try{
        const r=await fetch('/api/windows/update/install',{
          method:'POST',
          cache:'no-store'
        });
        const d=await r.json();
        if(!r.ok||!d.ok) throw new Error(d.error||'update failed');
        if(d.installed||d.installing){
          await waitForRestart(update);
          return;
        }
        remoteVersion=null;
        update.textContent='Update';
        update.disabled=true;
        check.textContent='Up to Date';
        setTimeout(()=>{check.textContent='Check for Updates';},1600);
      }catch(_){
        update.textContent='Update Failed';
        setTimeout(()=>{
          update.textContent='Update';
          update.disabled=!remoteVersion;
          check.disabled=false;
        },1800);
      }
    });

    forceManualOnly();
    setTimeout(forceManualOnly,500);
    setTimeout(forceManualOnly,1500);
    setTimeout(forceManualOnly,3000);
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(install()) return;
      if(++tries<80) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();


/* ------------------------------------------------------------------
   software-update-status.js
   ------------------------------------------------------------------ */
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


/* ------------------------------------------------------------------
   software-version.js
   ------------------------------------------------------------------ */
/* Windows Software version display.
   Kept separate from updater controls so version identity remains a small,
   reusable Software component when the settings frontend is restructured. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  function softwareCard(){
    const anchor=document.getElementById("v107SoftwareManual")
      ||document.getElementById("softwareVersion")
      ||document.getElementById("checkGithub");
    return anchor?.closest(".card,.v98-inner-card")||null;
  }

  function install(){
    const card=softwareCard();
    if(!card)return false;
    if(document.getElementById("softwareVersionCurrent"))return true;

    const row=document.createElement("div");
    row.id="softwareVersionCurrent";
    row.style.cssText="margin:0 0 12px;font-weight:900";
    row.textContent="Software version: checking…";
    const heading=card.querySelector("h2");
    if(heading)heading.insertAdjacentElement("afterend",row);
    else card.prepend(row);

    fetch("/api/system/version",{cache:"no-store"})
      .then(r=>r.json().then(d=>({r,d})))
      .then(({r,d})=>{
        if(!r.ok||!d?.ok)throw new Error(d?.error||"version unavailable");
        row.textContent=`Software version: ${String(d.version||"unknown")}`;
      })
      .catch(()=>{row.textContent="Software version: unavailable";});
    return true;
  }

  let tries=0;(function attempt(){
    if(install())return;
    if(++tries<120)setTimeout(attempt,50);
  })();
})();


/* ------------------------------------------------------------------
   software-update-diagnostics.js
   ------------------------------------------------------------------ */
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
